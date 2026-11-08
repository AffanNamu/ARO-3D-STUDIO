"""Orchestrator -> RunPod client -> handler -> storage -> orchestrator, with every real component except the GPU model and RunPod itself.

* RunPod is a labelled HTTP test double that follows its documented queue API and runs our real handler when a job is submitted.
* The engine is the labelled procedural test double (relabelled with the id 'triposg' so the registry path is exercised); the Studio
  preparation pipeline, the output gate, PostgreSQL, the credit ledger and the S3 API are real.
* A production-like configuration (allow_test_double off) must REFUSE this output: that is asserted too.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
import pytest

from aro_cloud import accounts
from aro_cloud.orchestrator import Orchestrator
from aro_cloud.providers import RunPodProvider
from aro_worker.engines.fake import FakeEngine
from aro_worker.headless import run_pipeline
from aro_worker.runpod_handler import Deps, HandlerConfig, handle
from tests.cloud.support import add_upload, enable_model, make_user, request_for

pytestmark = pytest.mark.slow


class FakeAsTripoSG(FakeEngine):
    """TEST DOUBLE registered under the id the platform expects. Its result is stamped test_double=true."""

    id = "triposg"


class InProcessRunPod:
    """RunPod's /run, /status, /cancel over httpx.MockTransport. /run executes the real handler synchronously."""

    def __init__(self, deps: Deps):
        self.deps, self.runs, self.n = deps, {}, 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path.endswith("/run"):
            body = json.loads(request.content)
            self.n += 1
            rid = f"rp-{self.n}"
            self.runs[rid] = handle({"id": rid, "input": body["input"]}, self.deps)
            return httpx.Response(200, json={"id": rid, "status": "IN_QUEUE"})
        m = re.search(r"/status/([\w-]+)$", path)
        if m and m.group(1) in self.runs:
            out = self.runs[m.group(1)]
            if "error" in out:
                return httpx.Response(200, json={"id": m.group(1), "status": "FAILED", "error": out["error"]})
            return httpx.Response(
                200, json={"id": m.group(1), "status": "COMPLETED", "output": out, "executionTime": 4200}
            )
        if "/cancel/" in path:
            return httpx.Response(200, json={"status": "CANCELLED"})
        return httpx.Response(404)


def build(pg, store, settings, concept_png, *, allow_test_double: bool):
    enable_model(pg)
    cfg = HandlerConfig(
        allowed_engines=("triposg",),
        allowed_hosts=("127.0.0.1", "0.0.0.0"),  # noqa: S104
        allow_insecure_urls=True,
        allow_test_double=allow_test_double,
        verified_licenses="triposg",
    )
    # the test engine is not 'fake', so the handler's own test-double gate is keyed on the engine's flag
    deps = Deps(
        cfg, lambda name: FakeAsTripoSG(), http=httpx.Client(timeout=60), pipeline=run_pipeline, sleep=lambda _s: None
    )
    rp = InProcessRunPod(deps)
    provider = RunPodProvider(
        api_key="test-key",
        endpoint_id="ep1",
        base_url="https://runpod.test/v2",
        client=httpx.Client(transport=httpx.MockTransport(rp)),
    )
    orch = Orchestrator(pg, store, provider, settings.model_copy(update={"allow_test_double": allow_test_double}))
    owner = make_user(pg, credits=50)
    upload = add_upload(pg, store, owner)
    # replace the synthetic 512px colour square with a real concept-style image so the Studio's matting has a subject
    with pg.transaction() as tx:
        row = tx.one("select r2_key from uploads where upload_id = CAST(:u AS uuid)", u=str(upload))
        import hashlib

        tx.execute(
            "update uploads set bytes = :b, sha256 = :s where upload_id = CAST(:u AS uuid)",
            b=len(concept_png),
            s=hashlib.sha256(concept_png).hexdigest(),
            u=str(upload),
        )
    store.put_bytes(row["r2_key"], concept_png, "image/png")
    return orch, owner, upload, rp


def test_a_generation_flows_from_submit_to_a_stored_validated_asset(pg, store, settings, concept_png):
    orch, owner, upload, rp = build(pg, store, settings, concept_png, allow_test_double=True)
    job, _ = orch.submit(
        owner,
        request_for(upload, settings={"preset": "STANDARD", "category": "car", "target_faces": 4000, "length_m": 4.5}),
        "e2e-key-0001",
    )
    sent = orch.dispatch(job["job_id"])
    assert sent["state"] == "initializing" and sent["provider_run_id"] == "rp-1"
    done = orch.reconcile(job["job_id"])
    assert done["state"] == "completed", done.get("error_message")
    with pg.transaction() as tx:
        assert accounts.balance(tx, owner) == {"balance": 40, "reserved": 0}
        v = tx.one(
            "select provenance, geometry_stats, validation from asset_versions where version_id = CAST(:v AS uuid)",
            v=done["result_version_id"],
        )
    assert (
        v["provenance"]["test_double"] is True and v["provenance"]["ai_inference"] is False
    )  # labelled, never reported as inference
    assert v["geometry_stats"]["triangles"] >= 200 and v["validation"]["status"] == "passed"
    assert v["validation"]["report"].get("stages")  # the Studio's own stage report travelled with the asset


def test_a_production_configuration_refuses_test_double_output(pg, store, settings, concept_png):
    orch, owner, upload, _ = build(pg, store, settings, concept_png, allow_test_double=False)
    # the handler of a production worker would refuse the test double outright; here the worker is permissive and the API is the second gate
    orch.s = settings.model_copy(update={"allow_test_double": False})
    job, _ = orch.submit(owner, request_for(upload, settings={"category": "car", "target_faces": 4000}), "e2e-key-0002")
    orch.dispatch(job["job_id"])
    out = orch.reconcile(job["job_id"])
    assert out["state"] == "failed" and out["error_code"] == "output_rejected" and "test double" in out["error_message"]
    with pg.transaction() as tx:
        assert accounts.balance(tx, owner) == {"balance": 50, "reserved": 0}  # not charged
        assert tx.one("select count(*) as n from assets")["n"] == 0


def test_a_worker_failure_travels_back_as_a_stable_code_and_releases_credits(pg, store, settings, concept_png):
    orch, owner, upload, rp = build(pg, store, settings, concept_png, allow_test_double=True)
    rp.deps.config.allowed_engines = ("something_else",)
    job, _ = orch.submit(owner, request_for(upload), "e2e-key-0003")
    orch.dispatch(job["job_id"])
    out: dict[str, Any] = orch.reconcile(job["job_id"])
    assert out["state"] == "failed" and out["error_code"] == "engine_not_allowed"
    with pg.transaction() as tx:
        assert accounts.balance(tx, owner) == {"balance": 50, "reserved": 0}
