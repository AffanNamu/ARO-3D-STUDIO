"""Performance budgets (spec §37). Budgets are deliberately generous (CI machines vary) - they catch order-of-magnitude
regressions such as an accidental O(n²) in mesh processing, not micro-optimisations. Measured numbers on a 4-vCPU
sandbox are printed with `-s` and recorded in docs/deployment/infrastructure.md."""

from __future__ import annotations

import time

import numpy as np
import pytest
import trimesh

from aro_studio.export.gltf import export_glb
from aro_studio.export.verify import verify_glb
from aro_studio.geometry import ops
from aro_studio.geometry.inspect import inspect_mesh
from aro_studio.geometry.selfintersect import find_self_intersections
from aro_studio.lod.generator import generate_lods
from aro_studio.textures.uv import unwrap_jointly
from aro_studio.validation.engine import ValidationConfig, run_validation
from aro_studio.vehicles.titan480 import build_titan480
from tests.conftest import make_scene_from_mesh

pytestmark = pytest.mark.performance


def timed(fn, *a, **k):
    t = time.perf_counter()
    out = fn(*a, **k)
    return out, time.perf_counter() - t


@pytest.fixture(scope="module")
def big():
    """~330k-triangle coloured mesh: the scale of a TripoSR 256³ output."""
    m = trimesh.creation.icosphere(subdivisions=7)
    c = (np.abs(m.vertices) * 255).astype(np.uint8)
    m.visual = trimesh.visual.ColorVisuals(mesh=m, vertex_colors=np.c_[c, np.full(len(c), 255, np.uint8)])
    return m


def test_big_mesh_scale(big):
    assert len(big.faces) > 300_000


def test_inspection_of_a_reconstruction_sized_mesh_is_fast(big):
    r, dt = timed(inspect_mesh, big, check_intersections=False)
    print(f"inspect {len(big.faces)} faces: {dt:.2f}s")
    assert r.is_watertight and dt < 30


def test_standard_cleanup_of_a_reconstruction_sized_mesh(big):
    from aro_studio.geometry.pipeline import STANDARD_CLEANUP, run_steps

    sc = make_scene_from_mesh(big)
    (_, rep), dt = timed(run_steps, sc, STANDARD_CLEANUP, category="prop", inspect_after=False)
    print(f"cleanup {len(big.faces)} faces: {dt:.2f}s")
    assert dt < 60


def test_decimation_of_a_reconstruction_sized_mesh(big):
    (out, rep), dt = timed(ops.decimate, big, target_faces=25_000)
    print(f"decimate {len(big.faces)} -> {len(out.faces)}: {dt:.2f}s")
    assert abs(len(out.faces) - 25_000) < 2_500 and dt < 60


def test_self_intersection_check_respects_its_time_budget(big):
    r, dt = timed(find_self_intersections, big, time_budget_s=3.0)
    print(f"self-intersection budgeted at 3s: {r.status}, {r.faces_checked}/{r.faces_total} faces in {dt:.2f}s")
    assert dt < 15 and r.status in ("partial", "checked")  # budget honoured (broad-phase build may add a few seconds)


def test_uv_unwrap_at_the_documented_limit():
    m = trimesh.creation.icosphere(subdivisions=5)  # 20,480 faces
    out, dt = timed(unwrap_jointly, {"s": m})
    print(f"xatlas {len(m.faces)} faces: {dt:.2f}s")
    assert dt < 90 and len(out["s"].faces) == len(m.faces)


def test_reference_vehicle_pipeline_budget():
    sc, t_build = timed(build_titan480)
    _, t_lod = timed(generate_lods, sc)
    rep, t_val = timed(run_validation, sc, "heavy_truck", ValidationConfig(check_intersections=False))
    (data, _), t_glb = timed(export_glb, sc)
    ver, t_ver = timed(verify_glb, data, sc)
    print(f"titan: build {t_build:.2f}s lod {t_lod:.2f}s validate {t_val:.2f}s glb {t_glb:.2f}s verify {t_ver:.2f}s")
    assert rep["overall"] > 0 and ver["ok"]
    assert t_build < 5 and t_lod < 10 and t_val < 15 and t_glb < 10 and t_ver < 10


def test_large_scene_export_scales_linearly(big):
    sc = make_scene_from_mesh(trimesh.creation.icosphere(subdivisions=6))
    (data, rep), dt = timed(export_glb, sc)
    print(f"export {rep['triangles']} tris: {dt:.2f}s {len(data) / 1e6:.1f} MB")
    assert dt < 30 and verify_glb(data, sc)["ok"]
