"""High-to-low detail transfer: bake a tangent-space NORMAL MAP from a dense mesh onto a game-budget mesh's UV atlas.

The dense mesh (what a strong engine returns: 100k to 1M triangles) holds the panel lines, grille slats and rivets; the game mesh (20-50k
triangles) cannot. For every texel of the low mesh's atlas this finds where that texel sits on the dense surface and stores the dense
surface's normal in the low mesh's tangent space. Under light the low mesh then reads as detailed.

Conventions (glTF, which Unity's glTF importers, Blender and three.js follow): +Z toward the viewer, +X along the texture's U direction,
+Y "up" in the image, bitangent = cross(normal, tangent) (right-handed, no handedness flag), 8-bit values (n * 0.5 + 0.5) * 255. The Studio's
in-memory UVs have V pointing up, as in ``bake.rasterize_uv_positions``.

Approximation: the dense point is the nearest dense VERTEX (inverse-distance blend of the k nearest) rather than an exact ray cast. That
is accurate when the low mesh is a decimation of the dense one, which is how the pipeline builds it, and it needs no ray tracer.
"""

from __future__ import annotations

import io
from typing import Any

import numpy as np
import trimesh
from PIL import Image
from scipy.spatial import cKDTree

from aro_studio.core.errors import InvalidInputError
from aro_studio.textures.bake import dilate


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.where(n < 1e-12, 1.0, n)


def rasterize_faces(mesh: trimesh.Trimesh, size: int) -> tuple[np.ndarray, np.ndarray]:
    """Per texel: the covering face index (-1 = none) and its barycentric weights. V is flipped so row 0 is the top of the image."""
    uv = getattr(mesh.visual, "uv", None)
    if uv is None:
        raise InvalidInputError("Baking needs UVs: unwrap the mesh first.")
    uv = np.asarray(uv, dtype=np.float64)
    px = np.stack([uv[:, 0] * size, (1.0 - uv[:, 1]) * size], axis=1)
    fid = np.full((size, size), -1, dtype=np.int32)
    bary = np.zeros((size, size, 3), dtype=np.float32)
    for i, f in enumerate(np.asarray(mesh.faces)):
        p0, p1, p2 = px[f[0]], px[f[1]], px[f[2]]
        x0, x1 = int(max(0, np.floor(min(p0[0], p1[0], p2[0])))), int(min(size - 1, np.ceil(max(p0[0], p1[0], p2[0]))))
        y0, y1 = int(max(0, np.floor(min(p0[1], p1[1], p2[1])))), int(min(size - 1, np.ceil(max(p0[1], p1[1], p2[1]))))
        if x1 < x0 or y1 < y0:
            continue
        den = (p1[1] - p2[1]) * (p0[0] - p2[0]) + (p2[0] - p1[0]) * (p0[1] - p2[1])
        if abs(den) < 1e-12:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        a = ((p1[1] - p2[1]) * (xs - p2[0]) + (p2[0] - p1[0]) * (ys - p2[1])) / den
        b = ((p2[1] - p0[1]) * (xs - p2[0]) + (p0[0] - p2[0]) * (ys - p2[1])) / den
        c = 1.0 - a - b
        inside = (a >= -1e-6) & (b >= -1e-6) & (c >= -1e-6)
        if not inside.any():
            continue
        sl = (slice(y0, y1 + 1), slice(x0, x1 + 1))
        fid[sl][inside] = i
        bary[sl][inside] = np.stack([a, b, c], axis=-1)[inside]
    return fid, bary


def vertex_tangent_frames(mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray]:
    """Per-vertex (normal, tangent): the tangent follows +U (area-weighted over the faces around the vertex), made perpendicular to the normal."""
    v = np.asarray(mesh.vertices, dtype=np.float64)
    f = np.asarray(mesh.faces)
    uv = np.asarray(mesh.visual.uv, dtype=np.float64)  # type: ignore[union-attr]
    d1, d2 = v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]]
    u1, u2 = uv[f[:, 1]] - uv[f[:, 0]], uv[f[:, 2]] - uv[f[:, 0]]
    det = u1[:, 0] * u2[:, 1] - u2[:, 0] * u1[:, 1]
    det = np.where(np.abs(det) < 1e-14, 1e-14, det)
    tan_face = (d1 * u2[:, 1:2] - d2 * u1[:, 1:2]) / det[:, None]  # dP/du
    area = 0.5 * np.linalg.norm(np.cross(d1, d2), axis=1)
    acc = np.zeros_like(v)
    for k in range(3):
        np.add.at(acc, f[:, k], tan_face * area[:, None])
    n = _unit(np.asarray(mesh.vertex_normals, dtype=np.float64))
    t = _unit(acc - n * (acc * n).sum(axis=1, keepdims=True))
    return n, t


def bake_normal_map(
    targets: list[trimesh.Trimesh],
    source: trimesh.Trimesh,
    size: int = 1024,
    padding: int = 4,
    k: int = 3,
) -> tuple[bytes, dict[str, Any]]:
    """Tangent-space normal map (PNG bytes, 8-bit RGB) of ``source`` on the UV atlas of ``targets`` (same coordinate frame)."""
    if size < 16 or size > 8192 or size & (size - 1):
        raise InvalidInputError("Texture resolution must be a power of two between 16 and 8192.")
    src_v = np.asarray(source.vertices, dtype=np.float64)
    src_n = _unit(np.asarray(source.vertex_normals, dtype=np.float64))
    tree = cKDTree(src_v)
    img = np.empty((size, size, 3), dtype=np.uint8)
    img[:] = (128, 128, 255)  # flat
    covered = np.zeros((size, size), dtype=bool)
    rejected = 0
    total = 0
    deviations: list[float] = []
    for mesh in targets:
        fid, bary = rasterize_faces(mesh, size)
        cov = fid >= 0
        if not cov.any():
            continue
        faces = np.asarray(mesh.faces)[fid[cov]]
        w = bary[cov].astype(np.float64)
        verts = np.asarray(mesh.vertices, dtype=np.float64)
        n_v, t_v = vertex_tangent_frames(mesh)
        pos = np.einsum("mk,mkc->mc", w, verts[faces])
        n = _unit(np.einsum("mk,mkc->mc", w, n_v[faces]))
        t = np.einsum("mk,mkc->mc", w, t_v[faces])
        t = _unit(t - n * (t * n).sum(axis=1, keepdims=True))
        b = np.cross(n, t)
        kk = min(k, len(src_v))
        dist, idx = tree.query(pos, k=kk)
        if kk == 1:
            dist, idx = dist[:, None], idx[:, None]
        wgt = 1.0 / (dist + 1e-9)
        nh = _unit((src_n[idx] * wgt[..., None]).sum(axis=1))
        wrong_sheet = (nh * n).sum(
            axis=1
        ) < 0.2  # matched another surface (thin part, gap): keep the low mesh's own normal
        nh[wrong_sheet] = n[wrong_sheet]
        rejected += int(wrong_sheet.sum())
        total += len(pos)
        ts = np.stack([(nh * t).sum(axis=1), (nh * b).sum(axis=1), (nh * n).sum(axis=1)], axis=1)
        deviations.append(float(np.degrees(np.arccos(np.clip(ts[:, 2], -1, 1))).mean()))
        enc = ((_unit(ts) * 0.5 + 0.5) * 255.0).round().clip(0, 255).astype(np.uint8)
        img[cov] = enc
        covered |= cov
    img = dilate(img, covered, padding)
    buf = io.BytesIO()
    Image.fromarray(img, "RGB").save(buf, "PNG", optimize=True)
    return buf.getvalue(), {
        "size": size,
        "coverage": float(covered.mean()),
        "texels": total,
        "rejected_wrong_sheet": rejected,
        "mean_deviation_from_low_normal_deg": round(float(np.mean(deviations)), 3) if deviations else 0.0,
        "source_triangles": int(len(source.faces)),
        "method": "nearest dense vertices (inverse-distance blend), tangent space = U direction, bitangent = cross(N, T)",
    }
