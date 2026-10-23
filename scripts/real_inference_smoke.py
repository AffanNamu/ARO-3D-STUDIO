#!/usr/bin/env python
"""Real image-to-3D smoke test THROUGH THE STUDIO (upload -> batch generation job -> raw asset -> viewer -> prepare -> validate -> export).

    python scripts/real_inference_smoke.py --manifest my-images.json [--out docs/acceptance/evidence/ai/smoke] [--preset BALANCED]
    python scripts/real_inference_smoke.py --manifest my-images.json --double      # wiring self-test with a TEST DOUBLE (never evidence)

Manifest (JSON):  {"items": [{"path": "truck.jpg", "category": "heavy_truck", "name": "Truck photo",
                              "source": "who owns it / licence", "length_m": 7.2, "up": "+Z", "forward": "+X"}, ...]}
``length_m``/``up``/``forward`` are optional; without ``length_m`` the prepared size is a flagged placeholder.

It drives the real FastAPI app in-process (same code as the server) with the REAL engine, the licence taken from the model lock
(no ARO_VERIFIED_MODEL_LICENSES override) and ``force=true`` so a cache hit can never pass for inference. Requirements for a result
that counts: >= 3 images, >= 2 asset groups including a vehicle and a non-vehicle. A deliberately invalid file is added to the
batch to prove that one bad item does not discard its valid siblings.

Evidence (out dir): ``smoke-evidence.json``, ``smoke-report.md``, per-item raw/prepared views, ``<item>-prepared.glb``.
Statuses: PASS / PARTIAL / BLOCKED / FAIL. Visual quality is NEVER judged automatically: each item carries a
``human_review`` block that stays PENDING_HUMAN_REVIEW until a person fills it in.
Exit code: 0 = every item really ran and verified; 3 = BLOCKED (engine not runnable); 1 = failure/partial.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "RESOURCE_LIMIT", "MODEL_ERROR", "INVALID_INPUT"}


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def git_head() -> str | None:
    import subprocess

    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10, check=False
        )  # noqa: S603, S607
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def image_facts(path: Path) -> dict:
    from PIL import Image

    with Image.open(path) as im:
        return {
            "width": im.width,
            "height": im.height,
            "mode": im.mode,
            "format": im.format,
            "has_alpha": "A" in im.getbands(),
        }


def wait_job(client, jid: str, timeout: float) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["state"] in TERMINAL:
            return j
        time.sleep(1.0)
    return {"state": "TIMEOUT", "error": {"message": f"smoke test gave up after {timeout}s"}, "job_id": jid}


def six_views(scene, out: Path, label: str) -> list[str]:
    from aro_studio.utils.render import render_asset_scene

    out.mkdir(parents=True, exist_ok=True)
    names = []
    for view, az, el in (
        ("front", 0, 5),
        ("rear", 180, 5),
        ("left", 90, 5),
        ("right", -90, 5),
        ("top", 0, 85),
        ("3q", 40, 15),
    ):
        p = out / f"{label}-{view}.png"
        render_asset_scene(scene, azimuth_deg=az, elevation_deg=el, size=640, background=(236, 236, 236)).save(p)
        names.append(p.name)
    return names


def load_manifest(path: Path) -> list[dict]:
    doc = json.loads(path.read_text())
    items = doc["items"] if isinstance(doc, dict) else doc
    base = path.parent
    out = []
    for i, it in enumerate(items):
        p = Path(it["path"]).expanduser()
        p = p if p.is_absolute() else base / p
        if not p.is_file():
            raise SystemExit(f"manifest item {i}: image not found: {p}")
        out.append({**it, "abs_path": p})
    return out


def coverage_problems(items: list[dict]) -> list[str]:
    from aro_studio.assets.taxonomy import get_category

    problems = []
    if len(items) < 3:
        problems.append(f"only {len(items)} image(s): at least 3 genuinely different images are required")
    groups = {get_category(i["category"]).group for i in items}
    if "vehicles" not in groups:
        problems.append("no vehicle image (category group 'vehicles')")
    if groups <= {"vehicles"}:
        problems.append("no non-vehicle image")
    if len({sha256(i["abs_path"].read_bytes()) for i in items}) < len(items):
        problems.append("duplicate image content in the manifest")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", default=str(ROOT / "docs/acceptance/evidence/ai/smoke"))
    ap.add_argument("--preset", default="BALANCED")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--timeout-s", type=int, default=3600, help="per generation job")
    ap.add_argument(
        "--double", action="store_true", help="wiring self-test with the plumbing TEST DOUBLE; not AI evidence"
    )
    ap.add_argument("--no-negative-probe", action="store_true")
    ap.add_argument(
        "--allow-partial-coverage",
        action="store_true",
        help="run with fewer than 3 images / without a vehicle+non-vehicle mix (e.g. one focused image). Never reports PASS: "
        "the status stays PARTIAL because the coverage requirement is not met",
    )
    a = ap.parse_args()

    from fastapi.testclient import TestClient

    from aro_studio.api.app import create_app
    from aro_studio.app_context import build_context
    from aro_studio.assets.taxonomy import get_category
    from aro_studio.config import Settings
    from aro_studio.verification.hardware import VramPoller, environment

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    items = load_manifest(Path(a.manifest))
    ev: dict[str, Any] = {
        "schema": 1,
        "recorded_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mode": "test_double" if a.double else "real_engine",
        "environment": environment(),
        "studio_commit": git_head(),
        "status": {"real_inference": "BLOCKED"},
        "blockers": [],
        "coverage_problems": coverage_problems(items),
        "items": [],
    }

    def crashed(where: str) -> int:
        import traceback

        tb = traceback.format_exc()
        ev["status"] = {"real_inference": "FAIL"}
        ev["crash"] = tb[-6000:]
        ev["blockers"].append(
            f"the smoke script crashed {where}: {tb.strip().splitlines()[-1][:300]} (full traceback in the 'crash' field)"
        )
        print(tb, file=sys.stderr)
        return finish(1)

    def finish(code: int) -> int:
        (out / "smoke-evidence.json").write_text(json.dumps(ev, indent=2, default=str) + "\n")
        write_report(ev, out / "smoke-report.md")
        print(json.dumps({"mode": ev["mode"], "status": ev["status"], "blockers": ev["blockers"]}, indent=2))
        print("evidence:", out / "smoke-evidence.json")
        return code

    # marker on disk until the run ends: if the process is killed or the runtime disconnects, this stays and the reader reports FAIL
    marker = {**ev, "status": {"real_inference": "RUNNING"}}
    (out / "smoke-evidence.json").write_text(json.dumps(marker, indent=2, default=str) + "\n")
    work = Path(tempfile.mkdtemp(prefix="aro_smoke_"))
    try:
        if a.double:
            from tests.support import PlumbingEngine

            s = Settings(
                data_dir=work / "data",
                verified_model_licenses="plumbing_test_double",
                default_engine="plumbing_test_double",
            )
            ctx = build_context(s, engines=[PlumbingEngine()])
            engine_id = "plumbing_test_double"
        else:
            s = Settings(
                data_dir=work / "data", device=a.device, default_engine="triposr"
            )  # licence comes from the lock only
            ctx = build_context(s)
            engine_id = "triposr"
        client = TestClient(create_app(ctx))
    except Exception:
        return crashed("while starting the Studio (before any image was processed)")
    poller = VramPoller()
    try:
        # ---- gates ---------------------------------------------------------------------------------------------
        eng = next(e for e in client.get("/api/engines").json()["items"] if e["info"]["id"] == engine_id)
        ev["engine"] = {
            "id": engine_id,
            "version": eng["info"]["version"],
            "revision": eng["info"].get("revision"),
            "licence": eng["info"]["license"],
            "runnable": eng["runnable"],
            "availability": eng["availability"],
            "device": eng["device"],
        }
        if not a.double:
            from aro_studio.engines.weights import load_lock

            ev["engine"]["lock_missing"] = load_lock("triposr").missing()
        if not eng["runnable"]:
            ev["blockers"].append(
                "engine not runnable: "
                + "; ".join(eng["availability"]["reasons"] or [f"licence {eng['info']['license']['status']}"])
                + " | activate: "
                + " | ".join(eng["availability"].get("activation", []))
            )
            return finish(3)
        if ev["coverage_problems"] and not a.double and not a.allow_partial_coverage:
            ev["blockers"].append("coverage: " + "; ".join(ev["coverage_problems"]))
            ev["status"]["real_inference"] = "BLOCKED"
            return finish(3)

        # ---- project + one batch request (valid images + one invalid probe) ------------------------------------
        proj = client.post("/api/projects", json={"name": "real-inference-smoke"}).json()
        pid = proj["project_id"]
        files = [("files", (i["abs_path"].name, i["abs_path"].read_bytes(), "application/octet-stream")) for i in items]
        specs = [{"name": i.get("name") or i["abs_path"].stem, "category": i["category"]} for i in items]
        if not a.no_negative_probe:
            files.append(("files", ("not-an-image.png", b"this is not an image, just text", "image/png")))
            specs.append({"name": "Invalid probe", "category": "prop"})
        poller.start()
        r = client.post(
            f"/api/projects/{pid}/batch-generate",
            files=files,
            data={
                "engine_id": engine_id,
                "preset": a.preset,
                "items_json": json.dumps(specs),
                "force": "true",
                "use_cache": "false",
            },
        )
        ev["batch_response_status"] = r.status_code
        batch = r.json()
        ev["batch"] = {k: batch.get(k) for k in ("batch_id", "total", "queued", "failed")}
        if r.status_code != 202:
            ev["blockers"].append(f"batch-generate answered {r.status_code}: {r.text[:300]}")
            return finish(1)
        probe_idx = len(items) if not a.no_negative_probe else None
        if probe_idx is not None:
            pr = batch["items"][probe_idx]
            ev["negative_probe"] = {
                "status": pr["status"],
                "error": pr.get("error"),
                "siblings_queued": sum(x["status"] == "QUEUED" for x in batch["items"][:probe_idx]),
                "result": "PASS"
                if pr["status"] == "FAILED" and all(x["status"] == "QUEUED" for x in batch["items"][:probe_idx])
                else "FAIL",
            }

        # ---- per item: wait, inspect, prepare, validate, export, verify ------------------------------------------
        for idx, it in enumerate(items):
            bi = batch["items"][idx]
            rec: dict[str, Any] = {
                "name": specs[idx]["name"],
                "category": it["category"],
                "category_group": get_category(it["category"]).group,
                "input_file": it["abs_path"].name,
                "input_sha256": sha256(it["abs_path"].read_bytes()),
                "input_size_bytes": it["abs_path"].stat().st_size,
                "input_image": image_facts(it["abs_path"]),
                "input_source_note": it.get("source", "(not recorded)"),
                "input_preserved_as": f"inputs/{idx + 1:02d}-{it['abs_path'].name}",
                "batch_status": bi["status"],
                "human_review": {
                    "status": "PENDING_HUMAN_REVIEW",
                    "recognisable": None,
                    "visual_defects": None,
                    "category_limitations": None,
                    "orientation_up_front": None,
                },
            }
            (out / "inputs").mkdir(exist_ok=True)
            shutil.copy2(it["abs_path"], out / rec["input_preserved_as"])  # the original bytes, untouched
            ev["items"].append(rec)
            if bi["status"] != "QUEUED":
                rec["result"] = "FAIL"
                rec["error"] = bi.get("error")
                continue
            job = wait_job(client, bi["job"]["job_id"], a.timeout_s)
            rec["generation_job"] = {
                "job_id": job.get("job_id"),
                "state": job["state"],
                "error": job.get("error"),
                "job_seconds": (job.get("resources") or {}).get("seconds"),
                "preflight": ((job.get("resources") or {}).get("annotations") or {}).get("resources_preflight"),
            }
            res = job.get("result") or {}
            if job["state"] != "COMPLETED" or not res.get("model_ran"):
                rec["result"] = "FAIL"
                rec["error"] = job.get("error") or {"message": "job ended without the model running"}
                continue
            raw_id = res["version_id"]
            raw_ver = client.get(f"/api/versions/{raw_id}").json()
            gen = client.get(f"/api/generations/{res['generation_id']}").json()
            raw_scene = ctx.assets.load_scene(raw_id)
            mesh = raw_scene.combined()
            import numpy as np

            finite = bool(np.isfinite(np.asarray(mesh.vertices)).all())
            prov = raw_scene.manifest.provenance
            rec["real_inference"] = {
                "model_ran": True,
                "cache_hit": bool(res.get("reused_from")),
                "engine_id": prov.engine_id,
                "model_version": prov.model_version,
                "device": res.get("device"),
                "model_load_time_s": round(float(res.get("model_load_time_s") or 0), 3),
                "inference_time_s": round(float(res.get("execution_time_s") or 0), 3),
                "vertices": int(len(mesh.vertices)),
                "triangles": int(len(mesh.faces)),
                "extents_native": [float(x) for x in mesh.extents],
                "finite": finite,
                "output_sha256": res.get("output_sha256"),
                "output_size_bytes": (ctx.layout.root / gen["output_path"]).stat().st_size
                if gen.get("output_path")
                else None,
                "generation_id": res["generation_id"],
                "raw_version_id": raw_id,
                "raw_stage": raw_ver["stage"],
                "provenance": prov.model_dump(),
            }
            stored = client.get(f"/api/projects/{pid}/sources/{bi['source']['sha256']}/image")
            rec["real_inference"]["stored_source_sha256"] = bi["source"]["sha256"]
            rec["real_inference"]["provenance_source_sha256_matches_batch"] = (
                prov.input_image_sha256 == bi["source"]["sha256"]
            )
            rec["real_inference"]["source_image_served"] = stored.status_code == 200
            if gen.get("output_path") and (ctx.layout.root / gen["output_path"]).is_file():
                (out / "raw").mkdir(exist_ok=True)
                raw_copy = out / "raw" / f"{idx + 1:02d}-{Path(rec['input_file']).stem}-raw.glb"
                shutil.copy2(ctx.layout.root / gen["output_path"], raw_copy)
                rec["raw_mesh_file"] = (
                    f"raw/{raw_copy.name}"  # large: kept out of git by .gitignore, packaged separately
                )
                rec["real_inference"]["raw_copy_sha256"] = sha256(raw_copy.read_bytes())
            rec["real_inference"]["input_bytes_equal_stored_source"] = rec["input_sha256"] == bi["source"]["sha256"]
            rec["generation_report"] = {
                k: (raw_scene.reports.get("generation") or {}).get(k)
                for k in ("settings", "preprocess_steps", "engine_details", "execution_time_s", "model_load_time_s")
            }
            rec["raw_sanity"] = res.get("mesh")
            rec["raw_manifest_sha256_before_prep"] = raw_ver["manifest_sha256"]
            rec["raw_views"] = six_views(raw_scene, out / "views", f"{idx + 1:02d}-raw")
            pv = client.get(f"/api/versions/{raw_id}/preview.glb")
            rec["viewer_preview"] = {"status": pv.status_code, "bytes": len(pv.content)}
            if (
                not finite
                or len(mesh.faces) < 100
                or not rec["real_inference"]["provenance_source_sha256_matches_batch"]
            ):
                rec["result"] = "FAIL"
                rec["error"] = {"message": "raw mesh empty/non-finite or provenance mismatch"}
                continue

            # prepare (queued job through the API; raw stays untouched)
            body: dict[str, Any] = {"lod": True}
            for k in ("length_m", "up", "forward"):
                if it.get(k) is not None:
                    body[k] = it[k]
            pj = client.post(f"/api/versions/{raw_id}/auto-process", json=body)
            if pj.status_code != 202:
                rec["result"] = "FAIL"
                rec["error"] = {"message": f"auto-process rejected: {pj.status_code} {pj.text[:200]}"}
                continue
            prep = wait_job(client, pj.json()["job_id"], 1800)
            rpt = prep.get("result") or ((prep.get("error") or {}).get("details") or {}).get("pipeline") or {}
            rec["preparation"] = {
                "job_state": prep["state"],
                "ok": bool(rpt.get("ok")),
                "needs_human": rpt.get("needs_human"),
                "steps": [
                    {"step": s["step"], "status": s["status"], "seconds": round(s["seconds"], 2)}
                    for s in rpt.get("steps", [])
                ],
                "final_extents_m": rpt.get("final_extents_m"),
                "validation": {
                    k: (rpt.get("validation") or {}).get(k)
                    for k in ("status", "overall", "critical_failures", "major_failures")
                },
                "source_axes": rpt.get("source_axes"),
                "final_version_id": rpt.get("final_version_id"),
            }
            after = client.get(f"/api/versions/{raw_id}").json()
            rec["raw_immutable"] = (
                after["manifest_sha256"] == rec["raw_manifest_sha256_before_prep"] and after["stage"] == "raw"
            )
            if prep["state"] != "COMPLETED" or not rpt.get("final_version_id"):
                rec["result"] = "FAIL"
                rec["error"] = prep.get("error")
                continue
            final_id = rpt["final_version_id"]
            final_scene = ctx.assets.load_scene(final_id)
            rec["prepared_views"] = six_views(final_scene, out / "views", f"{idx + 1:02d}-prepared")

            # export + independent re-open
            ej = client.post(f"/api/versions/{final_id}/export", json={"formats": ["glb"]})
            exp = wait_job(client, ej.json()["job_id"], 900)
            rec["export"] = {"job_state": exp["state"]}
            eid = ((exp.get("result") or {}).get("exports") or [{}])[0].get("export_id")
            if exp["state"] == "COMPLETED" and eid:
                meta = client.get(f"/api/exports/{eid}").json()
                dl = client.get(f"/api/exports/{eid}/download")
                data = dl.content
                import trimesh

                reopened = trimesh.load(io.BytesIO(data), file_type="glb", force="scene")
                tris = sum(len(g.faces) for g in reopened.geometry.values() if hasattr(g, "faces"))
                import numpy as np

                finite_all = all(
                    bool(np.isfinite(np.asarray(g.vertices)).all())
                    for g in reopened.geometry.values()
                    if hasattr(g, "vertices")
                )
                lod0 = [
                    g
                    for n, g in reopened.geometry.items()
                    if hasattr(g, "faces") and "_LOD" not in n or n.endswith("_LOD0")
                ]
                kh = meta["report"].get("khronos", {})
                (out / f"{idx + 1:02d}-prepared.glb").write_bytes(data)
                rec["export"].update(
                    {
                        "export_id": eid,
                        "status": meta["status"],
                        "size_bytes": len(data),
                        "sha256_download": sha256(data),
                        "sha256_matches_record": sha256(data) == meta["sha256"],
                        "internal_verification_ok": meta["report"]["verification"]["ok"],
                        "reopened_triangles_all_lods": int(tris),
                        "reopened_geometry_count": len(reopened.geometry),
                        "reopened_vertices_finite": finite_all,
                        "reopened_lod0_extents_m": [
                            round(float(x), 4) for x in (reopened.bounds[1] - reopened.bounds[0])
                        ]
                        if len(lod0)
                        else None,
                        "khronos": kh,
                    }
                )
            ok = (
                rec["export"].get("status") == "COMPLETED"
                and rec["export"].get("sha256_matches_record")
                and rec["export"].get("internal_verification_ok")
                and not (rec["export"].get("khronos") or {}).get("errors")
                and rec["export"].get("reopened_vertices_finite") is True
                and rec["export"].get("reopened_triangles_all_lods", 0) > 0
                and rec["raw_immutable"]
                and rec["viewer_preview"]["status"] == 200
            )
            rec["result"] = "PASS" if ok else "FAIL"

        poller.stop()
        ran = [i for i in ev["items"] if i.get("real_inference")]
        for i in ev["items"]:
            if i.get("real_inference"):
                i["real_inference"]["peak_vram_nvidia_smi_mb_whole_run"] = poller.peak_mb or None
        all_pass = bool(ev["items"]) and all(i.get("result") == "PASS" for i in ev["items"])
        if a.double:
            ev["status"] = {
                "real_inference": "NOT_RUN (test double)",
                "wiring_selftest": "PASS" if all_pass else "FAIL",
            }
            ev["blockers"].append(
                "--double was used: this proves the harness wiring only, never model quality or inference"
            )
            return finish(0 if all_pass else 1)
        if ev["coverage_problems"]:
            ev["status"]["real_inference"] = "PARTIAL"
            ev["status"]["scope"] = (
                "focused run: coverage requirement NOT met (needs >= 3 images incl. vehicle + non-vehicle)"
            )
            ev["blockers"].append("coverage: " + "; ".join(ev["coverage_problems"]))
            return finish(0 if all_pass and ran else 1)
        elif all_pass and len(ran) == len(items) and ev.get("negative_probe", {}).get("result", "PASS") == "PASS":
            ev["status"]["real_inference"] = "PASS"
        elif ran:
            ev["status"]["real_inference"] = "PARTIAL"
        else:
            ev["status"]["real_inference"] = "FAIL"
        ev["status"]["visual_quality"] = "PENDING_HUMAN_REVIEW"
        ev["status"]["production_ready"] = "NOT_CLAIMED"
        return finish(0 if ev["status"]["real_inference"] == "PASS" else 1)
    except Exception:
        return crashed("during the run")
    finally:
        poller.stop()
        ctx.close()


def write_report(ev: dict, path: Path) -> None:
    L = [
        f"# Real image-to-3D smoke test ({ev['mode']})",
        "",
        f"Recorded {ev['recorded_at_utc']} · status: **{ev['status']}**",
        "",
    ]
    env = ev["environment"]
    L += [
        f"Hardware: {env.get('nvidia_smi') or 'no NVIDIA GPU'} · torch {env.get('torch')} · python {env['python']}",
        "",
    ]
    if ev.get("engine"):
        e = ev["engine"]
        L += [
            f"Engine **{e['id']}** `{e['version']}` · device {e['device']} · runnable {e['runnable']} · licence status {e['licence']['status']}",
            "",
        ]
    if ev["blockers"]:
        L += ["## Blockers", *[f"* {b}" for b in ev["blockers"]], ""]
    if ev.get("coverage_problems"):
        L += ["## Coverage problems", *[f"* {b}" for b in ev["coverage_problems"]], ""]
    if ev.get("negative_probe"):
        L += [
            f"Invalid-file probe: **{ev['negative_probe']['result']}** (bad file {ev['negative_probe']['status']}, {ev['negative_probe']['siblings_queued']} valid siblings still queued)",
            "",
        ]
    L += [
        "| Item | Category | Result | Triangles | Load s | Infer s | Prep validation | Export |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i in ev["items"]:
        ri, pr, ex = i.get("real_inference", {}), i.get("preparation", {}), i.get("export", {})
        L.append(
            f"| {i['name']} | {i['category']} | **{i.get('result', '?')}** | {ri.get('triangles', '-')} | {ri.get('model_load_time_s', '-')} | {ri.get('inference_time_s', '-')} | {(pr.get('validation') or {}).get('status', '-')} | {ex.get('status', '-')} |"
        )
    L += [
        "",
        "Visual quality is **not** judged automatically: fill in `human_review` for each item in `smoke-evidence.json` after looking at `views/`.",
    ]
    path.write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(main())
