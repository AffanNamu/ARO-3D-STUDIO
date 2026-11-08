"""Job orchestration: submit, dispatch, reconcile, ingest, cancel.

The invariants this module exists to keep (each is tested against a real PostgreSQL in tests/cloud):

* A job costs credits exactly once. Credits are reserved in the same transaction that creates the job, captured in the same transaction
  that records the finished asset, and released in the same transaction that marks the job failed or cancelled. No other code path
  moves credits.
* A GPU run is started at most once per attempt. ``dispatch_started_at`` is written before the provider is called. An ambiguous answer
  (timeout, 5xx) is never answered by sending the job again; only a refusal that provably started nothing is retried.
* A provider's answer is not a result. The GLB is downloaded from storage and validated (``output_gate``) before the job completes.
* Every state change is a compare-and-set, so a request, the scheduler and a second API instance can all call ``reconcile`` on the same
  job without double-processing it.
* The database clock decides every deadline.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

import pg8000.exceptions

from aro_cloud import accounts, jobs, keys
from aro_cloud.db import Database, Tx, jdump
from aro_cloud.errors import Conflict, InvalidRequest, NotFound, PaymentRequired, TooManyRequests, Unavailable
from aro_cloud.jobs import RAW_NOW
from aro_cloud.output_gate import GateResult, validate_glb
from aro_cloud.providers.base import (
    ModelProvider,
    ProviderAmbiguous,
    ProviderRejected,
    ProviderStatus,
    ProviderUnavailable,
)
from aro_cloud.schemas import CreateGeneration, WorkerResult
from aro_cloud.settings import CloudSettings
from aro_cloud.storage import ObjectStore, ObjectTooLarge, StorageError

log = logging.getLogger("aro_cloud.orchestrator")

_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:\-]{8,128}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
SMALL_FILE_BYTES = 5_000_000
MARKER_BYTES = 262_144
# provider role -> files.role (report.json and result.json stay in storage; the report is copied into the version's validation record)
FILE_ROLE = {"raw_mesh": "raw_mesh", "glb": "glb", "thumbnail": "thumbnail"}


class _Rejected(Exception):
    """The worker's output is permanently unusable (as opposed to a storage hiccup, which is retried)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class _Lost(Exception):
    """Another process finished this transition first; roll back everything this transaction did."""


@dataclass
class _Verified:
    files: dict[str, tuple[str, bytes, str]]  # role -> (storage key, bytes, sha256)
    gate: GateResult
    report: dict[str, Any] | None


def pg_message(e: BaseException) -> str:
    """The server's message from a pg8000 error (never shown to clients; used to recognise our own SQL exceptions)."""
    a = e.args[0] if e.args else None
    if isinstance(a, dict):
        return str(a.get("M", ""))
    return str(a or "")


def clean_text(s: Any, limit: int = 300) -> str:
    return _CONTROL.sub(" ", str(s))[:limit].strip()


class Orchestrator:
    def __init__(self, db: Database, store: ObjectStore, provider: ModelProvider, settings: CloudSettings):
        self.db = db
        self.store = store
        self.provider = provider
        self.s = settings

    # ===================================================================================================== submit
    def submit(self, owner: uuid.UUID, body: CreateGeneration, idempotency_key: str) -> tuple[dict[str, Any], bool]:
        """Create a job (credits reserved, state ``queued``). Returns (job, created); a repeat of the same key + request returns the first."""
        if not _IDEMPOTENCY_KEY.match(idempotency_key or ""):
            raise InvalidRequest(
                "The Idempotency-Key header must be 8 to 128 characters (letters, digits and . _ : -).",
                recommended_action="Send a fresh random value (for example a UUID) with every new generation request.",
                code="invalid_idempotency_key",
            )
        if body.engine not in self.s.engines:
            raise InvalidRequest(
                f"The engine '{body.engine}' is not offered by this deployment.",
                details={"offered": self.s.engines},
                code="engine_not_offered",
            )
        request = body.model_dump(mode="json")
        sha = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        price = self.s.price_image_to_3d
        try:
            with self.db.transaction() as tx:
                accounts.ensure_account(tx, owner, self.s.signup_credits)
                tx.one(
                    "select pg_advisory_xact_lock(hashtextextended(:k, 0)) as locked", k=f"submit:{owner}"
                )  # serialises one user's submissions
                prior = tx.one(
                    "select job_id, request_sha256 from generation_jobs where owner_id = CAST(:o AS uuid) and idempotency_key = :k",
                    o=str(owner),
                    k=idempotency_key,
                )
                if prior:
                    if prior["request_sha256"] != sha:
                        raise Conflict(
                            "This Idempotency-Key was already used for a different request.",
                            recommended_action="Use a new Idempotency-Key for a new generation.",
                            code="idempotency_key_reused",
                        )
                    return _must(jobs.get(tx, prior["job_id"], owner)), False
                self._check_engine(tx, body.engine)
                up = tx.one(
                    "select upload_id from uploads where upload_id = CAST(:u AS uuid) and owner_id = CAST(:o AS uuid)",
                    u=str(body.upload_id),
                    o=str(owner),
                )
                if not up:
                    raise NotFound(
                        "That upload does not exist.",
                        recommended_action="Upload the image again.",
                        code="upload_not_found",
                    )
                if body.project_id and not tx.one(
                    "select 1 as ok from projects where project_id = CAST(:p AS uuid) and owner_id = CAST(:o AS uuid) and status = 'active'",
                    p=str(body.project_id),
                    o=str(owner),
                ):
                    raise NotFound("That project does not exist.", code="project_not_found")
                if jobs.active_count(tx, owner) >= self.s.max_active_jobs_per_user:
                    raise TooManyRequests(
                        f"You already have {self.s.max_active_jobs_per_user} generations running.",
                        recommended_action="Wait for one to finish, or cancel it.",
                        code="too_many_active_jobs",
                    )
                bal = accounts.balance(tx, owner)["balance"]
                if bal < price:
                    raise PaymentRequired(
                        f"A generation costs {price} credits and you have {bal}.",
                        recommended_action="Add credits to continue.",
                        details={"price": price, "balance": bal},
                    )
                row = tx.one(
                    """
                    insert into generation_jobs (owner_id, project_id, upload_id, name, kind, idempotency_key, request, request_sha256,
                                                 model_id, max_attempts, deadline_at)
                    values (CAST(:o AS uuid), CAST(:p AS uuid), CAST(:u AS uuid), :n, CAST(:k AS job_kind), :ik, CAST(:r AS jsonb), :sha,
                            :m, :ma, now() + CAST(:dl AS integer) * interval '1 second')
                    returning job_id
                    """,
                    o=str(owner),
                    p=str(body.project_id) if body.project_id else None,
                    u=str(body.upload_id),
                    n=body.name,
                    k=body.kind,
                    ik=idempotency_key,
                    r=jdump(request),
                    sha=sha,
                    m=body.engine,
                    ma=self.s.max_attempts,
                    dl=self.s.job_deadline_s,
                )
                assert row is not None
                job_id = row["job_id"]
                jobs.add_event(tx, job_id, None, "created", {"engine": body.engine, "price": price})
                tx.one(
                    "select reserve_credits(CAST(:u AS uuid), CAST(:j AS uuid), :n) as bal",
                    u=str(owner),
                    j=str(job_id),
                    n=price,
                )
                jobs.transition(tx, job_id, "validating", message="Checking your request", progress=0.02)
                queued = jobs.transition(tx, job_id, "queued", message="Waiting for a GPU", progress=0.05)
                assert queued is not None
                return _must(jobs.get(tx, job_id, owner)), True
        except pg8000.exceptions.DatabaseError as e:
            if "insufficient credits" in pg_message(
                e
            ):  # lost a race with another spend; the transaction has rolled back
                raise PaymentRequired(
                    "Not enough credits for this generation.", recommended_action="Add credits to continue."
                ) from None
            raise

    def _check_engine(self, tx: Tx, engine: str) -> None:
        reg = tx.one(
            "select enabled, licence_status::text as licence_status from model_registry where model_id = :m and task = 'image_to_3d'",
            m=engine,
        )
        if not reg or not reg["enabled"] or reg["licence_status"] != "verified":
            raise Unavailable(
                f"The model '{engine}' is not enabled on this deployment.",
                recommended_action="The platform owner must record the licence verification for this model before it can be used.",
                code="model_not_enabled",
            )

    # ================================================================================================== dispatch
    def dispatch(self, job_id: uuid.UUID | str) -> dict[str, Any] | None:
        """Send a queued job to the GPU provider, once. Returns the job as it stands afterwards."""
        with self.db.transaction() as tx:
            job = jobs.get(tx, job_id)
            if not job or job["state"] != "queued":
                return job
            if job["past_deadline"]:
                self._fail(
                    tx,
                    job,
                    "deadline_exceeded",
                    "The generation waited too long for a GPU and was stopped. You were not charged.",
                )
                return jobs.get(tx, job_id)
            cols: dict[str, Any] = {
                "provider": self.provider.name,
                "provider_run_id": None,
                "dispatch_started_at": RAW_NOW,
            }
            if job["attempt"] == 0:
                cols["started_at"] = RAW_NOW
            moved = jobs.transition(
                tx,
                job_id,
                "initializing",
                from_states=["queued"],
                message="Starting the GPU worker",
                progress=0.1,
                **cols,
            )
            if moved is None:  # someone else took it
                return jobs.get(tx, job_id)
            jobs.bump_attempt(tx, job_id)
            upload = tx.one(
                "select upload_id, r2_key, content_type, bytes, sha256 from uploads where upload_id = CAST(:u AS uuid)",
                u=str(job["upload_id"]),
            )
            remaining = int(max(60.0, float(job["remaining_s"])))
        # ---- outside the transaction from here on: network calls never hold a database transaction open ----
        try:
            if upload is None or self.store.head(upload["r2_key"]) is None:
                self._finish(
                    job_id, "failed", "upload_missing", "The uploaded image is no longer available. Upload it again."
                )
                return self.get(job_id)
            payload = self.worker_input(job, upload)
        except StorageError:
            self._requeue_or_fail(job_id, "storage_unavailable", "The image store was not reachable.")
            return self.get(job_id)
        try:
            run_id = self.provider.submit(
                payload, execution_timeout_s=min(self.s.execution_timeout_s, remaining), ttl_s=remaining
            )
        except ProviderRejected as e:
            if getattr(e, "retryable", False):
                self._requeue_or_fail(job_id, "provider_busy", str(e))
            else:
                self._finish(
                    job_id,
                    "failed",
                    "provider_rejected",
                    f"The GPU service refused the job. You were not charged. ({clean_text(e, 120)})",
                )
            return self.get(job_id)
        except ProviderAmbiguous as e:
            log.warning("job %s: ambiguous dispatch (%s); it will not be sent again", job_id, clean_text(e, 120))
            with self.db.transaction() as tx:
                jobs.touch(tx, job_id, "initializing", message="Waiting for the GPU service to confirm the job")
            return self.get(job_id)
        with self.db.transaction() as tx:
            recorded = jobs.touch(tx, job_id, "initializing", provider_run_id=run_id, message="Waiting for a GPU")
        if not recorded:  # the job left 'initializing' while we were calling (failed by the grace rule, or cancelled): stop the orphan run
            self._cancel_quietly(run_id)
        return self.get(job_id)

    def worker_input(self, job: dict[str, Any], upload: dict[str, Any]) -> dict[str, Any]:
        """What the RunPod handler receives: pre-signed URLs for the one input and the fixed output keys. No storage credentials."""
        owner, jid = uuid.UUID(job["owner_id"]), uuid.UUID(job["job_id"])
        ttl = max(self.s.signed_url_ttl_s, self.s.job_deadline_s + 600)
        outputs = {
            role: {"put_url": self.store.presign_put(keys.job_key(owner, jid, role), ttl, ctype), "content_type": ctype}
            for role, (_, ctype) in keys.JOB_FILES.items()
        }
        req = job["request"]
        return {
            "schema_version": 1,
            "job_id": str(jid),
            "kind": req["kind"],
            "engine": req["engine"],
            "image": {
                "get_url": self.store.presign_get(upload["r2_key"], ttl),
                "sha256": upload["sha256"],
                "bytes": upload["bytes"],
                "content_type": upload["content_type"],
            },
            "settings": req["settings"],
            "outputs": outputs,
            "limits": {"max_glb_bytes": self.s.max_glb_mb * 1_000_000},
        }

    # ================================================================================================= reconcile
    def get(self, job_id: uuid.UUID | str, owner: uuid.UUID | None = None) -> dict[str, Any] | None:
        with self.db.transaction() as tx:
            return jobs.get(tx, job_id, owner)

    def reconcile(self, job_id: uuid.UUID | str, *, min_interval_s: float = 0.0) -> dict[str, Any] | None:
        """Move one job as far forward as the facts allow. Safe to call from any process at any time."""
        job = self.get(job_id)
        if job is None or job["state"] in jobs.TERMINAL:
            return job
        state = job["state"]
        if state in (
            "created",
            "validating",
        ):  # submit does both steps in one transaction, so this is a crashed process's leftovers
            if float(job["idle_s"]) > 60:
                self._finish(
                    job_id, "failed", "stuck_before_queue", "The request could not be queued. You were not charged."
                )
            return self.get(job_id)
        if state == "queued":
            if float(job["idle_s"]) >= job["attempt"] * self.s.retry_backoff_s or job["past_deadline"]:
                return self.dispatch(job_id)
            return job
        if state in ("validating_output", "uploading"):
            return self._resume_ingest(job)
        # initializing / generating / processing: a run exists, or may exist
        if float(job["idle_s"]) < min_interval_s:
            return job
        return self._reconcile_running(job)

    def _reconcile_running(self, job: dict[str, Any]) -> dict[str, Any] | None:
        job_id = job["job_id"]
        run_id = job["provider_run_id"]
        if job["cancel_requested"]:
            return self._finish_cancel(job)
        if not run_id:
            marker = self._marker(job)
            if marker is not None:
                return self.ingest(job_id, marker, execution_ms=None)
            if job["past_deadline"] or float(job["dispatch_age_s"] or 0) > self.s.dispatch_grace_s:
                code = "deadline_exceeded" if job["past_deadline"] else "dispatch_uncertain"
                self._finish(
                    job_id,
                    "failed",
                    code,
                    "The GPU service never confirmed this job, so it was stopped and you were not charged. Please try again.",
                )
            return self.get(job_id)
        try:
            st = self.provider.status(run_id)
        except ProviderUnavailable as e:
            log.warning("job %s: provider status unavailable (%s)", job_id, clean_text(e, 100))
            if job["past_ingest_deadline"]:
                self._finish(
                    job_id,
                    "failed",
                    "provider_unreachable",
                    "The GPU service could not be reached before the time limit. You were not charged.",
                )
            return self.get(job_id)
        if st.state == "succeeded":
            result = _result_from(st) or self._marker(job)
            if result is None:
                self._finish(
                    job_id, "failed", "no_result", "The GPU run finished but returned no result. You were not charged."
                )
                return self.get(job_id)
            return self.ingest(job_id, result, execution_ms=st.execution_ms)
        if st.state in ("failed", "timed_out", "cancelled"):
            return self._on_run_ended(job, st)
        if job[
            "past_deadline"
        ]:  # read the provider first (above), then stop it: never pay for a run the user can no longer receive
            self._cancel_quietly(run_id)
            self._finish(
                job_id,
                "failed",
                "deadline_exceeded",
                "The generation took too long and was stopped. You were not charged.",
            )
            return self.get(job_id)
        if st.state == "unknown":
            marker = self._marker(job)
            if marker is not None:
                return self.ingest(job_id, marker, execution_ms=None)
            if float(job["dispatch_age_s"] or 0) > self.s.dispatch_grace_s:
                self._finish(
                    job_id, "failed", "provider_lost", "The GPU service lost track of this job. You were not charged."
                )
            return self.get(job_id)
        with self.db.transaction() as tx:
            if st.state == "running":
                if job["state"] == "initializing":
                    jobs.transition(
                        tx,
                        job_id,
                        "generating",
                        from_states=["initializing"],
                        message="Generating your 3D model",
                        progress=0.2,
                    )
                else:
                    jobs.touch(tx, job_id, job["state"], message="Generating your 3D model")
            else:
                jobs.touch(tx, job_id, job["state"], message="Waiting for a GPU")
        return self.get(job_id)

    def _on_run_ended(self, job: dict[str, Any], st: ProviderStatus) -> dict[str, Any] | None:
        job_id = job["job_id"]
        if st.state == "cancelled":
            if job["cancel_requested"]:
                self._finish(job_id, "cancelled", None, "Cancelled")
            else:
                self._finish(
                    job_id, "failed", "provider_cancelled", "The GPU service cancelled this job. You were not charged."
                )
            return self.get(job_id)
        if st.state == "timed_out":
            self._finish(
                job_id, "failed", "run_timed_out", "The GPU run exceeded its time limit. You were not charged."
            )
            return self.get(job_id)
        code, message, retryable = _worker_error(st)
        if retryable:
            self._requeue_or_fail(
                job_id, code, message, fail_code=code
            )  # re-queues, or ends the job (and settles credits) when out of attempts
        else:
            self._finish(job_id, "failed", code, f"{message} You were not charged.")
        return self.get(job_id)

    def reconcile_active(self, limit: int = 50) -> dict[str, int]:
        """The scheduler's tick: look at every unfinished job, oldest first. One bad job never stops the others."""
        with self.db.transaction() as tx:
            ids = [
                r["job_id"]
                for r in tx.all(
                    "select job_id from generation_jobs where state::text = any(CAST(:a AS text[])) order by updated_at limit :n",
                    a=list(jobs.ACTIVE),
                    n=limit,
                )
            ]
        counts = {"seen": len(ids), "finished": 0, "errors": 0}
        for jid in ids:
            try:
                after = self.reconcile(jid)
                if after and after["state"] in jobs.TERMINAL:
                    counts["finished"] += 1
            except Exception:  # noqa: BLE001 - isolate the failure; the next tick tries again
                counts["errors"] += 1
                log.exception("reconcile failed for job %s", jid)
        return counts

    # ===================================================================================================== ingest
    def _resume_ingest(self, job: dict[str, Any]) -> dict[str, Any] | None:
        """An ingest that stopped making progress (its process died) is taken over by exactly one caller."""
        job_id = job["job_id"]
        if float(job["idle_s"]) < self.s.ingest_stale_s:
            return job
        if job["past_ingest_deadline"]:
            self._finish(
                job_id,
                "failed",
                "ingest_timeout",
                "The finished model could not be saved in time. You were not charged.",
            )
            return self.get(job_id)
        with self.db.transaction() as tx:
            mine = jobs.claim_stale(tx, job_id, job["state"], job["updated_at"])
        if not mine:
            return self.get(job_id)
        marker = self._marker(job)
        if marker is None:
            self._finish(job_id, "failed", "no_result", "The finished model could not be found. You were not charged.")
            return self.get(job_id)
        return self.ingest(job_id, marker, execution_ms=None, resumed=True)

    def ingest(
        self, job_id: uuid.UUID | str, result: WorkerResult, *, execution_ms: int | None, resumed: bool = False
    ) -> dict[str, Any] | None:
        """Verify the worker's output and, only if it holds, record the asset and settle the credits."""
        if not resumed:
            with self.db.transaction() as tx:
                claimed = jobs.transition(
                    tx,
                    job_id,
                    "validating_output",
                    from_states=["initializing", "generating", "processing"],
                    message="Checking the model",
                    progress=0.9,
                )
            if claimed is None:  # another process is already ingesting it, or it ended
                return self.get(job_id)
        job = _must(self.get(job_id))
        try:
            if not result.ok:
                raise _Rejected("worker_failed", _worker_message(result))
            verified = self._verify_output(job, result)
        except _Rejected as r:
            self._finish(job_id, "failed", r.code, f"{r.message} You were not charged.")
            return self.get(job_id)
        except ObjectTooLarge:
            self._finish(
                job_id,
                "failed",
                "output_too_large",
                "The model file is larger than the platform allows. You were not charged.",
            )
            return self.get(job_id)
        except StorageError as e:  # transient: leave the job in validating_output; a later tick takes it over
            log.warning("job %s: storage error while checking output (%s)", job_id, clean_text(e, 100))
            return self.get(job_id)
        with self.db.transaction() as tx:
            jobs.transition(
                tx, job_id, "uploading", from_states=["validating_output"], message="Saving your model", progress=0.95
            )
        try:
            with self.db.transaction() as tx:
                self._complete(tx, job, result, verified, execution_ms)
        except _Lost:
            pass
        return self.get(job_id)

    def _verify_output(self, job: dict[str, Any], result: WorkerResult) -> _Verified:
        owner, jid = uuid.UUID(job["owner_id"]), uuid.UUID(job["job_id"])
        if result.engine is None or result.engine.id != job["request"]["engine"]:
            raise _Rejected("engine_mismatch", "The result does not come from the engine that was requested.")
        roles = [f.role for f in result.files]
        if len(set(roles)) != len(roles) or any(r not in keys.JOB_FILES or r == "result" for r in roles):
            raise _Rejected("invalid_output", "The result lists files the platform does not accept.")
        missing = [r for r in keys.REQUIRED_ROLES if r != "result" and r not in roles]
        if missing:
            raise _Rejected("invalid_output", f"The result is missing: {', '.join(missing)}.")
        max_glb = self.s.max_glb_mb * 1_000_000
        files: dict[str, tuple[str, bytes, str]] = {}
        gate: GateResult | None = None
        for f in result.files:
            key = keys.job_key(owner, jid, f.role)
            limit = max_glb if f.role in ("glb", "raw_mesh") else SMALL_FILE_BYTES
            if f.bytes > limit:
                raise ObjectTooLarge(f"{f.role} is too large")
            meta = self.store.head(key)
            if meta is None:
                raise _Rejected("output_missing", f"The {f.role} file was not uploaded.")
            data = self.store.get_bytes(key, limit)
            sha = hashlib.sha256(data).hexdigest()
            if len(data) != f.bytes or sha != f.sha256:
                raise _Rejected("output_corrupt", f"The {f.role} file does not match what the worker reported.")
            if f.role == "glb":
                gate = validate_glb(
                    data,
                    claimed_sha256=f.sha256,
                    max_bytes=max_glb,
                    engine_is_test_double=result.engine.test_double,
                    allow_test_double=self.s.allow_test_double,
                )
                if not gate.ok:
                    raise _Rejected(
                        "output_rejected",
                        "The generated model did not pass the quality gate: " + "; ".join(gate.reasons) + ".",
                    )
            elif f.role == "raw_mesh" and data[:4] != b"glTF":
                raise _Rejected("output_corrupt", "The raw mesh is not a GLB file.")
            elif f.role == "thumbnail" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise _Rejected("output_corrupt", "The thumbnail is not a PNG image.")
            files[f.role] = (key, data, sha)
        assert gate is not None
        report: dict[str, Any] | None = None
        if "report" in files:
            try:
                parsed = json.loads(files["report"][1])
                report = parsed if isinstance(parsed, dict) else None
            except ValueError:
                report = None
        return _Verified(files, gate, report)

    def _complete(
        self, tx: Tx, job: dict[str, Any], result: WorkerResult, v: _Verified, execution_ms: int | None
    ) -> None:
        owner, jid = job["owner_id"], job["job_id"]
        req = job["request"]
        up = (
            tx.one("select sha256, upload_id from uploads where upload_id = CAST(:u AS uuid)", u=str(job["upload_id"]))
            if job["upload_id"]
            else None
        )
        engine = result.engine
        assert engine is not None
        ai = not engine.test_double
        asset = tx.one(
            """
            insert into assets (owner_id, project_id, name, category, metadata)
            values (CAST(:o AS uuid), CAST(:p AS uuid), :n, :c, CAST(:m AS jsonb)) returning asset_id
            """,
            o=owner,
            p=job["project_id"],
            n=job["name"],
            c=req["settings"].get("category", "other"),
            m=jdump({"job_id": jid, "upload_id": job["upload_id"], "kind": req["kind"]}),
        )
        assert asset is not None
        validation = {"status": "passed", "warnings": v.gate.warnings, "report": v.report or {}}
        provenance = {
            "engine": engine.id,
            "engine_version": engine.version,
            "provider": job["provider"],
            "ai_inference": ai,
            "test_double": engine.test_double,
            "settings": req["settings"],
            "input_sha256": up["sha256"] if up else None,
            "job_id": jid,
        }
        ver = tx.one(
            """
            insert into asset_versions (asset_id, owner_id, version_no, label, produced_by_job, geometry_stats, validation, provenance)
            values (CAST(:a AS uuid), CAST(:o AS uuid), 1, 'Generated', CAST(:j AS uuid), CAST(:g AS jsonb), CAST(:v AS jsonb), CAST(:p AS jsonb))
            returning version_id
            """,
            a=str(asset["asset_id"]),
            o=owner,
            j=jid,
            g=jdump(v.gate.stats),
            v=jdump(validation),
            p=jdump(provenance),
        )
        assert ver is not None
        for role, (key, data, sha) in v.files.items():
            if role not in FILE_ROLE:
                continue
            tx.execute(
                """
                insert into files (owner_id, version_id, role, r2_key, content_type, bytes, sha256)
                values (CAST(:o AS uuid), CAST(:v AS uuid), :r, :k, :c, :b, :s)
                """,
                o=owner,
                v=str(ver["version_id"]),
                r=FILE_ROLE[role],
                k=key,
                c=keys.JOB_FILES[role][1],
                b=len(data),
                s=sha,
            )
        tx.execute(
            "update assets set current_version_id = CAST(:v AS uuid), updated_at = now() where asset_id = CAST(:a AS uuid)",
            v=str(ver["version_id"]),
            a=str(asset["asset_id"]),
        )
        gpu_s = (execution_ms / 1000.0) if execution_ms else _float(result.stats.get("total_s"))
        cost = round(gpu_s * self.s.gpu_usd_per_second, 5) if gpu_s and self.s.gpu_usd_per_second is not None else None
        done = jobs.transition(
            tx,
            jid,
            "completed",
            from_states=["uploading"],
            message="Your model is ready",
            progress=1.0,
            detail={"asset_id": str(asset["asset_id"]), "triangles": v.gate.stats.get("triangles")},
            result_version_id=str(ver["version_id"]),
            finished_at=RAW_NOW,
            cost_usd_estimated=cost,
        )
        if done is None:
            raise _Lost
        tx.one("select capture_credits(CAST(:u AS uuid), CAST(:j AS uuid)) as r", u=owner, j=jid)
        if gpu_s:
            tx.execute(
                "insert into usage_records (user_id, job_id, metric, quantity, unit, cost_usd) values (CAST(:u AS uuid), CAST(:j AS uuid), 'gpu_seconds', :q, 's', :c)",
                u=owner,
                j=jid,
                q=round(gpu_s, 3),
                c=cost,
            )

    def _marker(self, job: dict[str, Any]) -> WorkerResult | None:
        """The worker writes ``result.json`` last. If the run record is gone (RunPod keeps it 30 minutes), this is how a finished job is found."""
        key = keys.job_key(uuid.UUID(job["owner_id"]), uuid.UUID(job["job_id"]), "result")
        try:
            if self.store.head(key) is None:
                return None
            return WorkerResult.model_validate_json(self.store.get_bytes(key, MARKER_BYTES))
        except (StorageError, ValueError):
            return None

    # ===================================================================================================== cancel
    def cancel(self, owner: uuid.UUID, job_id: uuid.UUID) -> dict[str, Any]:
        for _ in range(3):
            with self.db.transaction() as tx:
                job = jobs.get(tx, job_id, owner)
                if job is None:
                    raise NotFound("That generation does not exist.", code="job_not_found")
                if job["state"] in jobs.TERMINAL:
                    return job
                if job["state"] in ("validating_output", "uploading"):
                    raise Conflict(
                        "The model is already being saved and can no longer be cancelled.",
                        recommended_action="It will be ready in a few seconds.",
                        code="too_late_to_cancel",
                    )
                if job["state"] in ("created", "validating", "queued"):
                    if self._cancel_now(tx, job, "Cancelled before it started") is not None:
                        return _must(jobs.get(tx, job_id, owner))
                    continue  # it moved on while we looked
                jobs.touch(tx, job_id, job["state"], cancel_requested=True, message="Cancelling")
            after = self.reconcile(job_id, min_interval_s=0)
            if after is not None:
                return after
        raise Conflict("The generation changed while it was being cancelled. Try again.", code="cancel_conflict")

    def _cancel_now(self, tx: Tx, job: dict[str, Any], message: str) -> dict[str, Any] | None:
        row = jobs.transition(
            tx,
            job["job_id"],
            "cancelled",
            from_states=["created", "validating", "queued"],
            message=message,
            finished_at=RAW_NOW,
            cancel_requested=True,
        )
        if row is not None:
            tx.one(
                "select release_credits(CAST(:u AS uuid), CAST(:j AS uuid)) as r", u=job["owner_id"], j=job["job_id"]
            )
        return row

    def _finish_cancel(self, job: dict[str, Any]) -> dict[str, Any] | None:
        run_id = job["provider_run_id"]
        if run_id:
            try:
                self.provider.cancel(run_id)
            except ProviderUnavailable as e:
                log.warning("job %s: cancel not confirmed (%s); will retry", job["job_id"], clean_text(e, 100))
                if job["past_ingest_deadline"]:
                    self._finish(job["job_id"], "cancelled", None, "Cancelled")
                return self.get(job["job_id"])
        self._finish(job["job_id"], "cancelled", None, "Cancelled")
        return self.get(job["job_id"])

    # ============================================================================================== settling
    def _finish(self, job_id: uuid.UUID | str, to: str, code: str | None, message: str) -> bool:
        """End a job and settle its credits atomically. ``to`` is failed or cancelled."""
        with self.db.transaction() as tx:
            job = jobs.get(tx, job_id)
            if not job or job["state"] in jobs.TERMINAL:
                return False
            return self._end(tx, job, to, code, message)

    def _fail(self, tx: Tx, job: dict[str, Any], code: str, message: str) -> bool:
        return self._end(tx, job, "failed", code, message)

    def _end(self, tx: Tx, job: dict[str, Any], to: str, code: str | None, message: str) -> bool:
        cols: dict[str, Any] = {"finished_at": RAW_NOW}
        if to == "failed":
            cols.update(error_code=code, error_message=clean_text(message, 480))
        row = jobs.transition(
            tx, job["job_id"], to, message=clean_text(message, 480), detail={"code": code} if code else None, **cols
        )
        if row is None:
            return False
        tx.one(
            "select release_credits(CAST(:u AS uuid), CAST(:j AS uuid)) as r", u=job["owner_id"], j=job["job_id"]
        )  # a no-op if already settled
        return True

    def _requeue_or_fail(
        self, job_id: uuid.UUID | str, reason: str, message: str, *, fail_code: str | None = None
    ) -> bool:
        """Retry a send that provably started nothing (or a worker error flagged retryable); give up when attempts or time run out."""
        with self.db.transaction() as tx:
            job = jobs.get(tx, job_id)
            if not job or job["state"] in jobs.TERMINAL:
                return False
            if (
                job["attempt"] < job["max_attempts"]
                and not job["past_deadline"]
                and not job["cancel_requested"]
                and float(job["remaining_s"]) > 120
            ):
                row = jobs.transition(
                    tx,
                    job_id,
                    "queued",
                    from_states=["initializing", "generating", "processing"],
                    message="Retrying",
                    progress=0.05,
                    detail={"retry_reason": reason},
                    provider_run_id=None,
                )
                if row is not None:
                    return True
            self._end(
                tx,
                job,
                "failed",
                fail_code or "provider_unavailable",
                f"{clean_text(message, 200)} You were not charged.",
            )
            return False

    def _cancel_quietly(self, run_id: str) -> None:
        try:
            self.provider.cancel(run_id)
        except ProviderUnavailable as e:
            log.warning("could not cancel run %s (%s)", run_id, clean_text(e, 100))


# ================================================================================================== helpers
def _must(job: dict[str, Any] | None) -> dict[str, Any]:
    if job is None:
        raise NotFound("That generation does not exist.", code="job_not_found")
    return job


def _float(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _result_from(st: ProviderStatus) -> WorkerResult | None:
    if st.output is None:
        return None
    try:
        return WorkerResult.model_validate(st.output)
    except ValueError:
        return None


def _worker_message(result: WorkerResult) -> str:
    err = result.error or {}
    return clean_text(err.get("message") or "The GPU worker could not generate a model from this image.")


def _worker_error(st: ProviderStatus) -> tuple[str, str, bool]:
    """(code, message, retryable) from a failed run. The handler reports ``{"code", "message", "retryable"}`` as JSON in ``error``."""
    code, message, retryable = "worker_failed", "The GPU worker could not generate a model from this image.", False
    raw = st.error or ""
    try:
        d = json.loads(raw)
    except ValueError:
        d = None
    if isinstance(d, dict):
        code = clean_text(d.get("code") or code, 40) or code
        message = clean_text(d.get("message") or message)
        retryable = bool(d.get("retryable"))
    elif raw:
        message = "The GPU worker failed: " + clean_text(raw, 200)
    return code, message, retryable
