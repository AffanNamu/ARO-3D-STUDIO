import json

import pytest
import trimesh

from aro_studio.core.enums import AssetStatus, Stage
from aro_studio.core.errors import ConflictError, ImmutableVersionError, InvalidInputError, NotFoundError
from aro_studio.scene.store import load_scene, save_scene
from tests.conftest import make_scene_from_mesh


def test_schema_migrates_idempotently(db):
    assert db.schema_version == 1
    db.migrate()
    assert db.schema_version == 1


def test_project_lifecycle(services):
    projects, assets = services
    p = projects.create("ARO TITAN 480", "reference vehicle")
    assert p["project_id"].startswith("prj_") and p["slug"] == "ARO-TITAN-480"
    assert projects.rename(p["project_id"], "ARO TITAN 480 v2")["name"] == "ARO TITAN 480 v2"
    projects.archive(p["project_id"])
    assert projects.get(p["project_id"])["status"] == "archived"
    projects.restore(p["project_id"])
    assert projects.get(p["project_id"])["status"] == "active"
    with pytest.raises(InvalidInputError):
        projects.create("   ")
    projects.delete(p["project_id"])
    with pytest.raises(NotFoundError):
        projects.get(p["project_id"])
    projects.restore(p["project_id"])  # soft delete is recoverable
    assert projects.get(p["project_id"])["status"] == "active"


def test_permanent_delete_requires_inactive(services, layout):
    projects, _ = services
    p = projects.create("X")
    with pytest.raises(ConflictError):
        projects.delete(p["project_id"], permanent=True)
    projects.archive(p["project_id"])
    projects.delete(p["project_id"], permanent=True)
    assert not layout.project_dir(p["project_id"]).exists()


def test_asset_category_rules(services):
    projects, assets = services
    p = projects.create("P")
    a = assets.create_asset(p["project_id"], "Titan", "heavy_truck", {"manufacturer": "ARO Motors", "model": "TITAN 480"})
    assert a["metadata"]["manufacturer"] == "ARO Motors" and a["status"] == "DRAFT"
    with pytest.raises(InvalidInputError):
        assets.create_asset(p["project_id"], "x", "nonexistent")
    with pytest.raises(InvalidInputError):
        assets.create_asset(p["project_id"], "x", "character")  # reserved for the future


def test_versions_are_immutable_and_raw_preserved(services, layout, box_scene):
    projects, assets = services
    p = projects.create("P")
    a = assets.create_asset(p["project_id"], "A", "prop")
    raw = assets.add_version(a["asset_id"], box_scene, stage=Stage.RAW, operation="import", description="raw")
    assert raw["number"] == 1 and raw["stage"] == "raw"
    # a derived version is a NEW version; the raw version's files must be byte-identical afterwards
    before = (assets.version_path(raw["version_id"]) / "manifest.json").read_bytes()
    s2 = assets.load_scene(raw["version_id"])
    s2.meshes["body"].apply_scale(2.0)
    v2 = assets.add_version(a["asset_id"], s2, stage=Stage.PROCESSED, operation="scale", parent_version_id=raw["version_id"])
    assert v2["number"] == 2 and v2["parent_version_id"] == raw["version_id"]
    assert (assets.version_path(raw["version_id"]) / "manifest.json").read_bytes() == before
    raw_scene = assets.load_scene(raw["version_id"])
    assert raw_scene.meshes["body"].extents[2] == pytest.approx(6.0, rel=1e-4)
    assert assets.load_scene(v2["version_id"]).meshes["body"].extents[2] == pytest.approx(12.0, rel=1e-4)


def test_version_dir_cannot_be_overwritten(tmp_path, box_scene):
    d = tmp_path / "v"
    save_scene(box_scene.copy(), d)
    with pytest.raises(InvalidInputError):
        save_scene(box_scene.copy(), d)


def test_tamper_detection(services, box_scene):
    projects, assets = services
    p = projects.create("P")
    a = assets.create_asset(p["project_id"], "A", "prop")
    v = assets.add_version(a["asset_id"], box_scene, stage=Stage.RAW, operation="import")
    path = assets.version_path(v["version_id"]) / "parts" / "body.npz"
    path.chmod(0o644)
    path.write_bytes(path.read_bytes() + b"tamper")
    with pytest.raises(InvalidInputError, match="integrity"):
        assets.load_scene(v["version_id"])


def test_raw_cannot_have_parent_and_cannot_be_deleted(services, box_scene):
    projects, assets = services
    p = projects.create("P")
    a = assets.create_asset(p["project_id"], "A", "prop")
    raw = assets.add_version(a["asset_id"], box_scene, stage=Stage.RAW, operation="import")
    with pytest.raises(InvalidInputError):
        assets.add_version(a["asset_id"], box_scene, stage=Stage.RAW, operation="x", parent_version_id=raw["version_id"])
    with pytest.raises(ConflictError):
        assets.delete_version(raw["version_id"])


def test_production_designation_requires_passing_validation(services, db, box_scene):
    projects, assets = services
    p = projects.create("P")
    a = assets.create_asset(p["project_id"], "A", "prop")
    v = assets.add_version(a["asset_id"], box_scene, stage=Stage.FINAL, operation="x")
    with pytest.raises(ConflictError, match="not been validated"):
        assets.designate_production_version(v["version_id"])
    with pytest.raises(ConflictError):
        assets.set_status(a["asset_id"], AssetStatus.PRODUCTION_READY)  # cannot be set directly
    db.execute("INSERT INTO validation_results VALUES ('val_x',?,?,50,'NEEDS_REVIEW',1,'{}',0)", (v["version_id"], a["asset_id"]))
    with pytest.raises(ConflictError, match="did not reach"):
        assets.designate_production_version(v["version_id"])
    db.execute("DELETE FROM validation_results")
    db.execute("INSERT INTO validation_results VALUES ('val_y',?,?,97,'PRODUCTION_READY',0,'{}',1)", (v["version_id"], a["asset_id"]))
    out = assets.designate_production_version(v["version_id"], semver="1.0.0")
    assert out["production_version_id"] == v["version_id"] and out["status"] == "PRODUCTION_READY"
    assert out["metadata"]["asset_version"] == "1.0.0"
    with pytest.raises(ConflictError):
        assets.delete_version(v["version_id"])  # current production version is protected


def test_status_machine(services):
    projects, assets = services
    p = projects.create("P")
    a = assets.create_asset(p["project_id"], "A", "prop")
    assets.set_status(a["asset_id"], "PROCESSING")
    with pytest.raises(ConflictError):
        assets.set_status(a["asset_id"], "APPROVED")  # PROCESSING -> APPROVED not allowed
    assets.set_status(a["asset_id"], "ARCHIVED")
    assets.set_status(a["asset_id"], "DRAFT")


def test_duplicate_project_deep_copy(services, box_scene):
    projects, assets = services
    p = projects.create("P")
    a = assets.create_asset(p["project_id"], "A", "prop")
    v1 = assets.add_version(a["asset_id"], box_scene, stage=Stage.RAW, operation="import")
    assets.add_version(a["asset_id"], box_scene, stage=Stage.PROCESSED, operation="x", parent_version_id=v1["version_id"])
    dup = projects.duplicate(p["project_id"], "P copy")
    na = assets.list_assets(project_id=dup["project_id"])
    assert len(na) == 1 and na[0]["asset_id"] != a["asset_id"]
    nv = assets.list_versions(na[0]["asset_id"])
    assert [v["number"] for v in nv] == [1, 2] and nv[1]["parent_version_id"] == nv[0]["version_id"]
    assert assets.load_scene(nv[0]["version_id"]).meshes["body"].extents[2] == pytest.approx(6.0, rel=1e-4)


def test_project_history_and_export(services, box_scene, tmp_path):
    projects, assets = services
    p = projects.create("P")
    a = assets.create_asset(p["project_id"], "A", "prop")
    assets.add_version(a["asset_id"], box_scene, stage=Stage.RAW, operation="import")
    h = projects.history(p["project_id"])
    assert {e["type"] for e in h} >= {"project.created", "asset.created", "version.created"}
    z = projects.export_archive(p["project_id"], tmp_path / "p.zip")
    import zipfile

    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
        assert "project.json" in names and any(n.endswith("manifest.json") for n in names)
        assert json.loads(zf.read("project.json"))["project"]["name"] == "P"


def test_reports_stored_with_version(services, box_scene):
    projects, assets = services
    p = projects.create("P")
    a = assets.create_asset(p["project_id"], "A", "prop")
    sc = box_scene.copy()
    sc.reports["processing"] = {"hello": "world"}
    v = assets.add_version(a["asset_id"], sc, stage=Stage.RAW, operation="import")
    assert assets.load_scene(v["version_id"]).reports["processing"] == {"hello": "world"}
