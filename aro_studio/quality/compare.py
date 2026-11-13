"""Compare models made from the SAME reference image (for example ARO's and Meshy's) on measured facts, side by side.

    python -m aro_studio.quality.compare --reference truck.png --category heavy_truck \\
        --model ARO=aro.glb --model Meshy=meshy.glb --out compare/            [--blind]

Writes ``comparison.png`` (reference + four views of each model, coloured from its own texture), ``comparison.json`` and
``comparison.md``. With ``--blind`` the models are shown as "Model A", "Model B" ... in random order and the key goes to ``key.json``
only, so a person can judge the pictures before knowing which is which.

What is measured, per model (full-detail mesh: the lowest LOD, without collision meshes):

* silhouette IoU against the reference cut-out from the best matching camera angle, and the outline's aspect error. This says whether
  the right object with the right outline was made. It says nothing about depth, surface detail or texture quality;
* proportions (width/length, height/length) with the vehicle plausibility bands where the category has one. Measured on sorted
  horizontal extents, so a model that faces another axis is not penalised;
* triangles, vertices, separate pieces, watertight, UVs, base-colour texture size, levels of detail, collision mesh, file size.

What is NOT measured and needs human eyes: how good the surface and colours look, whether details (mirrors, lights, wheels) are right.
Use ``--blind`` for that judgement. No score here declares a winner.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from PIL import Image, ImageDraw

from aro_studio.quality import fidelity as fd
from aro_studio.utils.render import render_scene

_LOD = re.compile(r"_LOD(\d+)$", re.IGNORECASE)
VIEWS = (
    ("best match", None, None),
    ("3/4 front", 40.0, 18.0),
    ("side", 90.0, 5.0),
    ("rear 3/4", 220.0, 18.0),
    ("top", 0.0, 85.0),
)
GREY = np.array([0.78, 0.78, 0.8], dtype=np.float32)


@dataclass
class Model:
    label: str
    path: Path
    mesh: trimesh.Trimesh
    face_rgb: np.ndarray  # (n_faces, 3) in 0..1
    facts: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------------------------------------------------------ loading
def _texture_of(visual: Any) -> Image.Image | None:
    mat = getattr(visual, "material", None)
    for attr in ("baseColorTexture", "image"):
        img = getattr(mat, attr, None)
        if isinstance(img, Image.Image):
            return img
    return None


def _factor_of(visual: Any) -> np.ndarray:
    mat = getattr(visual, "material", None)
    f = getattr(mat, "baseColorFactor", None)
    if f is None:
        return np.ones(3, dtype=np.float32)
    arr = np.asarray(f, dtype=np.float32)[:3]
    return arr / 255.0 if arr.max() > 1.0 else arr


def face_colours(mesh: trimesh.Trimesh) -> np.ndarray:
    """RGB 0..1 per face: the base-colour texture sampled at each triangle's UV centroid, else vertex/face colours, else grey."""
    n = len(mesh.faces)
    visual: Any = mesh.visual
    try:
        if getattr(visual, "kind", None) == "texture":
            uv = getattr(visual, "uv", None)
            img = _texture_of(visual)
            if uv is not None and img is not None and len(uv) == len(mesh.vertices):
                px = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
                h, w = px.shape[:2]
                c = np.asarray(uv)[np.asarray(mesh.faces)].mean(axis=1)
                x = np.clip((np.mod(c[:, 0], 1.0) * (w - 1)).round().astype(int), 0, w - 1)
                y = np.clip(((1.0 - np.mod(c[:, 1], 1.0)) * (h - 1)).round().astype(int), 0, h - 1)
                return np.clip(px[y, x] * _factor_of(visual), 0, 1)
            return np.tile(np.clip(_factor_of(visual), 0, 1), (n, 1))
        fc = np.asarray(visual.face_colors, dtype=np.float32)[:, :3] / 255.0
        if len(fc) == n:
            return fc
    except Exception:  # noqa: BLE001, S110 - a model without readable colour is still comparable in shape
        pass
    return np.tile(GREY, (n, 1))


def load_model(label: str, path: Path) -> Model:
    """The full-detail model of any GLB/glTF/OBJ: lowest LOD level (or everything if not LOD-named), without COL_* meshes."""
    scene: Any = trimesh.load(str(path), force="scene", process=False)
    parts: list[tuple[str, trimesh.Trimesh, int | None]] = []
    for node in scene.graph.nodes_geometry:
        transform, gname = scene.graph[node]
        g = scene.geometry.get(gname)
        if not isinstance(g, trimesh.Trimesh) or len(g.faces) == 0:
            continue
        name = str(node) if _LOD.search(str(node)) or str(node).upper().startswith("COL_") else str(gname)
        if name.upper().startswith("COL_"):
            continue
        m = g.copy()
        if not np.allclose(transform, np.eye(4)):
            m.apply_transform(transform)
        lod = _LOD.search(name)
        parts.append((name, m, int(lod.group(1)) if lod else None))
    if not parts:
        raise ValueError(f"{path.name}: no mesh geometry")
    levels = sorted({p[2] for p in parts if p[2] is not None})
    keep = [p for p in parts if p[2] is None or (levels and p[2] == levels[0])]
    meshes = [p[1] for p in keep]
    colours = [face_colours(m) for m in meshes]
    verts, faces, off = [], [], 0
    for m in meshes:
        verts.append(np.asarray(m.vertices, dtype=np.float64))
        faces.append(np.asarray(m.faces) + off)
        off += len(m.vertices)
    merged = trimesh.Trimesh(np.vstack(verts), np.vstack(faces), process=False)
    textures = [_texture_of(m.visual) for m in meshes]
    sizes = [t.size for t in textures if t is not None]
    facts = {
        "file": path.name,
        "file_bytes": path.stat().st_size,
        "meshes": len(meshes),
        "lod_levels": len(levels),
        "collision_mesh": any(str(n).upper().startswith("COL_") for n in scene.graph.nodes_geometry)
        or any(str(k).upper().startswith("COL_") for k in scene.geometry),
        "has_uv": any(getattr(m.visual, "uv", None) is not None for m in meshes),
        "texture_px": max(sizes, key=lambda s: s[0] * s[1]) if sizes else None,
    }
    return Model(label, path, merged, np.vstack(colours), facts)


# ------------------------------------------------------------------------------------------------------------------ scoring
def proportions(mesh: trimesh.Trimesh, category: str) -> dict[str, Any]:
    """Y is up (glTF). Length = the longer horizontal extent, width = the shorter one, whatever axis the model faces."""
    ex, ey, ez = (float(x) for x in mesh.extents)
    length, width = max(ex, ez), min(ex, ez)
    return fd.proportion_check((width, ey, length), category)


def score(model: Model, ref_mask: np.ndarray, category: str) -> None:
    bv = fd.best_view(model.mesh, ref_mask)
    summary = fd.mesh_summary(model.mesh)
    model.facts.update(
        silhouette_iou=round(bv.iou, 4),
        aspect_error=round(bv.aspect_error, 4),
        best_view={"azimuth_deg": bv.azimuth_deg, "elevation_deg": bv.elevation_deg},
        proportions=proportions(model.mesh, category),
        triangles=summary["triangles"],
        vertices=summary["vertices"],
        pieces=summary["components"],
        watertight=summary["watertight"],
        extents=summary["extents"],
    )


# ---------------------------------------------------------------------------------------------------------------- the sheet
def _centred(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    m = mesh.copy()
    m.apply_translation(-m.bounds.mean(axis=0))
    return m


def render_views(model: Model, size: int) -> list[tuple[str, Image.Image]]:
    m = _centred(model.mesh)
    best = model.facts.get("best_view") or {}
    out = []
    for name, az, el in VIEWS:
        a = best.get("azimuth_deg", 40.0) if az is None else az
        e = best.get("elevation_deg", 18.0) if el is None else el
        out.append(
            (name, render_scene([(m, model.face_rgb)], azimuth_deg=a, elevation_deg=e, size=size, smooth_shading=True))
        )
    return out


def _line(f: dict[str, Any]) -> str:
    p = f["proportions"]
    verdict = {"plausible": "plausible", "implausible": "IMPLAUSIBLE", "not_applicable": "no band"}.get(
        p.get("verdict", ""), ""
    )
    tex = (
        f"{f['texture_px'][0]}px texture"
        if f.get("texture_px")
        else ("UVs, no texture" if f["has_uv"] else "no texture")
    )
    return (
        f"outline match {f['silhouette_iou']:.2f} | W/L {p['ratios']['width_over_length']:.2f} H/L {p['ratios']['height_over_length']:.2f} "
        f"({verdict}) | {f['triangles']:,} tris, {f['pieces'] if f['pieces'] is not None else '?'} pieces | {tex} | "
        f"LODs {f['lod_levels']}, collision {'yes' if f['collision_mesh'] else 'no'}"
    )


def make_sheet(reference: Image.Image, models: list[Model], path: Path, size: int = 300) -> None:
    head = 34
    rows = len(models) + 1
    cols = len(VIEWS)
    sheet = Image.new("RGB", (cols * size, rows * (size + head)), (250, 250, 250))
    d = ImageDraw.Draw(sheet)
    ref = reference.convert("RGB").copy()
    ref.thumbnail((size * 2, size))
    d.text((8, 8), "Reference image (same input for every model)", fill=(0, 0, 0))
    sheet.paste(ref, (8, head))
    for i, model in enumerate(models, start=1):
        y = i * (size + head)
        d.text((8, y + 4), model.label, fill=(0, 0, 0))
        d.text((8, y + 18), _line(model.facts), fill=(70, 70, 70))
        for j, (name, im) in enumerate(render_views(model, size)):
            sheet.paste(im, (j * size, y + head))
            d.text((j * size + 6, y + head + 4), name, fill=(90, 90, 90))
    sheet.save(path)


def markdown(models: list[Model], category: str, blind: bool) -> str:
    def cell(v: Any) -> str:
        return "—" if v is None else str(v)

    rows = [
        (
            "Outline match vs reference (silhouette IoU, best angle; higher is closer)",
            lambda f: f"{f['silhouette_iou']:.3f}",
        ),
        ("Outline aspect error (lower is closer)", lambda f: f"{f['aspect_error']:.3f}"),
        ("Width / length", lambda f: f"{f['proportions']['ratios']['width_over_length']:.3f}"),
        ("Height / length", lambda f: f"{f['proportions']['ratios']['height_over_length']:.3f}"),
        (f"Proportions for '{category}'", lambda f: f["proportions"].get("verdict", "—")),
        ("Triangles (full-detail model)", lambda f: f"{f['triangles']:,}"),
        ("Separate pieces", lambda f: cell(f["pieces"])),
        ("Watertight", lambda f: "yes" if f["watertight"] else "no"),
        ("UV mapped", lambda f: "yes" if f["has_uv"] else "no"),
        (
            "Base-colour texture",
            lambda f: f"{f['texture_px'][0]}×{f['texture_px'][1]}" if f.get("texture_px") else "none",
        ),
        ("Levels of detail in the file", lambda f: str(f["lod_levels"])),
        ("Collision mesh in the file", lambda f: "yes" if f["collision_mesh"] else "no"),
        ("File size", lambda f: f"{f['file_bytes'] / 1e6:.2f} MB"),
    ]
    out = ["# Model comparison", ""]
    if blind:
        out += ["Blind mode: the key is in key.json. Judge the pictures first, then open it.", ""]
    out += ["| | " + " | ".join(m.label for m in models) + " |", "|---|" + "---|" * len(models)]
    for name, fn in rows:
        out.append(f"| {name} | " + " | ".join(fn(m.facts) for m in models) + " |")
    out += [
        "",
        "## Read this before drawing a conclusion",
        "",
        "* Outline match compares an orthographic silhouette with a perspective photo: compare models on the SAME image, not against 1.0.",
        "* Nothing here measures how good the surface, colours or small details look. Judge `comparison.png` by eye (blind if you can).",
        "* Proportion bands are heuristics for vehicles (car, heavy truck, bus); other categories show 'not_applicable'.",
        "* A higher triangle count is not better in itself: a game asset needs the right count for its role.",
        "* Record each model's settings (engine/model version, quality preset, texture on or off) next to this file.",
    ]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------------------------------------------------- run
def compare(
    reference_path: Path,
    specs: list[tuple[str, Path]],
    category: str,
    out: Path,
    *,
    blind: bool = False,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    if len(specs) < 1:
        raise ValueError("give at least one --model LABEL=PATH")
    labels = [s[0] for s in specs]
    if len(set(labels)) != len(labels):
        raise ValueError("model labels must be unique")
    out.mkdir(parents=True, exist_ok=True)
    reference = Image.open(reference_path)
    ref_mask = fd.reference_mask(reference.convert("RGB"))
    models = [load_model(label, path) for label, path in specs]
    for m in models:
        score(m, ref_mask, category)
    key: dict[str, str] = {}
    if blind:
        order = list(range(len(models)))
        (rng or random.SystemRandom()).shuffle(order)
        models = [models[i] for i in order]
        for i, m in enumerate(models):
            anon = f"Model {chr(ord('A') + i)}"
            key[anon] = m.label
            m.label = anon
        (out / "key.json").write_text(json.dumps(key, indent=2) + "\n")
    make_sheet(reference, models, out / "comparison.png")
    data = {
        "reference": reference_path.name,
        "category": category,
        "blind": blind,
        "models": {m.label: ({k: v for k, v in m.facts.items() if k != "file"} if blind else m.facts) for m in models},
        "not_measured": ["surface detail", "texture and colour quality", "correctness of small parts"],
    }
    (out / "comparison.json").write_text(json.dumps(data, indent=2, default=str) + "\n")
    (out / "comparison.md").write_text(markdown(models, category, blind))
    return data


def _spec(text: str) -> tuple[str, Path]:
    if "=" not in text:
        raise argparse.ArgumentTypeError("use LABEL=PATH, for example ARO=aro.glb")
    label, path = text.split("=", 1)
    p = Path(path).expanduser()
    if not label.strip() or not p.is_file():
        raise argparse.ArgumentTypeError(f"no such model file: {path}")
    return label.strip(), p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reference", required=True, type=Path)
    ap.add_argument("--model", required=True, action="append", type=_spec, help="LABEL=PATH (repeat for each model)")
    ap.add_argument("--category", default="other")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--blind", action="store_true", help="hide which model is which (key in key.json)")
    a = ap.parse_args(argv)
    data = compare(a.reference, a.model, a.category, a.out, blind=a.blind)
    for label, f in data["models"].items():
        print(
            f"{label:<12} outline {f['silhouette_iou']:.3f}  W/L {f['proportions']['ratios']['width_over_length']:.2f}  H/L {f['proportions']['ratios']['height_over_length']:.2f}  {f['triangles']:,} tris"
        )
    print(
        f"\nwrote {a.out / 'comparison.png'}, comparison.md, comparison.json"
        + (", key.json (do not open before judging)" if a.blind else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["compare", "face_colours", "load_model", "main"]
