import io
import json
import os
import shutil
import struct
import zipfile
from pathlib import Path

import pygltflib
import pytest
import trimesh

from aro_studio.animation.rig import build_rig
from aro_studio.collision.generate import generate_collision
from aro_studio.export.gltf import ExportOptions, export_glb, export_gltf
from aro_studio.export.obj import export_obj
from aro_studio.export.unity import build_unity_package
from aro_studio.export.verify import khronos_validate, verify_glb, verify_unity_package
from aro_studio.lod.generator import generate_lods
from aro_studio.validation.engine import RULES, ValidationConfig, run_validation
from aro_studio.vehicles.titan480 import build_titan480
from tests.conftest import make_scene_from_mesh


@pytest.fixture(scope="module")
def full():
    s = build_titan480()
    generate_collision(s)
    generate_lods(s)
    build_rig(s)
    return s


@pytest.fixture(scope="module")
def glb(full):
    return export_glb(full)[0]


# ---- glTF / GLB -------------------------------------------------------------------------------------
def test_glb_verifies_and_reloads_in_independent_loader(full, glb):
    r = verify_glb(glb, full)
    assert r["ok"], [c for c in r["checks"] if not c["ok"]]
    sc = trimesh.load(io.BytesIO(glb), file_type="glb")
    # independent parser sees all LODs' meshes: 60 + 54 + 54(LOD2 minus dropped… ) etc; at least the LOD0 parts
    assert len(sc.geometry) >= 60 + len(full.manifest.colliders)


def test_glb_structure_and_metadata(full, glb, tmp_path):
    f = tmp_path / "t.glb"
    f.write_bytes(glb)
    gl = pygltflib.GLTF2().load(str(f))
    names = [n.name for n in gl.nodes]
    assert len(names) == len(set(names))
    assert "COL_Body" in names and "Collision" in names and "Wheel_F_L_LOD0" in names and "Wheel_F_L_LOD3" in names
    root = gl.nodes[gl.scenes[0].nodes[0]]
    meta = root.extras["aro_studio"]
    assert meta["units"] == "m" and meta["up_axis"] == "+Y" and meta["forward_axis"] == "+Z"
    assert (
        meta["vehicle"]["identity"]["model"] == "TITAN 480" and meta["provenance"]["source"] == "procedural_reference"
    )
    assert len(meta["lods"]) == 4
    spin = next(n for n in gl.nodes if n.name == "Spin_Wheel_F_L")
    assert spin.extras["aro_rig"]["role"] == "wheel_spin" and spin.extras["aro_rig"]["axis"] == [1.0, 0.0, 0.0]


def test_glb_pivots_round_trip_world_positions(full, glb, tmp_path):
    """Local transforms + rebased vertices must reproduce the original world-space geometry."""
    sc = trimesh.load(io.BytesIO(glb), file_type="glb")
    node = "Wheel_F_L_LOD0"
    geom_name = sc.graph[node][1]
    world = sc.geometry[geom_name].copy()
    world.apply_transform(sc.graph[node][0])
    orig = full.meshes["Wheel_F_L"]
    assert world.bounds == pytest.approx(orig.bounds, abs=1e-4)


def test_lod_visibility_is_per_node_and_counts_match(full, glb, tmp_path):
    gl = pygltflib.GLTF2()
    f = tmp_path / "_t.glb"
    f.write_bytes(glb)
    gl = gl.load(str(f))
    counts = {}
    for n in gl.nodes:
        if n.mesh is not None and "_LOD" in n.name and not n.name.startswith("COL_"):
            lv = n.name.rsplit("_LOD", 1)[1]
            counts[lv] = counts.get(lv, 0) + gl.accessors[gl.meshes[n.mesh].primitives[0].indices].count // 3
    assert counts["0"] == full.triangle_count and counts["1"] > counts["2"] > counts["3"]


def test_verifier_catches_corruption(full, glb, tmp_path):
    assert not verify_glb(glb[:200], full)["ok"]
    assert not verify_glb(b"notglb" + glb, full)["ok"]
    # wrong scene triangle counts
    other = full.copy()
    other.meshes["Grille"] = trimesh.creation.icosphere(3)
    assert not verify_glb(glb, other)["ok"]
    # corrupt the BIN chunk (flip bytes in accessor data → NaN positions)
    bad = bytearray(glb)
    jl = struct.unpack("<I", bad[12:16])[0]
    start = 20 + jl + 8
    for i in range(start, start + 4000):
        bad[i] = 0xFF
    r = verify_glb(bytes(bad), full)
    assert not r["ok"] and any(not c["ok"] for c in r["checks"] if c["id"].startswith(("geometry", "lod")))


def test_gltf_separate_files(full, tmp_path):
    js, files, rep = export_gltf(full.copy(), ExportOptions(bin_name="m.bin"))
    d = tmp_path / "g"
    d.mkdir()
    (d / "m.gltf").write_text(js)
    for rel, b in files.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_bytes(b)
    gl = pygltflib.GLTF2().load(str(d / "m.gltf"))
    assert gl.buffers[0].uri == "m.bin" and (d / "m.bin").stat().st_size == gl.buffers[0].byteLength
    assert rep["triangles"]["LOD0"] == full.triangle_count


def test_materials_pbr_mapping(full, glb, tmp_path):
    f = tmp_path / "m.glb"
    f.write_bytes(glb)
    gl = pygltflib.GLTF2().load(str(f))
    mats = {m.name: m for m in gl.materials}
    assert mats["glass"].alphaMode == "BLEND" and mats["chrome"].pbrMetallicRoughness.metallicFactor == 1.0
    assert mats["taillight"].extensions["KHR_materials_emissive_strength"]["emissiveStrength"] == 1.5
    assert mats["body_paint"].pbrMetallicRoughness.baseColorFactor[0] == pytest.approx(0.86)
    assert "KHR_materials_emissive_strength" in gl.extensionsUsed


def test_textured_export_embeds_and_packs_orm(tmp_path):
    from PIL import Image

    from aro_studio.scene.model import TextureDef
    from aro_studio.textures.process import encode

    sc = make_scene_from_mesh(trimesh.creation.icosphere(2), "ball", "prop")
    from aro_studio.textures.uv import unwrap_jointly

    sc.meshes["ball"] = unwrap_jointly({"b": sc.meshes["ball"]})["b"]
    for name, ch, col in (
        ("bc", "base_color", (200, 30, 30)),
        ("rg", "roughness", (120,) * 3),
        ("mt", "metallic", (255,) * 3),
    ):
        data = encode(Image.new("RGB", (64, 64), col))
        sc.manifest.textures.append(
            TextureDef(name=name, file=f"textures/{name}.png", width=64, height=64, sha256="0" * 64, channel=ch)
        )
        sc.texture_data[f"textures/{name}.png"] = data
    sc.manifest.materials[0].textures = {"base_color": "bc", "roughness": "rg", "metallic": "mt"}
    data, rep = export_glb(sc)
    assert verify_glb(data, sc)["ok"]
    f = tmp_path / "t.glb"
    f.write_bytes(data)
    gl = pygltflib.GLTF2().load(str(f))
    m = gl.materials[0].pbrMetallicRoughness
    assert m.baseColorTexture is not None and m.metallicRoughnessTexture is not None and len(gl.images) == 2
    prim = gl.meshes[0].primitives[0]
    assert prim.attributes.TEXCOORD_0 is not None and prim.attributes.COLOR_0 is None  # no double-applied vertex colour


def test_vertex_colours_exported_when_untextured(tmp_path):
    import numpy as np

    s = trimesh.creation.icosphere(2)
    s.visual = trimesh.visual.ColorVisuals(
        mesh=s, vertex_colors=np.tile([10, 200, 10, 255], (len(s.vertices), 1)).astype(np.uint8)
    )
    sc = make_scene_from_mesh(s, "ball", "prop")
    data, _ = export_glb(sc)
    assert verify_glb(data, sc)["ok"]
    f = tmp_path / "_vc.glb"
    f.write_bytes(data)
    gl = pygltflib.GLTF2().load(str(f))
    prim = gl.meshes[0].primitives[0]
    assert prim.attributes.COLOR_0 is not None
    acc = gl.accessors[prim.attributes.COLOR_0]
    assert acc.componentType == pygltflib.UNSIGNED_BYTE and acc.normalized and acc.type == "VEC4"


@pytest.mark.skipif(
    not shutil.which("node") or not os.environ.get("ARO_GLTF_VALIDATOR_NODE_PATH"),
    reason="needs Node + npm gltf-validator (ARO_GLTF_VALIDATOR_NODE_PATH)",
)
def test_khronos_validator_reports_no_errors_or_warnings(glb, tmp_path):
    f = tmp_path / "k.glb"
    f.write_bytes(glb)
    r = khronos_validate(f)
    assert r["ran"], r
    assert r["errors"] == 0 and r["warnings"] == 0, r["messages"]


def test_khronos_validator_unavailable_is_reported_not_passed(monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "which", lambda _: None)
    r = khronos_validate(tmp_path / "x.glb")
    assert r["ran"] is False and "Node" in r["reason"]


# ---- OBJ ---------------------------------------------------------------------------------------------
def test_obj_roundtrip(full):
    o, mtl, files, rep = export_obj(full)
    back = trimesh.load(io.StringIO(o), file_type="obj", split_object=True, group_material=False)
    assert sum(len(m.faces) for m in back.geometry.values()) == rep["triangles"] == full.triangle_count
    assert "newmtl body_paint" in mtl and "Pm " in mtl
    o3, _, _, rep3 = export_obj(full, level=3)
    assert rep3["triangles"] < rep["triangles"] and o3.count("\no ") + 1 >= 1


# ---- Unity package ---------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def pkg(full, tmp_path_factory):
    out = tmp_path_factory.mktemp("unity")
    z, rep = build_unity_package(
        full,
        out,
        asset_id="ast_" + "0" * 20,
        version_id="ver_" + "0" * 20,
        version_label="v0.9",
        stage="final",
        validation_summary={"status": "PRODUCTION_READY", "overall": 99.0},
    )
    return z, Path(rep["package_dir"]), rep


def test_unity_package_structure(pkg, full):
    z, root, rep = pkg
    for d in ("Models", "Materials", "Textures", "LOD", "Collision", "Metadata", "Editor", "Scripts"):
        assert (root / d).is_dir()
    assert (root / "README.md").is_file() and (root / "Models" / "ARO-TITAN-480.glb").is_file()
    assert sorted(p.name for p in (root / "LOD").glob("*.glb")) == [f"ARO-TITAN-480_LOD{i}.glb" for i in range(4)]
    assert (root / "Collision" / "colliders.json").is_file() and (
        root / "Collision" / "ARO-TITAN-480_collision.glb"
    ).is_file()
    assert zipfile.ZipFile(z).testzip() is None


def test_unity_package_verifies_and_detects_tampering(pkg, full):
    z, root, rep = pkg
    assert verify_unity_package(root, full)["ok"]
    import shutil as sh

    copy = root.parent / "copy"
    sh.copytree(root, copy)
    (copy / "Metadata" / "vehicle.json").write_text("{}")
    r = verify_unity_package(copy, full)
    assert not r["ok"] and any(c["id"] == "checksums" and not c["ok"] for c in r["checks"])


def test_unity_metadata_is_honest_about_import_status(pkg):
    _, root, _ = pkg
    meta = json.loads((root / "Metadata" / "asset.json").read_text())
    assert meta["unity_import_verified"] is False
    assert meta["conventions"]["forward"] == "+Z" and meta["provenance"]["source"] == "procedural_reference"
    readme = (root / "README.md").read_text()
    assert "did **not** import it into Unity" in readme and "glTFast" in readme and "UNTESTED" in readme.upper()
    veh = json.loads((root / "Metadata" / "vehicle.json").read_text())
    assert len(veh["wheels"]) == 10 and veh["identity"]["drive_configuration"] == "6x4"
    lods = json.loads((root / "Metadata" / "lods.json").read_text())["levels"]
    assert [x["level"] for x in lods] == [0, 1, 2, 3] and lods[1]["screenHeight"] > lods[2]["screenHeight"] > lods[3][
        "screenHeight"
    ]
    mats = json.loads((root / "Materials" / "materials.json").read_text())["materials"]
    assert next(m for m in mats if m["name"] == "glass")["unity"]["surface"] == "Transparent"
    cs = (root / "Editor" / "AroAssetImporter.cs").read_text()
    assert "LODGroup" in cs and "FlipX" in cs and "UNTESTED" in cs


# ---- validation --------------------------------------------------------------------------------------------
def report(scene, cat="heavy_truck", **cfg):
    cfg.setdefault("check_intersections", False)  # covered by test_geometry; keeps rule tests fast
    return run_validation(scene, cat, ValidationConfig(**cfg))


def status(rep, rid):
    return next(c["status"] for c in rep["checks"] if c["id"] == rid)


def test_reference_vehicle_is_production_ready_with_no_blockers(full):
    r = report(full)
    assert (
        r["status"] == "PRODUCTION_READY"
        and r["critical_failures"] == 0
        and r["major_failures"] == 0
        and r["overall"] >= 90
    )
    assert set(r["categories"]) == {"geometry", "materials", "textures", "lod", "collision", "vehicle", "unity"}
    assert r["categories"]["textures"]["applicable"] is False  # flat-colour asset: not scored, not faked as 100%
    assert len(r["checks"]) == len(RULES)


@pytest.mark.parametrize(
    "mutate,rule",
    [
        (lambda s: setattr(s.manifest.vehicle, "wheels", []), "V002"),
        (lambda s: setattr(s.manifest.vehicle, "axles", []), "V003"),
        (lambda s: (setattr(s.manifest, "colliders", []), s.collision_meshes.clear()), "C001"),
        (lambda s: [m.apply_scale(100) for m in s.meshes.values()], "U001"),
        (lambda s: setattr(s.manifest, "materials", []), "M001"),
        (lambda s: setattr(s.manifest, "lods", []), "L002"),
    ],
)
def test_critical_or_blocking_failure_prevents_production_ready_even_with_high_score(full, mutate, rule):
    s = full.copy()
    mutate(s)
    r = report(s)
    assert status(r, rule) == "failed"
    assert r["status"] != "PRODUCTION_READY"
    assert r["overall"] > 70  # the score is high, yet the asset is NOT ready: scores never override failures
    assert r["score_never_overrides_critical"] and r["blocking_reasons"]


def test_critical_failures_block_even_at_100_percent_other_categories(full):
    s = full.copy()
    s.manifest.vehicle.wheels = []
    r = report(s)
    assert r["critical_failures"] >= 1 and r["status"] == "NEEDS_REVIEW"
    assert max(c["score"] for c in r["categories"].values() if c["score"] is not None) == 100.0


def test_orientation_and_pivot_rules(full):
    s = full.copy()
    from aro_studio.geometry.pipeline import run_steps

    rot, _ = run_steps(full, [{"op": "orient", "params": {"up": "+Y", "forward": "+X"}}], category="heavy_truck")
    assert status(report(rot), "U002") == "failed"
    moved = full.copy()
    for m in moved.meshes.values():
        m.apply_translation((0, 2, 0))
    assert status(report(moved), "U006") == "failed"
    assert status(report(s), "U002") == "passed"


def test_geometry_rules_detect_real_defects(full):
    s = full.copy()
    s.meshes["Grille"].faces[:5] = s.meshes["Grille"].faces[:5][:, ::-1]
    assert status(report(s, check_intersections=False), "G005") == "failed"
    s2 = full.copy()
    v = s2.meshes["Grille"].vertices.copy()
    v[0] = float("nan")
    s2.meshes["Grille"] = trimesh.Trimesh(v, s2.meshes["Grille"].faces, process=False)
    r = report(s2, check_intersections=False)
    assert status(r, "G002") == "failed" and r["status"] == "FAILED"
    s3 = full.copy()
    assert status(report(s3, tri_budget_lod0=1000), "G006") == "failed"


def test_lod_rules(full):
    s = full.copy()
    s.manifest.lods[1].triangle_count = s.manifest.lods[0].triangle_count  # LOD2 not smaller than LOD1
    assert status(report(s), "L005") == "failed"
    s2 = full.copy()
    s2.manifest.lods = s2.manifest.lods[:2]
    r = report(s2)
    assert (
        status(r, "L002") == "passed" and status(r, "L003") == "passed" and status(r, "L004") == "failed"
    )  # LOD3 missing


def test_vehicle_rules(full):
    s = full.copy()
    s.manifest.vehicle.wheels[0].position = (1.0, 0.9, 1.9)
    assert status(report(s), "V006") == "failed"
    s = full.copy()
    s.manifest.vehicle.center_of_mass = (0, 9, 0)
    assert status(report(s), "V008") == "failed"
    s = full.copy()
    s.manifest.vehicle.attachment_points = [a for a in s.manifest.vehicle.attachment_points if a.kind != "fifth_wheel"]
    assert status(report(s), "V009") == "failed"
    s = full.copy()
    s.manifest.vehicle.pivots = []
    assert status(report(s), "V005") == "failed"
    s = full.copy()
    s.manifest.vehicle.identity.drive_configuration = "8x4"
    assert status(report(s), "V002") == "failed"  # 8x4 needs 4 axles


def test_texture_rules_when_present():
    from PIL import Image

    from aro_studio.scene.model import TextureDef
    from aro_studio.textures.process import encode

    sc = make_scene_from_mesh(trimesh.creation.icosphere(2), "ball", "prop")
    data = encode(Image.new("RGB", (100, 100)))  # not power of two
    sc.manifest.textures.append(TextureDef(name="t", file="textures/t.png", width=100, height=100, sha256="0" * 64))
    sc.texture_data["textures/t.png"] = data
    sc.manifest.materials[0].textures = {"base_color": "t"}
    r = report(sc, "prop")
    assert status(r, "T004") == "failed" and status(r, "T005") == "failed"  # NPOT and no UVs
    sc.manifest.materials[0].textures = {"base_color": "ghost"}
    assert status(report(sc, "prop"), "T002") == "failed"
    sc.texture_data.clear()
    assert status(report(sc, "prop"), "T001") == "failed"


def test_non_vehicle_asset_skips_vehicle_rules():
    sc = make_scene_from_mesh(trimesh.creation.icosphere(3), "ball", "prop")
    generate_collision(sc, kind="convex_hull")
    r = report(sc, "prop")
    assert status(r, "V002") == "not_applicable" and r["categories"]["vehicle"]["applicable"] is False
    assert status(r, "C001") == "passed"


def test_crashing_rule_becomes_failed_check_not_crash(monkeypatch, full):
    from aro_studio.validation import engine

    monkeypatch.setattr(engine, "_parts_inspected", lambda ctx: (_ for _ in ()).throw(RuntimeError("boom")))
    r = report(full)
    assert status(r, "G003") == "failed" and "boom" in next(c["message"] for c in r["checks"] if c["id"] == "G003")


def test_unity_expectations_match_the_exported_glb_and_ship_with_the_verifier(pkg, full):
    """The expectations the Unity verifier compares against must agree with what is actually in the shipped GLB."""
    import numpy as np
    import trimesh

    _, root, _ = pkg
    exp = json.loads((root / "Metadata" / "unity_expectations.json").read_text())
    assert (root / "Editor" / "AroUnityVerifier.cs").is_file()
    assert "unity_expectations.json" in (root / "Metadata" / "checksums.sha256").read_text()
    scene = trimesh.load(root / "Models" / "ARO-TITAN-480.glb", force="scene")
    lod0 = [g for n, g in scene.geometry.items() if n.endswith("_LOD0") or "_LOD" not in n]
    assert lod0
    verts = np.concatenate(
        [
            trimesh.transform_points(g.vertices, scene.graph.get(nn)[0])
            for nn in scene.graph.nodes_geometry
            for g in [scene.geometry[scene.graph[nn][1]]]
            if "_LOD" not in scene.graph[nn][1] or scene.graph[nn][1].endswith("_LOD0")
        ]
    )
    assert np.allclose(verts.min(0), exp["boundsMin"], atol=0.01) and np.allclose(
        verts.max(0), exp["boundsMax"], atol=0.01
    )
    assert exp["lodTriangles"]["0"] == exp["triangles_lod0"] and sorted(exp["lodTriangles"]) == ["0", "1", "2", "3"]
    assert (
        {p["node"] for p in exp["parts"]}
        and exp["colliders"]
        and "boundsMin" in next(c for c in exp["colliders"] if c["kind"] in ("convex_hull", "vehicle_mesh"))
    )


def test_an_assumed_size_can_never_be_production_ready(full):
    """Real runs: a chair/teapot/robot scaled to a 1 m placeholder was labelled PRODUCTION_READY (99.6 %)."""
    assumed = report(full, size_confirmed=False)
    assert status(assumed, "U008") == "failed"
    assert assumed["status"] == "NEEDS_REVIEW" and assumed["major_failures"] >= 1
    assert any("U008" in r for r in assumed["blocking_reasons"])
    assert status(report(full, size_confirmed=True), "U008") == "passed"
    unset = report(full)  # authored assets make no claim either way
    assert status(unset, "U008") == "not_applicable" and unset["status"] == "PRODUCTION_READY"
