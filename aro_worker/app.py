"""The worker's HTTP API (protocol 1). One GPU, one job at a time; every call except /ping needs the bearer token.

GET    /ping                       liveness, no secrets
GET    /v1/engines                 manifests: version, licence claim, availability and the exact reasons it is not
POST   /v1/generate                multipart: image (RGBA cut-out), engine, settings (JSON)  -> 202 {job_id}
GET    /v1/jobs/{id}               state / progress / message / error / details
DELETE /v1/jobs/{id}               cancel (takes effect between stages)
GET    /v1/jobs/{id}/result        the GLB; header X-ARO-SHA256
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import logging
import queue
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image

from aro_worker import PROTOCOL
from aro_worker.engines.base import Cancelled, WorkerEngine, gpu_info

log = logging.getLogger("aro_worker")
MAX_PIXELS = 16_000_000
TERMINAL = ("done", "failed", "cancelled")


@dataclass
class Job:
    id: str
    engine: str
    settings: dict[str, Any]
    image: Image.Image
    state: str = "queued"
    progress: float = 0.0
    message: str = "queued"
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    result_path: Path | None = None
    sha256: str | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    created: float = field(default_factory=time.time)

    def public(self, position: int | None = None) -> dict[str, Any]:
        return {
            "job_id": self.id,
            "engine": self.engine,
            "state": self.state,
            "progress": round(self.progress, 3),
            "message": self.message,
            "error": self.error,
            "details": self.details if self.state == "done" else {},
            "queue_position": position,
            "sha256": self.sha256,
        }


def create_app(
    engines: list[WorkerEngine],
    token: str,
    *,
    max_upload_mb: int = 25,
    job_ttl_s: int = 3600,
    workdir: Path | None = None,
) -> FastAPI:
    if len(token) < 16:
        raise ValueError("the worker token must be at least 16 characters")
    by_id = {e.id: e for e in engines}
    root = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="aro_worker_"))
    root.mkdir(parents=True, exist_ok=True)
    jobs: dict[str, Job] = {}
    pending: queue.Queue[str] = queue.Queue()
    lock = threading.Lock()
    state: dict[str, Any] = {"loaded": None}

    def run_job(job: Job) -> None:
        eng = by_id[job.engine]
        try:
            job.state, job.message = "running", f"loading {eng.name}"
            if state["loaded"] != eng.id:
                if state["loaded"] and state["loaded"] in by_id:
                    by_id[state["loaded"]].unload()  # one model on the GPU at a time
                    state["loaded"] = None
                eng.load()
                state["loaded"] = eng.id
            if job.cancel.is_set():
                raise Cancelled()

            def progress(f: float, m: str) -> None:
                job.progress, job.message = max(0.0, min(1.0, f)), m

            res = eng.generate(job.image, job.settings, progress, job.cancel.is_set)
            out = root / f"{job.id}.glb"
            out.write_bytes(res.glb)
            job.sha256 = hashlib.sha256(res.glb).hexdigest()
            job.result_path = out
            job.details = {**res.details, "engine_version": eng.version, "glb_bytes": len(res.glb)}
            job.state, job.progress, job.message = "done", 1.0, "done"
        except Cancelled:
            job.state, job.message = "cancelled", "cancelled"
        except Exception as e:  # noqa: BLE001 - reported to the Studio verbatim, never turned into placeholder geometry
            log.exception("job %s failed", job.id)
            job.state, job.error, job.message = "failed", f"{type(e).__name__}: {e}"[:600], "failed"
            if "out of memory" in str(e).lower():
                job.error += " (GPU out of memory: use a smaller preset or a larger GPU)"
                eng.unload()
                state["loaded"] = None
        finally:
            job.image = None  # type: ignore[assignment]  # free the input

    def gpu_loop() -> None:
        while True:
            jid = pending.get()
            job = jobs.get(jid)
            if job is None or job.state == "cancelled":
                continue
            run_job(job)
            with lock:  # expire old jobs and their result files
                for k in [k for k, j in jobs.items() if j.state in TERMINAL and time.time() - j.created > job_ttl_s]:
                    p = jobs.pop(k).result_path
                    if p:
                        p.unlink(missing_ok=True)

    threading.Thread(target=gpu_loop, daemon=True, name="aro-worker-gpu").start()

    app = FastAPI(title="ARO GPU worker", docs_url=None, redoc_url=None, openapi_url=None)

    def auth(request: Request) -> None:
        got = request.headers.get("authorization", "")
        want = f"Bearer {token}"
        if not hmac.compare_digest(got.encode(), want.encode()):
            raise HTTPException(401, "invalid or missing bearer token")

    @app.get("/ping")
    def ping() -> dict[str, Any]:
        return {"ok": True, "protocol": PROTOCOL}

    @app.get("/v1/engines", dependencies=[Depends(auth)])
    def list_engines() -> dict[str, Any]:
        out = []
        for e in engines:
            m = e.manifest()
            m["warnings"] = e.warnings() if hasattr(e, "warnings") else []
            out.append(m)
        return {"protocol": PROTOCOL, "gpu": gpu_info(), "engines": out, "loaded": state["loaded"]}

    @app.post("/v1/generate", status_code=202, dependencies=[Depends(auth)])
    async def generate(
        image: UploadFile = File(...), engine: str = Form(...), settings: str = Form("{}")
    ) -> dict[str, Any]:
        eng = by_id.get(engine)
        if eng is None:
            raise HTTPException(404, f"unknown engine '{engine}'; available: {sorted(by_id)}")
        ok, reasons = eng.available()
        if not ok:
            raise HTTPException(409, f"engine '{engine}' is not available on this worker: {'; '.join(reasons)}")
        try:
            cfg = json.loads(settings or "{}")
            assert isinstance(cfg, dict)
        except (ValueError, AssertionError):
            raise HTTPException(422, "settings must be a JSON object") from None
        data = await image.read(max_upload_mb * 1_000_000 + 1)
        if len(data) > max_upload_mb * 1_000_000:
            raise HTTPException(413, f"image larger than {max_upload_mb} MB")
        try:
            img = Image.open(io.BytesIO(data))  # header only: the size is checked BEFORE the pixels are decoded
            too_big = img.width * img.height > MAX_PIXELS
            if not too_big:
                img.load()
        except Exception:  # noqa: BLE001
            raise HTTPException(422, "the upload is not a readable image") from None
        if too_big:
            raise HTTPException(413, f"image larger than {MAX_PIXELS:,} pixels")
        job = Job(uuid.uuid4().hex, engine, cfg, img.convert("RGBA"))
        with lock:
            jobs[job.id] = job
        pending.put(job.id)
        return {"job_id": job.id, "state": job.state}

    def get_job(jid: str) -> Job:
        job = jobs.get(jid)
        if job is None:
            raise HTTPException(404, "unknown or expired job")
        return job

    @app.get("/v1/jobs/{jid}", dependencies=[Depends(auth)])
    def job_status(jid: str) -> dict[str, Any]:
        job = get_job(jid)
        waiting = [j for j in sorted(jobs.values(), key=lambda j: j.created) if j.state == "queued"]
        pos = waiting.index(job) if job in waiting else None
        return job.public(pos)

    @app.delete("/v1/jobs/{jid}", dependencies=[Depends(auth)])
    def cancel(jid: str) -> dict[str, Any]:
        job = get_job(jid)
        job.cancel.set()
        if job.state == "queued":
            job.state, job.message = "cancelled", "cancelled"
        return job.public()

    @app.get("/v1/jobs/{jid}/result", dependencies=[Depends(auth)])
    def result(jid: str):
        job = get_job(jid)
        if job.state != "done" or job.result_path is None:
            return JSONResponse({"error": f"job is {job.state}"}, status_code=409)
        return FileResponse(
            job.result_path,
            media_type="model/gltf-binary",
            filename=f"{job.id}.glb",
            headers={"X-ARO-SHA256": job.sha256 or ""},
        )

    app.state.shutdown = lambda: shutil.rmtree(root, ignore_errors=True)
    app.state.jobs_view = lambda: list(jobs.values())  # for tests and diagnostics
    return app
