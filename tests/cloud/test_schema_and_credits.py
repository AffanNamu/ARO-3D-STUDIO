"""The database is the last line of defence: Row Level Security for clients, and credits that can only move through the ledger functions."""

from __future__ import annotations

import random
import uuid

import pg8000.exceptions
import pytest

from aro_cloud import accounts
from aro_cloud.db import Database, DatabaseError, jdump
from aro_cloud.migrate import migrate, split_sql
from tests.cloud.support import make_user


def new_job(pg: Database, owner: uuid.UUID) -> uuid.UUID:
    with pg.transaction() as tx:
        row = tx.one(
            "insert into generation_jobs (owner_id, kind, idempotency_key, request, request_sha256, deadline_at) "
            "values (CAST(:o AS uuid), 'image_to_3d', :k, CAST(:r AS jsonb), 'x', now() + interval '1 hour') returning job_id",
            o=str(owner),
            k=uuid.uuid4().hex,
            r=jdump({}),
        )
    return uuid.UUID(str(row["job_id"]))


def as_client(tx, user: uuid.UUID) -> None:
    """Behave like a browser holding that user's Supabase token: the `authenticated` role with auth.uid() = the user."""
    tx.execute("set local role authenticated")
    tx.one("select set_config('request.jwt.claim.sub', :u, true) as s", u=str(user))


# ------------------------------------------------------------------------------------------------------- migrations
def test_migrations_are_idempotent_and_tamper_evident(pg):
    assert migrate(pg) == []
    with pg.transaction() as tx:
        tx.execute("update public.aro_migrations set sha256 = 'tampered'")
    with pytest.raises(DatabaseError, match="changed after it was applied"):
        migrate(pg)


def test_the_auth_stub_is_refused_where_auth_users_exists(pg):
    with pytest.raises(DatabaseError, match="Supabase"):
        migrate(pg, stub_auth=True)


def test_split_sql_respects_quotes_comments_and_dollar_bodies():
    sql = """
    -- a; comment
    create table t (a text default 'x;y');  /* block; comment */
    create function f() returns int language plpgsql as $body$ begin return 1; end; $body$;
    select 1
    """
    parts = split_sql(sql)
    assert len(parts) == 3 and "x;y" in parts[0] and "return 1; end;" in parts[1]


# --------------------------------------------------------------------------------------------------------------- RLS
def test_a_client_sees_only_its_own_rows(pg):
    a, b = make_user(pg, 50), make_user(pg, 70)
    ja, jb = new_job(pg, a), new_job(pg, b)
    with pg.transaction() as tx:
        as_client(tx, a)
        assert [str(r["job_id"]) for r in tx.all("select job_id from generation_jobs")] == [str(ja)]
        assert [r["balance"] for r in tx.all("select balance from credit_accounts")] == [50]
        assert {r["user_id"] for r in tx.all("select user_id from credit_ledger")} == {a}
        assert tx.all("select * from profiles where user_id = CAST(:b AS uuid)", b=str(b)) == []
    with pg.transaction() as tx:
        as_client(tx, b)
        assert [str(r["job_id"]) for r in tx.all("select job_id from generation_jobs")] == [str(jb)]


def client_write_is_refused(pg: Database, user: uuid.UUID, sql: str, **params) -> None:
    with pytest.raises(pg8000.exceptions.DatabaseError), pg.transaction() as tx:
        as_client(tx, user)
        tx.execute(sql, **params)


def test_a_client_cannot_write_credits_jobs_or_the_ledger(pg):
    a = make_user(pg, 50)
    with pg.transaction() as tx:
        as_client(tx, a)
        assert (
            tx.execute("update credit_accounts set balance = 1000000 where user_id = CAST(:u AS uuid)", u=str(a)) == 0
        )  # no policy: no rows
    client_write_is_refused(
        pg,
        a,
        "insert into credit_ledger (user_id, kind, amount, balance_after) values (CAST(:u AS uuid), 'grant', 999, 999)",
        u=str(a),
    )
    client_write_is_refused(
        pg,
        a,
        "insert into generation_jobs (owner_id, kind, idempotency_key, request, request_sha256, deadline_at) "
        "values (CAST(:u AS uuid), 'image_to_3d', 'abcdefgh', '{}', 'x', now())",
        u=str(a),
    )
    with pg.transaction() as tx:
        assert accounts.balance(tx, a)["balance"] == 50


@pytest.mark.parametrize(
    "call",
    [
        "select grant_credits(CAST(:u AS uuid), 1000, 'free money')",
        "select reserve_credits(CAST(:u AS uuid), CAST(:j AS uuid), 1)",
        "select capture_credits(CAST(:u AS uuid), CAST(:j AS uuid))",
        "select release_credits(CAST(:u AS uuid), CAST(:j AS uuid))",
        "select ensure_user(CAST(:u AS uuid))",
    ],
)
def test_a_client_cannot_call_the_credit_functions(pg, call):
    a = make_user(pg, 50)
    j = new_job(pg, a)
    with pytest.raises(pg8000.exceptions.DatabaseError, match="permission denied"), pg.transaction() as tx:
        as_client(tx, a)
        tx.one(call, u=str(a), j=str(j))


def test_an_unverified_model_cannot_be_enabled_even_by_sql(pg):
    with pytest.raises(pg8000.exceptions.DatabaseError, match="check"), pg.transaction() as tx:
        tx.execute("update model_registry set enabled = true where model_id = 'triposg'")
    with pytest.raises(pg8000.exceptions.DatabaseError, match="check"), pg.transaction() as tx:
        tx.execute(
            "update model_registry set enabled = true, licence_status = 'evaluation_only' where model_id = 'trellis2'"
        )


def test_clients_only_see_enabled_models(pg):
    a = make_user(pg)
    with pg.transaction() as tx:
        as_client(tx, a)
        assert tx.all("select model_id from model_registry") == []


# ------------------------------------------------------------------------------------------------------- credit ledger
def test_settling_is_once_only(pg):
    a = make_user(pg, 100)
    j = new_job(pg, a)
    with pg.transaction() as tx:
        tx.one("select reserve_credits(CAST(:u AS uuid), CAST(:j AS uuid), 30) as r", u=str(a), j=str(j))
        tx.one(
            "select reserve_credits(CAST(:u AS uuid), CAST(:j AS uuid), 30) as r", u=str(a), j=str(j)
        )  # replay: no second hold
        tx.one("select capture_credits(CAST(:u AS uuid), CAST(:j AS uuid)) as r", u=str(a), j=str(j))
        tx.one("select capture_credits(CAST(:u AS uuid), CAST(:j AS uuid)) as r", u=str(a), j=str(j))
        tx.one(
            "select release_credits(CAST(:u AS uuid), CAST(:j AS uuid)) as r", u=str(a), j=str(j)
        )  # too late to refund a captured job
        kinds = [
            r["kind"]
            for r in tx.all(
                "select kind::text as kind from credit_ledger where job_id = CAST(:j AS uuid) order by entry_id",
                j=str(j),
            )
        ]
        assert kinds == ["reserve", "capture"]
        assert accounts.balance(tx, a) == {"balance": 70, "reserved": 0}


def test_reserve_refuses_more_than_the_balance(pg):
    a = make_user(pg, 10)
    j = new_job(pg, a)
    with pytest.raises(pg8000.exceptions.DatabaseError, match="insufficient credits"), pg.transaction() as tx:
        tx.one("select reserve_credits(CAST(:u AS uuid), CAST(:j AS uuid), 11) as r", u=str(a), j=str(j))
    with pg.transaction() as tx:
        assert accounts.balance(tx, a) == {"balance": 10, "reserved": 0}


def test_the_ledger_cannot_be_edited_by_the_api_role_but_stays_consistent(pg):
    a = make_user(pg, 40)
    with pg.transaction() as tx:
        led = tx.all(
            "select kind::text as kind, amount, balance_after from credit_ledger where user_id = CAST(:u AS uuid)",
            u=str(a),
        )
    assert led == [{"kind": "grant", "amount": 40, "balance_after": 40}]


@pytest.mark.parametrize("seed", range(8))
def test_random_operation_sequences_never_break_the_credit_invariants(pg, seed):
    """Whatever order grants, reservations, captures and releases arrive in: balance == sum of the ledger, never negative, and
    `reserved` == the credits held by jobs that are neither captured nor released."""
    rnd = random.Random(seed)
    users = [make_user(pg, rnd.randint(0, 60)) for _ in range(3)]
    jobs = [(u, new_job(pg, u)) for u in users for _ in range(4)]
    for _ in range(120):
        u, j = rnd.choice(jobs)
        op = rnd.choice(["grant", "reserve", "reserve", "capture", "release"])
        try:
            with pg.transaction() as tx:
                if op == "grant":
                    tx.one("select grant_credits(CAST(:u AS uuid), :n, 'g') as r", u=str(u), n=rnd.randint(1, 20))
                elif op == "reserve":
                    tx.one(
                        "select reserve_credits(CAST(:u AS uuid), CAST(:j AS uuid), :n) as r",
                        u=str(u),
                        j=str(j),
                        n=rnd.randint(0, 25),
                    )
                else:
                    tx.one(f"select {op}_credits(CAST(:u AS uuid), CAST(:j AS uuid)) as r", u=str(u), j=str(j))
        except pg8000.exceptions.DatabaseError:
            pass  # refused operations (insufficient credits, capture of an unreserved job) are fine; they must change nothing
        with pg.transaction() as tx:
            for user in users:
                bal = accounts.balance(tx, user)
                ledger_sum = tx.one(
                    "select coalesce(sum(amount), 0) as s from credit_ledger where user_id = CAST(:u AS uuid)",
                    u=str(user),
                )["s"]
                held = tx.one(
                    "select coalesce(sum(j.credits_reserved), 0) as s from generation_jobs j where j.owner_id = CAST(:u AS uuid) "
                    "and exists (select 1 from credit_ledger l where l.job_id = j.job_id and l.kind = 'reserve') "
                    "and not exists (select 1 from credit_ledger l where l.job_id = j.job_id and l.kind in ('capture', 'release'))",
                    u=str(user),
                )["s"]
                assert bal["balance"] >= 0 and bal["balance"] == ledger_sum and bal["reserved"] == held
