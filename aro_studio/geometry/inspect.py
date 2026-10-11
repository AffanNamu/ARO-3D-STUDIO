"""Mesh inspection (spec §13). Detection only - nothing here modifies geometry."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import trimesh

from aro_studio.core.enums import Severity
from aro_studio.geometry.selfintersect import SelfIntersectionResult, find_self_intersections

VEHICLE_LENGTH_RANGE_M = (2.0, 25.0)


@dataclass
class Issue:
    id: str
    severity: str
    count: int
    message: str
    fix: str | None = None  # name of the processing operation that can address it


@dataclass
class MeshReport:
    vertex_count: int
    face_count: int
    extents: tuple[float, float, float]
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]
    duplicate_vertices: int
    degenerate_faces: int
    duplicate_faces: int
    component_count: int
    small_component_count: int
    largest_component_faces: int
    nonmanifold_edges: int
    boundary_edges: int
    hole_count: int
    is_watertight: bool
    is_winding_consistent: bool
    inverted: bool
    invalid_normals: int
    nan_vertices: int
    volume: float | None
    self_intersections: dict
    scale_assessment: dict
    orientation_assessment: dict
    pivot_assessment: dict
    issues: list[Issue] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def issue(self, issue_id: str) -> Issue | None:
        return next((i for i in self.issues if i.id == issue_id), None)


def _v3(v) -> tuple[float, float, float]:
    a = [float(x) for x in v]
    return (a[0], a[1], a[2])


def boundary_loops(mesh: trimesh.Trimesh) -> list[list[int]]:
    """Ordered vertex loops of boundary edges (edges used by exactly one face)."""
    faces = np.asarray(mesh.faces)
    if len(faces) == 0:
        return []
    directed = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    undirected = np.sort(directed, axis=1)
    _, inv, counts = np.unique(undirected, axis=0, return_inverse=True, return_counts=True)
    boundary = directed[counts[inv.ravel()] == 1]
    if len(boundary) == 0:
        return []
    nxt: dict[int, list[int]] = {}
    for a, b in boundary:
        nxt.setdefault(int(a), []).append(int(b))
    loops: list[list[int]] = []
    seen_edges: set[tuple[int, int]] = set()
    for a, b in boundary:
        a, b = int(a), int(b)
        if (a, b) in seen_edges:
            continue
        loop = [a]
        cur, prev = b, a
        seen_edges.add((a, b))
        ok = True
        while cur != a:
            loop.append(cur)
            outs = [x for x in nxt.get(cur, []) if (cur, x) not in seen_edges]
            if not outs:
                ok = False
                break
            nx_v = outs[0]
            seen_edges.add((cur, nx_v))
            prev, cur = cur, nx_v
            if len(loop) > len(boundary) + 2:
                ok = False
                break
        del prev
        if ok:
            loops.extend(_split_simple(loop))
    return loops


def _split_simple(loop: list[int]) -> list[list[int]]:
    """Split a boundary walk that revisits a vertex ("figure-8" at a pinch point) into simple loops."""
    out: list[list[int]] = []
    stack: list[int] = []
    pos: dict[int, int] = {}
    for v in loop:
        if v in pos:
            i = pos[v]
            sub = stack[i:]
            if len(sub) >= 3:
                out.append(sub)
            for u in stack[i + 1 :]:
                pos.pop(u, None)
            stack = stack[: i + 1]
        else:
            pos[v] = len(stack)
            stack.append(v)
    if len(stack) >= 3:
        out.append(stack)
    return out


def _components(mesh: trimesh.Trimesh) -> list[np.ndarray]:
    if len(mesh.faces) == 0:
        return []
    return trimesh.graph.connected_components(mesh.face_adjacency, nodes=np.arange(len(mesh.faces)), min_len=1)


def inspect_mesh(
    mesh: trimesh.Trimesh,
    *,
    category_group: str | None = None,
    tri_budget: int | None = None,
    check_intersections: bool = True,
    intersection_budget_s: float = 20.0,
    small_component_ratio: float = 0.01,
) -> MeshReport:
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    nan_vertices = int((~np.isfinite(verts)).any(axis=1).sum()) if len(verts) else 0
    if nan_vertices:
        # still report, but avoid propagating NaN into the other metrics
        finite = np.asarray(np.isfinite(verts).all(axis=1), dtype=np.bool_)
        verts = np.where(finite[:, None], verts, 0.0)
        mesh = trimesh.Trimesh(verts, faces, process=False)

    ext = _v3(mesh.extents if len(verts) else (0, 0, 0))
    bmin = _v3(mesh.bounds[0] if len(verts) else (0, 0, 0))
    bmax = _v3(mesh.bounds[1] if len(verts) else (0, 0, 0))

    # duplicate vertices (positionally identical within tolerance)
    tol = max(1e-9, float(np.linalg.norm(ext)) * 1e-8)
    if len(verts):
        keys = np.round(verts / tol).astype(np.int64)
        dup_v = len(verts) - len(np.unique(keys, axis=0))
    else:
        dup_v = 0

    degenerate = int(len(faces) - int(mesh.nondegenerate_faces().sum())) if len(faces) else 0
    dup_faces = len(faces) - len(np.unique(np.sort(faces, axis=1), axis=0)) if len(faces) else 0

    # topology is evaluated on a merged copy so that duplicate vertices don't show up as fake holes
    m2 = trimesh.Trimesh(verts, faces, process=False)
    m2.merge_vertices()
    if len(m2.faces):
        m2.update_faces(m2.nondegenerate_faces())
        m2.update_faces(m2.unique_faces())
    comps = _components(m2)
    largest = max((len(c) for c in comps), default=0)
    small = sum(1 for c in comps if len(c) < max(2, small_component_ratio * largest)) if comps else 0

    f2 = np.asarray(m2.faces)
    if len(f2):
        e = np.sort(np.concatenate([f2[:, [0, 1]], f2[:, [1, 2]], f2[:, [2, 0]]]), axis=1)
        _, counts = np.unique(e, axis=0, return_counts=True)
        nonmanifold = int((counts > 2).sum())
        boundary_edges = int((counts == 1).sum())
    else:
        nonmanifold = boundary_edges = 0
    holes = len(boundary_loops(m2)) if boundary_edges else 0

    watertight = bool(m2.is_watertight) if len(f2) else False
    winding = bool(m2.is_winding_consistent) if len(f2) else False
    volume = float(m2.volume) if watertight else None
    inverted = bool(volume is not None and volume < 0)

    invalid_normals = 0
    if len(f2):
        fn = (
            np.cross(verts[faces[:, 1]] - verts[faces[:, 0]], verts[faces[:, 2]] - verts[faces[:, 0]])
            if len(faces)
            else np.zeros((0, 3))
        )
        ln = np.linalg.norm(fn, axis=1)
        invalid_normals = int((~np.isfinite(ln) | (ln < 1e-14)).sum())

    si = (
        find_self_intersections(m2, time_budget_s=intersection_budget_s)
        if check_intersections and len(f2)
        else SelfIntersectionResult("skipped", 0, 0, len(f2), 0.0, "disabled")
    )

    longest = max(ext) if ext else 0.0
    # scale
    scale: dict = {"longest_extent": longest, "expected_range_m": None, "plausible": None, "note": ""}
    if category_group == "vehicles":
        lo, hi = VEHICLE_LENGTH_RANGE_M
        scale.update(expected_range_m=[lo, hi], plausible=bool(lo <= longest <= hi))
        if not scale["plausible"]:
            scale["note"] = (
                f"Longest extent is {longest:.3f} m; a vehicle is expected to be {lo}-{hi} m long. Rescale in metres."
            )
    # orientation (advisory heuristic)
    axis_names = ["X", "Y", "Z"]
    long_axis = axis_names[int(np.argmax(ext))] if ext and longest > 0 else None
    orient: dict = {
        "longest_axis": long_axis,
        "ok": None,
        "note": "",
    }
    if category_group == "vehicles" and long_axis:
        is_z = long_axis == "Z"
        orient["ok"] = is_z
        if not is_z:
            orient["note"] = f"Longest axis is {long_axis}; vehicles must be built along +Z (forward) with +Y up."
    # pivot
    cx = (bmin[0] + bmax[0]) / 2
    pivot = {
        "offset_from_ground_center": [cx, bmin[1], (bmin[2] + bmax[2]) / 2],
        "ground_aligned": bool(abs(bmin[1]) <= 0.02 * max(ext[1], 1e-9) + 1e-6),
        "centered_x": bool(abs(cx) <= 0.02 * max(ext[0], 1e-9) + 1e-6),
    }

    r = MeshReport(
        vertex_count=len(verts),
        face_count=len(faces),
        extents=ext,
        bounds_min=bmin,
        bounds_max=bmax,
        duplicate_vertices=int(dup_v),
        degenerate_faces=degenerate,
        duplicate_faces=int(dup_faces),
        component_count=len(comps),
        small_component_count=int(small),
        largest_component_faces=int(largest),
        nonmanifold_edges=nonmanifold,
        boundary_edges=boundary_edges,
        hole_count=holes,
        is_watertight=watertight,
        is_winding_consistent=winding,
        inverted=inverted,
        invalid_normals=invalid_normals,
        nan_vertices=nan_vertices,
        volume=volume,
        self_intersections=si.to_dict(),
        scale_assessment=scale,
        orientation_assessment=orient,
        pivot_assessment=pivot,
    )
    _derive_issues(r, tri_budget)
    return r


def _derive_issues(r: MeshReport, tri_budget: int | None) -> None:
    add = r.issues.append
    S = Severity
    if r.vertex_count == 0 or r.face_count == 0:
        add(Issue("empty_mesh", S.CRITICAL, 0, "The mesh has no geometry."))
        return
    if r.nan_vertices:
        add(
            Issue(
                "nan_vertices",
                S.CRITICAL,
                r.nan_vertices,
                f"{r.nan_vertices} vertices have NaN/Inf coordinates.",
                "remove_invalid",
            )
        )
    if r.duplicate_vertices:
        add(
            Issue(
                "duplicate_vertices",
                S.MINOR,
                r.duplicate_vertices,
                f"{r.duplicate_vertices} duplicate vertices (weld them).",
                "merge_vertices",
            )
        )
    if r.degenerate_faces:
        add(
            Issue(
                "degenerate_faces",
                S.MAJOR,
                r.degenerate_faces,
                f"{r.degenerate_faces} zero-area triangles.",
                "remove_degenerate",
            )
        )
    if r.duplicate_faces:
        add(
            Issue(
                "duplicate_faces",
                S.MINOR,
                r.duplicate_faces,
                f"{r.duplicate_faces} duplicated triangles.",
                "remove_duplicate_faces",
            )
        )
    if r.invalid_normals:
        add(
            Issue(
                "invalid_normals",
                S.MAJOR,
                r.invalid_normals,
                f"{r.invalid_normals} triangles have no valid normal.",
                "remove_degenerate",
            )
        )
    if not r.is_winding_consistent:
        add(
            Issue(
                "inconsistent_winding", S.MAJOR, 1, "Triangle winding is inconsistent (flipped faces).", "fix_normals"
            )
        )
    if r.inverted:
        add(Issue("inverted", S.MAJOR, 1, "The mesh is inside-out (negative volume).", "fix_normals"))
    if r.component_count > 1:
        sev = S.MAJOR if r.small_component_count else S.INFO
        add(
            Issue(
                "disconnected_components",
                sev,
                r.component_count,
                f"{r.component_count} disconnected components ({r.small_component_count} tiny).",
                "remove_small_components",
            )
        )
    if r.nonmanifold_edges:
        add(
            Issue(
                "non_manifold",
                S.MAJOR,
                r.nonmanifold_edges,
                f"{r.nonmanifold_edges} non-manifold edges (shared by >2 triangles).",
                None,
            )
        )
    if r.hole_count:
        add(
            Issue(
                "holes",
                S.MAJOR,
                r.hole_count,
                f"{r.hole_count} open boundary loop(s) ({r.boundary_edges} boundary edges).",
                "fill_holes",
            )
        )
    si = r.self_intersections
    if si["intersecting_pairs"]:
        add(
            Issue(
                "self_intersections",
                S.MINOR,
                si["intersecting_pairs"],
                f"{si['intersecting_pairs']} intersecting triangle pairs.",
                None,
            )
        )
    if si["status"] == "skipped" and si.get("note") and si["note"] != "disabled":
        add(Issue("self_intersection_unchecked", S.INFO, 0, si["note"], "decimate"))
    if tri_budget and r.face_count > tri_budget:
        add(
            Issue(
                "excessive_polycount",
                S.MAJOR,
                r.face_count,
                f"{r.face_count} triangles exceed the budget of {tri_budget}.",
                "decimate",
            )
        )
    if r.scale_assessment.get("plausible") is False:
        add(Issue("incorrect_scale", S.MAJOR, 1, r.scale_assessment["note"], "scale"))
    if r.orientation_assessment.get("ok") is False:
        add(Issue("incorrect_orientation", S.MAJOR, 1, r.orientation_assessment["note"], "orient"))
    if not (r.pivot_assessment["ground_aligned"] and r.pivot_assessment["centered_x"]):
        add(Issue("incorrect_pivot", S.MINOR, 1, "Origin is not at ground level on the centreline.", "set_pivot"))
