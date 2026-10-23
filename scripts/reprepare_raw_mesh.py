#!/usr/bin/env python
"""Re-prepare a PRESERVED raw reconstruction mesh through the Studio's real pipeline. No GPU, no model, no new inference.

    python scripts/reprepare_raw_mesh.py --raw "raw/01-truck-raw.glb" --name Truck --category heavy_truck --out out/ \
        [--length-m 7.0 --width-m 2.55 --height-m 3.8] [--forward +Z] [--smooth 40] [--no-align-yaw] [--baseline]

The raw mesh is imported as the RAW version of a throw-away Studio data directory (it is never modified), then
auto-process -> validate -> export runs exactly as the app does. Output: prepared.glb, six smooth-shaded views, report.json
(raw SHA-256, options, every preparation step, validation, per-LOD / collision audit, surface roughness before/after).

This is NOT proof of inference: the raw mesh must come from a real run whose evidence holds the same SHA-256.
With --baseline the same pipeline also runs with yaw alignment and smoothing switched off, for a before/after comparison.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "RESOURCE_LIMIT", "MODEL_ERROR", "INVALID_INPUT"}


def roughness(mesh) -> dict[str, float]:
    """Angle between neighbouring triangle normals (degrees): lower = smoother panels."""
    import numpy as np

    ang = np.degrees(mesh.face_adjacency_angles)
    return {"mean_deg": round(float(ang.mean()), 2), "p90_deg": round(float(np.percentile(ang, 90)), 2)}


def run_variant(
    client, ctx, raw_bytes: bytes, name: str, category: str, label: str, form: dict[str, Any], out: Path
) -> dict:
    from aro_studio.utils.render import render_asset_scene
    from aro_studio.verification.glb_audit import audit_glb

    pid = client.post("/api/projects", json={"name": f"reprepare {label}"}).json()["project_id"]
    asset = client.post(f"/api/projects/{pid}/assets", json={"name": name, "category": category}).json()
    imp = client.post(
        f"/api/assets/{asset['asset_id']}/import", files={"file": ("raw.glb", raw_bytes, "model/gltf-binary")}
    )
    imp.raise_for_status()
    raw_vid = imp.json()["version"]["version_id"]
    job = client.post(f"/api/versions/{raw_vid}/auto-process", json=form).json()
    jid = job["job_id"]
    while True:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["state"] in TERMINAL:
            break
        time.sleep(0.2)
    res: dict[str, Any] = {"label": label, "options": form, "job_state": j["state"]}
    if j["state"] != "COMPLETED":
        res["error"] = j.get("error")
        return res
    r = j["result"]
    final = r["final_version_id"]
    exp = client.post(f"/api/versions/{final}/export", json={"formats": ["glb", "unity"]}).json()
    while True:
        e = client.get(f"/api/jobs/{exp['job_id']}").json()
        if e["state"] in TERMINAL:
            break
        time.sleep(0.2)
    res["export_job_state"] = e["state"]
    if e["state"] != "COMPLETED":
        res["error"] = e.get("error")
        return res
    by_format = {x["format"]: x for x in e["result"]["exports"]}
    eid = by_format["glb"]["export_id"]
    dl = client.get(f"/api/exports/{eid}/download")
    meta = client.get(f"/api/exports/{eid}").json()
    export_report = {
        "status": meta["status"],
        "sha256_matches_download": meta["sha256"] == hashlib.sha256(dl.content).hexdigest(),
        "internal_verification_ok": (meta["report"].get("verification") or {}).get("ok"),
        "khronos": meta["report"].get("khronos"),
    }
    unity_info: dict[str, Any] = {"status": by_format["unity"]["status"]}
    udl = client.get(f"/api/exports/{by_format['unity']['export_id']}/download")
    if udl.status_code == 200:
        (out / f"{label}-unity-package.zip").write_bytes(udl.content)
        unity_info.update(
            {
                "file": f"{label}-unity-package.zip",
                "bytes": len(udl.content),
                "sha256": hashlib.sha256(udl.content).hexdigest(),
                "note": "integrity-verified by the Studio; NOT imported into Unity (no editor here): see docs/verification/unity-verification-runbook.md",
            }
        )
    glb = out / f"{label}-prepared.glb"
    glb.write_bytes(dl.content)
    audit = audit_glb(glb)
    scene = ctx.assets.load_scene(final)
    views = out / "views"
    views.mkdir(parents=True, exist_ok=True)
    names = []
    for view, az, el in (
        ("front", 0, 5),
        ("rear", 180, 5),
        ("left", 90, 5),
        ("right", -90, 5),
        ("top", 0, 85),
        ("3q", 40, 15),
    ):
        p = views / f"{label}-{view}.png"
        render_asset_scene(
            scene, azimuth_deg=az, elevation_deg=el, size=640, background=(236, 236, 236), smooth_shading=True
        ).save(p)
        names.append(p.name)
    lod0 = scene.meshes[next(iter(scene.meshes))]
    res.update(
        {
            "export_report": export_report,
            "unity_package": unity_info,
            "glb": glb.name,
            "glb_bytes": glb.stat().st_size,
            "glb_sha256": hashlib.sha256(dl.content).hexdigest(),
            "views": names,
            "views_shading": "smooth (vertex normals, as exported)",
            "needs_human": r["needs_human"],
            "validation": {
                k: (r["validation"] or {}).get(k) for k in ("status", "overall", "critical_failures", "major_failures")
            },
            "validation_blocking_reasons": (r["validation"] or {}).get("blocking_reasons"),
            "validation_failed_checks": [
                {k: c.get(k) for k in ("id", "category", "title", "severity", "status", "message")}
                for c in ((r["validation"] or {}).get("checks") or [])
                if c.get("status") not in ("passed", "skipped", "not_applicable")
            ],
            "steps": [
                {"step": s["step"], "status": s["status"], "seconds": round(s["seconds"], 2)} for s in r["steps"]
            ],
            "final_extents_m": r["final_extents_m"],
            "lod0_roughness": roughness(lod0),
            "audit": {
                "ok": audit["ok"],
                "failed": [c["message"] for c in audit["checks"] if not c["ok"]],
                "nodes": audit["nodes"],
            },
        }
    )
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", required=True, type=Path)
    ap.add_argument("--name", default="Asset")
    ap.add_argument("--category", default="other")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--length-m", type=float)
    ap.add_argument("--width-m", type=float)
    ap.add_argument("--height-m", type=float)
    ap.add_argument("--forward")
    ap.add_argument("--up", default="+Z", help="source up axis (TripoSR native: +Z)")
    ap.add_argument("--smooth", type=int, default=40)
    ap.add_argument("--no-align-yaw", action="store_true")
    ap.add_argument("--target-triangles", type=int, default=24_000)
    ap.add_argument(
        "--baseline",
        action="store_true",
        help="also run with yaw alignment and smoothing switched off (everything else identical)",
    )
    a = ap.parse_args()

    from fastapi.testclient import TestClient

    from aro_studio.api.app import create_app
    from aro_studio.app_context import build_context
    from aro_studio.config import Settings

    raw_bytes = a.raw.read_bytes()
    a.out.mkdir(parents=True, exist_ok=True)
    form: dict[str, Any] = {
        "up": a.up,
        "target_triangles": a.target_triangles,
        "smooth_iterations": a.smooth,
        "auto_align_yaw": not a.no_align_yaw,
    }
    for k, v in (("length_m", a.length_m), ("width_m", a.width_m), ("height_m", a.height_m), ("forward", a.forward)):
        if v is not None:
            form[k] = v
    variants = [("improved", form)]
    if a.baseline:
        variants.insert(0, ("baseline", {**form, "smooth_iterations": 0, "auto_align_yaw": False}))
    report: dict[str, Any] = {
        "kind": "re-preparation of a preserved raw mesh (NOT new inference)",
        "raw_file": a.raw.name,
        "raw_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "raw_bytes": len(raw_bytes),
        "variants": [],
    }
    with tempfile.TemporaryDirectory(prefix="aro_reprep_") as td:
        ctx = build_context(Settings(data_dir=Path(td) / "data", default_engine="triposr"), engines=[])
        try:
            client = TestClient(create_app(ctx))
            for label, f in variants:
                report["variants"].append(run_variant(client, ctx, raw_bytes, a.name, a.category, label, f, a.out))
        finally:
            ctx.close()
    (a.out / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    for v in report["variants"]:
        print(
            f"{v['label']:9s} job={v['job_state']} validation={(v.get('validation') or {}).get('status')} "
            f"audit_ok={(v.get('audit') or {}).get('ok')} extents={v.get('final_extents_m')} roughness={v.get('lod0_roughness')}"
        )
    return (
        0 if all(v["job_state"] == "COMPLETED" and (v.get("audit") or {}).get("ok") for v in report["variants"]) else 1
    )


if __name__ == "__main__":
    sys.exit(main())
