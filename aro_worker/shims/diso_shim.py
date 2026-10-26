"""CPU stand-in for ``diso.DiffDMC`` (differentiable dual marching cubes), so TripoSG runs without compiling a CUDA extension.

Why: ``diso`` builds CUDA code at install time, which needs an ``nvcc`` matching PyTorch. Free notebook runtimes often have none, and the
mismatch is the most common reason the first install fails. TripoSG only needs the plain iso-surface of its SDF grid, so skimage's marching
cubes is an adequate fallback. Differences from the real package: slower (seconds to a minute at 512^3), output is a standard
marching-cubes mesh (more, thinner triangles than dual marching cubes), and no differentiability (not needed for inference).

The caller (``triposg.inference_utils.flash_extract_geometry``) does ``vertices, faces = dmc(sdf, deform=None, return_quads=False,
normalize=False)`` and then flips the face order itself: this shim therefore returns faces that are OUTWARD-wound after that flip.
NaN voxels (regions the octree never evaluated) are outside the surface by construction and are treated as such.
"""

from __future__ import annotations

from typing import Any

import numpy as np


class _Out:
    """Minimal tensor-like wrapper used when torch is not importable (tests); with torch the real tensors are returned."""

    def __init__(self, a: np.ndarray) -> None:
        self._a = a

    def detach(self) -> _Out:
        return self

    def cpu(self) -> _Out:
        return self

    def numpy(self) -> np.ndarray:
        return self._a


def _to_numpy(x: Any) -> np.ndarray:
    if hasattr(x, "detach"):
        x = x.detach().cpu().numpy()
    return np.asarray(x)


def _wrap(a: np.ndarray) -> Any:
    try:
        import torch

        return torch.from_numpy(np.ascontiguousarray(a))
    except Exception:  # noqa: BLE001 - torch is absent in the unit tests
        return _Out(a)


def _signed_volume(v: np.ndarray, f: np.ndarray) -> float:
    t = v[f]
    return float(np.einsum("ij,ij->", t[:, 0], np.cross(t[:, 1], t[:, 2])) / 6.0)


class DiffDMC:
    def __init__(self, dtype: Any = None, **_: Any) -> None:
        self.dtype = dtype

    def to(self, *_: Any, **__: Any) -> DiffDMC:
        return self

    def __call__(
        self, sdf: Any, deform: Any = None, return_quads: bool = False, normalize: bool = False
    ) -> tuple[Any, Any]:
        from skimage import measure

        vol = np.nan_to_num(_to_numpy(sdf).astype(np.float32), nan=1.0, posinf=1.0, neginf=-1.0)
        if not (float(np.min(vol)) < 0.0 < float(np.max(vol))):
            raise ValueError(
                "the SDF grid has no zero crossing: nothing to extract (the shape latents may be degenerate)"
            )
        verts, faces, _normals, _values = measure.marching_cubes(vol, level=0.0)
        verts = verts.astype(np.float32)
        faces = faces.astype(np.int64)
        if _signed_volume(verts, faces) < 0:  # make 'outward' explicit instead of trusting a library convention
            faces = faces[:, ::-1]
        # the caller flips the order once more, so hand it the inward-wound version
        faces = np.ascontiguousarray(faces[:, ::-1])
        if normalize:
            verts = verts / (np.array(vol.shape, dtype=np.float32) - 1.0) * 2.0 - 1.0
        return _wrap(verts), _wrap(faces)
