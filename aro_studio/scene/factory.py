"""Build scenes from raw meshes (engine output or imported files)."""

from __future__ import annotations

import trimesh

from aro_studio.materials.library import make_material
from aro_studio.scene.model import PartDef, Provenance, SceneManifest
from aro_studio.scene.store import Scene

RAW_PART = "Raw_Mesh"


def scene_from_mesh(
    mesh: trimesh.Trimesh, name: str, category: str, provenance: Provenance, part_name: str = RAW_PART
) -> Scene:
    """A single-part scene with a neutral material; vertex colours (if any) are kept on the mesh."""
    mat = make_material("raw_surface", "generic", base_color=(1.0, 1.0, 1.0, 1.0), roughness=0.8)
    man = SceneManifest(
        name=name,
        category=category,
        parts=[PartDef(name=part_name, component="body", material=mat.name, mesh_file="")],
        materials=[mat],
        provenance=provenance,
    )
    sc = Scene(manifest=man, meshes={part_name: mesh})
    sc.refresh_counts()
    return sc
