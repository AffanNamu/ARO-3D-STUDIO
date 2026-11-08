"""Owner-only operations, run from a terminal with the same environment as the API. Nothing here is reachable over HTTP.

    python -m aro_cloud.admin grant-credits --user <uuid> --amount 100 --note "welcome"
    python -m aro_cloud.admin balance --user <uuid>
    python -m aro_cloud.admin verify-model --model triposg --verified-by "Your Name" --weights-licence "MIT" --attest-licence-read
    python -m aro_cloud.admin enable-model --model triposg
    python -m aro_cloud.admin disable-model --model triposg
    python -m aro_cloud.admin list-jobs [--state failed]
    python -m aro_cloud.admin reconcile

``verify-model`` records that a PERSON has read the model's licence and decided it allows commercial use. The platform never sets this
itself, and a model that is not ``verified`` cannot be enabled (a CHECK constraint in the database enforces it).
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from typing import Any

from aro_cloud import accounts
from aro_cloud.db import Database, jdump
from aro_cloud.settings import load_settings
from aro_cloud.wiring import build_database, build_orchestrator

REFUSED_STATUSES = ("evaluation_only", "blocked")


def _audit(db: Database, action: str, target: str, detail: dict[str, Any]) -> None:
    with db.transaction() as tx:
        tx.execute(
            "insert into audit_log (actor_id, action, target, detail) values (NULL, :a, :t, CAST(:d AS jsonb))",
            a=action,
            t=target,
            d=jdump({**detail, "via": "cli"}),
        )


def grant_credits(db: Database, user: uuid.UUID, amount: int, note: str) -> int:
    with db.transaction() as tx:
        bal = tx.one("select grant_credits(CAST(:u AS uuid), :n, :note) as bal", u=str(user), n=amount, note=note)
    _audit(db, "grant_credits", str(user), {"amount": amount, "note": note})
    assert bal is not None
    return int(bal["bal"])


def verify_model(db: Database, model: str, verified_by: str, weights_licence: str | None, attested: bool) -> None:
    if not attested:
        raise SystemExit(
            "Refusing: pass --attest-licence-read to record that you have personally read this model's licence."
        )
    if not verified_by.strip():
        raise SystemExit("Refusing: --verified-by must name the person who read the licence.")
    with db.transaction() as tx:
        row = tx.one("select licence_status::text as licence_status from model_registry where model_id = :m", m=model)
        if row is None:
            raise SystemExit(f"Unknown model '{model}'.")
        if row["licence_status"] in REFUSED_STATUSES:
            raise SystemExit(
                f"Refusing: '{model}' is marked {row['licence_status']} (it is not licensed for commercial serving as it stands)."
            )
        tx.execute(
            "update model_registry set licence_status = 'verified', verified_by = :b, verified_at = now(), weights_licence = coalesce(:w, weights_licence) where model_id = :m",
            b=verified_by.strip(),
            w=weights_licence,
            m=model,
        )
    _audit(db, "verify_model", model, {"verified_by": verified_by.strip(), "weights_licence": weights_licence})


def set_enabled(db: Database, model: str, enabled: bool) -> None:
    with db.transaction() as tx:
        row = tx.one("select licence_status::text as licence_status from model_registry where model_id = :m", m=model)
        if row is None:
            raise SystemExit(f"Unknown model '{model}'.")
        if enabled and row["licence_status"] != "verified":
            raise SystemExit(
                f"Refusing: '{model}' is {row['licence_status']}. Run verify-model first (after reading its licence)."
            )
        tx.execute("update model_registry set enabled = :e where model_id = :m", e=enabled, m=model)
    _audit(db, "enable_model" if enabled else "disable_model", model, {})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m aro_cloud.admin", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("grant-credits")
    g.add_argument("--user", type=uuid.UUID, required=True)
    g.add_argument("--amount", type=int, required=True)
    g.add_argument("--note", required=True)
    b = sub.add_parser("balance")
    b.add_argument("--user", type=uuid.UUID, required=True)
    v = sub.add_parser("verify-model")
    v.add_argument("--model", required=True)
    v.add_argument("--verified-by", required=True)
    v.add_argument("--weights-licence")
    v.add_argument("--attest-licence-read", action="store_true")
    for name in ("enable-model", "disable-model"):
        sub.add_parser(name).add_argument("--model", required=True)
    lj = sub.add_parser("list-jobs")
    lj.add_argument("--state")
    lj.add_argument("--limit", type=int, default=30)
    sub.add_parser("reconcile")
    a = ap.parse_args(argv)

    s = load_settings()
    if a.cmd == "reconcile":
        print(json.dumps(build_orchestrator(s).reconcile_active()))
        return 0
    db = build_database(s)
    if a.cmd == "grant-credits":
        print(f"balance is now {grant_credits(db, a.user, a.amount, a.note)}")
    elif a.cmd == "balance":
        with db.transaction() as tx:
            print(json.dumps(accounts.balance(tx, a.user)))
    elif a.cmd == "verify-model":
        verify_model(db, a.model, a.verified_by, a.weights_licence, a.attest_licence_read)
        print(f"{a.model}: licence recorded as verified by {a.verified_by}. It is NOT enabled yet: run enable-model.")
    elif a.cmd in ("enable-model", "disable-model"):
        set_enabled(db, a.model, a.cmd == "enable-model")
        print(f"{a.model}: {'enabled' if a.cmd == 'enable-model' else 'disabled'}")
    elif a.cmd == "list-jobs":
        with db.transaction() as tx:
            rows = tx.all(
                "select job_id, state::text as state, name, model_id, attempt, error_code, created_at from generation_jobs "
                "where (CAST(:s AS text) is null or state::text = CAST(:s AS text)) order by created_at desc limit :n",
                s=a.state,
                n=a.limit,
            )
        for r in rows:
            print(
                f"{r['job_id']}  {r['state']:<18} {r['model_id']:<10} try {r['attempt']}  {r['error_code'] or '-':<20} {r['created_at']:%Y-%m-%d %H:%M}  {r['name']}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
