"""Job orchestration against a real PostgreSQL and an S3-compatible server. The GPU provider is a labelled test double; nothing here is AI inference."""

from __future__ import annotations

import threading
import uuid

import pytest

from aro_cloud import accounts, jobs
from aro_cloud.errors import Conflict, InvalidRequest, NotFound, PaymentRequired, TooManyRequests, Unavailable
from aro_cloud.orchestrator import Orchestrator
from aro_cloud.providers.base import ProviderAmbiguous, ProviderRejected, ProviderUnavailable
from tests.cloud.support import (
    ScriptedProvider,
    add_upload,
    enable_model,
    finish_run,
    make_glb,
    make_user,
    request_for,
)


@pytest.fixture
def env(pg, store, settings):
    enable_model(pg)
    provider = ScriptedProvider()
    orch = Orchestrator(pg, store, provider, settings)
    owner = make_user(pg, credits=100)
    upload = add_upload(pg, store, owner)
    return orch, provider, owner, upload


def ledger_kinds(pg, job_id):
    with pg.transaction() as tx:
        return [
            r["kind"]
            for r in tx.all(
                "select kind::text as kind from credit_ledger where job_id = CAST(:j AS uuid) order by entry_id",
                j=str(job_id),
            )
        ]


def balance(pg, owner):
    with pg.transaction() as tx:
        return accounts.balance(tx, owner)


def expire(pg, job_id, what="deadline_at"):
    with pg.transaction() as tx:
        tx.execute(
            f"update generation_jobs set {what} = now() - interval '1 second' where job_id = CAST(:j AS uuid)",
            j=str(job_id),
        )


def age(pg, job_id, seconds):
    with pg.transaction() as tx:
        tx.execute(
            "update generation_jobs set updated_at = now() - CAST(:s AS integer) * interval '1 second', dispatch_started_at = case when dispatch_started_at is null then null else now() - CAST(:s AS integer) * interval '1 second' end where job_id = CAST(:j AS uuid)",
            j=str(job_id),
            s=seconds,
        )


# --------------------------------------------------------------------------------------------------------------- submit
def test_submit_queues_and_reserves_exactly_the_price(env, pg):
    orch, _, owner, upload = env
    job, created = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    assert created and job["state"] == "queued" and job["credits_reserved"] == 10
    assert balance(pg, owner) == {"balance": 90, "reserved": 10}
    assert ledger_kinds(pg, job["job_id"]) == ["reserve"]


def test_same_key_and_request_returns_the_same_job_and_charges_once(env, pg):
    orch, _, owner, upload = env
    a, created_a = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    b, created_b = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    assert (created_a, created_b) == (True, False) and a["job_id"] == b["job_id"]
    assert balance(pg, owner) == {"balance": 90, "reserved": 10}


def test_same_key_with_a_different_request_is_a_conflict(env):
    orch, _, owner, upload = env
    orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    with pytest.raises(Conflict) as e:
        orch.submit(owner, request_for(upload, name="Another"), "key-aaaaaaaa")
    assert e.value.code == "idempotency_key_reused"


def test_concurrent_submits_with_one_key_create_one_job(env, pg):
    orch, _, owner, upload = env
    results, errors = [], []

    def go():
        try:
            results.append(orch.submit(owner, request_for(upload), "key-concurrent"))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert len({r[0]["job_id"] for r in results}) == 1 and sum(1 for r in results if r[1]) == 1
    assert balance(pg, owner)["balance"] == 90


@pytest.mark.parametrize("key", ["short", "has space in it!", "x" * 129, ""])
def test_bad_idempotency_keys_are_refused(env, key):
    orch, _, owner, upload = env
    with pytest.raises(InvalidRequest) as e:
        orch.submit(owner, request_for(upload), key)
    assert e.value.code == "invalid_idempotency_key"


def test_not_enough_credits_creates_nothing(pg, store, settings):
    enable_model(pg)
    orch = Orchestrator(pg, store, ScriptedProvider(), settings)
    owner = make_user(pg, credits=5)
    upload = add_upload(pg, store, owner)
    with pytest.raises(PaymentRequired) as e:
        orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    assert e.value.details == {"price": 10, "balance": 5}
    with pg.transaction() as tx:
        assert tx.one("select count(*) as n from generation_jobs")["n"] == 0
    assert balance(pg, owner) == {"balance": 5, "reserved": 0}


def test_a_model_that_a_person_has_not_verified_cannot_be_used(pg, store, settings):
    orch = Orchestrator(pg, store, ScriptedProvider(), settings)  # registry says 'claimed' and disabled
    owner = make_user(pg)
    upload = add_upload(pg, store, owner)
    with pytest.raises(Unavailable) as e:
        orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    assert e.value.code == "model_not_enabled"
    assert balance(pg, owner)["reserved"] == 0


def test_engine_not_offered_by_this_deployment(env):
    orch, _, owner, upload = env
    with pytest.raises(InvalidRequest) as e:
        orch.submit(owner, request_for(upload, engine="trellis2"), "key-aaaaaaaa")
    assert e.value.code == "engine_not_offered"


def test_someone_elses_upload_looks_like_it_does_not_exist(env, pg, store):
    orch, _, owner, _ = env
    other = make_user(pg)
    theirs = add_upload(pg, store, other)
    with pytest.raises(NotFound):
        orch.submit(owner, request_for(theirs), "key-aaaaaaaa")


def test_active_job_limit(env):
    orch, _, owner, upload = env
    orch.submit(owner, request_for(upload), "key-aaaaaaa1")
    orch.submit(owner, request_for(upload), "key-aaaaaaa2")
    with pytest.raises(TooManyRequests) as e:
        orch.submit(owner, request_for(upload), "key-aaaaaaa3")
    assert e.value.code == "too_many_active_jobs"


# ----------------------------------------------------------------------------------------------------------- happy path
def test_full_flow_to_a_completed_asset_and_captured_credits(env, pg):
    orch, provider, owner, upload = env
    job, _ = orch.submit(
        owner, request_for(upload, settings={"preset": "DRAFT", "target_faces": 20000}), "key-aaaaaaaa"
    )
    job = orch.dispatch(job["job_id"])
    assert job["state"] == "initializing" and job["provider_run_id"] == "run-1" and job["attempt"] == 1
    payload = provider.runs["run-1"].payload
    assert payload["engine"] == "triposg" and payload["settings"]["preset"] == "DRAFT"
    assert set(payload["outputs"]) == {"raw_mesh", "glb", "thumbnail", "report", "result"}
    assert "access_key" not in str(payload).lower() and "secret" not in str(payload).lower()

    provider.runs["run-1"].state = "running"
    assert orch.reconcile(job["job_id"])["state"] == "generating"

    finish_run(provider, "run-1")
    done = orch.reconcile(job["job_id"])
    assert done["state"] == "completed" and done["progress"] == 1.0 and done["credits_captured"] == 10
    assert ledger_kinds(pg, job["job_id"]) == ["reserve", "capture"]
    assert balance(pg, owner) == {"balance": 90, "reserved": 0}
    with pg.transaction() as tx:
        v = tx.one("select * from asset_versions where version_id = CAST(:v AS uuid)", v=done["result_version_id"])
        assert v["provenance"]["ai_inference"] is True and v["provenance"]["test_double"] is False
        assert v["geometry_stats"]["triangles"] >= 200
        roles = sorted(
            r["role"]
            for r in tx.all("select role from files where version_id = CAST(:v AS uuid)", v=done["result_version_id"])
        )
        assert roles == ["glb", "raw_mesh", "thumbnail"]
        assert (
            tx.one("select current_version_id from assets where asset_id = CAST(:a AS uuid)", a=str(v["asset_id"]))[
                "current_version_id"
            ]
            == v["version_id"]
        )
        usage = tx.one("select quantity, cost_usd from usage_records where job_id = CAST(:j AS uuid)", j=done["job_id"])
        assert float(usage["quantity"]) == 20.0 and float(usage["cost_usd"]) == pytest.approx(0.01)
    events = [e["to_state"] for e in _events(pg, job["job_id"])]
    assert events == [
        "created",
        "validating",
        "queued",
        "initializing",
        "generating",
        "validating_output",
        "uploading",
        "completed",
    ]


def _events(pg, job_id):
    with pg.transaction() as tx:
        return jobs.events(tx, job_id)


def test_polling_a_finished_job_changes_nothing(env, pg):
    orch, provider, owner, upload = env
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    orch.dispatch(job["job_id"])
    finish_run(provider, "run-1")
    orch.reconcile(job["job_id"])
    before = len(_events(pg, job["job_id"]))
    for _ in range(3):
        assert orch.reconcile(job["job_id"])["state"] == "completed"
    assert len(_events(pg, job["job_id"])) == before and provider.submits == 1


# ---------------------------------------------------------------------------------------------------- output is verified
@pytest.mark.parametrize(
    ("kw", "code"),
    [
        ({"test_double": True}, "output_rejected"),
        ({"corrupt_sha": True}, "output_corrupt"),
        ({"glb": b"this is not a glb"}, "output_corrupt"),
        ({"glb": make_glb(0)}, "output_rejected"),  # 20 triangles: too little geometry
        ({"engine": "hunyuan3d"}, "engine_mismatch"),
        ({"skip_roles": ("glb",)}, "invalid_output"),
        ({"skip_roles": ("thumbnail",), "write_marker": True}, None),  # optional file missing from the list: accepted
    ],
)
def test_output_that_does_not_hold_up_is_refused_and_credits_released(env, pg, kw, code):
    orch, provider, owner, upload = env
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    orch.dispatch(job["job_id"])
    finish_run(provider, "run-1", **kw)
    done = orch.reconcile(job["job_id"])
    if code is None:
        assert done["state"] == "completed"
        return
    assert done["state"] == "failed" and done["error_code"] == code
    assert "not charged" in done["error_message"]
    assert ledger_kinds(pg, job["job_id"]) == ["reserve", "release"]
    assert balance(pg, owner) == {"balance": 100, "reserved": 0}
    with pg.transaction() as tx:
        assert tx.one("select count(*) as n from assets")["n"] == 0


def test_a_missing_file_the_worker_claims_to_have_written(env, pg, store):
    orch, provider, owner, upload = env
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    orch.dispatch(job["job_id"])
    finish_run(provider, "run-1")
    from aro_cloud import keys

    store.delete(keys.job_key(owner, uuid.UUID(job["job_id"]), "glb"))
    done = orch.reconcile(job["job_id"])
    assert done["state"] == "failed" and done["error_code"] == "output_missing"


def test_the_test_double_is_accepted_only_when_a_test_explicitly_allows_it(pg, store, settings):
    enable_model(pg)
    permissive = settings.model_copy(update={"allow_test_double": True})
    provider = ScriptedProvider()
    orch = Orchestrator(pg, store, provider, permissive)
    owner = make_user(pg)
    up = add_upload(pg, store, owner)
    job, _ = orch.submit(owner, request_for(up), "key-aaaaaaaa")
    orch.dispatch(job["job_id"])
    finish_run(provider, "run-1", test_double=True)
    done = orch.reconcile(job["job_id"])
    assert done["state"] == "completed"
    with pg.transaction() as tx:
        v = tx.one(
            "select provenance from asset_versions where version_id = CAST(:v AS uuid)", v=done["result_version_id"]
        )
    assert (
        v["provenance"]["ai_inference"] is False and v["provenance"]["test_double"] is True
    )  # labelled, never passed off as inference


# --------------------------------------------------------------------------------------------- failures, retries, no double send
def test_a_provider_refusal_fails_the_job_and_gives_the_credits_back(env, pg):
    orch, provider, owner, upload = env
    provider.submit_errors = [ProviderRejected("the GPU provider refused the job (HTTP 401)")]
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    out = orch.dispatch(job["job_id"])
    assert out["state"] == "failed" and out["error_code"] == "provider_rejected"
    assert balance(pg, owner) == {"balance": 100, "reserved": 0} and ledger_kinds(pg, job["job_id"]) == [
        "reserve",
        "release",
    ]


def test_a_refusal_that_started_nothing_is_retried_once_after_the_backoff(env, pg):
    orch, provider, owner, upload = env
    provider.submit_errors = [ProviderRejected("busy", retryable=True)]
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    out = orch.dispatch(job["job_id"])
    assert out["state"] == "queued" and out["attempt"] == 1 and provider.submits == 1
    assert orch.reconcile(job["job_id"])["state"] == "queued"  # backoff not over: not sent yet
    age(pg, job["job_id"], 5)
    out = orch.reconcile(job["job_id"])
    assert out["state"] == "initializing" and out["attempt"] == 2 and provider.submits == 2
    assert balance(pg, owner) == {"balance": 90, "reserved": 10}  # still one reservation


def test_retries_stop_at_max_attempts(env, pg):
    orch, provider, owner, upload = env
    provider.submit_errors = [ProviderRejected("busy", retryable=True), ProviderRejected("busy", retryable=True)]
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    orch.dispatch(job["job_id"])
    age(pg, job["job_id"], 5)
    out = orch.reconcile(job["job_id"])
    assert out["state"] == "failed" and provider.submits == 2
    assert ledger_kinds(pg, job["job_id"]) == ["reserve", "release"]


def test_an_ambiguous_dispatch_is_never_sent_again_and_ends_after_the_grace(env, pg):
    orch, provider, owner, upload = env
    provider.submit_errors = [ProviderAmbiguous("no answer")]
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    out = orch.dispatch(job["job_id"])
    assert out["state"] == "initializing" and out["provider_run_id"] is None
    assert orch.reconcile(job["job_id"])["state"] == "initializing"  # inside the grace window
    age(pg, job["job_id"], 60)
    out = orch.reconcile(job["job_id"])
    assert out["state"] == "failed" and out["error_code"] == "dispatch_uncertain"
    assert provider.submits == 1  # never resent
    assert balance(pg, owner) == {"balance": 100, "reserved": 0}


def test_an_ambiguous_dispatch_whose_run_actually_finished_is_recovered_from_storage(env, pg):
    orch, provider, owner, upload = env
    provider.submit_errors = [ProviderAmbiguous("no answer")]
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    orch.dispatch(job["job_id"])
    # the request had in fact reached RunPod: a worker ran and wrote its outputs, but we never learned the run id
    from tests.cloud.support import upload_as_worker

    upload_as_worker(orch.worker_input(jobs_get(pg, job["job_id"]), _upload_row(pg, upload)))
    out = orch.reconcile(job["job_id"])
    assert out["state"] == "completed" and balance(pg, owner) == {"balance": 90, "reserved": 0}


def jobs_get(pg, job_id):
    with pg.transaction() as tx:
        return jobs.get(tx, job_id)


def _upload_row(pg, upload_id):
    with pg.transaction() as tx:
        return tx.one("select * from uploads where upload_id = CAST(:u AS uuid)", u=str(upload_id))


def test_a_finished_run_the_provider_forgot_is_recovered_from_the_storage_marker(env, pg):
    orch, provider, owner, upload = env
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    orch.dispatch(job["job_id"])
    finish_run(provider, "run-1")
    del provider.runs["run-1"]  # RunPod keeps /run results for 30 minutes; after that its status answer is 404
    out = orch.reconcile(job["job_id"])
    assert out["state"] == "completed"


def test_a_provider_that_lost_the_run_and_left_no_marker_fails_after_the_grace(env, pg):
    orch, provider, owner, upload = env
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    orch.dispatch(job["job_id"])
    del provider.runs["run-1"]
    assert orch.reconcile(job["job_id"])["state"] == "initializing"
    age(pg, job["job_id"], 60)
    out = orch.reconcile(job["job_id"])
    assert out["state"] == "failed" and out["error_code"] == "provider_lost"
    assert balance(pg, owner)["balance"] == 100


def test_provider_status_outage_changes_nothing(env):
    orch, provider, owner, upload = env
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    orch.dispatch(job["job_id"])
    provider.status_error = ProviderUnavailable("down")
    assert orch.reconcile(job["job_id"])["state"] == "initializing"


def test_a_failed_run_reports_the_workers_reason_and_releases_credits(env, pg):
    orch, provider, owner, upload = env
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    orch.dispatch(job["job_id"])
    run = provider.runs["run-1"]
    run.state, run.error = (
        "failed",
        '{"code":"cutout_failed","message":"No clear subject was found in the image.","retryable":false}',
    )
    out = orch.reconcile(job["job_id"])
    assert out["state"] == "failed" and out["error_code"] == "cutout_failed"
    assert "No clear subject" in out["error_message"]
    assert balance(pg, owner) == {"balance": 100, "reserved": 0}


def test_a_retryable_worker_error_is_requeued_once(env, pg):
    orch, provider, owner, upload = env
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    orch.dispatch(job["job_id"])
    run = provider.runs["run-1"]
    run.state, run.error = (
        "failed",
        '{"code":"download_failed","message":"The image could not be fetched.","retryable":true}',
    )
    assert orch.reconcile(job["job_id"])["state"] == "queued"
    age(pg, job["job_id"], 5)
    out = orch.reconcile(job["job_id"])
    assert out["state"] == "initializing" and provider.submits == 2
    run2 = provider.runs["run-2"]
    run2.state, run2.error = "failed", '{"code":"download_failed","message":"again","retryable":true}'
    out = orch.reconcile(job["job_id"])
    assert out["state"] == "failed" and provider.submits == 2  # out of attempts
    assert balance(pg, owner) == {"balance": 100, "reserved": 0}


@pytest.mark.parametrize(("state", "code"), [("timed_out", "run_timed_out"), ("cancelled", "provider_cancelled")])
def test_provider_timeout_and_provider_cancel_fail_the_job(env, pg, state, code):
    orch, provider, owner, upload = env
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    orch.dispatch(job["job_id"])
    provider.runs["run-1"].state = state
    out = orch.reconcile(job["job_id"])
    assert out["state"] == "failed" and out["error_code"] == code and balance(pg, owner)["balance"] == 100


# --------------------------------------------------------------------------------------------------------------- deadlines
def test_a_run_past_its_deadline_is_cancelled_and_not_charged(env, pg):
    orch, provider, owner, upload = env
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    orch.dispatch(job["job_id"])
    provider.runs["run-1"].state = "running"
    expire(pg, job["job_id"])
    out = orch.reconcile(job["job_id"])
    assert out["state"] == "failed" and out["error_code"] == "deadline_exceeded"
    assert provider.cancels == ["run-1"] and balance(pg, owner)["balance"] == 100


def test_a_run_that_finished_just_before_the_deadline_still_counts(env, pg):
    orch, provider, owner, upload = env
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    orch.dispatch(job["job_id"])
    finish_run(provider, "run-1")
    expire(pg, job["job_id"])
    assert (
        orch.reconcile(job["job_id"])["state"] == "completed"
    )  # the provider is read first: finished work is not thrown away


def test_a_queued_job_that_waited_past_its_deadline_is_failed_not_sent(env, pg):
    orch, provider, owner, upload = env
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    expire(pg, job["job_id"])
    out = orch.reconcile(job["job_id"])
    assert out["state"] == "failed" and provider.submits == 0 and balance(pg, owner)["balance"] == 100


# ------------------------------------------------------------------------------------------------------------------ cancel
def test_cancel_before_dispatch(env, pg):
    orch, provider, owner, upload = env
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    out = orch.cancel(owner, uuid.UUID(job["job_id"]))
    assert out["state"] == "cancelled" and provider.submits == 0
    assert ledger_kinds(pg, job["job_id"]) == ["reserve", "release"] and balance(pg, owner)["balance"] == 100


def test_cancel_while_running_stops_the_run(env, pg):
    orch, provider, owner, upload = env
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    orch.dispatch(job["job_id"])
    provider.runs["run-1"].state = "running"
    out = orch.cancel(owner, uuid.UUID(job["job_id"]))
    assert out["state"] == "cancelled" and provider.cancels == ["run-1"]
    assert balance(pg, owner) == {"balance": 100, "reserved": 0}


def test_cancel_wins_even_if_the_run_finished_meanwhile(env, pg):
    orch, provider, owner, upload = env
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    orch.dispatch(job["job_id"])
    finish_run(provider, "run-1")
    out = orch.cancel(owner, uuid.UUID(job["job_id"]))
    assert out["state"] == "cancelled" and balance(pg, owner)["balance"] == 100


def test_cancel_is_retried_when_the_provider_cannot_be_reached(env, pg):
    orch, provider, owner, upload = env
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    orch.dispatch(job["job_id"])
    provider.cancel_error = ProviderUnavailable("down")
    out = orch.cancel(owner, uuid.UUID(job["job_id"]))
    assert (
        out["state"] == "initializing" and out["cancel_requested"] is True
    )  # recorded, will be finished by the next reconcile
    provider.cancel_error = None
    assert orch.reconcile(job["job_id"])["state"] == "cancelled"


def test_cancel_is_idempotent_and_owner_scoped(env, pg):
    orch, _, owner, upload = env
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    assert orch.cancel(owner, uuid.UUID(job["job_id"]))["state"] == "cancelled"
    assert orch.cancel(owner, uuid.UUID(job["job_id"]))["state"] == "cancelled"
    assert balance(pg, owner)["balance"] == 100
    stranger = make_user(pg)
    with pytest.raises(NotFound):
        orch.cancel(stranger, uuid.UUID(job["job_id"]))
    assert orch.get(job["job_id"], stranger) is None


def test_a_job_being_saved_cannot_be_cancelled(env, pg):
    orch, provider, owner, upload = env
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    orch.dispatch(job["job_id"])
    with pg.transaction() as tx:
        jobs.transition(tx, job["job_id"], "validating_output", from_states=["initializing"])
    with pytest.raises(Conflict) as e:
        orch.cancel(owner, uuid.UUID(job["job_id"]))
    assert e.value.code == "too_late_to_cancel"


# ---------------------------------------------------------------------------------------------------------------- concurrency
def test_many_processes_reconciling_one_finished_job_record_it_once(env, pg):
    orch, provider, owner, upload = env
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    orch.dispatch(job["job_id"])
    finish_run(provider, "run-1")
    outs, errors = [], []

    def go():
        try:
            outs.append(orch.reconcile(job["job_id"]))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert orch.get(job["job_id"])["state"] == "completed"
    with pg.transaction() as tx:
        assert tx.one("select count(*) as n from assets")["n"] == 1
        assert tx.one("select count(*) as n from asset_versions")["n"] == 1
    assert ledger_kinds(pg, job["job_id"]) == ["reserve", "capture"] and balance(pg, owner) == {
        "balance": 90,
        "reserved": 0,
    }


def test_an_ingest_whose_process_died_is_taken_over_exactly_once(env, pg):
    orch, provider, owner, upload = env
    job, _ = orch.submit(owner, request_for(upload), "key-aaaaaaaa")
    orch.dispatch(job["job_id"])
    finish_run(provider, "run-1")
    with pg.transaction() as tx:  # a process claimed the ingest, then died
        jobs.transition(tx, job["job_id"], "validating_output", from_states=["initializing"])
    assert orch.reconcile(job["job_id"])["state"] == "validating_output"  # fresh: someone is presumably working on it
    age(pg, job["job_id"], 120)
    outs = []
    threads = [threading.Thread(target=lambda: outs.append(orch.reconcile(job["job_id"]))) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert orch.get(job["job_id"])["state"] == "completed"
    with pg.transaction() as tx:
        assert tx.one("select count(*) as n from assets")["n"] == 1


def test_reconcile_active_isolates_failures_and_counts(env, pg):
    orch, provider, owner, upload = env
    a, _ = orch.submit(owner, request_for(upload), "key-aaaaaaa1")
    b, _ = orch.submit(owner, request_for(upload), "key-aaaaaaa2")
    orch.dispatch(a["job_id"])
    orch.dispatch(b["job_id"])
    finish_run(provider, "run-1")
    counts = orch.reconcile_active()
    assert counts["seen"] == 2 and counts["finished"] == 1 and counts["errors"] == 0
    assert orch.get(a["job_id"])["state"] == "completed" and orch.get(b["job_id"])["state"] == "initializing"
