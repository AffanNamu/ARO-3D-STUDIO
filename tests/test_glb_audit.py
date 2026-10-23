"""Per-node audit of an exported GLB (every LOD and the collision mesh)."""

from __future__ import annotations

import numpy as np
import trimesh

from aro_studio.verification.glb_audit import audit_glb


def _sphere(r=0.5, sub=3):
    m = trimesh.creation.icosphere(subdivisions=sub, radius=r)
    v = np.asarray(m.vertices)
    uv = np.c_[0.5 + np.arctan2(v[:, 1], v[:, 0]) / (2 * np.pi), 0.5 + np.arcsin(np.clip(v[:, 2] / r, -1, 1)) / np.pi]
    m.visual = trimesh.visual.TextureVisuals(uv=np.clip(uv, 0, 1))
    return m


def _export(tmp_path, nodes: dict[str, trimesh.Trimesh]):
    scene = trimesh.Scene()
    for name, m in nodes.items():
        scene.add_geometry(m, node_name=name, geom_name=name)
    p = tmp_path / "a.glb"
    p.write_bytes(trimesh.exchange.gltf.export_glb(scene))
    return p


def _lods():
    return {
        "Mesh_LOD0": _sphere(0.5, 4),
        "Mesh_LOD1": _sphere(0.5, 3),
        "Mesh_LOD2": _sphere(0.5, 2),
        "COL_Hull": trimesh.convex.convex_hull(_sphere(0.5, 1).vertices),
    }


def test_a_consistent_lod_chain_and_a_convex_collider_pass(tmp_path):
    r = audit_glb(_export(tmp_path, _lods()))
    assert r["ok"], [c["message"] for c in r["checks"] if not c["ok"]]
    assert {n["name"] for n in r["nodes"]} == {"Mesh_LOD0", "Mesh_LOD1", "Mesh_LOD2", "COL_Hull"}


def test_lod_ladder_collider_limit_and_bounds_failures_are_reported(tmp_path):
    nodes = _lods()
    nodes["Mesh_LOD1"] = _sphere(0.5, 5)  # more triangles than LOD0: ladder broken
    nodes["COL_Hull"] = _sphere(0.5, 3)  # 1280 triangles: over the convex-collider limit
    r = audit_glb(_export(tmp_path, nodes))
    failed = " | ".join(c["message"] for c in r["checks"] if not c["ok"])
    assert not r["ok"] and "strictly decrease" in failed and "convex-collider limit" in failed


def test_a_lod_that_drifts_from_lod0_is_reported(tmp_path):
    nodes = _lods()
    nodes["Mesh_LOD2"] = _sphere(0.6, 2)  # 20 % bigger
    r = audit_glb(_export(tmp_path, nodes))
    assert any(not c["ok"] and c["id"] == "Mesh_LOD2.bounds" for c in r["checks"])


def test_seam_duplicated_vertices_do_not_read_as_holes(tmp_path):
    """Exporters split vertices at normal/UV seams; topology is judged after welding by position."""
    hull = trimesh.convex.convex_hull(_sphere(0.5, 1).vertices)
    nodes = _lods()
    # un-weld: every face gets its own three vertices, like a faceted export
    nodes["COL_Hull"] = trimesh.Trimesh(
        np.asarray(hull.vertices)[np.asarray(hull.faces).reshape(-1)],
        np.arange(len(hull.faces) * 3).reshape(-1, 3),
        process=False,
    )
    r = audit_glb(_export(tmp_path, nodes))
    col = next(n for n in r["nodes"] if n["name"] == "COL_Hull")
    assert col["watertight"] and col["convex"]
