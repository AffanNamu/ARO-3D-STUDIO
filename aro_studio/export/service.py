"""Export orchestration: write files, verify what was written, record the result (spec §21, §36)."""

from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

from aro_studio.assets.service import AssetService
from aro_studio.core.errors import InvalidInputError, NotFoundError
from aro_studio.core.hashing import sha256_file
from aro_studio.core.ids import new_id, require_id
from aro_studio.db.database import Database, dumps, loads
from aro_studio.export.gltf import ExportOptions, export_glb, export_gltf
from aro_studio.export.obj import export_obj
from aro_studio.export.unity import build_unity_package
from aro_studio.export.verify import khronos_validate, verify_glb, verify_unity_package
from aro_studio.security.audit import AuditLog
from aro_studio.security.filenames import slugify
from aro_studio.storage.layout import StorageLayout, remove_tree

FORMATS = ("glb", "gltf", "obj", "unity")


class ExportService:
    def __init__(self, db: Database, layout: StorageLayout, assets: AssetService, audit: AuditLog | None = None):
        self.db, self.layout, self.assets, self.audit = db, layout, assets, audit

    def latest_validation(self, version_id: str) -> dict | None:
        r = self.db.query_one(
            "SELECT * FROM validation_results WHERE version_id=? ORDER BY created_at DESC LIMIT 1", (version_id,)
        )
        if not r:
            return None
        rep = loads(r["report"], {})
        return {
            "validation_id": r["validation_id"],
            "status": r["status"],
            "overall": r["overall"],
            "critical_failures": r["critical_failures"],
            "categories": rep.get("categories"),
        }

    def export(self, version_id: str, fmt: str) -> dict:
        if fmt not in FORMATS:
            raise InvalidInputError(f"Unknown export format '{fmt}'.", recommended_action=f"Use one of {FORMATS}.")
        v = self.assets.get_version(version_id)
        asset = self.assets.get_asset(v["asset_id"])
        scene = self.assets.load_scene(version_id)
        eid = new_id("export")
        out = self.layout.export_dir(v["project_id"], eid)
        out.mkdir(parents=True, exist_ok=True)
        slug = slugify(scene.manifest.name)
        t0 = time.perf_counter()
        status, report, main = "COMPLETED", {}, None
        try:
            if fmt == "glb":
                data, rep = export_glb(scene, ExportOptions(root_name=slug))
                main = out / f"{slug}-{v['label']}.glb"
                main.write_bytes(data)
                ver = verify_glb(data, scene)
                report = {**rep, "verification": ver, "khronos": khronos_validate(main)}
                ok = ver["ok"] and report["khronos"].get("ok", True)
            elif fmt == "gltf":
                js, files, rep = export_gltf(scene, ExportOptions(root_name=slug, bin_name=f"{slug}.bin"))
                gdir = out / "gltf"
                (gdir / "textures").mkdir(parents=True, exist_ok=True)
                (gdir / f"{slug}.gltf").write_text(js, encoding="utf-8")
                for rel, b in files.items():
                    p = gdir / rel
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(b)
                main = out / f"{slug}-{v['label']}-gltf.zip"
                with zipfile.ZipFile(main, "w", zipfile.ZIP_DEFLATED) as zf:
                    for f in sorted(gdir.rglob("*")):
                        if f.is_file():
                            zf.write(f, f.relative_to(gdir).as_posix())
                # reload from disk to verify what was actually written
                import pygltflib as g

                gl = g.GLTF2().load(str(gdir / f"{slug}.gltf"))
                missing = [i.uri for i in (gl.images or []) if i.uri and not (gdir / i.uri).is_file()]
                binsize = (gdir / f"{slug}.bin").stat().st_size
                ok = not missing and binsize == gl.buffers[0].byteLength
                report = {
                    **rep,
                    "verification": {
                        "ok": ok,
                        "checks": [
                            {
                                "id": "gltf.files",
                                "ok": not missing,
                                "message": "all external images present" if not missing else f"missing {missing}",
                            },
                            {
                                "id": "gltf.bin",
                                "ok": binsize == gl.buffers[0].byteLength,
                                "message": "bin size matches buffer.byteLength",
                            },
                        ],
                    },
                }
            elif fmt == "obj":
                odir = out / "obj"
                odir.mkdir(parents=True, exist_ok=True)
                otext, mtl, files, rep = export_obj(scene, name=slug)
                (odir / f"{slug}.obj").write_text(otext)
                (odir / f"{slug}.mtl").write_text(mtl)
                for rel, b in files.items():
                    (odir / rel).parent.mkdir(parents=True, exist_ok=True)
                    (odir / rel).write_bytes(b)
                import trimesh

                back = trimesh.load(
                    io.StringIO((odir / f"{slug}.obj").read_text()),
                    file_type="obj",
                    split_object=True,
                    group_material=False,
                )
                tris = (
                    sum(len(m.faces) for m in back.geometry.values() if isinstance(m, trimesh.Trimesh))
                    if isinstance(back, trimesh.Scene)
                    else len(getattr(back, "faces", []))
                )
                ok = tris == rep["triangles"]
                report = {
                    **rep,
                    "verification": {
                        "ok": ok,
                        "checks": [
                            {
                                "id": "obj.reload",
                                "ok": ok,
                                "message": f"re-read {tris} triangles (expected {rep['triangles']})",
                            }
                        ],
                    },
                }
                main = out / f"{slug}-{v['label']}-obj.zip"
                with zipfile.ZipFile(main, "w", zipfile.ZIP_DEFLATED) as zf:
                    for f in sorted(odir.rglob("*")):
                        if f.is_file():
                            zf.write(f, f.relative_to(odir).as_posix())
            else:  # unity
                main, rep = build_unity_package(
                    scene,
                    out,
                    asset_id=asset["asset_id"],
                    version_id=version_id,
                    version_label=v["label"],
                    stage=v["stage"],
                    validation_summary=self.latest_validation(version_id),
                )
                ver = verify_unity_package(Path(rep["package_dir"]), scene)
                report = {**rep, "verification": ver}
                ok = ver["ok"]
            if not ok:
                status = "FAILED"
        except Exception as e:  # keep the record: failed exports are never silently dropped
            from aro_studio.core.errors import explain_exception

            ex = explain_exception(e)
            status, report = (
                "FAILED",
                {"error": {"code": ex.code, "message": ex.message, "recommended_action": ex.recommended_action}},
            )
            main = None
        report["seconds"] = round(time.perf_counter() - t0, 3)
        digest = sha256_file(main) if main and main.is_file() else None
        size = main.stat().st_size if main and main.is_file() else None
        self.db.execute(
            "INSERT INTO exports(export_id,project_id,asset_id,version_id,format,path,sha256,size_bytes,status,report,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                eid,
                v["project_id"],
                v["asset_id"],
                version_id,
                fmt,
                str(main.relative_to(out)) if main else "",
                digest,
                size,
                status,
                dumps(report),
                time.time(),
            ),
        )
        if self.audit:
            self.audit.record("export.create", target=eid, version_id=version_id, format=fmt, status=status)
        return self.get(eid)

    def get(self, export_id: str) -> dict:
        require_id(export_id, "export")
        r = self.db.query_one("SELECT * FROM exports WHERE export_id=?", (export_id,))
        if not r:
            raise NotFoundError("Export not found.")
        r["report"] = loads(r["report"], {})
        return r

    def list(self, *, asset_id: str | None = None, project_id: str | None = None) -> list[dict]:
        sql, p = "SELECT export_id FROM exports WHERE 1=1", []
        if asset_id:
            sql += " AND asset_id=?"
            p.append(require_id(asset_id, "asset"))  # noqa: E702
        if project_id:
            sql += " AND project_id=?"
            p.append(require_id(project_id, "project"))  # noqa: E702
        return [self.get(r["export_id"]) for r in self.db.query(sql + " ORDER BY created_at DESC", p)]

    def file_path(self, export_id: str) -> Path:
        e = self.get(export_id)
        if e["status"] != "COMPLETED" or not e["path"]:
            raise NotFoundError(
                "This export did not complete, so there is no file to download.",
                recommended_action="Check the export report and re-run.",
            )
        return self.layout.export_dir(e["project_id"], export_id) / e["path"]

    def delete(self, export_id: str) -> None:
        e = self.get(export_id)
        remove_tree(self.layout.export_dir(e["project_id"], export_id))
        self.db.execute("DELETE FROM exports WHERE export_id=?", (export_id,))
