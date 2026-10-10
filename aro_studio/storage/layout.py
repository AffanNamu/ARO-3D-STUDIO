"""On-disk layout. Paths are derived from validated ids only - never from user filenames.

data/
  studio.sqlite3
  logs/
  tmp/                                  scratch (cleaned on start)
  projects/<project_id>/
      source/                           uploaded concept images (named by content hash)
      generations/<generation_id>/      engine working output + logs
      assets/<asset_id>/{raw,processed,optimized,final}/<version_id>/
      exports/<export_id>/
      tmp/
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from aro_studio.core.enums import Stage
from aro_studio.core.ids import require_id
from aro_studio.security.paths import ensure_dir, safe_join


class StorageLayout:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        ensure_dir(self.root)
        for sub in ("projects", "logs", "tmp"):
            ensure_dir(self.root / sub)

    # -- paths --------------------------------------------------------------------------------
    def project_dir(self, project_id: str) -> Path:
        return safe_join(self.root, "projects", require_id(project_id, "project"))

    def source_dir(self, project_id: str) -> Path:
        return safe_join(self.project_dir(project_id), "source")

    def generation_dir(self, project_id: str, generation_id: str) -> Path:
        return safe_join(self.project_dir(project_id), "generations", require_id(generation_id, "generation"))

    def version_dir(self, project_id: str, asset_id: str, stage: Stage | str, version_id: str) -> Path:
        stage_s = Stage(stage).value
        return safe_join(
            self.project_dir(project_id),
            "assets",
            require_id(asset_id, "asset"),
            stage_s,
            require_id(version_id, "version"),
        )

    def export_dir(self, project_id: str, export_id: str) -> Path:
        return safe_join(self.project_dir(project_id), "exports", require_id(export_id, "export"))

    def logs_dir(self) -> Path:
        return self.root / "logs"

    def create_project_tree(self, project_id: str) -> Path:
        base = self.project_dir(project_id)
        for sub in ("source", "generations", "assets", "exports", "tmp"):
            ensure_dir(base / sub)
        return base

    # -- temp ---------------------------------------------------------------------------------
    @contextmanager
    def temp_dir(self, project_id: str | None = None) -> Iterator[Path]:
        """Private scratch directory (0700) inside the data dir, removed afterwards."""
        parent = self.project_dir(project_id) / "tmp" if project_id else self.root / "tmp"
        ensure_dir(parent)
        d = Path(tempfile.mkdtemp(prefix="work_", dir=parent))
        os.chmod(d, 0o700)
        try:
            yield d
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def clean_tmp(self) -> int:
        n = 0
        for d in [self.root / "tmp", *(self.root / "projects").glob("*/tmp")]:
            if d.is_dir():
                for child in d.iterdir():
                    shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink(missing_ok=True)
                    n += 1
        return n

    # -- sizes --------------------------------------------------------------------------------
    def dir_size(self, path: Path) -> int:
        total = 0
        for dirpath, _dirs, files in os.walk(path):
            for f in files:
                try:
                    total += (Path(dirpath) / f).stat().st_size
                except OSError:
                    pass
        return total

    def disk_free(self) -> int:
        return shutil.disk_usage(self.root).free


def make_readonly(path: Path) -> None:
    """Best effort: mark an immutable version directory read-only (defence in depth)."""
    for p in sorted(path.rglob("*"), reverse=True):
        try:
            os.chmod(p, 0o555 if p.is_dir() else 0o444)
        except OSError:
            pass
    try:
        os.chmod(path, 0o555)  # noqa: S103 - read-only on purpose (immutable versions)
    except OSError:
        pass


def make_writable(path: Path) -> None:
    for p in [path, *path.rglob("*")]:
        try:
            os.chmod(p, 0o755 if p.is_dir() else 0o644)
        except OSError:
            pass


def remove_tree(path: Path) -> None:
    if path.exists():
        make_writable(path)
        shutil.rmtree(path, ignore_errors=False)
