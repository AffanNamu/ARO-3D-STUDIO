"""Assets and immutable asset versions (spec §6, §12, §26, §43, §45)."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from aro_studio.assets.metadata import AssetMetadata
from aro_studio.assets.taxonomy import require_creatable
from aro_studio.core.enums import AssetStatus, Stage
from aro_studio.core.errors import ConflictError, InvalidInputError, NotFoundError
from aro_studio.core.hashing import sha256_file
from aro_studio.core.ids import new_id, require_id
from aro_studio.db.database import Database, dumps, loads
from aro_studio.scene.store import Scene, load_scene, save_scene
from aro_studio.security.audit import AuditLog
from aro_studio.storage.layout import StorageLayout, make_readonly, remove_tree

# Statuses a caller may move an asset to directly. PRODUCTION_READY is reachable only through
# `designate_production_version`, which requires a passing validation record.
_ALLOWED = {
    AssetStatus.DRAFT: {
        AssetStatus.GENERATING,
        AssetStatus.PROCESSING,
        AssetStatus.VALIDATING,
        AssetStatus.NEEDS_REVIEW,
        AssetStatus.FAILED,
        AssetStatus.ARCHIVED,
    },
    AssetStatus.GENERATING: {AssetStatus.PROCESSING, AssetStatus.DRAFT, AssetStatus.FAILED, AssetStatus.ARCHIVED},
    AssetStatus.PROCESSING: {
        AssetStatus.DRAFT,
        AssetStatus.PROCESSING,
        AssetStatus.VALIDATING,
        AssetStatus.NEEDS_REVIEW,
        AssetStatus.FAILED,
        AssetStatus.ARCHIVED,
    },
    AssetStatus.VALIDATING: {
        AssetStatus.DRAFT,
        AssetStatus.PROCESSING,
        AssetStatus.NEEDS_REVIEW,
        AssetStatus.APPROVED,
        AssetStatus.FAILED,
        AssetStatus.ARCHIVED,
    },
    AssetStatus.NEEDS_REVIEW: {
        AssetStatus.DRAFT,
        AssetStatus.PROCESSING,
        AssetStatus.VALIDATING,
        AssetStatus.APPROVED,
        AssetStatus.FAILED,
        AssetStatus.ARCHIVED,
    },
    AssetStatus.APPROVED: {
        AssetStatus.DRAFT,
        AssetStatus.PROCESSING,
        AssetStatus.VALIDATING,
        AssetStatus.NEEDS_REVIEW,
        AssetStatus.ARCHIVED,
    },
    AssetStatus.PRODUCTION_READY: {AssetStatus.PROCESSING, AssetStatus.NEEDS_REVIEW, AssetStatus.ARCHIVED},
    AssetStatus.FAILED: {AssetStatus.DRAFT, AssetStatus.PROCESSING, AssetStatus.GENERATING, AssetStatus.ARCHIVED},
    AssetStatus.ARCHIVED: {AssetStatus.DRAFT},
}


class AssetService:
    def __init__(self, db: Database, layout: StorageLayout, audit: AuditLog | None = None):
        self.db, self.layout, self.audit = db, layout, audit

    # -- assets -------------------------------------------------------------------------------
    @staticmethod
    def _asset(row: dict) -> dict:
        row["metadata"] = loads(row.get("metadata"), {})
        return row

    def create_asset(self, project_id: str, name: str, category: str, metadata: dict | None = None) -> dict:
        require_id(project_id, "project")
        name = (name or "").strip()
        if not (1 <= len(name) <= 120):
            raise InvalidInputError("Asset name must be 1-120 characters.")
        require_creatable(category)
        if not self.db.query_one("SELECT 1 FROM projects WHERE project_id=? AND status!='deleted'", (project_id,)):
            raise NotFoundError("Project not found.")
        meta = AssetMetadata.model_validate({**(metadata or {}), "category": category}).model_dump()
        now, aid = time.time(), new_id("asset")
        self.db.execute(
            "INSERT INTO assets(asset_id,project_id,name,category,status,metadata,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (aid, project_id, name, category, AssetStatus.DRAFT.value, dumps(meta), now, now),
        )
        if self.audit:
            self.audit.record("asset.create", target=aid, project_id=project_id, name=name)
        return self.get_asset(aid)

    def get_asset(self, asset_id: str) -> dict:
        require_id(asset_id, "asset")
        row = self.db.query_one("SELECT * FROM assets WHERE asset_id=?", (asset_id,))
        if not row:
            raise NotFoundError("Asset not found.")
        return self._asset(row)

    def list_assets(
        self,
        *,
        project_id: str | None = None,
        category: str | None = None,
        status: str | None = None,
        q: str | None = None,
    ) -> list[dict]:
        sql, params = "SELECT a.* FROM assets a JOIN projects p USING(project_id) WHERE p.status!='deleted'", []
        if project_id:
            sql += " AND a.project_id=?"
            params.append(require_id(project_id, "project"))  # noqa: E702
        if category:
            sql += " AND a.category=?"
            params.append(category)  # noqa: E702
        if status:
            sql += " AND a.status=?"
            params.append(status)  # noqa: E702
        if q:
            sql += " AND (a.name LIKE ? OR a.metadata LIKE ?)"
            params += [f"%{q}%", f"%{q}%"]  # noqa: E702
        sql += " ORDER BY a.updated_at DESC"
        return [self._asset(r) for r in self.db.query(sql, params)]

    def update_metadata(self, asset_id: str, patch: dict) -> dict:
        a = self.get_asset(asset_id)
        merged = AssetMetadata.model_validate({**a["metadata"], **patch, "category": a["category"]}).model_dump()
        self.db.execute(
            "UPDATE assets SET metadata=?, updated_at=? WHERE asset_id=?", (dumps(merged), time.time(), asset_id)
        )
        return self.get_asset(asset_id)

    def rename_asset(self, asset_id: str, name: str) -> dict:
        self.get_asset(asset_id)
        name = name.strip()
        if not (1 <= len(name) <= 120):
            raise InvalidInputError("Asset name must be 1-120 characters.")
        self.db.execute("UPDATE assets SET name=?, updated_at=? WHERE asset_id=?", (name, time.time(), asset_id))
        return self.get_asset(asset_id)

    def set_status(self, asset_id: str, status: AssetStatus | str) -> dict:
        a = self.get_asset(asset_id)
        new, cur = AssetStatus(status), AssetStatus(a["status"])
        if new is AssetStatus.PRODUCTION_READY:
            raise ConflictError(
                "PRODUCTION_READY can only be granted by designating a validated version.",
                recommended_action="Run validation, then designate the version as the current production version.",
            )
        if new != cur and new not in _ALLOWED[cur]:
            raise ConflictError(f"Cannot change status from {cur.value} to {new.value}.")
        self.db.execute("UPDATE assets SET status=?, updated_at=? WHERE asset_id=?", (new.value, time.time(), asset_id))
        meta = a["metadata"]
        meta["status"] = new.value.lower()  # noqa: E702
        self.db.execute("UPDATE assets SET metadata=? WHERE asset_id=?", (dumps(meta), asset_id))
        if self.audit:
            self.audit.record("asset.status", target=asset_id, from_=cur.value, to=new.value)
        return self.get_asset(asset_id)

    # -- versions -----------------------------------------------------------------------------
    def add_version(
        self,
        asset_id: str,
        scene: Scene,
        *,
        stage: Stage,
        operation: str,
        description: str = "",
        parent_version_id: str | None = None,
    ) -> dict:
        """Persist ``scene`` as a NEW immutable version. Never modifies an existing version."""
        asset = self.get_asset(asset_id)
        if parent_version_id:
            parent = self.get_version(parent_version_id)
            if parent["asset_id"] != asset_id:
                raise InvalidInputError("Parent version belongs to a different asset.")
        if stage is Stage.RAW and parent_version_id:
            raise InvalidInputError("A raw version cannot have a parent: raw output is the origin.")
        vid = new_id("version")
        final_dir = self.layout.version_dir(asset["project_id"], asset_id, stage, vid)
        staging = final_dir.with_name(final_dir.name + ".staging")
        try:
            digest = save_scene(scene, staging)
            final_dir.parent.mkdir(parents=True, exist_ok=True)
            staging.rename(final_dir)  # atomic publish
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        make_readonly(final_dir)
        man = scene.manifest
        with self.db.transaction():
            number = (
                self.db.query_one(
                    "SELECT COALESCE(MAX(number),0)+1 AS n FROM asset_versions WHERE asset_id=?", (asset_id,)
                )
                or {"n": 1}
            )["n"]
            self.db.execute(
                """INSERT INTO asset_versions(version_id,asset_id,project_id,number,label,stage,operation,description,
                   parent_version_id,manifest_sha256,vertex_count,triangle_count,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    vid,
                    asset_id,
                    asset["project_id"],
                    number,
                    f"v0.{number}",
                    stage.value,
                    operation,
                    description,
                    parent_version_id,
                    digest,
                    scene.vertex_count,
                    scene.triangle_count,
                    time.time(),
                ),
            )
            for m in man.materials:
                self.db.execute(
                    "INSERT INTO materials(version_id,name,category,data) VALUES (?,?,?,?)",
                    (vid, m.name, m.category.value, m.model_dump_json()),
                )
            for t in man.textures:
                self.db.execute(
                    "INSERT INTO textures(version_id,name,path,width,height,sha256) VALUES (?,?,?,?,?,?)",
                    (vid, t.name, t.file, t.width, t.height, t.sha256),
                )
            for lod in [*man.lods]:
                self.db.execute(
                    "INSERT INTO lods(version_id,level,triangle_count,vertex_count,target_ratio) VALUES (?,?,?,?,?)",
                    (vid, lod.level, lod.triangle_count, lod.vertex_count, lod.target_ratio),
                )
            self.db.execute(
                "INSERT INTO lods(version_id,level,triangle_count,vertex_count,target_ratio) VALUES (?,?,?,?,?)",
                (vid, 0, scene.triangle_count, scene.vertex_count, 1.0),
            )
            self.db.execute("UPDATE assets SET updated_at=? WHERE asset_id=?", (time.time(), asset_id))
        if self.audit:
            self.audit.record("version.create", target=vid, asset_id=asset_id, operation=operation, stage=stage.value)
        return self.get_version(vid)

    def get_version(self, version_id: str) -> dict:
        require_id(version_id, "version")
        row = self.db.query_one("SELECT * FROM asset_versions WHERE version_id=?", (version_id,))
        if not row:
            raise NotFoundError("Version not found.")
        a = self.db.query_one("SELECT production_version_id FROM assets WHERE asset_id=?", (row["asset_id"],))
        row["is_production"] = bool(a and a["production_version_id"] == version_id)
        return row

    def list_versions(self, asset_id: str) -> list[dict]:
        self.get_asset(asset_id)
        rows = self.db.query("SELECT version_id FROM asset_versions WHERE asset_id=? ORDER BY number", (asset_id,))
        return [self.get_version(r["version_id"]) for r in rows]

    def latest_version(self, asset_id: str) -> dict | None:
        r = self.db.query_one(
            "SELECT version_id FROM asset_versions WHERE asset_id=? ORDER BY number DESC LIMIT 1", (asset_id,)
        )
        return self.get_version(r["version_id"]) if r else None

    def version_path(self, version_id: str) -> Path:
        v = self.get_version(version_id)
        return self.layout.version_dir(v["project_id"], v["asset_id"], v["stage"], version_id)

    def load_scene(self, version_id: str, *, verify: bool = True) -> Scene:
        return load_scene(self.version_path(version_id), verify=verify)

    def verify_integrity(self, version_id: str) -> bool:
        """Re-hash every file of a version against its manifest."""
        p = self.version_path(version_id)
        scene = load_scene(p, verify=True)
        return bool(scene.manifest.files) and sha256_file(p / "manifest.json") is not None

    def delete_version(self, version_id: str) -> None:
        v = self.get_version(version_id)
        if v["is_production"]:
            raise ConflictError(
                "The current production version cannot be deleted.",
                recommended_action="Designate another version first.",
            )
        if self.db.query_one("SELECT 1 FROM asset_versions WHERE parent_version_id=?", (version_id,)):
            raise ConflictError(
                "Other versions derive from this one.", recommended_action="Delete the derived versions first."
            )
        if v["stage"] == Stage.RAW.value:
            raise ConflictError(
                "Raw reconstructions are never deleted individually.",
                recommended_action="Delete the whole asset/project instead.",
            )
        remove_tree(self.version_path(version_id))
        self.db.execute("DELETE FROM asset_versions WHERE version_id=?", (version_id,))
        if self.audit:
            self.audit.record("version.delete", target=version_id)

    # -- production designation ---------------------------------------------------------------
    def designate_production_version(self, version_id: str, *, semver: str | None = None) -> dict:
        """Mark ONE version as CURRENT PRODUCTION VERSION. Requires a passing validation record."""
        v = self.get_version(version_id)
        val = self.db.query_one(
            "SELECT status, critical_failures FROM validation_results WHERE version_id=? ORDER BY created_at DESC LIMIT 1",
            (version_id,),
        )
        if not val:
            raise ConflictError("This version has not been validated.", recommended_action="Run validation first.")
        if val["status"] != AssetStatus.PRODUCTION_READY.value or val["critical_failures"] > 0:
            raise ConflictError(
                "Validation did not reach PRODUCTION_READY, so this version cannot become the production version.",
                recommended_action="Fix the critical failures in the validation report and re-validate.",
            )
        with self.db.transaction():
            self.db.execute(
                "UPDATE assets SET production_version_id=?, status=?, updated_at=? WHERE asset_id=?",
                (version_id, AssetStatus.PRODUCTION_READY.value, time.time(), v["asset_id"]),
            )
            if semver:
                a = self.get_asset(v["asset_id"])
                meta = a["metadata"]
                meta["asset_version"] = semver
                meta["status"] = "production_ready"  # noqa: E702
                self.db.execute("UPDATE assets SET metadata=? WHERE asset_id=?", (dumps(meta), v["asset_id"]))
        if self.audit:
            self.audit.record("version.designate_production", target=version_id, asset_id=v["asset_id"], semver=semver)
        return self.get_asset(v["asset_id"])

    # -- deletion -----------------------------------------------------------------------------
    def delete_asset(self, asset_id: str) -> None:
        a = self.get_asset(asset_id)
        remove_tree(self.layout.project_dir(a["project_id"]) / "assets" / asset_id)
        self.db.execute("DELETE FROM assets WHERE asset_id=?", (asset_id,))
        if self.audit:
            self.audit.record("asset.delete", target=asset_id)
