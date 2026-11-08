"""Builds the running service from environment settings: the one place that knows which concrete database, store, provider and verifier to use."""

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI

from aro_cloud.api import create_app
from aro_cloud.auth import JwtVerifier
from aro_cloud.db import Database
from aro_cloud.orchestrator import Orchestrator
from aro_cloud.providers import RunPodProvider
from aro_cloud.settings import CloudSettings, ConfigError, load_settings
from aro_cloud.storage import R2Store

log = logging.getLogger("aro_cloud")
RECONCILE_EVERY_S = 15.0


def build_database(s: CloudSettings) -> Database:
    if not s.database_url:
        raise ConfigError("ARO_DATABASE_URL is not set.")
    return Database(s.database_url.get_secret_value(), ssl_mode=s.database_ssl, ca_file=s.database_ca_file)


def build_store(s: CloudSettings) -> R2Store:
    if not (s.r2_endpoint and s.r2_bucket and s.r2_access_key_id and s.r2_secret_access_key):
        raise ConfigError(
            "Cloudflare R2 is not configured (ARO_R2_ACCOUNT_ID, ARO_R2_BUCKET, ARO_R2_ACCESS_KEY_ID, ARO_R2_SECRET_ACCESS_KEY)."
        )
    return R2Store(
        bucket=s.r2_bucket,
        endpoint_url=s.r2_endpoint,
        access_key_id=s.r2_access_key_id.get_secret_value(),
        secret_access_key=s.r2_secret_access_key.get_secret_value(),
        region=s.r2_region,
    )


def build_provider(s: CloudSettings) -> RunPodProvider:
    if not (s.runpod_api_key and s.runpod_endpoint_id):
        raise ConfigError("RunPod is not configured (ARO_RUNPOD_API_KEY, ARO_RUNPOD_ENDPOINT_ID).")
    return RunPodProvider(
        api_key=s.runpod_api_key.get_secret_value(), endpoint_id=s.runpod_endpoint_id, base_url=s.runpod_base_url
    )


def build_verifier(s: CloudSettings) -> JwtVerifier:
    return JwtVerifier(
        audience=s.jwt_audience,
        issuer=s.jwt_issuer,
        secret=s.supabase_jwt_secret.get_secret_value() if s.supabase_jwt_secret else None,
        jwks_url=s.jwks_url,
    )


def build_orchestrator(s: CloudSettings) -> Orchestrator:
    return Orchestrator(build_database(s), build_store(s), build_provider(s), s)


def create() -> FastAPI:
    """uvicorn factory: ``uvicorn aro_cloud.wiring:create --factory``."""
    s = load_settings()
    orch = build_orchestrator(s)
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(RECONCILE_EVERY_S):
            try:
                orch.reconcile_active()
            except Exception:  # noqa: BLE001
                log.exception("reconcile tick failed")

    @contextlib.asynccontextmanager
    async def lifespan(_: Any) -> AsyncIterator[None]:
        thread = None
        if (
            s.run_reconciler_thread
        ):  # every step is a compare-and-set, so several instances running this is safe (just redundant)
            thread = threading.Thread(target=loop, name="aro-reconciler", daemon=True)
            thread.start()
        try:
            yield
        finally:
            stop.set()
            orch.db.close()

    return create_app(
        s,
        db=orch.db,
        store=orch.store,
        provider=orch.provider,
        verifier=build_verifier(s),
        orchestrator=orch,
        lifespan=lifespan,
    )
