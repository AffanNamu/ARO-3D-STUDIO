"""Runtime configuration. All sensitive values come from environment variables (spec §52-53)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARO_", env_file=".env", extra="ignore")

    data_dir: Path = Field(default=Path("data"), description="Root of all persistent studio data")
    # Access control. If set, every API call must carry `Authorization: Bearer <token>`.
    access_token: SecretStr | None = None
    cors_origins: list[str] = []

    # Uploads / security
    max_upload_mb: int = 25
    max_image_pixels: int = 64_000_000
    min_image_side: int = 64
    max_import_mb: int = 200  # mesh / archive imports
    max_archive_members: int = 2000
    max_archive_uncompressed_mb: int = 1000
    rate_limit_per_minute: int = 120
    heavy_rate_limit_per_minute: int = 20

    # Execution
    workers: int = 1  # one worker by default: free GPUs are shared and small
    job_timeout_s: int = 1800
    job_max_retries: int = 1
    device: str = "auto"  # auto | cpu | cuda | cuda:0
    default_engine: str = "triposr"
    model_idle_unload_s: int = 300
    min_free_disk_mb: int = 500
    min_free_ram_mb: int = 1024
    # Comma-separated engine ids whose *weights licence* the deployer has personally verified.
    verified_model_licenses: str = ""
    triposr_model_path: str = "stabilityai/TripoSR"  # HF repo id or local directory
    hf_token: SecretStr | None = None  # never logged

    # Budgets
    tri_budget_lod0: int = 150_000
    log_level: str = "INFO"

    @property
    def verified_licenses(self) -> set[str]:
        return {x.strip().lower() for x in self.verified_model_licenses.split(",") if x.strip()}

    @property
    def db_path(self) -> Path:
        return self.data_dir / "studio.sqlite3"


@lru_cache
def get_settings() -> Settings:
    return Settings()
