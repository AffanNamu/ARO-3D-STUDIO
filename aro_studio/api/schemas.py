from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    metadata: dict[str, Any] | None = None


class DuplicateBody(BaseModel):
    name: str | None = Field(default=None, max_length=120)


class AssetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    metadata: dict[str, Any] | None = None


class StatusBody(BaseModel):
    status: str


class DesignateBody(BaseModel):
    semver: str | None = Field(default=None, pattern=r"^\d+\.\d+\.\d+$")


class GenerateBody(BaseModel):
    image_sha256: str = Field(min_length=64, max_length=64)
    engine_id: str | None = None
    preset: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    preprocess: dict[str, Any] | None = None
    device: str | None = None
    use_cache: bool = True
    force: bool = False
    priority: int = Field(5, ge=1, le=9)
    max_retries: int = Field(0, ge=0, le=3)


class ProcessBody(BaseModel):
    operation: str
    params: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(5, ge=1, le=9)


class ExportBody(BaseModel):
    formats: list[str] = Field(default_factory=lambda: ["glb"], min_length=1, max_length=4)
    priority: int = Field(5, ge=1, le=9)
