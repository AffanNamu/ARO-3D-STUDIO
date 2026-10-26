"""The contract a worker engine fulfils. Engines are plug-ins: heavy imports happen inside methods, never at import time."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image


class Cancelled(Exception):
    """Raised by an engine when the job was cancelled between stages."""


@dataclass
class WorkerResult:
    glb: bytes
    details: dict[str, Any] = field(default_factory=dict)


def gpu_info() -> dict[str, Any]:
    """Name / total / free VRAM of the first CUDA device (empty dict when there is none or torch is missing)."""
    try:
        import torch

        if not torch.cuda.is_available():
            return {}
        free, total = torch.cuda.mem_get_info(0)
        major, minor = torch.cuda.get_device_capability(0)
        return {
            "name": torch.cuda.get_device_name(0),
            "total_mb": int(total / 2**20),
            "free_mb": int(free / 2**20),
            "compute_capability": f"{major}.{minor}",
            "bf16": bool(torch.cuda.is_bf16_supported()),
        }
    except Exception:  # noqa: BLE001 - informational
        return {}


def require_cutout(image: Image.Image, min_ratio: float = 0.01) -> Image.Image:
    """The Studio sends a matted RGBA cut-out. An image without one would make the upstream pipelines run their own background-removal
    network (BRIA RMBG / RMBG-2.0 are non-commercial licences), or crash trying: refuse instead.

    "Real cut-out" mirrors the upstream validity test (TripoSG's ``is_valid_alpha``): at least ``min_ratio`` of the pixels fully
    transparent AND at least ``min_ratio`` fully opaque. Anything else (all opaque, all clear, a faint vignette) is not a cut-out.
    """
    rgba = image.convert("RGBA")
    alpha = np.asarray(rgba.getchannel("A"))
    n = alpha.size
    clear = float((alpha < 13).sum()) / n
    solid = float((alpha > 242).sum()) / n
    if clear < min_ratio and solid >= min_ratio:
        raise ValueError(
            "the image has no transparent background: send the Studio's matted RGBA cut-out (the worker never runs its own "
            "background-removal model, whose licence is non-commercial)"
        )
    if solid < min_ratio:
        raise ValueError("the cut-out is empty or almost fully transparent")
    if clear < min_ratio:
        raise ValueError("the cut-out has no clearly transparent pixels")
    return rgba


class WorkerEngine(ABC):
    id: str
    name: str
    version: str  # what actually ran (resolved model revision when known)
    vram_mb: int  # documented minimum for the default preset
    license: dict[
        str, str
    ]  # spdx, source_url, commercial_use, notes - the PUBLISHER's claim; the Studio keeps its own table

    @abstractmethod
    def available(self) -> tuple[bool, list[str]]:
        """(usable, reasons it is not). Must not load weights."""

    @abstractmethod
    def presets(self) -> dict[str, dict[str, Any]]: ...

    def normalize(self, settings: dict[str, Any]) -> dict[str, Any]:
        base = dict(self.presets().get(str(settings.get("preset") or "STANDARD"), next(iter(self.presets().values()))))
        for k, v in settings.items():
            if k in base and v is not None:
                base[k] = type(base[k])(v)
        base["preset"] = settings.get("preset") or "STANDARD"
        return base

    @abstractmethod
    def load(self) -> None: ...

    @abstractmethod
    def unload(self) -> None: ...

    @abstractmethod
    def generate(
        self,
        image: Image.Image,
        settings: dict[str, Any],
        progress: Callable[[float, str], None],
        cancelled: Callable[[], bool],
    ) -> WorkerResult:
        """``image`` is an RGBA CUT-OUT made by the Studio (permissively licensed matting): engines must use its alpha as given."""

    def manifest(self) -> dict[str, Any]:
        ok, reasons = self.available()
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "vram_mb": self.vram_mb,
            "license": self.license,
            "available": ok,
            "reasons": reasons,
            "presets": self.presets(),
        }
