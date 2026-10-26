"""The GPU-worker protocol and the Studio's RemoteEngine, tested end to end WITHOUT a GPU.

The worker engine here is the procedural ``FakeEngine`` (labelled NOT AI in its own name and in every result): these tests prove the
protocol, authentication, queueing, cancellation, checksum verification, failure reporting and the Studio integration - not model
quality. TRELLIS.2 / TripoSG themselves need a 24 GB-class GPU and are covered by docs/architecture/gpu-worker.md plus the evidence
recorded from a real run.
"""

from __future__ import annotations

import io
import threading
import time

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import SecretStr

from aro_studio.app_context import build_context
from aro_studio.config import Settings
from aro_studio.core.cancellation import CancellationToken
from aro_studio.core.errors import EngineUnavailableError, InvalidInputError, JobCancelledError, ModelError
from aro_studio.engines.base import GenerationRequest
from aro_studio.engines.registry import license_gate
from aro_studio.engines.remote import KNOWN, RemoteEngine
from aro_worker.app import create_app as create_worker
from aro_worker.engines.base import require_cutout
from aro_worker.engines.fake import FakeEngine
from tests.test_api_integration import make_client, wait

pytestmark = pytest.mark.filterwarnings(
    "ignore:.*timeout.*TestClient.*"
)  # RemoteEngine pings with its own short timeout

TOKEN = "t" * 24
BASE = "http://worker.test"


def png(alpha: bool = True, size=(96, 64)) -> bytes:
    im = Image.new("RGBA", size, (200, 40, 40, 255))
    if alpha:
        im.paste((0, 0, 0, 0), (0, 0, 20, size[1]))  # a transparent strip = a cut-out
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


class BoomEngine(FakeEngine):
    id = "fake"

    def generate(self, image, settings, progress, cancelled):
        raise RuntimeError("CUDA out of memory. Tried to allocate 3.00 GiB")


@pytest.fixture
def worker(tmp_path):
    app = create_worker([FakeEngine()], TOKEN, workdir=tmp_path / "w")
    yield TestClient(app, base_url=BASE)
    app.state.shutdown()


def auth(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


def finish(c: TestClient, jid: str, timeout=20.0) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        j = c.get(f"/v1/jobs/{jid}", headers=auth()).json()
        if j["state"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(0.02)
    raise AssertionError("worker job did not finish")


def submit(c: TestClient, data: bytes | None = None, engine="fake", settings="{}"):
    return c.post(
        "/v1/generate",
        headers=auth(),
        files={"image": ("in.png", data if data is not None else png(), "image/png")},
        data={"engine": engine, "settings": settings},
    )


# ---- worker -----------------------------------------------------------------------------------
def test_worker_needs_a_real_token():
    with pytest.raises(ValueError, match="16 characters"):
        create_worker([FakeEngine()], "short")


def test_worker_ping_is_open_everything_else_needs_the_token(worker):
    assert worker.get("/ping").json() == {"ok": True, "protocol": 1}
    assert worker.get("/v1/engines").status_code == 401
    assert worker.get("/v1/engines", headers=auth("x" * 24)).status_code == 401
    assert submit(worker).status_code == 202
    assert (
        worker.post("/v1/generate", files={"image": ("a.png", png(), "image/png")}, data={"engine": "fake"}).status_code
        == 401
    )
    assert worker.get("/v1/jobs/nope", headers=auth("x" * 24)).status_code == 401


def test_worker_job_runs_and_serves_a_checksummed_glb(worker):
    jid = submit(worker, settings='{"target_faces": 500}').json()["job_id"]
    j = finish(worker, jid)
    assert j["state"] == "done" and j["details"]["test_double"] is True and j["details"]["engine_version"] == "fake-1"
    r = worker.get(f"/v1/jobs/{jid}/result", headers=auth())
    assert r.status_code == 200 and r.content[:4] == b"glTF"
    import hashlib

    assert r.headers["X-ARO-SHA256"] == hashlib.sha256(r.content).hexdigest() == j["sha256"]


def test_worker_rejects_bad_requests_before_queueing(worker):
    assert submit(worker, engine="nope").status_code == 404
    assert submit(worker, data=b"not an image").status_code == 422
    assert submit(worker, settings="[1]").status_code == 422
    assert worker.get("/v1/jobs/unknown", headers=auth()).status_code == 404
    jid = submit(worker).json()["job_id"]
    finish(worker, jid)
    assert worker.get(f"/v1/jobs/{jid}/result", headers=auth()).status_code == 200


def test_worker_refuses_a_huge_image_before_decoding_it(worker, monkeypatch):
    import aro_worker.app as wapp

    monkeypatch.setattr(wapp, "MAX_PIXELS", 1000)
    assert submit(worker, data=png(size=(64, 64))).status_code == 413  # 4096 px > 1000
    assert submit(worker, data=png(size=(20, 20))).status_code == 202


def test_worker_reports_engine_failures_verbatim_and_never_invents_geometry(tmp_path):
    app = create_worker([BoomEngine()], TOKEN, workdir=tmp_path / "w")
    c = TestClient(app, base_url=BASE)
    jid = submit(c).json()["job_id"]
    j = finish(c, jid)
    assert j["state"] == "failed" and "out of memory" in j["error"] and "larger GPU" in j["error"]
    assert c.get(f"/v1/jobs/{jid}/result", headers=auth()).status_code == 409  # nothing to download
    app.state.shutdown()


def test_worker_cancel_stops_a_running_job_between_stages(tmp_path):
    app = create_worker([FakeEngine(delay_s=0.2)], TOKEN, workdir=tmp_path / "w")
    c = TestClient(app, base_url=BASE)
    jid = submit(c).json()["job_id"]
    time.sleep(0.3)
    assert c.delete(f"/v1/jobs/{jid}", headers=auth()).status_code == 200
    assert finish(c, jid)["state"] == "cancelled"
    app.state.shutdown()


def test_real_engines_say_why_they_cannot_run_here_instead_of_pretending():
    from aro_worker.engines.trellis2 import Trellis2Engine
    from aro_worker.engines.triposg import TripoSGEngine

    for eng in (Trellis2Engine(), TripoSGEngine()):
        ok, reasons = eng.available()
        assert not ok and reasons  # this sandbox has no GPU / checkout: the reasons are concrete
        m = eng.manifest()
        assert m["available"] is False and m["reasons"] and m["license"]["spdx"] == "MIT"


def test_a_cutout_is_mandatory_so_no_non_commercial_matting_model_ever_runs():
    opaque = Image.open(io.BytesIO(png(alpha=False)))
    with pytest.raises(ValueError, match="no transparent background"):
        require_cutout(opaque)
    with pytest.raises(ValueError, match="empty"):
        require_cutout(Image.new("RGBA", (8, 8), (0, 0, 0, 0)))
    assert require_cutout(Image.open(io.BytesIO(png()))).mode == "RGBA"
    # a real cut-out whose subject fills its frame (almost nothing transparent) is padded, not rejected
    full = Image.new("RGBA", (200, 100), (10, 20, 30, 255))
    full.putpixel((0, 0), (0, 0, 0, 0))
    padded = require_cutout(full)
    assert padded.width > full.width and padded.height > full.height
    assert (np.asarray(padded.getchannel("A")) < 13).mean() > 0.01


# ---- Studio side: RemoteEngine ---------------------------------------------------------------
def remote(worker: TestClient, token=TOKEN, engine="fake", **kw) -> RemoteEngine:
    return RemoteEngine(BASE, token, engine, client=worker, poll_s=0.02, **kw)


def test_remote_engine_availability_gives_actionable_reasons(worker):
    assert remote(worker).availability("cuda").ok
    bad = remote(worker, token="x" * 24).availability("cuda")
    assert not bad.ok and "token" in " ".join(bad.reasons)
    missing = remote(worker, engine="trellis2").availability("cuda")
    assert not missing.ok and "does not offer 'trellis2'" in missing.reasons[0] and "['fake']" in missing.reasons[0]

    class Down(httpx.Client):
        def get(self, *a, **k):
            raise httpx.ConnectError("refused")

    down = RemoteEngine(BASE, TOKEN, "fake", client=Down()).availability("cuda")
    assert not down.ok and "not reachable" in down.reasons[0] and "ARO_WORKER_URL" in down.activation[0]


def test_remote_licence_comes_from_the_studio_table_never_from_the_worker(worker):
    e = remote(worker)
    assert e.info.license.status == "claimed" == KNOWN["fake"]["license"].status
    for name, k in KNOWN.items():
        assert k["license"].status != "verified", f"{name}: only a person who read the model card may verify"
    with pytest.raises(EngineUnavailableError, match="not yet verified"):
        license_gate(e, set())
    license_gate(e, {"fake"})


def test_remote_generation_returns_the_workers_glb_untouched(worker, tmp_path):
    e = remote(worker)
    img = Image.open(io.BytesIO(png()))
    steps: list[str] = []
    out = e.generate(
        GenerationRequest(
            img.convert("RGB"),
            {"preset": "STANDARD"},
            tmp_path / "gen",
            progress=lambda f, m: steps.append(m),
            cutout=img,
        )
    )
    assert out.output_format == "glb" and out.raw_file.read_bytes()[:4] == b"glTF"
    assert out.device.startswith("remote:") and len(out.mesh.faces) > 20
    assert out.details["engine_version"] == "fake-1" and out.details["worker_details"]["test_double"] is True
    assert any("GPU worker" in s for s in steps)
    assert e.info.version == "fake-1"  # adopts what the worker says actually ran


def test_remote_generation_detects_a_corrupted_transfer(worker, tmp_path):
    class Tamper(TestClient):
        def get(self, url, **kw):
            r = super().get(url, **kw)
            if str(url).endswith("/result"):
                r._content = r.content[:-1] + b"\x00"
            return r

    tampered = Tamper(worker.app, base_url=BASE)
    e = RemoteEngine(BASE, TOKEN, "fake", client=tampered, poll_s=0.02)
    img = Image.open(io.BytesIO(png()))
    with pytest.raises(ModelError, match="checksum"):
        e.generate(GenerationRequest(img.convert("RGB"), {}, tmp_path / "g", cutout=img))
    assert not (tmp_path / "g" / "raw_output.glb").exists()  # a corrupted GLB is never kept as the engine's artefact


def test_remote_engine_refuses_an_uncut_image_before_sending_it(worker, tmp_path):
    e = remote(worker)
    opaque = Image.open(io.BytesIO(png(alpha=False)))
    with pytest.raises(InvalidInputError, match="cut out"):
        e.generate(GenerationRequest(opaque.convert("RGB"), {}, tmp_path / "g", cutout=opaque))
    assert worker.app.state.jobs_view() == []  # nothing reached the worker


def test_remote_failure_surfaces_the_workers_error(tmp_path):
    app = create_worker([BoomEngine()], TOKEN, workdir=tmp_path / "w")
    e = RemoteEngine(BASE, TOKEN, "fake", client=TestClient(app, base_url=BASE), poll_s=0.02)
    img = Image.open(io.BytesIO(png()))
    with pytest.raises(ModelError, match="out of memory"):
        e.generate(GenerationRequest(img.convert("RGB"), {}, tmp_path / "g", cutout=img))
    app.state.shutdown()


def test_cancelling_in_the_studio_cancels_the_job_on_the_worker(tmp_path):
    app = create_worker([FakeEngine(delay_s=0.2)], TOKEN, workdir=tmp_path / "w")
    c = TestClient(app, base_url=BASE)
    e = RemoteEngine(BASE, TOKEN, "fake", client=c, poll_s=0.02)
    img = Image.open(io.BytesIO(png()))
    token = CancellationToken()
    threading.Timer(0.4, token.cancel).start()
    with pytest.raises(JobCancelledError):
        e.generate(GenerationRequest(img.convert("RGB"), {}, tmp_path / "g", cancel=token, cutout=img))
    time.sleep(0.2)
    states = [j.state for j in app.state.jobs_view()]
    assert states and all(s in ("cancelled", "running") for s in states)
    deadline = time.time() + 5
    while time.time() < deadline and any(s == "running" for s in [j.state for j in app.state.jobs_view()]):
        time.sleep(0.05)
    assert [j.state for j in app.state.jobs_view()] == ["cancelled"]
    app.state.shutdown()


def test_unknown_remote_engine_ids_are_refused():
    with pytest.raises(Exception, match="Unknown remote engine"):
        RemoteEngine(BASE, TOKEN, "mystery")


# ---- registration + the Studio as a whole ------------------------------------------------------
def test_worker_settings_register_remote_engines_alongside_triposr(tmp_path):
    s = Settings(
        data_dir=tmp_path / "d",
        worker_url=BASE,
        worker_token=SecretStr(TOKEN),
        worker_engines="trellis2, triposg ,bogus",
    )
    ctx = build_context(s, start_workers=False)
    try:
        ids = sorted(e.info.id for e in ctx.registry.all())
        assert ids == ["trellis2", "triposg", "triposr"]  # unknown ids are ignored, the default engine is untouched
        assert s.default_engine == "triposr"
    finally:
        ctx.close()


def test_without_a_worker_url_only_the_local_engine_exists(tmp_path):
    ctx = build_context(Settings(data_dir=tmp_path / "d"), start_workers=False)
    try:
        assert [e.info.id for e in ctx.registry.all()] == ["triposr"]
    finally:
        ctx.close()


def test_one_click_conversion_runs_on_the_remote_engine(worker, tmp_path):
    e = remote(worker)
    c, ctx = make_client(tmp_path, engines=[e], verified_model_licenses="fake", default_engine="fake")
    try:
        files = {"file": ("truck.png", png(alpha=False, size=(160, 120)), "image/png")}
        r = c.post("/api/convert", files=files, data={"category": "heavy_truck", "length_m": "6.5"})
        assert r.status_code == 202, r.text
        done = wait(c, r.json()["job"]["job_id"], timeout=120)
        assert done["state"] == "COMPLETED", done.get("error")
        res = done["result"]
        assert res["engine"]["id"] == "fake" and "NOT AI" in res["engine"]["name"]
        assert res["model_ran"] is True
        assert c.get(res["download"]).content[:4] == b"glTF"
        raw = c.get(f"/api/versions/{res['raw_version_id']}").json()
        assert raw["stage"] == "raw"
    finally:
        ctx.close()


def test_the_licence_gate_still_applies_to_remote_engines(worker, tmp_path):
    e = remote(worker)
    c, ctx = make_client(tmp_path, engines=[e], default_engine="fake")  # fake NOT in verified_model_licenses
    try:
        files = {"file": ("truck.png", png(alpha=False), "image/png")}
        r = c.post("/api/convert", files=files, data={"category": "heavy_truck"})
        assert r.status_code >= 400 and "licence" in r.text.lower()
    finally:
        ctx.close()
