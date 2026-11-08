"""PostgreSQL access (Supabase) with a small thread-safe pool.

Driver: pg8000 (BSD-3-Clause, pure Python). Chosen over psycopg (LGPL-3.0) so the dependency chain stays permissive, and because it works
with Supabase's transaction-mode pooler (no server-side prepared statements are kept between transactions).

Every unit of work runs in ``with db.transaction() as tx:``; SQL uses named parameters (``:name``) and ``CAST(:x AS type)`` for typed
values. The connection here is the SERVER's (service role / owner): it bypasses Row Level Security, so every query in this package
filters by ``owner_id`` explicitly. RLS protects direct client access and is the second line of defence, not the first.
"""

from __future__ import annotations

import contextlib
import json
import queue
import ssl
import threading
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import unquote, urlparse

import pg8000.exceptions
import pg8000.native

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class DatabaseError(RuntimeError):
    pass


def jdump(value: Any) -> str:
    """JSON text for a ``CAST(:x AS jsonb)`` parameter."""
    return json.dumps(value, separators=(",", ":"), default=str)


class Tx:
    """One open transaction. Rows are plain dicts."""

    def __init__(self, conn: pg8000.native.Connection) -> None:
        self._c = conn

    def all(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        rows = self._c.run(sql, **params)
        if not rows:
            return []
        names = [c["name"] for c in self._c.columns]
        return [dict(zip(names, r, strict=True)) for r in rows]

    def one(self, sql: str, **params: Any) -> dict[str, Any] | None:
        rows = self.all(sql, **params)
        return rows[0] if rows else None

    def execute(self, sql: str, **params: Any) -> int:
        self._c.run(sql, **params)
        return int(self._c.row_count or 0)


def _ssl_context(mode: str, host: str, ca_file: str | None) -> ssl.SSLContext | None:
    if mode == "auto":
        mode = "disable" if host in LOCAL_HOSTS else "verify"
    if mode == "disable":
        return None
    ctx = ssl.create_default_context(cafile=ca_file)
    if (
        mode == "require"
    ):  # encrypted but unauthenticated, like libpq's sslmode=require; prefer `verify` with the provider's CA file
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    elif mode != "verify":
        raise DatabaseError(f"ARO_DATABASE_SSL must be auto, verify, require or disable, not '{mode}'.")
    return ctx


class Database:
    def __init__(
        self,
        url: str,
        *,
        ssl_mode: str = "auto",
        ca_file: str | None = None,
        pool_size: int = 8,
        max_idle_s: float = 30.0,
    ):
        u = urlparse(url)
        if u.scheme not in ("postgresql", "postgres") or not u.hostname:
            raise DatabaseError("ARO_DATABASE_URL must look like postgresql://user:password@host:5432/database")
        self._kw: dict[str, Any] = {
            "user": unquote(u.username or "postgres"),
            "password": unquote(u.password) if u.password else None,
            "host": u.hostname,
            "port": u.port or 5432,
            "database": (u.path or "/postgres").lstrip("/") or "postgres",
            "ssl_context": _ssl_context(ssl_mode, u.hostname, ca_file),
            "timeout": 30,
            "application_name": "aro-cloud",
        }
        self._idle: queue.LifoQueue[tuple[pg8000.native.Connection, float]] = queue.LifoQueue()
        self._size = pool_size
        self._open = 0
        self._lock = threading.Lock()
        self._max_idle = max_idle_s

    # -- pool ----------------------------------------------------------------------------------------------------------------
    def _connect(self) -> pg8000.native.Connection:
        try:
            return pg8000.native.Connection(**self._kw)
        except (pg8000.exceptions.InterfaceError, pg8000.exceptions.DatabaseError, OSError) as e:
            raise DatabaseError(
                f"cannot connect to the database ({type(e).__name__})"
            ) from None  # never echo the driver's message

    def _acquire(self) -> pg8000.native.Connection:
        while True:
            try:
                conn, last = self._idle.get_nowait()
            except queue.Empty:
                break
            if time.monotonic() - last > self._max_idle:
                try:
                    conn.run(
                        "select 1"
                    )  # a stale socket (pooler timeout) is discovered here, not in the caller's transaction
                except Exception:  # noqa: BLE001
                    self._discard(conn)
                    continue
            return conn
        with self._lock:
            if self._open < self._size:
                self._open += 1
                try:
                    return self._connect()
                except Exception:
                    self._open -= 1
                    raise
        conn, _ = self._idle.get(timeout=30)  # pool exhausted: wait for a release
        return conn

    def _discard(self, conn: pg8000.native.Connection) -> None:
        with contextlib.suppress(Exception):
            conn.close()
        with self._lock:
            self._open = max(0, self._open - 1)

    @contextlib.contextmanager
    def transaction(self) -> Iterator[Tx]:
        conn = self._acquire()
        broken = False
        try:
            conn.run("BEGIN")
            tx = Tx(conn)
            yield tx
            conn.run("COMMIT")
        except pg8000.exceptions.InterfaceError:
            broken = True
            raise
        except BaseException:
            try:
                conn.run("ROLLBACK")
            except Exception:  # noqa: BLE001
                broken = True
            raise
        finally:
            if broken:
                self._discard(conn)
            else:
                self._idle.put((conn, time.monotonic()))

    def close(self) -> None:
        while True:
            try:
                conn, _ = self._idle.get_nowait()
            except queue.Empty:
                break
            self._discard(conn)

    def healthy(self) -> bool:
        try:
            with self.transaction() as tx:
                return tx.one("select 1 as ok") == {"ok": 1}
        except Exception:  # noqa: BLE001
            return False
