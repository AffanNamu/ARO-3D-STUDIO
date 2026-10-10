"""Filename sanitization. Uploaded filenames are never used as storage paths."""

from __future__ import annotations

import re
import unicodedata

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10)),
}


def sanitize_filename(name: str, *, default: str = "file", max_len: int = 80) -> str:
    """Return a display-safe filename: ASCII, no separators, no leading dots, bounded length.

    The result is for *display and metadata only*; storage paths are always generated from ids.
    """
    name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii")
    name = name.replace("\\", "/").split("/")[-1]  # drop any directory component
    name = name.replace("\x00", "")
    name = _SAFE.sub("_", name).strip("._-")
    if not name:
        return default
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    stem = stem.strip("._-") or "file"
    if stem.lower() in _WINDOWS_RESERVED:
        stem = f"_{stem}"
    ext = ext[:10]
    stem = stem[: max_len - len(ext) - 1] if ext else stem[:max_len]
    return f"{stem}.{ext}" if ext else stem


def slugify(name: str, *, default: str = "asset", max_len: int = 64) -> str:
    """Slug such as ``ARO-TITAN-480`` for node/package naming (Unity-safe)."""
    name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-")
    return (name[:max_len].strip("-")) or default
