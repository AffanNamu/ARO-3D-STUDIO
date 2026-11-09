"""The owner's verification commands: they must tell the truth, and never print a secret."""

from __future__ import annotations

import socket
import ssl

import httpx
import pg8000.exceptions
import pytest

from aro_cloud.db import Database, DatabaseError, explain_connect_error
from aro_cloud.doctor import check_r2, check_runpod, check_supabase, render
from aro_cloud.envfile import load_env_file, parse_env_text
from aro_cloud.settings import CloudSettings

PW = "S3cretPw-ZZ9"


def supa_settings(**over) -> CloudSettings:
    base = dict(
        env="test",
        database_url=f"postgresql://postgres.abcdefgh:{PW}@aws-0-eu.pooler.supabase.com:5432/postgres",
        supabase_url="https://abcdefgh.supabase.co",
    )
    base.update(over)
    return CloudSettings(**base)  # type: ignore[arg-type]


def jwks(status=200, keys=None):
    body = {"keys": keys if keys is not None else [{"kid": "k1", "alg": "ES256", "kty": "EC"}]}
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, json=body)))


def by_name(checks):
    return {c.name: c for c in checks}


# ------------------------------------------------------------------------------------------------------------ env file
def test_env_file_parsing_rules():
    text = "# comment\nARO_A=1\nexport ARO_B=\"two words\"\nARO_C='x'\nARO_URL=postgresql://u:p#ss@h/db\nPATH=/evil\nARO_EMPTY=\n  \nnot a line"
    values, ignored = parse_env_text(text)
    assert values["ARO_A"] == "1" and values["ARO_B"] == "two words" and values["ARO_C"] == "x"
    assert values["ARO_URL"] == "postgresql://u:p#ss@h/db"  # '#' inside a value is part of the value
    assert "PATH" not in values and ignored == ["PATH"]


def test_env_file_loading_never_overrides_or_prints_values(tmp_path, capsys):
    f = tmp_path / "aro.env"
    f.write_text("ARO_ENV=production\nARO_RUNPOD_API_KEY=rpa_TOPSECRET\nARO_R2_BUCKET=\n")
    f.chmod(0o600)
    env = {"ARO_ENV": "development"}
    names = load_env_file(f, environ=env)
    assert env["ARO_ENV"] == "development"  # the real environment wins
    assert (
        env["ARO_RUNPOD_API_KEY"] == "rpa_TOPSECRET" and "ARO_R2_BUCKET" not in env and names == ["ARO_RUNPOD_API_KEY"]
    )
    out = capsys.readouterr()
    assert "TOPSECRET" not in out.out + out.err


def test_env_file_warns_when_other_users_can_read_it(tmp_path, capsys):
    f = tmp_path / "aro.env"
    f.write_text("ARO_ENV=test\n")
    f.chmod(0o644)
    load_env_file(f, environ={})
    assert "chmod 600" in capsys.readouterr().err


def test_a_missing_env_file_is_an_error(tmp_path):
    with pytest.raises(SystemExit):
        load_env_file(tmp_path / "nope.env", environ={})


# ----------------------------------------------------------------------------------------------------- connection errors
def test_connection_errors_are_explained_with_fixed_texts():
    assert "certificate" in explain_connect_error(
        ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED for host admin.example")
    )
    assert "resolved" in explain_connect_error(socket.gaierror("Name or service not known: db.secret-host.example"))
    assert "did not answer" in explain_connect_error(TimeoutError())
    bad = pg8000.exceptions.DatabaseError({"C": "28P01", "M": 'password authentication failed for user "adminuser"'})
    text = explain_connect_error(bad)
    assert "user name or password" in text and "adminuser" not in text
    assert "does not exist" in explain_connect_error(
        pg8000.exceptions.DatabaseError({"C": "3D000", "M": 'database "x" does not exist'})
    )


def test_a_closed_port_gives_an_actionable_message_without_the_url():
    db = Database("postgresql://user:hunter2@127.0.0.1:1/db", ssl_mode="disable")
    with pytest.raises(DatabaseError) as e, db.transaction():
        pass
    assert "hunter2" not in str(e.value) and "127.0.0.1" not in str(e.value)


# ----------------------------------------------------------------------------------------------------------- supabase
def test_a_correct_setup_passes_every_supabase_check(pg):
    checks = check_supabase(supa_settings(), db=pg, http=jwks())
    bad = [c for c in checks if c.status not in ("PASS",)]
    assert [c.name for c in bad] == [], render(checks)
    names = by_name(checks)
    assert (
        "ES256" in names["token signing keys"].detail and "triposg: claimed, disabled" in names["model registry"].detail
    )
    assert PW not in render(checks) and "postgres.abcdefgh" not in render(checks)  # no secret, not even the user name


def test_missing_configuration_names_the_variables_only():
    out = check_supabase(CloudSettings(env="test"))
    assert out[0].status == "FAIL" and "ARO_DATABASE_URL" in out[0].detail and "ARO_SUPABASE_URL" in out[0].detail


def test_database_and_url_from_different_projects_fail(pg):
    checks = check_supabase(supa_settings(supabase_url="https://zzzzzzzz.supabase.co"), db=pg, http=jwks())
    c = by_name(checks)["same project"]
    assert c.status == "FAIL" and "abcdefgh" in c.detail and "zzzzzzzz" in c.detail


def test_unapplied_or_edited_migrations_fail(pg):
    with pg.transaction() as tx:
        tx.execute("update public.aro_migrations set sha256 = 'edited'")
    assert by_name(check_supabase(supa_settings(), db=pg, http=jwks()))["migrations"].status == "FAIL"
    with pg.transaction() as tx:
        tx.execute("delete from public.aro_migrations")
    c = by_name(check_supabase(supa_settings(), db=pg, http=jwks()))["migrations"]
    assert c.status == "FAIL" and "0001_init.sql" in c.detail


def test_a_public_table_without_row_level_security_fails(pg):
    with pg.transaction() as tx:
        tx.execute("create table public.oops (id int)")
    c = by_name(check_supabase(supa_settings(), db=pg, http=jwks()))["row level security"]
    assert c.status == "FAIL" and "oops" in c.detail


def test_credit_functions_open_to_browsers_fail(pg):
    with pg.transaction() as tx:
        tx.execute("grant execute on function grant_credits(uuid, integer, text) to authenticated")
    c = by_name(check_supabase(supa_settings(), db=pg, http=jwks()))["credit functions closed to browsers"]
    assert c.status == "FAIL" and "grant_credits" in c.detail


def test_signing_keys_legacy_and_missing(pg):
    none = check_supabase(supa_settings(), db=pg, http=jwks(404, []))
    assert by_name(none)["token signing keys"].status == "FAIL"
    legacy = check_supabase(supa_settings(supabase_jwt_secret="x" * 40), db=pg, http=jwks(404, []))
    assert by_name(legacy)["token signing keys"].status == "PASS"


def test_a_non_supabase_database_is_recognised(template_db):
    import uuid

    from tests.cloud.conftest import _admin, _url_for

    name = "aro_plain_" + uuid.uuid4().hex[:8]
    admin = _admin()
    admin.run(f'create database "{name}"')
    try:
        plain = Database(_url_for(name), ssl_mode="disable")
        checks = check_supabase(supa_settings(), db=plain, http=jwks())
        plain.close()
    finally:
        admin.run(f'drop database if exists "{name}" with (force)')
        admin.close()
    assert by_name(checks)["Supabase auth schema"].status == "FAIL"


# --------------------------------------------------------------------------------------------------------------- r2
def r2_settings(store, **over) -> CloudSettings:
    base = dict(
        env="test", r2_endpoint_url="http://x", r2_bucket=store.bucket, r2_access_key_id="k", r2_secret_access_key="s"
    )
    base.update(over)
    return CloudSettings(**base)  # type: ignore[arg-type]


def rewriting_client(rewrite):
    """An httpx client that performs the real request (against moto) and lets a test rewrite the response, to simulate what R2 enforces and moto does not."""
    real = httpx.Client(timeout=30)

    def handler(request: httpx.Request) -> httpx.Response:
        resp = real.send(httpx.Request(request.method, request.url, headers=request.headers, content=request.content))
        return rewrite(request, resp)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_r2_checks_report_round_trip_signed_links_and_cleanup(store):
    def r2_like(request, resp):
        headers = dict(resp.headers)
        if "X-Amz-Signature" not in str(request.url):
            return httpx.Response(403, content=b"AccessDenied")  # R2 refuses an unsigned request
        if request.headers.get("origin") == "http://localhost:3000":
            headers["access-control-allow-origin"] = "http://localhost:3000"
        else:
            headers.pop("access-control-allow-origin", None)
        return httpx.Response(resp.status_code, headers=headers, content=resp.content)

    checks = by_name(
        check_r2(r2_settings(store), store=store, http=rewriting_client(r2_like), origin="http://localhost:3000")
    )
    assert [c.status for c in checks.values()] == ["PASS"] * len(checks), render(list(checks.values()))
    assert store._c.list_objects_v2(Bucket=store.bucket).get("KeyCount", 0) == 0  # every test object was deleted


def test_a_readable_bucket_is_a_failure(store):
    def public(request, resp):  # what a bucket with public access turned on would answer to an unsigned GET
        return httpx.Response(200, content=b"public")

    c = by_name(check_r2(r2_settings(store), store=store, http=rewriting_client(public), origin=None))[
        "bucket is private"
    ]
    assert c.status == "FAIL" and "public access" in (c.hint or "")


def test_r2_cors_failure_is_reported_with_the_fix(store):
    def no_cors(request, resp):
        headers = {k: v for k, v in resp.headers.items() if not k.lower().startswith("access-control")}
        return httpx.Response(resp.status_code, headers=headers, content=resp.content)

    c = by_name(
        check_r2(r2_settings(store), store=store, http=rewriting_client(no_cors), origin="https://app.example")
    )["CORS for the web app"]
    assert c.status == "FAIL" and "CORS" in (c.hint or "")


def test_r2_storage_errors_are_actionable_and_block_the_rest(store):
    from aro_cloud.storage import R2Store

    broken = R2Store(
        bucket="does-not-exist-bucket",
        endpoint_url=store._c.meta.endpoint_url,
        access_key_id="test-key",
        secret_access_key="test-secret",
        region="auto",
    )
    out = check_r2(r2_settings(store, r2_bucket="does-not-exist-bucket"), store=broken)
    assert out[1].status == "FAIL" and out[2].status == "BLOCKED"


def test_r2_without_an_origin_is_partial_not_pass(store):
    assert by_name(check_r2(r2_settings(store), store=store))["CORS for the web app"].status == "PARTIAL"


def test_r2_missing_configuration_names_variables_only():
    out = check_r2(CloudSettings(env="test"))
    assert out[0].status == "FAIL" and "ARO_R2_BUCKET" in out[0].detail


# ----------------------------------------------------------------------------------------------------------- runpod
def rp(status, body=None):
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, json=body or {})))


def rp_settings():
    return CloudSettings(env="test", runpod_api_key="rpa_TOPSECRET", runpod_endpoint_id="ep123")


def test_runpod_health_is_read_only_and_reports_workers():
    out = check_runpod(
        rp_settings(), http=rp(200, {"jobs": {"inQueue": 0, "completed": 3}, "workers": {"idle": 0, "running": 0}})
    )
    assert out[-1].status == "PASS" and "idle 0" in out[-1].detail and "No job was submitted" in out[-1].detail
    assert "TOPSECRET" not in render(out)


@pytest.mark.parametrize(
    ("status", "needle"),
    [(401, "rejected the API key"), (403, "rejected the API key"), (404, "endpoint id"), (500, "HTTP 500")],
)
def test_runpod_failures_are_specific(status, needle):
    c = check_runpod(rp_settings(), http=rp(status))[-1]
    assert c.status == "FAIL" and needle in c.detail
