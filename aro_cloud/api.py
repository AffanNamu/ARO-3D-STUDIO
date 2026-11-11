"""The HTTP API the web app talks to.

Every ``/v1`` route needs a Supabase access token (``Authorization: Bearer``), is scoped to the caller's own rows, and answers errors
with one envelope: ``{"error": {"code", "message", "recommended_action", "details"}}``. Handlers are synchronous on purpose: they
call PostgreSQL, R2 and RunPod with blocking clients, and FastAPI runs them in its thread pool.
"""

from __future__ import annotations

import hmac
import logging
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from aro_cloud import __version__, accounts, assets, exports, jobs, uploads
from aro_cloud.auth import JwtVerifier, Principal
from aro_cloud.db import Database
from aro_cloud.errors import ApiError, InvalidRequest, NotFound, TooManyRequests, Unauthorized, Unavailable
from aro_cloud.orchestrator import Orchestrator
from aro_cloud.providers.base import ModelProvider
from aro_cloud.schemas import CreateGeneration, RenameAsset
from aro_cloud.settings import CloudSettings
from aro_cloud.storage import ObjectStore
from aro_studio.core.errors import RateLimitedError
from aro_studio.security.ratelimit import RateLimiter

log = logging.getLogger("aro_cloud.api")
JSON_BODY_LIMIT = 64 * 1024
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp")

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]


class _TooLarge(Exception):
    pass


class BodyLimitMiddleware:
    """Refuse oversized request bodies before they are buffered (Content-Length, or the running total for chunked bodies)."""

    def __init__(self, app: Any, limit_for: Callable[[str], int]):
        self.app = app
        self.limit_for = limit_for

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        limit = self.limit_for(scope["path"])
        declared = dict(scope["headers"]).get(b"content-length")
        started = False

        async def too_large() -> None:
            body = ApiError("The request body is too large.", code="payload_too_large").body()
            resp = JSONResponse(body, status_code=413)
            await resp(scope, receive, send)

        if declared is not None and declared.isdigit() and int(declared) > limit:
            await too_large()
            return
        total = 0

        async def limited_receive() -> MutableMapping[str, Any]:
            nonlocal total
            msg = await receive()
            if msg["type"] == "http.request":
                total += len(msg.get("body", b""))
                if total > limit:
                    raise _TooLarge
            return msg

        async def tracking_send(msg: MutableMapping[str, Any]) -> None:
            nonlocal started
            if msg["type"] == "http.response.start":
                started = True
            await send(msg)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _TooLarge:
            if not started:
                await too_large()


def job_view(job: dict[str, Any], asset_id: str | None = None) -> dict[str, Any]:
    """What a client may see of a job. The provider's run id, storage keys and idempotency data stay on the server."""
    err = {"code": job["error_code"], "message": job["error_message"]} if job.get("error_code") else None
    return {
        "job_id": job["job_id"],
        "name": job["name"],
        "kind": job["kind"],
        "engine": job["model_id"],
        "state": job["state"],
        "progress": job["progress"],
        "status_message": job["status_message"],
        "error": err,
        "attempt": job["attempt"],
        "cancel_requested": job["cancel_requested"],
        "credits": {"reserved": job["credits_reserved"], "captured": job["credits_captured"]},
        "created_at": _iso(job["created_at"]),
        "started_at": _iso(job["started_at"]),
        "finished_at": _iso(job["finished_at"]),
        "result": {"asset_id": asset_id, "version_id": job["result_version_id"]}
        if job["state"] == "completed" and asset_id
        else None,
        "settings": (job.get("request") or {}).get("settings"),
        "upload_id": job.get("upload_id"),
    }


def _iso(v: Any) -> str | None:
    return v.isoformat() if hasattr(v, "isoformat") else None


def create_app(
    settings: CloudSettings,
    *,
    db: Database,
    store: ObjectStore,
    provider: ModelProvider,
    verifier: JwtVerifier,
    orchestrator: Orchestrator | None = None,
    lifespan: Any = None,
) -> FastAPI:
    orch = orchestrator or Orchestrator(db, store, provider, settings)
    limiter = RateLimiter(settings.requests_per_minute)
    prod = settings.env == "production"
    app = FastAPI(
        title="ARO 3D AI Studio API",
        version=__version__,
        docs_url=None if prod else "/docs",
        redoc_url=None,
        openapi_url=None if prod else "/openapi.json",
        lifespan=lifespan,
    )

    upload_limit = settings.max_upload_mb * 1_000_000 + 4096
    app.add_middleware(
        BodyLimitMiddleware, limit_for=lambda path: upload_limit if path == "/v1/uploads" else JSON_BODY_LIMIT
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        allow_credentials=False,
        max_age=600,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Cache-Control", "no-store")
        resp.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        return resp

    # ---------------------------------------------------------------------------------------------------------- errors
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, e: ApiError) -> JSONResponse:
        headers: dict[str, str] = {}
        if isinstance(e, Unauthorized):
            headers["WWW-Authenticate"] = "Bearer"
        if isinstance(e, TooManyRequests) and e.details.get("retry_after_s"):
            headers["Retry-After"] = str(e.details["retry_after_s"])
        return JSONResponse(e.body(), status_code=e.status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, e: RequestValidationError) -> JSONResponse:
        problems = [
            {"field": ".".join(str(p) for p in err.get("loc", ())[1:]), "problem": str(err.get("msg", ""))[:200]}
            for err in e.errors()[:10]
        ]
        body = InvalidRequest(
            "The request is not valid.",
            recommended_action="Fix the listed fields and send it again.",
            details={"problems": problems},
        ).body()
        return JSONResponse(body, status_code=422)  # input values are never echoed back

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, e: Exception) -> JSONResponse:
        log.error("unhandled %s", type(e).__name__, exc_info=e)
        body = ApiError(
            "Something went wrong on our side.", recommended_action="Try again in a moment.", code="internal_error"
        ).body()
        return JSONResponse(body, status_code=500)

    # ------------------------------------------------------------------------------------------------------------ auth
    def principal(request: Request) -> Principal:
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise Unauthorized(
                "Sign in to continue.", recommended_action="Send your access token as 'Authorization: Bearer <token>'."
            )
        who = verifier.verify(token.strip())
        try:
            limiter.check(str(who.user_id))
        except RateLimitedError as e:
            raise TooManyRequests(e.message, recommended_action=e.recommended_action, details=e.details) from None
        return who

    # ---------------------------------------------------------------------------------------------------------- health
    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        ok = db.healthy()
        return JSONResponse({"status": "ready" if ok else "database_unreachable"}, status_code=200 if ok else 503)

    # ------------------------------------------------------------------------------------------------------------- me
    @app.get("/v1/me")
    def me(who: Principal = Depends(principal)) -> dict[str, Any]:
        with db.transaction() as tx:
            created = accounts.ensure_account(tx, who.user_id, settings.signup_credits)
            credits = accounts.balance(tx, who.user_id)
            engines = tx.all(
                "select model_id, version from model_registry where enabled and task = 'image_to_3d' order by model_id"
            )
        return {
            "user_id": str(who.user_id),
            "email": who.email,
            "new_user": created,
            "credits": credits,
            "price": {"image_to_3d": settings.price_image_to_3d},
            "engines": [e["model_id"] for e in engines if e["model_id"] in settings.engines],
            "limits": {
                "max_upload_mb": settings.max_upload_mb,
                "min_image_side": settings.min_image_side,
                "max_active_jobs": settings.max_active_jobs_per_user,
                "target_faces": [2_000, 25_000],
                "export_formats": list(exports.FORMATS),
            },
        }

    # ------------------------------------------------------------------------------------------------------- uploads
    @app.post("/v1/uploads", status_code=201)
    async def upload(request: Request, who: Principal = Depends(principal)) -> dict[str, Any]:
        ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype not in IMAGE_TYPES:
            raise InvalidRequest(
                "Send the image itself as the request body with Content-Type image/png, image/jpeg or image/webp.",
                code="unsupported_media_type",
            )
        data = bytearray()
        limit = settings.max_upload_mb * 1_000_000
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > limit:
                raise InvalidRequest(
                    f"The image is larger than {settings.max_upload_mb} MB.",
                    recommended_action="Downscale or compress it.",
                    code="image_too_large",
                )
        return await run_in_threadpool(uploads.create_upload, db, store, settings, who.user_id, bytes(data))

    @app.get("/v1/uploads/{upload_id}")
    def upload_link(upload_id: uuid.UUID, who: Principal = Depends(principal)) -> dict[str, Any]:
        return uploads.upload_url(db, store, who.user_id, upload_id, settings.signed_url_ttl_s)

    # ---------------------------------------------------------------------------------------------------- generations
    @app.post("/v1/generations")
    def create_generation(
        body: CreateGeneration,
        response: Response,
        who: Principal = Depends(principal),
        idempotency_key: str = Header("", alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        job, created = orch.submit(who.user_id, body, idempotency_key)
        if created:
            response.status_code = 201
            try:
                job = orch.dispatch(job["job_id"]) or job
            except Exception:  # noqa: BLE001 - the job is safely queued; the scheduler or the next poll sends it
                log.exception("dispatch failed for job %s", job["job_id"])
        return job_view(job)

    @app.get("/v1/generations")
    def list_generations(
        who: Principal = Depends(principal),
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0, le=100_000),
    ) -> dict[str, Any]:
        with db.transaction() as tx:
            rows = jobs.list_for_owner(tx, who.user_id, limit, offset)
            versions = [r["result_version_id"] for r in rows if r["result_version_id"]]
            asset_of = {}
            if versions:
                asset_of = {
                    str(r["version_id"]): str(r["asset_id"])
                    for r in tx.all(
                        "select version_id, asset_id from asset_versions where version_id = any(CAST(:v AS uuid[])) and owner_id = CAST(:o AS uuid)",
                        v=versions,
                        o=str(who.user_id),
                    )
                }
        return {
            "items": [job_view(r, asset_of.get(r["result_version_id"] or "")) for r in rows],
            "limit": limit,
            "offset": offset,
        }

    def _own_job(job_id: uuid.UUID, who: Principal) -> dict[str, Any]:
        job = orch.get(job_id, who.user_id)
        if job is None:
            raise NotFound("That generation does not exist.", code="job_not_found")
        return job

    def _view_with_asset(job: dict[str, Any], who: Principal) -> dict[str, Any]:
        asset_id = None
        if job["state"] == "completed" and job["result_version_id"]:
            with db.transaction() as tx:
                row = tx.one(
                    "select asset_id from asset_versions where version_id = CAST(:v AS uuid) and owner_id = CAST(:o AS uuid)",
                    v=job["result_version_id"],
                    o=str(who.user_id),
                )
            asset_id = str(row["asset_id"]) if row else None
        return job_view(job, asset_id)

    @app.get("/v1/generations/{job_id}")
    def get_generation(job_id: uuid.UUID, who: Principal = Depends(principal)) -> dict[str, Any]:
        job = _own_job(job_id, who)
        if (
            job["state"] not in jobs.TERMINAL
        ):  # polling is what keeps a job moving on a host that throttles background threads
            try:
                job = orch.reconcile(job_id, min_interval_s=2.5) or job
            except Exception:  # noqa: BLE001 - a provider hiccup must not turn a status read into an error
                log.exception("reconcile failed for job %s", job_id)
        return _view_with_asset(job, who)

    @app.get("/v1/generations/{job_id}/events")
    def generation_events(job_id: uuid.UUID, who: Principal = Depends(principal)) -> dict[str, Any]:
        _own_job(job_id, who)
        with db.transaction() as tx:
            ev = jobs.events(tx, job_id)
        return {
            "items": [
                {
                    "at": _iso(e["at"]),
                    "from": e["from_state"],
                    "to": e["to_state"],
                    "message": (e["detail"] or {}).get("message"),
                }
                for e in ev
            ]
        }

    @app.post("/v1/generations/{job_id}/cancel")
    def cancel_generation(job_id: uuid.UUID, who: Principal = Depends(principal)) -> dict[str, Any]:
        return _view_with_asset(orch.cancel(who.user_id, job_id), who)

    # ------------------------------------------------------------------------------------------------------- library
    @app.get("/v1/assets")
    def list_assets(
        who: Principal = Depends(principal),
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0, le=100_000),
        q: str | None = Query(None, max_length=100),
    ) -> dict[str, Any]:
        with db.transaction() as tx:
            return {"items": assets.list_assets(tx, who.user_id, limit, offset, q), "limit": limit, "offset": offset}

    @app.get("/v1/assets/{asset_id}")
    def get_asset(asset_id: uuid.UUID, who: Principal = Depends(principal)) -> dict[str, Any]:
        with db.transaction() as tx:
            return assets.get_asset(tx, who.user_id, asset_id)

    @app.patch("/v1/assets/{asset_id}")
    def rename_asset(asset_id: uuid.UUID, body: RenameAsset, who: Principal = Depends(principal)) -> dict[str, Any]:
        with db.transaction() as tx:
            return assets.rename_asset(tx, who.user_id, asset_id, body.name)

    @app.delete("/v1/assets/{asset_id}", status_code=204)
    def delete_asset(asset_id: uuid.UUID, who: Principal = Depends(principal)) -> Response:
        with db.transaction() as tx:
            assets.delete_asset(tx, who.user_id, asset_id)
        return Response(status_code=204)

    @app.get("/v1/assets/{asset_id}/versions/{version_no}/exports/{fmt}")
    def asset_export(
        asset_id: uuid.UUID, version_no: int, fmt: str, who: Principal = Depends(principal)
    ) -> dict[str, Any]:
        """Another file format of the model (obj, stl, ply), converted once on first request."""
        return exports.export_file(
            db,
            store,
            who.user_id,
            asset_id,
            version_no,
            fmt.lower(),
            max_glb_bytes=settings.max_glb_mb * 1_000_000,
            ttl_s=settings.signed_url_ttl_s,
        )

    @app.get("/v1/assets/{asset_id}/versions/{version_no}/files/{role}")
    def asset_file(
        asset_id: uuid.UUID, version_no: int, role: str, who: Principal = Depends(principal)
    ) -> dict[str, Any]:
        with db.transaction() as tx:
            return assets.file_url(tx, store, who.user_id, asset_id, version_no, role, settings.signed_url_ttl_s)

    # ------------------------------------------------------------------------------------------------------- credits
    @app.get("/v1/credits")
    def credits(who: Principal = Depends(principal)) -> dict[str, Any]:
        with db.transaction() as tx:
            return {**accounts.balance(tx, who.user_id), "price": {"image_to_3d": settings.price_image_to_3d}}

    @app.get("/v1/credits/ledger")
    def credit_ledger(
        who: Principal = Depends(principal),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0, le=100_000),
    ) -> dict[str, Any]:
        with db.transaction() as tx:
            rows = accounts.ledger(tx, who.user_id, limit, offset)
        for r in rows:
            r["at"] = _iso(r["at"])
        return {"items": rows, "limit": limit, "offset": offset}

    # ------------------------------------------------------------------------------------------------------ internal
    @app.post("/internal/reconcile")
    def internal_reconcile(x_internal_token: str = Header("", alias="X-Internal-Token")) -> dict[str, int]:
        expected = settings.internal_token.get_secret_value() if settings.internal_token else ""
        if not expected:
            raise Unavailable("The reconcile endpoint is not configured.", code="reconcile_disabled")
        if not hmac.compare_digest(x_internal_token.encode(), expected.encode()):
            raise Unauthorized("Invalid internal token.")
        return orch.reconcile_active()

    return app
