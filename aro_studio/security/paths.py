"""Path-traversal prevention. All filesystem access goes through ``safe_join``."""

from __future__ import annotations

from pathlib import Path

from aro_studio.core.errors import SecurityError


def safe_join(root: str | Path, *parts: str) -> Path:
    """Join ``parts`` under ``root`` and guarantee the result cannot escape ``root``.

    Rejects absolute components, NULs, ``..`` traversal and symlink escapes.
    """
    root_p = Path(root).resolve()
    for part in parts:
        if "\x00" in part:
            raise SecurityError("Path contains a NUL byte.")
        if Path(part).is_absolute() or part.startswith(("/", "\\")) or (len(part) > 1 and part[1] == ":"):
            raise SecurityError("Absolute paths are not allowed.")
    candidate = root_p.joinpath(*parts).resolve()
    if candidate != root_p and root_p not in candidate.parents:
        raise SecurityError("Path escapes its permitted directory.", details={"attempted": "/".join(parts)[:200]})
    return candidate


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
