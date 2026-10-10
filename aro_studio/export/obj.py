"""Wavefront OBJ/MTL writer (spec §21). OBJ has no hierarchy or units: positions are in asset space (metres)."""

from __future__ import annotations

import io

import numpy as np

from aro_studio.export.gltf import node_name
from aro_studio.export.shading import shade_split
from aro_studio.scene.store import Scene


def export_obj(
    scene: Scene, *, level: int = 0, name: str | None = None, hard_edge_angle_deg: float = 35.0
) -> tuple[str, str, dict[str, bytes], dict]:
    """Return (obj_text, mtl_text, {texture_path: bytes}, report) for one LOD level (default LOD0)."""
    man = scene.manifest
    parts = man.parts if level == 0 else next(lod for lod in man.lods if lod.level == level).parts
    meshes = scene.meshes if level == 0 else scene.lod_meshes[level]
    mtl_name = f"{node_name(name or man.name.replace(' ', '-'))}.mtl"
    o = io.StringIO()
    o.write(
        f"# ARO 3D Studio - {man.name} - LOD{level}\n# units: metres, +Y up, +Z forward (right-handed)\nmtllib {mtl_name}\n"
    )
    voff = toff = noff = 0
    tris = 0
    for p in parts:
        mesh = meshes.get(p.name)
        if mesh is None or not len(mesh.faces):
            continue
        s = shade_split(mesh, hard_edge_angle_deg)
        o.write(f"o {node_name(p.name)}\n")
        if p.material:
            o.write(f"usemtl {node_name(p.material)}\n")
        o.write("".join(f"v {x:.6f} {y:.6f} {z:.6f}\n" for x, y, z in s.positions))
        o.write("".join(f"vn {x:.5f} {y:.5f} {z:.5f}\n" for x, y, z in s.normals))
        has_uv = s.uv is not None
        if has_uv:
            o.write("".join(f"vt {u:.6f} {v:.6f}\n" for u, v in s.uv))  # type: ignore[union-attr]
        for a, b, c in s.indices + 1:
            ia, ib, ic = int(a) + voff, int(b) + voff, int(c) + voff
            if has_uv:
                o.write(
                    f"f {ia}/{int(a) + toff}/{int(a) + noff} {ib}/{int(b) + toff}/{int(b) + noff} {ic}/{int(c) + toff}/{int(c) + noff}\n"
                )
            else:
                o.write(f"f {ia}//{int(a) + noff} {ib}//{int(b) + noff} {ic}//{int(c) + noff}\n")
        tris += len(s.indices)
        voff += len(s.positions)
        noff += len(s.normals)
        toff += len(s.uv) if has_uv else 0  # type: ignore[arg-type]
    m = io.StringIO()
    files: dict[str, bytes] = {}
    for mat in man.materials:
        m.write(f"newmtl {node_name(mat.name)}\n")
        r, g, b, a = mat.base_color
        m.write(
            f"Kd {r:.4f} {g:.4f} {b:.4f}\nKa 0 0 0\nKs {mat.metallic * 0.5:.3f} {mat.metallic * 0.5:.3f} {mat.metallic * 0.5:.3f}\n"
        )
        m.write(f"Ns {max(1.0, (1.0 - mat.roughness) ** 2 * 1000):.1f}\nd {a:.3f}\n")
        if max(mat.emissive) > 0:
            m.write("Ke {:.3f} {:.3f} {:.3f}\n".format(*mat.emissive))
        m.write(f"Pr {mat.roughness:.4f}\nPm {mat.metallic:.4f}\n")
        for ch, key in (
            ("base_color", "map_Kd"),
            ("normal", "map_Bump"),
            ("emission", "map_Ke"),
            ("roughness", "map_Pr"),
            ("metallic", "map_Pm"),
        ):
            tn = mat.textures.get(ch)
            t = man.texture(tn) if tn else None
            if t and t.file in scene.texture_data:
                m.write(f"{key} {t.file}\n")
                files[t.file] = scene.texture_data[t.file]
        m.write("\n")
    return (
        o.getvalue(),
        m.getvalue(),
        files,
        {"format": "obj", "lod": level, "triangles": tris, "materials": len(man.materials)},
    )


_ = np
