"""A complete LOCAL stack for development and browser tests. Every paid service is replaced by a labelled double; nothing here is AI.

    ARO_DEV_DATABASE_URL=postgresql://postgres@127.0.0.1:5432/aro_dev python -m aro_cloud.dev.stack

Real: the API, the PostgreSQL schema and credit ledger, the S3 protocol (an in-process S3 server), the worker handler and the whole Studio
preparation pipeline. Doubles:

* sign-in: a tiny stand-in for Supabase Auth that accepts ANY email and password (it only exists in this process);
* RunPod: the worker handler runs in a thread of this process;
* the MODEL: the procedural TEST DOUBLE engine ``fake``. It draws the same blocky car whatever image you upload. Its results are stamped
  ``test_double`` and the web app labels them "Test output, not AI".

Guards: refuses ``ARO_ENV=production``; refuses any database that is not on localhost; refuses a database that carries the real Supabase
``auth`` schema. Needs the dev requirements (``pip install -r requirements-dev.txt``).
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import jwt
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from aro_cloud.api import create_app
from aro_cloud.auth import JwtVerifier
from aro_cloud.db import LOCAL_HOSTS, Database
from aro_cloud.migrate import migrate
from aro_cloud.orchestrator import Orchestrator
from aro_cloud.providers.base import ProviderStatus
from aro_cloud.settings import CloudSettings
from aro_cloud.storage import R2Store

log = logging.getLogger("aro_cloud.dev")
ENGINE = "fake"
BUCKET = "aro-dev"
S3_DEV_KEY = "dev"  # the in-process S3 double accepts anything; not a credential
TOKEN_TTL_S = 3600


class DevStackRefused(RuntimeError):
    pass


# ============================================================================================== sign-in double (Supabase Auth API shape)
def user_id_for(email: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, "aro-dev-user:" + email.strip().lower())


def create_auth_app(db: Database, secret: str, issuer: str, web_origins: list[str]) -> FastAPI:
    """The four routes supabase-js uses for email + password sign-in. Any email and password are accepted: this is NOT authentication."""
    app = FastAPI(title="DEV sign-in double (not Supabase)", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=web_origins, allow_methods=["*"], allow_headers=["*"])
    refresh: dict[str, str] = {}  # refresh token -> email

    def session(email: str) -> dict[str, Any]:
        uid = user_id_for(email)
        with db.transaction() as tx:
            tx.execute(
                "insert into auth.users (id, email) values (CAST(:u AS uuid), :e) on conflict (id) do nothing",
                u=str(uid),
                e=email,
            )
        now = int(time.time())
        claims = {
            "sub": str(uid),
            "aud": "authenticated",
            "role": "authenticated",
            "email": email,
            "iss": issuer,
            "iat": now,
            "exp": now + TOKEN_TTL_S,
        }
        token = jwt.encode(claims, secret, algorithm="HS256")
        rt = secrets.token_urlsafe(24)
        refresh[rt] = email
        user = {
            "id": str(uid),
            "aud": "authenticated",
            "role": "authenticated",
            "email": email,
            "app_metadata": {},
            "user_metadata": {},
        }
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": TOKEN_TTL_S,
            "expires_at": now + TOKEN_TTL_S,
            "refresh_token": rt,
            "user": user,
        }

    def bad(message: str, status: int = 400) -> JSONResponse:
        return JSONResponse({"code": status, "error_code": "validation_failed", "msg": message}, status_code=status)

    async def email_of(request: Request) -> str | None:
        try:
            body = await request.json()
        except ValueError:
            return None
        email = str(body.get("email", "")).strip().lower() if isinstance(body, dict) else ""
        return email if "@" in email and len(email) <= 200 else None

    @app.post("/auth/v1/token")
    async def token(request: Request, grant_type: str = "password") -> Response:
        if grant_type == "refresh_token":
            try:
                rt = str((await request.json()).get("refresh_token", ""))
            except ValueError:
                rt = ""
            email = refresh.pop(rt, None)
            return JSONResponse(session(email)) if email else bad("Invalid Refresh Token")
        email = await email_of(request)
        return JSONResponse(session(email)) if email else bad("Enter an email address")

    @app.post("/auth/v1/signup")
    async def signup(request: Request) -> Response:
        email = await email_of(request)
        return JSONResponse(session(email)) if email else bad("Enter an email address")

    @app.post("/auth/v1/otp")
    async def otp() -> Response:
        return bad("The local sign-in double has no email: use a password (any password works).")

    @app.get("/auth/v1/user")
    async def user(request: Request) -> Response:
        try:
            claims = jwt.decode(
                request.headers.get("authorization", "").removeprefix("Bearer ").strip(),
                secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
        except jwt.PyJWTError:
            return bad("invalid token", 401)
        return JSONResponse(
            {"id": claims["sub"], "aud": "authenticated", "role": "authenticated", "email": claims.get("email")}
        )

    @app.post("/auth/v1/logout")
    async def logout() -> Response:
        return Response(status_code=204)

    return app


# ================================================================================================== RunPod double (handler in a thread)
@dataclass
class _Run:
    state: str = "queued"
    output: dict[str, Any] | None = None
    error: str | None = None
    started: float = 0.0
    finished: float = 0.0


@dataclass
class LocalWorkerProvider:
    """TEST DOUBLE for RunPod: runs the real worker handler (with the test-double engine) in a background thread."""

    deps: Any
    queue_delay_s: float = 1.5
    name: str = "local-test-double"
    runs: dict[str, _Run] = field(default_factory=dict)

    def submit(self, payload: dict[str, Any], *, execution_timeout_s: int, ttl_s: int) -> str:
        from aro_worker.runpod_handler import handle

        rid = "local-" + uuid.uuid4().hex[:12]
        run = self.runs[rid] = _Run()

        def work() -> None:
            time.sleep(self.queue_delay_s)
            if run.state == "cancelled":
                return
            run.state, run.started = "running", time.time()
            out = handle({"id": rid, "input": payload}, self.deps)
            run.finished = time.time()
            if run.state == "cancelled":
                return
            if "error" in out:
                run.state, run.error = "failed", str(out["error"])
            else:
                run.state, run.output = "succeeded", out

        threading.Thread(target=work, name=f"aro-dev-worker-{rid}", daemon=True).start()
        return rid

    def status(self, run_id: str) -> ProviderStatus:
        run = self.runs.get(run_id)
        if run is None:
            return ProviderStatus("unknown", raw_status="404")
        ms = int((run.finished - run.started) * 1000) if run.finished else None
        return ProviderStatus(run.state, output=run.output, error=run.error, execution_ms=ms)

    def cancel(self, run_id: str) -> None:
        run = self.runs.get(run_id)
        if run and run.state in ("queued", "running"):
            run.state = "cancelled"


# ============================================================================================================================ wiring
def check_database_is_disposable(url: str) -> None:
    host = urlparse(url).hostname or ""
    if host not in LOCAL_HOSTS:
        raise DevStackRefused(
            "The dev stack only runs against a PostgreSQL on localhost (it accepts any password as a sign-in)."
        )
    db = Database(url, ssl_mode="disable")
    try:
        with db.transaction() as tx:
            real = tx.one(
                "select 1 as x from information_schema.columns where table_schema = 'auth' and table_name = 'users' and column_name = 'encrypted_password'"
            )
    finally:
        db.close()
    if real:
        raise DevStackRefused("This database carries the real Supabase auth schema. The dev stack refuses to touch it.")


@dataclass
class DevStack:
    settings: CloudSettings
    db: Database
    api: FastAPI
    auth: FastAPI
    orchestrator: Orchestrator
    s3_url: str
    s3_server: Any

    def web_env(self, api_url: str, auth_url: str) -> dict[str, str]:
        return {
            "NEXT_PUBLIC_API_URL": api_url,
            "NEXT_PUBLIC_SUPABASE_URL": auth_url,
            "NEXT_PUBLIC_SUPABASE_ANON_KEY": "dev-anon-key-not-a-secret-0000000000",
            "NEXT_PUBLIC_STORAGE_ORIGIN": self.s3_url,
        }

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.s3_server.stop()
        self.db.close()


def build_stack(
    database_url: str,
    *,
    auth_url: str,
    web_origins: list[str],
    s3_port: int = 9090,
    signup_credits: int = 100,
    engine_delay_s: float = 0.6,
) -> DevStack:
    if os.environ.get("ARO_ENV") == "production":
        raise DevStackRefused("ARO_ENV=production: the dev stack never runs in production.")
    check_database_is_disposable(database_url)
    try:
        import boto3
        from moto.server import ThreadedMotoServer
    except ImportError as e:  # pragma: no cover
        raise DevStackRefused("The dev stack needs the dev requirements: pip install -r requirements-dev.txt") from e
    from aro_worker.engines.fake import FakeEngine
    from aro_worker.headless import run_pipeline
    from aro_worker.runpod_handler import Deps, HandlerConfig

    db = Database(database_url, ssl_mode="disable")
    with db.transaction() as tx:
        has_auth = bool(tx.one("select to_regclass('auth.users') as t")["t"])  # type: ignore[index]
    migrate(db, stub_auth=not has_auth)
    with db.transaction() as tx:
        tx.execute(
            """
            insert into model_registry (model_id, task, version, provider, code_licence_spdx, weights_licence, licence_status, verified_by, verified_at, enabled)
            values (:m, 'image_to_3d', 'test-double', 'local', 'MIT', 'not a model: procedural test double', 'verified', 'dev stack', now(), true)
            on conflict (model_id) do update set licence_status = 'verified', enabled = true
            """,
            m=ENGINE,
        )

    server = ThreadedMotoServer(ip_address="127.0.0.1", port=s3_port, verbose=False)
    server.start()
    s3_url = f"http://127.0.0.1:{s3_port}"
    boto = boto3.client(
        "s3",
        endpoint_url=s3_url,
        aws_access_key_id=S3_DEV_KEY,
        aws_secret_access_key=S3_DEV_KEY,
        region_name="us-east-1",
    )
    boto.create_bucket(Bucket=BUCKET)
    store = R2Store(
        bucket=BUCKET, endpoint_url=s3_url, access_key_id=S3_DEV_KEY, secret_access_key=S3_DEV_KEY, region="auto"
    )

    secret = secrets.token_urlsafe(48)  # exists only in this process
    settings = CloudSettings(
        env="development",
        supabase_url=auth_url,
        r2_endpoint_url=s3_url,
        r2_bucket=BUCKET,
        allowed_origins=",".join(web_origins),
        enabled_engines=ENGINE,
        allow_test_double=True,
        signup_credits=signup_credits,
        internal_token=secrets.token_urlsafe(32),
        dispatch_grace_s=120,
    )
    cfg = HandlerConfig(
        allowed_engines=(ENGINE,),
        allow_test_double=True,
        verified_licenses=ENGINE,
        allowed_hosts=("127.0.0.1", "localhost"),
        allow_insecure_urls=True,
    )
    deps = Deps(cfg, engine_factory=lambda _name: FakeEngine(delay_s=engine_delay_s, detail=3), pipeline=run_pipeline)
    provider = LocalWorkerProvider(deps)
    orch = Orchestrator(db, store, provider, settings)
    verifier = JwtVerifier(secret=secret, issuer=settings.jwt_issuer)
    api = create_app(settings, db=db, store=store, provider=provider, verifier=verifier, orchestrator=orch)
    auth = create_auth_app(db, secret, settings.jwt_issuer or "", web_origins)
    return DevStack(settings, db, api, auth, orch, s3_url, server)


def serve(app: FastAPI, port: int) -> uvicorn.Server:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, name=f"aro-dev-{port}", daemon=True).start()
    return server


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--database-url", default=os.environ.get("ARO_DEV_DATABASE_URL"))
    ap.add_argument("--api-port", type=int, default=8080)
    ap.add_argument("--auth-port", type=int, default=8081)
    ap.add_argument("--s3-port", type=int, default=9090)
    ap.add_argument("--web-origin", default="http://localhost:3000,http://127.0.0.1:3000")
    ap.add_argument(
        "--engine-delay",
        type=float,
        default=0.6,
        help="seconds per step of the test-double engine (so progress is visible)",
    )
    a = ap.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if not a.database_url:
        print(
            "set ARO_DEV_DATABASE_URL (a throwaway local PostgreSQL), e.g. postgresql://postgres@127.0.0.1:5432/aro_dev"
        )
        return 2
    api_url, auth_url = f"http://127.0.0.1:{a.api_port}", f"http://127.0.0.1:{a.auth_port}"
    try:
        stack = build_stack(
            a.database_url,
            auth_url=auth_url,
            web_origins=[o.strip() for o in a.web_origin.split(",") if o.strip()],
            s3_port=a.s3_port,
            engine_delay_s=a.engine_delay,
        )
    except DevStackRefused as e:
        print(f"refused: {e}")
        return 1
    serve(stack.api, a.api_port)
    serve(stack.auth, a.auth_port)
    print("\nLOCAL DEV STACK (test doubles; NOT AI; any email + password signs in)")
    print(f"  API       {api_url}    sign-in double {auth_url}    S3 double {stack.s3_url}")
    print("  web app:  cd apps/web && put these in .env.local, then `npm run dev`")
    for k, v in stack.web_env(api_url, auth_url).items():
        print(f"    {k}={v}")
    print("  Ctrl+C stops everything.\n", flush=True)
    try:
        while True:
            time.sleep(2)
            try:
                stack.orchestrator.reconcile_active()
            except Exception:  # noqa: BLE001
                log.exception("reconcile tick failed")
    except KeyboardInterrupt:
        pass
    finally:
        stack.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
