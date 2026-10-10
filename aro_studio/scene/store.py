"""Scene (de)serialisation to an immutable version directory.

Layout of one version directory:
    manifest.json
    parts/<name>.npz            LOD0 visual meshes
    lods/<n>/<name>.npz         LOD n visual meshes
    collision/<name>.npz        hull / custom collision meshes
    textures/<file>.png
    reports/<name>.json         processing / validation reports that produced this version
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from aro_studio.core.errors import InvalidInputError
from aro_studio.core.hashing import canonical_json, sha256_bytes, sha256_file
from aro_studio.scene.model import SceneManifest


def mesh_to_npz(mesh: trimesh.Trimesh, path: Path) -> None:
    arrays: dict[str, np.ndarray] = {
        "vertices": np.asarray(mesh.vertices, dtype=np.float32),
        "faces": np.asarray(mesh.faces, dtype=np.uint32),
    }
    uv = getattr(mesh.visual, "uv", None)
    if uv is not None and len(uv) == len(mesh.vertices):
        arrays["uv"] = np.asarray(uv, dtype=np.float32)
    if mesh.visual.kind == "vertex":
        vc = np.asarray(mesh.visual.vertex_colors, dtype=np.uint8)
        if len(vc) == len(mesh.vertices):
            arrays["vertex_colors"] = vc
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **arrays)  # type: ignore[arg-type]


def npz_to_mesh(path: Path) -> trimesh.Trimesh:
    with np.load(path, allow_pickle=False) as z:  # pickle disabled: files are never executable
        verts = z["vertices"].astype(np.float64)
        faces = z["faces"].astype(np.int64)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        if "uv" in z.files:
            mesh.visual = trimesh.visual.TextureVisuals(uv=z["uv"].astype(np.float64))
        elif "vertex_colors" in z.files:
            mesh.visual = trimesh.visual.ColorVisuals(mesh=mesh, vertex_colors=z["vertex_colors"])
    return mesh


@dataclass
class Scene:
    """In-memory working copy of an asset version. Mutate freely; persist as a *new* version."""

    manifest: SceneManifest
    meshes: dict[str, trimesh.Trimesh] = field(default_factory=dict)  # LOD0 part name -> mesh
    lod_meshes: dict[int, dict[str, trimesh.Trimesh]] = field(default_factory=dict)
    collision_meshes: dict[str, trimesh.Trimesh] = field(default_factory=dict)
    texture_data: dict[str, bytes] = field(default_factory=dict)  # TextureDef.file -> bytes
    reports: dict[str, Any] = field(default_factory=dict)  # name -> JSON-able report, stored under reports/

    def copy(self) -> Scene:
        return Scene(
            manifest=self.manifest.model_copy(deep=True),
            meshes={k: v.copy() for k, v in self.meshes.items()},
            lod_meshes={lv: {k: v.copy() for k, v in d.items()} for lv, d in self.lod_meshes.items()},
            collision_meshes={k: v.copy() for k, v in self.collision_meshes.items()},
            texture_data=dict(self.texture_data),
            reports=json.loads(json.dumps(self.reports, default=str)),
        )

    def combined(self, level: int = 0) -> trimesh.Trimesh:
        src = self.meshes if level == 0 else self.lod_meshes[level]
        meshes = [m for m in src.values() if len(m.faces)]
        if not meshes:
            raise InvalidInputError("The scene has no geometry.")
        return trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0].copy()

    @property
    def triangle_count(self) -> int:
        return int(sum(len(m.faces) for m in self.meshes.values()))

    @property
    def vertex_count(self) -> int:
        return int(sum(len(m.vertices) for m in self.meshes.values()))

    def refresh_counts(self) -> None:
        """Re-sync manifest part/LOD statistics with the actual meshes."""
        for p in self.manifest.parts:
            m = self.meshes.get(p.name)
            if m is not None:
                p.vertex_count, p.triangle_count = len(m.vertices), len(m.faces)
                p.has_uv = getattr(m.visual, "uv", None) is not None
                p.has_vertex_colors = m.visual.kind == "vertex"
        for lod in self.manifest.lods:
            meshes = self.lod_meshes.get(lod.level, {})
            for p in lod.parts:
                m = meshes.get(p.name)
                if m is not None:
                    p.vertex_count, p.triangle_count = len(m.vertices), len(m.faces)
            lod.triangle_count = sum(p.triangle_count for p in lod.parts)
            lod.vertex_count = sum(p.vertex_count for p in lod.parts)
        for c in self.manifest.colliders:
            if c.mesh_file:
                m = self.collision_meshes.get(c.name)
                c.triangle_count = len(m.faces) if m is not None else 0


def part_file(name: str) -> str:
    return f"parts/{name}.npz"


def lod_file(level: int, name: str) -> str:
    return f"lods/{level}/{name}.npz"


def collision_file(name: str) -> str:
    return f"collision/{name}.npz"


def save_scene(scene: Scene, directory: Path) -> str:
    """Write ``scene`` into the *new, empty* ``directory`` and return the manifest sha256.

    Refuses to write into a non-empty directory: version directories are immutable.
    """
    directory = Path(directory)
    if directory.exists() and any(directory.iterdir()):
        raise InvalidInputError("Version directory already exists; versions are immutable.")
    directory.mkdir(parents=True, exist_ok=True)
    scene.refresh_counts()
    man = scene.manifest
    for p in man.parts:
        p.mesh_file = part_file(p.name)
        mesh_to_npz(scene.meshes[p.name], directory / p.mesh_file)
    for lod in man.lods:
        for p in lod.parts:
            p.mesh_file = lod_file(lod.level, p.name)
            mesh_to_npz(scene.lod_meshes[lod.level][p.name], directory / p.mesh_file)
    for c in man.colliders:
        if c.mesh_file:
            c.mesh_file = collision_file(c.name)
            mesh_to_npz(scene.collision_meshes[c.name], directory / c.mesh_file)
    for t in man.textures:
        dest = directory / t.file
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(scene.texture_data[t.file])
        t.sha256 = sha256_bytes(scene.texture_data[t.file])
    for rname, rdata in scene.reports.items():
        rp = directory / "reports" / f"{rname}.json"
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(rdata, indent=2, default=str, sort_keys=True), encoding="utf-8")
    man.files = {
        str(f.relative_to(directory)).replace("\\", "/"): sha256_file(f)
        for f in sorted(directory.rglob("*"))
        if f.is_file()
    }
    manifest_json = json.dumps(json.loads(man.model_dump_json()), indent=2, sort_keys=True)
    (directory / "manifest.json").write_text(manifest_json, encoding="utf-8")
    return sha256_bytes(canonical_json(json.loads(man.model_dump_json())).encode())


def load_scene(directory: Path, *, verify: bool = True) -> Scene:
    directory = Path(directory)
    mp = directory / "manifest.json"
    if not mp.is_file():
        raise InvalidInputError("Version manifest is missing.")
    man = SceneManifest.model_validate_json(mp.read_text(encoding="utf-8"))
    if verify:
        for rel, digest in man.files.items():
            f = directory / rel
            if not f.is_file() or sha256_file(f) != digest:
                raise InvalidInputError(
                    f"Version integrity check failed for '{rel}'.",
                    recommended_action="Restore this version from a backup/export.",
                )
    scene = Scene(manifest=man)
    for p in man.parts:
        scene.meshes[p.name] = npz_to_mesh(directory / p.mesh_file)
    for lod in man.lods:
        scene.lod_meshes[lod.level] = {p.name: npz_to_mesh(directory / p.mesh_file) for p in lod.parts}
    for c in man.colliders:
        if c.mesh_file:
            scene.collision_meshes[c.name] = npz_to_mesh(directory / c.mesh_file)
    for t in man.textures:
        scene.texture_data[t.file] = (directory / t.file).read_bytes()
    rdir = directory / "reports"
    if rdir.is_dir():
        for rf in sorted(rdir.glob("*.json")):
            scene.reports[rf.stem] = json.loads(rf.read_text(encoding="utf-8"))
    return scene
