"""Automatic post-reconstruction pipeline for a single-mesh, vertex-coloured raw asset (e.g. TripoSR output).

Every step is an ordinary processing operation that creates a NEW immutable version; the raw reconstruction is never
touched. Decisions a machine cannot make are NOT guessed silently: they are recorded in ``needs_human`` (e.g. which end of
the vehicle is the front, wheel/axle positions). Nothing here fabricates a vehicle specification.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from aro_studio.core.errors import StudioError
from aro_studio.processing.service import ProcessingService


@dataclass
class AIPipelineOptions:
    up: str | None = None  # source axis that is "up"; None → engine hint (+Z for TripoSR native)
    forward: str | None = (
        None  # source axis that is the vehicle's front; None → longest horizontal axis, sign UNCONFIRMED
    )
    length_m: float = 6.5  # real-world length along the forward axis
    target_triangles: int = 24_000  # decimation target (UV unwrapping is limited to 25,000 triangles per atlas)
    texture_resolution: int = 1024
    fill_holes_edges: int = 200
    vehicle_spec: dict | None = None  # artist-supplied VehicleSpec JSON (never generated automatically)
    component_map: dict | None = None
    lod: bool = True
    tri_budget: int | None = None
    validation_intersections: bool = False


@dataclass
class StepRecord:
    step: str
    status: str  # PASS | FAIL
    seconds: float
    version_id: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


def choose_axes(extents: np.ndarray, opts: AIPipelineOptions) -> tuple[str, str, list[str]]:
    """Return (up, forward, needs_human). ``forward`` sign is a guess unless the caller supplied it."""
    notes: list[str] = []
    up = opts.up or "+Z"
    if opts.up is None:
        notes.append(
            "up axis taken from the engine hint (TripoSR native +Z, inferred from upstream source; confirm visually)"
        )
    if opts.forward:
        return up, opts.forward, notes
    names = "XYZ"
    up_i = names.index(up[1])
    horizontal = [i for i in range(3) if i != up_i]
    fwd_i = max(horizontal, key=lambda i: extents[i])
    fwd = "+" + names[fwd_i]
    notes.append(
        f"forward axis guessed as the longest horizontal extent ({fwd}); WHICH END IS THE FRONT cannot be determined automatically - review the 6-view renders and re-run with --forward if reversed"
    )
    return up, fwd, notes


def run_ai_pipeline(
    processing: ProcessingService, assets, raw_version_id: str, opts: AIPipelineOptions | None = None
) -> dict[str, Any]:
    """Run the full chain and return a structured report. Stops at the first failing step (recorded, not hidden)."""
    opts = opts or AIPipelineOptions()
    raw_scene = assets.load_scene(raw_version_id)
    ext = np.asarray(raw_scene.combined().extents)
    up, fwd, needs_human = choose_axes(ext, opts)
    steps: list[StepRecord] = []
    cur = raw_version_id

    def run(name: str, op: str, params: dict[str, Any]) -> bool:
        nonlocal cur
        t = time.perf_counter()
        try:
            r = processing.run(op, cur, params)
        except StudioError as e:
            steps.append(StepRecord(name, "FAIL", time.perf_counter() - t, None, {"error": e.to_dict()}))
            return False
        except Exception as e:  # noqa: BLE001
            steps.append(StepRecord(name, "FAIL", time.perf_counter() - t, None, {"error": f"{type(e).__name__}: {e}"}))
            return False
        vid = r.get("version_id") if op != "validate" else None
        if vid and op != "validate":
            cur = vid
        steps.append(StepRecord(name, "PASS", time.perf_counter() - t, vid or cur, r))
        return True

    ok = run(
        "geometry: orient + scale + pivot + cleanup + fill holes",
        "geometry",
        {
            "steps": [
                {"op": "orient", "params": {"up": up, "forward": fwd}},
                {"op": "scale", "params": {"length_m": opts.length_m, "axis": "Z"}},
                {"op": "set_pivot", "params": {"mode": "ground_center"}},
                {"op": "remove_invalid"},
                {"op": "merge_vertices"},
                {"op": "remove_degenerate"},
                {"op": "remove_duplicate_faces"},
                {"op": "remove_small_components", "params": {"min_face_ratio": 0.01}},
                {"op": "fix_normals"},
                {"op": "fill_holes", "params": {"max_hole_edges": opts.fill_holes_edges}},
            ]
        },
    )
    cleaned = cur
    ok = ok and run(
        "geometry: decimate for texturing",
        "geometry",
        {
            "steps": [
                {"op": "decimate", "params": {"target_faces": opts.target_triangles}},
                # decimation moves silhouette vertices slightly: re-ground so the wheels/base sit exactly on Y=0
                {"op": "set_pivot", "params": {"mode": "ground_center"}},
            ]
        },
    )
    if ok and opts.target_triangles > 25_000:
        needs_human.append("target_triangles exceeds the 25,000-triangle UV unwrap limit; texture baking will fail")
    ok = ok and run(
        "textures: unwrap + bake colour from the RAW mesh",
        "textures",
        {
            "action": "bake",
            "resolution": opts.texture_resolution,
            "source_version_id": raw_version_id,
            "max_faces": 25_000,
        },
    )
    if opts.vehicle_spec is not None:
        ok = ok and run(
            "vehicle: artist-supplied specification",
            "vehicle",
            {"spec": opts.vehicle_spec, "component_map": opts.component_map},
        )
        ok = ok and run("rig: pivots and hierarchy", "rig", {})
    else:
        needs_human.append(
            "no vehicle specification supplied: wheel/axle/pivot positions and component roles are artist work (automatic part detection is not implemented); validation WILL report NEEDS_REVIEW for a vehicle category"
        )
    ok = ok and run("collision", "collision", {})
    if opts.lod:
        ok = ok and run("LOD generation", "lod", {})
    validation = None
    if ok:
        t = time.perf_counter()
        try:
            from aro_studio.validation.engine import ValidationConfig

            validation = processing.validation.validate_version(
                cur,
                ValidationConfig(
                    check_intersections=opts.validation_intersections,
                    **({"tri_budget_lod0": opts.tri_budget} if opts.tri_budget else {}),
                ),
            )
            steps.append(
                StepRecord(
                    "validation",
                    "PASS",
                    time.perf_counter() - t,
                    cur,
                    {
                        "status": validation["status"],
                        "overall": validation["overall"],
                        "critical_failures": validation["critical_failures"],
                        "major_failures": validation["major_failures"],
                    },
                )
            )
        except Exception as e:  # noqa: BLE001
            steps.append(
                StepRecord("validation", "FAIL", time.perf_counter() - t, cur, {"error": f"{type(e).__name__}: {e}"})
            )
            ok = False
    final_version = None
    if ok:
        ok = run("finalize", "finalize", {"note": "ai pipeline"})
        final_version = cur
    return {
        "ok": ok,
        "source_axes": {"up": up, "forward": fwd},
        "needs_human": needs_human,
        "raw_version_id": raw_version_id,
        "cleaned_version_id": cleaned,
        "final_version_id": final_version,
        "validation": validation,
        "steps": [s.__dict__ for s in steps],
        "options": {k: v for k, v in opts.__dict__.items() if k != "vehicle_spec"},
    }
