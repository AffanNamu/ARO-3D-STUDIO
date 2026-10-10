"""Time-budgeted self-intersection detection.

Broad phase: R-tree over triangle AABBs. Narrow phase: vectorised edge-vs-triangle tests in both
directions (Möller–Trumbore, segment form). Triangles sharing a vertex are skipped (they touch by
construction). Known limitation: exactly coplanar overlapping triangles are not reported.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass

import numpy as np
import trimesh
from rtree import index as rindex


@dataclass
class SelfIntersectionResult:
    status: str  # checked | partial | skipped
    intersecting_pairs: int
    faces_checked: int
    faces_total: int
    seconds: float
    note: str = ""
    sample_pairs: list[tuple[int, int]] | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _segments_hit_triangles(p0: np.ndarray, p1: np.ndarray, tri: np.ndarray, eps: float = 1e-9) -> np.ndarray:
    """Vectorised: does segment p0→p1 pierce triangle ``tri`` (N,3,3)? Returns bool (N,)."""
    d = p1 - p0
    e1 = tri[:, 1] - tri[:, 0]
    e2 = tri[:, 2] - tri[:, 0]
    h = np.cross(d, e2)
    a = np.einsum("ij,ij->i", e1, h)
    ok = np.abs(a) > eps
    f = np.zeros_like(a)
    f[ok] = 1.0 / a[ok]
    s = p0 - tri[:, 0]
    u = f * np.einsum("ij,ij->i", s, h)
    q = np.cross(s, e1)
    v = f * np.einsum("ij,ij->i", d, q)
    t = f * np.einsum("ij,ij->i", e2, q)
    # strict interior (with a tiny tolerance) so shared-edge touching is not flagged
    tol = 1e-7
    return ok & (u > tol) & (v > tol) & (u + v < 1 - tol) & (t > tol) & (t < 1 - tol)


def find_self_intersections(
    mesh: trimesh.Trimesh, *, time_budget_s: float = 20.0, max_faces: int = 600_000, sample: int = 20
) -> SelfIntersectionResult:
    t0 = time.perf_counter()
    n = len(mesh.faces)
    if n == 0:
        return SelfIntersectionResult("checked", 0, 0, 0, 0.0)
    if n > max_faces:
        return SelfIntersectionResult(
            "skipped", 0, 0, n, 0.0, f"Mesh has {n} faces (> {max_faces}); decimate first to test intersections."
        )
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    tris = verts[faces]
    lo, hi = tris.min(axis=1), tris.max(axis=1)
    pad = max(1e-9, float(np.linalg.norm(mesh.extents)) * 1e-9)

    def gen():
        for i in range(n):
            yield i, (*(lo[i] - pad), *(hi[i] + pad)), None

    idx = rindex.Index(gen(), properties=_props())
    pairs: list[tuple[int, int]] = []
    checked = 0
    partial = False
    batch_a: list[int] = []
    batch_b: list[int] = []
    hits: list[tuple[int, int]] = []

    def flush():
        if not batch_a:
            return
        a = np.asarray(batch_a)
        b = np.asarray(batch_b)
        ta, tb = tris[a], tris[b]
        hit = np.zeros(len(a), dtype=bool)
        for k in range(3):
            hit |= _segments_hit_triangles(ta[:, k], ta[:, (k + 1) % 3], tb)
            hit |= _segments_hit_triangles(tb[:, k], tb[:, (k + 1) % 3], ta)
        hits.extend(zip(a[hit].tolist(), b[hit].tolist(), strict=True))
        batch_a.clear()
        batch_b.clear()

    for i in range(n):
        if (i & 0x3FF) == 0 and time.perf_counter() - t0 > time_budget_s:
            partial = True
            break
        checked = i + 1
        fi = faces[i]
        for j in idx.intersection((*(lo[i] - pad), *(hi[i] + pad))):
            if j <= i:
                continue
            fj = faces[j]
            if fi[0] in fj or fi[1] in fj or fi[2] in fj:
                continue
            batch_a.append(i)
            batch_b.append(j)
        if len(batch_a) > 200_000:
            flush()
    flush()
    pairs = hits
    return SelfIntersectionResult(
        "partial" if partial else "checked",
        len(pairs),
        checked,
        n,
        time.perf_counter() - t0,
        "Time budget reached before all faces were tested." if partial else "Coplanar overlaps are not detected.",
        pairs[:sample] or None,
    )


def _props() -> rindex.Property:
    p = rindex.Property()
    p.dimension = 3
    return p
