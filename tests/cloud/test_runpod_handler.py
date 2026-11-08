"""The RunPod handler: input contract, URL safety, engine gating, transfers, and the real Studio pipeline around a labelled test-double engine.

The test-double engine (aro_worker.engines.fake) draws a procedural car; it proves the handler, the storage protocol and the preparation
pipeline, and is never counted as AI inference. Real inference needs a GPU and is verified with scripts/runpod_smoke.py on the owner's endpoint.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

import httpx
import pytest

from aro_cloud import keys
from aro_cloud.schemas import WorkerInput, WorkerResult
from aro_worker.engines.fake import FakeEngine
from aro_worker.headless import PipelineError, PipelineOutput
from aro_worker.runpod_handler import Deps, HandlerConfig, handle
from tests.cloud.support import make_glb, png_bytes, sha

HOSTS = ("127.0.0.1", "0.0.0.0")  # noqa: S104 - where moto listens


def config(**over: Any) -> HandlerConfig:
    base = dict(
        allowed_engines=("triposg",), allowed_hosts=HOSTS, allow_insecure_urls=True, verified_licenses="triposg"
    )
    base.update(over)
    return HandlerConfig(**base)  # type: ignore[arg-type]


def event_for(store, owner=None, job=None, *, image=None, engine="triposg", settings=None) -> dict[str, Any]:
    owner, job = owner or uuid.uuid4(), job or uuid.uuid4()
    image = image if image is not None else png_bytes()
    key = keys.upload_key(owner, uuid.uuid4(), "png")
    store.put_bytes(key, image, "image/png")
    outputs = {
        role: {"put_url": store.presign_put(keys.job_key(owner, job, role), 3600, ctype), "content_type": ctype}
        for role, (_, ctype) in keys.JOB_FILES.items()
    }
    return {
        "id": "rp-1",
        "input": {
            "schema_version": 1,
            "job_id": str(job),
            "kind": "image_to_3d",
            "engine": engine,
            "image": {
                "get_url": store.presign_get(key, 3600),
                "sha256": sha(image),
                "bytes": len(image),
                "content_type": "image/png",
            },
            "settings": settings or {"preset": "DRAFT", "category": "car"},
            "outputs": outputs,
            "limits": {"max_glb_bytes": 150_000_000},
        },
        "_owner": owner,
        "_job": job,
    }


class StubPipeline:
    """Stands in for the Studio pipeline in handler-level tests: returns a real GLB, records how it was called."""

    def __init__(self, glb: bytes | None = None, error: Exception | None = None):
        self.glb, self.error, self.calls = glb or make_glb(), error, []

    def __call__(self, engine, image, **kw):
        self.calls.append((engine.id, image, kw))
        if self.error:
            raise self.error
        return PipelineOutput(
            self.glb,
            self.glb,
            b"\x89PNG\r\n\x1a\n" + b"0" * 40,
            {"validation": {"status": "passed"}, "stages": []},
            1.5,
        )


def deps_for(cfg=None, pipeline=None, http=None, factory=None) -> Deps:
    return Deps(
        cfg or config(),
        factory or (lambda name: FakeEngine()),
        http=http or httpx.Client(timeout=30),
        pipeline=pipeline or StubPipeline(),
        sleep=lambda _s: None,
    )


def failure(out: dict[str, Any]) -> dict[str, Any]:
    assert set(out) == {"error"}, out
    return json.loads(out["error"])


# ------------------------------------------------------------------------------------------------------ contract
def test_the_input_the_api_builds_is_the_input_the_handler_parses(store, settings):
    from aro_cloud.orchestrator import Orchestrator

    owner, job, up = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    orch = Orchestrator(None, store, None, settings)  # type: ignore[arg-type]
    key = keys.upload_key(owner, up, "png")
    payload = orch.worker_input(
        {
            "owner_id": str(owner),
            "job_id": str(job),
            "request": {
                "kind": "image_to_3d",
                "engine": "triposg",
                "settings": {"preset": "HIGH", "category": "car", "seed": 7},
            },
        },
        {"r2_key": key, "sha256": "a" * 64, "bytes": 1234, "content_type": "image/png"},
    )
    parsed = WorkerInput.model_validate(payload)
    assert (
        parsed.settings.seed == 7
        and set(parsed.outputs) == set(keys.JOB_FILES)
        and parsed.limits["max_glb_bytes"] == 150_000_000
    )
    assert "secret" not in json.dumps(payload).lower().replace(
        "x-amz-signature", ""
    )  # signed URLs only; no credentials in the payload


@pytest.mark.parametrize(
    "bad", [{}, {"input": None}, {"input": {"schema_version": 2}}, {"input": {"schema_version": 1, "job_id": "x"}}]
)
def test_malformed_events_fail_cleanly(bad):
    err = failure(handle(bad, deps_for()))
    assert err["code"] == "invalid_input" and err["retryable"] is False


# ----------------------------------------------------------------------------------------------------- success path
def test_success_uploads_every_file_and_writes_the_marker_last(store):
    ev = event_for(store)
    order: list[str] = []
    client = httpx.Client(
        timeout=30,
        event_hooks={"request": [lambda r: order.append(r.url.path.rsplit("/", 1)[-1]) if r.method == "PUT" else None]},
    )
    pipe = StubPipeline()
    out = handle(ev, deps_for(http=client, pipeline=pipe), progress=lambda _m: None)
    assert out["ok"] is True and out["engine"]["test_double"] is True  # the fake is labelled, never passed off as AI
    assert [f["role"] for f in out["files"]] == ["raw_mesh", "glb", "thumbnail", "report"]
    assert order == ["raw.glb", "model.glb", "thumbnail.png", "report.json", "result.json"]  # result.json last
    for f in out["files"]:
        data = store.get_bytes(keys.job_key(ev["_owner"], ev["_job"], f["role"]), 200_000_000)
        assert len(data) == f["bytes"] and hashlib.sha256(data).hexdigest() == f["sha256"]
    marker = WorkerResult.model_validate_json(
        store.get_bytes(keys.job_key(ev["_owner"], ev["_job"], "result"), 100_000)
    )
    assert marker.ok and {f.role for f in marker.files} == {"raw_mesh", "glb", "thumbnail", "report"}
    _, _, kw = pipe.calls[0]
    assert (
        kw["category"] == "car"
        and kw["preset"] == "DRAFT"
        and kw["target_triangles"] == 24_000
        and kw["verified_licenses"] == "triposg"
    )


def test_settings_reach_the_pipeline_unchanged(store):
    pipe = StubPipeline()
    s = {
        "preset": "HIGH",
        "seed": 99,
        "target_faces": 12000,
        "category": "bus",
        "length_m": 11.5,
        "texture_resolution": 2048,
    }
    handle(event_for(store, settings=s), deps_for(pipeline=pipe))
    kw = pipe.calls[0][2]
    assert (
        kw["preset"],
        kw["seed"],
        kw["target_triangles"],
        kw["category"],
        kw["length_m"],
        kw["texture_resolution"],
    ) == ("HIGH", 99, 12000, "bus", 11.5, 2048)


# ------------------------------------------------------------------------------------------------------ engine gating
@pytest.mark.parametrize(
    ("engine", "cfg"),
    [
        ("fake", config(allowed_engines=("fake",))),  # a test double needs an explicit switch
        ("trellis2", config(allowed_engines=("trellis2",))),  # evaluation-only models need evaluation mode
        ("hunyuan3d", config(allowed_engines=("hunyuan3d",))),
        ("triposg", config(allowed_engines=("something_else",))),  # not served by this deployment
    ],
)
def test_engines_are_gated(store, engine, cfg):
    pipe = StubPipeline()
    err = failure(handle(event_for(store, engine=engine), deps_for(cfg, pipeline=pipe)))
    assert err["code"] == "engine_not_allowed" and not pipe.calls


def test_evaluation_mode_and_test_double_switches_open_their_own_gate(store):
    pipe = StubPipeline()
    assert handle(
        event_for(store, engine="fake"),
        deps_for(config(allowed_engines=("fake",), allow_test_double=True), pipeline=pipe),
    )["ok"]


# ----------------------------------------------------------------------------------------------------------- URL safety
@pytest.mark.parametrize(
    ("mutate", "cfg"),
    [
        (lambda u: u.replace("http://", "ftp://"), config()),
        (lambda u: u.replace("http://", "http://user:pw@"), config()),
        (lambda u: "http://evil.example/x?y=1", config()),  # host not on the allow-list
        (lambda u: u, config(allow_insecure_urls=False)),  # plain http without the test switch
    ],
)
def test_unsafe_urls_are_refused_before_any_request(store, mutate, cfg):
    ev = event_for(store)
    ev["input"]["image"]["get_url"] = mutate(ev["input"]["image"]["get_url"])
    calls = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200)))
    err = failure(handle(ev, deps_for(cfg, http=client)))
    assert err["code"] == "invalid_input" and not calls


def test_a_storage_host_that_resolves_to_a_private_address_is_refused(store):
    ev = event_for(store)
    ev["input"]["image"]["get_url"] = "https://127.0.0.1/x"
    for o in ev["input"]["outputs"].values():
        o["put_url"] = "https://127.0.0.1/y"
    err = failure(handle(ev, deps_for(config(allow_insecure_urls=False))))
    assert err["code"] == "invalid_input" and "non-public" in err["message"]


def test_error_messages_never_contain_signed_urls(store):
    ev = event_for(store)
    url = ev["input"]["image"]["get_url"]
    ev["input"]["image"]["get_url"] = url.replace("http://", "http://user:pw@")
    text = json.dumps(handle(ev, deps_for()))
    assert "X-Amz-Signature" not in text and "user:pw" not in text


# ------------------------------------------------------------------------------------------------------------ transfers
def test_an_image_that_is_not_the_validated_one_is_refused(store):
    ev = event_for(store)
    ev["input"]["image"]["sha256"] = "0" * 64
    err = failure(handle(ev, deps_for()))
    assert err["code"] == "invalid_input" and "does not match" in err["message"]


def test_download_failures_are_classified_for_retry(store):
    ev = event_for(store)
    gone = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    err = failure(handle(ev, deps_for(http=gone)))
    assert err["code"] == "download_failed" and err["retryable"] is False  # an expired URL is not fixed by asking again
    flaky = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    err = failure(handle(ev, deps_for(http=flaky)))
    assert err["code"] == "download_failed" and err["retryable"] is True


def test_a_download_that_recovers_is_used(store):
    ev = event_for(store)
    real = httpx.Client(timeout=30)
    n = {"get": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            n["get"] += 1
            if n["get"] == 1:
                return httpx.Response(503)
        return real.send(httpx.Request(request.method, request.url, headers=request.headers, content=request.content))

    assert handle(ev, deps_for(http=httpx.Client(transport=httpx.MockTransport(flaky))))["ok"] and n["get"] == 2


def test_upload_failures_are_retryable_and_stop_the_run(store):
    ev = event_for(store)
    real = httpx.Client(timeout=30)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            return httpx.Response(500)
        return real.send(httpx.Request(request.method, request.url, headers=request.headers))

    err = failure(handle(ev, deps_for(http=httpx.Client(transport=httpx.MockTransport(handler)))))
    assert err["code"] == "upload_failed" and err["retryable"] is True
    assert (
        store.head(keys.job_key(ev["_owner"], ev["_job"], "result")) is None
    )  # no marker for a run that did not finish


def test_a_refused_upload_is_not_retried_forever(store):
    ev = event_for(store)
    real = httpx.Client(timeout=30)
    puts = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            puts.append(1)
            return httpx.Response(403)
        return real.send(httpx.Request(request.method, request.url, headers=request.headers))

    err = failure(handle(ev, deps_for(http=httpx.Client(transport=httpx.MockTransport(handler)))))
    assert err["code"] == "upload_failed" and err["retryable"] is False and len(puts) == 1


def test_oversized_output_is_refused_before_upload(store):
    ev = event_for(store)
    ev["input"]["limits"]["max_glb_bytes"] = 1000
    err = failure(handle(ev, deps_for()))
    assert err["code"] == "output_too_large" and store.head(keys.job_key(ev["_owner"], ev["_job"], "glb")) is None


# ------------------------------------------------------------------------------------------------------- error mapping
@pytest.mark.parametrize(
    ("e", "code", "retryable"),
    [
        (PipelineError("INVALID_INPUT", "The image is too small.", "INVALID_INPUT"), "invalid_input", False),
        (
            PipelineError("ENGINE_UNAVAILABLE", "ARO_VERIFIED_MODEL_LICENSES secret detail", "REJECTED"),
            "engine_unavailable",
            False,
        ),
        (PipelineError("RESOURCE_LIMIT", "CUDA out of memory", "RESOURCE_LIMIT"), "resource_limit", False),
        (PipelineError("JOB_TIMEOUT", "late", "TIMEOUT"), "pipeline_timeout", False),
        (PipelineError("MODEL_ERROR", "trace /opt/TripoSG/x.py", "MODEL_ERROR"), "model_error", False),
    ],
)
def test_pipeline_failures_become_stable_codes_without_leaking_internals(store, e, code, retryable):
    err = failure(handle(event_for(store), deps_for(pipeline=StubPipeline(error=e))))
    assert err["code"] == code and err["retryable"] is retryable
    assert "ARO_VERIFIED" not in err["message"] and "/opt/" not in err["message"] and "CUDA" not in err["message"]


def test_an_unexpected_exception_does_not_leak_and_does_not_retry(store):
    err = failure(
        handle(event_for(store), deps_for(pipeline=StubPipeline(error=RuntimeError("secret path /root/.cache"))))
    )
    assert err["code"] == "internal_error" and "/root" not in err["message"] and err["retryable"] is False


# --------------------------------------------------------------------------- the real Studio pipeline around the test double
@pytest.mark.slow
def test_the_real_studio_pipeline_runs_end_to_end_around_the_test_double(store, concept_png):
    """Matting, orientation, preparation, UVs, validation and export are the real code; only the shape generator is the labelled test double."""
    ev = event_for(
        store,
        image=concept_png,
        engine="fake",
        settings={"preset": "STANDARD", "category": "car", "target_faces": 4000, "length_m": 4.5},
    )
    cfg = config(allowed_engines=("fake",), allow_test_double=True, verified_licenses="fake")
    from aro_worker.headless import run_pipeline

    out = handle(
        ev,
        Deps(
            cfg, lambda name: FakeEngine(), http=httpx.Client(timeout=60), pipeline=run_pipeline, sleep=lambda _s: None
        ),
    )
    assert out["ok"] is True, out
    assert out["engine"]["test_double"] is True
    glb = store.get_bytes(keys.job_key(ev["_owner"], ev["_job"], "glb"), 200_000_000)
    raw = store.get_bytes(keys.job_key(ev["_owner"], ev["_job"], "raw_mesh"), 200_000_000)
    assert glb[:4] == b"glTF" and raw[:4] == b"glTF" and glb != raw  # the prepared asset is a different, processed file
    from aro_cloud.output_gate import validate_glb

    gate = validate_glb(
        glb,
        claimed_sha256=sha(glb),
        max_bytes=150_000_000,
        engine_is_test_double=True,
        allow_test_double=True,
        min_triangles=200,
    )
    assert gate.ok, gate.reasons
    assert store.head(keys.job_key(ev["_owner"], ev["_job"], "thumbnail")) is not None
