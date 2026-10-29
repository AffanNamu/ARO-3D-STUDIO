"""The bake-off script's parsing and reporting (the engine runs themselves need a GPU worker; see tests/test_remote_engine.py)."""

from __future__ import annotations

import importlib.util
import io
import json
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from PIL import Image

from aro_worker.app import create_app as create_worker
from aro_worker.engines.fake import FakeEngine

SPEC = importlib.util.spec_from_file_location(
    "engine_bakeoff", Path(__file__).resolve().parents[1] / "scripts" / "engine_bakeoff.py"
)
assert SPEC and SPEC.loader
bakeoff = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bakeoff)


@pytest.mark.parametrize(
    "text, image, category, length",
    [
        ("truck.png:heavy_truck:7.0", "truck.png", "heavy_truck", 7.0),
        ("truck.png:heavy_truck", "truck.png", "heavy_truck", None),
        ("ARO 480 Truck at Golden Hour.png:heavy_truck:6.5", "ARO 480 Truck at Golden Hour.png", "heavy_truck", 6.5),
        ("C:\\imgs\\suv.png:car:4.5", "C:\\imgs\\suv.png", "car", 4.5),
    ],
)
def test_case_parsing(text, image, category, length):
    assert bakeoff.parse_case(text) == (Path(image), category, length)


def test_case_without_a_category_is_refused():
    with pytest.raises(SystemExit):
        bakeoff.parse_case("truck.png")


def test_summary_table_never_hides_a_failure():
    rows = [
        {"engine": "trellis2", "image": "a.png", "status": "FAIL", "reason": "GPU out of memory"},
        {"engine": "triposg", "image": "a.png", "status": "BLOCKED", "reason": "licence not verified"},
        {
            "engine": "trellis2",
            "image": "b.png",
            "status": "PASS",
            "ratios": {"width_over_length": 0.4, "height_over_length": 0.35},
            "silhouette_iou": 0.9,
            "proportions": "plausible",
            "meets_floor": True,
            "prepared_triangles": 30000,
            "prepared_components": 1,
            "validation": "NEEDS_REVIEW",
            "total_seconds": 90.0,
        },
    ]
    md = bakeoff.markdown(rows)
    assert "**FAIL**" in md and "GPU out of memory" in md and "**BLOCKED**" in md and "PENDING human review" in md
    assert (
        "| trellis2 | b.png | **PASS** | 0.90 | 0.40 | 0.35 | plausible | yes | 30000 | 1 | NEEDS_REVIEW | 90.0 |" in md
    )


class Response:
    """What describe_http_error needs from an HTTP response."""

    def __init__(self, status_code: int, body=None, text: str = ""):
        self.status_code, self._body, self.text = status_code, body, text

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


def test_the_studios_structured_refusal_is_described_not_sliced():
    """REGRESSION (Colab, 2026-10-27): the error field is a dict; slicing it as text raised KeyError and hid the real reason."""
    err = {"code": "ENGINE_UNAVAILABLE", "message": "licence not verified", "recommended_action": "read the model card"}
    d = bakeoff.describe_http_error(Response(409, {"error": err}))
    assert d == {"http_status": 409, **err}
    text = bakeoff.reason_text(d)
    assert "HTTP 409 ENGINE_UNAVAILABLE" in text and "licence not verified" in text and "read the model card" in text


@pytest.mark.parametrize(
    "response, expected",
    [
        (Response(400, {"error": "plain string"}), "plain string"),
        (Response(422, {"detail": "field required"}), "field required"),
        (Response(422, {"detail": [{"loc": ["body", "file"], "msg": "field required"}]}), "field required"),
        (Response(502, None, text="<html>Bad gateway</html>"), "Bad gateway"),
        (Response(500, {"unexpected": 1}), "unexpected"),
    ],
)
def test_any_error_body_becomes_text_instead_of_crashing(response, expected):
    d = bakeoff.describe_http_error(response)
    assert d["http_status"] == response.status_code and expected in d["message"]
    assert len(bakeoff.reason_text(d)) < 1500


def serve(app):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    end = time.time() + 10
    while not server.started and time.time() < end:
        time.sleep(0.05)
    assert server.started
    return f"http://127.0.0.1:{port}", server, t


def test_run_one_reports_a_licence_refusal_as_blocked_with_the_reason(tmp_path, capsys):
    """The path the Colab user hit: the licence gate refuses before any inference. It must come back as a BLOCKED row that says why."""
    token = "t" * 24
    app = create_worker(
        [FakeEngine()], token, workdir=tmp_path / "w"
    )  # labelled test double, never counted as an engine result
    url, server, thread = serve(app)
    try:
        image = tmp_path / "truck.png"
        im = Image.new("RGBA", (96, 64), (200, 40, 40, 255))
        im.paste((0, 0, 0, 0), (0, 0, 20, 64))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        image.write_bytes(buf.getvalue())
        row = bakeoff.run_one(url, token, "fake", image, "heavy_truck", None, "DRAFT", "", 60, tmp_path / "out", {})
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        app.state.shutdown()
    assert row["status"] == "BLOCKED"
    assert (
        "has not been verified by the deployer" in row["reason"]
        and "ARO_VERIFIED_MODEL_LICENSES=fake" in row["error"]["recommended_action"]
    )
    assert "I_HAVE_READ_THE_MODEL_CARDS" in row["hint"]
    assert "BLOCKED before any inference" in capsys.readouterr().out
    json.dumps(row)  # the row goes into bakeoff-summary.json
    md = bakeoff.markdown([row])
    assert "**BLOCKED**" in md and "has not been verified" in md


def interrupted_run(tmp_path, monkeypatch, capsys, slow_step_s: float = 0.0):
    """Colab, 2026-10-29: SIGINT arrived at 97 % ("Exporting fbx"); the working folder was deleted and the GPU run was lost. The raw mesh
    must be copied out first, and the row must say the run was interrupted, not that the engine failed."""
    import glob
    import hashlib
    import tempfile

    token = "t" * 24
    app = create_worker([FakeEngine()], token, workdir=tmp_path / "w")  # labelled test double
    url, server, thread = serve(app)

    private_tmp = (
        tmp_path / "private-tmp"
    )  # this test's own temp root: nothing from another test can trigger or fail it
    private_tmp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(private_tmp))
    fired = {"done": False}
    in_step = {"now": False}
    if slow_step_s:  # the Studio's job is still mid-flight (inside a preparation step) when the interrupt arrives
        from aro_studio.processing.service import ProcessingService

        original_run = ProcessingService.run

        def slow_run(self, *args, **kwargs):
            if not fired["done"]:
                return original_run(self, *args, **kwargs)
            in_step["now"] = True
            try:
                time.sleep(slow_step_s)
                return original_run(self, *args, **kwargs)
            finally:
                in_step["now"] = False

        monkeypatch.setattr(ProcessingService, "run", slow_run)

    class Clock:
        time = staticmethod(time.time)

        @staticmethod
        def sleep(seconds: float) -> None:
            time.sleep(0.05)
            raw_exists = glob.glob(
                str(Path(tempfile.gettempdir()) / "aro_bakeoff_*" / "**" / "raw_output.glb"), recursive=True
            )
            if raw_exists and not fired["done"]:
                fired["done"] = True
                raise KeyboardInterrupt  # the engine's mesh exists, the Studio is still preparing it; now the cell is "interrupted"

    monkeypatch.setattr(bakeoff, "time", Clock)
    try:
        image = tmp_path / "truck.png"
        im = Image.new("RGBA", (96, 64), (200, 40, 40, 255))
        im.paste((0, 0, 0, 0), (0, 0, 20, 64))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        image.write_bytes(buf.getvalue())
        out = tmp_path / "out"
        row = bakeoff.run_one(url, token, "fake", image, "heavy_truck", None, "STANDARD", "fake", 120, out, {})
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        app.state.shutdown()
    assert row["status"] == "FAIL" and row["interrupted"] is True
    assert "INTERRUPTED" in row["reason"] and "not an engine fault" in row["reason"]
    raw = out / "raw_output.glb"
    assert raw.exists() and row["raw_rescued"] is True
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == row["raw_sha256"]
    # no preparation step may still be running once the working folder has been deleted
    assert not in_step["now"], "run_one returned while a Studio job step was still running"
    # the Studio's job is cancelled and has ENDED before the folder is deleted (CI run 72: it kept writing into a half-deleted folder)
    assert row["job_state_after_interrupt"] in bakeoff.TERMINAL
    assert not glob.glob(str(Path(tempfile.gettempdir()) / "aro_bakeoff_*"))  # the working folder is still cleaned up
    assert "raw mesh kept" in capsys.readouterr().out


def test_an_interrupted_run_keeps_the_raw_mesh_and_says_it_was_interrupted(tmp_path, monkeypatch, capsys):
    interrupted_run(tmp_path, monkeypatch, capsys)


def test_an_interrupted_run_waits_for_the_studio_job_before_deleting_its_folder(tmp_path, monkeypatch, capsys):
    """REGRESSION (CI run 72): ctx.close() waits only 5 s for the job thread. A step that outlives that kept writing into the folder being
    deleted and left a half-deleted /tmp/aro_bakeoff_* behind. The job is now cancelled and awaited first."""
    interrupted_run(tmp_path, monkeypatch, capsys, slow_step_s=8.0)
