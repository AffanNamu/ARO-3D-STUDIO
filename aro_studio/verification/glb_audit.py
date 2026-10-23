"""Per-node audit of an exported GLB: every visual LOD and every collision mesh is opened again and measured.

``verify_glb`` (export/verify.py) checks the container; this checks what is *inside* each node, from the bytes on disk.
A check is only reported as passed when it was evaluated. Nothing here changes the file.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

MAX_CONVEX_TRIANGLES = 255  # PhysX / Unity limit for a convex mesh collider
LOD_BOUNDS_TOLERANCE = 0.03  # a LOD may shrink/grow by at most 3 % of the LOD0 diagonal
COLLIDER_BOUNDS_TOLERANCE = 0.05
_LOD = re.compile(r"_LOD(\d+)$")


def _welded(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Positions and faces only, vertices merged by position: duplicated vertices (normal/UV seams) must not read as holes."""
    m = trimesh.Trimesh(np.asarray(mesh.vertices), np.asarray(mesh.faces), process=False)
    m.merge_vertices()
    return m


def _non_manifold_edges(topo: trimesh.Trimesh) -> int:
    if not len(topo.faces):
        return 0
    f = np.asarray(topo.faces)
    e = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
    _, counts = np.unique(e, axis=0, return_counts=True)
    return int((counts > 2).sum())


def _stats(name: str, mesh: trimesh.Trimesh) -> dict[str, Any]:
    topo = _welded(mesh)
    v = np.asarray(mesh.vertices, dtype=float)
    f = np.asarray(mesh.faces)
    area = mesh.area_faces if len(f) else np.zeros(0)
    uv = getattr(mesh.visual, "uv", None)
    normals = mesh.vertex_normals if len(v) else np.zeros((0, 3))
    nlen = np.linalg.norm(normals, axis=1) if len(normals) else np.zeros(0)
    return {
        "name": name,
        "vertices": int(len(v)),
        "triangles": int(len(f)),
        "finite": bool(np.isfinite(v).all()),
        "indices_in_range": bool(len(f) == 0 or (f.min() >= 0 and f.max() < len(v))),
        "degenerate_triangles": int((area < 1e-14).sum()),
        "welded_vertices": int(len(topo.vertices)),
        "non_manifold_edges": _non_manifold_edges(topo),
        "watertight": bool(topo.is_watertight),
        "convex": bool(topo.is_convex) if len(f) else False,
        "extents_m": [round(float(x), 4) for x in mesh.extents],
        "bounds_m": [[round(float(x), 4) for x in b] for b in mesh.bounds],
        "uv_present": uv is not None,
        "uv_in_0_1": None if uv is None else bool(np.isfinite(uv).all() and uv.min() >= -1e-6 and uv.max() <= 1 + 1e-6),
        "normals_unit_length": bool(len(nlen) == 0 or np.allclose(nlen, 1.0, atol=1e-3)),
    }


def audit_glb(path: Path) -> dict[str, Any]:
    """Return ``{"ok", "nodes", "checks"}``; every check is ``{"id", "ok", "message"}``."""
    scene: Any = trimesh.load(str(path), force="scene")
    meshes: dict[str, trimesh.Trimesh] = {}
    for node in scene.graph.nodes_geometry:
        transform, geom_name = scene.graph[node]
        m = scene.geometry[geom_name].copy()
        m.apply_transform(transform)
        meshes[node] = m
    nodes = [_stats(n, m) for n, m in meshes.items()]
    checks: list[dict[str, Any]] = []

    def add(cid: str, ok: bool, message: str) -> None:
        checks.append({"id": cid, "ok": bool(ok), "message": message})

    lods: list[tuple[int, dict[str, Any]]] = []
    for s in nodes:
        hit = _LOD.search(s["name"])
        if hit:
            lods.append((int(hit.group(1)), s))
    lods.sort(key=lambda t: t[0])
    colliders = [s for s in nodes if s["name"].startswith("COL_")]
    add("nodes.visual_lods", len(lods) >= 1, f"{len(lods)} visual LOD node(s): {[s['name'] for _, s in lods]}")
    add("nodes.colliders", len(colliders) >= 1, f"{len(colliders)} collision node(s): {[s['name'] for s in colliders]}")
    for s in nodes:
        n = s["name"]
        add(f"{n}.finite", s["finite"] and s["indices_in_range"], f"{n}: all vertices finite, all indices in range")
        add(f"{n}.not_empty", s["triangles"] > 0, f"{n}: {s['triangles']} triangles")
        add(
            f"{n}.degenerate",
            s["degenerate_triangles"] == 0,
            f"{n}: {s['degenerate_triangles']} degenerate triangle(s)",
        )
        add(f"{n}.normals", s["normals_unit_length"], f"{n}: vertex normals are unit length")
        add(
            f"{n}.manifold",
            s["non_manifold_edges"] == 0,
            f"{n}: {s['non_manifold_edges']} non-manifold edge(s) (edges shared by 3+ triangles, after welding)",
        )
    for _, s in lods:
        n = s["name"]
        add(f"{n}.uv", bool(s["uv_present"] and s["uv_in_0_1"]), f"{n}: UV coordinates present and inside 0..1")
    tris = [s["triangles"] for _, s in lods]
    add(
        "lods.ladder",
        all(a > b for a, b in zip(tris, tris[1:], strict=False)),
        f"LOD triangle counts strictly decrease: {tris}",
    )
    if lods:
        base = np.asarray(lods[0][1]["bounds_m"], dtype=float)
        diag = float(np.linalg.norm(base[1] - base[0])) or 1.0
        for _, s in lods[1:]:
            b = np.asarray(s["bounds_m"], dtype=float)
            dev = float(np.abs(b - base).max()) / diag
            add(
                f"{s['name']}.bounds",
                dev <= LOD_BOUNDS_TOLERANCE,
                f"{s['name']}: bounds differ from LOD0 by {100 * dev:.2f} % of the diagonal (limit {100 * LOD_BOUNDS_TOLERANCE:.0f} %)",
            )
        for c in colliders:
            cb = np.asarray(c["bounds_m"], dtype=float)
            dev = float(np.abs(cb - base).max()) / diag
            add(
                f"{c['name']}.bounds",
                dev <= COLLIDER_BOUNDS_TOLERANCE,
                f"{c['name']}: bounds differ from LOD0 by {100 * dev:.2f} % of the diagonal (limit {100 * COLLIDER_BOUNDS_TOLERANCE:.0f} %)",
            )
    for c in colliders:
        add(f"{c['name']}.convex", c["convex"], f"{c['name']}: collision mesh is convex")
        add(f"{c['name']}.watertight", c["watertight"], f"{c['name']}: collision mesh is closed (after welding seams)")
        add(
            f"{c['name']}.triangle_limit",
            0 < c["triangles"] <= MAX_CONVEX_TRIANGLES,
            f"{c['name']}: {c['triangles']} triangles (convex-collider limit {MAX_CONVEX_TRIANGLES})",
        )
    return {"ok": all(c["ok"] for c in checks), "nodes": nodes, "checks": checks}
