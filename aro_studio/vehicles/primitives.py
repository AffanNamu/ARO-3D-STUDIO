"""Small, deterministic mesh builders used to author the procedural reference vehicle."""

from __future__ import annotations

import numpy as np
import trimesh
from shapely.geometry import Polygon

from aro_studio.core.tm import as_mesh

_SECTIONS = 32


def box(center, size) -> trimesh.Trimesh:
    m = trimesh.creation.box(extents=size)
    m.apply_translation(center)
    return m


def cylinder_x(center, radius: float, length: float, sections: int = _SECTIONS) -> trimesh.Trimesh:
    """Cylinder whose axis is X (wheel/axle orientation)."""
    m = trimesh.creation.cylinder(radius=radius, height=length, sections=sections)
    m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    m.apply_translation(center)
    return m


def cylinder_y(center, radius: float, height: float, sections: int = _SECTIONS) -> trimesh.Trimesh:
    m = trimesh.creation.cylinder(radius=radius, height=height, sections=sections)
    m.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
    m.apply_translation(center)
    return m


def cylinder_z(center, radius: float, length: float, sections: int = _SECTIONS) -> trimesh.Trimesh:
    m = trimesh.creation.cylinder(radius=radius, height=length, sections=sections)
    m.apply_translation(center)
    return m


def revolve_x(profile_rz: list[tuple[float, float]], center, sections: int = 48) -> trimesh.Trimesh:
    """Solid of revolution about the X axis. ``profile_rz`` = [(radius, axial_x)...] along the outline."""
    pts = list(profile_rz)
    if pts[0] != pts[-1]:
        pts.append(pts[0])  # close the outline so the solid is watertight
    ls = np.array([[r, a] for r, a in pts], dtype=float)
    m = trimesh.creation.revolve(ls, sections=sections)  # revolves about local Z; profile is (x=r, z=axial)
    m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    m.apply_translation(center)
    if m.volume < 0:
        m.invert()
    return m


def extrude_profile_zy(points_zy: list[tuple[float, float]], width_x: float, center_x: float = 0.0) -> trimesh.Trimesh:
    """Extrude a side-view polygon given as (z, y) points sideways along X (centred on ``center_x``)."""
    poly = Polygon(points_zy)
    if not poly.is_valid:
        poly = poly.buffer(0)
    m = trimesh.creation.extrude_polygon(poly, height=width_x)  # polygon in XY, extruded along +Z
    # (x', y', z') = (z, y, x)  → permutation matrix
    perm = np.array([[0, 0, 1, 0], [0, 1, 0, 0], [1, 0, 0, 0], [0, 0, 0, 1]], dtype=float)
    m.apply_transform(perm)
    if m.volume < 0:
        m.invert()
    m.apply_translation([center_x - width_x / 2, 0, 0])
    return m


def tube_between(a, b, radius: float, sections: int = 12) -> trimesh.Trimesh:
    a, b = np.asarray(a, float), np.asarray(b, float)
    return trimesh.creation.cylinder(radius=radius, segment=np.array([a, b]), sections=sections)


def torus_z(
    center, major: float, minor: float, rot=None, major_sections: int = 32, minor_sections: int = 12
) -> trimesh.Trimesh:
    m = trimesh.creation.torus(
        major_radius=major, minor_radius=minor, major_sections=major_sections, minor_sections=minor_sections
    )
    if rot is not None:
        m.apply_transform(rot)
    m.apply_translation(center)
    return m


def merge(meshes: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    return as_mesh(trimesh.util.concatenate(meshes))
