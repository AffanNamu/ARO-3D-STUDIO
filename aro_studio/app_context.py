"""Composition root: builds every service from ``Settings`` (no globals besides settings)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from aro_studio.assets.service import AssetService
from aro_studio.config import Settings, get_settings
from aro_studio.core.errors import StudioError
from aro_studio.db.database import Database
from aro_studio.engines.manager import ModelManager
from aro_studio.engines.registry import EngineRegistry
from aro_studio.engines.triposr import TripoSREngine
from aro_studio.export.service import ExportService
from aro_studio.generation.service import GenerationService
from aro_studio.jobs.queue import JobQueue
from aro_studio.observability.logging import configure_logging
from aro_studio.observability.metrics import Metrics
from aro_studio.processing.ai_pipeline import AIPipelineOptions, default_up_axis, run_ai_pipeline
from aro_studio.processing.service import OPERATIONS, ProcessingService
from aro_studio.projects.service import ProjectService
from aro_studio.projects.sources import SourceService
from aro_studio.security.audit import AuditLog
from aro_studio.security.ratelimit import RateLimiter
from aro_studio.storage.layout import StorageLayout
from aro_studio.validation.service import ValidationService


@dataclass
class StudioContext:
    settings: Settings
    db: Database
    layout: StorageLayout
    audit: AuditLog
    metrics: Metrics
    assets: AssetService
    projects: ProjectService
    sources: SourceService
    registry: EngineRegistry
    models: ModelManager
    validation: ValidationService
    processing: ProcessingService
    generation: GenerationService
    exports: ExportService
    jobs: JobQueue
    limiter: RateLimiter
    heavy_limiter: RateLimiter
    started: float = field(default_factory=time.time)

    def close(self) -> None:
        self.jobs.stop()
        self.models.unload()
        self.db.close()


def build_context(
    settings: Settings | None = None, *, start_workers: bool = True, engines: list | None = None
) -> StudioContext:
    s = settings or get_settings()
    layout = StorageLayout(s.data_dir)
    configure_logging(s.log_level, layout.logs_dir())
    layout.clean_tmp()
    db = Database(s.db_path)
    audit, metrics = AuditLog(db), Metrics()
    assets = AssetService(db, layout, audit)
    projects = ProjectService(db, layout, assets, audit)
    sources = SourceService(
        db, layout, max_bytes=s.max_upload_mb * 1_000_000, max_pixels=s.max_image_pixels, min_side=s.min_image_side
    )
    registry = EngineRegistry()
    for e in (
        engines
        if engines is not None
        else [TripoSREngine(s.triposr_model_path, s.hf_token.get_secret_value() if s.hf_token else None)]
    ):
        registry.register(e)
        _record_model(db, e)
    models = ModelManager(registry, db, s.model_idle_unload_s)
    validation = ValidationService(s, db, assets)
    processing = ProcessingService(s, assets, validation)
    generation = GenerationService(s, db, layout, assets, sources, registry, models, metrics)
    exports = ExportService(db, layout, assets, audit)
    jobs = JobQueue(
        db,
        workers=s.workers,
        default_timeout_s=s.job_timeout_s,
        min_free_disk_mb=s.min_free_disk_mb,
        min_free_ram_mb=min(s.min_free_ram_mb, 512),
        data_dir=str(s.data_dir),
        metrics=metrics,
        on_idle=lambda: bool(models.unload_if_idle()),
    )
    jobs.register("generation", generation.handle, heavy=True)
    jobs.register("processing", processing.handle, heavy=False)
    jobs.register("auto_process", _auto_process_handler(processing, assets, s), heavy=True)
    jobs.register("export", _export_handler(exports), heavy=False)
    jobs.register("cleanup", _cleanup_handler(layout, db), heavy=False)
    if start_workers:
        jobs.start()
    return StudioContext(
        s,
        db,
        layout,
        audit,
        metrics,
        assets,
        projects,
        sources,
        registry,
        models,
        validation,
        processing,
        generation,
        exports,
        jobs,
        RateLimiter(s.rate_limit_per_minute),
        RateLimiter(s.heavy_rate_limit_per_minute),
    )


def _record_model(db: Database, engine) -> None:
    i, lic = engine.info, engine.info.license
    db.execute(
        "INSERT OR REPLACE INTO models(model_id,name,capability,source,license,license_status,commercial_use,requirements,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            i.id,
            i.name,
            i.capability,
            i.source_url,
            lic.spdx,
            lic.status,
            lic.commercial_use,
            __import__("json").dumps(i.requirements),
            time.time(),
        ),
    )
    db.execute(
        "INSERT OR IGNORE INTO model_versions(model_id,version,revision,notes,registered_at) VALUES (?,?,?,?,?)",
        (i.id, i.version, i.revision, lic.notes[:500], time.time()),
    )


def _auto_process_handler(processing: ProcessingService, assets: AssetService, settings: Settings):
    """Build a queued, non-destructive auto-preparation job for raw reconstruction meshes."""

    def run(ctx) -> dict[str, Any]:
        raw_version_id = ctx.params["raw_version_id"]
        raw_scene = assets.load_scene(raw_version_id)
        provenance = raw_scene.manifest.provenance
        opts = AIPipelineOptions(
            up=ctx.params.get("up") or default_up_axis(provenance),
            forward=ctx.params.get("forward"),
            length_m=float(ctx.params.get("length_m", 1.0)),
            length_supplied=bool(ctx.params.get("length_supplied", False)),
            target_triangles=int(ctx.params.get("target_triangles", 24_000)),
            texture_resolution=int(ctx.params.get("texture_resolution", 1024)),
            lod=bool(ctx.params.get("lod", True)),
            tri_budget=settings.tri_budget_lod0,
        )
        ctx.annotate(
            raw_version_id=raw_version_id,
            preparation_options={
                "up": opts.up,
                "forward": opts.forward,
                "length_m": opts.length_m,
                "target_triangles": opts.target_triangles,
                "texture_resolution": opts.texture_resolution,
                "lod": opts.lod,
            },
        )
        report = run_ai_pipeline(
            processing,
            assets,
            raw_version_id,
            opts,
            progress=ctx.progress,
            check_cancel=ctx.check,
        )
        summary = {
            "ok": report["ok"],
            "raw_version_id": report["raw_version_id"],
            "cleaned_version_id": report["cleaned_version_id"],
            "final_version_id": report["final_version_id"],
            "validation": report["validation"],
            "needs_human": report["needs_human"],
            "steps": report["steps"],
        }
        ctx.annotate(auto_pipeline=summary)
        if not report["ok"]:
            failed = next((step for step in report["steps"] if step["status"] == "FAIL"), None)
            step_name = failed["step"] if failed else "an unknown step"
            raise StudioError(
                f"Automatic mesh preparation stopped at {step_name}.",
                recommended_action=(
                    "The raw reconstruction is preserved. Review the failed step and its error details, "
                    "adjust the settings if needed, and retry from the raw version."
                ),
                details={"pipeline": report},
            )
        status = report.get("validation") or {}
        ctx.progress(0.99, f"Preparation complete · validation: {status.get('status', 'NEEDS_REVIEW')}")
        return report

    return run


def _export_handler(exports: ExportService):
    def run(ctx) -> dict[str, Any]:
        out = []
        fmts = ctx.params.get("formats") or ["glb"]
        for i, f in enumerate(fmts):
            ctx.check()
            ctx.progress(i / len(fmts), f"Exporting {f}")
            rec = exports.export(ctx.params["version_id"], f)
            out.append(
                {"export_id": rec["export_id"], "format": f, "status": rec["status"], "size_bytes": rec["size_bytes"]}
            )
        if any(o["status"] != "COMPLETED" for o in out):
            from aro_studio.core.errors import StudioError

            raise StudioError(
                "One or more exports failed verification.",
                recommended_action="Open the export report for the failing check.",
                details={"exports": out},
            )
        return {"exports": out}

    return run


def _cleanup_handler(layout: StorageLayout, db: Database):
    def run(ctx) -> dict[str, Any]:
        import shutil

        n = layout.clean_tmp()
        freed = 0
        if ctx.params.get("purge_cache"):
            cache = layout.root / "cache"
            freed = layout.dir_size(cache) if cache.exists() else 0
            shutil.rmtree(cache, ignore_errors=True)  # preview GLBs are regenerated on demand; versions are untouched
        return {"temp_entries_removed": n, "cache_bytes_freed": freed}

    return run


_ = OPERATIONS
