"""Profiles and credit accounts. Credits only ever change through the SQL functions (reserve / capture / release / grant), which append to
an immutable ledger and are callable by the server role only."""

from __future__ import annotations

import uuid
from typing import Any

from aro_cloud.db import Tx


def ensure_account(tx: Tx, user: uuid.UUID, signup_credits: int = 0) -> bool:
    """Create the profile and credit account on a user's first request. Returns True when the user is new."""
    new = (
        tx.execute(
            "insert into profiles (user_id) values (CAST(:u AS uuid)) on conflict (user_id) do nothing", u=str(user)
        )
        == 1
    )
    tx.execute(
        "insert into credit_accounts (user_id) values (CAST(:u AS uuid)) on conflict (user_id) do nothing", u=str(user)
    )
    if new and signup_credits > 0:
        tx.one("select grant_credits(CAST(:u AS uuid), :n, 'signup credits') as bal", u=str(user), n=signup_credits)
    return new


def balance(tx: Tx, user: uuid.UUID) -> dict[str, int]:
    row = tx.one("select balance, reserved from credit_accounts where user_id = CAST(:u AS uuid)", u=str(user))
    return {"balance": int(row["balance"]), "reserved": int(row["reserved"])} if row else {"balance": 0, "reserved": 0}


def ledger(tx: Tx, user: uuid.UUID, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    rows = tx.all(
        "select entry_id, kind::text as kind, amount, balance_after, job_id, note, at from credit_ledger "
        "where user_id = CAST(:u AS uuid) order by entry_id desc limit :l offset :o",
        u=str(user),
        l=limit,
        o=offset,
    )
    for r in rows:
        r["job_id"] = str(r["job_id"]) if r["job_id"] else None
    return rows
