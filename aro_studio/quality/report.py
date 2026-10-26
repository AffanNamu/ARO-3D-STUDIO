"""Inspection sheet for a generated model: reference | outline overlay | best-matching view | five standard views."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from PIL import Image, ImageDraw

from aro_studio.quality import fidelity as fd
from aro_studio.utils.render import render_scene


def load_lod0(path: Path) -> trimesh.Trimesh:
    """The visual LOD0 of an exported GLB (not LOD1-3, not the collision mesh); any other GLB: its largest mesh."""
    scene: Any = trimesh.load(str(path), force="scene")
    cands = {n: scene.geometry[scene.graph[n][1]] for n in scene.graph.nodes_geometry}
    lod0 = [(n, g) for n, g in cands.items() if n.endswith("_LOD0")]
    pool = lod0 or [(n, g) for n, g in cands.items() if not n.startswith("COL_")]
    if not pool:
        raise ValueError(f"{path}: no visual geometry found")
    name, geom = max(pool, key=lambda t: len(t[1].faces))
    mesh = geom.copy()
    mesh.apply_transform(scene.graph[name][0])
    return mesh


def overlay(ref_mask: np.ndarray, render_mask: np.ndarray) -> Image.Image:
    """Reference outline (red) and render outline (green) on the normalised canvas: yellow = agreement."""
    rgb = np.zeros((*ref_mask.shape, 3), dtype=np.uint8)
    rgb[ref_mask & render_mask] = (230, 200, 40)
    rgb[ref_mask & ~render_mask] = (220, 60, 60)
    rgb[~ref_mask & render_mask] = (60, 200, 90)
    return Image.fromarray(rgb)


def make_sheet(
    mesh: trimesh.Trimesh, reference: Image.Image, rep: fd.FidelityReport, path: Path, size: int = 360
) -> None:
    ref_img = reference.convert("RGB")
    ref_norm, _ = fd.normalise_mask(fd.reference_mask(ref_img))
    v, f = np.asarray(mesh.vertices), np.asarray(mesh.faces)
    best, _ = fd.silhouette(v, f, rep.best_azimuth_deg, rep.best_elevation_deg)
    col = (0.80, 0.80, 0.82, 1.0)

    def view(az: float, el: float) -> Image.Image:
        return render_scene([(mesh, col)], azimuth_deg=az, elevation_deg=el, size=size, smooth_shading=True)

    tiles: list[tuple[str, Image.Image]] = [
        ("reference", ref_img.copy()),
        (f"outline overlay  IoU {rep.silhouette_iou:.2f}", overlay(ref_norm, best)),
        (
            f"best view  az {rep.best_azimuth_deg:.0f} el {rep.best_elevation_deg:.0f}",
            view(rep.best_azimuth_deg, rep.best_elevation_deg),
        ),
    ]
    for name, az, el in (("front", 0, 5), ("side", 90, 5), ("rear", 180, 5), ("top", 0, 85), ("3/4", 40, 18)):
        tiles.append((name, view(az, el)))
    cols = 4
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * size, rows * (size + 22)), (250, 250, 250))
    dr = ImageDraw.Draw(sheet)
    for i, (name, im) in enumerate(tiles):
        im = im.convert("RGB")
        im.thumbnail((size, size))
        x, y = (i % cols) * size, (i // cols) * (size + 22)
        dr.text((x + 6, y + 4), name, fill=(0, 0, 0))
        sheet.paste(im, (x + (size - im.width) // 2, y + 22))
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)
