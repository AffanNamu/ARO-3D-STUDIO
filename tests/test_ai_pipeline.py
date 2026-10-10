"""Post-reconstruction pipeline for single-mesh vertex-coloured raw assets.

PLUMBING TEST: the raw mesh below is a synthetic, TripoSR-scale (~330k triangles) vertex-coloured shape imported through the
normal import path (provenance = "import"). It is NOT AI output and nothing here claims inference works; it proves that the
code that will process a real reconstruction runs end to end (orient → scale → clean → decimate → bake → collision → LOD →
validate → export → verify) so a first GPU run is not also the first run of this code.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
import trimesh

from aro_studio.app_context import build_context
from aro_studio.config import Settings
from aro_studio.export.verify import verify_glb
from aro_studio.processing.ai_pipeline import AIPipelineOptions, choose_axes, run_ai_pipeline
from tests.support import PlumbingEngine


@pytest.fixture(scope="module")
def raw_like_mesh_glb() -> bytes:
    """Elongated blob, Z-up native frame, long axis along native X, with vertex colours: the geometry class TripoSR emits."""
    m = trimesh.creation.icosphere(subdivisions=7)
    m.apply_scale([1.0, 0.45, 0.4])  # long along X, narrow Y, low Z
    c = ((m.vertices - m.vertices.min(0)) / np.ptp(m.vertices, axis=0) * 255).astype(np.uint8)
    m.visual = trimesh.visual.ColorVisuals(mesh=m, vertex_colors=np.c_[c, np.full(len(c), 255, np.uint8)])
    return m.export(file_type="glb")


@pytest.fixture
def studio(tmp_path):
    ctx = build_context(Settings(data_dir=tmp_path / "d"), engines=[PlumbingEngine()], start_workers=False)
    yield ctx
    ctx.close()


def test_axis_choice_is_explicit_about_what_it_cannot_know():
    up, fwd, notes = choose_axes(np.array([2.0, 0.9, 0.8]), AIPipelineOptions())
    assert (up, fwd) == ("+Z", "+X") and any("FRONT" in n for n in notes) and any("engine hint" in n for n in notes)
    up, fwd, notes = choose_axes(np.array([2.0, 0.9, 0.8]), AIPipelineOptions(up="+Y", forward="-Z"))
    assert (up, fwd) == ("+Y", "-Z") and not notes


def test_ai_style_pipeline_runs_end_to_end_and_never_claims_production_ready_without_a_vehicle_spec(
    studio, raw_like_mesh_glb
):
    from aro_studio.assets.importer import import_mesh_bytes
    from aro_studio.core.enums import Stage

    p = studio.projects.create("ai-shaped")
    a = studio.assets.create_asset(p["project_id"], "ARO TITAN 480", "heavy_truck")
    scene, _ = import_mesh_bytes(
        raw_like_mesh_glb, "raw.glb", name=a["name"], category=a["category"], max_bytes=200_000_000
    )
    raw = studio.assets.add_version(
        a["asset_id"], scene, stage=Stage.RAW, operation="import", description="synthetic plumbing input (NOT AI)"
    )
    assert raw["triangle_count"] > 300_000 and scene.manifest.provenance.source == "import"
    raw_hash = raw["manifest_sha256"]

    rep = run_ai_pipeline(studio.processing, studio.assets, raw["version_id"], AIPipelineOptions(length_m=6.5))
    assert rep["ok"], [s for s in rep["steps"] if s["status"] != "PASS"]
    names = [s["step"] for s in rep["steps"]]
    for expected in ("orient", "decimate", "bake", "collision", "LOD", "validation", "finalize"):
        assert any(expected in n for n in names), expected

    # orientation/scale actually applied: long axis is now Z, 6.5 m, on the ground, centred
    final = studio.assets.load_scene(rep["final_version_id"])
    ext = final.combined().extents
    assert int(np.argmax(ext)) == 2 and ext[2] == pytest.approx(6.5, rel=1e-3)
    assert final.combined().bounds[0][1] == pytest.approx(0.0, abs=1e-6)
    assert (
        final.triangle_count <= 25_000 and final.manifest.textures and final.manifest.lods and final.manifest.colliders
    )
    assert final.manifest.provenance.source == "import"  # provenance preserved through every derived version

    # honest outcome: a vehicle without wheel/axle metadata must NOT validate as production ready
    assert rep["validation"]["status"] == "NEEDS_REVIEW" and rep["validation"]["critical_failures"] >= 1
    assert any("vehicle specification" in n for n in rep["needs_human"]) and any(
        "FRONT" in n for n in rep["needs_human"]
    )

    # raw untouched; the result exports and verifies
    assert studio.assets.get_version(raw["version_id"])["manifest_sha256"] == raw_hash
    assert studio.assets.load_scene(raw["version_id"]).triangle_count == raw["triangle_count"]
    glb = studio.exports.export(rep["final_version_id"], "glb")
    assert glb["status"] == "COMPLETED" and glb["report"]["verification"]["ok"]
    data = studio.exports.file_path(glb["export_id"]).read_bytes()
    assert verify_glb(data, final)["ok"] and len(io.BytesIO(data).getbuffer()) > 10_000


def test_pipeline_failure_is_recorded_not_hidden(studio, raw_like_mesh_glb):
    from aro_studio.assets.importer import import_mesh_bytes
    from aro_studio.core.enums import Stage

    p = studio.projects.create("fail")
    a = studio.assets.create_asset(p["project_id"], "x", "prop")
    scene, _ = import_mesh_bytes(raw_like_mesh_glb, "raw.glb", name="x", category="prop", max_bytes=200_000_000)
    raw = studio.assets.add_version(a["asset_id"], scene, stage=Stage.RAW, operation="import")
    rep = run_ai_pipeline(
        studio.processing, studio.assets, raw["version_id"], AIPipelineOptions(target_triangles=60_000)
    )  # over the UV limit
    assert rep["ok"] is False
    failing = [s for s in rep["steps"] if s["status"] == "FAIL"]
    assert (
        failing
        and "limited to" in str(failing[0]["detail"]["error"])
        and any("UV unwrap limit" in n for n in rep["needs_human"])
    )
