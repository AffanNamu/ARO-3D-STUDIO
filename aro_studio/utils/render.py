"""Tiny dependency-free software renderer (painter's algorithm, flat shading).

Used for thumbnails and for rendering the procedural reference asset to an image. Not a substitute for
the interactive three.js viewer.
"""

from __future__ import annotations

from typing import Any

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


def textured_face_colors(mesh: trimesh.Trimesh, texture: bytes) -> np.ndarray | None:
    """RGB 0..1 per face: the baked texture sampled at each triangle's UV centroid (Studio UV convention: v up). None if no UVs."""
    import io

    uv = getattr(mesh.visual, "uv", None)
    if uv is None or len(uv) != len(mesh.vertices):
        return None
    img = np.asarray(Image.open(io.BytesIO(texture)).convert("RGB"), dtype=np.float32) / 255.0
    h, w = img.shape[:2]
    c = np.asarray(uv)[np.asarray(mesh.faces)].mean(axis=1)
    px = np.clip((c[:, 0] * (w - 1)).round().astype(int), 0, w - 1)
    py = np.clip(((1.0 - c[:, 1]) * (h - 1)).round().astype(int), 0, h - 1)
    return img[py, px]


def render_scene(
    items: list[tuple[trimesh.Trimesh, tuple[float, float, float, float] | np.ndarray]],
    *,
    azimuth_deg: float = 35.0,
    elevation_deg: float = 15.0,
    size: int = 768,
    background=(238, 238, 238),
    fov_deg: float = 28.0,
    smooth_shading: bool = False,
    shaded: bool = True,
) -> Image.Image:
    """Render ``(mesh, colour)`` items; colour is one rgba 0..1 tuple or an (n_faces, 3|4) array of per-face colours. +Y is up; azimuth 0 looks at the +Z face from +Z.

    ``smooth_shading`` lights each triangle with the average of its vertex normals, which is what a viewer shows for an exported mesh that
    carries smooth normals (the default flat shading exaggerates facets and surface noise). ``shaded=False`` draws the colours as they are
    (no lighting), for tests and texture previews.
    """
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
        if smooth_shading:
            vn = np.asarray(mesh.vertex_normals)[fcs].mean(axis=1)
            lv = np.linalg.norm(vn, axis=1, keepdims=True)
            n = vn / np.where(lv == 0, 1, lv)
        shade = (0.38 + 0.62 * np.clip((n * light).sum(axis=1), 0, 1)) if shaded else np.ones(len(n))
        rel = t - eye
        cam = np.stack([rel @ r, rel @ u, rel @ f], axis=-1)  # (N,3,3) x,y,depth
        depth = cam[:, :, 2].mean(axis=1)
        scale = (size / 2) / np.tan(np.radians(fov_deg) / 2)
        px = size / 2 + cam[:, :, 0] / np.maximum(cam[:, :, 2], 1e-6) * scale
        py = size / 2 - cam[:, :, 1] / np.maximum(cam[:, :, 2], 1e-6) * scale
        cols: Any = color
        per_face = isinstance(cols, np.ndarray) and cols.ndim == 2
        for i in np.where(facing & (cam[:, :, 2] > 0.01).all(axis=1))[0]:
            tris.append((depth[i], px[i], py[i], shade[i], cols[i] if per_face else cols))
    tris.sort(key=lambda x: -x[0])
    ss = 2
    img = Image.new("RGB", (size * ss, size * ss), background)
    d = ImageDraw.Draw(img)
    for _depth, px, py, sh, col in tris:
        rgb = tuple(int(np.clip(c * sh, 0, 1) * 255) for c in col[:3])
        d.polygon([(px[0] * ss, py[0] * ss), (px[1] * ss, py[1] * ss), (px[2] * ss, py[2] * ss)], fill=rgb)
    return img.resize((size, size), Image.Resampling.LANCZOS)


def render_asset_scene(scene, *, textured: bool = True, **kw) -> Image.Image:
    """Render an asset's LOD0. With ``textured`` a part whose material has a baked base-colour texture is shown in that colour (sampled per
    triangle), so the views show what the export will look like; otherwise (or without a texture) the material's flat colour is used."""
    items: list = []
    mats = {m.name: m for m in scene.manifest.materials}
    for p in scene.manifest.parts:
        m = scene.meshes[p.name]
        mat = mats.get(p.material or "")
        col: Any = mat.base_color if mat else (0.7, 0.7, 0.7, 1.0)
        if mat and mat.category.value == "glass":
            col = (0.35, 0.5, 0.58, 1.0)
        elif textured and mat and mat.textures.get("base_color"):
            tdef = scene.manifest.texture(mat.textures["base_color"])
            data = scene.texture_data.get(tdef.file) if tdef else None
            faces_rgb = textured_face_colors(m, data) if data else None
            if faces_rgb is not None:
                tint = np.asarray(mat.base_color[:3], dtype=np.float32)
                col = np.clip(faces_rgb * tint, 0, 1)
        items.append((m, col))
    return render_scene(items, **kw)
