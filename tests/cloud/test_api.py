"""The HTTP API, driven like the web app drives it: bearer tokens in, JSON out, against a real PostgreSQL and S3 API."""

from __future__ import annotations

import time
import uuid

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from aro_cloud.api import create_app
from aro_cloud.auth import JwtVerifier
from aro_cloud.orchestrator import Orchestrator
from tests.cloud.support import ScriptedProvider, enable_model, finish_run, make_user, png_bytes

SECRET = "api-test-secret-" + "x" * 32


def token(user: uuid.UUID, **over) -> str:
    c = {
        "sub": str(user),
        "aud": "authenticated",
        "role": "authenticated",
        "exp": int(time.time()) + 600,
        "email": "u@example.test",
    }
    c.update(over)
    return jwt.encode(c, SECRET, algorithm="HS256")


def bearer(user: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {token(user)}"}


@pytest.fixture
def env(pg, store, settings):
    enable_model(pg)
    provider = ScriptedProvider()
    verifier = JwtVerifier(secret=SECRET)
    app = create_app(settings, db=pg, store=store, provider=provider, verifier=verifier)
    client = TestClient(app, raise_server_exceptions=False)
    user = make_user(pg, credits=100)
    return client, provider, user, pg, store


def upload(client, user, data=None, ctype="image/png"):
    return client.post(
        "/v1/uploads",
        content=data if data is not None else png_bytes(),
        headers={**bearer(user), "Content-Type": ctype},
    )


def generate(client, user, upload_id, key="api-key-0001", **over):
    body = {"kind": "image_to_3d", "upload_id": upload_id, "name": "Test car", "engine": "triposg", **over}
    return client.post("/v1/generations", json=body, headers={**bearer(user), "Idempotency-Key": key})


# --------------------------------------------------------------------------------------------------------------- auth
def test_every_v1_route_needs_a_valid_token(env):
    client, _, user, *_ = env
    for method, path in [
        ("get", "/v1/me"),
        ("get", "/v1/generations"),
        ("get", "/v1/assets"),
        ("get", "/v1/credits"),
        ("post", "/v1/uploads"),
    ]:
        r = getattr(client, method)(path)
        assert (
            r.status_code == 401
            and r.json()["error"]["code"] == "unauthorized"
            and r.headers["www-authenticate"] == "Bearer"
        )
    for bad in [token(user, exp=int(time.time()) - 3600), token(user, aud="x"), token(user, role="anon"), "garbage"]:
        assert client.get("/v1/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401


def test_health_is_public_and_headers_are_hardened(env):
    client, *_ = env
    r = client.get("/healthz")
    assert (
        r.status_code == 200
        and r.headers["x-content-type-options"] == "nosniff"
        and r.headers["cache-control"] == "no-store"
    )
    assert client.get("/readyz").status_code == 200


def test_cors_allows_only_configured_origins(env):
    client, *_ = env
    ok = client.options(
        "/v1/me",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,idempotency-key",
        },
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    bad = client.options("/v1/me", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers


# ----------------------------------------------------------------------------------------------------------------- me
def test_me_creates_the_account_and_reports_the_price(pg, store, settings):
    enable_model(pg)
    client = TestClient(
        create_app(settings, db=pg, store=store, provider=ScriptedProvider(), verifier=JwtVerifier(secret=SECRET))
    )
    stranger = uuid.uuid4()
    with pg.transaction() as tx:
        tx.execute("insert into auth.users (id, email) values (CAST(:u AS uuid), 'new@example.test')", u=str(stranger))
    me = client.get("/v1/me", headers=bearer(stranger)).json()
    assert (
        me["new_user"] is True
        and me["credits"] == {"balance": 0, "reserved": 0}
        and me["price"]["image_to_3d"] == 10
        and me["engines"] == ["triposg"]
    )
    assert client.get("/v1/me", headers=bearer(stranger)).json()["new_user"] is False


# ------------------------------------------------------------------------------------------------------------- uploads
def test_upload_validates_by_content(env):
    client, _, user, *_ = env
    ok = upload(client, user)
    assert ok.status_code == 201 and ok.json()["width"] == 512 and ok.json()["content_type"] == "image/png"
    again = upload(client, user)
    assert again.json()["upload_id"] == ok.json()["upload_id"]  # identical bytes: one upload
    assert upload(client, user, b"GIF89a-not-an-image", "image/png").status_code == 422
    assert upload(client, user, b"", "image/png").status_code in (422, 400)
    tiny = upload(client, user, png_bytes(64, 64))
    assert tiny.status_code == 422 and tiny.json()["error"]["code"] == "invalid_image"
    assert upload(client, user, png_bytes(), "text/plain").status_code == 422


def test_upload_size_is_capped_while_streaming(env):
    client, _, user, *_ = env
    r = client.post(
        "/v1/uploads",
        content=b"\x89PNG\r\n\x1a\n" + b"0" * (11 * 1_000_000),
        headers={**bearer(user), "Content-Type": "image/png"},
    )
    assert r.status_code in (413, 422)


def test_json_bodies_are_capped(env):
    client, _, user, *_ = env
    r = client.post(
        "/v1/generations",
        content=b"{" + b" " * 70_000 + b"}",
        headers={**bearer(user), "Content-Type": "application/json", "Idempotency-Key": "api-key-big1"},
    )
    assert r.status_code == 413


# ------------------------------------------------------------------------------------------------------- generate + poll
def test_generate_poll_and_load_the_result(env):
    client, provider, user, pg, store = env
    up = upload(client, user).json()["upload_id"]
    r = generate(client, user, up, settings={"preset": "DRAFT", "category": "car"})
    assert r.status_code == 201
    job = r.json()
    assert job["state"] == "initializing" and job["credits"]["reserved"] == 10 and "provider_run_id" not in job
    again = generate(client, user, up, settings={"preset": "DRAFT", "category": "car"})
    assert again.status_code == 200 and again.json()["job_id"] == job["job_id"]  # replay: same job, no second charge
    assert client.get("/v1/credits", headers=bearer(user)).json()["balance"] == 90

    provider.runs["run-1"].state = "running"
    time.sleep(2.6)  # status reads are throttled to protect the provider
    assert client.get(f"/v1/generations/{job['job_id']}", headers=bearer(user)).json()["state"] == "generating"
    finish_run(provider, "run-1")
    time.sleep(2.6)  # the poll is throttled to protect the provider; a later poll picks the result up
    done = client.get(f"/v1/generations/{job['job_id']}", headers=bearer(user)).json()
    assert done["state"] == "completed" and done["result"]["asset_id"] and done["credits"]["captured"] == 10

    assets = client.get("/v1/assets", headers=bearer(user)).json()["items"]
    assert (
        len(assets) == 1
        and assets[0]["name"] == "Test car"
        and assets[0]["triangles"] >= 200
        and assets[0]["ai_inference"] is True
    )
    detail = client.get(f"/v1/assets/{done['result']['asset_id']}", headers=bearer(user)).json()
    assert [f["role"] for f in detail["versions"][0]["files"]] == ["glb", "raw_mesh", "thumbnail"]
    f = client.get(f"/v1/assets/{done['result']['asset_id']}/versions/1/files/glb", headers=bearer(user)).json()
    got = httpx.get(f["url"])
    assert got.status_code == 200 and got.content[:4] == b"glTF" and f["filename"] == "Test_car.glb"

    ledger = client.get("/v1/credits/ledger", headers=bearer(user)).json()["items"]
    assert [e["kind"] for e in ledger][:2] == ["capture", "reserve"]
    events = client.get(f"/v1/generations/{job['job_id']}/events", headers=bearer(user)).json()["items"]
    assert events[0]["to"] == "created" and events[-1]["to"] == "completed"
    listing = client.get("/v1/generations", headers=bearer(user)).json()["items"]
    assert listing[0]["result"]["asset_id"] == done["result"]["asset_id"]


def test_generate_errors_have_one_envelope(env):
    client, _, user, pg, store = env
    up = upload(client, user).json()["upload_id"]
    r = client.post(
        "/v1/generations", json={"kind": "image_to_3d", "upload_id": up, "name": "x"}, headers=bearer(user)
    )  # no Idempotency-Key
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_idempotency_key"
    r = generate(client, user, up, key="api-key-0002", settings={"preset": "ULTRA"})
    assert r.status_code == 422 and r.json()["error"]["details"]["problems"]
    assert "ULTRA" not in r.text  # input values are not echoed
    r = generate(client, user, up, key="api-key-0003", settings={"category": "character"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_category"
    r = generate(client, user, str(uuid.uuid4()), key="api-key-0004")
    assert r.status_code == 404 and r.json()["error"]["code"] == "upload_not_found"
    broke = make_user(pg, credits=3)
    up2 = upload(client, broke).json()["upload_id"]
    r = generate(client, broke, up2, key="api-key-0005")
    assert r.status_code == 402 and r.json()["error"]["details"] == {"price": 10, "balance": 3}


def test_cancel_through_the_api_releases_the_credits(env):
    client, provider, user, *_ = env
    up = upload(client, user).json()["upload_id"]
    job = generate(client, user, up).json()
    r = client.post(f"/v1/generations/{job['job_id']}/cancel", headers=bearer(user))
    assert r.status_code == 200 and r.json()["state"] == "cancelled"
    assert client.get("/v1/credits", headers=bearer(user)).json()["balance"] == 100


# ------------------------------------------------------------------------------------------------------ tenant isolation
def test_users_cannot_see_or_touch_each_others_data(env):
    client, provider, alice, pg, store = env
    bob = make_user(pg, credits=100)
    up = upload(client, alice).json()["upload_id"]
    job = generate(client, alice, up).json()
    finish_run(provider, "run-1")
    time.sleep(2.6)
    done = client.get(f"/v1/generations/{job['job_id']}", headers=bearer(alice)).json()
    asset = done["result"]["asset_id"]
    for method, path in [
        ("get", f"/v1/generations/{job['job_id']}"),
        ("get", f"/v1/generations/{job['job_id']}/events"),
        ("post", f"/v1/generations/{job['job_id']}/cancel"),
        ("get", f"/v1/assets/{asset}"),
        ("get", f"/v1/assets/{asset}/versions/1/files/glb"),
    ]:
        r = getattr(client, method)(path, headers=bearer(bob))
        assert r.status_code == 404, (path, r.status_code)
    assert generate(client, bob, up, key="api-key-bob1").status_code == 404  # alice's upload id is not bob's
    assert client.get("/v1/assets", headers=bearer(bob)).json()["items"] == []
    assert client.get("/v1/generations", headers=bearer(bob)).json()["items"] == []
    assert client.get("/v1/credits/ledger", headers=bearer(bob)).json()["items"][0]["kind"] == "grant"


# ------------------------------------------------------------------------------------------------------------ internal
def test_internal_reconcile_needs_the_shared_token(env):
    client, provider, user, *_ = env
    assert client.post("/internal/reconcile").status_code == 401
    assert client.post("/internal/reconcile", headers={"X-Internal-Token": "wrong" * 8}).status_code == 401
    up = upload(client, user).json()["upload_id"]
    generate(client, user, up)
    finish_run(provider, "run-1")
    r = client.post("/internal/reconcile", headers={"X-Internal-Token": "t" * 32})
    assert r.status_code == 200 and r.json()["finished"] == 1


def test_unexpected_errors_answer_with_the_envelope_and_no_detail(pg, store, settings):
    class Boom(Orchestrator):
        def submit(self, *a, **k):
            raise RuntimeError("secret internal detail")

    enable_model(pg)
    client = TestClient(
        create_app(
            settings,
            db=pg,
            store=store,
            provider=ScriptedProvider(),
            verifier=JwtVerifier(secret=SECRET),
            orchestrator=Boom(pg, store, ScriptedProvider(), settings),
        ),
        raise_server_exceptions=False,
    )
    user = make_user(pg)
    up = upload(client, user).json()["upload_id"]
    r = generate(client, user, up)
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal_error" and "secret" not in r.text
