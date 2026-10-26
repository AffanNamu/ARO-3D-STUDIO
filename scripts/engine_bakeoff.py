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
    try:
        client = TestClient(create_app(ctx))
        t0 = time.time()
        form = {
            "category": category,
            "preset": preset,
            "engine_id": engine_id,
            "name": image.stem,
            "formats": "glb,unity",  # the Unity package is what gets imported into Unity 6 for the verification
        }
        if length_m:
            form["length_m"] = str(length_m)
        form.update(axes or {})
        r = client.post("/api/convert", files={"file": (image.name, image.read_bytes(), "image/png")}, data=form)
        if r.status_code >= 400:
            row.update(status="BLOCKED", reason=r.json().get("error", r.text)[:600])
            return row
        jid = r.json()["job"]["job_id"]
        while True:
            j = client.get(f"/api/jobs/{jid}").json()
            if j["state"] in TERMINAL:
                break
            print(f"  [{engine_id}] {j.get('progress', 0):.0%} {j.get('message', '')}", flush=True)
            time.sleep(3)
        row["total_seconds"] = round(time.time() - t0, 1)
        if j["state"] != "COMPLETED":
            err = j.get("error") or {}
            row.update(
                status="FAIL", reason=f"{j['state']}: {err.get('message', '')} {err.get('recommended_action', '')}"
            )
            return row
        res = j["result"]
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
        rep = fd.score_model(mesh, ref, category)
        d = rep.to_dict()
        (out / "fidelity.json").write_text(json.dumps(d, indent=2) + "\n")
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
        return row
    finally:
        ctx.close()
        shutil.rmtree(tmp, ignore_errors=True)


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
            lines.append(f"|  | | {r.get('reason', '')[:200]} | | | | | | | | | |")
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
    rows = []
    for text in a.case:
        image, category, length = parse_case(text)
        if not image.is_file():
            raise SystemExit(f"{image}: not found")
        for eng in [e.strip() for e in a.engines.split(",") if e.strip()]:
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
    return 0 if all(r.get("status") == "PASS" for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
