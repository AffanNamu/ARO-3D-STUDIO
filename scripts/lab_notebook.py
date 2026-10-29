"""Helpers the engine-lab notebook calls, so the notebook cells stay one or two lines and this logic is reviewable and testable."""

from __future__ import annotations

import glob
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import zipfile
from collections.abc import Callable, Sequence
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
    for gif in sorted(out.glob("*/blender/turntable.gif")):
        print("===== turntable (Blender):", gif.parent.parent.name)
        display(IPImage(filename=str(gif), width=384))
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


# --- runs that survive the notebook cell -------------------------------------------------------------------------------------------
# A Colab cell can be interrupted (stop button, Ctrl+M I, "Interrupt execution", a browser reconnect). A `!python ...` cell then dies
# with it, and a 10-minute GPU run is lost. The long run therefore lives in its OWN session, writes a log file and an exit-code file, and
# the cell only follows the log: interrupting the cell stops the watching, never the run.

_CHILDREN: dict[int, subprocess.Popen[bytes]] = {}


def _alive(pid: int) -> bool:
    child = _CHILDREN.get(pid)
    if child is not None:
        return child.poll() is None  # also reaps the finished child, so it cannot linger as a zombie
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:  # a zombie of another process still answers kill(0)
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def _paths(log: Path) -> tuple[Path, Path, Path]:
    return log.with_suffix(".pid"), log.with_suffix(".exit"), log.with_suffix(".cmd")


def run_state(log: Path) -> dict[str, Any]:
    """running / finished (with exit code) / none, for the detached run that writes ``log``."""
    pid_f, exit_f, cmd_f = _paths(log)
    pid = int(pid_f.read_text()) if pid_f.exists() and pid_f.read_text().strip().isdigit() else None
    code = int(exit_f.read_text()) if exit_f.exists() and exit_f.read_text().strip().lstrip("-").isdigit() else None
    if pid is not None and code is None and _alive(pid):
        return {"state": "running", "pid": pid, "cmd": cmd_f.read_text() if cmd_f.exists() else ""}
    if code is not None:
        return {"state": "finished", "exit_code": code, "cmd": cmd_f.read_text() if cmd_f.exists() else ""}
    if pid is not None:
        return {
            "state": "finished",
            "exit_code": None,
            "cmd": cmd_f.read_text() if cmd_f.exists() else "",
        }  # died without a code
    return {"state": "none"}


def start_detached(cmd: Sequence[str], log: Path, cwd: Path, env: dict[str, str] | None = None) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    pid_f, exit_f, cmd_f = _paths(log)
    for f in (log, pid_f, exit_f):
        f.unlink(missing_ok=True)
    cmd_f.write_text(json.dumps(list(cmd)))
    logf = open(log, "wb")  # noqa: SIM115 - the child keeps writing after this function returns
    proc = subprocess.Popen(  # noqa: S603 - the command is built by the notebook from its own cells
        ["bash", "-c", '"$@"; echo $? > "$ARO_EXIT_FILE"', "bash", *cmd],  # noqa: S607
        cwd=str(cwd),
        env={**os.environ, **(env or {}), "ARO_EXIT_FILE": str(exit_f)},
        stdout=logf,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    logf.close()
    _CHILDREN[proc.pid] = proc
    pid_f.write_text(str(proc.pid))
    return proc.pid


def _print_new(log: Path, pos: int, out: Callable[[str], None]) -> int:
    if not log.exists():
        return pos
    with open(log, "rb") as f:
        f.seek(pos)
        chunk = f.read()
    if chunk:
        out(chunk.decode("utf-8", errors="replace").rstrip("\n"))
    return pos + len(chunk)


def follow(
    log: Path,
    poll_s: float = 3.0,
    sleep: Callable[[float], None] = time.sleep,
    out: Callable[[str], None] = print,
) -> int | None:
    """Print the log as it grows until the run ends; return its exit code. If THIS cell is interrupted, say so and return None:
    the run itself keeps going."""
    pos = 0
    try:
        while True:
            pos = _print_new(log, pos, out)
            if run_state(log)["state"] != "running":
                break
            sleep(poll_s)
        _print_new(log, pos, out)
        return run_state(log).get("exit_code")
    except KeyboardInterrupt:
        out(
            "\n>>> This cell was interrupted, but the run was NOT stopped: it is still going in the background.\n"
            ">>> Run this cell again to follow it (it will not start a second run), or run the diagnose cell at the bottom."
        )
        return None


def run_detached(
    cmd: Sequence[str],
    log: Path,
    cwd: Path,
    env: dict[str, str] | None = None,
    rerun: bool = False,
    poll_s: float = 3.0,
    sleep: Callable[[float], None] = time.sleep,
    out: Callable[[str], None] = print,
) -> int | None:
    """Start ``cmd`` detached and follow it. Running this again while it is still going re-attaches instead of starting a second run;
    after a SUCCESSFUL identical run it shows that run's log instead of repeating the work (``rerun=True`` forces it)."""
    st = run_state(log)
    same = st.get("cmd") == json.dumps(list(cmd))
    if st["state"] == "running":
        out(f"A run is already in progress (pid {st['pid']}); following it. Its log: {log}")
    elif st["state"] == "finished" and st.get("exit_code") == 0 and same and not rerun:
        out("An identical run already finished successfully; showing its log. (Set RERUN = True to run it again.)")
    else:
        pid = start_detached(cmd, log, cwd, env)
        out(f"Started (pid {pid}, detached: interrupting this cell will not stop it). Log: {log}")
    return follow(log, poll_s, sleep, out)


def stop_detached(log: Path) -> bool:
    st = run_state(log)
    if st["state"] != "running":
        return False
    try:
        os.killpg(st["pid"], 15)
    except OSError:
        return False
    return True


# --- what happened on this VM ------------------------------------------------------------------------------------------------------


def worker_job_files(lab_root: Path) -> list[Path]:
    """The engines' raw GLBs still held by the worker (it keeps each finished job for an hour)."""
    found = list((lab_root / "worker-jobs").glob("*.glb")) + [Path(p) for p in glob.glob("/tmp/aro_worker_*/*.glb")]  # noqa: S108
    return sorted(set(found), key=lambda f: f.stat().st_mtime)


def _tail(path: Path, n: int) -> str:
    if not path.exists():
        return "(no such file)"
    return "".join(path.read_text(errors="replace").splitlines(keepends=True)[-n:]).rstrip() or "(empty)"


def _meminfo() -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        for ln in Path("/proc/meminfo").read_text().splitlines():
            k, _, v = ln.partition(":")
            if k in ("MemTotal", "MemAvailable"):
                out[k] = int(v.split()[0]) // 1024
    except (OSError, ValueError):
        pass
    return out


def diagnose(
    lab_root: Path = Path("/content/lab"), log: Path | None = None, out: Callable[[str], None] = print
) -> dict[str, Any]:
    """Facts about a run that stopped: was it a signal or a fault, is the worker alive, did the GPU job finish, is memory exhausted,
    and which raw meshes can still be rescued. It only reads."""
    log = log or lab_root / "bakeoff.log"
    info: dict[str, Any] = {"now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}
    try:
        info["vm_uptime_min"] = round(float(Path("/proc/uptime").read_text().split()[0]) / 60, 1)
    except (OSError, ValueError):
        pass
    info["memory_mb"] = _meminfo()
    info["disk_free_gb"] = round(shutil.disk_usage(lab_root if lab_root.exists() else Path("/")).free / 1e9, 1)
    info["gpu"] = _run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total", "--format=csv,noheader"])
    pid_f = lab_root / "worker.pid"
    info["worker_alive"] = bool(
        pid_f.exists() and pid_f.read_text().strip().isdigit() and _alive(int(pid_f.read_text()))
    )
    info["bakeoff_run"] = run_state(log)
    info["worker_job_files"] = [
        {
            "file": str(f),
            "mb": round(f.stat().st_size / 1e6, 1),
            "modified": time.strftime("%H:%M:%S", time.gmtime(f.stat().st_mtime)),
        }
        for f in worker_job_files(lab_root)
    ]
    dm = _run(["dmesg"])
    info["kernel_kills"] = [
        ln for ln in dm.splitlines() if "out of memory" in ln.lower() or "killed process" in ln.lower()
    ][-3:]
    out(json.dumps(info, indent=2))
    out("\n--- worker.log (last 25 lines)\n" + _tail(lab_root / "worker.log", 25))
    out("\n--- bakeoff.log (last 25 lines)\n" + _tail(log, 25))
    st = info["bakeoff_run"]
    code = st.get("exit_code")
    out("\n--- reading it")
    if st["state"] == "running":
        out("The run is STILL GOING. Re-run the cell that started it to follow it; nothing is lost.")
    elif code == 130:
        out(
            "Exit 130 = the run received an interrupt (SIGINT): something external stopped it, it was not an engine fault."
        )
    elif code == 0:
        out("The run finished successfully.")
    elif code is not None:
        out(f"The run ended with exit code {code}: read the end of bakeoff.log above.")
    if info["kernel_kills"]:
        out("The kernel log shows a process killed for memory: this was an out-of-memory kill, not an interrupt.")
    if not pid_f.exists():
        out(
            f"No {pid_f} here: the worker was not started by this notebook's start cell, so its state cannot be judged from this folder."
        )
    elif not info["worker_alive"]:
        out("The worker is NOT running (the runtime may have been recycled): its in-memory jobs are gone.")
    if info["worker_job_files"]:
        out(
            f"{len(info['worker_job_files'])} raw engine mesh(es) are still on this VM: run rescue_raw_meshes() before anything else."
        )
    return info


def rescue_raw_meshes(lab_root: Path = Path("/content/lab"), dest: Path = Path("/content/lab/rescued")) -> Path | None:
    """Zip the raw GLBs the worker still holds (one per finished job) so they can be downloaded. Raw engine meshes are large and
    stay out of git; this is only so a GPU run is never lost."""
    files = worker_job_files(lab_root)
    if not files:
        print("No raw meshes found on this VM (the worker keeps them for an hour; a recycled runtime loses them).")
        return None
    dest.mkdir(parents=True, exist_ok=True)
    z = dest / "rescued-raw-meshes.zip"
    listing = []
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            sha = hashlib.sha256(f.read_bytes()).hexdigest()
            zf.write(f, f"{f.stem}-{sha[:8]}.glb")
            listing.append(
                {
                    "file": f.name,
                    "sha256": sha,
                    "bytes": f.stat().st_size,
                    "modified_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(f.stat().st_mtime)),
                }
            )
        zf.writestr("listing.json", json.dumps(listing, indent=2) + "\n")
    print("rescued", len(files), "mesh(es):", json.dumps(listing))
    return z


def clean(out: Path) -> None:
    shutil.rmtree(out, ignore_errors=True)


def token_from_env() -> str:
    t = os.environ.get("ARO_WORKER_TOKEN", "")
    if not t:
        raise SystemExit("the worker has not been started in this session: run the 'start the worker' cell first")
    return t


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "environment"
    root = Path(sys.argv[2] if len(sys.argv) > 2 else "/content/lab")
    if action == "diagnose":
        diagnose(root)
    elif action == "rescue":
        rescue_raw_meshes(root, root / "rescued")
    else:
        print(json.dumps(environment(Path(action) if action != "environment" else root), indent=2))
