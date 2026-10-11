#!/usr/bin/env python
"""Split the smoke-test output into what belongs in git and what does not.

    python scripts/package_smoke_evidence.py --dir docs/acceptance/evidence/ai/smoke --out /content

Creates two zips:
  * smoke-evidence-repo.zip  - JSON + report, original inputs, six-view renders, prepared GLBs (each must be <= 8 MB).
                               Safe to commit under docs/acceptance/evidence/ai/smoke/.
  * smoke-raw-meshes.zip     - the untouched raw TripoSR meshes (large). Keep them (Drive), do NOT commit them;
                               their SHA-256 and sizes are in smoke-evidence.json.
Never includes model weights, caches, or anything outside --dir.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

MAX_REPO_FILE = 8_000_000


def package(src: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    repo_zip, raw_zip = out / "smoke-evidence-repo.zip", out / "smoke-raw-meshes.zip"
    skipped, repo_n, raw_n = [], 0, 0
    with (
        zipfile.ZipFile(repo_zip, "w", zipfile.ZIP_DEFLATED) as zr,
        zipfile.ZipFile(raw_zip, "w", zipfile.ZIP_DEFLATED) as zw,
    ):
        for f in sorted(p for p in src.rglob("*") if p.is_file()):
            rel = f.relative_to(src).as_posix()
            if rel.startswith("raw/"):
                zw.write(f, rel)
                raw_n += 1
            elif f.stat().st_size > MAX_REPO_FILE:
                skipped.append((rel, f.stat().st_size))
            else:
                zr.write(f, rel)
                repo_n += 1
    return {
        "repo_zip": str(repo_zip),
        "repo_files": repo_n,
        "repo_zip_bytes": repo_zip.stat().st_size,
        "repo_zip_sha256": hashlib.sha256(repo_zip.read_bytes()).hexdigest(),
        "raw_zip": str(raw_zip),
        "raw_files": raw_n,
        "raw_zip_bytes": raw_zip.stat().st_size,
        "too_large_for_git": skipped,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    src = Path(a.dir)
    if not (src / "smoke-evidence.json").is_file():
        print(f"no smoke-evidence.json in {src}: run scripts/real_inference_smoke.py first")
        return 2
    Path(a.out).mkdir(parents=True, exist_ok=True)
    r = package(src, Path(a.out))
    for k, v in r.items():
        print(f"{k}: {v}")
    if r["too_large_for_git"]:
        print("WARNING: these files exceed 8 MB and were left out of the repo zip:", r["too_large_for_git"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
