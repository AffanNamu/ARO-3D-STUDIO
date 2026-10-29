#!/usr/bin/env python
"""Engine bake-off: the same reference images through each GPU-worker engine, measured against the references.

    python scripts/engine_bakeoff.py --worker-url http://127.0.0.1:8000 --token "$ARO_WORKER_TOKEN" \
        --engines trellis2,triposg --verified-licences trellis2,triposg \
        --case truck.png:heavy_truck:7.0 --case suv.png:car:4.5 --preset STANDARD --out bakeoff/

For every engine x case it runs the Studio's real one-click flow (reconstruct on the worker -> prepare for games -> validate -> export),
then scores the prepared model against the reference image (silhouette overlap, proportions - see aro_studio/quality/fidelity.py) and
writes an inspection sheet. Run it on the GPU host itself or on any machine that can reach the worker.

Outputs in --out (one folder per engine/case): raw GLB exactly as the engine returned it (hash recorded), prepared GLB, fidelity JSON,
inspection sheet. Plus ``bakeoff-summary.json`` / ``bakeoff-summary.md`` with the table. Visual quality is NOT judged automatically:
``human_review`` stays PENDING until a person has looked at the sheets.

--verified-licences is YOUR attestation (same meaning as ARO_VERIFIED_MODEL_LICENSES): pass only engines whose model cards you read.
Without it the Studio's licence gate refuses to run them, which is the correct behaviour.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "RESOURCE_LIMIT", "MODEL_ERROR", "INVALID_INPUT"}


def peak_gb() -> float:
    """Peak resident memory of this process so far (Linux: ru_maxrss is in kB); 0 where the OS cannot say."""
    try:
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6
    except (ImportError, ValueError):
        return 0.0


def describe_http_error(response: Any) -> dict[str, Any]:
    """The Studio answers refusals with ``{"error": {"code", "message", "recommended_action"}}`` (FastAPI's own validation errors use
    ``{"detail": ...}``); anything else, or a body that is not JSON, is shown as text. Never assumes the field is a string."""
    try:
        body = response.json()
    except ValueError:
        body = None
    err = body.get("error") if isinstance(body, dict) else None
    if err is None and isinstance(body, dict):
        err = body.get("detail")
    if isinstance(err, dict):
        return {
            "http_status": response.status_code,
            "code": str(err.get("code", "")),
            "message": str(err.get("message", ""))[:600],
            "recommended_action": str(err.get("recommended_action", ""))[:600],
        }
    if isinstance(err, str):
        text = err
    elif err is not None:
        text = json.dumps(err)
    else:  # no error/detail field at all: show whatever the body was
        text = json.dumps(body) if body is not None else response.text
    return {"http_status": response.status_code, "code": "", "message": str(text)[:600], "recommended_action": ""}


def reason_text(err: dict[str, Any]) -> str:
    head = f"HTTP {err['http_status']}" + (f" {err['code']}" if err["code"] else "")
    return f"{head}: {err['message']}" + (f" -> {err['recommended_action']}" if err["recommended_action"] else "")


def parse_case(text: str) -> tuple[Path, str, float | None]:
    head, _, tail = text.rpartition(":")
    try:
        length: float | None = float(tail)
        spec = head
    except ValueError:
        length, spec = None, text
    image, _, category = spec.rpartition(":")
    if not image or not category:
        raise SystemExit(f"--case '{text}': use IMAGE:CATEGORY[:LENGTH_M], e.g. truck.png:heavy_truck:7.0")
    return Path(image), category, length


def _norm(name: str) -> str:
    """'01-ARO 480 Truck at Golden Hour (1).png' and 'ARO 480 Truck at Golden Hour.png' name the same reference."""
    stem = Path(name).stem.lower()
    stem = re.sub(r"^\d+[-_ ]+", "", stem)
    stem = re.sub(r"\s*\(\d+\)$", "", stem)
    return re.sub(r"[^a-z0-9]+", "", stem)


def load_baselines(directory: Path | None) -> dict[str, dict[str, Any]]:
    """TripoSR fidelity results committed in the repository (``score_model.py`` output), keyed by normalised reference image name."""
    found: dict[str, dict[str, Any]] = {}
    if directory is None or not directory.is_dir():
        return found
    for f in sorted(directory.rglob("*-fidelity.json")):
        d = json.loads(f.read_text())
        if d.get("reference"):
            found[_norm(d["reference"])] = {
                "label": d.get("label", f.stem),
                "silhouette_iou": d["silhouette_iou"],
                "ratios": d["proportions"]["ratios"],
                "proportions": d["proportions"]["verdict"],
                "meets_floor": d["meets_floor"],
                "triangles": d["mesh"]["triangles"],
                "source": str(f),
            }
    return found


def run_one(
    worker_url: str,
    token: str,
    engine_id: str,
    image: Path,
    category: str,
    length_m: float | None,
    preset: str,
    verified: str,
    timeout_s: int,
    out: Path,
    axes: dict[str, str] | None = None,
) -> dict[str, Any]:
    from fastapi.testclient import TestClient
    from PIL import Image
    from pydantic import SecretStr

    from aro_studio.api.app import create_app
    from aro_studio.app_context import build_context
    from aro_studio.config import Settings
    from aro_studio.engines.remote import RemoteEngine
    from aro_studio.quality import fidelity as fd
    from aro_studio.quality.report import load_lod0, make_sheet

    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="aro_bakeoff_"))
    s = Settings(
        data_dir=tmp / "data",
        worker_url=worker_url,
        worker_token=SecretStr(token),
        verified_model_licenses=verified,
        default_engine=engine_id,
        job_timeout_s=timeout_s,
    )
    eng = RemoteEngine(worker_url, token, engine_id, timeout_s=float(timeout_s))
    ctx = build_context(s, engines=[eng])
    row: dict[str, Any] = {"engine": engine_id, "image": image.name, "category": category, "preset": preset}
    blender_av = ctx.exports.blender.availability()
    blender_ok = bool(blender_av["ok"])
    client: Any = None
    jid: str | None = None
    try:
        client = TestClient(create_app(ctx))
        t0 = time.time()
        form = {
            "category": category,
            "preset": preset,
            "engine_id": engine_id,
            "name": image.stem,
            # the Unity package is what gets imported into Unity 6 for the verification; FBX only when Blender can verify it by re-import
            "formats": "glb,unity" + (",fbx" if blender_ok else ""),
        }
        if length_m:
            form["length_m"] = str(length_m)
        form.update(axes or {})
        r = client.post("/api/convert", files={"file": (image.name, image.read_bytes(), "image/png")}, data=form)
        if r.status_code >= 400:
            err = describe_http_error(r)
            row.update(status="BLOCKED", reason=reason_text(err), error=err)
            print(f"  BLOCKED before any inference: {row['reason']}", flush=True)
            attested = {v.strip().lower() for v in verified.split(",")}
            if engine_id.lower() not in attested and "licence" in (err["message"] + err["recommended_action"]).lower():
                row["hint"] = (
                    f"This is the licence gate working as designed, not a fault. After you have read the {engine_id} model card, "
                    f"pass --verified-licences {engine_id} (in the lab notebook: I_HAVE_READ_THE_MODEL_CARDS = True) and run again. "
                    "That attestation is yours; nothing sets it for you."
                )
                print(f"  HINT: {row['hint']}", flush=True)
            return row
        jid = r.json()["job"]["job_id"]
        last = ""
        while True:
            j = client.get(f"/api/jobs/{jid}").json()
            if j["state"] in TERMINAL:
                break
            line = f"{j.get('progress', 0):.0%} {j.get('message', '')}"
            if (
                line != last
            ):  # only changes, with the elapsed time: a stopped run shows exactly where and when it stopped
                print(f"  [{engine_id}] +{time.time() - t0:.0f}s {line}", flush=True)
                last = row["last_progress"] = line
            time.sleep(3)
        row["total_seconds"] = round(time.time() - t0, 1)

        def phase(
            what: str,
        ) -> None:  # the job prints no more progress after this: say what is happening and how much memory it has used
            print(
                f"  [{engine_id}] +{time.time() - t0:.0f}s after the job: {what} (peak memory {peak_gb():.1f} GB)",
                flush=True,
            )
            row["last_progress"] = f"after the job: {what}"

        phase(f"job {j['state']}")
        if j["state"] != "COMPLETED":
            err = j.get("error") or {}
            row.update(
                status="FAIL", reason=f"{j['state']}: {err.get('message', '')} {err.get('recommended_action', '')}"
            )
            return row
        res = j["result"]
        phase("downloading the prepared GLB, Unity package and FBX")
        glb = client.get(res["download"]).content
        prepared = out / "prepared.glb"
        prepared.write_bytes(glb)
        raws = sorted(ctx.layout.root.rglob("raw_output.glb"))
        if raws:
            shutil.copy2(raws[0], out / "raw_output.glb")
            row["raw_sha256"] = hashlib.sha256(raws[0].read_bytes()).hexdigest()
            row["raw_bytes"] = raws[0].stat().st_size
        unity = next((e for e in res.get("exports", []) if e.get("format") == "unity" and e.get("export_id")), None)
        if unity:
            u = client.get(f"/api/exports/{unity['export_id']}/download")
            if u.status_code == 200:
                (out / "unity-package.zip").write_bytes(u.content)
                row["unity_package_sha256"] = hashlib.sha256(u.content).hexdigest()
        fbx = next((e for e in res.get("exports", []) if e.get("format") == "fbx" and e.get("export_id")), None)
        if fbx:
            meta = client.get(f"/api/exports/{fbx['export_id']}").json()
            row["fbx_blender_verification"] = {
                "status": meta["status"],
                "checks": [
                    {k: c[k] for k in ("id", "ok")}
                    for c in (meta["report"].get("verification") or {}).get("checks", [])
                ],
            }
            f = client.get(f"/api/exports/{fbx['export_id']}/download")
            if f.status_code == 200:
                (out / "fbx-package.zip").write_bytes(f.content)
        if (
            blender_ok
        ):  # independent beauty renders: real texture sampling, normal map, PBR lighting (Blender Cycles on the CPU)
            try:
                phase("Blender beauty renders (CPU, a minute or two)")
                imgs = ctx.exports.blender.render(
                    prepared, out / "blender", views=("3q", "side", "front", "rear", "top"), size=640, samples=32
                )
                row["blender_renders"] = [p.name for p in imgs]
                phase("Blender turntable")
                ctx.exports.blender.turntable(prepared, out / "blender" / "turntable.gif")
                row["turntable"] = "blender/turntable.gif"
            except Exception as e:  # noqa: BLE001 - a nice-to-have must not fail a good run
                row["blender_renders_error"] = f"{type(e).__name__}: {str(e)[:200]}"
        else:
            row["blender_renders"] = "not available: " + "; ".join(blender_av["reasons"])[:200]
        try:  # what the engine and the Studio recorded about this run: timing, memory, detected frame, texture route
            gen = ctx.assets.load_scene(res["raw_version_id"]).reports.get("generation", {})
            det = gen.get("engine_details") or {}
            row["engine_details"] = {
                k: det.get(k)
                for k in ("worker_seconds", "peak_vram_allocated_mb", "engine_version", "pbr")
                if det.get(k) is not None
            } | {
                k: v
                for k, v in (det.get("worker_details") or {}).items()
                if k in ("surface_extractor", "raw_faces", "settings", "notes")
            }
            row["up_axis_detection"] = gen.get("up_axis_detection")
        except Exception as e:  # noqa: BLE001 - diagnostics must not fail a good run
            row["engine_details_error"] = f"{type(e).__name__}: {e}"
        ref = Image.open(image).convert("RGB")
        mesh = load_lod0(prepared)
        phase("scoring against the reference (silhouette search)")
        rep = fd.score_model(mesh, ref, category)
        d = rep.to_dict()
        (out / "fidelity.json").write_text(json.dumps(d, indent=2) + "\n")
        phase("contact sheet")
        make_sheet(mesh, ref, rep, out / "sheet.png")
        stages = {x["stage"]: x["status"] for x in res.get("stages", [])}
        row.update(
            status="PASS" if all(v == "COMPLETED" for v in stages.values()) and stages else "PARTIAL",
            engine_version=res.get("engine", {}).get("version"),
            engine_name=res.get("engine", {}).get("name"),
            stages=stages,
            silhouette_iou=rep.silhouette_iou,
            aspect_error=rep.aspect_error,
            ratios=rep.proportions["ratios"],
            proportions=rep.proportions["verdict"],
            meets_floor=rep.meets_floor,
            prepared_triangles=rep.mesh["triangles"],
            prepared_components=rep.mesh["components"],
            has_uv=rep.mesh["has_uv"],
            validation=(res.get("validation") or {}).get("status") or res.get("validation_status"),
            needs_human=res.get("needs_human", []),
            final_extents_m=res.get("final_extents_m"),
            glb_sha256=hashlib.sha256(glb).hexdigest(),
            human_review="PENDING",
        )
        row["peak_memory_gb"] = round(peak_gb(), 2)
        phase("done")
        return row
    except (
        KeyboardInterrupt
    ):  # SIGINT: Colab's "interrupt execution", a stop button, or Ctrl+C. Report it, keep what exists.
        row.update(
            status="FAIL",
            interrupted=True,
            reason="INTERRUPTED (SIGINT, not an engine fault) while: " + row.get("last_progress", "starting"),
        )
        print(f"  {row['reason']}", flush=True)
        _stop_job(client, jid, row)
        return row
    finally:
        _rescue_raw(
            ctx, out, row
        )  # before the working folder is deleted: the engine's mesh is the one irreplaceable file
        ctx.close()
        _remove_tree(tmp)


def _stop_job(client: Any, jid: str | None, row: dict[str, Any], wait_s: float = 90.0) -> None:
    """Cancel the Studio's job and wait for it to end. Without this the job's thread keeps writing into the working folder that is about
    to be deleted (and into a database that is about to be closed): CI left a half-deleted folder behind."""
    if client is None or jid is None:
        return
    state = "unknown"
    try:
        client.post(f"/api/jobs/{jid}/cancel")
        end = time.time() + wait_s
        while time.time() < end:
            state = client.get(f"/api/jobs/{jid}").json()["state"]
            if state in TERMINAL:
                break
            time.sleep(0.5)
        row["job_state_after_interrupt"] = state
    except KeyboardInterrupt:  # a second interrupt: stop waiting
        row["job_state_after_interrupt"] = f"{state} (not waited for: second interrupt)"
    except Exception as e:  # noqa: BLE001 - cleanup must not hide the real outcome
        row["job_cancel_error"] = f"{type(e).__name__}: {e}"


def _remove_tree(path: Path, attempts: int = 6) -> None:
    for _ in range(attempts):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        time.sleep(0.5)


def _rescue_raw(ctx: Any, out: Path, row: dict[str, Any]) -> None:
    """Copy the engine's raw mesh into the results folder if the run ended (or was interrupted) before that happened."""
    try:
        target = out / "raw_output.glb"
        raws = sorted(ctx.layout.root.rglob("raw_output.glb"))
        if raws and not target.exists():
            out.mkdir(parents=True, exist_ok=True)
            shutil.copy2(raws[0], target)
            row["raw_sha256"] = hashlib.sha256(raws[0].read_bytes()).hexdigest()
            row["raw_bytes"] = raws[0].stat().st_size
            row["raw_rescued"] = True
            print(f"  raw mesh kept: {target} ({row['raw_bytes']} bytes)", flush=True)
    except Exception as e:  # noqa: BLE001 - never mask the real outcome
        row["raw_rescue_error"] = f"{type(e).__name__}: {e}"


def markdown(rows: list[dict[str, Any]], baselines: dict[str, dict[str, Any]] | None = None) -> str:
    head = (
        "| Engine | Image | Status | IoU | W/L | H/L | Proportions | Floor | Tris | Components | Validation | Seconds |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|\n"
    )
    lines = []
    shown: set[str] = set()
    for r in rows:
        base = (baselines or {}).get(_norm(r["image"]))
        if (
            base and r["image"] not in shown
        ):  # the TripoSR result for the SAME reference, committed earlier, as the yardstick
            shown.add(r["image"])
            b = base["ratios"]
            lines.append(
                f"| triposr (baseline) | {r['image']} | measured earlier | {base['silhouette_iou']:.2f} | {b['width_over_length']:.2f} | "
                f"{b['height_over_length']:.2f} | {base['proportions']} | {'yes' if base['meets_floor'] else 'NO'} | {base['triangles']} | - | - | - |"
            )
    for r in rows:
        if r.get("status") in ("BLOCKED", "FAIL"):
            lines.append(f"| {r['engine']} | {r['image']} | **{r['status']}** | - | - | - | - | - | - | - | - | - |")
            lines.append(f"|  | | {r.get('reason', '')[:500]} | | | | | | | | | |")
            if r.get("hint"):
                lines.append(f"|  | | {r['hint']} | | | | | | | | | |")
            continue
        ra = r["ratios"]
        lines.append(
            f"| {r['engine']} | {r['image']} | **{r['status']}** | {r['silhouette_iou']:.2f} | {ra['width_over_length']:.2f} | "
            f"{ra['height_over_length']:.2f} | {r['proportions']} | {'yes' if r['meets_floor'] else 'NO'} | {r['prepared_triangles']} | "
            f"{r['prepared_components']} | {r['validation']} | {r['total_seconds']} |"
        )
    return (
        "# Engine bake-off\n\nMeasured against the reference images (silhouette + proportions). Visual quality: **PENDING human review** "
        "of each `sheet.png`; this table does not judge surface detail, wheels, texture or whether it looks right.\n\n"
        + head
        + "\n".join(lines)
        + "\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--worker-url", required=True)
    ap.add_argument("--token", default=os.environ.get("ARO_WORKER_TOKEN", ""))
    ap.add_argument("--engines", default="trellis2,triposg")
    ap.add_argument("--case", action="append", required=True, help="IMAGE:CATEGORY[:LENGTH_M] (repeatable)")
    ap.add_argument("--preset", default="STANDARD")
    ap.add_argument("--verified-licences", default="", help="engine ids whose model-card licence YOU have read")
    ap.add_argument(
        "--up", default="", help="raw up axis (+Y, +Z...) if an engine's frame is not glTF's +Y (default: per engine)"
    )
    ap.add_argument(
        "--forward",
        default="",
        help="raw forward axis; default: the longest horizontal extent (a guess, see needs_human)",
    )
    ap.add_argument("--timeout-s", type=int, default=3600)
    ap.add_argument(
        "--baseline-dir",
        type=Path,
        default=ROOT / "docs" / "acceptance" / "evidence" / "quality",
        help="folder with committed TripoSR *-fidelity.json files: the same reference's TripoSR result is shown first",
    )
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    baselines = load_baselines(a.baseline_dir)
    if not a.token:
        raise SystemExit("--token or ARO_WORKER_TOKEN is required")
    axes = {k: v for k, v in (("up", a.up), ("forward", a.forward)) if v}
    rows: list[dict[str, Any]] = []
    for text in a.case:
        if rows and rows[-1].get("interrupted"):
            break
        image, category, length = parse_case(text)
        if not image.is_file():
            raise SystemExit(f"{image}: not found")
        for eng in [e.strip() for e in a.engines.split(",") if e.strip()]:
            if rows and rows[-1].get("interrupted"):
                break
            print(f"== {eng} / {image.name} ({category})", flush=True)
            rows.append(
                run_one(
                    a.worker_url,
                    a.token,
                    eng,
                    image,
                    category,
                    length,
                    a.preset,
                    a.verified_licences,
                    a.timeout_s,
                    a.out / f"{eng}-{image.stem}",
                    axes,
                )
            )
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "bakeoff-summary.json").write_text(
        json.dumps({"rows": rows, "triposr_baselines": baselines}, indent=2) + "\n"
    )
    (a.out / "bakeoff-summary.md").write_text(markdown(rows, baselines))
    print(markdown(rows, baselines))
    if rows and rows[-1].get("interrupted"):
        print("The run was interrupted; the rows above are what finished. Nothing else was started.", flush=True)
        return 130
    return 0 if all(r.get("status") == "PASS" for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
