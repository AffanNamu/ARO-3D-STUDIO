"""TRELLIS.2 (Microsoft, 4B parameters, MIT): fully textured PBR assets from one image.

UNVERIFIED ON HARDWARE until a GPU run is recorded (docs/architecture/product-reassessment.md). Written from the official README and
pipeline source (microsoft/TRELLIS.2). Licensing notes that matter for a commercial game studio:

* the repository is MIT; the model weights' licence must be read on the model card (https://huggingface.co/microsoft/TRELLIS.2-4B);
* ``nvdiffrec`` (installed by the upstream setup script, used only to RENDER previews) is licensed NON-COMMERCIAL: this worker never
  imports it and the install script does not install it. ``nvdiffrast`` is the "1-way commercial" NVIDIA licence (commercial use ok);
* image conditioning uses DINOv3, a gated Hugging Face model: accept Meta's terms and give the worker an HF_TOKEN.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image

from aro_worker.engines.base import Cancelled, WorkerEngine, WorkerResult, gpu_info, require_cutout

log = logging.getLogger("aro_worker")
REPO_ID = "microsoft/TRELLIS.2-4B"


class Trellis2Engine(WorkerEngine):
    id = "trellis2"
    name = "TRELLIS.2 (4B, PBR)"
    version = f"{REPO_ID}@UNRESOLVED"
    vram_mb = 24_000  # README: "An NVIDIA GPU with at least 24GB of memory is necessary" (verified on A100 / H100 by the authors)
    license = {
        "spdx": "MIT",
        "source_url": "https://github.com/microsoft/TRELLIS.2/blob/main/LICENSE",
        "commercial_use": "allowed",
        "notes": "code MIT; weights licence to be read on the model card; do not use nvdiffrec (non-commercial); DINOv3 weights are gated",
    }

    def __init__(self) -> None:
        self._pipe: Any = None

    def presets(self) -> dict[str, dict[str, Any]]:
        return {
            # pipeline_type values are the pipeline's own: '512', '1024_cascade', '1536_cascade' (README: ~17 s at 1024, ~60 s at 1536 on H100)
            "DRAFT": {"pipeline_type": "512", "target_faces": 200_000, "texture_size": 2048, "seed": 42},
            "STANDARD": {"pipeline_type": "1024_cascade", "target_faces": 400_000, "texture_size": 4096, "seed": 42},
            "HIGH": {"pipeline_type": "1536_cascade", "target_faces": 1_000_000, "texture_size": 4096, "seed": 42},
        }

    def available(self) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        for mod in ("trellis2", "o_voxel"):
            if importlib.util.find_spec(mod) is None:
                reasons.append(
                    f"python package '{mod}' is not importable (run worker/install_engines.sh and set PYTHONPATH to the TRELLIS.2 checkout)"
                )
        g = gpu_info()
        if not g:
            reasons.append("no CUDA GPU is available")
        elif g["total_mb"] < 15_000:
            reasons.append(f"GPU has {g['total_mb']} MB; TRELLIS.2 documents a 24 GB minimum")
        return not reasons, reasons

    def warnings(self) -> list[str]:
        g = gpu_info()
        out = []
        if g and g["total_mb"] < self.vram_mb - 1500:
            out.append(
                f"{g['name']} has {g['total_mb']} MB, below the documented 24 GB: only the DRAFT preset may fit (unmeasured)"
            )
        if g and not g.get("bf16", True):
            out.append("this GPU has no native bf16 (e.g. T4): the bf16 flow models may be very slow or fail")
        return out

    def load(self) -> None:
        os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
        from trellis2.pipelines import Trellis2ImageTo3DPipeline

        self._pipe = Trellis2ImageTo3DPipeline.from_pretrained(REPO_ID)
        self._pipe.cuda()
        sha = None
        try:  # the resolved revision is RECORDED (the upstream loader does not pin one)
            from huggingface_hub import HfApi

            sha = HfApi().model_info(REPO_ID).sha
        except Exception as e:  # noqa: BLE001 - the revision is informational
            log.info("could not resolve the model revision: %s", e)
        self.version = f"{REPO_ID}@{sha or 'UNRESOLVED'}"

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
            raise RuntimeError("TRELLIS.2 is not loaded")
        import torch

        s = self.normalize(settings)
        t0 = time.perf_counter()
        torch.cuda.reset_peak_memory_stats()
        if cancelled():
            raise Cancelled()
        progress(0.08, f"TRELLIS.2 {s['pipeline_type']}: sampling structure, shape and PBR materials")
        # an RGBA input with a real alpha is used as given: the Studio's cut-out, no second matting model is involved
        mesh = self._pipe.run(
            require_cutout(image), seed=int(s["seed"]), pipeline_type=s["pipeline_type"], preprocess_image=True
        )[0]
        mesh.simplify(16_777_216)  # nvdiffrast limit, as in the upstream example
        if cancelled():
            raise Cancelled()
        progress(0.75, f"Extracting a textured GLB ({s['target_faces']:,} faces, {s['texture_size']} px)")
        import o_voxel

        glb = o_voxel.postprocess.to_glb(
            vertices=mesh.vertices,
            faces=mesh.faces,
            attr_volume=mesh.attrs,
            coords=mesh.coords,
            attr_layout=mesh.layout,
            voxel_size=mesh.voxel_size,
            aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
            decimation_target=int(s["target_faces"]),
            texture_size=int(s["texture_size"]),
            remesh=True,
            remesh_band=1,
            remesh_project=0,
            verbose=False,
        )
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.glb"
            glb.export(str(out), extension_webp=False)  # PNG textures: readable by every importer
            data = out.read_bytes()
        peak = int(torch.cuda.max_memory_allocated() / 2**20)
        torch.cuda.empty_cache()
        progress(1.0, "done")
        return WorkerResult(
            data,
            {
                "settings": s,
                "seconds": round(time.perf_counter() - t0, 2),
                "peak_vram_allocated_mb": peak,
                "pbr": True,
                "gpu": gpu_info(),
            },
        )
