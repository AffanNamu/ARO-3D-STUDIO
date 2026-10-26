"""Helpers the engine-lab notebook calls, so the notebook cells stay one or two lines and this logic is reviewable and testable."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return (r.stdout or r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"unavailable: {e}"


def environment(lab_root: Path) -> dict[str, Any]:
    """Everything needed to reproduce or diagnose a run, recorded next to its results."""
    setup = json.loads((lab_root / "setup.json").read_text()) if (lab_root / "setup.json").exists() else {}
    return {
        "studio_commit": _run(["git", "-C", str(ROOT_DIR), "rev-parse", "HEAD"]),
        "studio_branch": _run(["git", "-C", str(ROOT_DIR), "rev-parse", "--abbrev-ref", "HEAD"]),
        "notebook_python": platform.python_version(),
        "gpu": _run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"]),
        "worker_environment": setup,
    }


def show_results(out: Path) -> None:
    """Print the bake-off table and display every contact sheet (reference | overlay | best view | front/side/rear/top/3-4)."""
    from IPython.display import Image as IPImage
    from IPython.display import Markdown, display

    summary = out / "bakeoff-summary.md"
    if summary.exists():
        display(Markdown(summary.read_text()))
    for sheet in sorted(out.glob("*/sheet.png")):
        print("=====", sheet.parent.name)
        display(IPImage(filename=str(sheet), width=1100))
    for img in sorted(out.glob("*/blender/blender-3q.png")):
        print("===== Blender render (independent reader, real texture and lighting):", img.parent.parent.name)
        display(IPImage(filename=str(img), width=520))
    for f in sorted(out.glob("*/prepared.glb")):
        print(f.parent.name, "prepared.glb", round(f.stat().st_size / 1e6, 2), "MB")


def package(out: Path, lab_root: Path, dest: Path) -> list[Path]:
    """Two zips: ``lab-evidence-repo.zip`` (JSON, sheets, prepared GLBs, Unity packages, logs: safe to commit) and
    ``lab-raw-meshes.zip`` (the engines' untouched raw GLBs, large: keep, do not commit). Refuses an empty result."""
    dest.mkdir(parents=True, exist_ok=True)
    if not (out / "bakeoff-summary.json").exists():
        raise SystemExit("no bakeoff-summary.json: the run did not finish (see the worker log)")
    (out / "lab-environment.json").write_text(json.dumps(environment(lab_root), indent=2) + "\n")
    for name in ("worker.log", "setup.log"):
        if (lab_root / name).exists():
            tail = "".join((lab_root / name).read_text(errors="replace").splitlines(keepends=True)[-400:])
            (out / name).write_text(tail)
    repo_zip, raw_zip = dest / "lab-evidence-repo.zip", dest / "lab-raw-meshes.zip"
    with zipfile.ZipFile(repo_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.rglob("*")):
            if f.is_file() and f.name != "raw_output.glb":
                z.write(f, f.relative_to(out.parent))
    with zipfile.ZipFile(raw_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.rglob("raw_output.glb")):
            z.write(f, f.relative_to(out.parent))
    return [repo_zip, raw_zip]


def clean(out: Path) -> None:
    shutil.rmtree(out, ignore_errors=True)


def token_from_env() -> str:
    t = os.environ.get("ARO_WORKER_TOKEN", "")
    if not t:
        raise SystemExit("the worker has not been started in this session: run the 'start the worker' cell first")
    return t


if __name__ == "__main__":
    print(json.dumps(environment(Path(sys.argv[1] if len(sys.argv) > 1 else "/content/lab")), indent=2))
