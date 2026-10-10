"""Concept/source image intake (spec §8): validate, hash, store by content, never by filename."""

from __future__ import annotations

import io
import json
import time
from pathlib import Path

from PIL import Image

from aro_studio.core.errors import NotFoundError
from aro_studio.core.hashing import sha256_bytes
from aro_studio.core.ids import require_id
from aro_studio.db.database import Database, loads
from aro_studio.imaging.analysis import analyze
from aro_studio.imaging.validate import load_image
from aro_studio.security.filenames import sanitize_filename
from aro_studio.storage.layout import StorageLayout

EXT = {"png": "png", "jpeg": "jpg", "webp": "webp"}


class SourceService:
    def __init__(self, db: Database, layout: StorageLayout, *, max_bytes: int, max_pixels: int, min_side: int):
        self.db, self.layout = db, layout
        self.max_bytes, self.max_pixels, self.min_side = max_bytes, max_pixels, min_side

    def add_image(self, project_id: str, filename: str, data: bytes, *, category_group: str | None = None) -> dict:
        require_id(project_id, "project")
        if not self.db.query_one("SELECT 1 FROM projects WHERE project_id=? AND status!='deleted'", (project_id,)):
            raise NotFoundError("Project not found.")
        img, report = load_image(data, max_bytes=self.max_bytes, max_pixels=self.max_pixels, min_side=self.min_side)
        digest = sha256_bytes(data)
        path = self.layout.source_dir(project_id) / f"{digest}.{EXT[report.format]}"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)
        analysis = analyze(img, declared_category_group=category_group)
        rep = {"validation": report.to_dict(), "analysis": analysis.to_dict()}
        self.db.execute(
            "INSERT OR REPLACE INTO source_images(sha256,project_id,filename,mime,size_bytes,width,height,report,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                digest,
                project_id,
                sanitize_filename(filename, default="image"),
                f"image/{report.format}",
                len(data),
                report.width,
                report.height,
                json.dumps(rep),
                time.time(),
            ),
        )
        return self.get(project_id, digest)

    def get(self, project_id: str, sha256: str) -> dict:
        r = self.db.query_one(
            "SELECT * FROM source_images WHERE project_id=? AND sha256=?", (require_id(project_id, "project"), sha256)
        )
        if not r:
            raise NotFoundError("Source image not found.")
        r["report"] = loads(r["report"], {})
        return r

    def list(self, project_id: str) -> list[dict]:
        rows = self.db.query(
            "SELECT sha256 FROM source_images WHERE project_id=? ORDER BY created_at DESC",
            (require_id(project_id, "project"),),
        )
        return [self.get(project_id, r["sha256"]) for r in rows]

    def path(self, project_id: str, sha256: str) -> Path:
        r = self.get(project_id, sha256)
        return self.layout.source_dir(project_id) / f"{r['sha256']}.{EXT[r['mime'].split('/')[1]]}"

    def read_bytes(self, project_id: str, sha256: str) -> bytes:
        return self.path(project_id, sha256).read_bytes()

    def open(self, project_id: str, sha256: str) -> Image.Image:
        img, _ = load_image(
            self.read_bytes(project_id, sha256), max_bytes=self.max_bytes * 4, max_pixels=self.max_pixels, min_side=1
        )
        return img


_ = io
