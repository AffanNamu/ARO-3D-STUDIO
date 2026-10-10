"""TripoSR adapter (MIT, VAST-AI-Research / Stability AI).

Integration against the public ``tsr`` package, but **not** through upstream's ``TSR.from_pretrained``, which (at the
pinned commit) (1) downloads from the Hub without a ``revision``, (2) calls ``torch.load`` without ``weights_only`` and
(3) imports any class path named in ``config.yaml``; its image tokenizer also (4) downloads ``facebook/dino-vitb16``'s
``config.json`` unpinned on every construction. See docs/models/triposr-security-review.md. This adapter instead:

    verify every file against engines/locks/triposr.json → allow-list config class paths → construct ``TSR(cfg)`` with the
    tokenizer download replaced by the pinned local file → ``torch.load(weights_only=True)`` → ``load_state_dict``.

``tsr`` is not on PyPI; it must be importable (see Dockerfile). Nothing here imports torch at import time.
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path
from typing import Any
from unittest import mock

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
from aro_studio.engines.weights import ModelLock, load_lock, resolve_weights, validate_config_classes


def _licence_from_lock(lock: ModelLock) -> ModelLicense:
    """Status is 'verified' ONLY when the lock is complete (evidence + pinned revision + checksums)."""
    missing = lock.missing()
    lic = lock.license
    ev = "; ".join(
        f"{e.source} ({'independently fetched' if e.independently_fetched else 'owner statement'}, {e.verified_on})"
        for e in lic.evidence
    )
    notes = f"{lic.scope}. Evidence: {ev}."
    if missing:
        notes += " NOT YET VERIFIED FOR A SPECIFIC ARTEFACT - still required: " + "; ".join(missing) + "."
    return ModelLicense(
        spdx=lic.spdx,
        source_url="https://huggingface.co/stabilityai/TripoSR",
        commercial_use=lic.commercial_use,
        status="claimed" if missing else "verified",
        notes=notes,
    )


def _build_info(lock: ModelLock) -> EngineInfo:
    rev = lock.weights.revision
    return EngineInfo(
        id="triposr",
        name="TripoSR",
        capability="image_to_3d",
        version=f"{lock.weights.repo_id}@{rev or 'UNPINNED'}",
        revision=rev,
        source_url="https://github.com/VAST-AI-Research/TripoSR",
        license=_licence_from_lock(lock),
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
            "weights_download": f"{lock.weights.repo_id} (config.yaml + model.ckpt) at pinned revision {rev or '(not pinned yet)'}; "
            "plus facebook/dino-vitb16 config.json (pinned)",
            "code_commit": lock.code.get("commit"),
        },
    )


# Derived from upstream SOURCE, not from running the model: tsr/utils.py::to_gradio_3d_orientation applies Rx(-90°) then
# Ry(+90°) before display, which maps native +Z to +Y (up). Which native direction is the object's FRONT is not stated
# upstream: confirm visually on the first real output, then use the Geometry "Re-orient" step.
ORIENTATION_HINT = {
    "native_up": "+Z",
    "basis": "tsr/utils.py::to_gradio_3d_orientation = Rx(-90deg) then Ry(+90deg) at upstream commit 107cefd",
    "forward": "UNCONFIRMED: decide from the first real output",
    "status": "inferred_from_source_not_yet_verified_by_inference",
}

MIN_TORCH = (2, 6, 0)


def _version_tuple(v: str) -> tuple[int, ...]:
    nums = []
    for part in str(v).split("+")[0].split(".")[:3]:
        digits = "".join(ch for ch in part if ch.isdigit())
        nums.append(int(digits) if digits else 0)
    return tuple(nums + [0] * (3 - len(nums)))


_PRESETS: dict[str, dict[str, Any]] = {
    "LOW_RESOURCE": {"mc_resolution": 160, "chunk_size": 2048, "foreground_ratio": 0.85, "mc_threshold": 25.0},
    "BALANCED": {"mc_resolution": 256, "chunk_size": 8192, "foreground_ratio": 0.85, "mc_threshold": 25.0},
    "HIGH_QUALITY": {"mc_resolution": 320, "chunk_size": 8192, "foreground_ratio": 0.85, "mc_threshold": 25.0},
}


class TripoSREngine(ImageTo3DEngine):
    def __init__(
        self, model_path: str = "stabilityai/TripoSR", hf_token: str | None = None, lock: ModelLock | None = None
    ):
        self.lock = lock or load_lock("triposr")
        self.info = _build_info(self.lock)
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
        lock_missing = self.lock.missing()
        if lock_missing:
            reasons.append("Supply-chain lock incomplete: " + "; ".join(lock_missing) + ".")
            activation.append(
                "python scripts/pin_triposr_weights.py   (needs Hugging Face access) → review the diff of engines/locks/triposr.json → commit"
            )
        if importlib.util.find_spec("tsr") is None:
            reasons.append("The 'tsr' package (TripoSR source) is not importable.")
            activation.append(
                f"git clone https://github.com/VAST-AI-Research/TripoSR && git -C TripoSR checkout {self.lock.code.get('commit')} && add it to PYTHONPATH (the Dockerfile does this)."
            )
        if missing:
            reasons.append("Missing Python packages: " + ", ".join(missing) + ".")
            activation.append("pip install -r requirements-triposr.txt  (torch must match the host CUDA version)")
        if not reasons:
            try:
                import torch

                if _version_tuple(getattr(torch, "__version__", "0")) < MIN_TORCH:
                    reasons.append(
                        f"torch {getattr(torch, '__version__', '?')} is too old: torch >= {'.'.join(map(str, MIN_TORCH))} is required because "
                        "torch.load(weights_only=True) had a published remote-code-execution bypass in earlier releases."
                    )
                    activation.append("pip install 'torch>=2.6.0' (matching your CUDA build)")
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
        elif self.model_path != self.lock.weights.repo_id:
            reasons.append(
                f"ARO_TRIPOSR_MODEL_PATH='{self.model_path}' is neither the pinned repo '{self.lock.weights.repo_id}' nor a local directory."
            )
        else:
            warnings.append(
                f"Weights will be downloaded from huggingface.co at pinned revision {self.lock.weights.revision} and SHA-256 verified before loading."
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
                recommended_action=" | ".join(av.activation) or "See docs/models/model-requirements.md.",
                details=av.to_dict(),
            )
        import torch
        import tsr.models.tokenizers.image as tokenizer_module
        from omegaconf import OmegaConf
        from tsr.system import TSR

        try:
            if self._hf_token:
                import os

                os.environ.setdefault("HF_TOKEN", self._hf_token)
            resolved = resolve_weights(
                self.lock, self.model_path
            )  # every file checksum-verified BEFORE deserialisation
            cfg = OmegaConf.load(resolved.config)
            OmegaConf.resolve(cfg)
            validate_config_classes(cfg)

            def pinned_download(repo_id: str | None = None, filename: str | None = None, **_: Any) -> str:
                p = resolved.aux.get((str(repo_id), str(filename)))
                if p is None:
                    raise ModelError(
                        f"TripoSR tried to download an unpinned file ({repo_id}/{filename}); refused.",
                        recommended_action="Add it to engines/locks/triposr.json (revision + SHA-256) through a reviewed change.",
                    )
                return str(p)

            with mock.patch.object(tokenizer_module, "hf_hub_download", pinned_download):
                model = TSR(cfg)
            # weights_only=True: tensors only, no arbitrary pickle execution. No fallback to the unsafe mode on failure.
            state = torch.load(resolved.checkpoint, map_location="cpu", weights_only=True)
            model.load_state_dict(state)
            model.to(device)
        except ModelError:
            self.unload()
            raise
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
                recommended_action="Check the pinned files and the 'tsr' checkout (docs/models/triposr-security-review.md). Unsafe loading is never used as a fallback.",
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
            details={
                "mc_resolution": s["mc_resolution"],
                "coordinate_frame": "TripoSR native (unrotated)",
                "orientation_hint": ORIENTATION_HINT,
                "extents": [float(x) for x in mesh.extents],
                "weights_source": self.lock.weights.repo_id + "@" + str(self.lock.weights.revision),
            },
        )
