"""Optional Blender backend: FBX / USD / .blend export and an independent re-import check, through a separate process.

The Studio never imports ``bpy`` (heavy, not thread-safe). It runs ``blender_worker.py`` in a child process using, in this order:

1. ``ARO_BLENDER_PYTHON``: a Python interpreter that has the ``bpy`` module installed (``pip install bpy`` on a supported Python, 3.11 for
   Blender 5.0), or
2. ``ARO_BLENDER_BIN`` / a ``blender`` executable on PATH (Blender runs headless: ``--background --factory-startup --python``), or
3. the current interpreter, if it can import ``bpy``.

Like an engine, the backend reports "available" or exactly why not and how to enable it; nothing is faked when it is absent.
Every export is re-imported by Blender and compared with the source (triangles, size in metres, materials, wired maps).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aro_studio.core.errors import EngineUnavailableError, ModelError

BLENDER_FORMATS = ("fbx", "usd", "blend")
TARGETS = ("unity", "unreal", "generic")
RESULT_TAG = "ARO_BLENDER_RESULT "
WORKER = Path(__file__).with_name("blender_worker.py")

HOW_TO_ENABLE = [
    "Install the Blender Python module in a Python 3.11 environment: python3.11 -m venv blender-env && blender-env/bin/pip install bpy",
    "Then set ARO_BLENDER_PYTHON=/path/to/blender-env/bin/python (or install Blender and set ARO_BLENDER_BIN=/path/to/blender).",
]


@dataclass
class BlenderBackend:
    python: str = ""
    binary: str = ""
    timeout_s: float = 600.0
    _cache: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_env(cls, python: str = "", binary: str = "") -> BlenderBackend:
        return cls(python or os.environ.get("ARO_BLENDER_PYTHON", ""), binary or os.environ.get("ARO_BLENDER_BIN", ""))

    # -- how to run ------------------------------------------------------------------------------
    def _command(self, worker_args: list[str]) -> list[str] | None:
        if self.python:
            return [self.python, str(WORKER), *worker_args]
        exe = self.binary or shutil.which("blender") or ""
        if exe:
            return [exe, "--background", "--factory-startup", "--python", str(WORKER), "--", *worker_args]
        return None

    def availability(self) -> dict[str, Any]:
        """{"ok": bool, "reasons": [...], "how": [...], "version": str|None}; cached for the life of the object."""
        if "av" in self._cache:
            return self._cache["av"]
        reasons: list[str] = []
        version = None
        if self.python and not Path(self.python).exists():
            reasons.append(f"ARO_BLENDER_PYTHON points to a file that does not exist: {self.python}")
        elif self.python:
            r = subprocess.run(  # noqa: S603 - the interpreter is operator configuration (ARO_BLENDER_PYTHON)
                [self.python, "-c", "import bpy; print(bpy.app.version_string)"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if r.returncode == 0:
                version = r.stdout.strip().splitlines()[-1]
            else:
                reasons.append(
                    "the interpreter in ARO_BLENDER_PYTHON cannot import bpy: "
                    + (r.stderr.strip().splitlines() or ["?"])[-1][:200]
                )
        elif self.binary or shutil.which("blender"):
            exe = self.binary or shutil.which("blender") or ""
            r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=120)  # noqa: S603 - operator-configured executable
            if r.returncode == 0:
                version = r.stdout.strip().splitlines()[0]
            else:
                reasons.append(f"'{exe} --version' failed")
        else:
            r = subprocess.run([sys.executable, "-c", "import bpy"], capture_output=True, text=True, timeout=120)
            if r.returncode == 0:
                self.python = sys.executable
                version = "bpy (current interpreter)"
            else:
                reasons.append(
                    "Blender is not configured: no ARO_BLENDER_PYTHON, no ARO_BLENDER_BIN, no 'blender' on PATH, and bpy is not importable here"
                )
        av = {"ok": not reasons, "reasons": reasons, "how": [] if not reasons else HOW_TO_ENABLE, "version": version}
        self._cache["av"] = av
        return av

    # -- work ------------------------------------------------------------------------------------
    def _run(self, worker_args: list[str]) -> dict[str, Any]:
        av = self.availability()
        if not av["ok"]:
            raise EngineUnavailableError(
                "The Blender export backend is not available: " + " ".join(av["reasons"]),
                recommended_action=" ".join(av["how"]),
            )
        cmd = self._command(worker_args)
        assert cmd is not None
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout_s)  # noqa: S603 - operator-configured executable, files written by the Studio
        except subprocess.TimeoutExpired as e:
            raise ModelError(
                f"Blender did not finish within {self.timeout_s:.0f} s.", recommended_action="Try a smaller model."
            ) from e
        line = next((ln for ln in reversed(r.stdout.splitlines()) if ln.startswith(RESULT_TAG)), None)
        if line is None:
            raise ModelError(
                "Blender produced no result.",
                recommended_action="See the details for Blender's own output.",
                details={"returncode": r.returncode, "stdout": r.stdout[-1500:], "stderr": r.stderr[-1500:]},
            )
        return json.loads(line[len(RESULT_TAG) :])

    def inspect(self, path: Path, probe: int = 0) -> dict[str, Any]:
        """What Blender sees in ``path``; with ``probe`` also the base-colour image sampled at that many UV corners (see the worker)."""
        res = self._run(["inspect", "--in", str(path), *(["--probe", str(probe)] if probe else [])])
        if not res.get("ok"):
            raise ModelError(f"Blender could not read {path.name}: {res.get('error')}", details=res)
        return res

    def convert(self, src: Path, dst: Path, fmt: str, target: str = "unity") -> dict[str, Any]:
        """Convert ``src`` (a GLB) to ``fmt`` and verify by re-importing. Returns the worker's report (``ok`` false if a check failed)."""
        if fmt not in BLENDER_FORMATS:
            raise ModelError(f"The Blender backend writes {BLENDER_FORMATS}, not '{fmt}'.")
        res = self._run(["convert", "--in", str(src), "--out", str(dst), "--format", fmt, "--target", target])
        if res.get("error"):
            raise ModelError(f"Blender could not write {fmt}: {res['error']}", details=res)
        return res

    def render(
        self,
        src: Path,
        out_dir: Path,
        views: tuple[str, ...] = ("front", "side", "rear", "top", "3q"),
        size: int = 640,
        samples: int = 24,
    ) -> list[Path]:
        """Beauty renders of an asset's LOD0 by Blender (Cycles, CPU): an independent look with real textures, normal map and PBR lighting."""
        res = self._run(
            [
                "render",
                "--in",
                str(src),
                "--out-dir",
                str(out_dir),
                "--views",
                ",".join(views),
                "--size",
                str(size),
                "--samples",
                str(samples),
            ]
        )
        if not res.get("ok"):
            raise ModelError(f"Blender could not render {src.name}: {res.get('error')}", details=res)
        return [Path(p) for p in res["images"]]

    def turntable(self, src: Path, out_gif: Path, frames: int = 24, size: int = 384, samples: int = 12) -> Path:
        """A 360-degree turntable GIF of LOD0 rendered by Blender: the quickest way to look at a model from every side."""
        from PIL import Image

        frames = max(4, min(int(frames), 72))
        views = tuple(f"turn-{round(360 * i / frames):03d}" for i in range(frames))
        tmp = out_gif.parent / f".{out_gif.stem}-frames"
        paths = self.render(src, tmp, views=views, size=size, samples=samples)
        imgs = [Image.open(p).convert("P", palette=Image.Palette.ADAPTIVE) for p in paths]
        out_gif.parent.mkdir(parents=True, exist_ok=True)
        imgs[0].save(out_gif, save_all=True, append_images=imgs[1:], duration=80, loop=0, optimize=True)
        for p in paths:
            p.unlink(missing_ok=True)
        tmp.rmdir()
        return out_gif
