"""High-to-low normal bake: the recovered tangent-space normals must equal the dense surface's true normals (analytic here)."""

from __future__ import annotations

import io

import numpy as np
import pytest
import trimesh
from PIL import Image

from aro_studio.core.errors import InvalidInputError
from aro_studio.textures.normal_bake import bake_normal_map

AMP, FREQ = 0.02, 3.0


def height(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return AMP * np.sin(2 * np.pi * FREQ * x) * np.sin(2 * np.pi * FREQ * y)


def analytic_normal(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    k = 2 * np.pi * FREQ
    hx = AMP * k * np.cos(k * x) * np.sin(k * y)
    hy = AMP * k * np.sin(k * x) * np.cos(k * y)
    n = np.stack([-hx, -hy, np.ones_like(x)], axis=-1)
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


def dense_bumpy_plane(divs: int = 160) -> trimesh.Trimesh:
    g = np.linspace(0.0, 1.0, divs + 1)
    xx, yy = np.meshgrid(g, g, indexing="ij")
    verts = np.stack([xx.ravel(), yy.ravel(), height(xx, yy).ravel()], axis=1)
    idx = np.arange((divs + 1) ** 2).reshape(divs + 1, divs + 1)
    a, b, c, d = idx[:-1, :-1].ravel(), idx[1:, :-1].ravel(), idx[1:, 1:].ravel(), idx[:-1, 1:].ravel()
    faces = np.concatenate([np.stack([a, b, c], 1), np.stack([a, c, d], 1)])
    return trimesh.Trimesh(verts, faces, process=False)


def low_quad(uv_of) -> trimesh.Trimesh:
    verts = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=float)
    m = trimesh.Trimesh(verts, [[0, 1, 2], [0, 2, 3]], process=False)
    m.visual = trimesh.visual.TextureVisuals(uv=np.array([uv_of(v) for v in verts]))
    return m


def decode(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).astype(float) / 255.0 * 2.0 - 1.0


def texel_xy(size: int) -> tuple[np.ndarray, np.ndarray]:
    cols, rows = np.meshgrid(np.arange(size), np.arange(size))
    return (cols + 0.5) / size, 1.0 - (rows + 0.5) / size  # V points up: image row 0 is the top


def angle_deg(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.degrees(np.arccos(np.clip((a * b).sum(axis=-1), -1, 1)))


def test_normals_of_a_dense_bumpy_surface_land_on_a_two_triangle_quad():
    png, stats = bake_normal_map([low_quad(lambda v: (v[0], v[1]))], dense_bumpy_plane(), size=128)
    ts = decode(png)
    ts = ts / np.linalg.norm(ts, axis=-1, keepdims=True)
    x, y = texel_xy(128)
    want = analytic_normal(x, y)  # tangent frame of this quad: T = +X, B = +Y, N = +Z, so tangent space = world here
    err = angle_deg(ts, want)
    assert err.mean() < 3.0 and np.percentile(err, 99) < 10.0, (err.mean(), np.percentile(err, 99))
    assert stats["coverage"] > 0.98 and stats["source_triangles"] == 2 * 160 * 160
    assert ts[..., 2].min() > 0.9  # the bumps are gentle: every normal still faces the viewer


def test_the_normal_map_follows_the_uv_layout_not_the_world_axes():
    """Swap U and V (a mirrored layout): T becomes +Y and B = cross(N, T) = -X. Decoded through that frame the normals must still be right."""
    png, _ = bake_normal_map([low_quad(lambda v: (v[1], v[0]))], dense_bumpy_plane(), size=128)
    ts = decode(png)
    ts = ts / np.linalg.norm(ts, axis=-1, keepdims=True)
    cols, rows = np.meshgrid(np.arange(128), np.arange(128))
    u, v = (cols + 0.5) / 128, 1.0 - (rows + 0.5) / 128
    x, y = v, u  # uv = (y, x)  =>  x = v, y = u
    world = (
        ts[..., 0:1] * np.array([0.0, 1.0, 0.0])
        + ts[..., 1:2] * np.array([-1.0, 0.0, 0.0])
        + ts[..., 2:3] * np.array([0.0, 0.0, 1.0])
    )
    assert angle_deg(world, analytic_normal(x, y)).mean() < 3.0


def test_a_flat_source_gives_a_flat_map_and_the_same_encoding_as_a_blank_normal_texture():
    flat = trimesh.Trimesh(*_plane())
    png, stats = bake_normal_map([low_quad(lambda v: (v[0], v[1]))], flat, size=64)
    a = np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).astype(int)
    assert np.abs(a - np.array([128, 128, 255])).max() <= 1
    assert stats["mean_deviation_from_low_normal_deg"] < 1.0


def _plane():
    g = np.linspace(0, 1, 21)
    xx, yy = np.meshgrid(g, g, indexing="ij")
    verts = np.stack([xx.ravel(), yy.ravel(), np.zeros(xx.size)], axis=1)
    idx = np.arange(21 * 21).reshape(21, 21)
    a, b, c, d = idx[:-1, :-1].ravel(), idx[1:, :-1].ravel(), idx[1:, 1:].ravel(), idx[:-1, 1:].ravel()
    return verts, np.concatenate([np.stack([a, b, c], 1), np.stack([a, c, d], 1)])


def test_refuses_meshes_without_uvs_and_unsupported_sizes():
    bare = trimesh.Trimesh(*_plane())
    with pytest.raises(InvalidInputError, match="UVs"):
        bake_normal_map([bare], dense_bumpy_plane(20), size=64)
    with pytest.raises(InvalidInputError, match="resolution"):
        bake_normal_map([low_quad(lambda v: (v[0], v[1]))], dense_bumpy_plane(20), size=100)
