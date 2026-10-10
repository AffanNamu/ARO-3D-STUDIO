"""Run validation on a version and persist the result (spec §24-25, §43)."""

from __future__ import annotations

import time
from typing import Any

from aro_studio.assets.service import AssetService
from aro_studio.config import Settings
from aro_studio.core.enums import AssetStatus
from aro_studio.core.errors import NotFoundError, StudioError
from aro_studio.core.ids import new_id, require_id
from aro_studio.db.database import Database, dumps, loads
from aro_studio.validation.engine import ValidationConfig, run_validation


class ValidationService:
    def __init__(self, settings: Settings, db: Database, assets: AssetService):
        self.s, self.db, self.assets = settings, db, assets

    def validate_version(self, version_id: str, config: ValidationConfig | None = None) -> dict[str, Any]:
        v = self.assets.get_version(version_id)
        asset = self.assets.get_asset(v["asset_id"])
        config = config or ValidationConfig(tri_budget_lod0=self.s.tri_budget_lod0)
        self._status(asset["asset_id"], AssetStatus.VALIDATING)
        scene = self.assets.load_scene(version_id)
        report = run_validation(scene, asset["category"], config)
        report.update(version_id=version_id, asset_id=asset["asset_id"], version_label=v["label"])
        vid = new_id("validation")
        self.db.execute(
            "INSERT INTO validation_results(validation_id,version_id,asset_id,overall,status,critical_failures,report,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                vid,
                version_id,
                asset["asset_id"],
                report["overall"],
                report["status"],
                report["critical_failures"],
                dumps(report),
                time.time(),
            ),
        )
        # PRODUCTION_READY is never set here; a passing validation makes the asset APPROVED (eligible), a failing one NEEDS_REVIEW.
        target = {
            "PRODUCTION_READY": AssetStatus.APPROVED,
            "NEEDS_REVIEW": AssetStatus.NEEDS_REVIEW,
            "FAILED": AssetStatus.FAILED,
        }[report["status"]]
        if (
            asset["production_version_id"]
            and asset["production_version_id"] == version_id
            and report["status"] == "PRODUCTION_READY"
        ):
            target = AssetStatus.PRODUCTION_READY
        self._status(asset["asset_id"], target)
        report["validation_id"] = vid
        return report

    def _status(self, asset_id: str, status: AssetStatus) -> None:
        try:
            self.assets.set_status(asset_id, status)
        except StudioError:
            pass

    def get(self, validation_id: str) -> dict:
        r = self.db.query_one(
            "SELECT * FROM validation_results WHERE validation_id=?", (require_id(validation_id, "validation"),)
        )
        if not r:
            raise NotFoundError("Validation result not found.")
        rep = loads(r["report"], {})
        rep["validation_id"] = r["validation_id"]
        return rep

    def latest(self, version_id: str) -> dict | None:
        r = self.db.query_one(
            "SELECT validation_id FROM validation_results WHERE version_id=? ORDER BY created_at DESC LIMIT 1",
            (require_id(version_id, "version"),),
        )
        return self.get(r["validation_id"]) if r else None

    def list(self, *, asset_id: str | None = None, limit: int = 100) -> list[dict]:
        sql, p = (
            "SELECT validation_id, version_id, asset_id, overall, status, critical_failures, created_at FROM validation_results",
            [],
        )
        if asset_id:
            sql += " WHERE asset_id=?"
            p.append(require_id(asset_id, "asset"))  # noqa: E702
        return self.db.query(sql + " ORDER BY created_at DESC LIMIT ?", (*p, limit))
