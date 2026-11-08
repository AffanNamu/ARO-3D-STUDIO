"""Job persistence and the state machine. PostgreSQL is the source of truth; every change is a compare-and-set so two processes (or a
request and the reconciler) can never both win the same transition, and every transition leaves an event row."""

from __future__ import annotations

import uuid
from typing import Any

from aro_cloud.db import Tx, jdump

STATES = (
    "created",
    "validating",
    "queued",
    "initializing",
    "generating",
    "processing",
    "validating_output",
    "uploading",
    "completed",
    "failed",
    "cancelled",
)
TERMINAL = ("completed", "failed", "cancelled")
ACTIVE = tuple(s for s in STATES if s not in TERMINAL)
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "created": ("validating", "failed", "cancelled"),
    "validating": ("queued", "failed", "cancelled"),
    "queued": ("initializing", "failed", "cancelled"),
    "initializing": (
        "generating",
        "processing",
        "validating_output",
        "queued",
        "failed",
        "cancelled",
    ),  # queued: a retry
    "generating": ("processing", "validating_output", "queued", "failed", "cancelled"),
    "processing": ("validating_output", "queued", "failed", "cancelled"),
    "validating_output": ("uploading", "failed"),
    "uploading": ("completed", "failed"),
}
SETTABLE = {
    "error_code",
    "error_message",
    "provider",
    "provider_run_id",
    "dispatch_started_at",
    "started_at",
    "finished_at",
    "result_version_id",
    "cost_usd_estimated",
    "cost_usd_actual",
    "cancel_requested",
}
RAW_NOW = object()  # marker: set the column to now() (database time)

# one query shape everywhere: the job plus database-side ages, so no decision depends on this machine's clock
SELECT_JOB = """
select j.*, j.state::text as state_text,
       (now() > j.deadline_at) as past_deadline,
       (now() > j.deadline_at + interval '10 minutes') as past_ingest_deadline,
       extract(epoch from (j.deadline_at - now())) as remaining_s,
       extract(epoch from (now() - j.updated_at)) as idle_s,
       extract(epoch from (now() - j.dispatch_started_at)) as dispatch_age_s
from generation_jobs j
"""


def allowed_from(to: str) -> list[str]:
    return [s for s, tos in TRANSITIONS.items() if to in tos]


def get(tx: Tx, job_id: uuid.UUID | str, owner: uuid.UUID | str | None = None) -> dict[str, Any] | None:
    sql = SELECT_JOB + " where j.job_id = CAST(:id AS uuid)"
    params: dict[str, Any] = {"id": str(job_id)}
    if owner is not None:
        sql += " and j.owner_id = CAST(:o AS uuid)"
        params["o"] = str(owner)
    row = tx.one(sql, **params)
    return _norm(row) if row else None


def list_for_owner(tx: Tx, owner: uuid.UUID, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    rows = tx.all(
        SELECT_JOB + " where j.owner_id = CAST(:o AS uuid) order by j.created_at desc limit :l offset :f",
        o=str(owner),
        l=limit,
        f=offset,
    )
    return [_norm(r) for r in rows]


def active_count(tx: Tx, owner: uuid.UUID) -> int:
    row = tx.one(
        "select count(*) as n from generation_jobs where owner_id = CAST(:o AS uuid) and state::text = any(CAST(:a AS text[]))",
        o=str(owner),
        a=list(ACTIVE),
    )
    return int(row["n"]) if row else 0


def events(tx: Tx, job_id: uuid.UUID | str) -> list[dict[str, Any]]:
    return tx.all(
        "select at, from_state::text as from_state, to_state::text as to_state, detail from job_events where job_id = CAST(:id AS uuid) order by event_id",
        id=str(job_id),
    )


def add_event(
    tx: Tx, job_id: uuid.UUID | str, from_state: str | None, to_state: str, detail: dict[str, Any] | None = None
) -> None:
    tx.execute(
        "insert into job_events (job_id, from_state, to_state, detail) values (CAST(:id AS uuid), CAST(:f AS job_state), CAST(:t AS job_state), CAST(:d AS jsonb))",
        id=str(job_id),
        f=from_state,
        t=to_state,
        d=jdump(detail or {}),
    )


def transition(
    tx: Tx,
    job_id: uuid.UUID | str,
    to: str,
    *,
    from_states: list[str] | tuple[str, ...] | None = None,
    message: str | None = None,
    progress: float | None = None,
    detail: dict[str, Any] | None = None,
    **cols: Any,
) -> dict[str, Any] | None:
    """Atomically move a job to ``to`` if it is currently in one of ``from_states`` (default: every state the machine allows it from).
    Returns the updated row, or None when someone else got there first."""
    legal = allowed_from(to)
    froms = legal if from_states is None else [s for s in from_states if s in legal]
    if not froms:
        raise ValueError(f"no legal transition into '{to}' from {from_states}")
    sets = ["state = CAST(:to AS job_state)", "updated_at = now()"]
    params: dict[str, Any] = {"id": str(job_id), "to": to, "froms": froms}
    if message is not None:
        sets.append("status_message = :msg")
        params["msg"] = message[:500]
    if progress is not None:
        sets.append("progress = :prog")
        params["prog"] = round(float(progress), 3)
    for name, value in cols.items():
        if name not in SETTABLE:
            raise ValueError(f"column '{name}' cannot be set through a transition")
        if value is RAW_NOW:
            sets.append(f"{name} = now()")
        else:
            sets.append(f"{name} = :c_{name}")
            params[f"c_{name}"] = value
    row = tx.one(
        f"""
        with cur as (
          select job_id, state from generation_jobs
          where job_id = CAST(:id AS uuid) and state::text = any(CAST(:froms AS text[])) for update
        )
        update generation_jobs j set {", ".join(sets)} from cur where j.job_id = cur.job_id
        returning j.*, cur.state::text as previous_state
        """,  # noqa: S608  # nosec B608 - column names come from the SETTABLE whitelist; values are bound parameters
        **params,
    )
    if row is None:
        return None
    add_event(tx, job_id, row["previous_state"], to, {**(detail or {}), **({"message": message} if message else {})})
    return _norm(row)


def touch(
    tx: Tx,
    job_id: uuid.UUID | str,
    state: str,
    *,
    message: str | None = None,
    progress: float | None = None,
    **cols: Any,
) -> bool:
    """Update progress/message/columns WITHOUT changing the state (and without an event). True if the job is still in ``state``."""
    sets = ["updated_at = now()"]
    params: dict[str, Any] = {"id": str(job_id), "s": state}
    if message is not None:
        sets.append("status_message = :msg")
        params["msg"] = message[:500]
    if progress is not None:
        sets.append("progress = :prog")
        params["prog"] = round(float(progress), 3)
    for name, value in cols.items():
        if name not in SETTABLE:
            raise ValueError(f"column '{name}' cannot be set")
        sets.append(f"{name} = {'now()' if value is RAW_NOW else f':c_{name}'}")
        if value is not RAW_NOW:
            params[f"c_{name}"] = value
    n = tx.execute(
        f"update generation_jobs set {', '.join(sets)} where job_id = CAST(:id AS uuid) and state::text = :s",  # noqa: S608  # nosec B608 - whitelisted names
        **params,
    )
    return n == 1


def _norm(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["state"] = out.get("state_text") or str(out["state"])
    for k in ("job_id", "owner_id", "project_id", "upload_id", "result_version_id"):
        if out.get(k) is not None:
            out[k] = str(out[k])
    if out.get("progress") is not None:
        out["progress"] = float(out["progress"])
    return out


def claim_stale(tx: Tx, job_id: uuid.UUID | str, state: str, seen_updated_at: Any) -> bool:
    """Take over work another process abandoned: succeeds for exactly one caller, because ``updated_at`` is the optimistic token."""
    n = tx.execute(
        "update generation_jobs set updated_at = now() where job_id = CAST(:id AS uuid) and state::text = :s and updated_at = :u",
        id=str(job_id),
        s=state,
        u=seen_updated_at,
    )
    return n == 1


def bump_attempt(tx: Tx, job_id: uuid.UUID | str) -> int:
    row = tx.one(
        "update generation_jobs set attempt = attempt + 1 where job_id = CAST(:id AS uuid) returning attempt",
        id=str(job_id),
    )
    return int(row["attempt"]) if row else 0
