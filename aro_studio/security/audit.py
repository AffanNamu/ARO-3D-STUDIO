"""Append-only audit log of security-relevant and destructive actions (stored in SQLite)."""

from __future__ import annotations

import json
import time

from aro_studio.core.ids import new_id
from aro_studio.db.database import Database

_SENSITIVE = ("token", "secret", "password", "authorization", "api_key")


def _scrub(d: dict) -> dict:
    return {k: ("***" if any(s in k.lower() for s in _SENSITIVE) else v) for k, v in d.items()}


class AuditLog:
    def __init__(self, db: Database):
        self.db = db

    def record(self, action: str, *, actor: str = "system", target: str | None = None, **details) -> None:
        self.db.execute(
            "INSERT INTO audit_log(audit_id, ts, actor, action, target, details) VALUES (?,?,?,?,?,?)",
            (new_id("audit"), time.time(), actor, action, target, json.dumps(_scrub(details), default=str)),
        )

    def recent(self, limit: int = 100) -> list[dict]:
        rows = self.db.query("SELECT * FROM audit_log ORDER BY ts DESC LIMIT ?", (limit,))
        for r in rows:
            r["details"] = json.loads(r["details"] or "{}")
        return rows
