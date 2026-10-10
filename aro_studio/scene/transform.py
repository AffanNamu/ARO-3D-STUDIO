"""Scene-wide rigid/uniform transforms that keep meshes, LODs, colliders and vehicle data consistent."""

from __future__ import annotations

import numpy as np

from aro_studio.core.errors import InvalidInputError
from aro_studio.scene.model import ColliderKind, Vec3
from aro_studio.scene.store import Scene


def _pt(m: np.ndarray, p: Vec3 | None) -> Vec3 | None:
    if p is None:
        return None
    q = m @ np.array([*p, 1.0])
    return (float(q[0]), float(q[1]), float(q[2]))


def _dir(m: np.ndarray, d: Vec3) -> Vec3:
    r = m[:3, :3]
    s = np.cbrt(abs(np.linalg.det(r))) or 1.0
    q = (r / s) @ np.array(d)
    n = np.linalg.norm(q) or 1.0
    q = q / n
    return (float(q[0]), float(q[1]), float(q[2]))


def _axis_aligned(r: np.ndarray) -> bool:
    s = np.cbrt(abs(np.linalg.det(r))) or 1.0
    n = np.abs(r / s)
    return bool(np.all(np.isclose(n.max(axis=1), 1.0, atol=1e-6)) and np.all(np.isclose(n.sum(axis=1), 1.0, atol=1e-6)))


def transform_scene(scene: Scene, matrix: np.ndarray) -> Scene:
    """Return a transformed copy. Non-axis-aligned rotations are rejected when colliders exist."""
    matrix = np.asarray(matrix, dtype=float)
    r = matrix[:3, :3]
    sc = float(np.cbrt(abs(np.linalg.det(r))))
    if sc <= 0:
        raise InvalidInputError("Transform is singular.")
    if not np.allclose(r / sc @ (r / sc).T, np.eye(3), atol=1e-6):
        raise InvalidInputError("Only rotations, uniform scale and translation are supported (no shear / non-uniform scale).")
    if scene.manifest.colliders and not _axis_aligned(r):
        raise InvalidInputError(
            "This scene has colliders; only axis-aligned (90°) rotations can be applied. Regenerate collision after rotating.",
            recommended_action="Apply arbitrary rotations before generating collision.",
        )
    out = scene.copy()
    mirrored = np.linalg.det(r) < 0
    allm = [*out.meshes.values(), *(m for d in out.lod_meshes.values() for m in d.values()), *out.collision_meshes.values()]
    for m in allm:
        m.apply_transform(matrix)
        if mirrored:
            m.invert()
    man = out.manifest
    for p in man.parts:
        p.pivot = _pt(matrix, p.pivot)  # type: ignore[assignment]
    for lod in man.lods:
        for p in lod.parts:
            p.pivot = _pt(matrix, p.pivot)  # type: ignore[assignment]
    for c in man.colliders:
        c.center = _pt(matrix, c.center)  # type: ignore[assignment]
        if c.size is not None:
            perm = np.abs(r / sc) @ np.array(c.size) * sc
            c.size = (float(perm[0]), float(perm[1]), float(perm[2]))
        if c.radius is not None:
            c.radius *= sc
        if c.height is not None:
            c.height *= sc
        if c.kind is ColliderKind.CAPSULE:
            ax = np.abs(r / sc) @ np.eye(3)["XYZ".index(c.axis)]
            c.axis = "XYZ"[int(np.argmax(ax))]  # type: ignore[assignment]
    v = man.vehicle
    if v:
        v.center_of_mass = _pt(matrix, v.center_of_mass)
        v.steering_points = [_pt(matrix, p) for p in v.steering_points]  # type: ignore[misc]
        v.mirror_positions = [_pt(matrix, p) for p in v.mirror_positions]  # type: ignore[misc]
        if v.wheelbase:
            v.wheelbase *= sc
        for a in v.axles:
            a.position = _pt(matrix, a.position)  # type: ignore[assignment]
            a.track_width *= sc
            a.suspension_travel *= sc
        for w in v.wheels:
            w.position = _pt(matrix, w.position)  # type: ignore[assignment]
            w.radius *= sc
            w.width *= sc
        for s in v.suspension_points:
            s.position = _pt(matrix, s.position)  # type: ignore[assignment]
            s.travel *= sc
        for a in v.attachment_points:
            a.position = _pt(matrix, a.position)  # type: ignore[assignment]
            a.direction = _dir(matrix, a.direction)
        for p in v.pivots:
            p.position = _pt(matrix, p.position)  # type: ignore[assignment]
            p.axis = _dir(matrix, p.axis)
        for li in v.lights:
            li.position = _pt(matrix, li.position)  # type: ignore[assignment]
            li.direction = _dir(matrix, li.direction)
    if man.rig:
        for n in man.rig.nodes:
            n.pivot = _pt(matrix, n.pivot)  # type: ignore[assignment]
            if n.axis:
                n.axis = _dir(matrix, n.axis)
    out.refresh_counts()
    return out


def scene_bounds(scene: Scene) -> np.ndarray:
    ms = [m for m in scene.meshes.values() if len(m.vertices)]
    if not ms:
        raise InvalidInputError("The scene has no geometry.")
    lo = np.min([m.bounds[0] for m in ms], axis=0)
    hi = np.max([m.bounds[1] for m in ms], axis=0)
    return np.array([lo, hi])
