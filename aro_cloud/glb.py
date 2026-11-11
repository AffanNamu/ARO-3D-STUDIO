"""Reading the GLBs the pipeline writes: one file holds the visual model at several levels of detail plus collision meshes.

Naming (set by the Studio's exporter): visual meshes end in ``_LOD0`` .. ``_LODn`` (LOD0 is the full-detail model), collision meshes start
with ``COL_``. A GLB without those names (a raw engine output, a user's file) is treated as a single full-detail model.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any

import numpy as np
import trimesh

_LOD = re.compile(r"_LOD(\d+)$", re.IGNORECASE)


@dataclass
class Part:
    name: str
    mesh: trimesh.Trimesh  # in scene coordinates (the node transform is applied)
    lod: int | None  # None: not an LOD-named mesh
    collision: bool


def load_scene(data: bytes) -> Any:
    return trimesh.load(io.BytesIO(data), file_type="glb", force="scene", process=False)


def parts_of(scene: Any) -> list[Part]:
    out: list[Part] = []
    seen: set[str] = set()
    for node in scene.graph.nodes_geometry:
        transform, geom_name = scene.graph[node]
        geom = scene.geometry.get(geom_name)
        if not isinstance(geom, trimesh.Trimesh) or len(geom.faces) == 0:
            continue
        seen.add(str(geom_name))
        mesh = geom.copy()
        if not np.allclose(transform, np.eye(4)):
            mesh.apply_transform(transform)
        label = str(node) if _LOD.search(str(node)) or str(node).upper().startswith("COL_") else str(geom_name)
        m = _LOD.search(label)
        out.append(Part(label, mesh, int(m.group(1)) if m else None, label.upper().startswith("COL_")))
    for name, geom in scene.geometry.items():  # geometry no node refers to still counts (some writers omit nodes)
        if str(name) in seen or not isinstance(geom, trimesh.Trimesh) or len(geom.faces) == 0:
            continue
        m = _LOD.search(str(name))
        out.append(Part(str(name), geom, int(m.group(1)) if m else None, str(name).upper().startswith("COL_")))
    return out


def full_detail(parts: list[Part]) -> list[Part]:
    """The meshes a person means by "the model": the lowest LOD level present plus any visual mesh that is not LOD-named."""
    visual = [p for p in parts if not p.collision]
    levels = [p.lod for p in visual if p.lod is not None]
    if not levels:
        return visual
    top = min(levels)
    return [p for p in visual if p.lod is None or p.lod == top]


def lod_table(parts: list[Part]) -> list[dict[str, int]]:
    table: dict[int, int] = {}
    for p in parts:
        if not p.collision and p.lod is not None:
            table[p.lod] = table.get(p.lod, 0) + len(p.mesh.faces)
    return [{"level": k, "triangles": v} for k, v in sorted(table.items())]
