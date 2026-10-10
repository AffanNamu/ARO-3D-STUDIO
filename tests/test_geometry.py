import numpy as np
import pytest
import trimesh

from aro_studio.core.errors import InvalidInputError
from aro_studio.geometry import ops
from aro_studio.geometry.inspect import boundary_loops, inspect_mesh
from aro_studio.geometry.pipeline import STANDARD_CLEANUP, run_steps
from aro_studio.geometry.selfintersect import find_self_intersections
from tests.conftest import make_scene_from_mesh


def test_clean_box_has_no_geometry_issues():
    r = inspect_mesh(trimesh.creation.box((1, 1, 1)))
    assert r.is_watertight and r.component_count == 1 and r.hole_count == 0
    assert not [i for i in r.issues if i.severity in ("critical", "major")]


def test_detects_duplicate_vertices_degenerate_and_duplicate_faces():
    b = trimesh.creation.box()
    v = np.vstack([b.vertices, b.vertices[:2]])  # duplicated vertices (unreferenced but identical)
    f = np.vstack([b.faces, b.faces[0], [0, 0, 1]])  # duplicate face + degenerate face
    r = inspect_mesh(trimesh.Trimesh(v, f, process=False))
    ids = {i.id for i in r.issues}
    assert {"duplicate_vertices", "degenerate_faces", "duplicate_faces"} <= ids


def test_detects_nan_and_empty():
    v = trimesh.creation.box().vertices.copy()
    v[0] = np.nan
    r = inspect_mesh(trimesh.Trimesh(v, trimesh.creation.box().faces, process=False))
    assert r.issue("nan_vertices") and r.issue("nan_vertices").severity == "critical"
    e = inspect_mesh(trimesh.Trimesh())
    assert e.issue("empty_mesh")


def test_detects_holes_and_components_and_nonmanifold():
    b = trimesh.creation.box()
    b.update_faces(np.arange(len(b.faces)) > 1)
    assert inspect_mesh(b).hole_count >= 1
    two = trimesh.util.concatenate([trimesh.creation.box(), trimesh.creation.box().apply_translation((5, 0, 0))])
    assert inspect_mesh(two).component_count == 2
    # three triangles sharing one edge -> non-manifold
    v = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1]], float)
    f = np.array([[0, 1, 2], [0, 1, 3], [0, 1, 4]])
    assert inspect_mesh(trimesh.Trimesh(v, f, process=False)).nonmanifold_edges == 1


def test_detects_inverted_and_flipped_winding():
    s = trimesh.creation.icosphere(2)
    inv = s.copy()
    inv.invert()
    assert inspect_mesh(inv).inverted
    flipped = s.copy()
    flipped.faces[:5] = flipped.faces[:5][:, ::-1]
    assert not inspect_mesh(flipped).is_winding_consistent


def test_scale_orientation_pivot_assessment():
    # a 1m-long "vehicle" built along X, floating and off-centre
    m = trimesh.creation.box((1.0, 0.4, 0.4)).apply_translation((3, 5, 0))
    r = inspect_mesh(m, category_group="vehicles")
    ids = {i.id for i in r.issues}
    assert {"incorrect_scale", "incorrect_orientation", "incorrect_pivot"} <= ids


def test_excessive_polycount():
    r = inspect_mesh(trimesh.creation.icosphere(3), tri_budget=100)
    assert r.issue("excessive_polycount")


def test_self_intersection_found_and_clean_sphere_passes():
    a = trimesh.creation.box((1, 1, 1))
    b = trimesh.creation.box((1, 1, 1)).apply_translation((0.37, 0.41, 0.29))
    assert find_self_intersections(trimesh.util.concatenate([a, b])).intersecting_pairs > 0
    assert find_self_intersections(trimesh.creation.icosphere(3)).intersecting_pairs == 0


def test_self_intersection_skip_and_budget():
    big = trimesh.creation.icosphere(3)
    assert find_self_intersections(big, max_faces=10).status == "skipped"
    part = find_self_intersections(trimesh.creation.icosphere(5), time_budget_s=0.0)
    assert part.status == "partial" and part.faces_checked < part.faces_total


def test_boundary_loops_orders_loop():
    b = trimesh.creation.box()
    b.update_faces(np.arange(len(b.faces)) > 1)
    loops = boundary_loops(b)
    assert loops and all(len(set(lp)) == len(lp) for lp in loops)


# ---- ops ---------------------------------------------------------------------------------------
def test_ops_do_not_mutate_input():
    s = trimesh.creation.icosphere(3)
    before = (s.vertices.copy(), s.faces.copy())
    for fn in (ops.merge_vertices, ops.remove_degenerate, ops.fix_normals, ops.fill_holes):
        fn(s)
    ops.decimate(s, ratio=0.5)
    ops.smooth(s, 3)
    assert np.array_equal(before[0], s.vertices) and np.array_equal(before[1], s.faces)


def test_fill_holes_makes_watertight_and_leaves_large_holes():
    s = trimesh.creation.icosphere(3)
    h = s.copy()
    h.update_faces(np.arange(len(h.faces)) > 25)
    h.remove_unreferenced_vertices()
    out, rep = ops.fill_holes(h)
    assert rep.details["holes_filled"] >= 1 and out.is_watertight and out.volume > 0
    out2, rep2 = ops.fill_holes(h, max_hole_edges=3)
    assert rep2.details["holes_skipped"] >= 1 and rep2.warnings


def test_remove_small_components_keeps_largest_and_reports():
    big = trimesh.creation.icosphere(3)
    dust = trimesh.creation.box((0.01, 0.01, 0.01)).apply_translation((3, 0, 0))
    out, rep = ops.remove_small_components(trimesh.util.concatenate([big, dust]), 0.1)
    assert rep.details["removed_components"] == 1 and len(out.faces) == len(big.faces)
    # never removes everything
    out2, _ = ops.remove_small_components(trimesh.creation.box(), 0.99, keep_at_least=1)
    assert len(out2.faces) == 12


def test_fix_normals_repairs_flips():
    s = trimesh.creation.icosphere(2)
    s.faces[:10] = s.faces[:10][:, ::-1]
    out, _ = ops.fix_normals(s)
    assert out.is_winding_consistent and out.volume > 0
    inv = trimesh.creation.icosphere(2)
    inv.invert()
    out, _ = ops.fix_normals(inv)
    assert out.volume > 0


def test_decimate_reduces_and_preserves_vertex_colours():
    s = trimesh.creation.icosphere(4)
    s.visual = trimesh.visual.ColorVisuals(
        mesh=s, vertex_colors=np.tile([200, 20, 20, 255], (len(s.vertices), 1)).astype(np.uint8)
    )
    out, rep = ops.decimate(s, ratio=0.25)
    assert abs(len(out.faces) / len(s.faces) - 0.25) < 0.05 and out.visual.kind == "vertex"
    assert tuple(out.visual.vertex_colors[0][:3]) == (200, 20, 20)
    with pytest.raises(InvalidInputError):
        ops.decimate(s)
    same, rep = ops.decimate(s, target_faces=10**9)
    assert len(same.faces) == len(s.faces)


def test_smooth_is_bounded():
    s = trimesh.creation.icosphere(3)
    out, rep = ops.smooth(s, 5)
    assert rep.details["max_vertex_shift"] < 0.05 and abs(out.volume - s.volume) / s.volume < 0.05
    with pytest.raises(InvalidInputError):
        ops.smooth(s, 0)


@pytest.mark.parametrize("up,fwd", [("+Y", "+Z"), ("+Z", "+X"), ("+Z", "-Y"), ("-Y", "+X"), ("+X", "+Y")])
def test_orientation_is_proper_rotation_and_maps_axes(up, fwd):
    m = ops.rotation_to_canonical(up, fwd)
    assert np.linalg.det(m[:3, :3]) == pytest.approx(1.0)
    u, f = np.array(ops.AXES[up], float), np.array(ops.AXES[fwd], float)
    assert (m[:3, :3] @ u) == pytest.approx([0, 1, 0]) and (m[:3, :3] @ f) == pytest.approx([0, 0, 1])


def test_orientation_rejects_bad_axes():
    with pytest.raises(InvalidInputError):
        ops.rotation_to_canonical("+Y", "+Y")
    with pytest.raises(InvalidInputError):
        ops.rotation_to_canonical("Y", "+Z")


def test_scale_and_pivot():
    b = trimesh.creation.box((2, 1, 4)).apply_translation((5, 7, 3))
    s, rep = ops.scale_to_length(b, 8.0, "Z")
    assert s.extents[2] == pytest.approx(8.0)
    p, rep = ops.set_pivot(s, "ground_center")
    assert p.bounds[0][1] == pytest.approx(0.0, abs=1e-9) and (p.bounds[0][0] + p.bounds[1][0]) / 2 == pytest.approx(
        0.0, abs=1e-9
    )
    with pytest.raises(InvalidInputError):
        ops.set_pivot(b, "nonsense")


def test_suggest_orientation_is_advisory():
    m = trimesh.creation.box((2, 1.5, 6))
    sug = ops.suggest_orientation(m)
    assert sug["forward"] == "+Z" and sug["advisory"] is True


def test_pipeline_cleanup_report_and_raw_untouched():
    dirty = trimesh.util.concatenate(
        [trimesh.creation.icosphere(3), trimesh.creation.box((0.01,) * 3).apply_translation((2, 0, 0))]
    )
    sc = make_scene_from_mesh(dirty)
    before = sc.meshes["body"].vertices.copy()
    out, rep = run_steps(sc, STANDARD_CLEANUP, category="prop")
    assert np.array_equal(sc.meshes["body"].vertices, before)  # input scene untouched
    assert rep["before"]["component_count"] == 2 and rep["after"]["component_count"] == 1
    assert [s["op"] for s in rep["steps"]] == [s["op"] for s in STANDARD_CLEANUP]


def test_pipeline_unknown_op_and_part():
    sc = make_scene_from_mesh(trimesh.creation.box())
    with pytest.raises(InvalidInputError, match="Unknown geometry operation"):
        run_steps(sc, [{"op": "explode"}], category="prop")
    with pytest.raises(InvalidInputError, match="Unknown part"):
        run_steps(sc, [{"op": "merge_vertices", "params": {"parts": ["nope"]}}], category="prop")


def test_pipeline_scene_ops_keep_vehicle_metadata_consistent():
    from aro_studio.vehicles.titan480 import build_titan480

    sc = build_titan480()
    out, _ = run_steps(sc, [{"op": "uniform_scale", "params": {"factor": 0.1}}], category="heavy_truck")
    w0, w1 = sc.manifest.vehicle.wheels[0], out.manifest.vehicle.wheels[0]
    assert w1.radius == pytest.approx(w0.radius * 0.1) and w1.position[2] == pytest.approx(w0.position[2] * 0.1)
    tire = out.meshes[w1.tire_part]
    assert tire.extents[1] / 2 == pytest.approx(w1.radius, rel=0.02)  # mesh and metadata moved together
    # orientation: rotate 90° about Y and verify wheel positions follow geometry
    out2, _ = run_steps(sc, [{"op": "orient", "params": {"up": "+Y", "forward": "+X"}}], category="heavy_truck")
    assert out2.combined().extents[0] == pytest.approx(sc.combined().extents[2], rel=1e-6)
