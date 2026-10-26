"""REGRESSION: the GLB writer must follow glTF's texture convention (origin at the TOP-left of the image, V grows downward).

The Studio keeps UVs with V pointing up (like OBJ). Until 2026-10-26 they were written unchanged, so every exported texture was mirrored
vertically in any glTF-conforming reader (Blender, Unity, three.js). It went unnoticed because the checks used colour fields that only
vary horizontally, and our own renderer shares the writer's convention. This test decodes the written GLB independently and asks the only
question that matters: does a vertex at the TOP of the model sample the TOP of the image?
"""

from __future__ import annotations

import io

import numpy as np
import pygltflib as g
import trimesh
from PIL import Image

from aro_studio.export.gltf import ExportOptions, export_glb
from aro_studio.textures.pipeline import _set_texture
from tests.conftest import make_scene_from_mesh


def quad_scene():
    """A vertical quad (X wide, Y tall). Scene UVs, V up: the bottom edge is v = 0, the top edge v = 1."""
    verts = np.array([[-1, 0, 0], [1, 0, 0], [1, 2, 0], [-1, 2, 0]], dtype=float)
    m = trimesh.Trimesh(verts, [[0, 1, 2], [0, 2, 3]], process=False)
    m.visual = trimesh.visual.TextureVisuals(uv=np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=float))
    sc = make_scene_from_mesh(m, "wall", category="prop")
    img = Image.new("RGB", (8, 8), (0, 0, 255))  # bottom half blue
    img.paste((255, 0, 0), (0, 0, 8, 4))  # TOP half red (image row 0 is the top)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    _set_texture(sc, "wall_basecolor", buf.getvalue(), "base_color", "srgb")
    mat = sc.manifest.materials[0]
    mat.textures = {"base_color": "wall_basecolor"}
    return sc


def read_accessor(gltf: g.GLTF2, blob: bytes, index: int) -> np.ndarray:
    acc = gltf.accessors[index]
    view = gltf.bufferViews[acc.bufferView]
    n = {"VEC2": 2, "VEC3": 3}[acc.type]
    start = (view.byteOffset or 0) + (acc.byteOffset or 0)
    return np.frombuffer(blob[start : start + acc.count * n * 4], dtype="<f4").reshape(acc.count, n)


def test_the_top_of_the_model_samples_the_top_of_the_image_in_the_written_glb():
    data, _ = export_glb(quad_scene(), ExportOptions(root_name="wall"))
    gltf = g.GLTF2.load_from_bytes(data)
    blob = gltf.binary_blob()
    prim = gltf.meshes[0].primitives[0]
    pos = read_accessor(gltf, blob, prim.attributes.POSITION)
    uv = read_accessor(gltf, blob, prim.attributes.TEXCOORD_0)
    image_view = gltf.bufferViews[gltf.images[0].bufferView]
    start = image_view.byteOffset or 0
    image = np.asarray(Image.open(io.BytesIO(blob[start : start + image_view.byteLength])).convert("RGB"))
    h, w = image.shape[:2]
    for p, (u, v) in zip(pos, uv, strict=True):
        row = int(round(v * (h - 1)))  # glTF: v = 0 is the TOP row of the image
        col = int(round(u * (w - 1)))
        sampled = image[row, col]
        top = p[1] > 1.0  # the vertices at the top of the wall
        assert (sampled[0] == 255 and sampled[2] == 0) if top else (sampled[2] == 255 and sampled[0] == 0), (
            p,
            (u, v),
            sampled,
        )


def test_obj_keeps_the_scene_convention_where_v_points_up():
    from aro_studio.export.obj import export_obj

    otext, _mtl, _files, _rep = export_obj(quad_scene(), name="wall")
    vts = [tuple(float(x) for x in ln.split()[1:3]) for ln in otext.splitlines() if ln.startswith("vt ")]
    assert sorted(vts) == [
        (0.0, 0.0),
        (0.0, 1.0),
        (1.0, 0.0),
        (1.0, 1.0),
    ]  # OBJ, like the scene, has the origin at the bottom-left
