from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


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


class AutoProcessBody(BaseModel):
    """Settings for a non-destructive prepare/optimise/validate pass on a raw mesh."""

    length_m: float = Field(1.0, gt=0.01, le=100)
    up: str | None = Field(default=None, pattern=r"^[+-][XYZ]$")
    forward: str | None = Field(default=None, pattern=r"^[+-][XYZ]$")
    target_triangles: int = Field(24_000, ge=100, le=25_000)
    texture_resolution: Literal[512, 1024, 2048] = 1024
    lod: bool = True
    priority: int = Field(5, ge=1, le=9)

    @model_validator(mode="after")
    def axes_must_be_orthogonal(self):
        if self.up and self.forward and self.forward[1] == self.up[1]:
            raise ValueError("Up and forward directions must use different axes.")
        return self


class ExportBody(BaseModel):
    formats: list[str] = Field(default_factory=lambda: ["glb"], min_length=1, max_length=4)
    priority: int = Field(5, ge=1, le=9)
