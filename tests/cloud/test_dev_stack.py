"""The local development stack: its doubles must be honest (labelled, never AI) and it must refuse to run anywhere that matters."""

from __future__ import annotations

import time
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient

from aro_cloud.auth import JwtVerifier
from aro_cloud.dev.stack import (
    DevStackRefused,
    LocalWorkerProvider,
    build_stack,
    check_database_is_disposable,
    create_auth_app,
    user_id_for,
)
from tests.cloud.conftest import _admin, _url_for
from tests.cloud.support import png_bytes

pytestmark = pytest.mark.slow
ORIGIN = "http://localhost:3000"


@pytest.fixture
def plain_db(template_db):
    """An empty local database (no schema at all), as a developer would create one."""
    name = "aro_dev_" + uuid.uuid4().hex[:8]
    admin = _admin()
    admin.run(f'create database "{name}"')
    yield _url_for(name)
    admin.run(f'drop database if exists "{name}" with (force)')
    admin.close()


def free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


# ------------------------------------------------------------------------------------------------------------ guards
def test_refuses_production_remote_databases_and_real_supabase(monkeypatch, plain_db, pg):
    with pytest.raises(DevStackRefused, match="localhost"):
        check_database_is_disposable("postgresql://u:p@db.abcdefgh.supabase.co:5432/postgres")
    monkeypatch.setenv("ARO_ENV", "production")
    with pytest.raises(DevStackRefused, match="production"):
        build_stack(plain_db, auth_url="http://127.0.0.1:1", web_origins=[ORIGIN])
    monkeypatch.delenv("ARO_ENV")
    with pg.transaction() as tx:  # what a real Supabase project's auth.users has and the stub does not
        tx.execute("alter table auth.users add column encrypted_password text")
    with pytest.raises(DevStackRefused, match="real Supabase"):
        check_database_is_disposable(_url_for(pg._kw["database"]))


# ------------------------------------------------------------------------------------------------------ sign-in double
def test_the_sign_in_double_issues_tokens_the_api_accepts_and_is_stable_per_email(pg):
    secret, issuer = "s" * 48, "http://127.0.0.1:8081/auth/v1"
    auth = TestClient(create_auth_app(pg, secret, issuer, [ORIGIN]))
    r = auth.post("/auth/v1/token?grant_type=password", json={"email": "Owner@Example.test", "password": "anything"})
    s = r.json()
    assert (
        r.status_code == 200
        and s["token_type"] == "bearer"
        and s["user"]["id"] == str(user_id_for("owner@example.test"))
    )
    who = JwtVerifier(secret=secret, issuer=issuer).verify(s["access_token"])
    assert str(who.user_id) == s["user"]["id"] and who.email == "owner@example.test"
    with pg.transaction() as tx:
        assert tx.one("select count(*) as n from auth.users where id = CAST(:u AS uuid)", u=s["user"]["id"])["n"] == 1
    again = auth.post("/auth/v1/signup", json={"email": "owner@example.test", "password": "x"}).json()
    assert again["user"]["id"] == s["user"]["id"]
    refreshed = auth.post("/auth/v1/token?grant_type=refresh_token", json={"refresh_token": s["refresh_token"]})
    assert refreshed.status_code == 200 and refreshed.json()["user"]["id"] == s["user"]["id"]
    assert (
        auth.post("/auth/v1/token?grant_type=refresh_token", json={"refresh_token": s["refresh_token"]}).status_code
        == 400
    )  # single use
    assert (
        auth.get("/auth/v1/user", headers={"Authorization": f"Bearer {s['access_token']}"}).json()["email"]
        == "owner@example.test"
    )
    assert auth.get("/auth/v1/user", headers={"Authorization": "Bearer junk"}).status_code == 401
    assert auth.post("/auth/v1/token?grant_type=password", json={"email": "not-an-email"}).status_code == 400
    assert auth.post("/auth/v1/otp", json={"email": "a@b.c"}).status_code == 400
    assert auth.post("/auth/v1/logout").status_code == 204


def test_tokens_from_one_stack_do_not_work_on_another(pg):
    a = TestClient(create_auth_app(pg, "a" * 48, "http://x/auth/v1", [ORIGIN]))
    token = a.post("/auth/v1/token?grant_type=password", json={"email": "u@example.test", "password": "x"}).json()[
        "access_token"
    ]
    from aro_cloud.errors import Unauthorized

    with pytest.raises(Unauthorized):
        JwtVerifier(secret="b" * 48, issuer="http://x/auth/v1").verify(token)
    assert jwt.get_unverified_header(token)["alg"] == "HS256"


# -------------------------------------------------------------------------------------------- the whole stack, one process
def test_sign_in_upload_generate_and_download_through_the_local_stack(plain_db):
    stack = build_stack(
        plain_db, auth_url="http://127.0.0.1:8081", web_origins=[ORIGIN], s3_port=free_port(), engine_delay_s=0.0
    )
    try:
        assert isinstance(stack.orchestrator.provider, LocalWorkerProvider)
        stack.orchestrator.provider.queue_delay_s = 0.0
        auth, api = TestClient(stack.auth), TestClient(stack.api)
        token = auth.post(
            "/auth/v1/token?grant_type=password", json={"email": "dev@example.test", "password": "x"}
        ).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        me = api.get("/v1/me", headers=h).json()
        assert (
            me["engines"] == ["fake"] and me["credits"]["balance"] == 100
        )  # dev sign-up credits; the only engine is the labelled double
        up = api.post("/v1/uploads", content=png_bytes(), headers={**h, "Content-Type": "image/png"}).json()[
            "upload_id"
        ]
        body = {
            "kind": "image_to_3d",
            "upload_id": up,
            "name": "Dev car",
            "engine": "fake",
            "settings": {"preset": "STANDARD", "category": "car", "target_faces": 4000},
        }
        job = api.post("/v1/generations", json=body, headers={**h, "Idempotency-Key": "dev-stack-key-1"}).json()
        deadline = time.time() + 90
        state = job["state"]
        while time.time() < deadline and state not in ("completed", "failed", "cancelled"):
            time.sleep(1.0)
            stack.orchestrator.reconcile_active()
            j = api.get(f"/v1/generations/{job['job_id']}", headers=h).json()
            state = j["state"]
        assert state == "completed", j.get("error")
        detail = api.get(f"/v1/assets/{j['result']['asset_id']}", headers=h).json()
        m = detail["model"]
        assert (
            m["test_double"] is True and m["ai_inference"] is False and m["engine"] == "fake"
        )  # labelled, never passed off as AI
        assert (
            [x["level"] for x in m["lods"]] == [0, 1, 2, 3] and m["collision_triangles"] and m["checks"]["categories"]
        )
        import httpx

        glb = httpx.get(api.get(f"/v1/assets/{detail['asset_id']}/versions/1/files/glb", headers=h).json()["url"])
        assert glb.status_code == 200 and glb.content[:4] == b"glTF"
        assert stack.web_env("http://a", "http://b")["NEXT_PUBLIC_STORAGE_ORIGIN"] == stack.s3_url
    finally:
        stack.close()
