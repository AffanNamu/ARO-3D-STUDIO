"""Runs INSIDE Blender: inspect an asset file, or convert it to another format and verify the result by re-importing it.

Not imported by the Studio (it needs ``bpy``). The Studio starts it in a separate process, either with a Blender executable::

    blender --background --factory-startup --python blender_worker.py -- convert --in a.glb --out a.fbx --format fbx --target unity

or with a Python interpreter that has the ``bpy`` module installed::

    python blender_worker.py convert --in a.glb --out a.fbx --format fbx --target unity

The last line printed is ``ARO_BLENDER_RESULT <json>``. Blender is an INDEPENDENT consumer of the file: that is why it is used to verify
exports (does a tool that is not ours read the triangles, the real-world size and the materials back?), not only to write them.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from typing import Any

import bpy
import numpy as np

RESULT_TAG = "ARO_BLENDER_RESULT "

# FBX conventions per target application. Blender writes the axis metadata into the file; the importer of the target reads it.
FBX_TARGETS = {
    "unity": {"axis_forward": "-Z", "axis_up": "Y", "apply_scale_options": "FBX_SCALE_ALL"},
    "unreal": {"axis_forward": "-Y", "axis_up": "Z", "apply_scale_options": "FBX_SCALE_UNITS"},
}


def reset() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_any(path: str) -> None:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext in (".usd", ".usda", ".usdc", ".usdz"):
        bpy.ops.wm.usd_import(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext == ".blend":
        bpy.ops.wm.open_mainfile(filepath=path)
    else:
        raise ValueError(f"cannot import '{ext}' files")


def _is_collision(name: str) -> bool:
    return name.upper().startswith("COL_") or "_COL" in name.upper() or name.upper().startswith("UCX_")


def _lod_index(name: str) -> int | None:
    up = name.upper()
    if "_LOD" in up:
        tail = up.rsplit("_LOD", 1)[1]
        digits = "".join(ch for ch in tail if ch.isdigit())
        return int(digits) if digits else None
    return None


def _principled(mat):
    if not mat or not mat.use_nodes or not mat.node_tree:
        return None
    for n in mat.node_tree.nodes:
        if n.type == "BSDF_PRINCIPLED":
            return n
    return None


def inspect() -> dict:
    """What a Blender user would see after importing: geometry, real-world size in metres, materials and which maps are wired up."""
    dg = bpy.context.evaluated_depsgraph_get()
    objects = []
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    total = lod0 = 0
    mats: dict[str, dict] = {}
    for ob in bpy.context.scene.objects:
        if ob.type != "MESH":
            continue
        me = ob.evaluated_get(dg).to_mesh()
        me.calc_loop_triangles()
        tris = len(me.loop_triangles)
        co = np.empty(len(me.vertices) * 3, dtype=np.float64)
        me.vertices.foreach_get("co", co)
        m = np.array(ob.matrix_world, dtype=np.float64)
        pts = co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]
        has_uv = bool(me.uv_layers)
        objects.append(
            {
                "name": ob.name,
                "triangles": tris,
                "vertices": len(me.vertices),
                "uv": has_uv,
                "lod": _lod_index(ob.name),
                "collision": _is_collision(ob.name),
            }
        )
        total += tris
        visual = not _is_collision(ob.name) and _lod_index(ob.name) in (None, 0)
        if visual:
            lod0 += tris
            if len(pts):
                lo = np.minimum(lo, pts.min(axis=0))
                hi = np.maximum(hi, pts.max(axis=0))
        for slot in ob.material_slots:
            mat = slot.material
            if mat is None or mat.name in mats:
                continue
            bsdf = _principled(mat)
            info: dict[str, Any] = {"principled": bsdf is not None, "base_color_map": False, "normal_map": False}
            if bsdf is not None:
                bc = bsdf.inputs.get("Base Color")
                nm = bsdf.inputs.get("Normal")
                info["base_color_map"] = bool(bc and bc.is_linked and bc.links[0].from_node.type == "TEX_IMAGE")
                # a Normal Map node counts only if an IMAGE feeds it (Blender's FBX importer adds an empty one to every material)
                nmn = nm.links[0].from_node if nm and nm.is_linked else None
                col = nmn.inputs.get("Color") if nmn is not None and nmn.type == "NORMAL_MAP" else None
                info["normal_map"] = bool(col and col.is_linked and col.links[0].from_node.type == "TEX_IMAGE")
                info["metallic"] = round(float(bsdf.inputs["Metallic"].default_value), 3)
                info["roughness"] = round(float(bsdf.inputs["Roughness"].default_value), 3)
            mats[mat.name] = info
        ev = ob.evaluated_get(dg)
        ev.to_mesh_clear()
    ext = (hi - lo) if np.isfinite(lo).all() else np.zeros(3)
    scene = bpy.context.scene
    return {
        "blender": bpy.app.version_string,
        "objects": objects,
        "triangles_total": total,
        "triangles_lod0": lod0,
        "extents_blender_m": [round(float(x), 5) for x in ext],  # Blender: X right, Y forward, Z up
        "extents_studio_m": [
            round(float(ext[0]), 5),
            round(float(ext[2]), 5),
            round(float(ext[1]), 5),
        ],  # Studio: X width, Y height, Z length
        "unit_scale": float(scene.unit_settings.scale_length),
        "length_unit": scene.unit_settings.length_unit,
        "materials": mats,
        "images": sorted(i.name for i in bpy.data.images if i.type == "IMAGE" and i.name != "Render Result"),
    }


def texture_probe(max_samples: int = 4000) -> dict:
    """Where does each texel land? For loops of the visual LOD0 meshes: the corner's world position and the base-colour image sampled at
    the corner's UV with Blender's own convention (rows counted from the bottom). The Studio compares these with the colours it baked:
    a vertically mirrored texture is invisible to counts and extents but wrong here."""
    rng = np.random.default_rng(0)
    pos_all, col_all = [], []
    for ob in bpy.context.scene.objects:
        if ob.type != "MESH" or _is_collision(ob.name) or _lod_index(ob.name) not in (None, 0):
            continue
        mat = ob.material_slots[0].material if ob.material_slots else None
        bsdf = _principled(mat)
        bc = bsdf.inputs.get("Base Color") if bsdf else None
        if not (bc and bc.is_linked and bc.links[0].from_node.type == "TEX_IMAGE" and bc.links[0].from_node.image):
            continue
        img = bc.links[0].from_node.image
        w, h = img.size
        px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)[..., :3]
        me = ob.data
        if not me.uv_layers:
            continue
        uv_flat = np.empty(len(me.loops) * 2)
        me.uv_layers.active.data.foreach_get("uv", uv_flat)
        uv = uv_flat.reshape(-1, 2)
        loop_vertex = np.empty(len(me.loops), dtype=np.int32)
        me.loops.foreach_get("vertex_index", loop_vertex)
        co = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get("co", co)
        m = np.array(ob.matrix_world, dtype=np.float64)
        world = co.reshape(-1, 3)[loop_vertex] @ m[:3, :3].T + m[:3, 3]
        pick = rng.choice(len(uv), size=min(max_samples, len(uv)), replace=False)
        xi = np.clip(np.round(uv[pick, 0] * (w - 1)).astype(int), 0, w - 1)
        yi = np.clip(np.round(uv[pick, 1] * (h - 1)).astype(int), 0, h - 1)
        pos_all.append(world[pick])
        col_all.append(px[yi, xi])
    if not pos_all:
        return {"positions_blender": [], "colors": []}
    return {
        "positions_blender": np.concatenate(pos_all).round(5).tolist(),
        "colors": np.concatenate(col_all).round(4).tolist(),
    }


def _filtered(op, kwargs: dict) -> tuple[dict, list[str]]:
    """Only the options this Blender version knows (the operator properties change between releases); the rest are reported."""
    props = set(op.get_rna_type().properties.keys())
    return {k: v for k, v in kwargs.items() if k in props}, sorted(k for k in kwargs if k not in props)


def export_as(dst: str, fmt: str, target: str) -> list[str]:
    skipped: list[str] = []
    if fmt == "fbx":
        t = FBX_TARGETS.get(target, FBX_TARGETS["unity"])
        kw, skipped = _filtered(
            bpy.ops.export_scene.fbx,
            {
                "filepath": dst,
                "check_existing": False,
                "use_selection": False,
                "object_types": {"MESH", "EMPTY"},
                "use_mesh_modifiers": True,
                "mesh_smooth_type": "FACE",
                "use_tspace": True,
                "path_mode": "COPY",
                "embed_textures": True,
                "bake_anim": False,
                "add_leaf_bones": False,
                "global_scale": 1.0,
                "apply_unit_scale": True,
                **t,
            },
        )
        bpy.ops.export_scene.fbx(**kw)
    elif fmt == "usd":
        kw, skipped = _filtered(
            bpy.ops.wm.usd_export,
            {
                "filepath": dst,
                "check_existing": False,
                "selected_objects_only": False,
                "export_materials": True,
                "generate_preview_surface": True,
                "export_textures": True,
                "export_textures_mode": "NEW",
                "overwrite_textures": True,
                "relative_paths": True,
                "export_normals": True,
                "export_uvmaps": True,
            },
        )
        bpy.ops.wm.usd_export(**kw)
    elif fmt == "blend":
        bpy.ops.wm.save_as_mainfile(filepath=dst, compress=True, check_existing=False)
    elif fmt == "obj":
        kw, skipped = _filtered(
            bpy.ops.wm.obj_export,
            {"filepath": dst, "check_existing": False, "export_materials": True, "path_mode": "COPY"},
        )
        bpy.ops.wm.obj_export(**kw)
    else:
        raise ValueError(f"unknown format '{fmt}'")
    return skipped


def compare(before: dict, after: dict, rel_tol: float = 0.01) -> list[dict]:
    checks = []

    def add(cid: str, ok: bool, message: str) -> None:
        checks.append({"id": cid, "ok": bool(ok), "message": message})

    add(
        "triangles",
        before["triangles_total"] == after["triangles_total"],
        f"{after['triangles_total']} triangles re-read (source {before['triangles_total']})",
    )
    add(
        "triangles_lod0",
        before["triangles_lod0"] == after["triangles_lod0"],
        f"LOD0 {after['triangles_lod0']} (source {before['triangles_lod0']})",
    )
    b, a = np.array(before["extents_blender_m"]), np.array(after["extents_blender_m"])
    scale = max(float(b.max()), 1e-9)
    ok = bool(np.all(np.abs(a - b) <= rel_tol * scale))
    add(
        "extents",
        ok,
        f"size in metres {a.round(4).tolist()} (source {b.round(4).tolist()}, tolerance {rel_tol:.0%} of the largest side)",
    )
    add(
        "materials",
        len(before["materials"]) == len(after["materials"]),
        f"{len(after['materials'])} materials (source {len(before['materials'])})",
    )
    src_nm = sum(1 for m in before["materials"].values() if m.get("normal_map"))
    dst_nm = sum(1 for m in after["materials"].values() if m.get("normal_map"))
    add("normal_maps", src_nm == dst_nm, f"{dst_nm} normal map(s) wired (source {src_nm})")
    src_bc = sum(1 for m in before["materials"].values() if m.get("base_color_map"))
    dst_bc = sum(1 for m in after["materials"].values() if m.get("base_color_map"))
    add("base_color_maps", src_bc == dst_bc, f"{dst_bc} base-colour map(s) wired (source {src_bc})")
    add(
        "uvs",
        all(o["uv"] for o in after["objects"] if not o["collision"])
        or not all(o["uv"] for o in before["objects"] if not o["collision"]),
        "visual meshes keep their UVs",
    )
    return checks


def run_convert(src: str, dst: str, fmt: str, target: str) -> dict:
    reset()
    import_any(src)
    before = inspect()
    skipped = export_as(dst, fmt, target)
    reset()
    import_any(dst)
    after = inspect()
    checks = compare(before, after)
    return {
        "ok": all(c["ok"] for c in checks),
        "format": fmt,
        "target": target,
        "output_bytes": os.path.getsize(dst),
        "skipped_options": skipped,
        "source": before,
        "reimported": after,
        "checks": checks,
    }


VIEWS = {  # name -> (azimuth, elevation) in the Studio convention: azimuth 0 looks at the +Z face from +Z, +Y is up
    "front": (0.0, 5.0),
    "side": (90.0, 5.0),
    "rear": (180.0, 5.0),
    "top": (0.0, 85.0),
    "3q": (40.0, 18.0),
    "3q-rear": (220.0, 18.0),
}


def _to_blender(v):
    """Studio (X right, Y up, Z forward) -> Blender (X right, Y forward, Z up): glTF's own conversion."""
    from mathutils import Vector

    return Vector((v[0], -v[2], v[1]))


def render_views(out_dir: str, views: list[str], size: int, samples: int) -> dict:
    """Beauty renders of the imported asset's LOD0 with Cycles on the CPU (no GPU, no display): real textures, the normal map, PBR lighting."""
    import math

    from mathutils import Vector

    scene = bpy.context.scene
    lo, hi = Vector((1e9,) * 3), Vector((-1e9,) * 3)
    for ob in scene.objects:
        if ob.type != "MESH":
            continue
        visual = not _is_collision(ob.name) and _lod_index(ob.name) in (None, 0)
        ob.hide_render = not visual
        ob.hide_viewport = not visual
        if visual:
            for corner in ob.bound_box:
                w = ob.matrix_world @ Vector(corner)
                lo = Vector([min(lo[i], w[i]) for i in range(3)])
                hi = Vector([max(hi[i], w[i]) for i in range(3)])
    center = (lo + hi) / 2
    radius = max((hi - lo).length / 2, 1e-6)

    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = False
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.image_settings.file_format = "PNG"
    try:
        scene.view_settings.view_transform = "Khronos PBR Neutral"
    except TypeError:
        scene.view_settings.view_transform = "Standard"
    world = bpy.data.worlds.new("aro_world")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.86, 0.87, 0.9, 1.0)
    bg.inputs[
        "Strength"
    ].default_value = 0.35  # soft fill: a strong bright world turns every grazing facet into Fresnel sheen
    scene.world = world

    sun = bpy.data.lights.new("aro_sun", "SUN")
    sun.energy = 4.0
    sun_ob = bpy.data.objects.new("aro_sun", sun)
    scene.collection.objects.link(sun_ob)
    sun_ob.rotation_euler = (math.radians(50), 0, math.radians(35))

    cam_data = bpy.data.cameras.new("aro_cam")
    cam_data.lens = 70
    cam_data.sensor_width = 36
    cam = bpy.data.objects.new("aro_cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    target = bpy.data.objects.new("aro_target", None)
    scene.collection.objects.link(target)
    target.location = center
    track = cam.constraints.new("TRACK_TO")
    track.target = target
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"
    dist = radius / math.tan(math.atan(36 / (2 * 70))) * 1.25

    os.makedirs(out_dir, exist_ok=True)
    written = []
    for name in views:
        az, el = VIEWS[name]
        a, e = math.radians(az), math.radians(el)
        # Studio-frame direction towards the camera, converted to Blender axes; centre/radius are already in Blender axes
        direction = _to_blender((math.sin(a) * math.cos(e), math.sin(e), math.cos(a) * math.cos(e)))
        cam.location = center + direction * dist
        bpy.context.view_layer.update()
        path = os.path.join(out_dir, f"blender-{name}.png")
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        written.append(path)
    return {
        "ok": True,
        "images": written,
        "engine": "CYCLES (CPU)",
        "samples": samples,
        "size": size,
        "blender": bpy.app.version_string,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("inspect")
    i.add_argument("--in", dest="src", required=True)
    i.add_argument("--probe", type=int, default=0, help="also sample the base-colour texture at this many UV corners")
    c = sub.add_parser("convert")
    c.add_argument("--in", dest="src", required=True)
    c.add_argument("--out", dest="dst", required=True)
    c.add_argument("--format", required=True, choices=["fbx", "usd", "blend", "obj"])
    c.add_argument("--target", default="unity", choices=["unity", "unreal", "generic"])
    r = sub.add_parser("render")
    r.add_argument("--in", dest="src", required=True)
    r.add_argument("--out-dir", required=True)
    r.add_argument("--views", default="front,side,rear,top,3q")
    r.add_argument("--size", type=int, default=640)
    r.add_argument("--samples", type=int, default=24)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "inspect":
            reset()
            import_any(a.src)
            result: dict = {"ok": True, **inspect()}
            if a.probe:
                result["probe"] = texture_probe(a.probe)
        elif a.cmd == "render":
            reset()
            import_any(a.src)
            result = render_views(a.out_dir, [v for v in a.views.split(",") if v in VIEWS], a.size, a.samples)
        else:
            result = run_convert(a.src, a.dst, a.format, a.target)
        print(RESULT_TAG + json.dumps(result))
        return 0
    except Exception as e:  # noqa: BLE001 - reported to the Studio, which decides what to tell the user
        print(
            RESULT_TAG
            + json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]})
        )
        return 2


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    sys.exit(main(args))
