"""Automatic post-reconstruction pipeline for a single-mesh, vertex-coloured raw asset (e.g. TripoSR output).

Every step is an ordinary processing operation that creates a NEW immutable version; the raw reconstruction is never
touched. Decisions a machine cannot make are NOT guessed silently: they are recorded in ``needs_human`` (e.g. which end of
the vehicle is the front, wheel/axle positions). Nothing here fabricates a vehicle specification.
"""

from __future__ import annotations

import time
from collections.abc import Callable
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
    length_supplied: bool = False  # True only when a person gave the real size; otherwise the size is an ASSUMPTION
    width_m: float | None = (
        None  # real-world width / height, ONLY when a person supplies them (never guessed): the model's depth is
    )
    height_m: float | None = (
        None  # an estimate from one view, so these stretch the reconstruction to the stated proportions
    )
    auto_align_yaw: bool = (
        True  # square the footprint up with the axes (single-view output is often yawed); skipped if forward is given
    )
    smooth_iterations: int = (
        40  # Taubin smoothing of the full-resolution mesh before decimation (0 = off); deviation is reported
    )
    target_triangles: int = 24_000  # decimation target (UV unwrapping is limited to 25,000 triangles per atlas)
    texture_resolution: int = 1024
    fill_holes_edges: int = 200
    vehicle_spec: dict | None = None  # artist-supplied VehicleSpec JSON (never generated automatically)
    component_map: dict | None = None
    lod: bool = True
    tri_budget: int | None = None
    validation_intersections: bool = False
    reference: Any = None  # PIL RGBA cut-out of the source image: geometry-only engines get their colour projected from it (never serialised)
    symmetric_projection: bool | None = None  # mirror the seen side onto the unseen one; None = yes for vehicles only


@dataclass
class StepRecord:
    step: str
    status: str  # PASS | FAIL
    seconds: float
    version_id: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


def _has_colours(assets, version_id: str) -> bool:
    from aro_studio.core.tm import has_vertex_colors

    scene = assets.load_scene(version_id)
    return any(has_vertex_colors(m) for m in scene.meshes.values())


def default_up_axis(provenance) -> str:
    """Native up axis of a raw mesh, from the engine's documented orientation hint (+Y for imported/glTF meshes)."""
    detected = getattr(provenance, "native_up", None)
    if detected:  # judged from the reference image at generation time (aro_studio.quality.fidelity.detect_up_axis)
        return str(detected)
    if (
        getattr(provenance, "source", None) == "ai_reconstruction"
        and getattr(provenance, "engine_id", None) == "triposr"
    ):
        return "+Z"
    return "+Y"


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
    processing: ProcessingService,
    assets,
    raw_version_id: str,
    opts: AIPipelineOptions | None = None,
    *,
    progress: Callable[[float, str], None] | None = None,
    check_cancel: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Run the full chain, report step progress, and stop at the first recorded failure."""
    opts = opts or AIPipelineOptions()
    if check_cancel:
        check_cancel()
    raw_scene = assets.load_scene(raw_version_id)
    ext = np.asarray(raw_scene.combined().extents)
    up, fwd, needs_human = choose_axes(ext, opts)
    from aro_studio.assets.taxonomy import get_category

    try:
        group = get_category(raw_scene.manifest.category).group
    except StudioError:
        group = "other"
    if not opts.length_supplied:
        needs_human.append(
            f"real-world size is not recoverable from a single image: the model was scaled to {opts.length_m:g} m along "
            "its forward axis as a PLACEHOLDER - enter the true length and re-run before using it for dimensions"
        )
    steps: list[StepRecord] = []
    cur = raw_version_id
    total_steps = 6 + int(opts.lod) + (2 if opts.vehicle_spec is not None else 0)
    completed_steps = 0

    def announce(message: str) -> None:
        if check_cancel:
            check_cancel()
        if progress:
            progress(min(0.97, 0.03 + 0.92 * completed_steps / total_steps), message)

    def advance(message: str) -> None:
        nonlocal completed_steps
        completed_steps += 1
        if progress:
            progress(min(0.98, 0.03 + 0.92 * completed_steps / total_steps), message)

    def run(name: str, op: str, params: dict[str, Any]) -> bool:
        nonlocal cur
        announce(name)
        t = time.perf_counter()
        try:
            r = processing.run(op, cur, params)
        except StudioError as e:
            steps.append(StepRecord(name, "FAIL", time.perf_counter() - t, None, {"error": e.to_dict()}))
            advance(f"{name} failed")
            return False
        except Exception as e:  # noqa: BLE001
            steps.append(StepRecord(name, "FAIL", time.perf_counter() - t, None, {"error": f"{type(e).__name__}: {e}"}))
            advance(f"{name} failed")
            return False
        vid = r.get("version_id") if op != "validate" else None
        if vid and op != "validate":
            cur = vid
        steps.append(StepRecord(name, "PASS", time.perf_counter() - t, vid or cur, r))
        advance(f"{name} complete")
        return True

    prep_steps: list[dict[str, Any]] = [{"op": "orient", "params": {"up": up, "forward": fwd}}]
    if opts.auto_align_yaw and not opts.forward:
        prep_steps.append({"op": "align_yaw"})
    prep_steps.append({"op": "scale", "params": {"length_m": opts.length_m, "axis": "Z"}})
    if opts.width_m is not None or opts.height_m is not None:
        prep_steps.append({"op": "fit_dimensions", "params": {"width_m": opts.width_m, "height_m": opts.height_m}})
    prep_steps += [
        {"op": "set_pivot", "params": {"mode": "ground_center"}},
        {"op": "remove_invalid"},
        {"op": "merge_vertices"},
        {"op": "remove_degenerate"},
        {"op": "remove_duplicate_faces"},
        {"op": "remove_small_components", "params": {"min_face_ratio": 0.01}},
        {"op": "fix_normals"},
        {"op": "fill_holes", "params": {"max_hole_edges": opts.fill_holes_edges}},
    ]
    if opts.smooth_iterations > 0:
        # low-pass the iso-surface noise at FULL resolution (before decimation, so facets are not baked in); the raw version is untouched
        prep_steps += [{"op": "smooth", "params": {"iterations": int(opts.smooth_iterations)}}]
    ok = run("geometry: orient + scale + pivot + cleanup + fill holes + smooth", "geometry", {"steps": prep_steps})
    if steps:
        details = ((steps[-1].detail.get("report") or {}).get("step_details")) or {}
        yaw = details.get("align_yaw")
        if yaw is not None:
            needs_human.append(
                f"footprint aligned to the axes by rotating {yaw['yaw_deg']:+.1f} deg about the up axis (long side = forward, footprint {yaw['footprint_long_m']:.3g} x {yaw['footprint_short_m']:.3g})"
                if yaw.get("aligned")
                else f"footprint NOT yaw-aligned: {yaw.get('reason', 'not applicable')}"
            )
        fit = details.get("fit_dimensions")
        if fit is not None:
            needs_human.append(
                "proportions were STRETCHED to the supplied width/height (distortion vs a uniform scale: "
                f"{fit['distortion_vs_uniform']}): this is not what the model predicted, and a stretch of the height changes wheel roundness"
            )
        elif opts.width_m is None and opts.height_m is None:
            needs_human.append(
                "width and height relative to the length are the model's estimate from ONE view and are often wrong (often too stubby): "
                "supply the real width/height to correct the proportions"
            )
    if ok and opts.reference is not None and not _has_colours(assets, cur):
        symmetric = (group == "vehicles") if opts.symmetric_projection is None else opts.symmetric_projection
        projected = run(
            "textures: project the reference image onto the geometry",
            "textures",
            {"action": "project_reference", "reference": opts.reference, "symmetric": symmetric},
        )
        if projected:
            rep_p = (steps[-1].detail.get("report") or {}).get("projected") or [{}]
            needs_human.append(
                "the engine returned geometry only: colour was PROJECTED from the reference photo "
                f"(seen {rep_p[0].get('seen_fraction', 0):.0%}, mirrored {rep_p[0].get('mirrored_fraction', 0):.0%}, "
                f"filled {rep_p[0].get('filled_fraction', 0):.0%}). Everything not seen is inferred; check the far side and the roof"
            )
        else:
            needs_human.append("projecting the reference colours failed (see the step detail): the mesh has no colour")
    cleaned = cur
    ok = ok and run(
        "geometry: decimate for texturing",
        "geometry",
        {
            "steps": [
                {"op": "decimate", "params": {"target_faces": opts.target_triangles, "stages": 5}},
                # quadric decimation can pinch a closed surface (edges shared by 3+ triangles): repair, close the specks, re-orient
                {"op": "remove_non_manifold"},
                {"op": "fill_holes", "params": {"max_hole_edges": 60}},
                {"op": "fix_normals"},
                # smoothing and decimation shift the surface a little: restore the exact requested length, then re-ground so the
                # wheels/base sit exactly on Y=0
                {"op": "scale", "params": {"length_m": opts.length_m, "axis": "Z"}},
                {"op": "set_pivot", "params": {"mode": "ground_center"}},
            ]
        },
    )
    if ok and opts.target_triangles > 25_000:
        needs_human.append("target_triangles exceeds the 25,000-triangle UV unwrap limit; texture baking will fail")
    if ok:
        textured = run(
            "textures: unwrap + bake colour from the cleaned full-resolution mesh (which carries the raw vertex colours)",
            "textures",
            {
                "action": "bake",
                "resolution": opts.texture_resolution,
                "source_version_id": cleaned,
                "max_faces": 25_000,
            },
        )
        ok = textured
        baked = (steps[-1].detail.get("report") or {}) if textured else {}
        if textured and not baked.get("groups"):
            # the step "succeeded" but baked nothing (e.g. the mesh had lost its colours): never present that as a texture
            reasons = (
                "; ".join(str(x.get("reason")) for x in baked.get("skipped", [])) or "no texture group was produced"
            )
            steps[-1].status = "SKIPPED"
            needs_human.append(f"texture baking produced NO texture ({reasons}): the prepared mesh has no baked colour")
        if not textured and opts.target_triangles <= 25_000:
            ok = True
            # Texturing is optional: keep going with untextured geometry rather than discarding a usable mesh.
            # (A target above the unwrap limit is a configuration error and still stops the run.)
            steps[-1].status = "SKIPPED"
            needs_human.append(
                "texture baking failed (see the step detail): the prepared mesh has NO baked colour texture. "
                "Geometry, collision, LODs and validation continued without it"
            )
    if opts.vehicle_spec is not None:
        ok = ok and run(
            "vehicle: artist-supplied specification",
            "vehicle",
            {"spec": opts.vehicle_spec, "component_map": opts.component_map},
        )
        ok = ok and run("rig: pivots and hierarchy", "rig", {})
    else:
        if group == "vehicles":
            needs_human.append(
                "no vehicle specification supplied: wheel/axle/pivot positions and component roles are artist work (automatic part detection is not implemented); validation WILL report NEEDS_REVIEW for a vehicle category"
            )
        else:
            needs_human.append(
                "the result is one merged mesh: parts, pivots and hierarchy are not detected automatically (part detection is not implemented)"
            )
    ok = ok and run("collision", "collision", {})
    if opts.lod:
        ok = ok and run("LOD generation", "lod", {})
    validation = None
    if ok:
        announce("Validation")
        t = time.perf_counter()
        try:
            from aro_studio.validation.engine import ValidationConfig

            validation = processing.validation.validate_version(
                cur,
                ValidationConfig(
                    check_intersections=opts.validation_intersections,
                    size_confirmed=opts.length_supplied,
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
        advance("Validation complete" if ok else "Validation failed")
    final_version = None
    if ok:
        ok = run("finalize", "finalize", {"note": "AI mesh preparation pipeline"})
        final_version = cur
    return {
        "ok": ok,
        "source_axes": {"up": up, "forward": fwd},
        "needs_human": needs_human,
        "raw_version_id": raw_version_id,
        "cleaned_version_id": cleaned,
        "final_version_id": final_version,
        "validation": validation,
        "final_extents_m": [round(float(x), 4) for x in assets.load_scene(cur).combined().extents] if ok else None,
        "steps": [s.__dict__ for s in steps],
        "options": {k: v for k, v in opts.__dict__.items() if k != "vehicle_spec"},
    }
