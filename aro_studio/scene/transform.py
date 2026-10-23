"""Scene-wide rigid/uniform transforms that keep meshes, LODs, colliders and vehicle data consistent."""

from __future__ import annotations

import numpy as np

from aro_studio.core.errors import InvalidInputError
from aro_studio.scene.model import ColliderKind, Vec3
from aro_studio.scene.store import Scene


def _p3(m: np.ndarray, p: Vec3) -> Vec3:
    q = m @ np.array([*p, 1.0])
    return (float(q[0]), float(q[1]), float(q[2]))


def _pt(m: np.ndarray, p: Vec3 | None) -> Vec3 | None:
    return None if p is None else _p3(m, p)


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
        raise InvalidInputError(
            "Only rotations, uniform scale and translation are supported (no shear / non-uniform scale)."
        )
    if scene.manifest.colliders and not _axis_aligned(r):
        raise InvalidInputError(
            "This scene has colliders; only axis-aligned (90°) rotations can be applied. Regenerate collision after rotating.",
            recommended_action="Apply arbitrary rotations before generating collision.",
        )
    out = scene.copy()
    mirrored = np.linalg.det(r) < 0
    all_meshes = [
        *out.meshes.values(),
        *(m for d in out.lod_meshes.values() for m in d.values()),
        *out.collision_meshes.values(),
    ]
    for m in all_meshes:
        m.apply_transform(matrix)
        if mirrored:
            m.invert()
    man = out.manifest
    for part in man.parts:
        part.pivot = _p3(matrix, part.pivot)
    for lod in man.lods:
        for lod_part in lod.parts:
            lod_part.pivot = _p3(matrix, lod_part.pivot)
    perm = np.abs(r / sc)
    for col in man.colliders:
        col.center = _p3(matrix, col.center)
        if col.size is not None:
            sz = perm @ np.array(col.size) * sc
            col.size = (float(sz[0]), float(sz[1]), float(sz[2]))
        if col.radius is not None:
            col.radius *= sc
        if col.height is not None:
            col.height *= sc
        if col.kind is ColliderKind.CAPSULE:
            axis_vec = perm @ np.eye(3)["XYZ".index(col.axis)]
            col.axis = ("X", "Y", "Z")[int(np.argmax(axis_vec))]
    veh = man.vehicle
    if veh:
        if veh.center_of_mass is not None:
            veh.center_of_mass = _p3(matrix, veh.center_of_mass)
        veh.steering_points = [_p3(matrix, q) for q in veh.steering_points]
        veh.mirror_positions = [_p3(matrix, q) for q in veh.mirror_positions]
        if veh.wheelbase:
            veh.wheelbase *= sc
        for axle in veh.axles:
            axle.position = _p3(matrix, axle.position)
            axle.track_width *= sc
            axle.suspension_travel *= sc
        for wheel in veh.wheels:
            wheel.position = _p3(matrix, wheel.position)
            wheel.radius *= sc
            wheel.width *= sc
        for sp in veh.suspension_points:
            sp.position = _p3(matrix, sp.position)
            sp.travel *= sc
        for at in veh.attachment_points:
            at.position = _p3(matrix, at.position)
            at.direction = _dir(matrix, at.direction)
        for pv in veh.pivots:
            pv.position = _p3(matrix, pv.position)
            pv.axis = _dir(matrix, pv.axis)
        for light in veh.lights:
            light.position = _p3(matrix, light.position)
            light.direction = _dir(matrix, light.direction)
    if man.rig:
        for node in man.rig.nodes:
            node.pivot = _p3(matrix, node.pivot)
            if node.axis:
                node.axis = _dir(matrix, node.axis)
    out.refresh_counts()
    return out


def stretch_scene(scene: Scene, factors: tuple[float, float, float]) -> Scene:
    """Non-uniform scale along the scene's X/Y/Z. Only for a bare reconstruction: colliders, vehicle metadata and rigs are all expressed
    in metres/axes and would silently become wrong, so they must not exist yet."""
    f = np.asarray(factors, dtype=float)
    if not np.isfinite(f).all() or (f <= 0).any():
        raise InvalidInputError("Stretch factors must be positive.")
    man = scene.manifest
    if man.colliders or man.vehicle or man.rig:
        raise InvalidInputError(
            "Cannot stretch a scene that already has colliders, vehicle metadata or a rig.",
            recommended_action="Fit the real dimensions before generating collision or vehicle data.",
        )
    out = scene.copy()
    matrix = np.diag([*f, 1.0])
    for m in [*out.meshes.values(), *(m for d in out.lod_meshes.values() for m in d.values())]:
        m.apply_transform(matrix)
    for part in out.manifest.parts:
        part.pivot = _p3(matrix, part.pivot)
    for lod in out.manifest.lods:
        for lod_part in lod.parts:
            lod_part.pivot = _p3(matrix, lod_part.pivot)
    out.refresh_counts()
    return out


def scene_bounds(scene: Scene) -> np.ndarray:
    ms = [m for m in scene.meshes.values() if len(m.vertices)]
    if not ms:
        raise InvalidInputError("The scene has no geometry.")
    lo = np.min([m.bounds[0] for m in ms], axis=0)
    hi = np.max([m.bounds[1] for m in ms], axis=0)
    return np.array([lo, hi])
