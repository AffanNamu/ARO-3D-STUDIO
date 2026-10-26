#!/usr/bin/env python
"""Set up and run the GPU worker inside a notebook runtime (Google Colab) or any Linux box with an NVIDIA GPU.

    python scripts/lab_bootstrap.py setup  --engines triposg,hunyuan3d --root /content/lab
    python scripts/lab_bootstrap.py start  --engines triposg,hunyuan3d --root /content/lab --port 8000
    python scripts/lab_bootstrap.py status --root /content/lab
    python scripts/lab_bootstrap.py stop   --root /content/lab

Why a separate environment: the heavy engines were written for Python 3.10 and an older PyTorch than a notebook runtime ships
(Colab: Python 3.13, CUDA 13), and some pin libraries that cannot coexist with the Studio's. ``setup`` therefore builds an isolated
Python 3.10 environment with ``uv`` (no root needed, no system changes), installs one PyTorch build with its own CUDA libraries (no
``nvcc`` and no compiling), clones the engines at their current head and records the commit. The worker then runs in that
environment and the Studio talks to it over HTTP on localhost: exactly the architecture used later on a rented GPU server, so nothing is
thrown away when moving.

Nothing here downloads model weights: the worker does that on first use, from Hugging Face, pinned to the commit it resolves (recorded).
TRELLIS.2 is not set up by this script: it needs a 24 GB-class GPU and compiled CUDA extensions (see worker/install_engines.sh).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]

# PyPI's Linux wheels of torch 2.5.1 are the CUDA 12.4 build and pull in their own CUDA libraries (nvidia-* wheels): no toolkit and no
# compiler are needed on the machine, only a driver. T4 (sm_75) and newer GPUs are supported.
TORCH = ("torch==2.5.1", "torchvision==0.20.1")

WORKER_RUNTIME = [
    "fastapi",
    "uvicorn",
    "python-multipart",
    "pillow",
    "numpy==1.26.4",
    "trimesh",
    "fast-simplification",
    "huggingface_hub<1.0",
    "scipy",
]

# Pinned to the releases current when each engine was published; if pip reports a conflict, the log says which package.
ENGINES: dict[str, dict[str, Any]] = {
    "triposg": {
        "repo": "https://github.com/VAST-AI-Research/TripoSG",
        "dir": "TripoSG",
        "env": "TRIPOSG_DIR",
        "min_vram_mb": 8_000,
        "pip": [
            "diffusers==0.32.2",
            "transformers==4.49.0",
            "einops",
            "omegaconf",
            "scikit-image",
            "peft==0.14.0",
            "jaxtyping",
            "typeguard",
            "opencv-python-headless",
            "accelerate",
            "safetensors",
        ],
        "notes": "geometry only; the iso-surface step uses a CPU stand-in for the 'diso' CUDA extension (no compiler needed)",
    },
    "hunyuan3d": {
        "repo": "https://github.com/Tencent-Hunyuan/Hunyuan3D-2",
        "dir": "Hunyuan3D-2",
        "env": "HUNYUAN3D_DIR",
        "min_vram_mb": 6_000,
        "pip": [
            "diffusers==0.32.2",
            "transformers==4.49.0",
            "einops",
            "omegaconf",
            "opencv-python-headless",
            "pymeshlab",
            "pygltflib",
            "accelerate",
            "safetensors",
            "tqdm",
            "pyyaml",
        ],
        "notes": "EVALUATION ONLY: restricted licence (not valid in the EU, UK, South Korea; no training on outputs). Shape stage only",
    },
}


def plan(engines: list[str], gpu_mb: int | None) -> dict[str, Any]:
    """Which of the requested engines this GPU can run, and why not for the others. Pure function (unit-tested)."""
    unknown = [e for e in engines if e not in ENGINES and e != "trellis2"]
    if unknown:
        raise SystemExit(f"unknown engine(s) {unknown}: choose from {sorted(ENGINES)}")
    run: list[str] = []
    skipped: dict[str, str] = {}
    for e in engines:
        if e == "trellis2":
            skipped[e] = (
                "needs a 24 GB-class GPU and compiled CUDA extensions: use worker/install_engines.sh on a suitable machine"
            )
            continue
        need = ENGINES[e]["min_vram_mb"]
        if gpu_mb is None:
            skipped[e] = "no CUDA GPU detected"
        elif gpu_mb < need:
            skipped[e] = f"the GPU has {gpu_mb} MB; {e} documents {need} MB"
        else:
            run.append(e)
    return {"run": run, "skipped": skipped}


def gpu_memory_mb() -> int | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return int(out.stdout.strip().splitlines()[0]) if out.returncode == 0 and out.stdout.strip() else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def venv_python(root: Path) -> Path:
    return root / "venv" / "bin" / "python"


def sh(cmd: list[str], *, log: Path, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    """Run a command, append its full output to ``log``, and show the last lines if it fails."""
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a") as fh:
        fh.write("\n$ " + " ".join(cmd) + "\n")
        fh.flush()
        r = subprocess.run(cmd, cwd=cwd, env=env, stdout=fh, stderr=subprocess.STDOUT)
    if r.returncode != 0:
        tail = "".join(log.read_text().splitlines(keepends=True)[-60:])
        raise SystemExit(f"FAILED ({r.returncode}): {' '.join(cmd)}\n--- last lines of {log} ---\n{tail}")


def ensure_uv(log: Path) -> str:
    found = shutil.which("uv")
    if found:
        return found
    sh([sys.executable, "-m", "pip", "install", "-q", "uv"], log=log)
    return shutil.which("uv") or str(Path(sys.executable).parent / "uv")


def setup(engines: list[str], root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    log = root / "setup.log"
    p = plan(engines, gpu_memory_mb())
    if not p["run"]:
        raise SystemExit(f"none of the requested engines can run here: {p['skipped']}")
    uv = ensure_uv(log)
    py = venv_python(root)
    if not py.exists():
        print("creating an isolated Python 3.10 environment (uv downloads the interpreter) ...", flush=True)
        sh([uv, "venv", "--python", "3.10", str(root / "venv")], log=log)
    print("installing PyTorch (CUDA 12.4 build, a few GB: several minutes) ...", flush=True)
    sh([uv, "pip", "install", "--python", str(py), *TORCH], log=log)
    print("installing the worker runtime ...", flush=True)
    sh([uv, "pip", "install", "--python", str(py), *WORKER_RUNTIME], log=log)
    commits: dict[str, str] = {}
    for e in p["run"]:
        spec = ENGINES[e]
        print(f"installing {e} ...", flush=True)
        sh([uv, "pip", "install", "--python", str(py), *spec["pip"]], log=log)
        dest = root / spec["dir"]
        if not dest.exists():
            sh(["git", "clone", "--depth", "1", spec["repo"], str(dest)], log=log)
        head = subprocess.run(
            ["git", "-C", str(dest), "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        commits[e] = head
    probe = subprocess.run(
        [
            str(py),
            "-c",
            "import torch,sys;print(sys.version.split()[0],torch.__version__,torch.cuda.is_available(),torch.version.cuda)",
        ],
        capture_output=True,
        text=True,
    )
    info = {
        "root": str(root),
        "engines_ready": p["run"],
        "engines_skipped": p["skipped"],
        "engine_commits": commits,
        "venv_python_torch_cuda": probe.stdout.strip() or probe.stderr.strip()[-300:],
        "gpu_mb": gpu_memory_mb(),
    }
    (root / "setup.json").write_text(json.dumps(info, indent=2) + "\n")
    print(json.dumps(info, indent=2))
    if "True" not in probe.stdout:
        raise SystemExit(
            "PyTorch in the worker environment cannot see the GPU: " + (probe.stdout + probe.stderr)[-400:]
        )
    return info


def setup_blender(root: Path) -> str | None:
    """Optional: an isolated Python 3.11 with the ``bpy`` module (Blender as a library, a few hundred MB). Gives independent beauty renders and
    the FBX/USD re-import check. Returns the interpreter path, or None (with the reason printed) if it could not be set up: never fatal."""
    log = root / "setup-blender.log"
    try:
        uv = ensure_uv(log)
        py = root / "blender-venv" / "bin" / "python"
        if not py.exists():
            print("creating an isolated Python 3.11 environment for Blender ...", flush=True)
            sh([uv, "venv", "--python", "3.11", str(root / "blender-venv")], log=log)
        print("installing bpy (Blender as a Python module, several minutes) ...", flush=True)
        sh([uv, "pip", "install", "--python", str(py), "bpy", "numpy"], log=log)
        probe = subprocess.run(
            [str(py), "-c", "import bpy; print(bpy.app.version_string)"], capture_output=True, text=True, timeout=300
        )
        if probe.returncode != 0:
            raise SystemExit("bpy installed but cannot be imported: " + probe.stderr[-300:])
        print("Blender", probe.stdout.strip(), "ready:", py, flush=True)
        return str(py)
    except SystemExit as e:  # noqa: PERF203
        print("Blender is optional and could not be set up:", str(e)[:400], flush=True)
        return None


def worker_env(root: Path, token: str, engines: list[str]) -> dict[str, str]:
    env = {
        **os.environ,
        "ARO_WORKER_TOKEN": token,
        "PYTHONPATH": str(ROOT_DIR),
        "ARO_WORKER_CACHE": str(root / "weights"),
    }
    env.pop("PYTHONHOME", None)
    for e in engines:
        spec = ENGINES[e]
        env[spec["env"]] = str(root / spec["dir"])
    return env


def start(engines: list[str], root: Path, port: int, token: str | None) -> dict[str, Any]:
    info = json.loads((root / "setup.json").read_text()) if (root / "setup.json").exists() else {}
    ready = [e for e in engines if e in info.get("engines_ready", [])]
    if not ready:
        raise SystemExit("run `setup` first (and check which engines it could install)")
    stop(root, quiet=True)
    token = token or os.environ.get("ARO_WORKER_TOKEN") or __import__("secrets").token_urlsafe(24)
    logf = open(root / "worker.log", "ab")  # noqa: SIM115 - the child keeps writing to it after this function returns
    proc = subprocess.Popen(
        [
            str(venv_python(root)),
            "-m",
            "aro_worker",
            "--engines",
            ",".join(ready),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=worker_env(root, token, ready),
        stdout=logf,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    (root / "worker.pid").write_text(str(proc.pid))
    base = f"http://127.0.0.1:{port}"
    for _ in range(120):
        if proc.poll() is not None:
            raise SystemExit(
                "the worker exited at start-up:\n"
                + "".join((root / "worker.log").read_text().splitlines(keepends=True)[-40:])
            )
        try:
            urllib.request.urlopen(base + "/ping", timeout=2)  # noqa: S310
            break
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    else:
        raise SystemExit(
            "the worker did not answer /ping within 60 s:\n"
            + "".join((root / "worker.log").read_text().splitlines(keepends=True)[-40:])
        )
    out = {"url": base, "token": token, "pid": proc.pid, "engines": ready}
    (root / "worker.json").write_text(json.dumps({k: v for k, v in out.items() if k != "token"}, indent=2) + "\n")
    return out


def status(root: Path) -> dict[str, Any]:
    pid_file = root / "worker.pid"
    alive = False
    if pid_file.exists():
        try:
            os.kill(int(pid_file.read_text()), 0)
            alive = True
        except (OSError, ValueError):
            alive = False
    return {
        "worker_running": alive,
        "log_tail": "".join((root / "worker.log").read_text().splitlines(keepends=True)[-15:])
        if (root / "worker.log").exists()
        else "",
    }


def stop(root: Path, quiet: bool = False) -> None:
    pid_file = root / "worker.pid"
    if not pid_file.exists():
        return
    try:
        os.killpg(int(pid_file.read_text()), signal.SIGTERM)
    except (OSError, ValueError):
        pass
    pid_file.unlink(missing_ok=True)
    if not quiet:
        print("worker stopped")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["setup", "setup-blender", "start", "status", "stop", "plan"])
    ap.add_argument("--engines", default="triposg")
    ap.add_argument("--root", type=Path, default=Path("/content/lab"))
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--token", default="")
    a = ap.parse_args()
    engines = [e.strip() for e in a.engines.split(",") if e.strip()]
    if a.action == "plan":
        print(json.dumps(plan(engines, gpu_memory_mb()), indent=2))
    elif a.action == "setup":
        setup(engines, a.root)
    elif a.action == "setup-blender":
        print(setup_blender(a.root) or "")
    elif a.action == "start":
        r = start(engines, a.root, a.port, a.token or None)
        print(json.dumps({**r, "token": "(printed once below; never put it in a notebook cell's source)"}, indent=2))
        print("ARO_WORKER_TOKEN=" + r["token"])
    elif a.action == "status":
        print(json.dumps(status(a.root), indent=2))
    else:
        stop(a.root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
