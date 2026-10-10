"""Stable engine interfaces (spec §4). The rest of the Studio only ever sees these types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import trimesh
from PIL import Image

from aro_studio.core.cancellation import CancellationToken


@dataclass(frozen=True)
class ModelLicense:
    spdx: str  # e.g. "MIT"
    source_url: str  # where the licence text was read
    commercial_use: str  # allowed | restricted | prohibited | unknown
    # verified  = licence of code AND weights independently verified by a maintainer
    # claimed   = stated by the publisher but not yet verified for this exact weights revision
    # prohibited= licence forbids our use; engine may never be registered
    status: str
    notes: str = ""


@dataclass(frozen=True)
class EngineInfo:
    id: str
    name: str
    capability: str  # image_to_3d | texture | segmentation | ...
    version: str  # exact model/weights version used
    revision: str | None  # git/HF revision pin
    source_url: str
    license: ModelLicense
    description: str = ""
    requirements: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Availability:
    ok: bool
    reasons: list[str] = field(default_factory=list)  # blocking problems
    warnings: list[str] = field(default_factory=list)
    activation: list[str] = field(default_factory=list)  # exact steps to make the engine usable

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ResourceEstimate:
    vram_mb: int | None
    ram_mb: int | None
    measured: bool  # True only if the number comes from a real measurement
    note: str = ""


@dataclass
class GenerationRequest:
    image: Image.Image  # preprocessed model input (RGB)
    settings: dict[str, Any]
    workdir: Path
    cancel: CancellationToken | None = None
    progress: Callable[[float, str], None] | None = None


@dataclass
class GenerationOutput:
    raw_file: Path  # original engine artefact, kept untouched as the "raw" asset
    output_format: str  # glb | obj | ply
    mesh: trimesh.Trimesh
    device: str
    execution_time_s: float
    details: dict[str, Any] = field(default_factory=dict)


class ImageTo3DEngine(ABC):
    """Contract every image-to-3D model adapter fulfils."""

    info: EngineInfo

    @abstractmethod
    def availability(self, device: str) -> Availability: ...

    @abstractmethod
    def presets(self) -> dict[str, dict[str, Any]]:
        """Named, resource-aware setting bundles (e.g. LOW_RESOURCE / BALANCED / HIGH_QUALITY)."""

    @abstractmethod
    def normalize_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Validate and fill defaults. Must be deterministic: its output feeds the cache key."""

    @abstractmethod
    def estimate_resources(self, settings: dict[str, Any], device: str) -> ResourceEstimate: ...

    @abstractmethod
    def load(self, device: str) -> None:
        """Load weights onto ``device``. Raises EngineUnavailableError / ModelError."""

    @abstractmethod
    def unload(self) -> None:
        """Release model memory (including GPU cache)."""

    @property
    @abstractmethod
    def is_loaded(self) -> bool: ...

    @abstractmethod
    def generate(self, request: GenerationRequest) -> GenerationOutput:
        """Run real inference. Never substitutes placeholder geometry on failure."""
