"""Production-design checks for the original ARO TITAN 480 hero vehicle."""

import numpy as np
import pytest

from aro_studio.animation.rig import build_rig
from aro_studio.geometry.inspect import inspect_mesh
from aro_studio.lod.generator import generate_lods
from aro_studio.vehicles.titan480 import AXLES, TIRE_R, build_titan480


def test_titan_hero_palette_and_reference_details_are_present():
    scene = build_titan480()
    materials = {material.name: material for material in scene.manifest.materials}
    parts = {part.name: part for part in scene.manifest.parts}

    assert {"aro_pearl_white", "aro_gold", "aro_black_paint"} <= set(materials)
    assert materials["aro_pearl_white"].base_color[0] >= 0.85
    assert materials["aro_pearl_white"].base_color[1] >= 0.85
    assert materials["aro_gold"].base_color[0] > materials["aro_gold"].base_color[2]
    assert materials["aro_gold"].metallic >= 0.8

    expected_parts = {
        "Cab_Fascia",
        "Grille",
        "ARO_Grille_Stroke_01",
        "ARO_Grille_Stroke_10",
        "Gold_Bumper_Trim",
        "Headlight_Bezel_L",
        "Headlight_Bezel_R",
        "Roof_Marker_1",
        "Roof_Marker_5",
        "Gold_Pinstripe_L",
        "Gold_Pinstripe_R",
        "Logo_Door_L_01",
        "Logo_Door_L_09",
        "Logo_Door_R_01",
        "Logo_Door_R_09",
        "Side_Step_L",
        "Side_Step_R",
        "Fender_Arch_Front_L",
        "Fender_Accent_Rear2_R",
    }
    assert expected_parts <= set(parts)

    for part in scene.manifest.parts:
        assert part.material in materials, part.name
        mesh = scene.meshes[part.name]
        assert len(mesh.faces) > 0, part.name
        assert np.isfinite(np.asarray(mesh.vertices)).all(), part.name
        assert mesh.is_watertight and mesh.volume > 0, part.name

    assert len(scene.manifest.vehicle.components["wheel"]) == 10
    assert len(scene.manifest.vehicle.components["wheel_detail"]) == 20
    assert all(len(w.detail_parts) == 2 for w in scene.manifest.vehicle.wheels)

    nonmanifold = {}
    for name, mesh in scene.meshes.items():
        report = inspect_mesh(mesh, check_intersections=False)
        if report.nonmanifold_edges:
            nonmanifold[name] = report.nonmanifold_edges
    assert not nonmanifold, nonmanifold


def test_titan_axle_layout_matches_provisional_3900_mm_wheelbase():
    scene = build_titan480()
    vehicle = scene.manifest.vehicle

    assert len(vehicle.axles) == 3
    assert vehicle.identity.drive_configuration == "6x4"
    assert AXLES == {"Axle_Front": 1.95, "Axle_Rear1": -1.30, "Axle_Rear2": -2.60}
    assert vehicle.wheelbase == pytest.approx(3.9, abs=1e-9)
    assert [axle.steering for axle in vehicle.axles] == [True, False, False]
    assert [axle.driven for axle in vehicle.axles] == [False, True, True]
    assert len(vehicle.wheels) == 10
    for wheel in vehicle.wheels:
        assert wheel.part in scene.meshes
        assert wheel.tire_part in scene.meshes
        assert all(detail in scene.meshes for detail in wheel.detail_parts)
        assert scene.meshes[wheel.tire_part].extents[1] / 2 == pytest.approx(TIRE_R, abs=0.01)


def test_wheel_details_follow_the_wheel_rig_and_survive_all_lods():
    scene = build_titan480()
    generate_lods(scene)
    build_rig(scene)

    for wheel in scene.manifest.vehicle.wheels:
        assert len(wheel.detail_parts) == 2
        for detail in wheel.detail_parts:
            assert scene.manifest.part(detail).parent == f"Spin_{wheel.name}"

    for lod_level in scene.manifest.lods:
        names = {part.name for part in lod_level.parts}
        assert all(detail in names for wheel in scene.manifest.vehicle.wheels for detail in wheel.detail_parts)


def test_windshield_is_offset_along_the_actual_cab_plane_normal():
    scene = build_titan480()
    glass = scene.meshes["Window_Windshield"]

    delta_z = 2.22 - 2.63
    delta_y = 3.55 - 2.35
    length = np.hypot(delta_z, delta_y)
    outward_normal = np.array([0.0, -delta_z, delta_y]) / length
    plane_midpoint = np.array([0.0, (2.35 + 3.55) / 2, (2.63 + 2.22) / 2])

    assert np.allclose(
        glass.centroid,
        plane_midpoint + outward_normal * 0.03,
        atol=1e-6,
    )

