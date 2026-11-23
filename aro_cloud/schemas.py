"""Request and response models. Strict: unknown fields are rejected, and only controls that actually change the result exist."""

from __future__ import annotations

import re
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aro_cloud.keys import JOB_FILES

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
    target_faces: int = Field(24_000, ge=2_000, le=25_000)  # triangle budget of LOD0 after preparation
    category: str = Field("other", min_length=1, max_length=40)  # asset category (orientation and proportion rules)
    length_m: float | None = Field(None, gt=0, le=60)  # real length in metres, when the user knows it
    # Real width and height. From one photo the model often gets the proportions wrong (a 3/4 view comes out too short for its
    # width): with these the Studio fits each axis to the real size, and says in the report that it stretched the model.
    width_m: float | None = Field(None, gt=0, le=60)
    height_m: float | None = Field(None, gt=0, le=60)
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


class RenameAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)

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


# ---------------------------------------------------------------------------------------------- what the RunPod handler receives
INLINE_IMAGE_MAX_BYTES = 6_000_000  # RunPod's /run body limit is ~10 MB, and base64 adds a third


class WorkerImage(BaseModel):
    """The one input image: a pre-signed GET URL (what the API sends), or the bytes themselves in base64 for a direct test
    (``python -m aro_cloud.direct_test``; only when the worker allows inline transfers)."""

    model_config = ConfigDict(extra="ignore")
    get_url: str | None = Field(None, min_length=10, max_length=4096)
    data_b64: str | None = Field(None, min_length=8, max_length=(INLINE_IMAGE_MAX_BYTES * 4) // 3 + 8)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(gt=0, le=10_000_000)
    content_type: Literal["image/png", "image/jpeg", "image/webp"]

    @model_validator(mode="after")
    def _exactly_one_source(self) -> WorkerImage:
        if (self.get_url is None) == (self.data_b64 is None):
            raise ValueError("give exactly one of image.get_url and image.data_b64")
        return self


class WorkerOutputSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    put_url: str = Field(
        min_length=10, max_length=4096
    )  # pre-signed PUT for exactly one key; the worker holds no storage credentials
    content_type: str = Field(min_length=3, max_length=100)


class WorkerInput(BaseModel):
    """The ``input`` of a RunPod /run call. Shared by the API (which builds it) and the handler (which parses it), so a contract test
    catches drift. Unknown fields are ignored so an older worker image keeps working while the API is upgraded first."""

    model_config = ConfigDict(extra="ignore")
    schema_version: Literal[1]
    job_id: uuid.UUID
    kind: Literal["image_to_3d"]
    engine: str = Field(min_length=1, max_length=40)
    image: WorkerImage
    settings: GenerationSettings
    outputs: dict[str, WorkerOutputSpec] | Literal["inline"]
    limits: dict[str, int] = Field(default_factory=dict)

    @property
    def inline(self) -> bool:
        return self.outputs == "inline"

    @model_validator(mode="after")
    def _outputs_are_the_fixed_set(self) -> WorkerInput:
        if isinstance(self.outputs, dict) and set(self.outputs) != set(JOB_FILES):
            raise ValueError("outputs must be exactly: " + ", ".join(sorted(JOB_FILES)))
        if self.inline != (self.image.data_b64 is not None):
            raise ValueError("an inline image goes with inline outputs, and a URL image with output URLs")
        return self
