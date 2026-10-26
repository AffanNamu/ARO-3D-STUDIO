"""glTF 2.0 / GLB writer (spec §21).

Produces a node hierarchy that a game can animate directly:
    <Asset>                      root (extras.aro_studio carries the asset metadata)
      Vehicle_Root … rig nodes   (Susp_/Steer_/Spin_/Hinge_/Pivot_/Light_/Attach_)
        <Part>_LOD0 … _LODn      visual meshes (LOD suffix only when the asset has LODs)
      Collision
        COL_*                    primitive colliders (empty nodes + extras) and hull/mesh colliders

Conventions: metres, right-handed, +Y up, +Z forward.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pygltflib as g

from aro_studio.export.shading import shade_split
from aro_studio.scene.model import MaterialDef
from aro_studio.scene.store import Scene
from aro_studio.textures.process import pack_metallic_roughness

_SAFE = re.compile(r"[^A-Za-z0-9_.\-]")


def node_name(name: str) -> str:
    return _SAFE.sub("_", name)[:64]


@dataclass
class ExportOptions:
    include_lods: bool = True
    include_collision: bool = True
    include_rig: bool = True
    lod_levels: list[int] | None = None  # None = all (LOD0 always included)
    visual_lod0: bool = True
    external: bool = False  # True → .gltf + .bin + image files
    hard_edge_angle_deg: float = 35.0
    extras: dict[str, Any] = field(default_factory=dict)
    root_name: str | None = None
    bin_name: str = "model.bin"


class _Buffer:
    def __init__(self) -> None:
        self.data = bytearray()
        self.views: list[g.BufferView] = []
        self.accessors: list[g.Accessor] = []

    def view(self, raw: bytes, target: int | None = None, name: str | None = None) -> int:
        while len(self.data) % 4:
            self.data.append(0)
        off = len(self.data)
        self.data.extend(raw)
        self.views.append(g.BufferView(buffer=0, byteOffset=off, byteLength=len(raw), target=target, name=name))
        return len(self.views) - 1

    def accessor(
        self, arr: np.ndarray, ctype: int, atype: str, target: int, *, minmax: bool = False, normalized: bool = False
    ) -> int:
        vi = self.view(np.ascontiguousarray(arr).tobytes(), target)
        acc = g.Accessor(
            bufferView=vi,
            componentType=ctype,
            count=int(arr.shape[0] if arr.ndim else arr.size),
            type=atype,
            normalized=normalized or None,
        )
        if minmax:
            acc.min, acc.max = arr.min(axis=0).astype(float).tolist(), arr.max(axis=0).astype(float).tolist()
        self.accessors.append(acc)
        return len(self.accessors) - 1


def _png_or_jpeg_mime(fmt: str) -> str:
    return "image/jpeg" if fmt in ("jpeg", "jpg") else "image/png"


class GltfBuilder:
    def __init__(self, scene: Scene, opts: ExportOptions):
        self.scene, self.opts = scene, opts
        self.buf = _Buffer()
        self.gltf = g.GLTF2(asset=g.Asset(version="2.0", generator="ARO 3D Studio"))
        self.gltf.nodes, self.gltf.meshes, self.gltf.materials = [], [], []
        self.gltf.images, self.gltf.textures, self.gltf.samplers = (
            [],
            [],
            [g.Sampler(magFilter=9729, minFilter=9987, wrapS=10497, wrapT=10497)],
        )
        self.mat_index: dict[str, int] = {}
        self.img_index: dict[str, int] = {}
        self.tex_index: dict[str, int] = {}
        self.external_files: dict[str, bytes] = {}  # relative path → bytes (external mode)
        self.extensions: set[str] = set()
        self.stats: dict[str, Any] = {"meshes": 0, "triangles": {}, "nodes": 0}

    # -- images / materials -------------------------------------------------------------------
    def _image(self, key: str, data: bytes, fmt: str, file: str) -> int:
        if key in self.img_index:
            return self.img_index[key]
        if self.opts.external:
            self.external_files[file] = data
            img = g.Image(uri=file, mimeType=_png_or_jpeg_mime(fmt), name=key)
        else:
            vi = self.buf.view(data, None, f"image:{key}")
            img = g.Image(bufferView=vi, mimeType=_png_or_jpeg_mime(fmt), name=key)
        self.gltf.images.append(img)
        self.img_index[key] = len(self.gltf.images) - 1
        return self.img_index[key]

    def _texture(self, key: str, data: bytes, fmt: str, file: str) -> int:
        if key in self.tex_index:
            return self.tex_index[key]
        self.gltf.textures.append(g.Texture(source=self._image(key, data, fmt, file), sampler=0, name=key))
        self.tex_index[key] = len(self.gltf.textures) - 1
        return self.tex_index[key]

    def _tex_data(self, tex_name: str) -> tuple[bytes, str, str] | None:
        t = self.scene.manifest.texture(tex_name)
        if t is None or t.file not in self.scene.texture_data:
            return None
        return self.scene.texture_data[t.file], t.format, t.file

    def _tex_bytes(self, tex_name: str | None) -> bytes | None:
        d = self._tex_data(tex_name) if tex_name else None
        return d[0] if d else None

    def material(self, m: MaterialDef) -> int:
        if m.name in self.mat_index:
            return self.mat_index[m.name]
        pbr = g.PbrMetallicRoughness(
            baseColorFactor=list(m.base_color), metallicFactor=m.metallic, roughnessFactor=m.roughness
        )
        em = list(m.emissive)
        gm = g.Material(
            name=m.name,
            pbrMetallicRoughness=pbr,
            alphaMode=m.alpha_mode,
            doubleSided=m.double_sided or None,
            emissiveFactor=[min(1.0, c) for c in em],
            extras={"aro_category": m.category.value},
        )
        if m.alpha_mode == "MASK":
            gm.alphaCutoff = m.alpha_cutoff
        if m.emissive_strength != 1.0 and max(em) > 0:
            gm.extensions = {"KHR_materials_emissive_strength": {"emissiveStrength": m.emissive_strength}}
            self.extensions.add("KHR_materials_emissive_strength")
        ch = m.textures
        if d := ch.get("base_color") and self._tex_data(ch["base_color"]):
            pbr.baseColorTexture = g.TextureInfo(index=self._texture(ch["base_color"], *d))
        if d := ch.get("normal") and self._tex_data(ch["normal"]):
            gm.normalTexture = g.NormalMaterialTexture(index=self._texture(ch["normal"], *d))
        if d := ch.get("emission") and self._tex_data(ch["emission"]):
            gm.emissiveTexture = g.TextureInfo(index=self._texture(ch["emission"], *d))
            if max(em) <= 0:
                gm.emissiveFactor = [1.0, 1.0, 1.0]
        rough = self._tex_bytes(ch.get("roughness"))
        metal = self._tex_bytes(ch.get("metallic"))
        occ = self._tex_bytes(ch.get("occlusion"))
        if rough or metal or occ:
            packed = pack_metallic_roughness(rough, metal, occ)
            key = f"{m.name}_orm"
            ti = self._texture(key, packed, "png", f"textures/{key}.png")
            if rough or metal:
                pbr.metallicRoughnessTexture = g.TextureInfo(index=ti)
                if rough:
                    pbr.roughnessFactor = 1.0
                if metal:
                    pbr.metallicFactor = 1.0
            if occ:
                gm.occlusionTexture = g.OcclusionTextureInfo(index=ti)
        self.gltf.materials.append(gm)
        self.mat_index[m.name] = len(self.gltf.materials) - 1
        return self.mat_index[m.name]

    # -- meshes -------------------------------------------------------------------------------
    def mesh(self, name: str, mesh, pivot, material: MaterialDef | None) -> int:
        import trimesh

        local = trimesh.Trimesh(np.asarray(mesh.vertices) - np.asarray(pivot), np.asarray(mesh.faces), process=False)
        local.visual = mesh.visual
        s = shade_split(local, self.opts.hard_edge_angle_deg)
        attrs: dict[str, int] = {
            "POSITION": self.buf.accessor(s.positions, g.FLOAT, g.VEC3, g.ARRAY_BUFFER, minmax=True),
            "NORMAL": self.buf.accessor(s.normals, g.FLOAT, g.VEC3, g.ARRAY_BUFFER),
        }
        has_tex = bool(material and material.textures.get("base_color"))
        if s.uv is not None:
            # The Studio's UVs have V pointing UP (v = 0 is the bottom of the image, like OBJ and the baker's `(1 - v) * size` row). glTF's
            # origin is the TOP-left of the image (v grows downward), so V is flipped here. Without this every exported texture is
            # mirrored vertically in any glTF reader (found by re-importing the export into Blender).
            gltf_uv = s.uv.copy()
            gltf_uv[:, 1] = 1.0 - gltf_uv[:, 1]
            attrs["TEXCOORD_0"] = self.buf.accessor(gltf_uv, g.FLOAT, g.VEC2, g.ARRAY_BUFFER)
        if s.colors is not None and not has_tex:
            attrs["COLOR_0"] = self.buf.accessor(s.colors, g.UNSIGNED_BYTE, g.VEC4, g.ARRAY_BUFFER, normalized=True)
        idx = s.indices.reshape(-1)
        if len(s.positions) < 65535:
            ia = self.buf.accessor(idx.astype(np.uint16), g.UNSIGNED_SHORT, g.SCALAR, g.ELEMENT_ARRAY_BUFFER)
        else:
            ia = self.buf.accessor(idx.astype(np.uint32), g.UNSIGNED_INT, g.SCALAR, g.ELEMENT_ARRAY_BUFFER)
        prim = g.Primitive(attributes=g.Attributes(**attrs), indices=ia, mode=g.TRIANGLES)
        if material is not None:
            prim.material = self.material(material)
        self.gltf.meshes.append(g.Mesh(name=name, primitives=[prim]))
        self.stats["meshes"] += 1
        return len(self.gltf.meshes) - 1

    # -- nodes --------------------------------------------------------------------------------
    def node(self, name: str, translation=(0, 0, 0), mesh: int | None = None, extras: dict | None = None) -> int:
        n = g.Node(name=name, mesh=mesh, extras=extras or None)
        t = [float(x) for x in translation]
        if any(abs(x) > 1e-12 for x in t):
            n.translation = t
        n.children = []
        self.gltf.nodes.append(n)
        return len(self.gltf.nodes) - 1

    def add_child(self, parent: int, child: int) -> None:
        self.gltf.nodes[parent].children.append(child)

    def build(self) -> None:
        sc, man, o = self.scene, self.scene.manifest, self.opts
        levels = [0] + [
            lod.level for lod in man.lods if o.include_lods and (o.lod_levels is None or lod.level in o.lod_levels)
        ]
        has_lods = len(levels) > 1
        slug = node_name(o.root_name or man.name.replace(" ", "-"))
        meta = self.asset_metadata(levels)
        root = self.node(slug, extras={"aro_studio": {**meta, **o.extras}})
        rig_nodes: dict[str, int] = {}
        rig_pivot: dict[str, tuple] = {}
        if o.include_rig and man.rig:
            pending = list(man.rig.nodes)
            while pending:
                progressed = False
                for rn in list(pending):
                    if rn.parent is None or rn.parent in rig_nodes:
                        ppiv = rig_pivot.get(rn.parent, (0, 0, 0)) if rn.parent else (0, 0, 0)
                        tr = np.asarray(rn.pivot) - np.asarray(ppiv)
                        extras = {
                            "aro_rig": {
                                "role": rn.role,
                                "axis": list(rn.axis) if rn.axis else None,
                                "limits_deg": list(rn.limits_deg) if rn.limits_deg else None,
                                "part": rn.part,
                            }
                        }
                        idx = self.node(node_name(rn.name), tr, extras=extras)
                        rig_nodes[rn.name], rig_pivot[rn.name] = idx, rn.pivot
                        self.add_child(rig_nodes[rn.parent] if rn.parent else root, idx)
                        pending.remove(rn)
                        progressed = True
                if not progressed:
                    raise ValueError(
                        "Rig hierarchy has a cycle or a missing parent: " + ", ".join(n.name for n in pending)
                    )
        mats = {m.name: m for m in man.materials}
        for lv in levels:
            parts = man.parts if lv == 0 else next(lod for lod in man.lods if lod.level == lv).parts
            meshes = sc.meshes if lv == 0 else sc.lod_meshes[lv]
            lod_def = None if lv == 0 else next(lod for lod in man.lods if lod.level == lv)
            tris = 0
            for p in parts:
                if p.name not in meshes or not len(meshes[p.name].faces):
                    continue
                mesh = meshes[p.name]
                tris += len(mesh.faces)
                nm = node_name(f"{p.name}_LOD{lv}" if has_lods else p.name)
                mi = self.mesh(nm, mesh, p.pivot, mats.get(p.material or ""))
                parent_name = p.parent if (o.include_rig and p.parent in rig_nodes) else None
                ppiv = rig_pivot.get(parent_name, (0, 0, 0)) if parent_name else (0, 0, 0)
                tr = np.asarray(p.pivot) - np.asarray(ppiv)
                ex: dict[str, Any] = {"aro_part": {"component": p.component, "material": p.material}}
                if has_lods:
                    ex["aro_lod"] = {"level": lv, "screen_height": lod_def.screen_height if lod_def else 0.6}
                idx = self.node(nm, tr, mesh=mi, extras=ex)
                self.add_child(rig_nodes[parent_name] if parent_name else root, idx)
            self.stats["triangles"][f"LOD{lv}"] = tris
        if o.include_collision and man.colliders:
            col_root = self.node("Collision", extras={"aro_collision_group": True})
            self.add_child(root, col_root)
            for c in man.colliders:
                ex = {
                    "aro_collider": {
                        "kind": c.kind.value,
                        "purpose": c.purpose,
                        "size": list(c.size) if c.size else None,
                        "radius": c.radius,
                        "height": c.height,
                        "axis": c.axis,
                        "triangles": c.triangle_count,
                    }
                }
                if c.mesh_file and c.name in sc.collision_meshes:
                    mi = self.mesh(node_name(c.name), sc.collision_meshes[c.name], (0, 0, 0), None)
                    idx = self.node(node_name(c.name), (0, 0, 0), mesh=mi, extras=ex)
                else:
                    idx = self.node(node_name(c.name), c.center, extras=ex)
                self.add_child(col_root, idx)
        for n in self.gltf.nodes:
            if not n.children:
                n.children = None
        self.gltf.scenes = [g.Scene(name=slug, nodes=[root])]
        self.gltf.scene = 0
        self.stats["nodes"] = len(self.gltf.nodes)
        self.gltf.bufferViews, self.gltf.accessors = self.buf.views, self.buf.accessors
        if not self.gltf.images:
            self.gltf.images = None
            self.gltf.textures = None
            self.gltf.samplers = None
        if not self.gltf.materials:
            self.gltf.materials = None
        if self.extensions:
            self.gltf.extensionsUsed = sorted(self.extensions)

    def asset_metadata(self, levels: list[int]) -> dict[str, Any]:
        man = self.scene.manifest
        meta: dict[str, Any] = {
            "schema": 1,
            "name": man.name,
            "category": man.category,
            "units": "m",
            "up_axis": "+Y",
            "forward_axis": "+Z",
            "handedness": "right",
            "provenance": man.provenance.model_dump(),
            "lods": [{"level": 0, "screen_height": 0.6}]
            + [
                {"level": lod.level, "screen_height": lod.screen_height, "triangles": lod.triangle_count}
                for lod in man.lods
                if lod.level in levels
            ],
        }
        if man.vehicle:
            meta["vehicle"] = json.loads(man.vehicle.model_dump_json())
        return meta

    def finish_glb(self) -> bytes:
        self.gltf.buffers = [g.Buffer(byteLength=len(self.buf.data))]
        self.gltf.set_binary_blob(bytes(self.buf.data))
        out = self.gltf.save_to_bytes()
        return out if isinstance(out, bytes) else b"".join(out)

    def finish_gltf(self) -> tuple[str, bytes]:
        self.gltf.buffers = [g.Buffer(byteLength=len(self.buf.data), uri=self.opts.bin_name)]
        return self.gltf.to_json(indent=2), bytes(self.buf.data)


def export_glb(scene: Scene, opts: ExportOptions | None = None) -> tuple[bytes, dict]:
    opts = opts or ExportOptions()
    b = GltfBuilder(scene, ExportOptions(**{**opts.__dict__, "external": False}))
    b.build()
    data = b.finish_glb()
    return data, {"format": "glb", "bytes": len(data), **b.stats}


def export_gltf(scene: Scene, opts: ExportOptions | None = None) -> tuple[str, dict[str, bytes], dict]:
    """Return (gltf_json, {relative_path: bytes}, report). Files include the .bin and all images."""
    opts = opts or ExportOptions()
    b = GltfBuilder(scene, ExportOptions(**{**opts.__dict__, "external": True}))
    b.build()
    js, binary = b.finish_gltf()
    files = {opts.bin_name: binary, **b.external_files}
    return js, files, {"format": "gltf", "bytes": len(js) + sum(len(v) for v in files.values()), **b.stats}
