"""A provider's answer is not a result. The GLB itself must pass before a job can complete (directive section 10).

Checked on the bytes the API downloads from storage, never on what the worker claims: file integrity (the claimed SHA-256 must match),
that it parses as glTF, that it holds real geometry (not an empty or placeholder scene), finite coordinates, sane bounds and a minimum
triangle count. A labelled test double is refused unless the deployment explicitly allows it (tests only).
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import trimesh


@dataclass
class GateResult:
    ok: bool
    reasons: list[str] = field(default_factory=list)  # why it was refused
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    sha256: str = ""


def validate_glb(
    data: bytes,
    *,
    claimed_sha256: str | None,
    max_bytes: int,
    min_triangles: int = 200,
    engine_is_test_double: bool = False,
    allow_test_double: bool = False,
) -> GateResult:
    sha = hashlib.sha256(data).hexdigest()
    res = GateResult(ok=False, sha256=sha)
    if engine_is_test_double and not allow_test_double:
        res.reasons.append("the output comes from a labelled test double, not an AI model")
        return res
    if len(data) > max_bytes:
        res.reasons.append(f"the GLB is {len(data) / 1e6:.1f} MB, above the {max_bytes / 1e6:.0f} MB limit")
        return res
    if data[:4] != b"glTF":
        res.reasons.append("the file is not a binary glTF (GLB)")
        return res
    if claimed_sha256 and claimed_sha256 != sha:
        res.reasons.append("the GLB does not match the checksum the worker reported (corrupt or substituted upload)")
        return res
    try:
        scene: Any = trimesh.load(io.BytesIO(data), file_type="glb", force="scene", process=False)
    except Exception as e:  # noqa: BLE001 - any parser failure means the file is not usable
        res.reasons.append(f"the GLB cannot be parsed ({type(e).__name__})")
        return res
    geoms = [
        g
        for name, g in scene.geometry.items()
        if isinstance(g, trimesh.Trimesh) and not str(name).upper().startswith("COL_")
    ]
    if not geoms:
        res.reasons.append("the GLB contains no mesh geometry")
        return res
    triangles = int(sum(len(g.faces) for g in geoms))
    vertices = int(sum(len(g.vertices) for g in geoms))
    res.stats = {"meshes": len(geoms), "triangles": triangles, "vertices": vertices, "bytes": len(data)}
    if triangles < min_triangles:
        res.reasons.append(f"only {triangles} triangles: too little geometry to be a model")
        return res
    allv = np.concatenate([np.asarray(g.vertices, dtype=np.float64) for g in geoms])
    if not np.isfinite(allv).all():
        res.reasons.append("the geometry contains NaN or infinite coordinates")
        return res
    ext = allv.max(axis=0) - allv.min(axis=0)
    res.stats["extents"] = [round(float(x), 6) for x in ext]
    if float(ext.max()) <= 1e-6:
        res.reasons.append("the geometry has no extent (all points coincide)")
        return res
    if float(ext.max()) > 1e5:
        res.reasons.append("the geometry is implausibly large (more than 100 km)")
        return res
    degenerate = 0
    for g in geoms:
        tri = np.asarray(g.triangles, dtype=np.float64)
        area = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
        degenerate += int((area < 1e-12).sum())
    res.stats["degenerate_triangles"] = degenerate
    if degenerate > 0.5 * triangles:
        res.reasons.append("more than half of the triangles have no area")
        return res
    res.stats["has_uv"] = any(getattr(g.visual, "uv", None) is not None for g in geoms)
    res.stats["materials"] = len({id(getattr(g.visual, "material", None)) for g in geoms})
    if not res.stats["has_uv"]:
        res.warnings.append("the model has no UV coordinates (it carries vertex colours or no colour)")
    res.ok = True
    return res
