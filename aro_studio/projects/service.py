"""Project management (spec §6)."""

from __future__ import annotations

import builtins
import json
import shutil
import time
import zipfile
from pathlib import Path

from aro_studio.assets.service import AssetService
from aro_studio.core.enums import ProjectStatus
from aro_studio.core.errors import ConflictError, InvalidInputError, NotFoundError
from aro_studio.core.ids import new_id, require_id
from aro_studio.db.database import Database, dumps, loads
from aro_studio.security.audit import AuditLog
from aro_studio.security.filenames import slugify
from aro_studio.storage.layout import StorageLayout, remove_tree

PROJECT_SECTIONS = [
    "Source",
    "Generation",
    "Geometry",
    "Materials",
    "Textures",
    "Vehicle Setup",
    "Collision",
    "LOD",
    "Validation",
    "Exports",
]


class ProjectService:
    def __init__(self, db: Database, layout: StorageLayout, assets: AssetService, audit: AuditLog | None = None):
        self.db, self.layout, self.assets, self.audit = db, layout, assets, audit

    @staticmethod
    def _row(r: dict) -> dict:
        r["metadata"] = loads(r.get("metadata"), {})
        return r

    @staticmethod
    def _clean_name(name: str) -> str:
        name = " ".join((name or "").split())
        if not (1 <= len(name) <= 120):
            raise InvalidInputError("Project name must be 1-120 characters.")
        return name

    def create(self, name: str, description: str = "", metadata: dict | None = None) -> dict:
        name = self._clean_name(name)
        pid, now = new_id("project"), time.time()
        self.layout.create_project_tree(pid)
        self.db.execute(
            "INSERT INTO projects(project_id,name,slug,description,status,metadata,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                pid,
                name,
                slugify(name, default="project"),
                description[:2000],
                ProjectStatus.ACTIVE.value,
                dumps(metadata or {}),
                now,
                now,
            ),
        )
        if self.audit:
            self.audit.record("project.create", target=pid, name=name)
        return self.get(pid)

    def get(self, project_id: str, *, include_deleted: bool = False) -> dict:
        require_id(project_id, "project")
        r = self.db.query_one("SELECT * FROM projects WHERE project_id=?", (project_id,))
        if not r or (r["status"] == "deleted" and not include_deleted):
            raise NotFoundError("Project not found.")
        return self._row(r)

    def list(self, *, status: str | None = None, q: str | None = None) -> list[dict]:
        sql, params = "SELECT * FROM projects WHERE status != 'deleted'", []
        if status:
            sql += " AND status=?"
            params.append(status)  # noqa: E702
        if q:
            sql += " AND (name LIKE ? OR description LIKE ?)"
            params += [f"%{q}%"] * 2  # noqa: E702
        sql += " ORDER BY updated_at DESC"
        rows = [self._row(r) for r in self.db.query(sql, params)]
        for r in rows:
            cnt = self.db.query_one("SELECT COUNT(*) c FROM assets WHERE project_id=?", (r["project_id"],))
            r["asset_count"] = cnt["c"] if cnt else 0
        return rows

    def rename(self, project_id: str, name: str) -> dict:
        name = self._clean_name(name)
        self.get(project_id)
        self.db.execute(
            "UPDATE projects SET name=?, slug=?, updated_at=? WHERE project_id=?",
            (name, slugify(name, default="project"), time.time(), project_id),
        )
        if self.audit:
            self.audit.record("project.rename", target=project_id, name=name)
        return self.get(project_id)

    def update(self, project_id: str, *, description: str | None = None, metadata: dict | None = None) -> dict:
        p = self.get(project_id)
        self.db.execute(
            "UPDATE projects SET description=?, metadata=?, updated_at=? WHERE project_id=?",
            (
                (description if description is not None else p["description"])[:2000],
                dumps(metadata if metadata is not None else p["metadata"]),
                time.time(),
                project_id,
            ),
        )
        return self.get(project_id)

    def archive(self, project_id: str) -> dict:
        self.get(project_id)
        self.db.execute(
            "UPDATE projects SET status='archived', updated_at=? WHERE project_id=?", (time.time(), project_id)
        )
        if self.audit:
            self.audit.record("project.archive", target=project_id)
        return self.get(project_id)

    def restore(self, project_id: str) -> dict:
        p = self.get(project_id, include_deleted=True)
        if p["status"] == "active":
            raise ConflictError("Project is already active.")
        self.db.execute(
            "UPDATE projects SET status='active', updated_at=? WHERE project_id=?", (time.time(), project_id)
        )
        if self.audit:
            self.audit.record("project.restore", target=project_id)
        return self.get(project_id)

    def delete(self, project_id: str, *, permanent: bool = False) -> None:
        """Soft delete by default (recoverable via ``restore``); ``permanent`` removes all files."""
        p = self.get(project_id, include_deleted=True)
        if permanent:
            if p["status"] == "active":
                raise ConflictError("Archive or soft-delete the project before permanent deletion.")
            with self.db.transaction():
                self.db.execute("DELETE FROM generations WHERE project_id=?", (project_id,))
                self.db.execute("DELETE FROM exports WHERE project_id=?", (project_id,))
                self.db.execute(
                    "DELETE FROM validation_results WHERE asset_id IN (SELECT asset_id FROM assets WHERE project_id=?)",
                    (project_id,),
                )
                self.db.execute("DELETE FROM jobs WHERE project_id=?", (project_id,))
                self.db.execute("DELETE FROM projects WHERE project_id=?", (project_id,))
            remove_tree(self.layout.project_dir(project_id))
        else:
            self.db.execute(
                "UPDATE projects SET status='deleted', updated_at=? WHERE project_id=?", (time.time(), project_id)
            )
        if self.audit:
            self.audit.record("project.delete", target=project_id, permanent=permanent)

    def duplicate(self, project_id: str, new_name: str | None = None) -> dict:
        """Deep copy: new ids for the project, every asset and every version; files are copied."""
        src = self.get(project_id)
        new = self.create(new_name or f"{src['name']} (copy)", src["description"], src["metadata"])
        npid = new["project_id"]
        # source images
        for f in self.layout.source_dir(project_id).glob("*"):
            if f.is_file():
                shutil.copy2(f, self.layout.source_dir(npid) / f.name)
        for a in self.db.query("SELECT * FROM assets WHERE project_id=? ORDER BY created_at", (project_id,)):
            naid, now = new_id("asset"), time.time()
            self.db.execute(
                "INSERT INTO assets(asset_id,project_id,name,category,status,metadata,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (naid, npid, a["name"], a["category"], a["status"], a["metadata"], now, now),
            )
            vmap: dict[str, str] = {}
            for v in self.db.query("SELECT * FROM asset_versions WHERE asset_id=? ORDER BY number", (a["asset_id"],)):
                nvid = vmap[v["version_id"]] = new_id("version")
                s = self.layout.version_dir(project_id, a["asset_id"], v["stage"], v["version_id"])
                d = self.layout.version_dir(npid, naid, v["stage"], nvid)
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(s, d)
                self.db.execute(
                    """INSERT INTO asset_versions(version_id,asset_id,project_id,number,label,stage,operation,description,
                       parent_version_id,manifest_sha256,vertex_count,triangle_count,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        nvid,
                        naid,
                        npid,
                        v["number"],
                        v["label"],
                        v["stage"],
                        v["operation"],
                        v["description"],
                        vmap.get(v["parent_version_id"] or ""),
                        v["manifest_sha256"],
                        v["vertex_count"],
                        v["triangle_count"],
                        v["created_at"],
                    ),
                )
                # Identifiers below come from this fixed tuple and from PRAGMA table_info; all values are bound parameters.
                for t in ("materials", "textures", "lods"):
                    cols = [
                        c["name"]
                        for c in self.db.query(f"PRAGMA table_info({t})")  # nosec B608
                        if c["name"] not in (f"{t[:-1]}_id", "version_id")
                    ]  # noqa: S608
                    for r in self.db.query(f"SELECT {','.join(cols)} FROM {t} WHERE version_id=?", (v["version_id"],)):  # noqa: S608  # nosec B608
                        self.db.execute(
                            f"INSERT INTO {t}(version_id,{','.join(cols)}) VALUES (?{',?' * len(cols)})",  # noqa: S608  # nosec B608
                            (nvid, *[r[c] for c in cols]),
                        )
            if a["production_version_id"] in vmap:
                self.db.execute(
                    "UPDATE assets SET production_version_id=? WHERE asset_id=?",
                    (vmap[a["production_version_id"]], naid),
                )
        if self.audit:
            self.audit.record("project.duplicate", target=npid, source=project_id)
        return self.get(npid)

    # -- history ------------------------------------------------------------------------------
    def history(self, project_id: str, limit: int = 200) -> builtins.list[dict]:
        """Chronological timeline of everything that happened in the project."""
        self.get(project_id, include_deleted=True)
        ev: list[dict] = []
        p = self.get(project_id, include_deleted=True)
        ev.append(
            {
                "ts": p["created_at"],
                "type": "project.created",
                "title": f"Project '{p['name']}' created",
                "ref": project_id,
            }
        )
        for a in self.db.query("SELECT asset_id,name,created_at FROM assets WHERE project_id=?", (project_id,)):
            ev.append(
                {
                    "ts": a["created_at"],
                    "type": "asset.created",
                    "title": f"Asset '{a['name']}' created",
                    "ref": a["asset_id"],
                }
            )
        for v in self.db.query("SELECT * FROM asset_versions WHERE project_id=?", (project_id,)):
            ev.append(
                {
                    "ts": v["created_at"],
                    "type": "version.created",
                    "title": f"{v['label']} ({v['stage']}) - {v['operation']}",
                    "detail": v["description"],
                    "ref": v["version_id"],
                }
            )
        for g in self.db.query("SELECT * FROM generations WHERE project_id=?", (project_id,)):
            ev.append(
                {
                    "ts": g["created_at"],
                    "type": "generation",
                    "title": f"Generation {g['status']} ({g['engine_id']})",
                    "ref": g["generation_id"],
                }
            )
        for e in self.db.query("SELECT * FROM exports WHERE project_id=?", (project_id,)):
            ev.append(
                {
                    "ts": e["created_at"],
                    "type": "export",
                    "title": f"Export {e['format']} {e['status']}",
                    "ref": e["export_id"],
                }
            )
        for v in self.db.query(
            "SELECT vr.* FROM validation_results vr JOIN assets a USING(asset_id) WHERE a.project_id=?", (project_id,)
        ):
            ev.append(
                {
                    "ts": v["created_at"],
                    "type": "validation",
                    "title": f"Validation {v['status']} ({v['overall']:.0f}%)",
                    "ref": v["validation_id"],
                }
            )
        for j in self.db.query("SELECT * FROM jobs WHERE project_id=?", (project_id,)):
            ev.append(
                {"ts": j["created_at"], "type": "job", "title": f"Job {j['kind']} {j['state']}", "ref": j["job_id"]}
            )
        ev.sort(key=lambda e: e["ts"], reverse=True)
        return ev[:limit]

    # -- export -------------------------------------------------------------------------------
    def export_archive(self, project_id: str, dest_zip: Path) -> Path:
        """Zip the whole project (files + a JSON dump of its database records)."""
        p = self.get(project_id)
        base = self.layout.project_dir(project_id)
        records = {
            "project": p,
            "assets": [
                self.assets._asset(a) for a in self.db.query("SELECT * FROM assets WHERE project_id=?", (project_id,))
            ],
            "versions": self.db.query("SELECT * FROM asset_versions WHERE project_id=?", (project_id,)),
            "generations": self.db.query("SELECT * FROM generations WHERE project_id=?", (project_id,)),
            "exports": self.db.query("SELECT * FROM exports WHERE project_id=?", (project_id,)),
        }
        dest_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("project.json", json.dumps(records, indent=2, default=str))
            for f in sorted(base.rglob("*")):
                if f.is_file() and "tmp" not in f.relative_to(base).parts[:1]:
                    zf.write(f, f"files/{f.relative_to(base).as_posix()}")
        if self.audit:
            self.audit.record("project.export", target=project_id)
        return dest_zip
