"""Mesh processing operations (spec §13).

Every operation is pure: it returns a NEW mesh plus an ``OpReport`` and never mutates its input.
Callers persist results as a new asset version, so the source is always recoverable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import fast_simplification
import numpy as np
import trimesh
from scipy.spatial import cKDTree

from aro_studio.core.errors import InvalidInputError
from aro_studio.geometry.inspect import boundary_loops


@dataclass
class OpReport:
    op: str
    faces_before: int
    faces_after: int
    vertices_before: int
    vertices_after: int
    changed: bool
    details: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _report(op: str, before: trimesh.Trimesh, after: trimesh.Trimesh, **details: Any) -> OpReport:
    warnings = details.pop("warnings", [])
    changed = (len(before.faces), len(before.vertices)) != (len(after.faces), len(after.vertices)) or not np.array_equal(
        np.asarray(before.vertices), np.asarray(after.vertices)
    )
    return OpReport(op, len(before.faces), len(after.faces), len(before.vertices), len(after.vertices), bool(changed), details, warnings)


def _copy_attrs_nearest(src: trimesh.Trimesh, dst: trimesh.Trimesh) -> list[str]:
    """Transfer UVs / vertex colours from ``src`` to ``dst`` by nearest source vertex."""
    notes: list[str] = []
    if len(src.vertices) == 0 or len(dst.vertices) == 0:
        return notes
    tree = cKDTree(src.vertices)
    _, idx = tree.query(dst.vertices)
    uv = getattr(src.visual, "uv", None)
    if uv is not None and len(uv) == len(src.vertices):
        dst.visual = trimesh.visual.TextureVisuals(uv=np.asarray(uv)[idx])
        notes.append("uv")
    elif src.visual.kind == "vertex":
        dst.visual = trimesh.visual.ColorVisuals(mesh=dst, vertex_colors=np.asarray(src.visual.vertex_colors)[idx])
        notes.append("vertex_colors")
    return notes


def _clone(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    return mesh.copy()


# -- cleanup ----------------------------------------------------------------------------------
def remove_invalid(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, OpReport]:
    """Drop vertices with NaN/Inf coordinates and the faces that use them."""
    v = np.asarray(mesh.vertices)
    ok = np.isfinite(v).all(axis=1)
    if ok.all():
        return _clone(mesh), _report("remove_invalid", mesh, mesh, removed_vertices=0)
    keep_faces = ok[mesh.faces].all(axis=1)
    out = mesh.copy()
    out.update_faces(keep_faces)
    out.remove_unreferenced_vertices()
    return out, _report("remove_invalid", mesh, out, removed_vertices=int((~ok).sum()))


def merge_vertices(mesh: trimesh.Trimesh, tolerance: float | None = None) -> tuple[trimesh.Trimesh, OpReport]:
    out = mesh.copy()
    digits = None
    if tolerance:
        digits = max(0, int(-np.floor(np.log10(tolerance))))
    out.merge_vertices(digits_vertex=digits) if digits is not None else out.merge_vertices()
    return out, _report("merge_vertices", mesh, out, merged=len(mesh.vertices) - len(out.vertices))


def remove_degenerate(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, OpReport]:
    out = mesh.copy()
    keep = out.nondegenerate_faces()
    removed = int((~keep).sum())
    if removed:
        out.update_faces(keep)
        out.remove_unreferenced_vertices()
    return out, _report("remove_degenerate", mesh, out, removed_faces=removed)


def remove_duplicate_faces(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, OpReport]:
    out = mesh.copy()
    keep = out.unique_faces()
    removed = int((~keep).sum()) if keep.dtype == bool else len(out.faces) - len(keep)
    out.update_faces(keep)
    out.remove_unreferenced_vertices()
    return out, _report("remove_duplicate_faces", mesh, out, removed_faces=removed)


def remove_small_components(
    mesh: trimesh.Trimesh, min_face_ratio: float = 0.01, keep_at_least: int = 1
) -> tuple[trimesh.Trimesh, OpReport]:
    """Remove floating fragments smaller than ``min_face_ratio`` of the largest component.

    Never removes everything: the largest ``keep_at_least`` components always survive.
    """
    if not 0 <= min_face_ratio < 1:
        raise InvalidInputError("min_face_ratio must be in [0, 1).")
    comps = trimesh.graph.connected_components(mesh.face_adjacency, nodes=np.arange(len(mesh.faces)), min_len=1)
    if len(comps) <= 1:
        return _clone(mesh), _report("remove_small_components", mesh, mesh, removed_components=0, total_components=len(comps))
    sizes = np.array([len(c) for c in comps])
    order = np.argsort(-sizes)
    keep_idx = set(order[:keep_at_least].tolist()) | {i for i, s in enumerate(sizes) if s >= min_face_ratio * sizes.max()}
    keep_faces = np.zeros(len(mesh.faces), dtype=bool)
    for i in keep_idx:
        keep_faces[comps[i]] = True
    out = mesh.copy()
    out.update_faces(keep_faces)
    out.remove_unreferenced_vertices()
    return out, _report(
        "remove_small_components", mesh, out,
        removed_components=len(comps) - len(keep_idx), total_components=len(comps),
        removed_faces=int((~keep_faces).sum()),
    )


# -- normals / repair -------------------------------------------------------------------------
def fix_normals(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, OpReport]:
    """Make winding consistent, orient outward when the mesh is closed, and refresh vertex normals."""
    out = mesh.copy()
    trimesh.repair.fix_winding(out)
    flipped = False
    if out.is_watertight and out.volume < 0:
        out.invert()
        flipped = True
    elif not out.is_watertight:
        trimesh.repair.fix_normals(out, multibody=True)
    out._cache.clear()
    _ = out.vertex_normals  # recompute
    return out, _report("fix_normals", mesh, out, inverted_whole_mesh=flipped, winding_consistent=bool(out.is_winding_consistent))


def fill_holes(mesh: trimesh.Trimesh, max_hole_edges: int = 200) -> tuple[trimesh.Trimesh, OpReport]:
    """Close boundary loops of at most ``max_hole_edges`` edges with a centroid fan.

    Large openings (windows, cavities, intentionally open shells) are left alone and reported.
    """
    out = mesh.copy()
    out.merge_vertices()
    loops = boundary_loops(out)
    verts = np.asarray(out.vertices)
    new_v: list[np.ndarray] = []
    new_f: list[list[int]] = []
    filled = skipped = 0
    for loop in loops:
        if len(loop) > max_hole_edges:
            skipped += 1
            continue
        c = verts[loop].mean(axis=0)
        ci = len(verts) + len(new_v)
        new_v.append(c)
        n = len(loop)
        for i in range(n):
            a, b = loop[i], loop[(i + 1) % n]
            # boundary edge a→b belongs to an existing face; the cap must traverse b→a
            new_f.append([ci, b, a])
        filled += 1
    if new_v:
        out = trimesh.Trimesh(
            vertices=np.vstack([verts, np.array(new_v)]), faces=np.vstack([np.asarray(out.faces), np.array(new_f)]), process=False
        )
        trimesh.repair.fix_winding(out)
    warn = [f"{skipped} large opening(s) were left open (> {max_hole_edges} edges)."] if skipped else []
    return out, _report("fill_holes", mesh, out, holes_filled=filled, holes_skipped=skipped, warnings=warn)


# -- smoothing / optimisation -----------------------------------------------------------------
def smooth(mesh: trimesh.Trimesh, iterations: int = 5, lamb: float = 0.5, nu: float = 0.53) -> tuple[trimesh.Trimesh, OpReport]:
    """Taubin smoothing (low-pass without the shrinkage of plain Laplacian smoothing)."""
    if not 1 <= iterations <= 100:
        raise InvalidInputError("iterations must be 1-100.")
    out = mesh.copy()
    trimesh.smoothing.filter_taubin(out, lamb=lamb, nu=nu, iterations=iterations)
    shift = float(np.linalg.norm(np.asarray(out.vertices) - np.asarray(mesh.vertices), axis=1).max())
    return out, _report("smooth", mesh, out, iterations=iterations, max_vertex_shift=shift)


def decimate(
    mesh: trimesh.Trimesh, *, target_faces: int | None = None, ratio: float | None = None, aggressiveness: int = 7
) -> tuple[trimesh.Trimesh, OpReport]:
    """Quadric-error decimation to ``target_faces`` (or ``ratio`` of the current count)."""
    n = len(mesh.faces)
    if target_faces is None and ratio is None:
        raise InvalidInputError("Provide target_faces or ratio.")
    if target_faces is None:
        if not 0 < ratio <= 1:  # type: ignore[operator]
            raise InvalidInputError("ratio must be in (0, 1].")
        target_faces = int(n * ratio)  # type: ignore[operator]
    target_faces = max(4, int(target_faces))
    if target_faces >= n:
        return _clone(mesh), _report("decimate", mesh, mesh, target_faces=target_faces, note="already below target")
    reduction = 1.0 - target_faces / n
    pts, faces = fast_simplification.simplify(
        np.asarray(mesh.vertices, dtype=np.float64), np.asarray(mesh.faces, dtype=np.int64),
        target_reduction=reduction, agg=aggressiveness,
    )
    out = trimesh.Trimesh(pts, faces, process=False)
    transferred = _copy_attrs_nearest(mesh, out)
    warnings = []
    if "uv" in transferred:
        warnings.append("UVs were transferred by nearest vertex; check texture seams on the decimated mesh.")
    return out, _report("decimate", mesh, out, target_faces=target_faces, achieved_ratio=len(out.faces) / n, attributes_transferred=transferred, warnings=warnings)


# -- transforms -------------------------------------------------------------------------------
AXES = {"+X": (1, 0, 0), "-X": (-1, 0, 0), "+Y": (0, 1, 0), "-Y": (0, -1, 0), "+Z": (0, 0, 1), "-Z": (0, 0, -1)}


def rotation_to_canonical(up: str, forward: str) -> np.ndarray:
    """4x4 rotation taking a mesh whose up/forward axes are ``up``/``forward`` to +Y up, +Z forward.

    The mapping is proper (determinant +1) so it never mirrors the mesh.
    """
    if up not in AXES or forward not in AXES:
        raise InvalidInputError("up/forward must be one of +X,-X,+Y,-Y,+Z,-Z.")
    u, f = np.array(AXES[up], float), np.array(AXES[forward], float)
    if abs(float(u @ f)) > 1e-9:
        raise InvalidInputError("up and forward must be perpendicular axes.")
    right = np.cross(u, f)  # canonical +X (right-handed: X = Y × Z)
    src = np.stack([right, u, f])  # rows are source directions of canonical X, Y, Z
    m = np.eye(4)
    m[:3, :3] = src  # maps source-frame coordinates onto canonical axes
    return m


def apply_matrix(mesh: trimesh.Trimesh, matrix: np.ndarray, op: str = "transform", **details: Any) -> tuple[trimesh.Trimesh, OpReport]:
    out = mesh.copy()
    out.apply_transform(matrix)
    if np.linalg.det(matrix[:3, :3]) < 0:
        out.invert()  # keep winding outward after a mirror
    return out, _report(op, mesh, out, matrix=np.asarray(matrix).round(9).tolist(), **details)


def orient(mesh: trimesh.Trimesh, up: str, forward: str) -> tuple[trimesh.Trimesh, OpReport]:
    return apply_matrix(mesh, rotation_to_canonical(up, forward), "orient", up=up, forward=forward)


def scale_to_length(mesh: trimesh.Trimesh, length_m: float, axis: str = "Z") -> tuple[trimesh.Trimesh, OpReport]:
    if length_m <= 0:
        raise InvalidInputError("Target length must be positive.")
    ai = "XYZ".index(axis.upper())
    cur = float(mesh.extents[ai])
    if cur <= 0:
        raise InvalidInputError("Mesh has zero extent along the chosen axis.")
    s = length_m / cur
    m = np.eye(4)
    m[:3, :3] *= s
    return apply_matrix(mesh, m, "scale", factor=s, axis=axis.upper(), target_length_m=length_m)


def uniform_scale(mesh: trimesh.Trimesh, factor: float) -> tuple[trimesh.Trimesh, OpReport]:
    if factor <= 0:
        raise InvalidInputError("Scale factor must be positive.")
    m = np.eye(4)
    m[:3, :3] *= factor
    return apply_matrix(mesh, m, "scale", factor=factor)


def pivot_translation(bounds: np.ndarray, mode: str, custom: tuple[float, float, float] | None = None) -> np.ndarray:
    """Translation that moves the chosen pivot to the origin."""
    lo, hi = bounds
    if mode == "ground_center":
        p = np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
    elif mode == "bounds_center":
        p = (lo + hi) / 2
    elif mode == "origin":
        p = np.zeros(3)
    elif mode == "custom" and custom is not None:
        p = np.asarray(custom, float)
    else:
        raise InvalidInputError("pivot mode must be ground_center, bounds_center, origin or custom (with a point).")
    return -p


def set_pivot(mesh: trimesh.Trimesh, mode: str = "ground_center", custom: tuple[float, float, float] | None = None) -> tuple[trimesh.Trimesh, OpReport]:
    t = pivot_translation(mesh.bounds, mode, custom)
    m = np.eye(4)
    m[:3, 3] = t
    return apply_matrix(mesh, m, "set_pivot", mode=mode, translation=t.round(9).tolist())


# -- orientation suggestion -------------------------------------------------------------------
def suggest_orientation(mesh: trimesh.Trimesh) -> dict:
    """ADVISORY: guess (up, forward) from geometry. Always confirm in the viewer before applying.

    Heuristic: the longest extent is "forward". Of the remaining axes, "up" is the one whose two ends
    differ most in vertex density (the flat underside/ground contact has many vertices near one end).
    The sign of "forward" cannot be determined from shape alone and defaults to +.
    """
    ext = np.asarray(mesh.extents)
    fwd = int(np.argmax(ext))
    others = [i for i in range(3) if i != fwd]
    v = np.asarray(mesh.vertices)
    best, best_score, best_sign = others[0], -1.0, 1
    for ax in others:
        lo, hi = v[:, ax].min(), v[:, ax].max()
        span = hi - lo
        if span <= 0:
            continue
        near_lo = float((v[:, ax] < lo + 0.05 * span).mean())
        near_hi = float((v[:, ax] > hi - 0.05 * span).mean())
        score = abs(near_lo - near_hi)
        if score > best_score:
            best, best_score, best_sign = ax, score, (1 if near_lo >= near_hi else -1)
    # flat underside at the low end → +axis is up
    names = "XYZ"
    up = ("+" if best_sign == 1 else "-") + names[best]
    forward = "+" + names[fwd]
    # forward and up must be perpendicular: they are by construction (different axes)
    return {"up": up, "forward": forward, "confidence": "low" if best_score < 0.05 else "medium", "advisory": True}
