"""FBX / USD / .blend export through the optional Blender backend, verified by Blender re-importing what was written.

Unit tests (no Blender) check the configuration, the honest "not available" behaviour and the API. The integration tests need a Python with
the ``bpy`` module: set ARO_BLENDER_PYTHON (CI does; ARO_BLENDER_REQUIRED=1 makes a missing backend a FAILURE instead of a skip).
Blender is an independent reader, so these tests prove the exported files carry the triangles, the real-world size in metres, the materials
and the baked maps, not merely that a writer ran. They do NOT prove that Unreal Engine or Unity open the files: nothing here ran those.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
import trimesh

from aro_studio.app_context import build_context
from aro_studio.config import Settings
from aro_studio.core.enums import Stage
from aro_studio.export.blender import HOW_TO_ENABLE, BlenderBackend
from aro_studio.geometry import ops
from aro_studio.textures.pipeline import bake_scene_textures
from tests.conftest import make_scene_from_mesh
from tests.support import PlumbingEngine
from tests.test_textures import coloured_sphere

PYTHON = os.environ.get("ARO_BLENDER_PYTHON", "")
HAVE_BLENDER = bool(PYTHON) and Path(PYTHON).exists()
needs_blender = pytest.mark.skipif(
    not HAVE_BLENDER and os.environ.get("ARO_BLENDER_REQUIRED") != "1",
    reason="set ARO_BLENDER_PYTHON to a Python with the bpy module (pip install bpy on Python 3.11)",
)


@pytest.fixture
def studio(tmp_path, monkeypatch):
    for k in ("ARO_BLENDER_PYTHON", "ARO_BLENDER_BIN"):
        monkeypatch.delenv(k, raising=False)
    ctx = build_context(Settings(data_dir=tmp_path / "d"), engines=[PlumbingEngine()], start_workers=False)
    yield ctx
    ctx.close()


def add_version(studio, scene, name="Prop"):
    p = studio.projects.create("blender")
    a = studio.assets.create_asset(p["project_id"], name, "prop")
    return studio.assets.add_version(
        a["asset_id"], scene, stage=Stage.PROCESSED, operation="test", description="synthetic"
    )


def textured_scene():
    """A decimated, UV-unwrapped sphere with a baked colour texture AND a baked normal map (from a dense bumpy source)."""
    hi = coloured_sphere(5)
    v = np.asarray(hi.vertices)
    hi.vertices = v * (1.0 + 0.04 * np.sin(12 * v[:, 0]) * np.sin(12 * v[:, 1]))[:, None]
    lo, _ = ops.decimate(hi, target_faces=800)
    lo.apply_scale([4.0, 1.5, 2.0])  # a known real-world size in metres
    hi.apply_scale([4.0, 1.5, 2.0])
    sc = make_scene_from_mesh(lo, "ball", category="prop")
    src = make_scene_from_mesh(hi, "ball", category="prop")
    rep = bake_scene_textures(sc, resolution=512, source=src, bake_normals=True)
    assert rep["groups"][0]["normal_map"]["coverage"] > 0.2
    return sc


# ---- no Blender needed -------------------------------------------------------------------------
def test_without_configuration_the_backend_says_why_and_how(monkeypatch):
    for k in ("ARO_BLENDER_PYTHON", "ARO_BLENDER_BIN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PATH", "/nonexistent")
    be = BlenderBackend.from_env()
    be.python = ""
    av = be.availability()
    if av["ok"]:
        pytest.skip("bpy is importable by this interpreter: Blender is available here")
    assert not av["ok"] and av["how"] == HOW_TO_ENABLE and "not configured" in av["reasons"][0]


def test_a_missing_interpreter_path_is_reported_not_guessed(tmp_path):
    av = BlenderBackend(python=str(tmp_path / "nope" / "python")).availability()
    assert not av["ok"] and "does not exist" in av["reasons"][0]


def test_format_status_lists_native_formats_as_available_and_blender_ones_with_reasons(studio):
    if studio.exports.blender.availability()["ok"]:
        pytest.skip("Blender is available in this environment")
    st = studio.exports.format_status()
    assert all(st[f]["available"] for f in ("glb", "gltf", "obj", "unity"))
    for f in ("fbx", "usd", "blend"):
        assert not st[f]["available"] and st[f]["reasons"] and st[f]["how"] and st[f]["needs"] == "Blender backend"


def test_exporting_fbx_without_blender_fails_with_an_explanation_and_no_fake_file(studio):
    if studio.exports.blender.availability()["ok"]:
        pytest.skip("Blender is available in this environment")
    sc = make_scene_from_mesh(trimesh.creation.box((2, 1, 4)), "box")
    v = add_version(studio, sc)
    rec = studio.exports.export(v["version_id"], "fbx")
    assert rec["status"] == "FAILED" and rec["size_bytes"] is None and rec["path"] == ""
    assert "Blender" in rec["report"]["error"]["message"] and rec["report"]["error"]["recommended_action"]


def test_unknown_target_is_refused_before_anything_is_written(studio):
    sc = make_scene_from_mesh(trimesh.creation.box((2, 1, 4)), "box")
    v = add_version(studio, sc)
    rec = studio.exports.export(v["version_id"], "fbx", "playstation")
    assert rec["status"] == "FAILED"


# ---- needs Blender -----------------------------------------------------------------------------
@pytest.fixture
def blender_studio(tmp_path):
    ctx = build_context(
        Settings(data_dir=tmp_path / "d", blender_python=PYTHON), engines=[PlumbingEngine()], start_workers=False
    )
    yield ctx
    ctx.close()


@needs_blender
@pytest.mark.parametrize("fmt,target", [("fbx", "unity"), ("fbx", "unreal"), ("usd", "unity"), ("blend", "unity")])
def test_textured_asset_survives_a_round_trip_through_blender(blender_studio, fmt, target):
    sc = textured_scene()
    v = add_version(blender_studio, sc)
    rec = blender_studio.exports.export(v["version_id"], fmt, target)
    assert rec["status"] == "COMPLETED", rec["report"]
    checks = {c["id"]: c for c in rec["report"]["verification"]["checks"]}
    failed = [c for c in checks.values() if not c["ok"]]
    assert not failed, failed
    assert {"triangles", "extents", "materials", "normal_maps", "base_color_maps"} <= set(checks)
    src = rec["report"]["source_in_blender"]
    # the real-world size in metres reached Blender intact (X width, Y height, Z length in the Studio frame)
    assert src["extents_studio_m"] == pytest.approx(sc.combined().extents.tolist(), rel=0.01)
    assert rec["size_bytes"] > 1000 and rec["report"]["not_verified"]


@needs_blender
def test_blender_reads_the_exported_glb_as_an_independent_consumer(blender_studio, tmp_path):
    sc = textured_scene()
    v = add_version(blender_studio, sc)
    rec = blender_studio.exports.export(v["version_id"], "glb")
    glb = blender_studio.exports.file_path(rec["export_id"])
    info = blender_studio.exports.blender.inspect(glb)
    assert info["triangles_lod0"] == len(sc.meshes["ball"].faces)
    assert info["extents_studio_m"] == pytest.approx(sc.combined().extents.tolist(), rel=0.01)
    assert any(m.get("normal_map") and m.get("base_color_map") for m in info["materials"].values())


@needs_blender
def test_the_texture_lands_where_the_asset_says_not_mirrored(blender_studio):
    """REGRESSION (found by this very check): the GLB writer left V pointing up, so Blender, Unity and any glTF reader saw every texture
    mirrored vertically. The baked colour field is a function of position (red = |x|, green = |y|, blue = |z| of the unit sphere); the
    image Blender samples at each UV corner must follow it, in particular along the VERTICAL direction."""
    sc = textured_scene()
    v = add_version(blender_studio, sc)
    rec = blender_studio.exports.export(v["version_id"], "glb")
    info = blender_studio.exports.blender.inspect(blender_studio.exports.file_path(rec["export_id"]), probe=3000)
    pos_b = np.array(info["probe"]["positions_blender"])
    col = np.array(info["probe"]["colors"])
    studio = np.stack(
        [pos_b[:, 0], pos_b[:, 2], -pos_b[:, 1]], axis=1
    )  # Blender (X, Y fwd, Z up) -> Studio (X, Y up, Z fwd)
    size = sc.combined().extents / 2.0  # the sphere was unit radius before it was scaled to the real size
    want = np.abs(studio - sc.combined().bounds.mean(axis=0)) / size
    for ch, name in enumerate("xyz"):
        c = np.corrcoef(col[:, ch], want[:, ch])[0, 1]
        assert c > 0.9, (
            f"colour channel {name} does not follow |{name}| (corr {c:.2f}): the texture is mirrored or scrambled"
        )
