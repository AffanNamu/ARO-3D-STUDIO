"""Project the REFERENCE IMAGE onto a geometry-only mesh (TripoSG, Hunyuan3D shape, ...), producing per-vertex colours.

Geometry-only engines return grey surfaces. The photo that produced them is the best colour source there is, so it is projected back:

1. **Camera.** The orthographic view whose silhouette best matches the cut-out (``fidelity.best_view``), then the silhouette's tight box is
   fitted onto the cut-out's tight box. A photo is perspective, the model orthographic: near/far parts land a few percent off, which is
   why colours are only taken where the surface faces the camera well and away from the cut-out edge (matte fringe).
2. **Visibility.** A z-buffer over the projected vertices (coarse grid, dilated) removes surface hidden behind nearer surface.
3. **Sampling.** Bilinear colour from the photo for every visible, camera-facing vertex.
4. **Symmetry (optional, default for vehicles).** A vertex the photo cannot see takes the colour of its mirror image about the
   left-right plane (x = centre of the mesh) if that side was seen. Wrong for logos and one-sided decals: they are not invented
   on the far side because the mirror is only used where the near side was actually observed, and the far side is flagged as inferred.
5. **Fill.** What is still unknown (roof, underside) is diffused from coloured neighbours along the mesh.

This is honest texturing, not generation: the unseen side is an inference, reported as such (``coverage``). Replacing it with a
generated back view (multi-view diffusion) is a later step.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import trimesh
from PIL import Image
from scipy import ndimage, sparse
from scipy.spatial import cKDTree

from aro_studio.quality import fidelity as fd

VIS_GRID = 256
FACING_MIN = 0.25  # cos(angle between surface normal and the direction to the camera): ~75 degrees


@dataclass
class ProjectionReport:
    azimuth_deg: float
    elevation_deg: float
    silhouette_iou: float
    seen_fraction: float  # vertices coloured straight from the photo
    mirrored_fraction: float  # vertices coloured from their mirror image
    filled_fraction: float  # vertices coloured by diffusion only
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _view_geometry(az_deg: float, el_deg: float) -> tuple[np.ndarray, np.ndarray]:
    basis = fd._basis(az_deg, el_deg)  # rows: camera right, camera up
    az, el = np.radians(az_deg), np.radians(el_deg)
    towards_camera = np.array([np.sin(az) * np.cos(el), np.sin(el), np.cos(az) * np.cos(el)])
    return basis, towards_camera


def _sample_bilinear(img: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """img (H, W, 3) float, x/y pixel coordinates (centre = integer). Returns (n, 3)."""
    return np.stack(
        [ndimage.map_coordinates(img[..., c], [y, x], order=1, mode="nearest") for c in range(img.shape[2])], axis=1
    )


def _diffuse(mesh: trimesh.Trimesh, colors: np.ndarray, known: np.ndarray, iterations: int = 400) -> np.ndarray:
    """Spread known colours over unknown vertices along mesh edges (frontier averaging). Returns the filled array."""
    n = len(mesh.vertices)
    e = np.asarray(mesh.edges_unique)
    a = sparse.coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n))
    adj = (a + a.T).tocsr()
    colors = colors.copy()
    known = known.copy()
    for _ in range(iterations):
        if known.all():
            break
        w = adj @ known.astype(float)
        frontier = (~known) & (w > 0)
        if not frontier.any():
            break
        acc = adj @ (colors * known[:, None])
        colors[frontier] = acc[frontier] / w[frontier, None]
        known = known | frontier
    if not known.all():  # a disconnected piece the photo never touched: neutral mean rather than black
        colors[~known] = colors[known].mean(axis=0) if known.any() else 128.0
    return colors


def project_reference(
    mesh: trimesh.Trimesh,
    reference: Image.Image,
    *,
    symmetric: bool = True,
    camera: tuple[float, float] | None = None,
) -> tuple[np.ndarray, ProjectionReport]:
    """Per-vertex RGBA (uint8) for ``mesh`` (canonical frame) from the reference image (alpha = cut-out)."""
    rgba = reference.convert("RGBA")
    arr = np.asarray(rgba)
    alpha = arr[..., 3] > 127
    if alpha.sum() < 100:
        raise ValueError("the reference cut-out is empty")
    rgb = arr[..., :3].astype(np.float32)
    h, w = alpha.shape
    ys, xs = np.where(alpha)
    x0, x1, y0, y1 = float(np.min(xs)), float(np.max(xs)), float(np.min(ys)), float(np.max(ys))

    verts = np.asarray(mesh.vertices, dtype=float)
    iou = 0.0
    if camera is None:
        bv = fd.best_view(mesh, alpha)
        az, el, iou = bv.azimuth_deg, bv.elevation_deg, bv.iou
    else:
        az, el = camera
    basis, to_cam = _view_geometry(az, el)
    xy = verts @ basis.T
    lo, hi = xy.min(axis=0), xy.max(axis=0)
    span = np.maximum(hi - lo, 1e-9)
    px = x0 + (xy[:, 0] - lo[0]) / span[0] * (x1 - x0)
    py = y1 - (xy[:, 1] - lo[1]) / span[1] * (y1 - y0)

    # visibility: z-buffer over a coarse grid (dilated so sparse sampling cannot leak hidden surface through)
    depth = verts @ to_cam
    cx = np.clip(((xy[:, 0] - lo[0]) / span[0] * (VIS_GRID - 1)).astype(int), 0, VIS_GRID - 1)
    cy = np.clip(((xy[:, 1] - lo[1]) / span[1] * (VIS_GRID - 1)).astype(int), 0, VIS_GRID - 1)
    zbuf = np.full((VIS_GRID, VIS_GRID), -np.inf)
    np.maximum.at(zbuf, (cy, cx), depth)
    zbuf = ndimage.maximum_filter(zbuf, size=3)
    diag = float(np.linalg.norm(verts.max(axis=0) - verts.min(axis=0)))
    visible = depth >= zbuf[cy, cx] - 0.012 * diag

    normals = np.asarray(mesh.vertex_normals, dtype=float)
    facing = normals @ to_cam
    inside = ndimage.binary_erosion(alpha, iterations=3)
    pxi = np.clip(np.round(px).astype(int), 0, w - 1)
    pyi = np.clip(np.round(py).astype(int), 0, h - 1)
    direct = visible & (facing > FACING_MIN) & inside[pyi, pxi]

    n = len(verts)
    colors = np.zeros((n, 3), dtype=np.float32)
    if direct.any():
        colors[direct] = _sample_bilinear(rgb, px[direct], py[direct])
    known = direct.copy()
    notes: list[str] = []

    mirrored = np.zeros(n, dtype=bool)
    if symmetric and direct.any():
        cx_plane = float((verts[:, 0].min() + verts[:, 0].max()) / 2.0)
        mirror_pos = verts.copy()
        mirror_pos[:, 0] = 2.0 * cx_plane - mirror_pos[:, 0]
        tree = cKDTree(verts[direct])
        dist, idx = tree.query(mirror_pos[~known])
        ok = dist < 0.02 * diag
        src = np.where(direct)[0][idx[ok]]
        todo = np.where(~known)[0][ok]
        colors[todo] = colors[src]
        mirrored[todo] = True
        known[todo] = True
        notes.append(
            "the side the photo cannot see was coloured by mirroring the visible side (an inference, not observed)"
        )

    filled_mask = ~known
    if filled_mask.any():
        colors = _diffuse(mesh, colors, known)
        notes.append("surfaces seen from neither side (roof, underside) were filled by spreading neighbouring colours")

    rgba_out = np.concatenate(
        [np.clip(colors, 0, 255).round().astype(np.uint8), np.full((n, 1), 255, np.uint8)], axis=1
    )
    rep = ProjectionReport(
        azimuth_deg=float(az),
        elevation_deg=float(el),
        silhouette_iou=round(float(iou), 4),
        seen_fraction=round(float(direct.mean()), 4),
        mirrored_fraction=round(float(mirrored.mean()), 4),
        filled_fraction=round(float(filled_mask.mean()), 4),
        notes=notes,
    )
    return rgba_out, rep
