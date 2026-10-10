"""TEST DOUBLES - these prove the Studio's plumbing (job states, cache, memory manager, error handling).

They do NOT prove AI quality and are NEVER registered in the product. ``PlumbingEngine`` returns a trivial
icosphere so tests can exercise everything *around* inference; any test that uses it asserts on the plumbing
only. Real inference is covered by tests/test_triposr_real.py (needs weights + GPU, see docs/models).
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import trimesh

from aro_studio.core.errors import InvalidInputError, ModelError
from aro_studio.engines.base import (
    Availability,
    EngineInfo,
    GenerationOutput,
    GenerationRequest,
    ImageTo3DEngine,
    ModelLicense,
    ResourceEstimate,
)

LICENSE = ModelLicense(
    spdx="MIT",
    source_url="https://example.invalid/test-double",
    commercial_use="allowed",
    status="verified",
    notes="test double",
)


class PlumbingEngine(ImageTo3DEngine):
    info = EngineInfo(
        id="plumbing_test_double",
        name="Plumbing test double (NOT AI)",
        capability="image_to_3d",
        version="test-1",
        revision=None,
        source_url="https://example.invalid",
        license=LICENSE,
    )

    def __init__(
        self, *, fail: str | None = None, delay: float = 0.0, vram_mb: int | None = None, available: bool = True
    ):
        self.fail, self.delay, self.vram_mb, self._available = fail, delay, vram_mb, available
        self._loaded = False
        self.load_count = self.generate_count = self.unload_count = 0

    def availability(self, device: str) -> Availability:
        return Availability(
            ok=self._available, reasons=[] if self._available else ["test double disabled"], activation=["enable it"]
        )

    def presets(self) -> dict[str, dict[str, Any]]:
        return {"LOW_RESOURCE": {"n": 1}, "BALANCED": {"n": 2}}

    def normalize_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        n = settings.get("n", {"LOW_RESOURCE": 1}.get(settings.get("preset"), 2))
        if not isinstance(n, int) or n < 1:
            raise InvalidInputError("n must be a positive int")
        return {"n": n, "foreground_ratio": 0.85, "preset": settings.get("preset", "BALANCED")}

    def estimate_resources(self, settings: dict[str, Any], device: str) -> ResourceEstimate:
        return ResourceEstimate(self.vram_mb, 100, False)

    def load(self, device: str) -> None:
        if self.fail == "load":
            raise ModelError("weights missing")
        self._loaded = True
        self.load_count += 1

    def unload(self) -> None:
        self._loaded = False
        self.unload_count += 1

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def generate(self, request: GenerationRequest) -> GenerationOutput:
        self.generate_count += 1
        t0 = time.perf_counter()
        steps = max(1, int(self.delay / 0.02)) if self.delay else 1
        for i in range(steps):
            if request.cancel:
                request.cancel.check()
            if self.delay:
                time.sleep(0.02)
            if request.progress:
                request.progress((i + 1) / steps, "working")
        if self.fail == "oom":
            raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
        if self.fail == "empty":
            mesh = trimesh.Trimesh()
        else:
            mesh = trimesh.creation.icosphere(subdivisions=1 + request.settings["n"])
            mesh.visual = trimesh.visual.ColorVisuals(
                mesh=mesh, vertex_colors=(np.abs(mesh.vertices) * 255).astype(np.uint8)
            )
        request.workdir.mkdir(parents=True, exist_ok=True)
        f = request.workdir / "raw_output.glb"
        if len(mesh.faces):
            mesh.export(f)
        else:
            f.write_bytes(b"")
        return GenerationOutput(
            raw_file=f,
            output_format="glb",
            mesh=mesh,
            device="cpu",
            execution_time_s=time.perf_counter() - t0,
            details={"test_double": True},
        )
