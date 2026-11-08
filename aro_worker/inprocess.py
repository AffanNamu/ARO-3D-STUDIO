"""Run a worker engine inside the Studio's own pipeline, in the same process (no HTTP hop).

The RunPod handler cannot call an HTTP worker that does not exist, so this adapter gives the Studio's ``ImageTo3DEngine`` contract an
implementation that calls the ``WorkerEngine`` directly. Everything else (matting, up-axis detection, mesh preparation, UVs, texture
projection, validation, export) is the Studio pipeline unchanged. Licences are taken from the Studio's table, never from the engine.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from aro_studio.core.errors import EngineUnavailableError, InvalidInputError, ModelError
from aro_studio.engines.base import (
    Availability,
    EngineInfo,
    GenerationOutput,
    GenerationRequest,
    ImageTo3DEngine,
    ResourceEstimate,
)
from aro_studio.engines.remote import KNOWN, _load_single_mesh
from aro_worker.engines.base import Cancelled, WorkerEngine, gpu_info


class InProcessEngine(ImageTo3DEngine):
    def __init__(self, engine: WorkerEngine) -> None:
        if engine.id not in KNOWN:
            raise InvalidInputError(f"Unknown engine '{engine.id}'.", recommended_action=f"Known: {sorted(KNOWN)}")
        self.engine = engine
        k = KNOWN[engine.id]
        self.info = EngineInfo(
            id=engine.id,
            name=k["name"].replace(" - remote GPU", " - GPU worker"),
            capability="image_to_3d",
            version=engine.version,
            revision=None,
            source_url=k["source_url"],
            license=k["license"],  # the Studio's reading of the licence, not the engine's claim
            description=k["description"],
            requirements={"in_process": True},
        )
        self._loaded = False

    def availability(self, device: str) -> Availability:
        ok, reasons = self.engine.available()
        warnings = []
        if hasattr(self.engine, "warnings"):
            warnings = list(self.engine.warnings())
        g = gpu_info()
        if g:
            warnings.append(f"runs on the worker GPU: {g.get('name')} ({g.get('total_mb')} MB)")
        return Availability(
            ok, reasons, warnings, [] if ok else ["Fix the reasons above in the worker image or its environment."]
        )

    def presets(self) -> dict[str, dict[str, Any]]:
        return {k: dict(v) for k, v in self.engine.presets().items()}

    def normalize_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        name = str(settings.get("preset") or "STANDARD")
        if name not in self.engine.presets():
            raise InvalidInputError(
                f"Unknown preset '{name}'.", recommended_action=f"Use one of {sorted(self.engine.presets())}"
            )
        out = self.engine.normalize({**settings, "preset": name})
        out["foreground_ratio"] = float(settings.get("foreground_ratio", 0.85))  # the Studio's own preprocessing input
        return out

    def estimate_resources(self, settings: dict[str, Any], device: str) -> ResourceEstimate:
        return ResourceEstimate(
            self.engine.vram_mb, None, False, "documented minimum from the engine's upstream README, not measured"
        )

    def load(self, device: str) -> None:
        ok, reasons = self.engine.available()
        if not ok:
            raise EngineUnavailableError(
                " ".join(reasons), recommended_action="Fix the worker image or its environment."
            )
        if not self.engine.resident:  # a warm worker loads the weights once, not once per job
            self.engine.load()
            self.engine.resident = True
        self._loaded = True
        self._sync_version()

    def unload(self) -> None:
        """The Studio unloads at job end and shutdown; on a serverless worker the weights stay resident (see ``release``)."""
        self._loaded = False

    def release(self) -> None:
        self.engine.unload()
        self.engine.resident = False
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def _sync_version(self) -> None:
        if self.engine.version != self.info.version:
            self.info = EngineInfo(**{**self.info.__dict__, "version": self.engine.version})

    def generate(self, request: GenerationRequest) -> GenerationOutput:
        t0 = time.perf_counter()
        s = self.normalize_settings(request.settings)
        sent = {k: v for k, v in s.items() if k != "foreground_ratio"}
        img = (request.cutout or request.image).convert("RGBA")
        alpha_min: Any = img.getchannel("A").getextrema()[0]
        if int(alpha_min) >= 250:
            raise InvalidInputError(
                f"{self.info.name} needs the subject cut out of its background, but this image has no transparency.",
                recommended_action="Use automatic background removal, or upload an image with a transparent background.",
            )

        def progress(p: float, message: str) -> None:
            if request.progress:
                request.progress(0.05 + 0.9 * max(0.0, min(1.0, p)), f"GPU: {message}")

        def cancelled() -> bool:
            return bool(request.cancel and request.cancel.cancelled)

        try:
            res = self.engine.generate(img, sent, progress, cancelled)
        except Cancelled:
            if request.cancel:
                request.cancel.check()
            raise
        self._sync_version()
        request.workdir.mkdir(parents=True, exist_ok=True)
        raw = Path(request.workdir) / "raw_output.glb"
        raw.write_bytes(res.glb)  # the engine's artefact, untouched
        mesh = _load_single_mesh(raw)
        if len(mesh.faces) == 0:
            raise ModelError("The engine returned an empty mesh.")
        details = dict(res.details)
        gpu = (details.get("gpu") or {}).get("name") or "local"
        return GenerationOutput(
            raw_file=raw,
            output_format="glb",
            mesh=mesh,
            device=f"gpu:{gpu}",
            execution_time_s=time.perf_counter() - t0,
            details={
                "engine_version": self.engine.version,
                "worker_seconds": details.get("seconds"),
                "peak_vram_allocated_mb": details.get("peak_vram_allocated_mb"),
                "pbr": details.get("pbr"),
                "worker_details": {k: v for k, v in details.items() if k != "gpu"},
                "coordinate_frame": "engine native (glTF, +Y up as written by the engine)",
                "extents": [float(x) for x in mesh.extents],
                "test_double": bool(getattr(self.engine, "test_double", False)),
            },
        )


__all__ = ["InProcessEngine"]
