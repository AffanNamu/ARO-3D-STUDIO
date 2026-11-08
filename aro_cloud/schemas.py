"""Request and response models. Strict: unknown fields are rejected, and only controls that actually change the result exist."""

from __future__ import annotations

import re
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class GenerationSettings(BaseModel):
    """What the user may choose. Each field is wired through to the engine or the preparation pipeline; nothing here is decorative."""

    model_config = ConfigDict(extra="forbid")
    preset: Literal["DRAFT", "STANDARD", "HIGH"] = (
        "STANDARD"  # engine quality tier (diffusion steps and surface-extraction resolution)
    )
    seed: int | None = Field(
        None, ge=0, le=2**31 - 1
    )  # None: the engine's default; same seed + same image reproduces the shape
    target_faces: int = Field(30_000, ge=2_000, le=200_000)  # triangle budget of LOD0 after preparation
    category: str = Field("other", min_length=1, max_length=40)  # asset category (orientation and proportion rules)
    length_m: float | None = Field(None, gt=0, le=60)  # real length in metres, when the user knows it
    texture_resolution: Literal[512, 1024, 2048] = 1024


class CreateGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["image_to_3d"]  # text_to_3d and multi_image_to_3d are not implemented and are refused, not faked
    upload_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    engine: str = Field("triposg", min_length=1, max_length=40)
    settings: GenerationSettings = Field(default_factory=GenerationSettings)
    project_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        v = v.strip()
        if not v or _CONTROL.search(v):
            raise ValueError("the name must be 1 to 120 printable characters")
        return v


class WorkerFile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: str
    bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class WorkerEngineInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    version: str | None = None
    test_double: bool = False


class WorkerResult(BaseModel):
    """What the RunPod handler returns. The API trusts none of it blindly: keys are rebuilt server-side and the GLB is re-validated."""

    model_config = ConfigDict(extra="ignore")
    schema_version: int = 1
    ok: bool
    engine: WorkerEngineInfo | None = None
    files: list[WorkerFile] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
