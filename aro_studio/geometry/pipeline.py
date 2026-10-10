"""Scene-level geometry processing: run a list of operations, producing a before/after report."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import trimesh

from aro_studio.assets.taxonomy import get_category
from aro_studio.core.cancellation import CancellationToken
from aro_studio.core.errors import InvalidInputError
from aro_studio.geometry import ops
from aro_studio.geometry.inspect import MeshReport, inspect_mesh
from aro_studio.scene.store import Scene
from aro_studio.scene.transform import scene_bounds, transform_scene

# Operations applied independently to each part mesh: (mesh, **params) -> (mesh, OpReport)
PART_OPS: dict[str, Callable[..., tuple[trimesh.Trimesh, ops.OpReport]]] = {
    "remove_invalid": ops.remove_invalid,
    "merge_vertices": ops.merge_vertices,
    "remove_degenerate": ops.remove_degenerate,
    "remove_duplicate_faces": ops.remove_duplicate_faces,
    "remove_small_components": ops.remove_small_components,
    "fix_normals": ops.fix_normals,
    "fill_holes": ops.fill_holes,
    "smooth": ops.smooth,
    "decimate": ops.decimate,
}
# Operations applied to the whole scene with one matrix so parts stay aligned.
SCENE_OPS = {"orient", "scale", "uniform_scale", "set_pivot"}

STANDARD_CLEANUP: list[dict[str, Any]] = [
    {"op": "remove_invalid"},
    {"op": "merge_vertices"},
    {"op": "remove_degenerate"},
    {"op": "remove_duplicate_faces"},
    {"op": "remove_small_components", "params": {"min_face_ratio": 0.01}},
    {"op": "fix_normals"},
]


def known_operations() -> list[str]:
    return sorted([*PART_OPS, *SCENE_OPS])


def combined_report(
    scene: Scene, *, category: str, tri_budget: int | None, check_intersections: bool = True
) -> MeshReport:
    group = get_category(category).group
    mesh = scene.combined(0) if len(scene.meshes) > 1 else next(iter(scene.meshes.values()))
    return inspect_mesh(mesh, category_group=group, tri_budget=tri_budget, check_intersections=check_intersections)


def run_steps(
    scene: Scene,
    steps: list[dict[str, Any]],
    *,
    category: str,
    tri_budget: int | None = None,
    cancel: CancellationToken | None = None,
    progress: Callable[[float, str], None] | None = None,
    inspect_after: bool = True,
    check_intersections: bool = False,
) -> tuple[Scene, dict[str, Any]]:
    """Apply ``steps`` to a copy of ``scene``. Returns (new_scene, report). The input is untouched."""
    if not scene.meshes:
        raise InvalidInputError("The scene has no geometry to process.")
    group = get_category(category).group
    work = scene.copy()
    before = combined_report(
        work, category=category, tri_budget=tri_budget, check_intersections=check_intersections
    ).to_dict()
    log: list[dict[str, Any]] = []
    for i, step in enumerate(steps):
        if cancel:
            cancel.check()
        name, params = step.get("op"), dict(step.get("params") or {})
        if progress:
            progress(i / max(len(steps), 1), f"Geometry: {name}")
        if name in SCENE_OPS:
            work, rep = _scene_op(work, name, params, group)
            log.append(rep)
        elif name in PART_OPS:
            targets = params.pop("parts", None) or list(work.meshes)
            fn = PART_OPS[name]
            per_part = {}
            for pn in targets:
                if pn not in work.meshes:
                    raise InvalidInputError(f"Unknown part '{pn}' in step '{name}'.")
                new_mesh, op_rep = fn(work.meshes[pn], **params)
                work.meshes[pn] = new_mesh
                per_part[pn] = op_rep.to_dict()
            log.append({"op": name, "params": params, "parts": per_part})
        else:
            raise InvalidInputError(
                f"Unknown geometry operation '{name}'.", recommended_action=f"Known operations: {known_operations()}"
            )
    work.refresh_counts()
    after = combined_report(work, category=category, tri_budget=tri_budget).to_dict() if inspect_after else None
    return work, {"steps": log, "before": before, "after": after}


def _scene_op(work: Scene, name: str, params: dict[str, Any], group: str) -> tuple[Scene, dict[str, Any]]:
    b = scene_bounds(work)
    if name == "orient":
        m = ops.rotation_to_canonical(params["up"], params["forward"])
        out = transform_scene(work, m)
        return out, {"op": name, "params": params}
    if name == "scale":
        length = float(params["length_m"])
        axis = params.get("axis", "Z").upper()
        cur = float((b[1] - b[0])["XYZ".index(axis)])
        if cur <= 0:
            raise InvalidInputError("Cannot scale: zero extent on that axis.")
        f = length / cur
        m = np.eye(4)
        m[:3, :3] *= f
        return transform_scene(work, m), {"op": name, "params": params, "factor": f}
    if name == "uniform_scale":
        f = float(params["factor"])
        if f <= 0:
            raise InvalidInputError("factor must be positive.")
        m = np.eye(4)
        m[:3, :3] *= f
        return transform_scene(work, m), {"op": name, "params": params, "factor": f}
    if name == "set_pivot":
        t = ops.pivot_translation(
            b, params.get("mode", "ground_center"), tuple(params["point"]) if params.get("point") else None
        )
        m = np.eye(4)
        m[:3, 3] = t
        return transform_scene(work, m), {"op": name, "params": params, "translation": t.round(9).tolist()}
    raise InvalidInputError(f"Unknown scene operation '{name}'.")  # pragma: no cover
