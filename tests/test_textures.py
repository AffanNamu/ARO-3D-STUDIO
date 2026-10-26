import io
import subprocess
import sys

import numpy as np
import pytest
import trimesh
from PIL import Image

from aro_studio.core.errors import InvalidInputError, ModelError
from aro_studio.textures import process as tp
from aro_studio.textures import uv as uvmod
from aro_studio.textures.bake import bake_color_texture, rasterize_uv_positions
from aro_studio.textures.pipeline import (
    bake_scene_textures,
    compress_scene_textures,
    resize_scene_textures,
    unity_texture_settings,
)
from aro_studio.textures.uv import unwrap_jointly
from tests.conftest import make_scene_from_mesh


def coloured_sphere(sub=3):
    s = trimesh.creation.icosphere(subdivisions=sub)
    c = (np.abs(s.vertices) * 255).astype(np.uint8)
    s.visual = trimesh.visual.ColorVisuals(mesh=s, vertex_colors=np.c_[c, np.full(len(c), 255, np.uint8)])
    return s


def test_unwrap_gives_unit_uvs_and_preserves_faces_and_geometry():
    s, b = coloured_sphere(2), trimesh.creation.box()
    b.apply_translation((3, 0, 0))
    out = unwrap_jointly({"s": s, "b": b})
    assert set(out) == {"s", "b"}
    for k, src in (("s", s), ("b", b)):
        m = out[k]
        assert len(m.faces) == len(src.faces)
        uv = m.visual.uv
        assert uv.min() >= -1e-6 and uv.max() <= 1 + 1e-6
        assert m.area == pytest.approx(src.area, rel=1e-4)  # geometry unchanged by the vertex split
        assert m.metadata["source_vertex_index"].max() < len(src.vertices)


def test_unwrap_face_budget_error_is_actionable():
    with pytest.raises(InvalidInputError, match="limited to"):
        unwrap_jointly({"s": trimesh.creation.icosphere(3)}, max_faces=100)


def test_unwrap_crash_is_isolated_not_fatal(monkeypatch, tmp_path):
    """A native crash in xatlas must become a ModelError, not kill the Studio."""
    crasher = tmp_path / "w.py"
    crasher.write_text("import os, signal; os.kill(os.getpid(), signal.SIGSEGV)")
    monkeypatch.setattr(uvmod, "_WORKER", crasher)
    with pytest.raises(ModelError, match="crashed"):
        unwrap_jointly({"s": trimesh.creation.icosphere(1)})


def test_unwrap_timeout_maps_to_resource_limit(monkeypatch, tmp_path):
    slow = tmp_path / "w.py"
    slow.write_text("import time; time.sleep(30)")
    monkeypatch.setattr(uvmod, "_WORKER", slow)
    from aro_studio.core.errors import ResourceLimitError

    with pytest.raises(ResourceLimitError):
        unwrap_jointly({"s": trimesh.creation.icosphere(1)}, timeout_s=0.5)


def test_bake_projects_colour_from_source():
    s = coloured_sphere(3)
    uvm = unwrap_jointly({"s": s})["s"]
    png, stats = bake_color_texture([uvm], s, 512)
    img = np.asarray(Image.open(io.BytesIO(png)).convert("RGB"))
    assert stats["coverage"] > 0.4 and stats["max_projection_distance"] < 0.2
    # sample: for a covered texel the baked colour equals the colour of the nearest source vertex
    pos, cov = rasterize_uv_positions([uvm], 512)
    ys, xs = np.where(cov)
    i = len(ys) // 2
    p = pos[ys[i], xs[i]]
    nearest = np.argmin(np.linalg.norm(s.vertices - p, axis=1))
    assert (
        np.abs(img[ys[i], xs[i]].astype(int) - np.asarray(s.visual.vertex_colors[nearest][:3]).astype(int)).max() == 0
    )


def test_bake_requires_uv_colours_and_valid_resolution():
    s = coloured_sphere(1)
    with pytest.raises(InvalidInputError, match="UV"):
        bake_color_texture([s], s, 512)
    uvm = unwrap_jointly({"s": s})["s"]
    with pytest.raises(InvalidInputError, match="resolution"):
        bake_color_texture([uvm], s, 300)
    with pytest.raises(InvalidInputError, match="vertex colours"):
        bake_color_texture([uvm], trimesh.creation.box(), 512)


def test_scene_bake_creates_texture_material_and_uvs():
    sc = make_scene_from_mesh(coloured_sphere(2), "ball", category="prop")
    rep = bake_scene_textures(sc, resolution=512)
    assert rep["groups"] and sc.manifest.textures[0].width == 512
    mat = sc.manifest.material(sc.manifest.part("ball").material)
    assert mat.textures["base_color"] == sc.manifest.textures[0].name and mat.base_color[:3] == (1.0, 1.0, 1.0)
    assert sc.meshes["ball"].visual.uv is not None
    assert sc.manifest.textures[0].file in sc.texture_data


def test_scene_bake_from_high_res_source_onto_decimated_mesh():
    from aro_studio.geometry import ops

    hi = coloured_sphere(5)
    lo, _ = ops.decimate(hi, target_faces=800)
    sc = make_scene_from_mesh(lo, "ball", category="prop")
    src = make_scene_from_mesh(hi, "ball", category="prop")
    rep = bake_scene_textures(sc, resolution=512, source=src)
    assert rep["groups"][0]["max_projection_distance"] < 0.1


def test_scene_bake_skips_when_no_colours():
    sc = make_scene_from_mesh(trimesh.creation.icosphere(1), "ball", category="prop")
    rep = bake_scene_textures(sc, resolution=512)
    assert rep["skipped"] and not sc.manifest.textures


def test_resize_compress_and_settings():
    sc = make_scene_from_mesh(coloured_sphere(2), "ball", category="prop")
    bake_scene_textures(sc, resolution=1024)
    assert resize_scene_textures(sc, 512)[0]["to"] == [512, 512]
    assert resize_scene_textures(sc, 4096) == []  # never upscales
    out = compress_scene_textures(sc, "jpeg", 80)
    assert out and out[0]["bytes_after"] > 0 and sc.manifest.textures[0].file.endswith(".jpg")
    st = unity_texture_settings(sc)[0]
    assert st["sRGB"] and st["generateMipMaps"] and st["maxTextureSize"] == 512
    with pytest.raises(InvalidInputError):
        resize_scene_textures(sc, 300)


def test_pack_metallic_roughness_channels():
    r = tp.encode(Image.new("L", (64, 64), 200))
    m = tp.encode(Image.new("L", (64, 64), 30))
    packed = np.asarray(tp.open_image(tp.pack_metallic_roughness(r, m)).convert("RGB"))
    assert packed[0, 0].tolist() == [255, 200, 30]  # R=occlusion default 1.0, G=roughness, B=metallic


def test_mip_chain_and_pot():
    assert tp.mip_chain(1024, 1024)[-1] == (1, 1) and len(tp.mip_chain(1024, 1024)) == 11
    assert tp.is_power_of_two(512) and not tp.is_power_of_two(500)
    assert tp.mip_chain_memory_bytes(512, 512) == pytest.approx(512 * 512 * 4 * 4 / 3, rel=0.01)


def test_atlas_pack_no_overlap_and_uv_remap():
    imgs = {f"t{i}": Image.new("RGB", (64 * (1 + i % 3), 64), (i * 20, 0, 0)) for i in range(6)}
    atlas, rects = tp.pack_atlas(imgs, 1024)
    boxes = [(r.x, r.y, r.x + r.w, r.y + r.h) for r in rects.values()]
    for i, a in enumerate(boxes):
        assert a[2] <= atlas.width and a[3] <= atlas.height
        for b in boxes[i + 1 :]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]
    r = rects["t1"]
    uv = tp.remap_uv_to_atlas(np.array([[0.0, 1.0], [1.0, 0.0]]), r, atlas.width)
    assert uv[0, 0] == pytest.approx(r.x / atlas.width) and uv[1, 0] == pytest.approx((r.x + r.w) / atlas.width)
    with pytest.raises(InvalidInputError):
        tp.pack_atlas({"big": Image.new("RGB", (2000, 2000))}, 1024)


def test_worker_script_is_self_contained():
    # the worker must run under `python -I` with only numpy+xatlas importable
    src = uvmod._WORKER.read_text()
    assert "aro_studio" not in src
    assert (
        subprocess.run(
            [sys.executable, "-I", "-c", "import ast,sys; ast.parse(open(sys.argv[1]).read())", str(uvmod._WORKER)],
            check=False,
        ).returncode
        == 0
    )


def test_textured_face_colours_follow_the_uv_layout():
    """The six-view evidence renders must show the baked texture where the UVs say, v up (Studio convention)."""
    import io

    import numpy as np
    import trimesh
    from PIL import Image

    from aro_studio.utils.render import textured_face_colors

    img = Image.new("RGB", (8, 8), (255, 0, 0))  # top half red
    img.paste((0, 0, 255), (0, 4, 8, 8))  # bottom half blue
    buf = io.BytesIO()
    img.save(buf, "PNG")
    # one quad, two triangles: v in [0, 0.4] is the bottom of the image (blue), v in [0.6, 1] the top (red)
    verts = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=float)
    mesh = trimesh.Trimesh(verts, [[0, 1, 2], [0, 2, 3]], process=False)
    mesh.visual = trimesh.visual.TextureVisuals(uv=np.array([[0, 0], [1, 0], [1, 0.4], [0, 0.4]]))
    cols = textured_face_colors(mesh, buf.getvalue())
    assert cols is not None and np.allclose(cols, [[0, 0, 1], [0, 0, 1]])
    mesh.visual = trimesh.visual.TextureVisuals(uv=np.array([[0, 0.6], [1, 0.6], [1, 1], [0, 1]]))
    assert np.allclose(textured_face_colors(mesh, buf.getvalue()), [[1, 0, 0], [1, 0, 0]])
    plain = trimesh.Trimesh(verts, [[0, 1, 2]], process=False)
    assert (
        textured_face_colors(plain, buf.getvalue()) is None
    )  # no UVs: the caller falls back to the flat material colour
