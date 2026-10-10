"""Persistent job queue (spec §11, §29, §44).

* Jobs are rows in SQLite - they survive restarts and failed jobs are NEVER dropped.
* Priority (1 = most urgent … 9), FIFO within a priority, retry with backoff for unexpected errors,
  cancellation (queued: immediate; running: cooperative), cooperative timeouts, structured error reports.
* Long work runs in worker threads, so HTTP requests return immediately and the UI polls / streams progress.
"""

from __future__ import annotations

import builtins
import heapq
import itertools
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from aro_studio.core.cancellation import CancellationToken
from aro_studio.core.enums import JobState
from aro_studio.core.errors import InvalidInputError, NotFoundError, ResourceLimitError, StudioError, explain_exception
from aro_studio.core.ids import new_id, require_id
from aro_studio.db.database import Database, dumps, loads
from aro_studio.observability.logging import get_logger, redact
from aro_studio.observability.metrics import Metrics
from aro_studio.observability.resources import snapshot

log = get_logger("jobs")


@dataclass
class JobContext:
    job_id: str
    kind: str
    params: dict[str, Any]
    project_id: str | None
    asset_id: str | None
    cancel: CancellationToken
    _queue: JobQueue
    annotations: dict[str, Any] = field(default_factory=dict)

    def set_state(self, state: JobState, progress: float | None = None, message: str = "") -> None:
        self._queue._update(self.job_id, state=state, progress=progress, message=message)

    def progress(self, progress: float, message: str = "") -> None:
        self._queue._update(self.job_id, progress=progress, message=message)

    def log(self, message: str, level: str = "INFO") -> None:
        self._queue._event(self.job_id, level, None, message)

    def check(self) -> None:
        self.cancel.check()

    def annotate(self, **kw: Any) -> None:
        """Attach input/model/resource information that must survive a failure."""
        self.annotations.update(kw)


Handler = Callable[[JobContext], dict[str, Any]]


@dataclass
class _Registered:
    fn: Handler
    heavy: bool
    timeout_s: int | None


class JobQueue:
    def __init__(
        self,
        db: Database,
        *,
        workers: int = 1,
        default_timeout_s: int = 1800,
        min_free_disk_mb: int = 500,
        min_free_ram_mb: int = 512,
        data_dir: str = ".",
        metrics: Metrics | None = None,
        backoff_base_s: float = 2.0,
        on_idle: Callable[[], object] | None = None,
    ):
        self.db, self.workers = db, max(1, workers)
        self.default_timeout_s, self.min_free_disk_mb, self.min_free_ram_mb = (
            default_timeout_s,
            min_free_disk_mb,
            min_free_ram_mb,
        )
        self.data_dir, self.metrics, self.backoff_base_s, self.on_idle = (
            data_dir,
            metrics or Metrics(),
            backoff_base_s,
            on_idle,
        )
        self._handlers: dict[str, _Registered] = {}
        self._heap: list[tuple[int, int, float, str]] = []  # (priority, seq, not_before, job_id)
        self._seq = itertools.count()
        self._cv = threading.Condition()
        self._tokens: dict[str, CancellationToken] = {}
        self._threads: list[threading.Thread] = []
        self._stop = False
        self._running: set[str] = set()

    # -- registry -----------------------------------------------------------------------------
    def register(self, kind: str, fn: Handler, *, heavy: bool = False, timeout_s: int | None = None) -> None:
        self._handlers[kind] = _Registered(fn, heavy, timeout_s)

    # -- lifecycle ----------------------------------------------------------------------------
    def start(self) -> None:
        self._recover()
        for i in range(self.workers):
            t = threading.Thread(target=self._worker, name=f"aro-job-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self, timeout: float = 5.0) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        for t in self._threads:
            t.join(timeout)

    def _recover(self) -> None:
        """After a restart: re-queue QUEUED jobs; mark jobs that were mid-flight as FAILED (kept, with reason)."""
        for r in self.db.query(
            "SELECT job_id, state, priority FROM jobs WHERE state NOT IN ('COMPLETED','FAILED','CANCELLED','TIMEOUT','RESOURCE_LIMIT','MODEL_ERROR','INVALID_INPUT','CREATED')"
        ):
            if r["state"] == "QUEUED":
                self._push(r["job_id"], r["priority"])
            else:
                err = {
                    "code": "INTERRUPTED",
                    "message": "The Studio restarted while this job was running.",
                    "recommended_action": "Re-queue the job.",
                }
                self._update(r["job_id"], state=JobState.FAILED, message=err["message"], error=err, finished=True)

    # -- submit / control ---------------------------------------------------------------------
    def submit(
        self,
        kind: str,
        params: dict[str, Any],
        *,
        project_id: str | None = None,
        asset_id: str | None = None,
        priority: int = 5,
        max_retries: int = 0,
    ) -> dict:
        if kind not in self._handlers:
            raise InvalidInputError(
                f"Unknown job kind '{kind}'.", recommended_action=f"Known kinds: {sorted(self._handlers)}"
            )
        if not 1 <= priority <= 9:
            raise InvalidInputError("priority must be 1 (urgent) to 9 (background).")
        jid = new_id("job")
        self.db.execute(
            "INSERT INTO jobs(job_id,kind,project_id,asset_id,state,progress,message,priority,attempts,max_retries,params,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                jid,
                kind,
                project_id,
                asset_id,
                JobState.QUEUED.value,
                0.0,
                "Queued",
                priority,
                0,
                max_retries,
                dumps(params),
                time.time(),
            ),
        )
        self._event(jid, "INFO", JobState.QUEUED.value, f"Job created ({kind}), priority {priority}")
        self._push(jid, priority)
        self.metrics.incr(f"jobs.submitted.{kind}")
        return self.get(jid)

    def _push(self, job_id: str, priority: int, delay_s: float = 0.0) -> None:
        with self._cv:
            heapq.heappush(self._heap, (priority, next(self._seq), time.monotonic() + delay_s, job_id))
            self._cv.notify()

    def cancel(self, job_id: str) -> dict:
        j = self.get(job_id)
        st = JobState(j["state"])
        if st.is_terminal:
            raise InvalidInputError(f"Job is already {st.value}.")
        self.db.execute("UPDATE jobs SET cancel_requested=1 WHERE job_id=?", (job_id,))
        tok = self._tokens.get(job_id)
        if tok:
            tok.cancel()
            self._event(job_id, "INFO", None, "Cancellation requested; stopping at the next checkpoint")
        elif st is JobState.QUEUED:
            self._update(job_id, state=JobState.CANCELLED, message="Cancelled before it started", finished=True)
        return self.get(job_id)

    def requeue(self, job_id: str) -> dict:
        """Re-run a terminal, non-successful job from the start (its history is kept in job_events)."""
        j = self.get(job_id)
        st = JobState(j["state"])
        if not st.is_terminal or st is JobState.COMPLETED:
            raise InvalidInputError("Only failed/cancelled jobs can be re-queued.")
        self.db.execute(
            "UPDATE jobs SET state='QUEUED', progress=0, message='Re-queued', cancel_requested=0, attempts=0, error=NULL, result=NULL, started_at=NULL, finished_at=NULL WHERE job_id=?",
            (job_id,),
        )
        self._event(job_id, "INFO", JobState.QUEUED.value, f"Re-queued after {st.value}")
        self._push(job_id, j["priority"])
        return self.get(job_id)

    # -- queries ------------------------------------------------------------------------------
    @staticmethod
    def _row(r: dict) -> dict:
        for k in ("params", "result", "error", "resources"):
            r[k] = loads(r.get(k))
        r["cancel_requested"] = bool(r["cancel_requested"])
        return r

    def get(self, job_id: str) -> dict:
        require_id(job_id, "job")
        r = self.db.query_one("SELECT * FROM jobs WHERE job_id=?", (job_id,))
        if not r:
            raise NotFoundError("Job not found.")
        return self._row(r)

    def list(
        self, *, state: str | None = None, project_id: str | None = None, kind: str | None = None, limit: int = 100
    ) -> list[dict]:
        sql, p = "SELECT * FROM jobs WHERE 1=1", []
        if state:
            sql += " AND state=?"
            p.append(state)  # noqa: E702
        if project_id:
            sql += " AND project_id=?"
            p.append(project_id)  # noqa: E702
        if kind:
            sql += " AND kind=?"
            p.append(kind)  # noqa: E702
        return [self._row(r) for r in self.db.query(sql + " ORDER BY created_at DESC LIMIT ?", (*p, limit))]

    def events(self, job_id: str, after_id: int = 0) -> builtins.list[dict]:
        require_id(job_id, "job")
        return self.db.query(
            "SELECT id, ts, level, state, message FROM job_events WHERE job_id=? AND id>? ORDER BY id",
            (job_id, after_id),
        )

    def wait(self, job_id: str, timeout: float = 60.0, poll: float = 0.05) -> dict:
        """Block until the job is terminal (used by tests and scripts, not by the web UI)."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            j = self.get(job_id)
            if JobState(j["state"]).is_terminal:
                return j
            time.sleep(poll)
        raise TimeoutError(f"Job {job_id} did not finish within {timeout}s")

    def stats(self) -> dict:
        rows = self.db.query("SELECT state, COUNT(*) c FROM jobs GROUP BY state")
        return {
            "by_state": {r["state"]: r["c"] for r in rows},
            "workers": self.workers,
            "running": len(self._running),
            "queued_in_memory": len(self._heap),
        }

    # -- internals ----------------------------------------------------------------------------
    def _event(self, job_id: str, level: str, state: str | None, message: str) -> None:
        self.db.execute(
            "INSERT INTO job_events(job_id,ts,level,state,message) VALUES (?,?,?,?,?)",
            (job_id, time.time(), level, state, redact(message)[:2000]),
        )

    def _update(
        self,
        job_id: str,
        *,
        state: JobState | None = None,
        progress: float | None = None,
        message: str | None = None,
        error: dict | None = None,
        result: dict | None = None,
        resources: dict | None = None,
        finished: bool = False,
        started: bool = False,
    ) -> None:
        sets: builtins.list[str] = []
        args: builtins.list[Any] = []
        if state is not None:
            sets.append("state=?")
            args.append(state.value)  # noqa: E702
        if progress is not None:
            sets.append("progress=?")
            args.append(max(0.0, min(1.0, progress)))  # noqa: E702
        if message is not None:
            sets.append("message=?")
            args.append(redact(message)[:500])  # noqa: E702
        if error is not None:
            sets.append("error=?")
            args.append(dumps(error))  # noqa: E702
        if result is not None:
            sets.append("result=?")
            args.append(dumps(result))  # noqa: E702
        if resources is not None:
            sets.append("resources=?")
            args.append(dumps(resources))  # noqa: E702
        if finished:
            sets.append("finished_at=?")
            args.append(time.time())  # noqa: E702
        if started:
            sets.append("started_at=?")
            args.append(time.time())  # noqa: E702
        # `sets` only ever contains fixed "column=?" fragments built above; every value is a bound parameter.
        if sets:
            self.db.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE job_id=?", (*args, job_id))  # noqa: S608  # nosec B608
        if state is not None or message:
            self._event(job_id, "INFO", state.value if state else None, message or (state.value if state else ""))

    def _next(self) -> str | None:
        with self._cv:
            while not self._stop:
                if self._heap:
                    pri, _seq, not_before, jid = self._heap[0]
                    wait = not_before - time.monotonic()
                    if wait <= 0:
                        heapq.heappop(self._heap)
                        return jid
                    self._cv.wait(timeout=min(wait, 1.0))
                else:
                    self._cv.wait(timeout=1.0)
                    if self.on_idle:
                        try:
                            self.on_idle()
                        except Exception:  # noqa: BLE001
                            log.exception("on_idle hook failed")
            return None

    def _worker(self) -> None:
        while True:
            jid = self._next()
            if jid is None:
                return
            try:
                self._run(jid)
            except Exception:  # never let a worker die
                log.exception("job worker crashed on %s", jid, extra={"job_id": jid})

    def _run(self, jid: str) -> None:
        j = self.get(jid)
        if JobState(j["state"]).is_terminal:
            return
        if j["cancel_requested"]:
            self._update(jid, state=JobState.CANCELLED, message="Cancelled before it started", finished=True)
            return
        reg = self._handlers.get(j["kind"])
        if reg is None:
            self._update(
                jid,
                state=JobState.FAILED,
                message="No handler registered",
                error={"code": "NO_HANDLER", "message": f"No handler for '{j['kind']}'."},
                finished=True,
            )
            return
        attempts = j["attempts"] + 1
        self.db.execute("UPDATE jobs SET attempts=? WHERE job_id=?", (attempts, jid))
        timeout = reg.timeout_s or self.default_timeout_s
        token = CancellationToken(timeout)
        self._tokens[jid] = token
        self._running.add(jid)
        res_start = snapshot(self.data_dir).to_dict()
        ctx = JobContext(jid, j["kind"], j["params"], j["project_id"], j["asset_id"], token, self)
        t0 = time.perf_counter()
        self._update(
            jid,
            state=JobState.INITIALIZING if j["kind"] == "generation" else JobState.PROCESSING,
            progress=0.0,
            message=f"Started (attempt {attempts})",
            started=True,
            resources={"at_start": res_start},
        )
        try:
            if reg.heavy:
                self._preflight(res_start)
            result = reg.fn(ctx)
            self._update(
                jid,
                state=JobState.COMPLETED,
                progress=1.0,
                message="Completed",
                result=result,
                finished=True,
                resources={
                    "at_start": res_start,
                    "at_end": snapshot(self.data_dir).to_dict(),
                    "seconds": round(time.perf_counter() - t0, 3),
                    **({"annotations": ctx.annotations} if ctx.annotations else {}),
                },
            )
            self.metrics.incr(f"jobs.completed.{j['kind']}")
            self.metrics.observe(f"job.{j['kind']}", time.perf_counter() - t0)
        except BaseException as e:  # noqa: BLE001 - everything is recorded, nothing escapes
            self._fail(jid, j, ctx, e, attempts, res_start, time.perf_counter() - t0)
        finally:
            self._tokens.pop(jid, None)
            self._running.discard(jid)

    def _preflight(self, res: dict) -> None:
        if res["disk_free_mb"] < self.min_free_disk_mb:
            raise ResourceLimitError(
                f"Only {res['disk_free_mb']} MB of disk is free (need {self.min_free_disk_mb} MB).",
                recommended_action="Purge the cache / delete unused exports in Settings, then re-queue the job.",
            )
        if res["ram_available_mb"] < self.min_free_ram_mb:
            raise ResourceLimitError(
                f"Only {res['ram_available_mb']} MB of RAM is available (need {self.min_free_ram_mb} MB).",
                recommended_action="Wait for other work to finish, or use a lower-resource preset, then re-queue.",
            )

    def _fail(
        self, jid: str, j: dict, ctx: JobContext, e: BaseException, attempts: int, res_start: dict, seconds: float
    ) -> None:
        ex = explain_exception(e)
        state = JobState(ex.job_state)
        tb = redact("".join(traceback.format_exception(type(e), e, e.__traceback__))[-4000:])
        error = {
            "code": ex.code,
            "message": ex.message,
            "recommended_action": ex.recommended_action,
            "exception": type(e).__name__,
            "traceback": tb,
            "context": {"params": j["params"], **ctx.annotations},
        }
        if isinstance(e, StudioError) and e.details:
            error["details"] = e.details
        retryable = state is JobState.FAILED and ex.code == "UNEXPECTED_ERROR" and attempts <= j["max_retries"]
        resources = {"at_start": res_start, "at_end": snapshot(self.data_dir).to_dict(), "seconds": round(seconds, 3)}
        if retryable:
            delay = self.backoff_base_s * (2 ** (attempts - 1))
            self._update(
                jid,
                state=JobState.QUEUED,
                progress=0.0,
                message=f"Attempt {attempts} failed ({ex.code}); retrying in {delay:.0f}s",
                error=error,
                resources=resources,
            )
            self._event(jid, "WARNING", JobState.QUEUED.value, tb[-800:])
            self._push(jid, j["priority"], delay)
            self.metrics.incr("jobs.retried")
            return
        self._update(jid, state=state, message=ex.message, error=error, resources=resources, finished=True)
        self._event(jid, "ERROR", state.value, f"{ex.code}: {ex.message} | action: {ex.recommended_action}")
        log.error("job %s %s: %s", jid, state.value, ex.message, extra={"job_id": jid})
        self.metrics.incr(f"jobs.failed.{state.value}")
