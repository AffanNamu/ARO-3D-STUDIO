"""Run the Studio's whole "Convert to 3D" pipeline headlessly: image bytes in, prepared GLB + raw GLB + thumbnail + report out.

This is the existing, tested Studio pipeline (matting -> engine -> orientation/scale -> mesh preparation -> UVs and texture projection ->
validation -> export), driven through its own HTTP app in memory. No new geometry logic lives here.
"""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aro_studio.api.app import create_app
from aro_studio.app_context import build_context
from aro_studio.config import Settings
from aro_worker.engines.base import WorkerEngine
from aro_worker.inprocess import InProcessEngine

TERMINAL = {
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "TIMEOUT",
    "INVALID_INPUT",
    "MODEL_ERROR",
    "RESOURCE_LIMIT",
    "NEEDS_HUMAN",
}


class PipelineError(Exception):
    """The Studio pipeline stopped. ``code`` is the Studio's stable error code, ``state`` its job state."""

    def __init__(self, code: str, message: str, state: str, recommended_action: str | None = None):
        super().__init__(message)
        self.code, self.message, self.state, self.recommended_action = code, message, state, recommended_action


@dataclass
class PipelineOutput:
    prepared_glb: bytes
    raw_glb: bytes
    thumbnail_png: bytes | None
    report: dict[str, Any]
    seconds: float
    stages: list[dict[str, Any]] = field(default_factory=list)


def run_pipeline(
    engine: WorkerEngine,
    image: bytes,
    *,
    filename: str,
    category: str,
    preset: str,
    seed: int | None,
    target_triangles: int,
    texture_resolution: int,
    length_m: float | None,
    verified_licenses: str,
    timeout_s: int,
    progress: Callable[[float, str], None] | None = None,
    workdir: Path | None = None,
) -> PipelineOutput:
    from fastapi.testclient import TestClient

    root = Path(tempfile.mkdtemp(prefix="aro_job_", dir=str(workdir) if workdir else None))
    settings = Settings(
        data_dir=root / "data",
        verified_model_licenses=verified_licenses,
        default_engine=engine.id,
        job_timeout_s=timeout_s,
        max_upload_mb=10,
    )
    ctx = build_context(settings, engines=[InProcessEngine(engine)])
    t0 = time.time()
    try:
        client = TestClient(create_app(ctx), raise_server_exceptions=False)
        form: dict[str, str] = {
            "category": category,
            "preset": preset,
            "engine_id": engine.id,
            "name": "generation",
            "formats": "glb",
            "target_triangles": str(target_triangles),
            "texture_resolution": str(texture_resolution),
            "settings_json": json.dumps({"seed": seed} if seed is not None else {}),
        }
        if length_m:
            form["length_m"] = str(length_m)
        r = client.post("/api/convert", files={"file": (filename, image, "application/octet-stream")}, data=form)
        if r.status_code >= 400:
            err = _error_of(r)
            raise PipelineError(err["code"], err["message"], "REJECTED", err.get("recommended_action"))
        job_id = r.json()["job"]["job_id"]
        last = ""
        while True:
            j = client.get(f"/api/jobs/{job_id}").json()
            if progress and f"{j.get('progress', 0):.2f}{j.get('message', '')}" != last:
                last = f"{j.get('progress', 0):.2f}{j.get('message', '')}"
                progress(float(j.get("progress", 0)), str(j.get("message", "")))
            if j["state"] in TERMINAL:
                break
            time.sleep(0.5)
        if j["state"] != "COMPLETED":
            err = j.get("error") or {}
            raise PipelineError(
                str(err.get("code") or j["state"]),
                str(err.get("message") or f"The pipeline ended in state {j['state']}."),
                j["state"],
                err.get("recommended_action"),
            )
        res = j["result"]
        prepared = client.get(res["download"]).content
        raws = sorted(ctx.layout.root.rglob("raw_output.glb"))
        if not raws:
            raise PipelineError("RAW_MISSING", "The engine's raw output was not kept by the pipeline.", "FAILED")
        raw = raws[0].read_bytes()
        stages = list(res.get("stages", []))
        report = {
            "validation": res.get("validation"),
            "needs_human": res.get("needs_human", []),
            "final_extents_m": res.get("final_extents_m"),
            "preparation_steps": res.get("preparation_steps", []),
            "stages": stages,
            "engine": res.get("engine"),
            "device": res.get("device"),
            "model_ran": res.get("model_ran"),
        }
        return PipelineOutput(prepared, raw, _thumbnail(prepared, root), report, time.time() - t0, stages)
    finally:
        ctx.close()
        shutil.rmtree(root, ignore_errors=True)


def _error_of(r: Any) -> dict[str, Any]:
    try:
        body = r.json()
    except ValueError:
        return {"code": f"HTTP_{r.status_code}", "message": "The pipeline refused the request."}
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        return {
            "code": str(err.get("code", f"HTTP_{r.status_code}")),
            "message": str(err.get("message", "")),
            "recommended_action": err.get("recommended_action"),
        }
    return {"code": f"HTTP_{r.status_code}", "message": "The pipeline refused the request."}


def _thumbnail(glb: bytes, root: Path) -> bytes | None:
    """A 512 px shaded render of LOD0 (the Studio's CPU renderer). A thumbnail must never fail a good model, so any error means none."""
    try:
        from aro_studio.quality.report import load_lod0
        from aro_studio.utils.render import render_scene

        path = root / "prepared_for_thumbnail.glb"
        path.write_bytes(glb)
        mesh = load_lod0(path)
        img = render_scene(
            [(mesh, (0.80, 0.80, 0.82, 1.0))], azimuth_deg=35, elevation_deg=15, size=512, smooth_shading=True
        )
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "PNG")
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        return None
