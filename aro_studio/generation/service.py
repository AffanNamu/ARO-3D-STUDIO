"""Image-to-3D generation as a job (spec §10-12, §31-32, §44).

Hard rules enforced here:
  * No placeholder geometry. If the engine cannot run, the job ends MODEL_ERROR and NO asset version is created.
  * Success is only recorded after the engine returned a non-empty finite mesh from a real inference call.
  * The raw engine artefact is saved untouched; everything downstream derives new versions from it.
"""

from __future__ import annotations

import json
import time
from typing import Any

import numpy as np

from aro_studio.assets.service import AssetService
from aro_studio.assets.taxonomy import get_category
from aro_studio.config import Settings
from aro_studio.core.enums import AssetStatus, JobState, Stage
from aro_studio.core.errors import (
    EngineUnavailableError,
    InvalidInputError,
    ModelError,
    ResourceLimitError,
    StudioError,
    explain_exception,
)
from aro_studio.core.hashing import generation_cache_key, sha256_file
from aro_studio.core.ids import new_id, require_id
from aro_studio.db.database import Database, dumps, loads
from aro_studio.engines.base import GenerationRequest
from aro_studio.engines.manager import ModelManager, resolve_device
from aro_studio.engines.registry import EngineRegistry, license_gate
from aro_studio.geometry.inspect import inspect_mesh
from aro_studio.imaging.preprocess import PreprocessOptions, preprocess
from aro_studio.jobs.queue import JobContext
from aro_studio.observability.metrics import Metrics
from aro_studio.observability.resources import snapshot
from aro_studio.projects.sources import SourceService
from aro_studio.scene.factory import scene_from_mesh
from aro_studio.scene.model import Provenance
from aro_studio.storage.layout import StorageLayout


class GenerationService:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        layout: StorageLayout,
        assets: AssetService,
        sources: SourceService,
        registry: EngineRegistry,
        models: ModelManager,
        metrics: Metrics | None = None,
    ):
        self.s, self.db, self.layout, self.assets, self.sources = settings, db, layout, assets, sources
        self.registry, self.models, self.metrics = registry, models, metrics or Metrics()

    # -- discovery ----------------------------------------------------------------------------
    def engine_status(self) -> list[dict]:
        device = resolve_device(self.s.device)
        out = []
        for e in self.registry.all():
            av = e.availability(device)
            lic = e.info.license
            licensed = lic.status == "verified" or e.info.id.lower() in self.s.verified_licenses
            out.append(
                {
                    "info": e.info.to_dict(),
                    "device": device,
                    "availability": av.to_dict(),
                    "loaded": e.is_loaded,
                    "license_verified_by_deployer": licensed,
                    "runnable": av.ok and licensed,
                    "presets": e.presets(),
                    "estimate_default": e.estimate_resources({}, device).__dict__,
                }
            )
        return out

    # -- cache --------------------------------------------------------------------------------
    def find_cached(self, cache_key: str) -> dict | None:
        for r in self.db.query(
            "SELECT * FROM generations WHERE cache_key=? AND status='COMPLETED' AND version_id IS NOT NULL AND reused_from IS NULL ORDER BY created_at DESC",
            (cache_key,),
        ):
            if self.db.query_one("SELECT 1 FROM asset_versions WHERE version_id=?", (r["version_id"],)):
                return r
        return None

    def cache_stats(self) -> dict:
        r = (
            self.db.query_one(
                "SELECT COUNT(*) n, COALESCE(SUM(reused_from IS NOT NULL),0) hits FROM generations WHERE status='COMPLETED'"
            )
            or {}
        )
        return {"completed": r.get("n", 0), "cache_hits": r.get("hits", 0)}

    # -- preflight ----------------------------------------------------------------------------
    def preflight(self, engine, settings: dict[str, Any], device: str) -> dict:
        est = engine.estimate_resources(settings, device)
        res = snapshot(self.s.data_dir)
        info: dict[str, Any] = {
            "estimate": est.__dict__,
            "gpu": res.gpu.__dict__,
            "ram_available_mb": res.ram_available_mb,
            "disk_free_mb": res.disk_free_mb,
        }
        if device.startswith("cuda"):
            if res.gpu.available and res.gpu.free_mb is not None and est.vram_mb and res.gpu.free_mb < est.vram_mb:
                raise ResourceLimitError(
                    f"The GPU has {res.gpu.free_mb} MB free but the selected configuration needs about {est.vram_mb} MB.",
                    recommended_action="Choose the LOW_RESOURCE preset, wait for the GPU to free up, or run on CPU.",
                    details=info,
                )
        elif est.ram_mb and res.ram_available_mb < est.ram_mb:
            raise ResourceLimitError(
                f"Only {res.ram_available_mb} MB of RAM is available; CPU inference needs about {est.ram_mb} MB.",
                recommended_action="Free memory, use a smaller preset, or run on a GPU.",
                details=info,
            )
        if res.disk_free_mb < self.s.min_free_disk_mb:
            raise ResourceLimitError(
                f"Only {res.disk_free_mb} MB of disk is free.",
                recommended_action="Purge cache/exports in Settings.",
                details=info,
            )
        return info

    # -- job handler --------------------------------------------------------------------------
    def handle(self, ctx: JobContext) -> dict[str, Any]:
        p = ctx.params
        project_id, asset_id = require_id(p["project_id"], "project"), require_id(p["asset_id"], "asset")
        asset = self.assets.get_asset(asset_id)
        if asset["project_id"] != project_id:
            raise InvalidInputError("Asset does not belong to this project.")
        engine_id = p.get("engine_id") or self.s.default_engine
        gid = new_id("generation")
        created = time.time()
        self.db.execute(
            "INSERT INTO generations(generation_id,project_id,asset_id,job_id,engine_id,model_version,input_image_sha256,settings,cache_key,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                gid,
                project_id,
                asset_id,
                ctx.job_id,
                engine_id,
                "",
                p.get("image_sha256", ""),
                "{}",
                "",
                JobState.INITIALIZING.value,
                created,
            ),
        )
        ctx.annotate(generation_id=gid, engine_id=engine_id, image_sha256=p.get("image_sha256"))
        prev_status = asset["status"]
        self._asset_status(asset_id, AssetStatus.GENERATING)
        try:
            out = self._run(ctx, gid, project_id, asset, engine_id)
            self._asset_status(asset_id, AssetStatus.DRAFT)
            return out
        except BaseException as e:
            ex = explain_exception(e)
            self.db.execute(
                "UPDATE generations SET status=?, error=? WHERE generation_id=?",
                (
                    ex.job_state,
                    dumps({"code": ex.code, "message": ex.message, "recommended_action": ex.recommended_action}),
                    gid,
                ),
            )
            self._asset_status(
                asset_id,
                AssetStatus.FAILED if prev_status != AssetStatus.PRODUCTION_READY.value else AssetStatus.PROCESSING,
            )
            raise

    def _asset_status(self, asset_id: str, status: AssetStatus) -> None:
        try:
            self.assets.set_status(asset_id, status)
        except StudioError:
            pass  # status is advisory; never mask the real outcome

    def _run(self, ctx: JobContext, gid: str, project_id: str, asset: dict, engine_id: str) -> dict[str, Any]:
        p = ctx.params
        ctx.set_state(JobState.INITIALIZING, 0.02, "Resolving engine")
        engine = self.registry.get(engine_id)
        device = resolve_device(p.get("device") or self.s.device)
        # recorded BEFORE any gate can fail so a failed job always carries its model information (spec §44)
        ctx.annotate(
            model={
                "id": engine.info.id,
                "name": engine.info.name,
                "version": engine.info.version,
                "revision": engine.info.revision,
                "license": engine.info.license.spdx,
                "license_status": engine.info.license.status,
            },
            device=device,
        )
        license_gate(engine, self.s.verified_licenses)
        av = engine.availability(device)
        if not av.ok:
            raise EngineUnavailableError(
                f"{engine.info.name} cannot run in this environment: " + " ".join(av.reasons),
                recommended_action=" ".join(av.activation) or "See docs/models/model-requirements.md.",
                details=av.to_dict(),
            )
        settings = engine.normalize_settings(
            {**(p.get("settings") or {}), **({"preset": p["preset"]} if p.get("preset") else {})}
        )
        pre_opts = PreprocessOptions(**(p.get("preprocess") or {"foreground_ratio": settings["foreground_ratio"]}))
        image_sha = require_sha(p.get("image_sha256"))
        cache_settings = {"engine": settings, "preprocess": pre_opts.as_settings()}
        key = generation_cache_key(image_sha, engine.info.id, engine.info.version, cache_settings)
        self.db.execute(
            "UPDATE generations SET model_version=?, settings=?, cache_key=?, device=? WHERE generation_id=?",
            (engine.info.version, dumps(cache_settings), key, device, gid),
        )
        ctx.annotate(settings=cache_settings, cache_key=key)

        # -- cache -----------------------------------------------------------------------------
        if p.get("use_cache", True) and not p.get("force"):
            hit = self.find_cached(key)
            if hit:
                ctx.set_state(JobState.POSTPROCESSING, 0.8, "Reusing cached reconstruction (no GPU time spent)")
                scene = self.assets.load_scene(hit["version_id"])
                scene.manifest.name = asset["name"]
                scene.manifest.provenance = scene.manifest.provenance.model_copy(
                    update={
                        "generation_id": gid,
                        "note": f"Reused from generation {hit['generation_id']} (cache key match)",
                    }
                )
                v = self.assets.add_version(
                    asset["asset_id"],
                    scene,
                    stage=Stage.RAW,
                    operation="generation.cached",
                    description=f"Reused {hit['generation_id']}",
                )
                self.db.execute(
                    "UPDATE generations SET status='COMPLETED', version_id=?, reused_from=?, output_format=?, output_sha256=? WHERE generation_id=?",
                    (v["version_id"], hit["generation_id"], hit["output_format"], hit["output_sha256"], gid),
                )
                self.metrics.incr("generation.cache_hits")
                return {
                    "generation_id": gid,
                    "version_id": v["version_id"],
                    "reused_from": hit["generation_id"],
                    "cache_key": key,
                    "model_ran": False,
                }

        info = self.preflight(engine, settings, device)
        ctx.annotate(resources_preflight=info)
        ctx.check()

        # -- preprocessing ---------------------------------------------------------------------
        ctx.set_state(JobState.PREPROCESSING, 0.1, "Validating and preparing the image")
        src_img = self.sources.open(project_id, image_sha)
        pre = preprocess(src_img, pre_opts)
        gdir = self.layout.generation_dir(project_id, gid)
        gdir.mkdir(parents=True, exist_ok=True)
        pre.image.save(gdir / "model_input.png")
        (gdir / "preprocess.json").write_text(
            json.dumps({"steps": pre.steps, "options": pre_opts.as_settings(), "bbox": pre.foreground_bbox}, indent=2)
        )
        ctx.check()

        # -- generation ------------------------------------------------------------------------
        ctx.set_state(JobState.GENERATING, 0.2, f"Loading {engine.info.name} on {device} (first use loads the weights)")
        with self.models.acquire(engine.info.id, device) as (eng, load_s):
            ctx.annotate(model_load_time_s=round(load_s, 3))
            ctx.progress(0.35, "Running reconstruction")
            out = eng.generate(
                GenerationRequest(
                    image=pre.image,
                    settings=settings,
                    workdir=gdir,
                    cancel=ctx.cancel,
                    progress=lambda f, m: ctx.progress(0.35 + 0.4 * f, m),
                )
            )
        self._unload_if_low(device)
        ctx.check()

        # -- post-processing: preserve raw ----------------------------------------------------
        ctx.set_state(JobState.POSTPROCESSING, 0.8, "Saving raw asset")
        mesh = out.mesh
        if len(mesh.faces) == 0 or not np.isfinite(np.asarray(mesh.vertices)).all():
            raise ModelError(
                "The engine returned empty or non-finite geometry.",
                recommended_action="Try another input image or preset.",
            )
        out_hash = sha256_file(out.raw_file)
        prov = Provenance(
            source="ai_reconstruction",
            engine_id=engine.info.id,
            model_version=engine.info.version,
            generation_id=gid,
            input_image_sha256=image_sha,
            note=f"{engine.info.name} single-image reconstruction on {out.device}; raw native coordinate frame.",
        )
        scene = scene_from_mesh(mesh, asset["name"], asset["category"], prov)
        scene.reports["generation"] = {
            "generation_id": gid,
            "engine": engine.info.to_dict(),
            "settings": cache_settings,
            "device": out.device,
            "model_load_time_s": load_s,
            "execution_time_s": out.execution_time_s,
            "output_sha256": out_hash,
            "preprocess_steps": pre.steps,
            "engine_details": out.details,
        }
        v = self.assets.add_version(
            asset["asset_id"],
            scene,
            stage=Stage.RAW,
            operation="generation",
            description=f"{engine.info.name} / {settings.get('preset', '')} / {out.device}",
        )

        # -- validating -----------------------------------------------------------------------
        ctx.set_state(JobState.VALIDATING, 0.92, "Sanity-checking the reconstruction")
        rep = inspect_mesh(mesh, category_group=get_category(asset["category"]).group, check_intersections=False)
        summary = {
            "vertices": rep.vertex_count,
            "faces": rep.face_count,
            "watertight": rep.is_watertight,
            "components": rep.component_count,
            "issues": [{"id": i.id, "severity": i.severity, "message": i.message} for i in rep.issues],
        }
        (gdir / "generation.json").write_text(
            json.dumps(
                {
                    "generation_id": gid,
                    "cache_key": key,
                    "output_sha256": out_hash,
                    "summary": summary,
                    **scene.reports["generation"],
                },
                indent=2,
                default=str,
            )
        )
        self.db.execute(
            "UPDATE generations SET status='COMPLETED', model_load_time_s=?, execution_time_s=?, output_format=?, output_sha256=?, output_path=?, version_id=?, input_path=? WHERE generation_id=?",
            (
                load_s,
                out.execution_time_s,
                out.output_format,
                out_hash,
                str((gdir / out.raw_file.name).relative_to(self.layout.root)),
                v["version_id"],
                str((gdir / "model_input.png").relative_to(self.layout.root)),
                gid,
            ),
        )
        self.metrics.incr("generation.completed")
        self.metrics.observe("generation.inference_s", out.execution_time_s)
        return {
            "generation_id": gid,
            "version_id": v["version_id"],
            "cache_key": key,
            "model_ran": True,
            "device": out.device,
            "execution_time_s": out.execution_time_s,
            "model_load_time_s": load_s,
            "output_sha256": out_hash,
            "mesh": summary,
        }

    def _unload_if_low(self, device: str) -> None:
        """Free the model right away when the GPU is nearly full (shared/free GPUs)."""
        if device.startswith("cuda"):
            res = snapshot(self.s.data_dir)
            if res.gpu.available and res.gpu.free_mb is not None and res.gpu.free_mb < 1500:
                self.models.unload()

    def get_generation(self, generation_id: str) -> dict:
        r = self.db.query_one(
            "SELECT * FROM generations WHERE generation_id=?", (require_id(generation_id, "generation"),)
        )
        if not r:
            from aro_studio.core.errors import NotFoundError

            raise NotFoundError("Generation not found.")
        r["settings"], r["error"] = loads(r["settings"], {}), loads(r["error"])
        return r

    def list_generations(
        self, *, project_id: str | None = None, asset_id: str | None = None, limit: int = 100
    ) -> list[dict]:
        sql, p = "SELECT generation_id FROM generations WHERE 1=1", []
        if project_id:
            sql += " AND project_id=?"
            p.append(project_id)  # noqa: E702
        if asset_id:
            sql += " AND asset_id=?"
            p.append(asset_id)  # noqa: E702
        return [
            self.get_generation(r["generation_id"])
            for r in self.db.query(sql + " ORDER BY created_at DESC LIMIT ?", (*p, limit))
        ]


def require_sha(v: Any) -> str:
    if not isinstance(v, str) or len(v) != 64 or any(c not in "0123456789abcdef" for c in v):
        raise InvalidInputError("image_sha256 must be the 64-hex id of an uploaded source image.")
    return v
