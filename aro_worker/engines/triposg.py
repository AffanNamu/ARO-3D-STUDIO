"""TripoSG (VAST-AI, 1.5B rectified-flow shape model, MIT): high-resolution GEOMETRY only (no texture), about 8 GB of VRAM (fp16).

STATUS: written against the upstream source (VAST-AI-Research/TripoSG: ``scripts/inference_triposg.py``, ``scripts/image_process.py``,
``triposg/pipelines/pipeline_triposg.py``, ``triposg/inference_utils.py``, read 2026-10-26) but NOT run on a GPU yet. The first real run
is the open evidence item (docs/architecture/product-reassessment.md).

Licensing and install notes that matter:

* The upstream script removes backgrounds with BRIA RMBG-1.4, licensed NON-COMMERCIALLY. This plug-in never loads it: it hands the
  Studio's RGBA cut-out to upstream's ``prepare_image`` which uses a valid alpha as given (``require_cutout`` guarantees it is valid,
  because with ``rmbg_net=None`` an invalid alpha would crash instead of matting).
* ``triposg.inference_utils`` imports ``diso`` (a CUDA extension compiled at install). When it cannot be imported, the CPU
  marching-cubes stand-in ``aro_worker.shims.diso_shim`` is registered under that name; the details of every result say which one ran.
* The mesh has no colour: the Studio projects the reference image onto it afterwards.
"""

from __future__ import annotations

import importlib.util
import io
import logging
import os
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image

from aro_worker.engines.base import Cancelled, WorkerEngine, WorkerResult, gpu_info, require_cutout

log = logging.getLogger("aro_worker")
REPO_ID = "VAST-AI/TripoSG"


def ensure_diso() -> str:
    """Make ``import diso`` work. Returns "diso" (the compiled package) or "skimage-shim" (the CPU stand-in)."""
    try:
        import diso  # noqa: F401

        return "diso"
    except Exception as e:  # noqa: BLE001 - missing, or built against a different CUDA
        log.warning("diso is not importable (%s): using the skimage marching-cubes stand-in", type(e).__name__)
        from aro_worker.shims import diso_shim

        sys.modules["diso"] = diso_shim
        return "skimage-shim"


class TripoSGEngine(WorkerEngine):
    id = "triposg"
    name = "TripoSG (1.5B, geometry only)"
    version = f"{REPO_ID}@UNRESOLVED"
    vram_mb = 8_000  # upstream README: "CUDA-enabled GPU with at least 8GB VRAM"
    license = {
        "spdx": "MIT",
        "source_url": "https://github.com/VAST-AI-Research/TripoSG/blob/main/LICENSE",
        "commercial_use": "allowed",
        "notes": "code MIT; weights licence to be read on the model card; BRIA RMBG-1.4 (non-commercial) is NOT used; no texture is produced",
    }

    def __init__(self) -> None:
        self._pipe: Any = None
        self._diso = "unknown"
        self._root = Path(os.environ.get("TRIPOSG_DIR", "/opt/TripoSG"))

    def presets(self) -> dict[str, dict[str, Any]]:
        # flash_octree_depth is the iso-surface grid: 8 = 256^3, 9 = 512^3 (upstream default). Depth 10 (1024^3) needs the real diso and
        # a lot of memory: it is not offered.
        return {
            "DRAFT": {"steps": 25, "guidance": 7.0, "octree_depth": 8, "target_faces": 150_000, "seed": 42},
            "STANDARD": {"steps": 50, "guidance": 7.0, "octree_depth": 9, "target_faces": 400_000, "seed": 42},
            "HIGH": {"steps": 70, "guidance": 7.5, "octree_depth": 9, "target_faces": 800_000, "seed": 42},
        }

    def available(self) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if not (self._root / "triposg").is_dir():
            reasons.append(
                f"TripoSG checkout not found at {self._root} (set TRIPOSG_DIR; run worker/install_engines.sh or the notebook's setup cell)"
            )
        for mod in ("torch", "diffusers", "skimage", "cv2", "einops"):
            if importlib.util.find_spec(mod) is None:
                reasons.append(f"python package '{mod}' is not installed in the worker environment")
        g = gpu_info()
        if not g:
            reasons.append("no CUDA GPU is available")
        elif g["total_mb"] < self.vram_mb:
            reasons.append(f"GPU has {g['total_mb']} MB; TripoSG documents {self.vram_mb} MB")
        return not reasons, reasons

    def warnings(self) -> list[str]:
        return (
            []
            if importlib.util.find_spec("diso")
            else ["diso is not installed: the slower CPU marching-cubes stand-in will be used"]
        )

    def load(self) -> None:
        import torch
        from huggingface_hub import snapshot_download

        for p in (str(self._root), str(self._root / "scripts")):
            if p not in sys.path:
                sys.path.insert(0, p)
        self._diso = ensure_diso()
        from triposg.pipelines.pipeline_triposg import TripoSGPipeline

        weights = Path(os.environ.get("ARO_WORKER_CACHE", str(Path(tempfile.gettempdir()) / "aro_worker"))) / "TripoSG"
        # pin to an exact commit: ARO_TRIPOSG_REVISION if the operator chose one, else the head commit resolved right now (and recorded)
        revision = os.environ.get("ARO_TRIPOSG_REVISION") or None
        if revision is None:
            try:
                from huggingface_hub import HfApi

                revision = HfApi().model_info(REPO_ID).sha
            except Exception as e:  # noqa: BLE001 - fall back to the default branch, which is then recorded as unresolved
                log.warning("could not resolve the TripoSG revision (%s): downloading the default branch", e)
        snapshot_download(repo_id=REPO_ID, revision=revision, local_dir=str(weights))
        self._pipe = TripoSGPipeline.from_pretrained(str(weights)).to("cuda", torch.float16)
        self.version = f"{REPO_ID}@{revision or 'UNRESOLVED'}"

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
            raise RuntimeError("TripoSG is not loaded")
        import numpy as np
        import torch
        import trimesh
        from image_process import prepare_image  # upstream helper (scripts/image_process.py)

        s = self.normalize(settings)
        t0 = time.perf_counter()
        torch.cuda.reset_peak_memory_stats()
        if cancelled():
            raise Cancelled()
        cutout = require_cutout(image)
        progress(0.08, "Preparing the cut-out")
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.png"
            cutout.save(src)
            prepared = prepare_image(str(src), bg_color=np.array([1.0, 1.0, 1.0]), rmbg_net=None)
        steps = int(s["steps"])

        def on_step(_pipe: Any, i: int, _t: Any, kw: dict[str, Any]) -> dict[str, Any]:
            progress(0.12 + 0.68 * (i + 1) / steps, f"TripoSG: flow step {i + 1} of {steps}")
            if cancelled():
                raise Cancelled()
            return kw

        with torch.no_grad():
            out = self._pipe(
                image=prepared,
                generator=torch.Generator(device=self._pipe.device).manual_seed(int(s["seed"])),
                num_inference_steps=steps,
                guidance_scale=float(s["guidance"]),
                flash_octree_depth=int(s["octree_depth"]),
                callback_on_step_end=on_step,
            ).samples[0]
        progress(0.9, "Building the mesh")
        if out is None or out[0] is None:
            raise RuntimeError(
                "TripoSG produced no mesh (the iso-surface extraction failed: see the worker log; out of memory is the usual cause)"
            )
        mesh = trimesh.Trimesh(np.asarray(out[0], dtype=np.float32), np.ascontiguousarray(out[1]))
        raw_faces = len(mesh.faces)
        if cancelled():
            raise Cancelled()
        notes: list[str] = []
        if raw_faces > int(s["target_faces"]):
            try:
                import fast_simplification

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
                "surface_extractor": self._diso,
                "pbr": False,
                "coordinate_frame": "engine native (unverified: the Studio detects the up axis from the reference image)",
                "notes": notes,
                "gpu": gpu_info(),
            },
        )
