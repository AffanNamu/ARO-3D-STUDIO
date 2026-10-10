"""Safe archive handling: validate every member *before* extracting anything."""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path, PurePosixPath

from aro_studio.core.errors import SecurityError
from aro_studio.security.paths import safe_join


def validate_zip(
    zf: zipfile.ZipFile, *, max_members: int, max_uncompressed: int, max_ratio: int = 200
) -> list[zipfile.ZipInfo]:
    infos = zf.infolist()
    if len(infos) > max_members:
        raise SecurityError(f"Archive has {len(infos)} entries (limit {max_members}).")
    total = 0
    for info in infos:
        name = info.filename
        p = PurePosixPath(name)
        if p.is_absolute() or ".." in p.parts or "\\" in name or "\x00" in name or (len(name) > 1 and name[1] == ":"):
            raise SecurityError("Archive contains an unsafe path.", details={"member": name[:200]})
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise SecurityError("Archive contains a symbolic link.", details={"member": name[:200]})
        if info.flag_bits & 0x1:
            raise SecurityError("Encrypted archives are not supported.")
        total += info.file_size
        if total > max_uncompressed:
            raise SecurityError("Archive expands beyond the allowed size (possible zip bomb).")
        if (
            info.compress_size
            and info.file_size / max(info.compress_size, 1) > max_ratio
            and info.file_size > 1_000_000
        ):
            raise SecurityError("Archive compression ratio is suspicious (possible zip bomb).")
    return infos


def safe_extract_zip(
    archive: str | Path, dest: str | Path, *, max_members: int = 2000, max_uncompressed: int = 1_000_000_000
) -> list[Path]:
    """Extract ``archive`` into the (empty, private) ``dest`` directory using only validated members."""
    dest_p = Path(dest)
    dest_p.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    with zipfile.ZipFile(archive) as zf:
        infos = validate_zip(zf, max_members=max_members, max_uncompressed=max_uncompressed)
        for info in infos:
            target = safe_join(dest_p, info.filename)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with zf.open(info) as src, open(target, "wb") as dst:
                while chunk := src.read(1 << 20):
                    written += len(chunk)
                    if written > info.file_size + 1:  # lying header
                        raise SecurityError("Archive member is larger than its declared size.")
                    dst.write(chunk)
            out.append(target)
    return out
