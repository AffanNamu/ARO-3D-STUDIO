"""Texture projection and baking (spec §15): rasterise UV space and project colour from a source mesh."""

from __future__ import annotations

import io

import numpy as np
import trimesh
from PIL import Image
from scipy import ndimage
from scipy.spatial import cKDTree

from aro_studio.core.errors import InvalidInputError
from aro_studio.core.tm import vertex_colors

ALLOWED_RESOLUTIONS = (512, 1024, 2048, 4096)


def rasterize_uv_positions(meshes: list[trimesh.Trimesh], size: int) -> tuple[np.ndarray, np.ndarray]:
    """For every texel covered by a triangle, return the interpolated 3D position.

    Returns (positions[size,size,3], coverage[size,size] bool). V is flipped so the image origin is
    top-left as glTF expects (v=0 is the top row).
    """
    pos = np.zeros((size, size, 3), dtype=np.float64)
    cov = np.zeros((size, size), dtype=bool)
    for mesh in meshes:
        uv = getattr(mesh.visual, "uv", None)
        if uv is None:
            raise InvalidInputError("Baking needs UVs: unwrap the mesh first.")
        uv = np.asarray(uv, dtype=np.float64)
        px = np.stack([uv[:, 0] * size, (1.0 - uv[:, 1]) * size], axis=1)  # pixel coords, y down
        verts = np.asarray(mesh.vertices, dtype=np.float64)
        for f in np.asarray(mesh.faces):
            p0, p1, p2 = px[f[0]], px[f[1]], px[f[2]]
            x0, x1 = (
                int(max(0, np.floor(min(p0[0], p1[0], p2[0])))),
                int(min(size - 1, np.ceil(max(p0[0], p1[0], p2[0])))),
            )
            y0, y1 = (
                int(max(0, np.floor(min(p0[1], p1[1], p2[1])))),
                int(min(size - 1, np.ceil(max(p0[1], p1[1], p2[1])))),
            )
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
            P = a[..., None] * verts[f[0]] + b[..., None] * verts[f[1]] + c[..., None] * verts[f[2]]
            sl = (slice(y0, y1 + 1), slice(x0, x1 + 1))
            pos[sl][inside] = P[inside]
            cov[sl] |= inside
    return pos, cov


def dilate(image: np.ndarray, coverage: np.ndarray, padding: int) -> np.ndarray:
    """Bleed covered texel colours outward by ``padding`` px to hide seams under mip-mapping."""
    if padding <= 0 or coverage.all():
        return image
    dist, (iy, ix) = ndimage.distance_transform_edt(~coverage, return_indices=True)
    out = image.copy()
    fill = (~coverage) & (dist <= padding)
    out[fill] = image[iy[fill], ix[fill]]
    return out


def bake_color_texture(
    targets: list[trimesh.Trimesh],
    source: trimesh.Trimesh,
    size: int = 1024,
    padding: int = 4,
    fallback_color: tuple[int, int, int] = (128, 128, 128),
) -> tuple[bytes, dict]:
    """Project vertex colours from ``source`` onto the UV space of ``targets`` (nearest source vertex).

    Returns (png_bytes, stats). ``source`` must carry vertex colours.
    """
    if size not in ALLOWED_RESOLUTIONS:
        raise InvalidInputError(f"Texture resolution must be one of {ALLOWED_RESOLUTIONS}.")
    vc = vertex_colors(source)
    if vc is None:
        raise InvalidInputError("The source mesh has no vertex colours to bake.")
    colors = vc[:, :3]
    pos, cov = rasterize_uv_positions(targets, size)
    img = np.empty((size, size, 3), dtype=np.uint8)
    img[:] = fallback_color
    if cov.any():
        tree = cKDTree(np.asarray(source.vertices))
        dist, idx = tree.query(pos[cov])
        img[cov] = colors[idx]
        max_dist = float(dist.max())
    else:
        max_dist = 0.0
    img = dilate(img, cov, padding)
    buf = io.BytesIO()
    Image.fromarray(img, "RGB").save(buf, "PNG", optimize=True)
    return buf.getvalue(), {
        "size": size,
        "coverage": float(cov.mean()),
        "max_projection_distance": max_dist,
        "padding": padding,
    }
