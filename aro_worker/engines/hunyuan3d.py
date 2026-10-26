"""Hunyuan3D-2 mini (Tencent, 0.6B flow-matching shape model): geometry only, about 6 GB of VRAM for shape generation.

EVALUATION ONLY. The licence (Tencent Hunyuan 3D 2.0 Community License, read 2026-10-26) does not apply in the EU, UK and South Korea
and forbids using the Works, Outputs or results there; forbids using Outputs to improve any other AI model; needs a separate licence
above 1 M monthly active users; and requires end-user disclosure when used to provide a service. Some files of the repository still carry
an older "NON-COMMERCIAL" header, so the position is ambiguous. It is therefore registered as ``restricted`` and the Studio refuses to
run it until a person attests it; it is a quality yardstick for the benchmark, not a product dependency. Do not offer it to users in
the excluded territories.

STATUS: written against the upstream source (Tencent-Hunyuan/Hunyuan3D-2: ``minimal_demo.py``, ``hy3dgen/shapegen/pipelines.py``), NOT
run on a GPU yet. Only the shape stage is used (the texture stage needs about 16 GB and compiled rasteriser extensions); the Studio
projects the reference image onto the mesh afterwards. Upstream's demo runs ``rembg`` on RGB input; this plug-in always passes the Studio's
cut-out, so no matting model runs.
"""

from __future__ import annotations

import importlib.util
import io
import logging
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image

from aro_worker.engines.base import Cancelled, WorkerEngine, WorkerResult, gpu_info, require_cutout

log = logging.getLogger("aro_worker")
REPO_ID = "tencent/Hunyuan3D-2mini"
SUBFOLDER = "hunyuan3d-dit-v2-mini"


class Hunyuan3DEngine(WorkerEngine):
    id = "hunyuan3d"
    name = "Hunyuan3D-2 mini (shape only, EVALUATION ONLY: restricted licence)"
    version = f"{REPO_ID}/{SUBFOLDER}@UNRESOLVED"
    vram_mb = 6_000  # upstream README: "6 GB VRAM for shape generation"
    license = {
        "spdx": "LicenseRef-Tencent-Hunyuan-3D-2.0-Community",
        "source_url": "https://github.com/Tencent-Hunyuan/Hunyuan3D-2/blob/main/LICENSE",
        "commercial_use": "restricted",
        "notes": "not valid in the EU, UK, South Korea (including Outputs); no training other models on Outputs; >1M MAU needs a licence",
    }

    def __init__(self) -> None:
        self._pipe: Any = None
        self._root = Path(os.environ.get("HUNYUAN3D_DIR", "/opt/Hunyuan3D-2"))

    def presets(self) -> dict[str, dict[str, Any]]:
        return {
            "DRAFT": {"steps": 30, "guidance": 5.0, "octree_resolution": 256, "target_faces": 150_000, "seed": 42},
            "STANDARD": {"steps": 50, "guidance": 5.0, "octree_resolution": 384, "target_faces": 400_000, "seed": 42},
            "HIGH": {"steps": 50, "guidance": 5.0, "octree_resolution": 512, "target_faces": 800_000, "seed": 42},
        }

    def available(self) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if not (self._root / "hy3dgen").is_dir():
            reasons.append(
                f"Hunyuan3D-2 checkout not found at {self._root} (set HUNYUAN3D_DIR; run the notebook's setup cell or worker/install_engines.sh)"
            )
        for mod in ("torch", "diffusers", "pymeshlab", "cv2", "einops"):
            if importlib.util.find_spec(mod) is None:
                reasons.append(f"python package '{mod}' is not installed in the worker environment")
        g = gpu_info()
        if not g:
            reasons.append("no CUDA GPU is available")
        elif g["total_mb"] < self.vram_mb:
            reasons.append(f"GPU has {g['total_mb']} MB; Hunyuan3D-2 documents {self.vram_mb} MB for shape generation")
        return not reasons, reasons

    def warnings(self) -> list[str]:
        return [
            "restricted licence: evaluation only, not for the EU, UK or South Korea, never to train other models (see the module docstring)"
        ]

    def load(self) -> None:
        if str(self._root) not in sys.path:
            sys.path.insert(0, str(self._root))
        from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline

        self._pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(REPO_ID, subfolder=SUBFOLDER)
        sha = None
        try:
            from huggingface_hub import HfApi

            sha = HfApi().model_info(REPO_ID).sha
        except Exception as e:  # noqa: BLE001 - informational
            log.info("could not resolve the model revision: %s", e)
        self.version = f"{REPO_ID}/{SUBFOLDER}@{sha or 'UNRESOLVED'}"

    def unload(self) -> None:
        self._pipe = None
        import gc

        gc.collect()
        try:
            import torch

            torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001, S110
            pass

    def generate(
        self,
        image: Image.Image,
        settings: dict[str, Any],
        progress: Callable[[float, str], None],
        cancelled: Callable[[], bool],
    ) -> WorkerResult:
        if self._pipe is None:
            raise RuntimeError("Hunyuan3D is not loaded")
        import torch

        s = self.normalize(settings)
        t0 = time.perf_counter()
        torch.cuda.reset_peak_memory_stats()
        if cancelled():
            raise Cancelled()
        cutout = require_cutout(image)
        steps = int(s["steps"])

        def on_step(step_idx: int, _t: Any, _outputs: Any) -> None:
            progress(0.1 + 0.7 * (step_idx + 1) / steps, f"Hunyuan3D: flow step {step_idx + 1} of {steps}")
            if cancelled():
                raise Cancelled()

        progress(0.08, "Hunyuan3D: encoding the image")
        out = self._pipe(
            image=cutout,
            num_inference_steps=steps,
            guidance_scale=float(s["guidance"]),
            octree_resolution=int(s["octree_resolution"]),
            generator=torch.Generator(device="cpu").manual_seed(int(s["seed"])),
            callback=on_step,
            callback_steps=1,
        )
        mesh = out[0]
        raw_faces = len(mesh.faces)
        notes: list[str] = []
        if raw_faces > int(s["target_faces"]):
            try:
                import fast_simplification
                import numpy as np
                import trimesh

                v, f = fast_simplification.simplify(
                    np.asarray(mesh.vertices, dtype=np.float64),
                    np.asarray(mesh.faces, dtype=np.int64),
                    target_reduction=1.0 - int(s["target_faces"]) / raw_faces,
                )
                mesh = trimesh.Trimesh(v, f, process=False)
            except ImportError:
                notes.append("fast_simplification missing: the full-resolution mesh is returned")
        buf = io.BytesIO()
        mesh.export(buf, file_type="glb")
        peak = int(torch.cuda.max_memory_allocated() / 2**20)
        torch.cuda.empty_cache()
        progress(1.0, "done")
        return WorkerResult(
            buf.getvalue(),
            {
                "settings": s,
                "seconds": round(time.perf_counter() - t0, 2),
                "peak_vram_allocated_mb": peak,
                "raw_faces": raw_faces,
                "returned_faces": int(len(mesh.faces)),
                "pbr": False,
                "coordinate_frame": "engine native (unverified: the Studio detects the up axis from the reference image)",
                "licence_warning": "evaluation only: restricted licence",
                "notes": notes,
                "gpu": gpu_info(),
            },
        )
