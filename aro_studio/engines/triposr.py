"""TripoSR adapter (MIT, VAST-AI-Research / Stability AI).

Real integration against the public `tsr` package API:
    TSR.from_pretrained(path_or_repo, config_name="config.yaml", weight_name="model.ckpt")
    model.renderer.set_chunk_size(n); model.to(device)
    scene_codes = model([image], device=device)
    meshes = model.extract_mesh(scene_codes, has_vertex_color, resolution=...)

`tsr` is not on PyPI; it must be importable (see Dockerfile / docs/models/model-requirements.md).
Nothing in this module runs at import time that needs torch.
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path
from typing import Any

import trimesh

from aro_studio.core.errors import EngineUnavailableError, InvalidInputError, ModelError
from aro_studio.engines.base import (
    Availability,
    EngineInfo,
    GenerationOutput,
    GenerationRequest,
    ImageTo3DEngine,
    ModelLicense,
    ResourceEstimate,
)

TRIPOSR_LICENSE = ModelLicense(
    spdx="MIT",
    source_url="https://huggingface.co/stabilityai/TripoSR",
    commercial_use="allowed",
    status="claimed",
    notes=(
        "Code licence verified: github.com/VAST-AI-Research/TripoSR/LICENSE is the MIT licence (Tripo AI & Stability AI, 2024) "
        "and the README states source, pretrained models and demo are MIT. The Hugging Face model card could not be "
        "fetched from the build environment (network policy), so the WEIGHTS licence is not independently verified here."
    ),
)

INFO = EngineInfo(
    id="triposr",
    name="TripoSR",
    capability="image_to_3d",
    version="stabilityai/TripoSR (model.ckpt)",
    revision=None,  # pin a commit hash of the HF repo in deployment: ARO_TRIPOSR_MODEL_PATH
    source_url="https://github.com/VAST-AI-Research/TripoSR",
    license=TRIPOSR_LICENSE,
    description="Feed-forward single-image reconstruction (LRM-style triplane transformer) with marching-cubes mesh extraction.",
    requirements={
        "python": ">=3.9",
        "packages": [
            "torch",
            "omegaconf==2.3.0",
            "einops==0.7.0",
            "transformers==4.35.0",
            "huggingface-hub",
            "torchmcubes",
            "trimesh",
        ],
        "vram_mb_default": 6000,
        "vram_source": "TripoSR README: 'The default options takes about 6GB VRAM for a single image input.'",
        "weights_download": "stabilityai/TripoSR on huggingface.co (config.yaml + model.ckpt)",
    },
)

_PRESETS: dict[str, dict[str, Any]] = {
    "LOW_RESOURCE": {"mc_resolution": 160, "chunk_size": 2048, "foreground_ratio": 0.85, "mc_threshold": 25.0},
    "BALANCED": {"mc_resolution": 256, "chunk_size": 8192, "foreground_ratio": 0.85, "mc_threshold": 25.0},
    "HIGH_QUALITY": {"mc_resolution": 320, "chunk_size": 8192, "foreground_ratio": 0.85, "mc_threshold": 25.0},
}


class TripoSREngine(ImageTo3DEngine):
    info = INFO

    def __init__(self, model_path: str = "stabilityai/TripoSR", hf_token: str | None = None):
        self.model_path = model_path
        self._hf_token = hf_token
        self._model = None
        self._device: str | None = None

    # -- discovery ----------------------------------------------------------------------------
    def availability(self, device: str) -> Availability:
        missing = [
            m
            for m in ("torch", "omegaconf", "einops", "transformers", "huggingface_hub", "torchmcubes")
            if importlib.util.find_spec(m) is None
        ]
        reasons, warnings, activation = [], [], []
        if importlib.util.find_spec("tsr") is None:
            reasons.append("The 'tsr' package (TripoSR source) is not importable.")
            activation.append(
                "git clone https://github.com/VAST-AI-Research/TripoSR && add it to PYTHONPATH (the Dockerfile does this)."
            )
        if missing:
            reasons.append("Missing Python packages: " + ", ".join(missing) + ".")
            activation.append("pip install -r requirements-triposr.txt  (torch must match the host CUDA version)")
        if not reasons:
            try:
                import torch

                if device.startswith("cuda") and not torch.cuda.is_available():
                    reasons.append("CUDA device requested but torch.cuda.is_available() is False.")
                    activation.append("Run on a GPU host or set ARO_DEVICE=cpu.")
                elif device == "cpu":
                    warnings.append("Running on CPU: reconstruction will be very slow and needs several GB of RAM.")
            except Exception as e:  # noqa: BLE001
                reasons.append(f"torch failed to import: {type(e).__name__}: {e}")
        p = Path(self.model_path)
        if p.is_dir():
            for f in ("config.yaml", "model.ckpt"):
                if not (p / f).is_file():
                    reasons.append(f"Local model directory is missing '{f}'.")
        else:
            warnings.append(
                f"Weights will be downloaded from huggingface.co ('{self.model_path}') on first load; this needs outbound network access."
            )
        return Availability(ok=not reasons, reasons=reasons, warnings=warnings, activation=activation)

    def presets(self) -> dict[str, dict[str, Any]]:
        return {k: dict(v) for k, v in _PRESETS.items()}

    def normalize_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        base = dict(_PRESETS["BALANCED"])
        preset = settings.get("preset")
        if preset:
            if preset not in _PRESETS:
                raise InvalidInputError(
                    f"Unknown preset '{preset}'.", recommended_action=f"Use one of {sorted(_PRESETS)}"
                )
            base = dict(_PRESETS[preset])
        for k in ("mc_resolution", "chunk_size", "foreground_ratio", "mc_threshold"):
            if k in settings and settings[k] is not None:
                base[k] = settings[k]
        try:
            base["mc_resolution"] = int(base["mc_resolution"])
            base["chunk_size"] = int(base["chunk_size"])
            base["foreground_ratio"] = float(base["foreground_ratio"])
            base["mc_threshold"] = float(base["mc_threshold"])
        except (TypeError, ValueError) as e:
            raise InvalidInputError("Generation settings must be numeric.") from e
        if not 32 <= base["mc_resolution"] <= 512:
            raise InvalidInputError("mc_resolution must be between 32 and 512.")
        if base["chunk_size"] != 0 and not 256 <= base["chunk_size"] <= 65536:
            raise InvalidInputError("chunk_size must be 0 (no chunking) or between 256 and 65536.")
        if not 0.3 <= base["foreground_ratio"] <= 1.0:
            raise InvalidInputError("foreground_ratio must be between 0.3 and 1.0.")
        base["preset"] = preset or "BALANCED"
        return base

    def estimate_resources(self, settings: dict[str, Any], device: str) -> ResourceEstimate:
        s = self.normalize_settings(settings)
        default = s["mc_resolution"] == 256 and s["chunk_size"] == 8192
        if device.startswith("cuda"):
            if default:
                return ResourceEstimate(6000, 4000, True, "Published by TripoSR for default options (single image).")
            return ResourceEstimate(
                6000 if s["chunk_size"] in (0, 8192, 16384) else 4500,
                4000,
                False,
                "Estimate only: not measured for non-default settings.",
            )
        return ResourceEstimate(None, 6000, False, "CPU inference: RAM estimate only, not measured.")

    # -- lifecycle ----------------------------------------------------------------------------
    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self, device: str) -> None:
        av = self.availability(device)
        if not av.ok:
            raise EngineUnavailableError(
                "TripoSR cannot run in this environment: " + " ".join(av.reasons),
                recommended_action=" ".join(av.activation) or "See docs/models/model-requirements.md.",
                details=av.to_dict(),
            )
        import torch
        from tsr.system import TSR

        try:
            if self._hf_token:
                import os

                os.environ.setdefault("HF_TOKEN", self._hf_token)
            model = TSR.from_pretrained(self.model_path, config_name="config.yaml", weight_name="model.ckpt")
            model.to(device)
        except torch.cuda.OutOfMemoryError as e:
            self.unload()
            raise ModelError(
                "GPU ran out of memory while loading TripoSR.",
                recommended_action="Use a GPU with >= 8 GB VRAM or run on CPU.",
            ) from e
        except Exception as e:
            self.unload()
            raise ModelError(
                f"Failed to load TripoSR weights: {type(e).__name__}: {e}",
                recommended_action="Check the model path/network access and the weights files.",
            ) from e
        self._model, self._device = model, device

    def unload(self) -> None:
        self._model = None
        self._device = None
        import gc

        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001, S110
            pass

    # -- inference ----------------------------------------------------------------------------
    def generate(self, request: GenerationRequest) -> GenerationOutput:
        if not self.is_loaded or self._model is None or self._device is None:
            raise EngineUnavailableError("TripoSR is not loaded.", recommended_action="Call load() first.")
        import torch

        s = self.normalize_settings(request.settings)
        model, device = self._model, self._device
        t0 = time.perf_counter()
        if request.cancel:
            request.cancel.check()
        if request.progress:
            request.progress(0.1, "Running TripoSR transformer")
        try:
            model.renderer.set_chunk_size(s["chunk_size"])
            with torch.no_grad():
                scene_codes = model([request.image.convert("RGB")], device=device)
                if request.cancel:
                    request.cancel.check()
                if request.progress:
                    request.progress(0.6, "Extracting surface (marching cubes)")
                meshes = model.extract_mesh(
                    scene_codes, True, resolution=s["mc_resolution"], threshold=s["mc_threshold"]
                )
        except torch.cuda.OutOfMemoryError:
            self.unload()
            raise
        mesh: trimesh.Trimesh = meshes[0]
        if len(mesh.faces) == 0 or len(mesh.vertices) == 0:
            raise ModelError(
                "TripoSR produced an empty surface.",
                recommended_action="Lower mc_threshold, use a cleaner subject on a plain background, or try another view.",
            )
        request.workdir.mkdir(parents=True, exist_ok=True)
        raw_file = request.workdir / "raw_output.glb"
        mesh.export(raw_file)  # original artefact, untouched
        return GenerationOutput(
            raw_file=raw_file,
            output_format="glb",
            mesh=mesh,
            device=device,
            execution_time_s=time.perf_counter() - t0,
            details={"mc_resolution": s["mc_resolution"], "coordinate_frame": "TripoSR native (unrotated)"},
        )
