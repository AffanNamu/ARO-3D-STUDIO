"""Tiny dependency-free software renderer (painter's algorithm, flat shading).

Used for thumbnails and for rendering the procedural reference asset to an image. Not a substitute for
the interactive three.js viewer.
"""

from __future__ import annotations

import numpy as np
import trimesh
from PIL import Image, ImageDraw


def _look_at(eye, target, up=(0, 1, 0)):
    f = np.asarray(target, float) - np.asarray(eye, float)
    f /= np.linalg.norm(f)
    r = np.cross(f, up)
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    return r, u, f


def render_scene(
    items: list[tuple[trimesh.Trimesh, tuple[float, float, float, float]]],
    *,
    azimuth_deg: float = 35.0,
    elevation_deg: float = 15.0,
    size: int = 768,
    background=(238, 238, 238),
    fov_deg: float = 28.0,
) -> Image.Image:
    """Render ``(mesh, rgba 0..1)`` items. +Y is up; azimuth 0 looks at the +Z face from +Z."""
    all_v = np.concatenate([m.vertices for m, _ in items])
    center = (all_v.min(0) + all_v.max(0)) / 2
    radius = np.linalg.norm(all_v.max(0) - all_v.min(0)) / 2
    az, el = np.radians(azimuth_deg), np.radians(elevation_deg)
    dist = radius / np.tan(np.radians(fov_deg) / 2) * 1.05
    eye = center + dist * np.array([np.sin(az) * np.cos(el), np.sin(el), np.cos(az) * np.cos(el)])
    r, u, f = _look_at(eye, center)
    light = np.array([0.4, 0.8, 0.5])
    light /= np.linalg.norm(light)
    tris = []
    for mesh, color in items:
        v = np.asarray(mesh.vertices)
        fcs = np.asarray(mesh.faces)
        t = v[fcs]
        n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        ln = np.linalg.norm(n, axis=1, keepdims=True)
        n = n / np.where(ln == 0, 1, ln)
        centroid = t.mean(axis=1)
        facing = ((eye - centroid) * n).sum(axis=1) > 0
        shade = 0.38 + 0.62 * np.clip((n * light).sum(axis=1), 0, 1)
        rel = t - eye
        cam = np.stack([rel @ r, rel @ u, rel @ f], axis=-1)  # (N,3,3) x,y,depth
        depth = cam[:, :, 2].mean(axis=1)
        scale = (size / 2) / np.tan(np.radians(fov_deg) / 2)
        px = size / 2 + cam[:, :, 0] / np.maximum(cam[:, :, 2], 1e-6) * scale
        py = size / 2 - cam[:, :, 1] / np.maximum(cam[:, :, 2], 1e-6) * scale
        for i in np.where(facing & (cam[:, :, 2] > 0.01).all(axis=1))[0]:
            tris.append((depth[i], px[i], py[i], shade[i], color))
    tris.sort(key=lambda x: -x[0])
    ss = 2
    img = Image.new("RGB", (size * ss, size * ss), background)
    d = ImageDraw.Draw(img)
    for _depth, px, py, sh, col in tris:
        rgb = tuple(int(np.clip(c * sh, 0, 1) * 255) for c in col[:3])
        d.polygon([(px[0] * ss, py[0] * ss), (px[1] * ss, py[1] * ss), (px[2] * ss, py[2] * ss)], fill=rgb)
    return img.resize((size, size), Image.Resampling.LANCZOS)


def render_asset_scene(scene, **kw) -> Image.Image:
    items = []
    mats = {m.name: m for m in scene.manifest.materials}
    for p in scene.manifest.parts:
        m = scene.meshes[p.name]
        mat = mats.get(p.material or "")
        col = mat.base_color if mat else (0.7, 0.7, 0.7, 1.0)
        if mat and mat.category.value == "glass":
            col = (0.35, 0.5, 0.58, 1.0)
        items.append((m, col))
    return render_scene(items, **kw)
