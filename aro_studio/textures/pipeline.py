"""Scene-level texture operations."""

from __future__ import annotations

import trimesh

from aro_studio.core.errors import InvalidInputError
from aro_studio.core.tm import as_mesh, has_vertex_colors
from aro_studio.scene.model import TextureDef
from aro_studio.scene.store import Scene
from aro_studio.textures import process as tp
from aro_studio.textures.bake import ALLOWED_RESOLUTIONS, bake_color_texture
from aro_studio.textures.normal_bake import bake_normal_map
from aro_studio.textures.uv import DEFAULT_MAX_FACES, unwrap_jointly


def _set_texture(scene: Scene, name: str, data: bytes, channel: str, colorspace: str, fmt: str = "png") -> TextureDef:
    im = tp.open_image(data)
    t = TextureDef(
        name=name,
        file=f"textures/{name}.{'jpg' if fmt == 'jpeg' else fmt}",
        width=im.width,
        height=im.height,
        sha256="0" * 64,
        colorspace=colorspace,
        channel=channel,
        format=fmt,
    )
    old = scene.manifest.texture(name)
    if old:
        scene.texture_data.pop(old.file, None)
        scene.manifest.textures.remove(old)
    scene.manifest.textures.append(t)
    scene.texture_data[t.file] = data
    return t


def bake_scene_textures(
    scene: Scene,
    *,
    resolution: int = 1024,
    parts: list[str] | None = None,
    source: Scene | None = None,
    padding: int = 4,
    max_faces: int = DEFAULT_MAX_FACES,
    bake_normals: bool = False,
) -> dict:
    """Unwrap parts (grouped by material → one atlas each) and bake vertex colours into base-colour textures.

    ``source`` (typically the full-resolution mesh the budget mesh was decimated from, in the same frame) supplies the colours to project;
    without it the scene's own vertex colours are used. With ``bake_normals`` the source's fine surface detail is also baked into a
    tangent-space normal map, when the source has at least twice the triangles of the targets (otherwise there is no detail to transfer).
    """
    if resolution not in ALLOWED_RESOLUTIONS:
        raise InvalidInputError(f"Resolution must be one of {ALLOWED_RESOLUTIONS}.")
    man = scene.manifest
    names = parts or [p.name for p in man.parts]
    src_scene = source or scene
    groups: dict[str, list[str]] = {}
    for n in names:
        p = man.part(n)
        if p is None:
            raise InvalidInputError(f"Unknown part '{n}'.")
        groups.setdefault(p.material or "unassigned", []).append(n)
    report: dict = {"groups": [], "skipped": []}
    for gi, (mat_name, members) in enumerate(groups.items()):
        src_meshes = [
            src_scene.meshes[m]
            for m in (members if source is None else src_scene.meshes)
            if m in src_scene.meshes and has_vertex_colors(src_scene.meshes[m])
        ]
        if not src_meshes:
            report["skipped"].append({"material": mat_name, "reason": "no vertex colours to bake"})
            continue
        source_mesh = as_mesh(trimesh.util.concatenate(src_meshes)) if len(src_meshes) > 1 else src_meshes[0]
        unwrapped = unwrap_jointly({m: scene.meshes[m] for m in members}, max_faces=max_faces)
        png, stats = bake_color_texture(list(unwrapped.values()), source_mesh, resolution, padding)
        normal_png: bytes | None = None
        target_faces = sum(len(m.faces) for m in unwrapped.values())
        if bake_normals and len(source_mesh.faces) >= 2 * target_faces:
            normal_png, normal_stats = bake_normal_map(list(unwrapped.values()), source_mesh, resolution, padding)
            stats = {**stats, "normal_map": normal_stats}
        elif bake_normals:
            stats = {
                **stats,
                "normal_map": {
                    "skipped": "the source has fewer than twice the triangles of the target: no detail to transfer"
                },
            }
        tex_name = f"{mat_name}_basecolor" if mat_name != "unassigned" else f"baked_{gi}_basecolor"
        _set_texture(scene, tex_name, png, "base_color", "srgb")
        base = man.material(mat_name)
        baked_name = f"{mat_name}_baked" if mat_name != "unassigned" else f"baked_{gi}"
        if base:
            mat = base.model_copy(
                deep=True, update={"name": baked_name, "base_color": (1.0, 1.0, 1.0, base.base_color[3])}
            )
        else:
            from aro_studio.materials.library import make_material

            mat = make_material(baked_name, "generic", base_color=(1.0, 1.0, 1.0, 1.0))
        mat.textures = {**mat.textures, "base_color": tex_name}
        if normal_png is not None:
            normal_name = f"{baked_name}_normal"
            _set_texture(scene, normal_name, normal_png, "normal", "linear")
            mat.textures["normal"] = normal_name
        man.materials = [m for m in man.materials if m.name != baked_name] + [mat]
        for m in members:
            scene.meshes[m] = unwrapped[m]
            man.part(m).material = baked_name  # type: ignore[union-attr]
        report["groups"].append(
            {"material": mat_name, "baked_material": baked_name, "texture": tex_name, "parts": members, **stats}
        )
    scene.refresh_counts()
    # drop materials/textures no part references any more
    used = {p.material for p in man.parts}
    man.materials = [
        m for m in man.materials if m.name in used or m.name in {p.material for lod in man.lods for p in lod.parts}
    ]
    return report


def resize_scene_textures(scene: Scene, max_size: int) -> list[dict]:
    if max_size not in ALLOWED_RESOLUTIONS:
        raise InvalidInputError(f"Resolution must be one of {ALLOWED_RESOLUTIONS}.")
    out = []
    for t in scene.manifest.textures:
        data = scene.texture_data[t.file]
        new = tp.resize_texture(data, max_size)
        if new is not data:
            im = tp.open_image(new)
            scene.texture_data[t.file] = new
            out.append({"texture": t.name, "from": [t.width, t.height], "to": [im.width, im.height]})
            t.width, t.height = im.width, im.height
    return out


def compress_scene_textures(scene: Scene, fmt: str = "jpeg", quality: int = 88) -> list[dict]:
    """Re-encode opaque colour textures (JPEG is smaller; never applied to normal/data maps or alpha)."""
    out = []
    for t in list(scene.manifest.textures):
        if t.channel not in ("base_color", "emission") or t.format == fmt:
            continue
        im = tp.open_image(scene.texture_data[t.file])
        if im.mode in ("RGBA", "LA") and fmt == "jpeg":
            continue
        before = len(scene.texture_data[t.file])
        data = tp.encode(im, fmt, quality)
        new_file = f"textures/{t.name}.{'jpg' if fmt == 'jpeg' else fmt}"
        scene.texture_data.pop(t.file, None)
        scene.texture_data[new_file] = data
        t.file, t.format = new_file, fmt
        out.append({"texture": t.name, "bytes_before": before, "bytes_after": len(data)})
    return out


def unity_texture_settings(scene: Scene) -> list[dict]:
    """Per-texture Unity TextureImporter hints (consumed by the generated Editor importer)."""
    out = []
    for t in scene.manifest.textures:
        out.append(
            {
                "texture": t.name,
                "file": t.file,
                "sRGB": t.colorspace == "srgb",
                "generateMipMaps": True,
                "maxTextureSize": max(t.width, t.height),
                "isNormalMap": t.channel == "normal",
                "compression": "NormalQuality",
                "mipChainTexels": sum(w * h for w, h in tp.mip_chain(t.width, t.height)),
            }
        )
    return out
