"""Environment configuration. Every secret is a SecretStr (never logged); production refuses to start with anything missing."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PRODUCTION_REQUIRED = (
    "database_url",
    "supabase_url",
    "r2_bucket",
    "r2_access_key_id",
    "r2_secret_access_key",
    "runpod_api_key",
    "runpod_endpoint_id",
    "internal_token",
)


class ConfigError(RuntimeError):
    pass


class CloudSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARO_", extra="ignore")

    env: str = "development"  # production | development | test

    # --- Supabase (auth + PostgreSQL) -------------------------------------------------------------------------------------
    database_url: SecretStr | None = None  # postgresql://user:password@host:5432/postgres  (server-side only)
    database_ssl: str = (
        "auto"  # auto | verify | require | disable   (auto: verify for remote hosts, disable for localhost)
    )
    database_ca_file: str | None = None
    supabase_url: str | None = None  # https://<project-ref>.supabase.co
    supabase_jwks_url: str | None = None  # default: <supabase_url>/auth/v1/.well-known/jwks.json
    supabase_jwt_secret: SecretStr | None = None  # legacy HS256 projects only
    jwt_audience: str = "authenticated"

    # --- Cloudflare R2 (S3 API) ---------------------------------------------------------------------------------------------
    r2_account_id: str | None = None
    r2_endpoint_url: str | None = None  # default https://<account>.r2.cloudflarestorage.com ; overridden in tests
    r2_bucket: str | None = None
    r2_access_key_id: SecretStr | None = None
    r2_secret_access_key: SecretStr | None = None
    r2_region: str = "auto"
    signed_url_ttl_s: int = Field(600, ge=30, le=3600)

    # --- RunPod Serverless -----------------------------------------------------------------------------------------------
    runpod_api_key: SecretStr | None = None
    runpod_endpoint_id: str | None = None
    runpod_base_url: str = "https://api.runpod.ai/v2"
    execution_timeout_s: int = Field(900, ge=30, le=3600)  # RunPod `policy.executionTimeout`
    job_deadline_s: int = Field(
        1500, ge=120, le=3600
    )  # total life of a job; kept below RunPod's 30-minute result retention
    dispatch_grace_s: int = Field(
        120, ge=30, le=900
    )  # a dispatch with no run id after this long is declared uncertain, never re-sent
    max_attempts: int = Field(
        2, ge=1, le=3
    )  # sends per job; only a provider refusal that started nothing, or a worker error flagged retryable
    retry_backoff_s: int = Field(
        15, ge=1, le=300
    )  # a re-queued job waits attempt * this many seconds before it is sent again
    ingest_stale_s: int = Field(
        120, ge=30, le=900
    )  # an ingest that made no progress for this long may be taken over by another process
    gpu_usd_per_second: float | None = Field(
        None, ge=0
    )  # the owner's RunPod price for the chosen GPU; unset: no cost estimate is recorded

    # --- limits, pricing, behaviour -------------------------------------------------------------------------------------
    allowed_origins: str = ""  # comma-separated web origins for CORS
    internal_token: SecretStr | None = None  # protects POST /internal/reconcile (Cloud Scheduler)
    max_upload_mb: int = Field(10, ge=1, le=10)  # RunPod /run bodies are capped at 10 MB; images are sent by URL anyway
    max_image_pixels: int = 40_000_000
    min_image_side: int = 256
    max_active_jobs_per_user: int = Field(2, ge=1, le=20)
    requests_per_minute: int = Field(120, ge=10, le=6000)
    price_image_to_3d: int = Field(
        10, ge=1
    )  # credits reserved per generation (owner decision; not copied from any competitor)
    max_glb_mb: int = Field(150, ge=1, le=500)
    enabled_engines: str = (
        "triposg"  # engines a request may name; each must ALSO be enabled in model_registry by a person
    )
    signup_credits: int = Field(0, ge=0)  # free credits on first sign-in: an owner decision, default none
    allow_test_double: bool = False  # tests only: accept output flagged as a labelled test double (never in production)
    run_reconciler_thread: bool = False  # VM deployments; on Cloud Run use Cloud Scheduler + polling instead

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def engines(self) -> list[str]:
        return [e.strip() for e in self.enabled_engines.split(",") if e.strip()]

    @property
    def jwks_url(self) -> str | None:
        if self.supabase_jwks_url:
            return self.supabase_jwks_url
        if self.supabase_url:
            return self.supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json"
        return None

    @property
    def jwt_issuer(self) -> str | None:
        return self.supabase_url.rstrip("/") + "/auth/v1" if self.supabase_url else None

    @property
    def r2_endpoint(self) -> str | None:
        if self.r2_endpoint_url:
            return self.r2_endpoint_url
        return f"https://{self.r2_account_id}.r2.cloudflarestorage.com" if self.r2_account_id else None

    def validate_for_production(self) -> None:
        if self.env != "production":
            return
        missing = [f"ARO_{n.upper()}" for n in PRODUCTION_REQUIRED if not getattr(self, n)]
        if not (self.r2_endpoint):
            missing.append("ARO_R2_ACCOUNT_ID (or ARO_R2_ENDPOINT_URL)")
        if not (self.supabase_jwt_secret or self.jwks_url):
            missing.append("ARO_SUPABASE_URL / ARO_SUPABASE_JWKS_URL / ARO_SUPABASE_JWT_SECRET")
        if self.allow_test_double:
            raise ConfigError(
                "ARO_ALLOW_TEST_DOUBLE must never be set in production: it would accept non-AI output as a result."
            )
        if not self.origins:
            missing.append("ARO_ALLOWED_ORIGINS")
        if missing:
            raise ConfigError("Missing configuration for production: " + ", ".join(missing))
        token = self.internal_token.get_secret_value() if self.internal_token else ""
        if len(token) < 24:
            raise ConfigError("ARO_INTERNAL_TOKEN must be at least 24 characters.")


@lru_cache
def load_settings() -> CloudSettings:
    s = CloudSettings()
    s.validate_for_production()
    return s
