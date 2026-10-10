"""Unity 6 package builder (spec §21-22)."""

from __future__ import annotations

import json
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any

from aro_studio import __version__
from aro_studio.export.gltf import ExportOptions, export_glb, node_name
from aro_studio.export.unity_templates import DESCRIPTOR_CS, IMPORTER_CS, README_TEMPLATE
from aro_studio.export.unity_verifier import VERIFIER_CS
from aro_studio.export.verify import sha256_of
from aro_studio.scene.model import MaterialDef
from aro_studio.scene.store import Scene
from aro_studio.security.filenames import slugify
from aro_studio.textures.pipeline import unity_texture_settings


def _tex_file(man, name: str) -> str | None:
    t = man.texture(name)
    return t.file if t else None


def unity_material_hint(m: MaterialDef) -> dict[str, Any]:
    transparent = m.alpha_mode == "BLEND"
    return {
        "shader_urp": "Universal Render Pipeline/Lit",
        "shader_hdrp": "HDRP/Lit",
        "surface": "Transparent" if transparent else ("Cutout" if m.alpha_mode == "MASK" else "Opaque"),
        "_BaseColor": list(m.base_color),
        "_Metallic": m.metallic,
        "_Smoothness": round(1.0 - m.roughness, 4),
        "_EmissionColor": [c * m.emissive_strength for c in m.emissive],
        "twoSided": m.double_sided,
        "note": "Unity smoothness = 1 - glTF roughness. Packed ORM maps: R=occlusion, G=roughness, B=metallic (HDRP mask map needs repacking).",
    }


def _collider_expectation(scene: Scene, c) -> dict[str, Any]:
    d: dict[str, Any] = {
        "node": node_name(c.name),
        "kind": c.kind.value,
        "center": list(c.center),
        "size": list(c.size) if c.size else None,
        "radius": c.radius or 0.0,
        "height": c.height or 0.0,
        "axis": c.axis,
        "triangles": c.triangle_count,
    }
    cm = scene.collision_meshes.get(c.name)
    if cm is not None and len(cm.faces):
        d["boundsMin"] = [round(float(x), 5) for x in cm.bounds[0]]
        d["boundsMax"] = [round(float(x), 5) for x in cm.bounds[1]]
    return d


def unity_expectations(scene: Scene) -> dict[str, Any]:
    """Ground truth for the Unity-side verifier, computed from the scene (not from the exported glTF).

    All coordinates are in the glTF/package frame (right-handed, +Y up, +Z forward, metres). The verifier applies the
    glTFast X-mirror itself, so a wrong mirror shows up as a mismatch instead of being baked into the expectation.
    """
    man = scene.manifest
    whole = scene.combined()
    parts = []
    for p in man.parts:
        m = scene.meshes.get(p.name)
        if m is None or not len(m.faces):
            continue
        parts.append(
            {
                "node": node_name(p.name),
                "triangles": int(len(m.faces)),
                "boundsMin": [round(float(x), 5) for x in m.bounds[0]],
                "boundsMax": [round(float(x), 5) for x in m.bounds[1]],
                "material": p.material,
            }
        )
    return {
        "schema": 1,
        "frame": "gltf: right-handed, +Y up, +Z forward, metres",
        "boundsMin": [round(float(x), 5) for x in whole.bounds[0]],
        "boundsMax": [round(float(x), 5) for x in whole.bounds[1]],
        "extents": [round(float(x), 5) for x in whole.extents],
        "triangles_lod0": scene.triangle_count,
        "lodTriangles": {
            "0": scene.triangle_count,
            **{str(lv): int(sum(len(m.faces) for m in scene.lod_meshes[lv].values())) for lv in scene.lod_meshes},
        },
        "parts": parts,
        "materials": [m.name for m in man.materials],
        "colliders": [_collider_expectation(scene, c) for c in man.colliders],
        "tolerance": {"length_m": 0.01, "triangle_ratio": 0.0},
    }


def build_unity_package(
    scene: Scene,
    out_dir: Path,
    *,
    asset_id: str,
    version_id: str,
    version_label: str,
    stage: str,
    validation_summary: dict | None = None,
) -> tuple[Path, dict]:
    """Write ``<slug>-Unity/`` under ``out_dir`` and a zip next to it. Returns (zip_path, report)."""
    man = scene.manifest
    slug = slugify(man.name)
    root = out_dir / f"{slug}-Unity"
    if root.exists():
        shutil.rmtree(root)
    for d in ("Models", "Materials", "Textures", "LOD", "Collision", "Metadata", "Editor", "Scripts"):
        (root / d).mkdir(parents=True)
    report: dict[str, Any] = {"files": [], "triangles": {}}

    # Models + LODs + collision
    full, rep = export_glb(scene, ExportOptions(root_name=slug))
    (root / "Models" / f"{slug}.glb").write_bytes(full)
    report["triangles"] = rep["triangles"]
    for lv in man.lod_levels:
        data, _ = export_glb(
            scene,
            ExportOptions(
                root_name=slug, include_lods=lv > 0, lod_levels=[lv] if lv > 0 else None, include_collision=False
            ),
        )
        (root / "LOD" / f"{slug}_LOD{lv}.glb").write_bytes(data)
    if man.colliders:
        from aro_studio.scene.model import SceneManifest
        from aro_studio.scene.store import Scene as _Scene

        only = _Scene(
            manifest=SceneManifest(
                name=man.name, category=man.category, colliders=man.colliders, provenance=man.provenance
            ),
            meshes={},
            collision_meshes=scene.collision_meshes,
        )
        cdata, _ = export_glb(only, ExportOptions(root_name=f"{slug}_collision", include_rig=False))
        (root / "Collision" / f"{slug}_collision.glb").write_bytes(cdata)
    (root / "Collision" / "colliders.json").write_text(
        json.dumps(
            {
                "colliders": [
                    {
                        "name": node_name(c.name),
                        "kind": c.kind.value,
                        "purpose": c.purpose,
                        "center": list(c.center),
                        "size": list(c.size) if c.size else None,
                        "radius": c.radius or 0.0,
                        "height": c.height or 0.0,
                        "axis": c.axis,
                        "triangles": c.triangle_count,
                    }
                    for c in man.colliders
                ]
            },
            indent=2,
        )
    )

    # Textures + materials
    for t in man.textures:
        (root / "Textures" / Path(t.file).name).write_bytes(scene.texture_data[t.file])
    (root / "Materials" / "materials.json").write_text(
        json.dumps(
            {
                "materials": [
                    {
                        "name": m.name,
                        "category": m.category.value,
                        "baseColor": list(m.base_color),
                        "metallic": m.metallic,
                        "roughness": m.roughness,
                        "emissive": list(m.emissive),
                        "emissiveStrength": m.emissive_strength,
                        "alphaMode": m.alpha_mode,
                        "doubleSided": m.double_sided,
                        "textures": {ch: _tex_file(man, tn) for ch, tn in m.textures.items()},
                        "unity": unity_material_hint(m),
                    }
                    for m in man.materials
                ]
            },
            indent=2,
        )
    )
    (root / "Metadata" / "texture_import_settings.json").write_text(
        json.dumps({"textures": unity_texture_settings(scene)}, indent=2)
    )

    # Metadata
    lods = [
        {"level": 0, "screenHeight": 0.6, "triangles": scene.triangle_count, "targetRatio": 1.0, "nodeSuffix": "_LOD0"}
    ] + [
        {
            "level": lod.level,
            "screenHeight": lod.screen_height,
            "triangles": lod.triangle_count,
            "targetRatio": lod.target_ratio,
            "nodeSuffix": f"_LOD{lod.level}",
        }
        for lod in man.lods
    ]
    (root / "Metadata" / "lods.json").write_text(json.dumps({"levels": lods}, indent=2))
    (root / "Metadata" / "unity_expectations.json").write_text(json.dumps(unity_expectations(scene), indent=2))
    if man.vehicle:
        (root / "Metadata" / "vehicle.json").write_text(man.vehicle.model_dump_json(indent=2))
    if man.rig:
        (root / "Metadata" / "rig.json").write_text(man.rig.model_dump_json(indent=2))
    asset_meta = {
        "name": man.name,
        "slug": slug,
        "category": man.category,
        "asset_id": asset_id,
        "version_id": version_id,
        "version_label": version_label,
        "stage": stage,
        "studio_version": __version__,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "conventions": {
            "units": "m",
            "up": "+Y",
            "forward": "+Z",
            "handedness": "right (glTF)",
            "origin": "ground / centreline / wheelbase centre",
        },
        "provenance": man.provenance.model_dump(),
        "triangles": report["triangles"],
        "validation": validation_summary,
        "unity_import_verified": False,
        "identity": man.vehicle.identity.model_dump() if man.vehicle else None,
    }
    (root / "Metadata" / "asset.json").write_text(json.dumps(asset_meta, indent=2))
    if validation_summary:
        (root / "Metadata" / "validation_report.json").write_text(json.dumps(validation_summary, indent=2))

    # Docs + scripts
    readiness = validation_summary["status"] if validation_summary else "not validated"
    prov = man.provenance
    (root / "README.md").write_text(
        README_TEMPLATE.format(
            title=man.name,
            studio_version=__version__,
            date=time.strftime("%Y-%m-%d", time.gmtime()),
            asset_id=asset_id,
            version_label=version_label,
            version_id=version_id,
            stage=stage,
            provenance=prov.source,
            provenance_note=f" {prov.note}" if prov.note else "",
            readiness=readiness,
            slug=slug,
        ),
        encoding="utf-8",
    )
    (root / "Editor" / "AroAssetImporter.cs").write_text(IMPORTER_CS, encoding="utf-8")
    (root / "Editor" / "AroUnityVerifier.cs").write_text(VERIFIER_CS, encoding="utf-8")
    (root / "Scripts" / "AroVehicleDescriptor.cs").write_text(DESCRIPTOR_CS, encoding="utf-8")

    # Checksums (sorted, stable)
    lines = [
        f"{sha256_of(f)}  {f.relative_to(root).as_posix()}"
        for f in sorted(root.rglob("*"))
        if f.is_file() and f.name != "checksums.sha256"
    ]
    (root / "Metadata" / "checksums.sha256").write_text("\n".join(lines) + "\n")

    zip_path = out_dir / f"{slug}-Unity-{version_label}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(root.rglob("*")):
            if f.is_file():
                zf.write(f, f"{root.name}/{f.relative_to(root).as_posix()}")
    report["files"] = [f.relative_to(root).as_posix() for f in sorted(root.rglob("*")) if f.is_file()]
    report["package_dir"] = str(root)
    return zip_path, report
