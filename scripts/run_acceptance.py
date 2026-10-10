#!/usr/bin/env python
"""ARO TITAN 480 acceptance run (spec §54): attempts all 22 stages and reports each one honestly.

    python scripts/run_acceptance.py                     # writes docs/acceptance/titan480-acceptance-report.{md,json}
    python scripts/run_acceptance.py --data-dir /tmp/x   # keep the generated data for inspection

Status vocabulary (never rounded up):
    PASS      executed and verified
    PARTIAL   executed, but with a documented limitation
    BLOCKED   cannot run in this environment (reason + exact activation steps are given)
    FAIL      executed and failed
Only these four are used. "Not applicable to this input" is PARTIAL with the reason in the detail; "needs a human decision" is
BLOCKED with what is needed.

If the real image-to-3D engine can run (weights + torch + GPU/CPU), stages 5-7 run it for real and the pipeline
continues from the AI output. Otherwise the pipeline continues from the ARO TITAN 480 *procedural reference*,
which is clearly labelled and is NEVER presented as an AI reconstruction.
"""

from __future__ import annotations

import argparse
import io
import json
import platform
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aro_studio import __version__  # noqa: E402
from aro_studio.app_context import build_context  # noqa: E402
from aro_studio.config import Settings  # noqa: E402
from aro_studio.observability.resources import snapshot  # noqa: E402
from aro_studio.utils.render import render_asset_scene  # noqa: E402
from aro_studio.vehicles.titan480 import build_titan480  # noqa: E402

STAGES = [
    "Create ARO TITAN 480 project",
    "Upload concept image",
    "Validate the input",
    "Preprocess the image",
    "Load the image-to-3D model",
    "Run actual reconstruction",
    "Save raw output",
    "Process the geometry",
    "Repair valid geometry problems",
    "Process materials",
    "Process textures where supported",
    "Configure vehicle metadata",
    "Configure wheels and axles",
    "Generate/prepare collision geometry",
    "Generate LODs",
    "Validate the entire asset",
    "Display in the 3D viewer",
    "Save the project version",
    "Export GLB",
    "Generate Unity-ready output",
    "Validate export integrity",
    "Test import compatibility with Unity 6",
]


class Report:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, n: int, status: str, detail: str, seconds: float = 0.0, **extra) -> None:
        self.rows.append(
            {"n": n, "stage": STAGES[n - 1], "status": status, "detail": detail, "seconds": round(seconds, 2), **extra}
        )
        print(f"[{n:2d}] {status:8s} {STAGES[n - 1]:45s} {detail[:110]}", flush=True)


def wait_ok(ctx, job):
    j = ctx.jobs.wait(job["job_id"], timeout=900)
    return j


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--out", default=str(ROOT / "docs" / "acceptance"))
    ap.add_argument("--with-browser", action="store_true", help="also run the Playwright UI test for stage 17")
    ap.add_argument("--device", default="auto")
    ap.add_argument(
        "--verify-licence", default="", help="engine ids whose WEIGHTS licence you have verified (e.g. triposr)"
    )
    args = ap.parse_args()
    data = Path(args.data_dir) if args.data_dir else Path(tempfile.mkdtemp(prefix="aro_acceptance_"))
    rep = Report()
    s = Settings(data_dir=data, device=args.device, verified_model_licenses=args.verify_licence)
    ctx = build_context(s)
    env = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "studio": __version__,
        "resources": snapshot(data).to_dict(),
    }
    state: dict = {}
    t0 = time.perf_counter()
    try:
        run(ctx, rep, state, args)
    except Exception:  # an unexpected crash must be visible, not hidden
        rep.rows.append(
            {
                "n": 0,
                "stage": "acceptance harness",
                "status": "FAIL",
                "detail": traceback.format_exc()[-800:],
                "seconds": 0,
            }
        )
        print(traceback.format_exc())
    finally:
        ctx.close()
    done = {r["n"] for r in rep.rows}
    for n in range(1, 23):
        if n not in done:
            rep.add(n, "BLOCKED", "not reached (an earlier stage did not complete)")
    rep.rows.sort(key=lambda r: r["n"])
    write_reports(rep, env, state, Path(args.out), time.perf_counter() - t0, data)
    bad = [r for r in rep.rows if r["status"] == "FAIL"]
    return 1 if bad else 0


def run(ctx, rep: Report, state: dict, args) -> None:
    # 1 --------------------------------------------------------------------------------------
    t = time.perf_counter()
    p = ctx.projects.create("ARO TITAN 480", "Acceptance run")
    a = ctx.assets.create_asset(
        p["project_id"],
        "ARO TITAN 480",
        "heavy_truck",
        {"manufacturer": "ARO Motors", "brand": "ARO", "model": "TITAN 480", "drive_configuration": "6x4"},
    )
    rep.add(1, "PASS", f"project {p['project_id']}, asset {a['asset_id']}", time.perf_counter() - t)
    pid, aid = p["project_id"], a["asset_id"]

    # 2 -- concept image: a render of the procedural reference (NOT concept art, NOT AI-made) -------------
    t = time.perf_counter()
    ref = build_titan480()
    img = render_asset_scene(ref, azimuth_deg=40, elevation_deg=10, size=1024, background=(236, 236, 236))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    src = ctx.sources.add_image(pid, "titan480_reference_render.png", buf.getvalue(), category_group="vehicles")
    sha = src["sha256"]
    rep.add(
        2,
        "PARTIAL",
        "image is a software render of the procedural reference model, not an artist's concept image; stored by content hash",
        time.perf_counter() - t,
        sha256=sha,
    )
    # 3 --------------------------------------------------------------------------------------
    v = src["report"]["validation"]
    rep.add(
        3,
        "PASS",
        f"{v['width']}x{v['height']} {v['format']}, quality {v['quality_score']}, warnings: {v['warnings'] or 'none'}; analysis: bg={src['report']['analysis']['background_type']}, category auto-detected={src['report']['analysis']['classification']}",
    )
    # 4 --------------------------------------------------------------------------------------
    from aro_studio.imaging.preprocess import PreprocessOptions, preprocess

    t = time.perf_counter()
    pre = preprocess(ctx.sources.open(pid, sha), PreprocessOptions())
    rep.add(
        4,
        "PASS",
        " → ".join(x["step"] for x in pre.steps) + f" → {pre.image.size[0]}x{pre.image.size[1]} model input",
        time.perf_counter() - t,
    )

    # 5-7 real engine --------------------------------------------------------------------------
    eng = ctx.generation.engine_status()[0]
    raw_version = None
    if eng["runnable"]:
        t = time.perf_counter()
        job = ctx.jobs.submit(
            "generation",
            {
                "project_id": pid,
                "asset_id": aid,
                "image_sha256": sha,
                "engine_id": eng["info"]["id"],
                "preset": "BALANCED",
            },
            project_id=pid,
            asset_id=aid,
        )
        j = wait_ok(ctx, job)
        if j["state"] == "COMPLETED":
            raw_version = j["result"]["version_id"]
            rep.add(
                5,
                "PASS",
                f"{eng['info']['name']} loaded on {j['result']['device']} in {j['result']['model_load_time_s']:.1f}s",
                j["result"]["model_load_time_s"],
            )
            rep.add(
                6,
                "PASS",
                f"inference {j['result']['execution_time_s']:.1f}s, mesh {j['result']['mesh']['faces']:,} faces (actual model run)",
                j["result"]["execution_time_s"],
            )
            rep.add(
                7,
                "PASS",
                f"raw saved as immutable raw version {raw_version}; output sha256 {j['result']['output_sha256'][:16]}…",
            )
            state["source"] = "ai_reconstruction"
        else:
            err = j["error"] or {}
            rep.add(5, "FAIL", f"{j['state']}: {err.get('message')} → {err.get('recommended_action')}")
            rep.add(6, "BLOCKED", "model did not load")
    else:
        why = "; ".join(eng["availability"]["reasons"]) or "weights licence not verified by deployer"
        if not eng["license_verified_by_deployer"]:
            why += f"; weights licence '{eng['info']['license']['status']}' not yet verified (set ARO_VERIFIED_MODEL_LICENSES={eng['info']['id']})"
        act = " | ".join(eng["availability"]["activation"])
        rep.add(
            5,
            "BLOCKED",
            f"{eng['info']['name']} cannot load here: {why}. To activate: {act}",
            reasons=eng["availability"]["reasons"],
        )
        rep.add(
            6,
            "BLOCKED",
            "no real reconstruction was run; NO placeholder geometry was substituted. See docs/models/model-requirements.md for the GPU test strategy",
        )
    if raw_version is None:
        t = time.perf_counter()
        r = ctx.assets  # reference raw (procedural)
        from aro_studio.core.enums import Stage
        from aro_studio.scene.model import Provenance

        sc = build_titan480()
        sc.manifest.provenance = Provenance(
            source="procedural_reference", note="Original procedural ARO TITAN 480 reference. NOT an AI reconstruction."
        )
        ver = r.add_version(
            aid, sc, stage=Stage.RAW, operation="reference.titan480", description="Procedural reference (not AI)"
        )
        raw_version = ver["version_id"]
        state["source"] = "procedural_reference"
        rep.add(
            7,
            "PARTIAL",
            f"no AI output exists; the procedural reference was saved as the raw version {raw_version} so the remaining stages can run on a real, structured vehicle",
            time.perf_counter() - t,
        )

    # processing chain -------------------------------------------------------------------------
    def op(n_stage: int, operation: str, params: dict, version: str):
        t = time.perf_counter()
        j = ctx.jobs.wait(
            ctx.jobs.submit(
                "processing",
                {"operation": operation, "version_id": version, "params": params},
                project_id=pid,
                asset_id=aid,
            )["job_id"],
            timeout=900,
        )
        return j, time.perf_counter() - t

    cur = raw_version
    j, dt = op(8, "geometry", {"preset": "standard_cleanup"}, cur)
    if j["state"] != "COMPLETED":
        rep.add(8, "FAIL", f"{j['state']}: {(j['error'] or {}).get('message')}")
        return
    cur = j["result"]["version_id"]
    gl = ctx.assets.load_scene(cur).reports["geometry"]
    rep.add(
        8,
        "PASS",
        f"standard cleanup: {gl['before']['face_count']:,} → {gl['after']['face_count']:,} faces; steps {[s['op'] for s in gl['steps']]}",
        dt,
    )
    b, a_ = gl["before"], gl["after"]
    problems = {
        k: b[k]
        for k in ("duplicate_vertices", "degenerate_faces", "duplicate_faces", "hole_count", "nonmanifold_edges")
        if b[k]
    }
    rep.add(
        9,
        "PASS" if not problems else "PARTIAL",
        f"defects found before repair: {problems or 'none'}; after: holes={a_['hole_count']}, non-manifold={a_['nonmanifold_edges']}. Repair operations (merge, fill holes, normals, fragments) are unit-tested on damaged meshes"
        if state["source"] == "procedural_reference"
        else f"defects before: {problems}; after: holes={a_['hole_count']}",
    )
    j, dt = op(
        10, "materials", {"apply_vehicle_palette": True, "overwrite": state["source"] == "ai_reconstruction"}, cur
    )
    cur = j["result"]["version_id"] if j["state"] == "COMPLETED" else cur
    rep.add(
        10,
        "PASS" if j["state"] == "COMPLETED" else "FAIL",
        f"{len(ctx.assets.load_scene(cur).manifest.materials)} PBR materials (paint, glass, rubber, chrome, plastic, lights, interior…)",
        dt,
    )
    sc = ctx.assets.load_scene(cur)
    if state["source"] == "ai_reconstruction":
        from aro_studio.processing.ai_pipeline import AIPipelineOptions, run_ai_pipeline

        r = run_ai_pipeline(ctx.processing, ctx.assets, raw_version, AIPipelineOptions())
        for st in r["steps"]:
            print(f"      ai-pipeline: {st['status']:5s} {st['name']}", flush=True)
        by = {st["name"].split(":")[0]: st for st in r["steps"]}
        ok_ = lambda k: by.get(k, {}).get("status") == "PASS"  # noqa: E731
        rep.add(
            11,
            "PASS" if ok_("textures") else "FAIL",
            "AI mesh decimated, UV-unwrapped and colour-baked from the raw mesh",
        )
        rep.add(12, "BLOCKED", "; ".join(r["needs_human"]) or "vehicle specification required")
        rep.add(13, "BLOCKED", "wheel and axle positions must be provided by the artist for a reconstructed mesh")
        rep.add(14, "PASS" if ok_("collision") else "FAIL", "collision generated by the AI pipeline")
        rep.add(15, "PASS" if ok_("LOD generation") else "FAIL", "LODs generated by the AI pipeline")
        v_ = r.get("validation")
        rep.add(
            16,
            "PASS" if v_ and v_["status"] == "PRODUCTION_READY" else "PARTIAL",
            f"validation {v_['status'] if v_ else 'not run'}; needs a human: {r['needs_human']}",
        )
        state["validation"] = v_
        rep.add(
            17,
            "BLOCKED",
            "viewer / save / export stages for AI output are recorded by scripts/record_real_inference.py",
        )
        return
    v = sc.manifest.vehicle
    rep.add(
        12,
        "PASS",
        f"{v.identity.manufacturer} {v.identity.model} · {v.identity.category} · {v.identity.drive_configuration}; components: {sorted(v.components)}; {len(v.pivots)} pivots, {len(v.lights)} lights, {len(v.attachment_points)} attachment points, CoM {v.center_of_mass}",
    )
    rep.add(
        13,
        "PASS",
        f"{len(v.axles)} axles, {len(v.wheels)} wheels (steered: {sum(w.steering for w in v.wheels)}, driven: {sum(w.driven for w in v.wheels)}), wheelbase {v.wheelbase:.2f} m — taken from the reference spec, not auto-detected",
    )
    j, dt = op(14, "rig", {}, cur)
    cur = j["result"]["version_id"]
    j, dt = op(14, "collision", {}, cur)
    cur = j["result"]["version_id"]
    sc = ctx.assets.load_scene(cur)
    rep.add(
        14,
        "PASS",
        f"{len(sc.manifest.colliders)} colliders ({', '.join(c.name + ':' + str(c.triangle_count) for c in sc.manifest.colliders)}); rig of {len(sc.manifest.rig.nodes)} nodes",
        dt,
        fidelity=sc.reports["collision"].get("fidelity"),
    )
    j, dt = op(15, "lod", {}, cur)
    cur = j["result"]["version_id"]
    lods = ctx.assets.load_scene(cur).manifest.lods
    rep.add(
        15,
        "PASS",
        "triangles: "
        + " → ".join([f"LOD0 {sc.triangle_count:,}"] + [f"LOD{x.level} {x.triangle_count:,}" for x in lods]),
        dt,
    )
    j, dt = op(16, "validate", {"config": {"check_intersections": True}}, cur)
    val = j["result"]
    state["validation"] = {
        k: val[k]
        for k in (
            "status",
            "overall",
            "critical_failures",
            "major_failures",
            "categories",
            "blocking_reasons",
            "validation_id",
        )
    }
    rep.add(
        16,
        "PASS" if val["status"] == "PRODUCTION_READY" else "FAIL",
        f"{val['status']} · overall {val['overall']}% · critical {val['critical_failures']} · major {val['major_failures']} · "
        + ", ".join(f"{k} {v['score']}%" for k, v in val["categories"].items() if v["applicable"]),
        dt,
    )
    warn = [c for c in val["checks"] if c["status"] == "warning"]
    state["warnings"] = [f"{c['id']} {c['title']}: {c['message']}" for c in warn]

    # 17 viewer ------------------------------------------------------------------------------------
    if args.with_browser:
        import subprocess

        t = time.perf_counter()
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/e2e", "-q", "-x", "-W", "ignore"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        rep.add(
            17,
            "PASS" if r.returncode == 0 else "FAIL",
            "Playwright/Chromium e2e: loaded the asset in the three.js viewer, exercised views, wireframe, shading, grid, bounds, collision, rig, LOD switching, lighting, stats"
            if r.returncode == 0
            else r.stdout[-400:],
            time.perf_counter() - t,
        )
    else:
        rep.add(
            17,
            "PARTIAL",
            "viewer is verified by the browser e2e test (tests/e2e/test_ui_flow.py, run in CI). Re-run this script with --with-browser to execute it here",
        )
    # 18 -------------------------------------------------------------------------------------------
    j, dt = op(18, "finalize", {"note": "acceptance"}, cur)
    final = j["result"]["version_id"]
    j, dt = op(18, "validate", {}, final)
    ctx.assets.designate_production_version(final, semver="1.0.0") if j["result"][
        "status"
    ] == "PRODUCTION_READY" else None
    vs = ctx.assets.list_versions(aid)
    rep.add(
        18,
        "PASS",
        f"{len(vs)} immutable versions: "
        + ", ".join(f"{x['label']}:{x['operation']}" for x in vs)
        + f"; CURRENT PRODUCTION VERSION = {ctx.assets.get_asset(aid)['production_version_id']}",
        dt,
    )
    # 19-21 ------------------------------------------------------------------------------------------
    t = time.perf_counter()
    e_glb = ctx.exports.export(final, "glb")
    kh = e_glb["report"].get("khronos", {})
    rep.add(
        19,
        "PASS" if e_glb["status"] == "COMPLETED" else "FAIL",
        f"{e_glb['size_bytes'] / 1e6:.2f} MB, sha256 {e_glb['sha256'][:16]}…, triangles per LOD {e_glb['report']['triangles']}; Khronos validator: "
        + (
            f"{kh['errors']} errors / {kh['warnings']} warnings (v{kh['validator_version']})"
            if kh.get("ran")
            else f"not run ({kh.get('reason')})"
        ),
        time.perf_counter() - t,
    )
    t = time.perf_counter()
    e_unity = ctx.exports.export(final, "unity")
    ex2 = [ctx.exports.export(final, f) for f in ("gltf", "obj")]
    rep.add(
        20,
        "PASS" if e_unity["status"] == "COMPLETED" else "FAIL",
        f"Unity package {e_unity['size_bytes'] / 1e6:.2f} MB with Models/ LOD/ Collision/ Materials/ Textures/ Metadata/ Editor/ Scripts/ README.md; also glTF {ex2[0]['status']}, OBJ {ex2[1]['status']}",
        time.perf_counter() - t,
    )
    ver = e_unity["report"]["verification"]
    rep.add(
        21,
        "PASS" if ver["ok"] and e_glb["report"]["verification"]["ok"] else "FAIL",
        f"{len(ver['checks'])} package checks + {len(e_glb['report']['verification']['checks'])} GLB checks re-read from disk (checksums, accessors, hierarchy, LOD counts, collision nodes)",
    )
    from aro_studio.verification.evidence import read_unity_evidence

    uev = read_unity_evidence(ROOT / "docs/acceptance/evidence/unity/unity-verification.json")
    rep.add(22, uev.status, uev.detail)
    state["export_dir"] = str(ctx.layout.export_dir(p["project_id"], e_unity["export_id"]))
    state["final_version"] = final
    state["khronos"] = kh
    shutil.copy2(ctx.exports.file_path(e_glb["export_id"]), Path(args.out) / "ARO-TITAN-480.glb") if Path(
        args.out
    ).exists() else None
    state["glb_path"] = str(ctx.exports.file_path(e_glb["export_id"]))


def write_reports(rep: Report, env: dict, state: dict, out: Path, seconds: float, data: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for r in rep.rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    from aro_studio.verification.components import compute, production_ready

    comps = compute(
        ROOT,
        {
            "validation_status": (state.get("validation") or {}).get("status"),
            "rows": rep.rows,
        },
    )
    complete = all(r["status"] == "PASS" for r in rep.rows) and production_ready(comps)
    verdict = "ACCEPTANCE CRITERIA SATISFIED" if complete else "NOT COMPLETE — production readiness is not claimed"
    md = [
        "# ARO TITAN 480 — acceptance run",
        "",
        f"**Verdict: {verdict}**",
        "",
        f"Studio {env['studio']} · Python {env['python']} · {env['platform']} · {env['resources']['cpu_count']} vCPU · {env['resources']['ram_total_mb']} MB RAM · GPU: {env['resources']['gpu']['name'] or 'none'} · run time {seconds:.0f}s",
        f"Pipeline input: **{state.get('source', 'n/a')}**",
        "",
        "Summary: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())),
        "",
        "## Component status (each reported separately; derived only from recorded evidence files)",
        "",
        "| Component | Status | Basis |",
        "|---|---|---|",
        *[f"| {c['component']} | **{c['status']}** | {c['detail'].replace('|', '/')[:420]} |" for c in comps],
        "",
        "ARO 3D Studio is production-ready only when **all seven** are PASS.",
        "",
        "## The 22 stages",
        "",
        "| # | Stage | Status | Detail | s |",
        "|---|---|---|---|---|",
    ]
    for r in rep.rows:
        md.append(
            f"| {r['n']} | {r['stage']} | **{r['status']}** | {r['detail'].replace('|', '/').replace(chr(10), ' ')} | {r['seconds']} |"
        )
    if state.get("validation"):
        v = state["validation"]
        md += [
            "",
            "## Production-readiness report",
            "",
            f"Status **{v['status']}** · overall **{v['overall']}%** · critical {v['critical_failures']} · major {v['major_failures']}",
            "",
            "| Category | Score |",
            "|---|---|",
        ]
        md += [
            f"| {'LOD' if k == 'lod' else k.title()} | {('n/a (not applicable)' if not c['applicable'] else str(c['score']) + '%')} |"
            for k, c in v["categories"].items()
        ]
        md += [
            "",
            "Note: this status is for the **procedural reference asset** passing the validation rules. It does not mean the platform acceptance is complete: see the BLOCKED/PARTIAL stages above.",
        ]
        if state.get("warnings"):
            md += ["", "Warnings (non-blocking):", *[f"* {w}" for w in state["warnings"]]]
    md += [
        "",
        "## What this run does and does not prove",
        "",
        "* Everything from raw asset onward (geometry, materials, vehicle, rig, collision, LOD, validation, versioning, export, verification) executed for real on a real, correctly-scaled, structured vehicle.",
        "* The AI reconstruction stages are listed as BLOCKED/PARTIAL where the engine could not run. **No placeholder geometry was substituted and none is claimed as AI output.**",
        "* The Unity 6 import status is whatever the component table above says; the package being generated and integrity-verified is not an import verification.",
        "",
    ]
    (out / "titan480-acceptance-report.md").write_text("\n".join(md), encoding="utf-8")
    (out / "titan480-acceptance-report.json").write_text(
        json.dumps(
            {"verdict": verdict, "components": comps, "env": env, "state": state, "stages": rep.rows},
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"\n{verdict}\nreport: {out / 'titan480-acceptance-report.md'}  (data kept in {data})")


if __name__ == "__main__":
    raise SystemExit(main())
