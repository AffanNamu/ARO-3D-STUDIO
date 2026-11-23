"""The direct test path: image inside the job, model inside the result. No storage involved, still the real handler and output gate."""

from __future__ import annotations

import base64
import hashlib
import json

import httpx
import pytest
from pydantic import ValidationError

from aro_cloud.direct_test import build_input, run
from aro_cloud.providers import RunPodProvider
from aro_cloud.schemas import WorkerInput
from aro_worker.headless import run_pipeline
from aro_worker.runpod_handler import Deps, HandlerConfig, handle
from tests.cloud.support import make_glb, png_bytes
from tests.cloud.test_end_to_end import FakeAsTripoSG, InProcessRunPod
from tests.cloud.test_runpod_handler import StubPipeline


def provider_with(deps: Deps) -> RunPodProvider:
    return RunPodProvider(
        api_key="k",
        endpoint_id="ep1",
        base_url="https://runpod.test/v2",
        client=httpx.Client(transport=httpx.MockTransport(InProcessRunPod(deps))),
    )


def cfg(**over):
    base = dict(allowed_engines=("triposg",), verified_licenses="triposg", allow_inline=True)
    base.update(over)
    return HandlerConfig(**base)  # type: ignore[arg-type]


def failure(out):
    return json.loads(out["error"])


# ----------------------------------------------------------------------------------------------------------- contract
def test_an_inline_input_is_valid_and_mixing_modes_is_not():
    payload = build_input(png_bytes(), engine="triposg", preset="DRAFT", category="car", length_m=4.5, seed=None)
    spec = WorkerInput.model_validate(payload)
    assert spec.inline and spec.settings.length_m == 4.5
    mixed = dict(
        payload,
        outputs={"glb": {"put_url": "https://x.r2.cloudflarestorage.com/a", "content_type": "model/gltf-binary"}},
    )
    with pytest.raises(ValidationError):
        WorkerInput.model_validate(mixed)
    both = json.loads(json.dumps(payload))
    both["image"]["get_url"] = "https://x.r2.cloudflarestorage.com/a"
    with pytest.raises(ValidationError):
        WorkerInput.model_validate(both)


def test_images_too_large_for_the_job_payload_are_refused_before_sending():
    with pytest.raises(SystemExit, match="direct test takes up to"):
        build_input(
            b"\x89PNG" + b"0" * 6_100_000, engine="triposg", preset="DRAFT", category="car", length_m=None, seed=None
        )


# ----------------------------------------------------------------------------------------------------------- handler
def test_inline_is_off_unless_the_endpoint_allows_it():
    payload = build_input(png_bytes(), engine="triposg", preset="DRAFT", category="car", length_m=None, seed=None)
    err = failure(
        handle({"input": payload}, Deps(cfg(allow_inline=False), lambda n: FakeAsTripoSG(), pipeline=StubPipeline()))
    )
    assert err["code"] == "inline_not_allowed"


def test_a_corrupted_inline_image_is_refused():
    payload = build_input(png_bytes(), engine="triposg", preset="DRAFT", category="car", length_m=None, seed=None)
    payload["image"]["sha256"] = "0" * 64
    assert (
        failure(handle({"input": payload}, Deps(cfg(), lambda n: FakeAsTripoSG(), pipeline=StubPipeline())))["code"]
        == "invalid_input"
    )


def test_inline_result_carries_the_files_and_drops_the_raw_mesh_first_when_big(monkeypatch):
    import aro_worker.runpod_handler as h

    payload = build_input(png_bytes(), engine="triposg", preset="DRAFT", category="car", length_m=None, seed=None)
    out = handle({"input": payload}, Deps(cfg(), lambda n: FakeAsTripoSG(), pipeline=StubPipeline()))
    assert set(out["inline_files"]) == {"glb", "thumbnail", "report", "raw_mesh"} and out["not_returned"] == []
    glb = base64.b64decode(out["inline_files"]["glb"])
    assert hashlib.sha256(glb).hexdigest() == next(f["sha256"] for f in out["files"] if f["role"] == "glb")
    monkeypatch.setattr(
        h,
        "INLINE_OUTPUT_MAX_B64",
        len(out["inline_files"]["glb"])
        + len(out["inline_files"]["thumbnail"])
        + len(out["inline_files"]["report"])
        + 10,
    )
    out2 = handle({"input": payload}, Deps(cfg(), lambda n: FakeAsTripoSG(), pipeline=StubPipeline()))
    assert out2["not_returned"] == ["raw_mesh"] and "raw_mesh" not in out2["inline_files"]
    monkeypatch.setattr(h, "INLINE_OUTPUT_MAX_B64", 100)
    assert (
        failure(handle({"input": payload}, Deps(cfg(), lambda n: FakeAsTripoSG(), pipeline=StubPipeline())))["code"]
        == "output_too_large"
    )


# ----------------------------------------------------------------------------------------------------------- the tool
def test_the_tool_writes_the_model_and_never_calls_a_test_double_inference(tmp_path):
    deps = Deps(cfg(), lambda n: FakeAsTripoSG(), pipeline=StubPipeline(glb=make_glb()))
    ev = run(
        provider_with(deps), png_bytes(), tmp_path / "run", category="car", sleep=lambda _s: None, say=lambda _m: None
    )
    assert ev["provider_state"] == "succeeded" and ev["engine_reported"]["test_double"] is True
    assert (
        ev["ai_inference"] is False and ev["status"] == "FAIL" and "test double" in ev["reason"]
    )  # the gate refuses non-AI output
    assert (tmp_path / "run" / "model.glb").read_bytes()[:4] == b"glTF"
    assert json.loads((tmp_path / "run" / "evidence.json").read_text())["status"] == "FAIL"


def test_a_worker_failure_is_reported_with_its_reason(tmp_path):
    deps = Deps(cfg(allow_inline=False), lambda n: FakeAsTripoSG(), pipeline=StubPipeline())
    ev = run(provider_with(deps), png_bytes(), tmp_path / "run", sleep=lambda _s: None, say=lambda _m: None)
    assert ev["provider_state"] == "failed" and "inline_not_allowed" in ev["reason"] and ev["ai_inference"] is False


def test_a_tampered_answer_is_refused(tmp_path):
    class Tamper(InProcessRunPod):
        def __call__(self, request):
            resp = super().__call__(request)
            if "/status/" in request.url.path:
                body = resp.json()
                out = body.get("output") or {}
                if "inline_files" in out:
                    out["inline_files"]["glb"] = base64.b64encode(make_glb(1)).decode()
                return httpx.Response(200, json=body)
            return resp

    deps = Deps(cfg(), lambda n: FakeAsTripoSG(), pipeline=StubPipeline())
    p = RunPodProvider(
        api_key="k",
        endpoint_id="ep1",
        base_url="https://runpod.test/v2",
        client=httpx.Client(transport=httpx.MockTransport(Tamper(deps))),
    )
    ev = run(p, png_bytes(), tmp_path / "run", sleep=lambda _s: None, say=lambda _m: None)
    assert ev["status"] == "FAIL" and "does not match" in ev["reason"]


@pytest.mark.slow
def test_the_real_pipeline_through_the_direct_path(tmp_path, concept_png):
    deps = Deps(
        cfg(allowed_engines=("triposg",)),
        lambda n: FakeAsTripoSG(detail=3),
        pipeline=run_pipeline,
        sleep=lambda _s: None,
    )
    ev = run(
        provider_with(deps),
        concept_png,
        tmp_path / "run",
        category="car",
        length_m=4.5,
        preset="STANDARD",
        sleep=lambda _s: None,
        say=lambda _m: None,
    )
    assert ev["provider_state"] == "succeeded" and ev["model"]["triangles"] > 200 and len(ev["model"]["lods"]) == 4
    assert ev["ai_inference"] is False  # test double: labelled and refused, never reported as inference
    assert {"model.glb", "thumbnail.png", "report.json"} <= set(ev["files_written"])


@pytest.mark.slow
def test_a_real_width_and_height_reach_the_model(tmp_path, concept_png):
    """From one photo the model's proportions are a guess; the real width and height the user gives must decide the final size."""
    deps = Deps(
        cfg(allowed_engines=("triposg",)),
        lambda n: FakeAsTripoSG(detail=3),
        pipeline=run_pipeline,
        sleep=lambda _s: None,
    )
    ev = run(
        provider_with(deps),
        concept_png,
        tmp_path / "run",
        category="car",
        length_m=4.5,
        width_m=1.8,
        height_m=1.4,
        preset="STANDARD",
        sleep=lambda _s: None,
        say=lambda _m: None,
    )
    assert ev["provider_state"] == "succeeded", ev
    w, h, length = ev["model"]["extents"]
    assert length == pytest.approx(4.5, rel=0.05)
    assert w == pytest.approx(1.8, rel=0.05)
    assert h == pytest.approx(1.4, rel=0.05)
    assert (ev["width_m"], ev["height_m"]) == (1.8, 1.4)
    report = json.loads((tmp_path / "run" / "report.json").read_text())
    assert any("STRETCHED" in note for note in report["needs_human"])  # the report says the proportions were imposed
