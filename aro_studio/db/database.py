"""SQLite persistence.

Chosen deliberately (spec §28): zero infrastructure, single file, transactional, ships with
Python, and works on Hugging Face Spaces. A thread lock serialises writes; WAL keeps readers fast.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from aro_studio.db.schema import MIGRATIONS


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys=ON")
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
        self.migrate()

    # -- migrations ---------------------------------------------------------------------------
    def migrate(self) -> None:
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
            )
            current = self._conn.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations").fetchone()[0]
            for version, statements in MIGRATIONS:
                if version <= current:
                    continue
                self._conn.execute("BEGIN")
                try:
                    for stmt in statements:
                        self._conn.execute(stmt)
                    self._conn.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, strftime('%s','now'))",
                        (version,),
                    )
                    self._conn.execute("COMMIT")
                except Exception:
                    self._conn.execute("ROLLBACK")
                    raise

    @property
    def schema_version(self) -> int:
        row = self.query_one("SELECT COALESCE(MAX(version),0) AS v FROM schema_migrations")
        return int(row["v"]) if row else 0

    # -- helpers ------------------------------------------------------------------------------
    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            return cur.rowcount

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, tuple(params)).fetchall()]

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> dict | None:
        with self._lock:
            row = self._conn.execute(sql, tuple(params)).fetchone()
            return dict(row) if row else None

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def dumps(obj: Any) -> str:
    return json.dumps(obj, default=str, separators=(",", ":"))


def loads(s: str | None, default: Any = None) -> Any:
    if not s:
        return default
    return json.loads(s)
