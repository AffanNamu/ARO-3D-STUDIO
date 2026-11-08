"""Apply the SQL migrations in ``aro_cloud/migrations`` in order, once each.

    ARO_DATABASE_URL=postgresql://... python -m aro_cloud.migrate            # against Supabase
    python -m aro_cloud.migrate --database-url postgresql://postgres@127.0.0.1:5432/postgres --stub-auth   # plain PostgreSQL for dev/CI

``--stub-auth`` installs the minimum of Supabase's ``auth`` schema (aro_cloud/dev/supabase_stub.sql) and is REFUSED when ``auth.users``
already exists, so it can never touch a real Supabase project.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

from aro_cloud.db import Database, DatabaseError, Tx

HERE = Path(__file__).resolve().parent
MIGRATIONS = HERE / "migrations"
STUB = HERE / "dev" / "supabase_stub.sql"


def split_sql(sql: str) -> list[str]:
    """Split a script into statements, respecting '...' strings, -- and /* */ comments and $tag$ ... $tag$ bodies (PL/pgSQL functions)."""
    out: list[str] = []
    buf: list[str] = []
    i, n = 0, len(sql)
    in_quote, dollar = False, None
    while i < n:
        c = sql[i]
        if dollar:
            if sql.startswith(dollar, i):
                buf.append(dollar)
                i += len(dollar)
                dollar = None
            else:
                buf.append(c)
                i += 1
            continue
        if in_quote:
            buf.append(c)
            if c == "'":
                if i + 1 < n and sql[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                in_quote = False
            i += 1
            continue
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j < 0 else j
            buf.append(sql[i:j])
            i = j
            continue
        if sql.startswith("/*", i):  # block comments nest in PostgreSQL
            depth, j = 1, i + 2
            while j < n and depth:
                if sql.startswith("/*", j):
                    depth, j = depth + 1, j + 2
                elif sql.startswith("*/", j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            buf.append(sql[i:j])
            i = j
            continue
        if c == "'":
            in_quote = True
            buf.append(c)
            i += 1
            continue
        if c == "$":
            m = re.match(r"\$[A-Za-z_]*\$", sql[i:])
            if m:
                dollar = m.group(0)
                buf.append(dollar)
                i += len(dollar)
                continue
        if c == ";":
            stmt = "".join(buf).strip()
            if _has_code(stmt):
                out.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    tail = "".join(buf).strip()
    if _has_code(tail):
        out.append(tail)
    return out


def _has_code(stmt: str) -> bool:
    return any(line.strip() and not line.strip().startswith("--") for line in stmt.splitlines())


def _files() -> list[Path]:
    return sorted(p for p in MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def _run_script(tx: Tx, path: Path) -> None:
    for stmt in split_sql(path.read_text(encoding="utf-8")):
        tx.execute(stmt)


def migrate(db: Database, *, stub_auth: bool = False) -> list[str]:
    """Apply pending migrations; returns the names applied. Each file runs in its own transaction."""
    with db.transaction() as tx:
        has_auth = bool(tx.one("select to_regclass('auth.users') as t")["t"])  # type: ignore[index]
        if stub_auth:
            if has_auth:
                raise DatabaseError(
                    "auth.users already exists: this looks like Supabase. --stub-auth is for plain PostgreSQL only."
                )
            _run_script(tx, STUB)
        elif not has_auth:
            raise DatabaseError(
                "auth.users does not exist, so this is not a Supabase database. Use the project's connection string, "
                "or --stub-auth for a throwaway local PostgreSQL."
            )
        tx.execute(
            "create table if not exists public.aro_migrations (name text primary key, sha256 text not null, applied_at timestamptz not null default now())"
        )
    applied: list[str] = []
    for path in _files():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with db.transaction() as tx:
            row = tx.one("select sha256 from public.aro_migrations where name = :n", n=path.name)
            if row:
                if row["sha256"] != digest:
                    raise DatabaseError(
                        f"migration {path.name} was changed after it was applied: add a new migration instead."
                    )
                continue
            _run_script(tx, path)
            tx.execute("insert into public.aro_migrations (name, sha256) values (:n, :h)", n=path.name, h=digest)
            applied.append(path.name)
    return applied


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--database-url", default=os.environ.get("ARO_DATABASE_URL"))
    ap.add_argument("--ssl", default=os.environ.get("ARO_DATABASE_SSL", "auto"))
    ap.add_argument(
        "--stub-auth", action="store_true", help="dev/CI only: create a minimal auth schema on plain PostgreSQL"
    )
    a = ap.parse_args(argv)
    if not a.database_url:
        print("set ARO_DATABASE_URL (or --database-url)", file=sys.stderr)
        return 2
    db = Database(a.database_url, ssl_mode=a.ssl, ca_file=os.environ.get("ARO_DATABASE_CA_FILE"))
    try:
        done = migrate(db, stub_auth=a.stub_auth)
    except DatabaseError as e:
        print(f"migration failed: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()
    print("applied: " + (", ".join(done) if done else "nothing (already up to date)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
