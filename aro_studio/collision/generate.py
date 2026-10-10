"""Collision generation (spec §19). Collision geometry is kept separate from visual geometry.

All colliders live in ``manifest.colliders`` (+ ``collision_meshes`` for hull/mesh kinds) and are exported
under a dedicated ``Collision`` group. Convex hulls are capped at 255 triangles (the PhysX / Unity limit
for convex mesh colliders).
"""

from __future__ import annotations

import numpy as np
import trimesh

from aro_studio.core.errors import InvalidInputError
from aro_studio.core.tm import as_mesh
from aro_studio.geometry import ops
from aro_studio.scene.model import ColliderDef, ColliderKind
from aro_studio.scene.store import Scene

MAX_CONVEX_TRIANGLES = 255
# Parts excluded from the main body collider: they move, are tiny, or are handled by wheel colliders.
BODY_EXCLUDED_ROLES = {
    "wheel",
    "tire",
    "mirror",
    "wiper",
    "exhaust",
    "interior",
    "door",
    "window",
    "headlight",
    "taillight",
    "attachment",
}


def _selection(scene: Scene, parts: list[str] | None, exclude_roles: set[str] | None = None) -> trimesh.Trimesh:
    names = parts or [p.name for p in scene.manifest.parts if p.component not in (exclude_roles or set())]
    meshes = [scene.meshes[n] for n in names if n in scene.meshes and len(scene.meshes[n].faces)]
    if not meshes:
        raise InvalidInputError("No geometry selected for collision.")
    return as_mesh(trimesh.util.concatenate(meshes)) if len(meshes) > 1 else meshes[0]


def box_collider(name: str, mesh: trimesh.Trimesh, purpose: str = "body") -> ColliderDef:
    lo, hi = mesh.bounds
    c, size = (lo + hi) / 2, hi - lo
    return ColliderDef(
        name=name,
        kind=ColliderKind.BOX,
        purpose=purpose,
        center=tuple(float(x) for x in c),
        size=tuple(float(x) for x in size),
    )


def sphere_collider(name: str, mesh: trimesh.Trimesh, purpose: str = "body") -> ColliderDef:
    lo, hi = mesh.bounds
    c = (lo + hi) / 2
    r = float(np.linalg.norm(np.asarray(mesh.vertices) - c, axis=1).max())
    return ColliderDef(
        name=name, kind=ColliderKind.SPHERE, purpose=purpose, center=tuple(float(x) for x in c), radius=r
    )


def capsule_collider(name: str, mesh: trimesh.Trimesh, axis: str | None = None, purpose: str = "body") -> ColliderDef:
    lo, hi = mesh.bounds
    ext = hi - lo
    ai = "XYZ".index(axis.upper()) if axis else int(np.argmax(ext))
    others = [i for i in range(3) if i != ai]
    radius = float(max(ext[others]) / 2)
    height = float(max(ext[ai], 2 * radius))
    return ColliderDef(
        name=name,
        kind=ColliderKind.CAPSULE,
        purpose=purpose,
        center=tuple(float(x) for x in (lo + hi) / 2),
        radius=radius,
        height=height,
        axis="XYZ"[ai],
    )


def convex_hull(mesh: trimesh.Trimesh, max_triangles: int = MAX_CONVEX_TRIANGLES) -> trimesh.Trimesh:
    """Convex hull of ``mesh`` reduced to <= ``max_triangles`` (re-hulling keeps it truly convex)."""
    hull = mesh.convex_hull
    guard = 0
    while len(hull.faces) > max_triangles and guard < 12:
        target = max(4, int(len(hull.faces) * 0.7)) if len(hull.faces) * 0.7 > max_triangles else max_triangles - 2
        reduced, _ = ops.decimate(hull, target_faces=target)
        hull = trimesh.convex.convex_hull(reduced.vertices)
        guard += 1
    if len(hull.faces) > max_triangles:
        hull = _sampled_hull(np.asarray(hull.vertices), max_triangles)
    if len(hull.faces) > max_triangles:
        raise InvalidInputError(f"Could not reduce the convex hull below {max_triangles} triangles.")
    return trimesh.Trimesh(np.asarray(hull.vertices), np.asarray(hull.faces), process=False)


def _sampled_hull(vertices: np.ndarray, max_triangles: int) -> trimesh.Trimesh:
    """Hull of a farthest-point subset of ``vertices``.

    A convex hull of ``k`` points has at most ``2k - 4`` faces, so choosing
    ``k = max_triangles // 2 + 1`` bounds the triangle count regardless of how
    smooth the source surface is. Farthest-point sampling keeps the extremes, so
    the extents stay close; the hull is a subset of the true hull (slightly
    smaller, never larger) and the caller reports the fidelity.
    """
    k = max(4, max_triangles // 2 + 1)
    pts = np.asarray(vertices, dtype=float)
    if len(pts) <= k:
        return trimesh.convex.convex_hull(pts)
    chosen = [int(np.argmax(pts[:, 0])), int(np.argmin(pts[:, 0]))]
    dist = np.minimum(np.linalg.norm(pts - pts[chosen[0]], axis=1), np.linalg.norm(pts - pts[chosen[1]], axis=1))
    while len(chosen) < k:
        nxt = int(np.argmax(dist))
        chosen.append(nxt)
        dist = np.minimum(dist, np.linalg.norm(pts - pts[nxt], axis=1))
    return trimesh.convex.convex_hull(pts[chosen])


def add_collider(scene: Scene, collider: ColliderDef, mesh: trimesh.Trimesh | None = None) -> None:
    man = scene.manifest
    man.colliders = [c for c in man.colliders if c.name != collider.name]
    scene.collision_meshes.pop(collider.name, None)
    if collider.kind in (ColliderKind.CONVEX_HULL, ColliderKind.MESH, ColliderKind.VEHICLE_MESH):
        if mesh is None:
            raise InvalidInputError("Mesh colliders need a mesh.")
        collider.mesh_file = f"collision/{collider.name}.npz"
        collider.triangle_count = len(mesh.faces)
        scene.collision_meshes[collider.name] = mesh
    man.colliders.append(collider)


def generate_collision(
    scene: Scene,
    *,
    kind: str = "vehicle",
    parts: list[str] | None = None,
    max_triangles: int = MAX_CONVEX_TRIANGLES,
    wheel_colliders: bool = False,
    replace: bool = True,
) -> dict:
    """Create colliders. ``kind``: box | sphere | capsule | convex_hull | mesh | vehicle."""
    if replace:
        scene.manifest.colliders = []
        scene.collision_meshes = {}
    made: list[str] = []
    fidelity: dict[str, dict] = {}
    if kind == "vehicle":
        veh = scene.manifest.vehicle
        if veh is None:
            raise InvalidInputError(
                "Vehicle collision needs vehicle metadata.", recommended_action="Configure the vehicle first."
            )
        body = _selection(scene, parts, BODY_EXCLUDED_ROLES)
        hull = convex_hull(body, max_triangles)
        add_collider(
            scene, ColliderDef(name="COL_Body", kind=ColliderKind.VEHICLE_MESH, purpose="body", source_part=None), hull
        )
        made.append("COL_Body")
        fidelity["COL_Body"] = _fidelity(body, hull)
        cab_parts = [p.name for p in scene.manifest.parts if p.component in ("cabin", "door", "window")]
        if cab_parts:
            cab = _selection(scene, cab_parts)
            chull = convex_hull(cab, max_triangles)
            add_collider(scene, ColliderDef(name="COL_Cabin", kind=ColliderKind.CONVEX_HULL, purpose="cabin"), chull)
            made.append("COL_Cabin")
            fidelity["COL_Cabin"] = _fidelity(cab, chull)
        if wheel_colliders:
            for w in veh.wheels:
                # Optional rolling-sphere approximation. Proper wheel physics use the game's WheelColliders,
                # configured from the exported wheel metadata (position/radius/width) - see docs/unity.
                scene.manifest.colliders.append(
                    ColliderDef(
                        name=f"COL_{w.name}",
                        kind=ColliderKind.SPHERE,
                        purpose="wheel",
                        center=w.position,
                        radius=w.radius,
                        source_part=w.tire_part,
                    )
                )
                made.append(f"COL_{w.name}")
    else:
        m = _selection(scene, parts)
        if kind == "box":
            add_collider(scene, box_collider("COL_Box", m))
            made.append("COL_Box")  # noqa: E702
        elif kind == "sphere":
            add_collider(scene, sphere_collider("COL_Sphere", m))
            made.append("COL_Sphere")  # noqa: E702
        elif kind == "capsule":
            add_collider(scene, capsule_collider("COL_Capsule", m))
            made.append("COL_Capsule")  # noqa: E702
        elif kind == "convex_hull":
            add_collider(
                scene, ColliderDef(name="COL_Hull", kind=ColliderKind.CONVEX_HULL), convex_hull(m, max_triangles)
            )
            made.append("COL_Hull")  # noqa: E702
        elif kind == "mesh":
            simp, _ = ops.decimate(m, target_faces=max(12, min(len(m.faces), max_triangles * 8)))
            add_collider(scene, ColliderDef(name="COL_Mesh", kind=ColliderKind.MESH), simp)
            made.append("COL_Mesh")  # noqa: E702
        else:
            raise InvalidInputError(
                f"Unknown collision kind '{kind}'.",
                recommended_action="Use box, sphere, capsule, convex_hull, mesh or vehicle.",
            )
    scene.refresh_counts()
    return {
        "colliders": made,
        "triangles": int(sum(len(m.faces) for m in scene.collision_meshes.values())),
        "fidelity": fidelity,
    }


def _fidelity(source: trimesh.Trimesh, reduced: trimesh.Trimesh) -> dict:
    """How closely the reduced hull follows the exact convex hull (volume ratio, worst-case vertex gap in metres)."""
    exact = source.convex_hull
    gap = 0.0
    try:
        pts = np.asarray(exact.vertices)
        _, dist, _ = trimesh.proximity.closest_point(reduced, pts)
        inside = reduced.contains(pts)
        gap = float(np.max(np.where(inside, 0.0, dist)))
    except Exception:  # noqa: BLE001 - fidelity is informational
        gap = float("nan")
    return {
        "exact_triangles": int(len(exact.faces)),
        "reduced_triangles": int(len(reduced.faces)),
        "volume_ratio": round(float(reduced.volume / exact.volume), 4) if exact.volume > 0 else None,
        "max_corner_gap_m": round(gap, 4),
    }
