"""Import existing meshes (GLB / glTF / OBJ / PLY / STL, or a zip) as a RAW version (spec §35)."""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

import numpy as np
import trimesh

from aro_studio.core.errors import InvalidInputError
from aro_studio.core.tm import vertex_colors
from aro_studio.materials.library import make_material
from aro_studio.scene.model import PartDef, Provenance, SceneManifest
from aro_studio.scene.store import Scene
from aro_studio.security.archives import safe_extract_zip
from aro_studio.security.filenames import sanitize_filename
from aro_studio.security.uploads import MESH_EXTENSIONS, looks_like_text_mesh, sniff


def _unique(name: str, used: set[str]) -> str:
    base = sanitize_filename(name, default="Part").rsplit(".", 1)[0][:48] or "Part"
    cand, i = base, 1
    while cand in used:
        i += 1
        cand = f"{base}_{i}"
    used.add(cand)
    return cand


def import_mesh_bytes(
    data: bytes,
    filename: str,
    *,
    name: str,
    category: str,
    max_bytes: int,
    max_archive_members: int = 2000,
    max_archive_mb: int = 1000,
) -> tuple[Scene, dict]:
    if not data:
        raise InvalidInputError("The uploaded file is empty.")
    if len(data) > max_bytes:
        raise InvalidInputError(f"File is {len(data) / 1e6:.1f} MB; the import limit is {max_bytes / 1e6:.0f} MB.")
    ext = Path(sanitize_filename(filename, default="mesh.glb")).suffix.lower()
    kind = sniff(data).kind
    report: dict = {"source_filename": sanitize_filename(filename), "warnings": []}
    with tempfile.TemporaryDirectory(prefix="import_") as td:
        work = Path(td)
        if kind == "zip":
            extracted = safe_extract_zip(
                _write(work / "in.zip", data),
                work / "x",
                max_members=max_archive_members,
                max_uncompressed=max_archive_mb * 1_000_000,
            )
            cands = [p for p in extracted if p.suffix.lower() in MESH_EXTENSIONS]
            if not cands:
                raise InvalidInputError(
                    "The archive contains no supported mesh file.",
                    recommended_action="Include a .glb, .obj, .ply or .stl file.",
                )
            target = sorted(cands, key=lambda p: p.stat().st_size, reverse=True)[0]
            if len(cands) > 1:
                report["warnings"].append(f"Archive had {len(cands)} meshes; imported the largest ({target.name}).")
            ftype = target.suffix.lower().lstrip(".")
            payload = target
        else:
            if ext not in MESH_EXTENSIONS:
                raise InvalidInputError(
                    f"Unsupported mesh type '{ext or 'unknown'}'.",
                    recommended_action="Use .glb, .gltf, .obj, .ply or .stl.",
                )
            if kind == "glb" and ext != ".glb":
                ext = ".glb"
            if kind not in ("glb", "unknown") and kind != "zip":
                raise InvalidInputError("The file content does not match a mesh format.")
            if ext in (".obj", ".gltf") and not looks_like_text_mesh(data):
                raise InvalidInputError("The file is not a valid text mesh.")
            if ext == ".glb" and kind != "glb":
                raise InvalidInputError("The file is not a valid GLB (bad magic header).")
            ftype = ext.lstrip(".")
            payload = _write(work / f"in{ext}", data)
        try:
            loaded = trimesh.load(str(payload), file_type=ftype, process=False, force="scene")
        except Exception as e:  # noqa: BLE001
            raise InvalidInputError(
                f"The mesh could not be parsed: {type(e).__name__}.",
                recommended_action="Re-export the model and try again.",
            ) from e
    parts: list[PartDef] = []
    meshes: dict[str, trimesh.Trimesh] = {}
    used: set[str] = set()
    mats: dict[str, object] = {}
    dumped = loaded.dump(concatenate=False) if isinstance(loaded, trimesh.Scene) else [loaded]
    for m in dumped:
        if not isinstance(m, trimesh.Trimesh) or len(m.faces) == 0:
            continue
        pname = _unique(str(m.metadata.get("name") or m.metadata.get("node") or "Part"), used)
        mat_name = None
        vis = m.visual
        mat = getattr(vis, "material", None)
        if mat is not None and hasattr(mat, "baseColorFactor") and mat.baseColorFactor is not None:
            col = tuple(float(x) / 255.0 for x in np.asarray(mat.baseColorFactor)[:4])
            mat_name = _unique(str(getattr(mat, "name", None) or f"{pname}_mat"), set(mats))
            mats[mat_name] = make_material(
                mat_name,
                "generic",
                base_color=col,
                metallic=float(getattr(mat, "metallicFactor", 0.0) or 0.0),
                roughness=float(
                    getattr(mat, "roughnessFactor", 0.6) if getattr(mat, "roughnessFactor", None) is not None else 0.6
                ),
            )
            if getattr(mat, "baseColorTexture", None) is not None:
                report["warnings"].append(
                    f"Texture on '{pname}' was not imported (textures are re-created in the texture stage)."
                )
        mesh = trimesh.Trimesh(np.asarray(m.vertices, dtype=np.float64), np.asarray(m.faces), process=False)
        if (vc := vertex_colors(m)) is not None:
            mesh.visual = trimesh.visual.ColorVisuals(mesh=mesh, vertex_colors=vc)
        meshes[pname] = mesh
        parts.append(PartDef(name=pname, component="body", material=mat_name, mesh_file=""))
    if not meshes:
        raise InvalidInputError("The file contains no triangle geometry.")
    if len(meshes) > 400:
        raise InvalidInputError(f"The file has {len(meshes)} parts; the limit is 400.")
    default = make_material("raw_surface", "generic", base_color=(1.0, 1.0, 1.0, 1.0), roughness=0.8)
    materials = list(mats.values())
    if any(p.material is None for p in parts):
        materials.append(default)
        for p in parts:
            p.material = p.material or default.name
    man = SceneManifest(
        name=name,
        category=category,
        parts=parts,
        materials=materials,
        provenance=Provenance(source="import", note=f"Imported from {sanitize_filename(filename)}"),
    )
    sc = Scene(manifest=man, meshes=meshes)
    sc.refresh_counts()
    report.update(parts=len(meshes), triangles=sc.triangle_count, vertices=sc.vertex_count)
    return sc, report


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


_ = io
