"""FastAPI application (spec §33-36, §39). The UI is a static SPA served from the same origin."""

from __future__ import annotations

import asyncio
import hmac
import json
import mimetypes
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from aro_studio import __version__
from aro_studio.api.schemas import (
    AssetCreate,
    AssetPatch,
    AutoProcessBody,
    DesignateBody,
    DuplicateBody,
    ExportBody,
    GenerateBody,
    ProcessBody,
    ProjectCreate,
    ProjectPatch,
    StatusBody,
)
from aro_studio.app_context import StudioContext, build_context
from aro_studio.assets import taxonomy
from aro_studio.assets.importer import import_mesh_bytes
from aro_studio.core.enums import JobState, Stage
from aro_studio.core.errors import (
    EngineUnavailableError,
    InvalidInputError,
    NotFoundError,
    RateLimitedError,
    StudioError,
    UnauthorizedError,
    explain_exception,
)
from aro_studio.core.ids import require_id
from aro_studio.export.gltf import ExportOptions, export_glb
from aro_studio.export.service import FORMATS as EXPORT_FORMATS
from aro_studio.geometry.pipeline import combined_report, known_operations
from aro_studio.imaging.preprocess import PreprocessOptions, preprocess
from aro_studio.observability.logging import get_logger
from aro_studio.observability.resources import cgroup_memory_limit_mb, snapshot
from aro_studio.processing.ai_pipeline import default_up_axis
from aro_studio.processing.service import OPERATIONS
from aro_studio.scene.model import Provenance
from aro_studio.security.filenames import sanitize_filename, slugify
from aro_studio.vehicles.titan480 import build_titan480

log = get_logger("api")
STATIC = Path(__file__).resolve().parent.parent / "ui" / "static"
CSP = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self' blob: data:; "
    "worker-src 'self' blob:; frame-ancestors 'self' https://huggingface.co https://*.hf.space; base-uri 'none'; form-action 'self'"
)


def form_flag(value: str | None, default: bool) -> bool:
    """A boolean multipart field with a REAL default.

    ``bool = Form(True)`` is not safe: recent FastAPI releases turn an ABSENT form boolean into ``False`` (checkbox semantics), which
    silently disabled the reconstruction cache and LOD generation for clients that simply omit the field.
    """
    if value is None or not str(value).strip():
        return default
    v = str(value).strip().lower()
    if v in ("1", "true", "on", "yes"):
        return True
    if v in ("0", "false", "off", "no"):
        return False
    raise InvalidInputError(f"'{value}' is not a valid true/false value.")


async def read_limited(f: UploadFile, max_bytes: int) -> bytes:
    """Read an upload in chunks, aborting as soon as it exceeds ``max_bytes`` (no unbounded buffering)."""
    chunks, total = [], 0
    while chunk := await f.read(1 << 20):
        total += len(chunk)
        if total > max_bytes:
            raise InvalidInputError(
                f"Upload exceeds the {max_bytes / 1e6:.0f} MB limit.", recommended_action="Reduce the file size."
            )
        chunks.append(chunk)
    return b"".join(chunks)


def create_app(ctx: StudioContext | None = None) -> FastAPI:
    holder: dict[str, StudioContext] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        if "ctx" in holder and ctx is None:  # we built it, so we close it (worker threads, model, database)
            holder["ctx"].close()

    app = FastAPI(
        title="ARO 3D Studio",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    def get_ctx() -> StudioContext:
        if "ctx" not in holder:
            holder["ctx"] = ctx or build_context()
        return holder["ctx"]

    if ctx is not None:
        holder["ctx"] = ctx

    # -- middleware -----------------------------------------------------------------------------
    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        t0 = time.perf_counter()
        try:
            if path.startswith("/api") and path not in ("/api/health", "/api/docs", "/api/openapi.json"):
                c = get_ctx()
                token = c.settings.access_token
                client = request.client.host if request.client else "unknown"
                if token is not None:
                    supplied = request.headers.get("authorization", "")
                    supplied = supplied[7:] if supplied.lower().startswith("bearer ") else ""
                    if not hmac.compare_digest(supplied.encode(), token.get_secret_value().encode()):
                        raise UnauthorizedError(
                            "A valid access token is required.",
                            recommended_action="Open Settings and enter the access token.",
                        )
                    client = "token"
                if not (
                    request.method == "GET" and path.startswith("/api/jobs")
                ):  # job polling is a cheap read; never throttle progress UIs
                    c.limiter.check(client)
                if request.method in ("POST", "PUT", "PATCH", "DELETE") and any(
                    x in path
                    for x in (
                        "/generate",
                        "/batch-generate",
                        "/convert",
                        "/auto-process",
                        "/process",
                        "/export",
                        "/sources",
                        "/import",
                    )
                ):
                    c.heavy_limiter.check(client + ":heavy")
            response = await call_next(request)
        except StudioError as e:
            response = _error_response(e)
        except Exception as e:  # noqa: BLE001 - last line of defence: never leak a traceback
            log.exception("unhandled error on %s", path)
            ex = explain_exception(e)
            response = JSONResponse(
                {"error": {"code": ex.code, "message": ex.message, "recommended_action": ex.recommended_action}},
                status_code=500,
            )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Content-Security-Policy", CSP)
        if path.startswith("/api"):
            response.headers.setdefault("Cache-Control", "no-store")
            get_ctx().metrics.observe("http.request", time.perf_counter() - t0)
        return response

    @app.exception_handler(StudioError)
    async def studio_error(_: Request, e: StudioError):
        return _error_response(e)

    def _error_response(e: StudioError) -> JSONResponse:
        headers = {"Retry-After": str(e.details["retry_after_s"])} if "retry_after_s" in e.details else None
        return JSONResponse({"error": e.to_dict()}, status_code=e.http_status, headers=headers)

    C = Depends(get_ctx)

    # -- system -----------------------------------------------------------------------------------
    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/system")
    def system(c: StudioContext = C):
        res = snapshot(c.settings.data_dir)
        s = c.settings
        return {
            "version": __version__,
            "uptime_s": time.time() - c.started,
            "resources": res.to_dict(),
            "cgroup_memory_limit_mb": cgroup_memory_limit_mb(),
            "device_setting": s.device,
            "workers": s.workers,
            "queue": c.jobs.stats(),
            "metrics": c.metrics.snapshot(),
            "models": c.models.status(),
            "cache": c.generation.cache_stats(),
            "schema_version": c.db.schema_version,
            "auth_enabled": s.access_token is not None,
            "limits": {
                "max_upload_mb": s.max_upload_mb,
                "max_image_pixels": s.max_image_pixels,
                "min_image_side": s.min_image_side,
                "job_timeout_s": s.job_timeout_s,
                "tri_budget_lod0": s.tri_budget_lod0,
            },
            "data_dir_size_mb": round(c.layout.dir_size(c.layout.root) / 1e6, 2),
            "cache_size_mb": round(c.layout.dir_size(c.layout.root / "cache") / 1e6, 2),
        }

    @app.get("/api/taxonomy")
    def get_taxonomy():
        return {
            "groups": taxonomy.tree(),
            "geometry_operations": known_operations(),
            "processing_operations": OPERATIONS,
        }

    @app.get("/api/audit")
    def audit(limit: int = 100, c: StudioContext = C):
        return {"items": c.audit.recent(min(limit, 500))}

    @app.post("/api/maintenance/cleanup")
    def cleanup(purge_cache: bool = False, c: StudioContext = C):
        return c.jobs.submit("cleanup", {"purge_cache": purge_cache}, priority=9)

    @app.post("/api/models/unload")
    def unload(c: StudioContext = C):
        c.models.unload()
        return c.models.status()

    # -- projects ---------------------------------------------------------------------------------
    @app.get("/api/projects")
    def list_projects(status: str | None = None, q: str | None = None, c: StudioContext = C):
        return {"items": c.projects.list(status=status, q=q)}

    @app.post("/api/projects", status_code=201)
    def create_project(b: ProjectCreate, c: StudioContext = C):
        return c.projects.create(b.name, b.description, b.metadata)

    @app.get("/api/projects/{pid}")
    def get_project(pid: str, c: StudioContext = C):
        p = c.projects.get(pid)
        p["assets"] = c.assets.list_assets(project_id=pid)
        p["sources"] = c.sources.list(pid)
        return p

    @app.patch("/api/projects/{pid}")
    def patch_project(pid: str, b: ProjectPatch, c: StudioContext = C):
        if b.name:
            c.projects.rename(pid, b.name)
        if b.description is not None or b.metadata is not None:
            c.projects.update(pid, description=b.description, metadata=b.metadata)
        return c.projects.get(pid)

    @app.post("/api/projects/{pid}/archive")
    def archive_project(pid: str, c: StudioContext = C):
        return c.projects.archive(pid)

    @app.post("/api/projects/{pid}/restore")
    def restore_project(pid: str, c: StudioContext = C):
        return c.projects.restore(pid)

    @app.post("/api/projects/{pid}/duplicate", status_code=201)
    def duplicate_project(pid: str, b: DuplicateBody | None = None, c: StudioContext = C):
        return c.projects.duplicate(pid, b.name if b else None)

    @app.delete("/api/projects/{pid}", status_code=204)
    def delete_project(pid: str, permanent: bool = False, c: StudioContext = C):
        c.projects.delete(pid, permanent=permanent)
        return Response(status_code=204)

    @app.get("/api/projects/{pid}/history")
    def project_history(pid: str, c: StudioContext = C):
        return {"items": c.projects.history(pid)}

    @app.get("/api/projects/{pid}/archive.zip")
    def project_archive(pid: str, c: StudioContext = C):
        c.projects.get(pid)
        dest = c.layout.root / "tmp" / f"{require_id(pid, 'project')}.zip"
        c.projects.export_archive(pid, dest)
        name = f"{slugify(c.projects.get(pid)['name'])}-project.zip"
        return FileResponse(dest, media_type="application/zip", filename=name)

    # -- source images ----------------------------------------------------------------------------
    @app.post("/api/projects/{pid}/sources", status_code=201)
    async def upload_source(
        pid: str, file: UploadFile = File(...), category: str | None = Form(None), c: StudioContext = C
    ):
        data = await read_limited(file, c.settings.max_upload_mb * 1_000_000)
        group = taxonomy.get_category(category).group if category else None
        return await asyncio.to_thread(c.sources.add_image, pid, file.filename or "image", data, category_group=group)

    @app.post("/api/projects/{pid}/batch-generate", status_code=202)
    async def batch_generate(
        pid: str,
        files: list[UploadFile] = File(...),
        category: str = Form("other"),
        engine_id: str | None = Form(None),
        preset: str | None = Form(None),
        settings_json: str = Form("{}"),
        preprocess_json: str = Form("{}"),
        items_json: str = Form("[]"),
        use_cache: str | None = Form(None),
        force: bool = Form(False),
        priority: int = Form(5, ge=1, le=9),
        max_retries: int = Form(0, ge=0, le=3),
        c: StudioContext = C,
    ):
        """Upload up to ten independent object images and queue one real reconstruction job per image.

        A batch creates separate assets; it does not fuse multiple views of the same object.
        Invalid files are reported individually while valid files continue through the queue.
        """
        if not 1 <= len(files) <= 10:
            raise InvalidInputError("Choose between 1 and 10 images per batch.")

        project = c.projects.get(pid)
        if project["status"] != "active":
            raise InvalidInputError("Images can only be queued in an active project.")

        try:
            settings_value = json.loads(settings_json)
            preprocess_value = json.loads(preprocess_json)
            item_specs = json.loads(items_json)
            if not isinstance(settings_value, dict) or not isinstance(preprocess_value, dict):
                raise ValueError("Settings must be JSON objects.")
            if not isinstance(item_specs, list) or (item_specs and len(item_specs) != len(files)):
                raise ValueError("Per-image settings must be a list matching the uploaded files.")
            if not item_specs:
                item_specs = [{} for _ in files]
            if any(not isinstance(spec, dict) for spec in item_specs):
                raise ValueError("Each per-image setting must be an object.")
            # Validate preprocessing before accepting work, so malformed options do not create doomed jobs.
            preprocess_value = PreprocessOptions(**preprocess_value).as_settings()
        except (ValueError, TypeError) as e:
            raise InvalidInputError(
                "Batch settings are invalid JSON objects or contain unsupported preprocessing options.",
                recommended_action="Review the generation and preprocessing settings, then try again.",
            ) from e

        batch_id = f"batch_{uuid.uuid4().hex[:20]}"
        items: list[dict[str, Any]] = []
        for index, upload in enumerate(files, start=1):
            original_name = sanitize_filename(upload.filename or f"image-{index}.png")
            asset = None
            try:
                spec = item_specs[index - 1]
                item_category = spec.get("category", category)
                category_def = taxonomy.require_creatable(item_category)
                data = await read_limited(upload, c.settings.max_upload_mb * 1_000_000)
                source = await asyncio.to_thread(
                    c.sources.add_image,
                    pid,
                    upload.filename or f"image-{index}.png",
                    data,
                    category_group=category_def.group,
                )
                stem = Path(original_name).stem
                default_name = " ".join(stem.replace("_", " ").replace("-", " ").split()) or f"Image {index}"
                requested_name = spec.get("name", default_name)
                if not isinstance(requested_name, str):
                    raise InvalidInputError("Asset name must be text.")
                asset_name = " ".join(requested_name.split())
                asset = c.assets.create_asset(
                    pid,
                    asset_name[:120],
                    item_category,
                    {
                        "source_filename": original_name,
                        "source_sha256": source["sha256"],
                        "ingestion_mode": "batch_image_to_3d",
                        "batch_id": batch_id,
                    },
                )
                params = {
                    "image_sha256": source["sha256"],
                    "engine_id": engine_id or None,
                    "preset": preset or None,
                    "settings": settings_value,
                    "preprocess": preprocess_value,
                    "use_cache": form_flag(use_cache, True),
                    "force": force,
                    "project_id": pid,
                    "asset_id": asset["asset_id"],
                    "batch_id": batch_id,
                }
                job = c.jobs.submit(
                    "generation",
                    params,
                    project_id=pid,
                    asset_id=asset["asset_id"],
                    priority=priority,
                    max_retries=max_retries,
                )
                items.append(
                    {
                        "index": index - 1,
                        "filename": original_name,
                        "status": "QUEUED",
                        "source": {"sha256": source["sha256"], "width": source["width"], "height": source["height"]},
                        "asset": {"asset_id": asset["asset_id"], "name": asset["name"], "category": asset["category"]},
                        "job": job,
                    }
                )
            except Exception as e:  # per-file failures must not discard successful sibling jobs
                ex = explain_exception(e)
                log.warning("batch image %d failed (%s)", index, type(e).__name__)
                items.append(
                    {
                        "index": index - 1,
                        "filename": original_name,
                        "status": "FAILED",
                        "asset": (
                            {"asset_id": asset["asset_id"], "name": asset["name"], "category": asset["category"]}
                            if asset
                            else None
                        ),
                        "error": {
                            "code": ex.code,
                            "message": ex.message,
                            "recommended_action": ex.recommended_action,
                        },
                    }
                )
            finally:
                await upload.close()

        queued = sum(item["status"] == "QUEUED" for item in items)
        failed = len(items) - queued
        return {"batch_id": batch_id, "total": len(items), "queued": queued, "failed": failed, "items": items}

    # -- one-click image -> 3D -------------------------------------------------------------------------------
    QUICK_PROJECT = "Quick conversions"

    @app.post("/api/convert", status_code=202)
    async def convert_to_3d(
        file: UploadFile = File(...),
        name: str | None = Form(None),
        category: str = Form("other"),
        project_id: str | None = Form(None),
        engine_id: str | None = Form(None),
        preset: str | None = Form(None),
        settings_json: str = Form("{}"),
        preprocess_json: str = Form("{}"),
        length_m: float | None = Form(None, gt=0.01, le=100),
        width_m: float | None = Form(None, gt=0.01, le=100),
        height_m: float | None = Form(None, gt=0.01, le=100),
        smooth_iterations: int = Form(40, ge=0, le=100),
        auto_align_yaw: str | None = Form(None),
        up: str | None = Form(None, pattern=r"^[+-][XYZ]$"),
        forward: str | None = Form(None, pattern=r"^[+-][XYZ]$"),
        target_triangles: int = Form(24_000, ge=100, le=25_000),
        texture_resolution: int = Form(1024),
        lod: str | None = Form(None),
        formats: str = Form("glb"),
        use_cache: str | None = Form(None),
        force: bool = Form(False),
        priority: int = Form(5, ge=1, le=9),
        max_retries: int = Form(0, ge=0, le=3),
        c: StudioContext = C,
    ):
        """Upload ONE image and queue reconstruct -> prepare -> export as a single job.

        The real engine must be able to run: otherwise this answers immediately with the exact reasons and creates nothing
        (no asset, no placeholder). Everything after the upload is the existing generation / preparation / export code.
        """
        if up and forward and up[1] == forward[1]:
            raise InvalidInputError("Up and forward directions must use different axes.")
        if texture_resolution not in (512, 1024, 2048):
            raise InvalidInputError("texture_resolution must be 512, 1024 or 2048.")
        fmts = [f for f in (x.strip() for x in formats.split(",")) if f]
        if not fmts or len(fmts) > 8 or any(f not in EXPORT_FORMATS for f in fmts):
            raise InvalidInputError(f"formats must be a comma-separated list of {', '.join(EXPORT_FORMATS)}.")
        category_def = taxonomy.require_creatable(category)
        try:
            settings_value = json.loads(settings_json)
            preprocess_value = json.loads(preprocess_json)
            if not isinstance(settings_value, dict) or not isinstance(preprocess_value, dict):
                raise ValueError("Settings must be JSON objects.")
            preprocess_value = PreprocessOptions(**preprocess_value).as_settings()
        except (ValueError, TypeError) as e:
            raise InvalidInputError(
                "Settings are invalid JSON objects or contain unsupported preprocessing options.",
                recommended_action="Review the generation and preprocessing settings, then try again.",
            ) from e

        # fail fast and honestly: no job, no asset if the engine cannot run here
        want = engine_id or c.settings.default_engine
        status = next((e for e in c.generation.engine_status() if e["info"]["id"] == want), None)
        if status is None:
            raise InvalidInputError(f"Unknown engine '{want}'.", recommended_action="See GET /api/engines.")
        if not status["runnable"]:
            reasons = list(status["availability"]["reasons"])
            actions = list(status["availability"]["activation"])
            if not status["license_verified_by_deployer"]:
                lic = status["info"]["license"]
                reasons.append(
                    f"The weights licence ({lic['spdx']}) is '{lic['status']}' and has not been verified by the deployer."
                )
                actions.append(
                    f"Read the model card at {lic['source_url']}; if it permits your use, set "
                    f"ARO_VERIFIED_MODEL_LICENSES={want}. That attestation is yours: the Studio never sets it."
                )
            raise EngineUnavailableError(
                f"{status['info']['name']} cannot run in this environment: " + " ".join(reasons),
                recommended_action=" | ".join(actions) or "See docs/models/model-requirements.md.",
                details=status,
            )

        if project_id:
            project = c.projects.get(project_id)
            if project["status"] != "active":
                raise InvalidInputError("Images can only be converted in an active project.")
        else:
            existing = [p for p in c.projects.list(status="active") if p["name"] == QUICK_PROJECT]
            project = (
                existing[0]
                if existing
                else c.projects.create(QUICK_PROJECT, "Created automatically for one-click conversions.")
            )
        pid = project["project_id"]

        original_name = sanitize_filename(file.filename or "image.png")
        data = await read_limited(file, c.settings.max_upload_mb * 1_000_000)
        source = await asyncio.to_thread(
            c.sources.add_image, pid, file.filename or "image.png", data, category_group=category_def.group
        )  # content validation happens here; a bad file stops the request before any asset exists
        stem = " ".join(Path(original_name).stem.replace("_", " ").replace("-", " ").split()) or "Image"
        asset_name = " ".join((name or stem).split())[:120]
        asset = c.assets.create_asset(
            pid,
            asset_name,
            category,
            {"source_filename": original_name, "source_sha256": source["sha256"], "ingestion_mode": "convert_to_3d"},
        )
        params: dict[str, Any] = {
            "project_id": pid,
            "asset_id": asset["asset_id"],
            "image_sha256": source["sha256"],
            "engine_id": engine_id or None,
            "preset": preset or None,
            "settings": settings_value,
            "preprocess": preprocess_value,
            "use_cache": form_flag(use_cache, True),
            "force": force,
            "target_triangles": target_triangles,
            "texture_resolution": texture_resolution,
            "lod": form_flag(lod, True),
            "formats": fmts,
            "length_supplied": length_m is not None,  # otherwise the size is a flagged placeholder
        }
        params["smooth_iterations"] = smooth_iterations
        params["auto_align_yaw"] = form_flag(auto_align_yaw, True)
        for key, value in (
            ("length_m", length_m),
            ("width_m", width_m),
            ("height_m", height_m),
            ("up", up),
            ("forward", forward),
        ):
            if value is not None:
                params[key] = value
        job = c.jobs.submit(
            "convert", params, project_id=pid, asset_id=asset["asset_id"], priority=priority, max_retries=max_retries
        )
        return {
            "job": job,
            "project": {"project_id": pid, "name": project["name"]},
            "asset": {"asset_id": asset["asset_id"], "name": asset["name"], "category": asset["category"]},
            "source": {"sha256": source["sha256"], "width": source["width"], "height": source["height"]},
        }

    @app.get("/api/projects/{pid}/sources/{sha}/image")
    def source_image(pid: str, sha: str, c: StudioContext = C):
        p = c.sources.path(pid, sha)
        return FileResponse(
            p,
            media_type=mimetypes.guess_type(p.name)[0] or "application/octet-stream",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @app.get("/api/projects/{pid}/sources/{sha}/preprocessed.png")
    def source_preprocessed(
        pid: str,
        sha: str,
        remove_background: str = "auto",
        foreground_ratio: float = 0.85,
        size: int = 512,
        c: StudioContext = C,
    ):
        img = c.sources.open(pid, sha)
        pre = preprocess(
            img,
            PreprocessOptions(
                remove_background=remove_background,
                foreground_ratio=foreground_ratio,
                output_size=max(64, min(1024, size)),
            ),
        )
        import io

        buf = io.BytesIO()
        pre.image.save(buf, "PNG")
        return Response(
            buf.getvalue(),
            media_type="image/png",
            headers={"X-Preprocess-Steps": json.dumps([s["step"] for s in pre.steps])},
        )

    # -- assets & versions ------------------------------------------------------------------------
    @app.get("/api/assets")
    def list_assets(
        project_id: str | None = None,
        category: str | None = None,
        status: str | None = None,
        q: str | None = None,
        c: StudioContext = C,
    ):
        items = c.assets.list_assets(project_id=project_id, category=category, status=status, q=q)
        for a in items:
            lv = c.assets.latest_version(a["asset_id"])
            a["latest_version"] = lv
            a["version_count"] = len(c.assets.list_versions(a["asset_id"]))
        return {"items": items}

    @app.post("/api/projects/{pid}/assets", status_code=201)
    def create_asset(pid: str, b: AssetCreate, c: StudioContext = C):
        return c.assets.create_asset(pid, b.name, b.category, b.metadata)

    @app.get("/api/assets/{aid}")
    def get_asset(aid: str, c: StudioContext = C):
        a = c.assets.get_asset(aid)
        a["versions"] = c.assets.list_versions(aid)
        a["generations"] = c.generation.list_generations(asset_id=aid, limit=20)
        a["exports"] = c.exports.list(asset_id=aid)
        return a

    @app.patch("/api/assets/{aid}")
    def patch_asset(aid: str, b: AssetPatch, c: StudioContext = C):
        if b.name:
            c.assets.rename_asset(aid, b.name)
        if b.metadata is not None:
            c.assets.update_metadata(aid, b.metadata)
        return c.assets.get_asset(aid)

    @app.post("/api/assets/{aid}/status")
    def set_status(aid: str, b: StatusBody, c: StudioContext = C):
        return c.assets.set_status(aid, b.status)

    @app.delete("/api/assets/{aid}", status_code=204)
    def delete_asset(aid: str, c: StudioContext = C):
        c.assets.delete_asset(aid)
        return Response(status_code=204)

    @app.get("/api/versions/{vid}")
    def get_version(vid: str, c: StudioContext = C):
        v = c.assets.get_version(vid)
        sc = c.assets.load_scene(vid)
        m = sc.manifest
        v["scene"] = {
            "manifest": json.loads(m.model_dump_json(exclude={"files"})),
            "reports": list(sc.reports),
            "lod_levels": m.lod_levels,
            "stats": {
                "parts": len(m.parts),
                "triangles": sc.triangle_count,
                "vertices": sc.vertex_count,
                "materials": len(m.materials),
                "textures": len(m.textures),
                "colliders": len(m.colliders),
                "lods": {
                    f"LOD{lv}": (
                        sc.triangle_count if lv == 0 else sum(len(x.faces) for x in sc.lod_meshes[lv].values())
                    )
                    for lv in m.lod_levels
                },
            },
        }
        v["validation"] = c.validation.latest(vid)
        return v

    @app.get("/api/versions/{vid}/reports/{name}")
    def version_report(vid: str, name: str, c: StudioContext = C):
        sc = c.assets.load_scene(vid)
        if name not in sc.reports:
            raise NotFoundError("Report not found.")
        return sc.reports[name]

    @app.get("/api/versions/{vid}/preview.glb")
    def preview(vid: str, c: StudioContext = C):
        require_id(vid, "version")
        c.assets.get_version(vid)
        cache = c.layout.root / "cache" / "preview"
        cache.mkdir(parents=True, exist_ok=True)
        f = cache / f"{vid}.glb"
        if not f.exists():
            sc = c.assets.load_scene(vid)
            data, _ = export_glb(sc, ExportOptions())
            tmp = f.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(f)
        return FileResponse(f, media_type="model/gltf-binary", headers={"Cache-Control": "private, max-age=3600"})

    @app.post("/api/versions/{vid}/inspect")
    def inspect_version(vid: str, c: StudioContext = C):
        sc = c.assets.load_scene(vid)
        a = c.assets.get_asset(c.assets.get_version(vid)["asset_id"])
        return combined_report(sc, category=a["category"], tri_budget=c.settings.tri_budget_lod0).to_dict()

    @app.post("/api/versions/{vid}/designate-production")
    def designate(vid: str, b: DesignateBody, c: StudioContext = C):
        return c.assets.designate_production_version(vid, semver=b.semver)

    @app.delete("/api/versions/{vid}", status_code=204)
    def delete_version(vid: str, c: StudioContext = C):
        c.assets.delete_version(vid)
        return Response(status_code=204)

    @app.get("/api/versions/{vid}/validation")
    def latest_validation(vid: str, c: StudioContext = C):
        r = c.validation.latest(vid)
        if r is None:
            raise NotFoundError("This version has not been validated yet.", recommended_action="Run validation first.")
        return r

    @app.get("/api/validations")
    def list_validations(asset_id: str | None = None, c: StudioContext = C):
        return {"items": c.validation.list(asset_id=asset_id)}

    @app.get("/api/validations/{valid}")
    def get_validation(valid: str, c: StudioContext = C):
        return c.validation.get(valid)

    # -- import / reference -----------------------------------------------------------------------
    @app.post("/api/assets/{aid}/import", status_code=201)
    async def import_mesh(aid: str, file: UploadFile = File(...), c: StudioContext = C):
        asset = c.assets.get_asset(aid)
        data = await read_limited(file, c.settings.max_import_mb * 1_000_000)
        scene, rep = await asyncio.to_thread(
            import_mesh_bytes,
            data,
            file.filename or "mesh.glb",
            name=asset["name"],
            category=asset["category"],
            max_bytes=c.settings.max_import_mb * 1_000_000,
            max_archive_members=c.settings.max_archive_members,
            max_archive_mb=c.settings.max_archive_uncompressed_mb,
            tmp_root=c.layout.root / "tmp",  # private, studio-owned scratch space (never the shared system /tmp)
        )
        v = c.assets.add_version(
            aid,
            scene,
            stage=Stage.RAW,
            operation="import",
            description=f"Imported {sanitize_filename(file.filename or 'mesh')}",
        )
        return {"version": v, "report": rep}

    @app.post("/api/assets/{aid}/reference/titan480", status_code=201)
    def create_reference(aid: str, c: StudioContext = C):
        """Create the ARO TITAN 480 *procedural reference* as a raw version. It is not AI output and says so."""
        asset = c.assets.get_asset(aid)
        if asset["category"] != "heavy_truck":
            raise InvalidInputError(
                "The TITAN 480 reference is a heavy truck; create the asset in the 'heavy_truck' category."
            )
        sc = build_titan480(asset["name"])
        sc.manifest.provenance = Provenance(
            source="procedural_reference",
            note="Original procedurally authored ARO TITAN 480 reference. NOT an AI reconstruction.",
        )
        v = c.assets.add_version(
            aid,
            sc,
            stage=Stage.RAW,
            operation="reference.titan480",
            description="Procedural reference model (not AI-generated)",
        )
        return v

    # -- engines & generation ---------------------------------------------------------------------
    @app.get("/api/engines")
    def engines(c: StudioContext = C):
        return {
            "items": c.generation.engine_status(),
            "blocked": __import__("aro_studio.engines.registry", fromlist=["BLOCKED_MODELS"]).BLOCKED_MODELS,
        }

    @app.get("/api/models")
    def models(c: StudioContext = C):
        rows = c.db.query("SELECT * FROM models ORDER BY name")
        for r in rows:
            r["requirements"] = json.loads(r["requirements"] or "{}")
            r["versions"] = c.db.query(
                "SELECT version, revision, notes, registered_at FROM model_versions WHERE model_id=?", (r["model_id"],)
            )
        return {
            "items": rows,
            "events": c.db.query("SELECT * FROM model_events ORDER BY ts DESC LIMIT 50"),
            "status": c.models.status(),
        }

    @app.post("/api/assets/{aid}/generate", status_code=202)
    def generate(aid: str, b: GenerateBody, c: StudioContext = C):
        a = c.assets.get_asset(aid)
        params = b.model_dump(exclude={"priority", "max_retries"})
        params.update(project_id=a["project_id"], asset_id=aid)
        return c.jobs.submit(
            "generation",
            params,
            project_id=a["project_id"],
            asset_id=aid,
            priority=b.priority,
            max_retries=b.max_retries,
        )

    @app.get("/api/generations")
    def generations(project_id: str | None = None, asset_id: str | None = None, c: StudioContext = C):
        return {"items": c.generation.list_generations(project_id=project_id, asset_id=asset_id)}

    @app.get("/api/generations/{gid}")
    def generation(gid: str, c: StudioContext = C):
        return c.generation.get_generation(gid)

    # -- processing / export jobs -----------------------------------------------------------------
    @app.post("/api/versions/{vid}/process", status_code=202)
    def process(vid: str, b: ProcessBody, c: StudioContext = C):
        v = c.assets.get_version(vid)
        return c.jobs.submit(
            "processing",
            {"operation": b.operation, "version_id": vid, "params": b.params},
            project_id=v["project_id"],
            asset_id=v["asset_id"],
            priority=b.priority,
        )

    @app.post("/api/versions/{vid}/auto-process", status_code=202)
    def auto_process(vid: str, b: AutoProcessBody, c: StudioContext = C):
        v = c.assets.get_version(vid)
        if v["stage"] != Stage.RAW.value:
            raise InvalidInputError(
                "Automatic preparation must start from a raw mesh version.",
                recommended_action="Choose the original raw reconstruction in the Versions panel; existing versions are never overwritten.",
            )
        if b.forward and not b.up:
            inferred_up = default_up_axis(c.assets.load_scene(vid).manifest.provenance)
            if b.forward[1] == inferred_up[1]:
                raise InvalidInputError(
                    "The selected forward direction conflicts with this mesh's default up axis.",
                    recommended_action="Choose a forward direction on a different axis, or explicitly set both up and forward directions.",
                )
        params = b.model_dump(exclude={"priority"})
        params["raw_version_id"] = vid
        params["length_supplied"] = "length_m" in b.model_fields_set  # otherwise the size is an assumption
        return c.jobs.submit(
            "auto_process",
            params,
            project_id=v["project_id"],
            asset_id=v["asset_id"],
            priority=b.priority,
        )

    @app.post("/api/versions/{vid}/export", status_code=202)
    def export(vid: str, b: ExportBody, c: StudioContext = C):
        v = c.assets.get_version(vid)
        return c.jobs.submit(
            "export",
            {"version_id": vid, "formats": b.formats, "target": b.target},
            project_id=v["project_id"],
            asset_id=v["asset_id"],
            priority=b.priority,
        )

    @app.get("/api/export-formats")
    def export_formats(c: StudioContext = C):
        """Every export format and whether it can be written here (the optional Blender formats explain why not and how to enable them)."""
        return {"formats": c.exports.format_status()}

    @app.get("/api/exports")
    def list_exports(asset_id: str | None = None, project_id: str | None = None, c: StudioContext = C):
        return {"items": c.exports.list(asset_id=asset_id, project_id=project_id)}

    @app.get("/api/exports/{eid}")
    def get_export(eid: str, c: StudioContext = C):
        return c.exports.get(eid)

    @app.get("/api/exports/{eid}/download")
    def download_export(eid: str, c: StudioContext = C):
        p = c.exports.file_path(eid)
        e = c.exports.get(eid)
        return FileResponse(
            p,
            filename=sanitize_filename(p.name),
            media_type="model/gltf-binary" if e["format"] == "glb" else "application/zip",
        )

    @app.delete("/api/exports/{eid}", status_code=204)
    def delete_export(eid: str, c: StudioContext = C):
        c.exports.delete(eid)
        return Response(status_code=204)

    # -- jobs -------------------------------------------------------------------------------------
    @app.get("/api/jobs")
    def list_jobs(
        state: str | None = None,
        project_id: str | None = None,
        kind: str | None = None,
        limit: int = 100,
        c: StudioContext = C,
    ):
        return {
            "items": c.jobs.list(state=state, project_id=project_id, kind=kind, limit=min(limit, 500)),
            "stats": c.jobs.stats(),
        }

    @app.get("/api/jobs/{jid}")
    def get_job(jid: str, c: StudioContext = C):
        return c.jobs.get(jid)

    @app.get("/api/jobs/{jid}/events")
    def job_events(jid: str, after: int = 0, c: StudioContext = C):
        return {"items": c.jobs.events(jid, after)}

    @app.post("/api/jobs/{jid}/cancel")
    def cancel_job(jid: str, c: StudioContext = C):
        return c.jobs.cancel(jid)

    @app.post("/api/jobs/{jid}/requeue")
    def requeue_job(jid: str, c: StudioContext = C):
        return c.jobs.requeue(jid)

    @app.get("/api/jobs/{jid}/stream")
    async def stream_job(jid: str, c: StudioContext = C):
        c.jobs.get(jid)

        async def gen():
            last = 0
            while True:
                job = await asyncio.to_thread(c.jobs.get, jid)
                for ev in await asyncio.to_thread(c.jobs.events, jid, last):
                    last = ev["id"]
                    yield f"event: log\ndata: {json.dumps(ev)}\n\n"
                yield f"event: progress\ndata: {json.dumps({'state': job['state'], 'progress': job['progress'], 'message': job['message']})}\n\n"
                if JobState(job["state"]).is_terminal:
                    yield f"event: done\ndata: {json.dumps(job, default=str)}\n\n"
                    return
                await asyncio.sleep(0.5)

        return StreamingResponse(
            gen(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
        )

    # -- UI ---------------------------------------------------------------------------------------
    if STATIC.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC), name="static")

        @app.get("/")
        def index():
            return FileResponse(STATIC / "index.html", media_type="text/html")

    return app


_ = RateLimitedError, Any
