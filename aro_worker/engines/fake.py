"""A TEST DOUBLE (not AI): returns a procedural car-like mesh so the worker protocol and the Studio integration can be tested without
a GPU. It is labelled as a test double in its manifest and is never registered unless ``--engines fake`` is passed."""

from __future__ import annotations

import io
import time
from collections.abc import Callable
from typing import Any

import numpy as np
import trimesh
from PIL import Image

from aro_worker.engines.base import Cancelled, WorkerEngine, WorkerResult


class FakeEngine(WorkerEngine):
    id = "fake"
    name = "TEST DOUBLE (procedural, NOT AI)"
    version = "fake-1"
    vram_mb = 0
    license = {"spdx": "MIT", "source_url": "https://github.com/", "commercial_use": "allowed", "notes": "test double"}

    def __init__(self, delay_s: float = 0.0) -> None:
        self.delay_s = delay_s
        self.loaded = False

    def presets(self) -> dict[str, dict[str, Any]]:
        return {"STANDARD": {"seed": 1, "target_faces": 1000}}

    def available(self) -> tuple[bool, list[str]]:
        return True, []

    def load(self) -> None:
        self.loaded = True

    def unload(self) -> None:
        self.loaded = False

    def generate(
        self,
        image: Image.Image,
        settings: dict[str, Any],
        progress: Callable[[float, str], None],
        cancelled: Callable[[], bool],
    ) -> WorkerResult:
        parts = [
            trimesh.creation.box((1.8, 0.5, 4.2)).apply_translation((0, 0.55, 0)),
            trimesh.creation.box((1.6, 0.5, 2.0)).apply_translation((0, 1.0, -0.3)),
        ]
        for x in (-0.9, 0.9):
            for z in (-1.3, 1.3):
                w = trimesh.creation.cylinder(radius=0.35, height=0.25, sections=24)
                w.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 0, 1]))
                parts.append(w.apply_translation((x, 0.35, z)))
        mesh: trimesh.Trimesh = trimesh.util.concatenate(parts)  # type: ignore[assignment]
        mesh.visual = trimesh.visual.ColorVisuals(
            mesh=mesh, vertex_colors=np.tile([180, 60, 50, 255], (len(mesh.vertices), 1))
        )
        for i in range(5):
            if cancelled():
                raise Cancelled()
            progress(i / 5, "fake step")
            time.sleep(self.delay_s)
        buf = io.BytesIO()
        mesh.export(buf, file_type="glb")
        return WorkerResult(buf.getvalue(), {"settings": settings, "test_double": True, "image_size": list(image.size)})
