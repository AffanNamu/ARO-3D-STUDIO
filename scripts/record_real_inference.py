#!/usr/bin/env python
"""Run REAL TripoSR inference on this host and record the evidence (Phase 2).

    python scripts/record_real_inference.py --image concept.png [--out docs/acceptance/evidence/ai] [--up +Z --forward +X]

What it does, in order (each step is recorded; the first failure is recorded and stops the run - nothing is faked):
  1. environment + hardware (platform, python, torch, CUDA device, VRAM, nvidia-smi)
  2. gates: lock complete (revision + checksums + licence evidence)? weights present and matching the lock? engine available?
  3. real generation through the normal job queue (download pinned weights -> verify -> load -> infer), timed, peak VRAM
  4. the raw mesh: format, triangle count, extents, bounds, finite check, six reference renders
  5. the post-reconstruction pipeline (aro_studio.processing.ai_pipeline) on that REAL raw mesh
  6. GLB export + Khronos validation + export integrity re-read
  7. ``inference-evidence.json`` with a status per claim. If any gate is closed the file says BLOCKED with the reasons.

The input image is whatever you pass with ``--image``. ``--titan-render`` uses a render of the procedural TITAN 480 as the
concept image; that is a legitimate *input* but is recorded as such. The procedural asset is never used as an output.

Exit code 0 only if inference actually ran and produced a finite mesh. A skipped/blocked run exits 3.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EVIDENCE_NAME = "inference-evidence.json"


def sh(cmd: list[str]) -> str | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


class VramPoller(threading.Thread):
    """Samples nvidia-smi (all processes on the GPU) so the peak is not only torch's own allocator view."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.peak_mb = 0
        self.samples = 0
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            out = sh(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"])
            if out:
                try:
                    self.peak_mb = max(self.peak_mb, max(int(x) for x in out.split()))
                    self.samples += 1
                except ValueError:
                    pass
            self._stop.wait(0.5)

    def stop(self) -> None:
        self._stop.set()


def environment() -> dict:
    env: dict = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "machine": platform.machine(),
        "nvidia_smi": sh(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"]),
        "torch": None,
        "cuda": None,
    }
    try:
        import torch

        env["torch"] = torch.__version__
        env["cuda"] = {
            "available": bool(torch.cuda.is_available()),
            "version": torch.version.cuda,
            "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "total_vram_mb": int(torch.cuda.get_device_properties(0).total_memory / 2**20)
            if torch.cuda.is_available()
            else None,
        }
    except Exception as e:  # noqa: BLE001
        env["torch_error"] = f"{type(e).__name__}: {e}"
    try:
        import tsr  # noqa: F401

        env["tsr_importable"] = True
    except Exception as e:  # noqa: BLE001
        env["tsr_importable"] = False
        env["tsr_error"] = f"{type(e).__name__}: {e}"
    return env


def six_views(scene, out: Path) -> list[str]:
    from aro_studio.utils.render import render_asset_scene

    out.mkdir(parents=True, exist_ok=True)
    names = []
    for label, az, el in (
        ("front", 0, 5),
        ("rear", 180, 5),
        ("left", 90, 5),
        ("right", -90, 5),
        ("top", 0, 85),
        ("three_quarter", 40, 15),
    ):
        p = out / f"{label}.png"
        render_asset_scene(scene, azimuth_deg=az, elevation_deg=el, size=768, background=(236, 236, 236)).save(p)
        names.append(p.name)
    return names


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", help="concept image (PNG/JPG) to reconstruct")
    ap.add_argument("--titan-render", action="store_true", help="use a render of the procedural TITAN 480 as the INPUT")
    ap.add_argument("--out", default=str(ROOT / "docs/acceptance/evidence/ai"))
    ap.add_argument("--preset", default="BALANCED")
    ap.add_argument("--allow-cpu", action="store_true", help="permit a (slow) CPU run; recorded as such")
    ap.add_argument(
        "--up", default=None, help="native up axis of the model output, e.g. +Z (default: engine hint, flagged)"
    )
    ap.add_argument("--forward", default=None, help="native forward axis, e.g. +X (default: guessed, flagged)")
    ap.add_argument("--length-m", type=float, default=6.5)
    ap.add_argument("--timeout-s", type=int, default=3600)
    a = ap.parse_args()
    if not a.image and not a.titan_render:
        ap.error("pass --image PATH or --titan-render")

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ev: dict = {
        "schema": 1,
        "recorded_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_commit": sh(["git", "-C", str(ROOT), "rev-parse", "HEAD"]),
        "environment": environment(),
        "input": {"image": a.image, "titan_render": bool(a.titan_render)},
        "status": {"real_inference": "BLOCKED", "pipeline": "BLOCKED", "validated_production_asset": "BLOCKED"},
        "blockers": [],
        "steps": [],
    }

    def finish(code: int) -> int:
        (out / EVIDENCE_NAME).write_text(json.dumps(ev, indent=2, default=str) + "\n")
        print(json.dumps({"status": ev["status"], "blockers": ev["blockers"]}, indent=2))
        print(f"evidence: {out / EVIDENCE_NAME}")
        return code

    # ---- gates --------------------------------------------------------------------------------------------------------
    from aro_studio.engines.manager import resolve_device
    from aro_studio.engines.weights import load_lock

    lock = load_lock("triposr")
    ev["lock"] = {
        "code": lock.code,
        "revision": lock.weights.revision,
        "missing": lock.missing(),
    }
    if ev["lock"]["missing"]:
        ev["blockers"].append(
            "model lock incomplete - run `python scripts/pin_triposr_weights.py --by <you>` on a host with Hugging Face "
            "access, review and commit the diff: " + "; ".join(ev["lock"]["missing"])
        )
    device = resolve_device("auto")
    ev["device"] = device
    if device != "cuda" and not a.allow_cpu:
        ev["blockers"].append("no CUDA device visible to torch (use a GPU host, or --allow-cpu for a slow CPU run)")
    from aro_studio.config import Settings
    from aro_studio.engines.triposr import TripoSREngine

    probe = TripoSREngine().availability(device)
    ev["engine_availability"] = {"ok": probe.ok, "reasons": list(probe.reasons)}
    if not probe.ok:
        ev["blockers"].append("TripoSR engine unavailable: " + "; ".join(probe.reasons))
    if ev["blockers"]:
        return finish(3)

    # ---- real generation ----------------------------------------------------------------------------------------------
    from aro_studio.app_context import build_context

    work = Path(tempfile.mkdtemp(prefix="aro_real_"))
    ctx = build_context(Settings(data_dir=work / "data", device=device))
    poller = VramPoller()
    try:
        p = ctx.projects.create("real-inference-evidence")
        asset = ctx.assets.create_asset(p["project_id"], "real-inference", "heavy_truck")
        if a.titan_render:
            import io

            from aro_studio.utils.render import render_asset_scene
            from aro_studio.vehicles.titan480 import build_titan480

            buf = io.BytesIO()
            render_asset_scene(
                build_titan480(), azimuth_deg=40, elevation_deg=10, size=1024, background=(236, 236, 236)
            ).save(buf, "PNG")
            data, fname = buf.getvalue(), "titan-render.png"
        else:
            data, fname = Path(a.image).read_bytes(), Path(a.image).name
        src = ctx.sources.add_image(p["project_id"], fname, data)
        ev["input"]["sha256"] = src["sha256"]
        (out / "input").mkdir(exist_ok=True)
        (out / "input" / fname).write_bytes(data)

        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.reset_peak_memory_stats()
        except Exception:  # noqa: BLE001
            torch = None  # type: ignore[assignment]
        poller.start()
        t0 = time.perf_counter()
        job = ctx.jobs.wait(
            ctx.jobs.submit(
                "generation",
                {
                    "project_id": p["project_id"],
                    "asset_id": asset["asset_id"],
                    "image_sha256": src["sha256"],
                    "engine_id": "triposr",
                    "preset": a.preset,
                },
            )["job_id"],
            timeout=a.timeout_s,
        )
        wall = time.perf_counter() - t0
        poller.stop()
        gen = {
            "job_state": job["state"],
            "wall_seconds": round(wall, 2),
            "result": job.get("result"),
            "error": job.get("error"),
            "peak_vram_nvidia_smi_mb": poller.peak_mb or None,
        }
        try:
            if torch is not None and torch.cuda.is_available():
                gen["peak_vram_torch_allocated_mb"] = round(torch.cuda.max_memory_allocated() / 2**20, 1)
                gen["peak_vram_torch_reserved_mb"] = round(torch.cuda.max_memory_reserved() / 2**20, 1)
        except Exception:  # noqa: BLE001
            pass
        ev["generation"] = gen
        ran = job["state"] == "COMPLETED" and bool((job.get("result") or {}).get("model_ran"))
        if not ran:
            ev["blockers"].append(f"generation job ended {job['state']}: {job.get('error')}")
            return finish(1)

        # ---- the raw mesh ---------------------------------------------------------------------------------------------
        import numpy as np

        raw_id = job["result"]["version_id"]
        raw = ctx.assets.load_scene(raw_id)
        mesh = raw.combined()
        finite = bool(np.isfinite(np.asarray(mesh.vertices)).all())
        ev["raw"] = {
            "version_id": raw_id,
            "provenance": raw.manifest.provenance.model_dump() if raw.manifest.provenance else None,
            "triangles": int(len(mesh.faces)),
            "vertices": int(len(mesh.vertices)),
            "extents": [float(x) for x in mesh.extents],
            "bounds": [[float(x) for x in b] for b in mesh.bounds],
            "finite": finite,
            "has_vertex_colors": bool(getattr(mesh.visual, "kind", None) == "vertex"),
            "watertight": bool(mesh.is_watertight),
            "renders": six_views(raw, out / "raw-views"),
        }
        shutil.copy2(job["result"].get("raw_file", "") or "/dev/null", out / "raw-output") if job["result"].get(
            "raw_file"
        ) else None
        if not finite or len(mesh.faces) < 100:
            ev["blockers"].append("model returned a non-finite or near-empty mesh")
            return finish(1)
        ev["status"]["real_inference"] = "PASS"

        # ---- pipeline on the REAL raw mesh ------------------------------------------------------------------------
        from aro_studio.processing.ai_pipeline import AIPipelineOptions, run_ai_pipeline

        opts = AIPipelineOptions(length_m=a.length_m)
        if a.up:
            opts.up = a.up
        if a.forward:
            opts.forward = a.forward
        rep = run_ai_pipeline(ctx.processing, ctx.assets, raw_id, opts)
        ev["pipeline"] = {k: rep[k] for k in ("ok", "source_axes", "needs_human", "final_version_id", "options")}
        ev["pipeline"]["steps"] = [
            {k: s[k] for k in ("name", "status", "seconds")} for s in rep["steps"] if isinstance(s, dict)
        ]
        ev["pipeline"]["validation"] = (
            {k: rep["validation"][k] for k in ("status", "overall", "critical_failures", "major_failures")}
            if rep.get("validation")
            else None
        )
        ev["status"]["pipeline"] = "PASS" if rep["ok"] else "FAIL"
        if not rep["ok"]:
            ev["blockers"].append(
                "post-reconstruction pipeline stopped: " + json.dumps(rep["steps"][-1], default=str)[:400]
            )
            return finish(1)
        final_id = rep["final_version_id"]
        final = ctx.assets.load_scene(final_id)
        ev["final_renders"] = six_views(final, out / "final-views")

        # ---- export + integrity -----------------------------------------------------------------------------------
        e = ctx.exports.export(final_id, "glb")
        ev["export"] = {
            "status": e["status"],
            "size_bytes": e.get("size_bytes"),
            "sha256": e.get("sha256"),
            "khronos": e["report"].get("khronos"),
            "verification_ok": e["report"]["verification"]["ok"],
        }
        if e["status"] == "COMPLETED":
            shutil.copy2(ctx.exports.file_path(e["export_id"]), out / "real-asset.glb")
        vstat = (rep.get("validation") or {}).get("status")
        if rep["ok"] and e["status"] == "COMPLETED" and vstat == "PRODUCTION_READY":
            ev["status"]["validated_production_asset"] = "PASS"
        elif rep["ok"]:
            ev["status"]["validated_production_asset"] = "PARTIAL"
            ev["blockers"].append(
                f"validation status {vstat}: a vehicle specification (wheels/axles/components) and human review of "
                f"orientation/forward axis are required before this can be PRODUCTION_READY"
            )
        return finish(0)
    finally:
        poller.stop()
        ctx.close()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
