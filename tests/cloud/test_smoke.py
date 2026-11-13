"""The owner-run smoke check, exercised against the labelled doubles: it must report PASS only for output that is both gate-valid and not a test double."""

from __future__ import annotations

import httpx
import pytest

from aro_cloud.providers import RunPodProvider
from aro_cloud.smoke import run_endpoint_smoke
from aro_worker.engines.fake import FakeEngine
from aro_worker.headless import run_pipeline
from aro_worker.runpod_handler import Deps, HandlerConfig
from tests.cloud.test_end_to_end import FakeAsTripoSG, InProcessRunPod

pytestmark = pytest.mark.slow


def provider_for(engine_cls):
    cfg = HandlerConfig(
        allowed_engines=("triposg",),
        allowed_hosts=("127.0.0.1", "0.0.0.0"),
        allow_insecure_urls=True,
        verified_licenses="triposg",
    )  # noqa: S104
    rp = InProcessRunPod(
        Deps(
            cfg, lambda name: engine_cls(), http=httpx.Client(timeout=60), pipeline=run_pipeline, sleep=lambda _s: None
        )
    )
    return RunPodProvider(
        api_key="k",
        endpoint_id="ep1",
        base_url="https://runpod.test/v2",
        client=httpx.Client(transport=httpx.MockTransport(rp)),
    )


def test_a_test_double_run_never_counts_as_inference(store, settings, concept_png):
    ev = run_endpoint_smoke(
        store, provider_for(FakeAsTripoSG), settings, concept_png, preset="STANDARD", sleep=lambda _s: None
    )
    assert ev["provider_state"] == "succeeded" and ev["engine_reported"]["test_double"] is True
    assert ev["gate_ok"] is False and ev["ai_inference"] is False and ev["status"] == "FAIL"
    assert "test double" in ev["reason"]


def test_a_failed_run_is_reported_with_the_workers_reason(store, settings, concept_png):
    class Broken(FakeEngine):
        id = "triposg"

        def generate(self, *a, **k):
            raise RuntimeError("boom")

    ev = run_endpoint_smoke(
        store, provider_for(Broken), settings, concept_png, preset="STANDARD", sleep=lambda _s: None
    )
    assert ev["status"] == "FAIL" and ev["ai_inference"] is False and ev["provider_state"] == "failed"


def test_secrets_and_signed_urls_never_appear_in_the_evidence(store, settings, concept_png):
    import json

    text = json.dumps(
        run_endpoint_smoke(
            store, provider_for(FakeAsTripoSG), settings, concept_png, preset="STANDARD", sleep=lambda _s: None
        )
    )
    assert "X-Amz" not in text and "test-secret" not in text and "http" not in text


def test_cleanup_removes_the_objects_it_created(store, settings, concept_png):
    run_endpoint_smoke(
        store, provider_for(FakeAsTripoSG), settings, concept_png, preset="STANDARD", sleep=lambda _s: None
    )
    assert store._c.list_objects_v2(Bucket=store.bucket).get("KeyCount", 0) == 0


def test_the_real_length_reaches_the_worker(store, settings, concept_png):
    seen = {}

    class Recorder:
        name = "recorder"

        def submit(self, payload, *, execution_timeout_s, ttl_s):
            seen.update(payload["settings"])
            raise RuntimeError("stop here")

    with pytest.raises(RuntimeError):
        run_endpoint_smoke(
            store, Recorder(), settings, concept_png, category="heavy_truck", length_m=6.9, sleep=lambda _s: None
        )
    assert seen["length_m"] == 6.9 and seen["category"] == "heavy_truck"
