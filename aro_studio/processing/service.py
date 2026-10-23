"""Processing operations on asset versions. Each operation produces a NEW immutable version (spec §12, §45)."""

from __future__ import annotations

from typing import Any

from aro_studio.animation.rig import build_rig
from aro_studio.assets.service import AssetService
from aro_studio.collision.generate import generate_collision
from aro_studio.config import Settings
from aro_studio.core.enums import AssetStatus, Stage
from aro_studio.core.errors import InvalidInputError, StudioError
from aro_studio.geometry import pipeline as gp
from aro_studio.jobs.queue import JobContext
from aro_studio.lod.generator import LodConfig, generate_lods
from aro_studio.materials.library import REFERENCE_MATERIALS, assign_material, upsert_material
from aro_studio.scene.model import MaterialDef
from aro_studio.scene.store import Scene
from aro_studio.textures.pipeline import bake_scene_textures, compress_scene_textures, resize_scene_textures
from aro_studio.validation.engine import ValidationConfig
from aro_studio.validation.service import ValidationService
from aro_studio.vehicles.assemble import configure_vehicle

# default material by vehicle component role (starting point the user can override)
ROLE_MATERIAL = {
    "chassis": "chassis_steel",
    "cabin": "body_paint",
    "body": "body_paint",
    "bumper": "plastic",
    "grille": "plastic",
    "door": "body_paint",
    "window": "glass",
    "mirror": "plastic",
    "headlight": "headlight",
    "taillight": "taillight",
    "exhaust": "chrome",
    "axle": "chassis_steel",
    "wheel": "rim_steel",
    "tire": "rubber",
    "attachment": "chassis_steel",
    "wiper": "plastic",
    "interior": "interior",
}

OPERATIONS = ["geometry", "materials", "textures", "vehicle", "collision", "lod", "rig", "finalize", "validate"]


class ProcessingService:
    def __init__(self, settings: Settings, assets: AssetService, validation: ValidationService):
        self.s, self.assets, self.validation = settings, assets, validation

    # -- entry used by the job handler ----------------------------------------------------------
    def handle(self, ctx: JobContext) -> dict[str, Any]:
        p = ctx.params
        op = p.get("operation")
        if op not in OPERATIONS:
            raise InvalidInputError(
                f"Unknown processing operation '{op}'.", recommended_action=f"Use one of {OPERATIONS}."
            )
        ctx.annotate(operation=op, parent_version_id=p.get("version_id"))
        ctx.progress(0.05, f"Loading version for {op}")
        return self.run(op, p["version_id"], p.get("params") or {}, ctx=ctx)

    def run(self, op: str, version_id: str, params: dict[str, Any], *, ctx: JobContext | None = None) -> dict[str, Any]:
        parent = self.assets.get_version(version_id)
        asset = self.assets.get_asset(parent["asset_id"])
        if op == "validate":
            return self.validation.validate_version(version_id, ValidationConfig(**(params.get("config") or {})))
        scene = self.assets.load_scene(version_id)
        if ctx:
            ctx.check()
            ctx.progress(0.2, f"Running {op}")
        self._status(asset["asset_id"], AssetStatus.PROCESSING)
        try:
            new, report, stage, desc = getattr(self, f"_op_{op}")(scene, asset, params, ctx)
            new.reports[op] = report
            if ctx:
                ctx.check()
                ctx.progress(0.85, "Saving new version")
            v = self.assets.add_version(
                asset["asset_id"], new, stage=stage, operation=op, description=desc, parent_version_id=version_id
            )
        except StudioError:
            self._status(asset["asset_id"], AssetStatus.FAILED)
            raise
        self._status(asset["asset_id"], AssetStatus.DRAFT)
        return {
            "version_id": v["version_id"],
            "label": v["label"],
            "stage": v["stage"],
            "triangles": v["triangle_count"],
            "report": _brief(report),
        }

    def _status(self, asset_id: str, status: AssetStatus) -> None:
        try:
            self.assets.set_status(asset_id, status)
        except StudioError:
            pass

    # -- operations: (scene, asset, params, ctx) -> (new_scene, report, stage, description) ------
    def _op_geometry(self, scene: Scene, asset: dict, params: dict, ctx: JobContext | None):
        steps = params.get("steps") or (
            gp.STANDARD_CLEANUP if params.get("preset", "standard_cleanup") == "standard_cleanup" else None
        )
        if not steps:
            raise InvalidInputError("Provide 'steps' or preset 'standard_cleanup'.")
        new, rep = gp.run_steps(
            scene,
            steps,
            category=asset["category"],
            tri_budget=self.s.tri_budget_lod0,
            cancel=ctx.cancel if ctx else None,
            progress=(lambda f, m: ctx.progress(0.2 + 0.6 * f, m)) if ctx else None,
        )
        stage = Stage.OPTIMIZED if any(s.get("op") == "decimate" for s in steps) else Stage.PROCESSED
        return new, rep, stage, "Geometry: " + ", ".join(s["op"] for s in steps)

    def _op_materials(self, scene: Scene, asset: dict, params: dict, ctx):
        new = scene.copy()
        n_def = 0
        if params.get("apply_vehicle_palette"):
            for m in REFERENCE_MATERIALS:
                upsert_material(new, m.model_copy(deep=True))
            for p in new.manifest.parts:
                mat = ROLE_MATERIAL.get(p.component)
                if mat and (params.get("overwrite", False) or not p.material or p.material == "raw_surface"):
                    assign_material(new, p.name, mat)
                    n_def += 1
        for md in params.get("materials", []):
            upsert_material(new, MaterialDef.model_validate(md))
        for part, mat in (params.get("assignments") or {}).items():
            assign_material(new, part, mat)
        used = {p.material for p in new.manifest.parts} | {p.material for lod in new.manifest.lods for p in lod.parts}
        if params.get("prune_unused", True):
            new.manifest.materials = [m for m in new.manifest.materials if m.name in used]
        return (
            new,
            {"materials": [m.name for m in new.manifest.materials], "role_defaults_applied": n_def},
            Stage.PROCESSED,
            "Materials configured",
        )

    def _op_textures(self, scene: Scene, asset: dict, params: dict, ctx):
        action = params.get("action", "bake")
        new = scene.copy()
        if action == "bake":
            source = None
            if params.get("source_version_id"):
                source = self.assets.load_scene(params["source_version_id"])
            rep = bake_scene_textures(
                new,
                resolution=int(params.get("resolution", 1024)),
                parts=params.get("parts"),
                source=source,
                max_faces=int(params.get("max_faces", 25000)),
            )
            return new, rep, Stage.PROCESSED, f"Textures baked at {params.get('resolution', 1024)}px"
        if action == "resize":
            return (
                new,
                {"resized": resize_scene_textures(new, int(params["resolution"]))},
                Stage.OPTIMIZED,
                f"Textures resized to ≤{params['resolution']}px",
            )
        if action == "compress":
            return (
                new,
                {
                    "compressed": compress_scene_textures(
                        new, params.get("format", "jpeg"), int(params.get("quality", 88))
                    )
                },
                Stage.OPTIMIZED,
                "Textures compressed",
            )
        raise InvalidInputError("textures.action must be bake, resize or compress.")

    def _op_vehicle(self, scene: Scene, asset: dict, params: dict, ctx):
        new = scene.copy()
        rep = configure_vehicle(new, params.get("spec"), params.get("component_map"))
        return new, rep, Stage.PROCESSED, "Vehicle configured"

    def _op_collision(self, scene: Scene, asset: dict, params: dict, ctx):
        new = scene.copy()
        kind = params.get("kind") or ("vehicle" if new.manifest.vehicle else "convex_hull")
        rep = generate_collision(
            new,
            kind=kind,
            parts=params.get("parts"),
            max_triangles=int(params.get("max_triangles", 255)),
            wheel_colliders=bool(params.get("wheel_colliders", False)),
        )
        return new, rep, Stage.OPTIMIZED, f"Collision generated ({kind})"

    def _op_lod(self, scene: Scene, asset: dict, params: dict, ctx):
        new = scene.copy()
        cfg = LodConfig.model_validate(params["config"]) if params.get("config") else None
        res = generate_lods(new, cfg)
        if new.manifest.rig:
            build_rig(new)
        return (
            new,
            {"levels": [r.to_dict() for r in res]},
            Stage.OPTIMIZED,
            "LODs: " + ", ".join(f"LOD{r.level}={r.triangles:,}" for r in res),
        )

    def _op_rig(self, scene: Scene, asset: dict, params: dict, ctx):
        new = scene.copy()
        rig = build_rig(new)
        return new, {"nodes": len(rig.nodes)}, Stage.PROCESSED, "Rig/pivots prepared"

    def _op_finalize(self, scene: Scene, asset: dict, params: dict, ctx):
        return scene.copy(), {"note": params.get("note", "")}, Stage.FINAL, "Finalised (no geometry change)"


def _brief(rep: dict) -> dict:
    """A compact report for the job result (full report is stored with the version)."""
    out = {k: v for k, v in rep.items() if k not in ("before", "after", "steps")} | (
        {"steps": [s["op"] for s in rep["steps"]]} if "steps" in rep else {}
    )
    # what the shape-correcting steps actually did is part of the answer (yaw applied or skipped and why, stretch factors)
    details = {
        s["op"]: {k: v for k, v in s.items() if k != "params"}
        for s in rep.get("steps", [])
        if s["op"] in ("align_yaw", "fit_dimensions", "smooth")
    }
    return out | ({"step_details": details} if details else {})
