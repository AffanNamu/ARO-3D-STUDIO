"""Angle-based normal generation (hard edges stay hard, curved surfaces stay smooth)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from aro_studio.core.tm import vertex_colors


@dataclass
class ShadedMesh:
    positions: np.ndarray  # (N,3) float32
    normals: np.ndarray  # (N,3) float32
    indices: np.ndarray  # (F,3) uint32
    uv: np.ndarray | None  # (N,2) float32
    colors: np.ndarray | None  # (N,4) uint8
    source_vertex: np.ndarray  # (N,) index into the original vertex array


def shade_split(mesh: trimesh.Trimesh, angle_deg: float = 35.0) -> ShadedMesh:
    faces = np.asarray(mesh.faces, dtype=np.int64)
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    nf = len(faces)
    tri = verts[faces]
    fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area2 = np.linalg.norm(fn, axis=1)
    unit = fn / np.where(area2 == 0, 1.0, area2)[:, None]
    # connect face-corners across smooth edges
    corner_count = nf * 3
    rows: list[np.ndarray] = []
    cols: list[np.ndarray] = []
    adj = np.asarray(mesh.face_adjacency) if len(faces) > 1 else np.zeros((0, 2), dtype=np.int64)
    if len(adj):
        edges = np.asarray(mesh.face_adjacency_edges)
        angles = np.asarray(mesh.face_adjacency_angles)
        smooth = angles <= np.radians(angle_deg)
        fa, fb, ed = adj[smooth, 0], adj[smooth, 1], edges[smooth]
        for k in (0, 1):
            v = ed[:, k]
            ca = fa * 3 + np.argmax(faces[fa] == v[:, None], axis=1)
            cb = fb * 3 + np.argmax(faces[fb] == v[:, None], axis=1)
            rows.append(ca)
            cols.append(cb)
    r = np.concatenate(rows) if rows else np.zeros(0, dtype=np.int64)
    c = np.concatenate(cols) if cols else np.zeros(0, dtype=np.int64)
    g = coo_matrix((np.ones(len(r), dtype=np.int8), (r, c)), shape=(corner_count, corner_count))
    n_comp, labels = connected_components(g, directed=False)
    # area-weighted normal per component
    corner_face = np.repeat(np.arange(nf), 3)
    acc = np.zeros((n_comp, 3))
    np.add.at(acc, labels, fn[corner_face])  # fn is area-weighted already
    ln = np.linalg.norm(acc, axis=1)
    acc = acc / np.where(ln == 0, 1.0, ln)[:, None]
    acc[ln == 0] = (0.0, 1.0, 0.0)
    corner_vertex = faces.reshape(-1)
    rep = np.zeros(n_comp, dtype=np.int64)
    rep[labels] = corner_vertex  # any corner of the component (all share the original vertex)
    uv = getattr(mesh.visual, "uv", None)
    colors = None
    vc = vertex_colors(mesh)
    if vc is not None:
        colors = vc[rep]
        if colors.shape[1] == 3:
            colors = np.concatenate([colors, np.full((len(colors), 1), 255, np.uint8)], axis=1)
    del unit
    return ShadedMesh(
        positions=verts[rep].astype(np.float32),
        normals=acc.astype(np.float32),
        indices=labels.reshape(-1, 3).astype(np.uint32),
        uv=np.asarray(uv, dtype=np.float32)[rep] if uv is not None and len(uv) == len(verts) else None,
        colors=colors,
        source_vertex=rep,
    )
