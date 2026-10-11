import json

import numpy as np
import pytest
import trimesh

from aro_studio.animation.rig import ROOT, build_rig
from aro_studio.collision.generate import MAX_CONVEX_TRIANGLES, generate_collision
from aro_studio.core.errors import InvalidInputError
from aro_studio.lod.generator import LodConfig, LodLevelConfig, generate_lods
from aro_studio.materials.library import assign_material, check_pbr, make_material
from aro_studio.scene.model import MaterialDef
from aro_studio.scene.store import load_scene, save_scene
from aro_studio.scene.transform import transform_scene
from aro_studio.vehicles.assemble import configure_vehicle
from aro_studio.vehicles.titan480 import AXLES, TIRE_R, build_titan480
from tests.conftest import make_scene_from_mesh


@pytest.fixture(scope="module")
def titan():
    return build_titan480()


@pytest.fixture
def full(titan):
    s = titan.copy()
    generate_collision(s)
    generate_lods(s)
    build_rig(s)
    return s


# ---- reference asset ---------------------------------------------------------------------------
def test_titan_identity_is_original_and_labelled_procedural(titan):
    v = titan.manifest.vehicle
    assert (v.identity.manufacturer, v.identity.model, v.identity.drive_configuration, v.identity.body_type) == (
        "ARO Motors",
        "TITAN 480",
        "6x4",
        "tractor_unit",
    )
    prov = titan.manifest.provenance
    assert prov.source == "procedural_reference" and "Not AI" in prov.note and prov.engine_id is None


def test_titan_geometry_is_sound_and_correctly_scaled(titan):
    ext = titan.combined().extents
    assert 6.0 < ext[2] < 7.5 and 3.0 < ext[0] < 3.6 and 3.5 < ext[1] < 4.2  # a real tractor unit, in metres
    assert all(m.is_watertight and m.volume > 0 for m in titan.meshes.values())
    assert titan.combined().bounds[0][1] == pytest.approx(0.0, abs=1e-6)  # on the ground


def test_titan_6x4_layout(titan):
    v = titan.manifest.vehicle
    assert len(v.axles) == 3 and len(v.wheels) == 10
    assert [a.steering for a in v.axles] == [True, False, False] and [a.driven for a in v.axles] == [False, True, True]
    assert v.wheelbase == pytest.approx(AXLES["Axle_Front"] - (AXLES["Axle_Rear1"] + AXLES["Axle_Rear2"]) / 2)
    for w in v.wheels:
        assert w.position[1] == pytest.approx(TIRE_R)
        tire = titan.meshes[w.tire_part]
        assert tire.extents[1] / 2 == pytest.approx(w.radius, abs=0.01)
        assert np.allclose(
            tire.bounds.mean(axis=0), w.position, atol=0.02
        )  # tyre mesh is centred on its declared position


def test_every_vehicle_part_has_component_and_material(titan):
    roles = {
        "chassis",
        "cabin",
        "body",
        "bumper",
        "grille",
        "door",
        "window",
        "mirror",
        "headlight",
        "taillight",
        "exhaust",
        "axle",
        "wheel",
        "tire",
        "attachment",
    }
    assert roles <= {p.component for p in titan.manifest.parts}
    assert all(p.material for p in titan.manifest.parts)
    assert titan.manifest.vehicle.components["tire"] and len(titan.manifest.vehicle.components["wheel"]) == 10


# ---- collision -----------------------------------------------------------------------------------
def test_collision_separate_and_optimised(full):
    cols = {c.name: c for c in full.manifest.colliders}
    assert {"COL_Body", "COL_Cabin"} <= set(cols)
    for c in cols.values():
        assert 4 <= c.triangle_count <= MAX_CONVEX_TRIANGLES
    assert not any(p.name.startswith("COL_") for p in full.manifest.parts)  # not mixed into visuals
    for name, m in full.collision_meshes.items():
        assert m.is_convex, name


def test_collision_body_approximates_chassis_within_tolerance(full):
    hull = full.collision_meshes["COL_Body"]
    chassis_meshes = [
        mesh for name, mesh in full.meshes.items() if name == "Chassis_Frame" or name.startswith("Chassis_Crossmember_")
    ]
    pts = np.vstack([mesh.vertices for mesh in chassis_meshes])
    _, dist, _ = trimesh.proximity.closest_point(hull, pts)
    inside = hull.contains(pts)
    assert np.where(inside, 0.0, dist).max() < 0.15  # simplified hull may clip corners, but only slightly
    assert inside.mean() > 0.6


def test_collision_reports_hull_fidelity():
    s = build_titan480()
    rep = generate_collision(s)
    f = rep["fidelity"]["COL_Body"]
    assert (
        0.8 < f["volume_ratio"] <= 1.0
        and f["max_corner_gap_m"] < 0.15
        and f["reduced_triangles"] <= MAX_CONVEX_TRIANGLES
    )


@pytest.mark.parametrize("kind", ["box", "sphere", "capsule", "convex_hull", "mesh"])
def test_generic_collider_kinds(kind):
    sc = make_scene_from_mesh(trimesh.creation.icosphere(3))
    generate_collision(sc, kind=kind)
    assert len(sc.manifest.colliders) == 1 and sc.manifest.colliders[0].kind.value == kind


def test_collision_rejects_unknown_kind_and_vehicle_without_metadata():
    sc = make_scene_from_mesh(trimesh.creation.box())
    with pytest.raises(InvalidInputError):
        generate_collision(sc, kind="vehicle")
    with pytest.raises(InvalidInputError):
        generate_collision(sc, kind="torus")


# ---- LOD -------------------------------------------------------------------------------------------
def test_lod_decreases_monotonically_and_hits_targets(titan):
    s = titan.copy()
    res = generate_lods(s)
    tri = [s.triangle_count] + [r.triangles for r in res]
    assert all(b < a * 0.9 for a, b in zip(tri, tri[1:], strict=False)), tri
    for r in res:
        assert r.achieved_ratio <= r.target_ratio * 1.5 + 0.02
    assert s.manifest.lod_levels == [0, 1, 2, 3]


def test_lod_keeps_wheels_at_every_level_and_merges_only_static(titan):
    s = titan.copy()
    generate_lods(s)
    for lod in s.manifest.lods:
        names = {p.name for p in lod.parts}
        assert all(w.part in names and w.tire_part in names for w in s.manifest.vehicle.wheels)
    l3 = next(x for x in s.manifest.lods if x.level == 3)
    assert any(p.name.startswith("Merged_") for p in l3.parts) and not any(
        p.name.startswith("Merged_") and p.component in ("wheel", "tire") for p in l3.parts
    )
    assert not {p.name for p in l3.parts} & {"Seat_Driver", "Wiper_L"}  # dropped roles


def test_lod_does_not_touch_lod0(titan):
    s = titan.copy()
    before = {k: v.vertices.copy() for k, v in s.meshes.items()}
    generate_lods(s)
    assert all(np.array_equal(before[k], s.meshes[k].vertices) for k in before)


def test_lod_config_validation():
    with pytest.raises(InvalidInputError):
        LodConfig(
            levels=[
                LodLevelConfig(level=1, ratio=0.5, screen_height=0.3),
                LodLevelConfig(level=2, ratio=0.6, screen_height=0.1),
            ]
        ).validate_monotonic()
    with pytest.raises(InvalidInputError):
        LodConfig(levels=[LodLevelConfig(level=2, ratio=0.5, screen_height=0.3)]).validate_monotonic()
    with pytest.raises(InvalidInputError):
        LodConfig(levels=[LodLevelConfig(level=1, ratio=0.5, screen_height=0.7)]).validate_monotonic()


def test_lod_custom_config():
    s = make_scene_from_mesh(trimesh.creation.icosphere(4))
    res = generate_lods(
        s,
        LodConfig(
            levels=[
                LodLevelConfig(level=1, ratio=0.5, screen_height=0.4),
                LodLevelConfig(level=2, ratio=0.1, screen_height=0.1),
            ]
        ),
    )
    assert len(res) == 2 and res[1].triangles < res[0].triangles < s.triangle_count


# ---- rig ---------------------------------------------------------------------------------------------
def test_rig_hierarchy_roles_and_pivots(full):
    nodes = {n.name: n for n in full.manifest.rig.nodes}
    assert nodes[ROOT].parent is None
    assert (
        sum(n.role == "wheel_spin" for n in nodes.values()) == 10
        and sum(n.role == "steering" for n in nodes.values()) == 2
    )
    assert nodes["Spin_Wheel_F_L"].parent == "Steer_Wheel_F_L" and nodes["Steer_Wheel_F_L"].parent == "Susp_Axle_Front"
    assert nodes["Spin_Wheel_R1_LI"].parent == "Susp_Axle_Rear1"  # rear wheels do not steer
    assert nodes["Spin_Wheel_F_L"].axis == (1.0, 0.0, 0.0)
    wheel_part = full.manifest.part("Wheel_F_L")
    assert wheel_part.parent == "Spin_Wheel_F_L" and wheel_part.pivot == nodes["Spin_Wheel_F_L"].pivot
    assert (
        full.manifest.part("Door_L").parent == "Hinge_Door_L"
        and full.manifest.part("Window_Door_L").parent == "Hinge_Door_L"
    )
    # every LOD part inherits hierarchy
    assert all(p.parent for lod in full.manifest.lods for p in lod.parts)


def test_door_limits_follow_right_hand_rule(full):
    nodes = {n.name: n for n in full.manifest.rig.nodes}
    # left door (+X side) opens with negative rotation about +Y: rotate its rear edge and check it moves outward (+X)
    a = np.radians(-60)
    rot = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    rear_edge = np.array([0, 0, -1.0])
    assert (rot @ rear_edge)[0] > 0
    lo, hi = nodes["Hinge_Door_L"].limits_deg
    assert lo < 0 == hi


def test_rig_requires_vehicle():
    with pytest.raises(InvalidInputError):
        build_rig(make_scene_from_mesh(trimesh.creation.box()))


# ---- scene transform / store ----------------------------------------------------------------------------
def test_transform_rotates_everything_consistently(full):
    m = np.eye(4)
    m[:3, :3] = trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0])[:3, :3]
    out = transform_scene(full, m)
    w0, w1 = full.manifest.vehicle.wheels[0], out.manifest.vehicle.wheels[0]
    assert np.allclose(m[:3, :3] @ np.array(w0.position), w1.position, atol=1e-9)
    assert np.allclose(out.meshes[w1.tire_part].bounds.mean(axis=0), w1.position, atol=0.02)
    c0 = full.manifest.colliders[0]
    assert c0.name == out.manifest.colliders[0].name
    assert out.collision_meshes["COL_Body"].bounds[1][0] == pytest.approx(
        full.collision_meshes["COL_Body"].bounds[1][2], abs=1e-6
    )


def test_transform_rejects_shear_and_oblique_rotation_with_colliders(full):
    shear = np.eye(4)
    shear[0, 1] = 0.5
    with pytest.raises(InvalidInputError):
        transform_scene(full, shear)
    ob = np.eye(4)
    ob[:3, :3] = trimesh.transformations.rotation_matrix(0.3, [0, 1, 0])[:3, :3]
    with pytest.raises(InvalidInputError, match="axis-aligned"):
        transform_scene(full, ob)


def test_store_roundtrip_is_lossless(full, tmp_path):
    save_scene(full.copy(), tmp_path / "v")
    back = load_scene(tmp_path / "v")
    assert back.triangle_count == full.triangle_count and back.manifest.lod_levels == [0, 1, 2, 3]
    assert set(back.collision_meshes) == set(full.collision_meshes)
    assert back.manifest.vehicle.model_dump() == full.manifest.vehicle.model_dump()
    assert back.manifest.rig.model_dump() == full.manifest.rig.model_dump()
    k = "Wheel_F_L"
    assert np.allclose(back.meshes[k].vertices, full.meshes[k].vertices, atol=1e-5)
    assert (tmp_path / "v" / "manifest.json").is_file()
    json.loads((tmp_path / "v" / "manifest.json").read_text())


def test_npz_loading_never_unpickles(tmp_path, titan):
    import numpy as _np

    save_scene(titan.copy(), tmp_path / "v")
    f = tmp_path / "v" / "parts" / "Grille.npz"
    f.chmod(0o644)
    _np.savez(f, vertices=_np.array([["x"]], dtype=object), faces=_np.zeros((1, 3)))  # object array needs pickle
    with pytest.raises(Exception):  # noqa: B017 - integrity check or allow_pickle=False must stop it
        load_scene(tmp_path / "v", verify=False)


# ---- materials -----------------------------------------------------------------------------------------
def test_pbr_checks():
    assert check_pbr(make_material("c", "chrome")) == []
    assert check_pbr(MaterialDef(name="g", category="glass", alpha_mode="OPAQUE"))
    assert check_pbr(MaterialDef(name="r", category="rubber", metallic=0.9))
    assert check_pbr(MaterialDef(name="l", category="lights"))
    with pytest.raises(ValueError):
        MaterialDef(name="x", metallic=1.5)
    with pytest.raises(ValueError):
        MaterialDef(name="x", textures={"bogus": "t"})


def test_assign_material_updates_lods_too(full):
    assign_material(full, "Grille", "chrome")
    assert full.manifest.part("Grille").material == "chrome"
    assert all(p.material == "chrome" for lod in full.manifest.lods for p in lod.parts if p.name == "Grille")
    with pytest.raises(InvalidInputError):
        assign_material(full, "Grille", "nope")
    with pytest.raises(InvalidInputError):
        assign_material(full, "Nope", "chrome")


def test_configure_vehicle_validates_references():
    sc = make_scene_from_mesh(trimesh.creation.box((2, 1.5, 6)))
    spec = {
        "identity": {"manufacturer": "ARO Motors", "brand": "ARO", "model": "X", "category": "heavy_truck"},
        "axles": [{"name": "A", "position": [0, 0.5, 1], "track_width": 2}],
        "wheels": [
            {"name": "W", "axle": "MISSING", "side": "left", "position": [1, 0.5, 1], "radius": 0.5, "width": 0.3}
        ],
    }
    with pytest.raises(InvalidInputError, match="unknown axle"):
        configure_vehicle(sc, spec)
    spec["wheels"][0]["axle"] = "A"
    spec["wheels"][0]["part"] = "ghost"
    with pytest.raises(InvalidInputError, match="unknown part"):
        configure_vehicle(sc, spec)
    spec["wheels"][0].pop("part")
    out = configure_vehicle(sc, spec, {"body": "chassis"})
    assert out["wheels"] == 1 and sc.manifest.part("body").component == "chassis"
    with pytest.raises(InvalidInputError):
        configure_vehicle(sc, {"identity": {}}, None)
    with pytest.raises(InvalidInputError, match="role"):
        configure_vehicle(sc, None, {"body": "spaceship"})
