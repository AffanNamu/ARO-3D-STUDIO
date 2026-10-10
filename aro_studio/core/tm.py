"""Typed accessors for trimesh's loosely-typed visual API (keeps the rest of the code strictly typed)."""

from __future__ import annotations

import numpy as np
import trimesh


def has_vertex_colors(mesh: trimesh.Trimesh) -> bool:
    return mesh.visual is not None and mesh.visual.kind == "vertex"


def vertex_colors(mesh: trimesh.Trimesh) -> np.ndarray | None:
    """(N,4) uint8 vertex colours or None."""
    if not has_vertex_colors(mesh):
        return None
    return np.asarray(mesh.visual.vertex_colors, dtype=np.uint8)  # type: ignore[union-attr]


def uv_coords(mesh: trimesh.Trimesh) -> np.ndarray | None:
    """(N,2) float UVs or None."""
    uv = getattr(mesh.visual, "uv", None)
    if uv is None or len(uv) != len(mesh.vertices):
        return None
    return np.asarray(uv, dtype=np.float64)


def as_mesh(obj: object) -> trimesh.Trimesh:
    if not isinstance(obj, trimesh.Trimesh):
        raise TypeError(f"expected Trimesh, got {type(obj).__name__}")
    return obj
