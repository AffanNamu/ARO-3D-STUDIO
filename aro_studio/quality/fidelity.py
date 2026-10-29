"""Reference fidelity: how closely does a generated model match the image it was generated from?

A model can be a perfectly valid, manifold, Khronos-clean GLB and still be a lumpy approximation of the picture. These metrics do
not look at file validity at all. They compare the model with the REFERENCE IMAGE:

* ``silhouette_iou``  - the camera (azimuth x elevation) is searched for the view whose orthographic silhouette best overlaps the
  reference cut-out (both normalised to their tight bounding boxes). 1.0 = identical outline. This is sensitive to proportions
  (a stubby truck loses IoU against a long one), missing/extra parts and wrong outlines; it cannot see surface detail or colour.
* ``aspect_error``    - |ln(render aspect / reference aspect)| at that best view: a direct proportion error (0 = same shape ratio).
* ``proportion_check``- length/width/height ratios of the model against explicit, heuristic plausibility bands for the vehicle class.
  The bands are the author's estimates of typical vehicle dimensions, not a standard: they flag implausible results, they do not
  certify correct ones.

IMPORTANT, measured on the first real baselines: the silhouette overlap is BLIND TO DEPTH. A single photo shows one 3/4 view, so a
model whose depth is wrong still reproduces that outline from some camera: TripoSR's truck and SUV score IoU 0.91-0.94 although they are
about 35-60 % too short for their width/height. ``proportion_check`` is therefore the primary criterion for vehicles; IoU is only a sanity
floor (right object, right outline). ``meets_floor`` requires both.

Perspective in the reference photo is not modelled (the render is orthographic), so a perfect model scores < 1.0 against a photo.
Use the numbers to compare engines on the same image, not as an absolute grade. Appearance (texture/colour) and fine detail are NOT
measured here; see docs/architecture/product-reassessment.md for what is measured and what still needs eyes.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import trimesh
from PIL import Image, ImageDraw

SEARCH_FACES = 12_000  # the view search runs on a decimated copy; the final score is re-checked on the full mesh
SIZE = 192
IOU_FLOOR = 0.85  # right object, right outline; says nothing about depth (see the module docstring)

# Heuristic plausibility bands for vehicles in the Studio's canonical frame (X width, Y height, Z length): (min, max) of W/L and H/L.
# Author's estimates from typical dimensions (car ~4.5 x 1.8 x 1.5 m, tractor unit ~6.5 x 2.55 x 3.8 m, 12 m bus ~12 x 2.55 x 3.2 m).
VEHICLE_BANDS: dict[str, dict[str, tuple[float, float]]] = {
    "car": {"width_over_length": (0.34, 0.50), "height_over_length": (0.27, 0.45)},
    "heavy_truck": {"width_over_length": (0.25, 0.46), "height_over_length": (0.40, 0.66)},
    "bus": {"width_over_length": (0.17, 0.28), "height_over_length": (0.22, 0.36)},
}
BAND_ALIASES = {
    "suv": "car",
    "taxi": "car",
    "pickup": "car",
    "van": "car",
    "truck": "heavy_truck",
    "tractor": "heavy_truck",
}


@dataclass
class BestView:
    azimuth_deg: float
    elevation_deg: float
    iou: float
    render_aspect: float  # width / height of the silhouette's tight bounding box
    reference_aspect: float

    @property
    def aspect_error(self) -> float:
        return abs(math.log(max(self.render_aspect, 1e-6) / max(self.reference_aspect, 1e-6)))


@dataclass
class FidelityReport:
    silhouette_iou: float
    aspect_error: float
    best_azimuth_deg: float
    best_elevation_deg: float
    proportions: dict[str, Any]
    mesh: dict[str, Any]
    meets_floor: bool
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# -- reference ---------------------------------------------------------------------------------------------------------
def reference_mask(image: Image.Image) -> np.ndarray:
    """Foreground of the reference image, cut out exactly as the generation path does it (alpha if present, else the Studio matting)."""
    from aro_studio.imaging.preprocess import PreprocessOptions, preprocess

    alpha = np.asarray(preprocess(image, PreprocessOptions()).rgba.convert("RGBA"))[..., 3]
    return alpha > 127


def _tight(mask: np.ndarray) -> tuple[np.ndarray, float]:
    ys, xs = np.where(mask)
    if not len(xs):
        raise ValueError("empty silhouette")
    crop = mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    return crop, crop.shape[1] / crop.shape[0]


def normalise_mask(mask: np.ndarray, size: int = SIZE) -> tuple[np.ndarray, float]:
    """Tight crop, aspect preserved, centred on a size x size canvas. Returns (canvas, width/height of the crop)."""
    crop, aspect = _tight(mask)
    h, w = crop.shape
    s = (size - 2) / max(h, w)
    nw, nh = max(1, round(w * s)), max(1, round(h * s))
    img = Image.fromarray((crop * 255).astype(np.uint8)).resize((nw, nh), Image.Resampling.BILINEAR)
    canvas = Image.new("L", (size, size), 0)
    canvas.paste(img, ((size - nw) // 2, (size - nh) // 2))
    return np.asarray(canvas) > 127, aspect


# -- rendering ---------------------------------------------------------------------------------------------------------
def _basis(az_deg: float, el_deg: float) -> np.ndarray:
    """Camera right/up rows for a camera at (azimuth, elevation) looking at the origin: the same convention as utils.render.render_scene
    (azimuth 0 looks at the +Z face from +Z, +Y up), so an angle found here reproduces the same view in the contact sheet."""
    az, el = math.radians(az_deg), math.radians(el_deg)
    d = np.array([math.sin(az) * math.cos(el), math.sin(el), math.cos(az) * math.cos(el)])  # origin -> camera
    f = -d
    r = np.cross(f, [0.0, 1.0, 0.0])
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    return np.stack([r, u])


def silhouette(
    vertices: np.ndarray, faces: np.ndarray, az_deg: float, el_deg: float, size: int = SIZE
) -> tuple[np.ndarray, float]:
    """Orthographic silhouette from (az, el), normalised like the reference. Returns (canvas, tight-bbox aspect)."""
    xy = vertices @ _basis(az_deg, el_deg).T
    lo, hi = xy.min(axis=0), xy.max(axis=0)
    span = np.maximum(hi - lo, 1e-9)
    big = 4 * size  # draw large, then normalise: keeps thin parts (antennas, mirrors) from vanishing
    s = (big - 2) / span.max()
    px = (xy - lo) * s + 1
    px[:, 1] = (big - 1) - px[:, 1]  # image y points down
    img = Image.new("L", (big, big), 0)
    d = ImageDraw.Draw(img)
    tri = px[faces]
    for t in tri:
        d.polygon([(t[0, 0], t[0, 1]), (t[1, 0], t[1, 1]), (t[2, 0], t[2, 1])], fill=255)
    return normalise_mask(np.asarray(img) > 127, size)


def _search_mesh(mesh: trimesh.Trimesh, max_faces: int = SEARCH_FACES) -> tuple[np.ndarray, np.ndarray]:
    v, f = np.asarray(mesh.vertices, dtype=float), np.asarray(mesh.faces)
    if len(f) > max_faces:
        from aro_studio.geometry import ops

        small, _ = ops.decimate(mesh, target_faces=max_faces)
        v, f = np.asarray(small.vertices, dtype=float), np.asarray(small.faces)
    return v, f


def iou(a: np.ndarray, b: np.ndarray) -> float:
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 0.0


def best_view(
    mesh: trimesh.Trimesh,
    ref_mask: np.ndarray,
    *,
    azimuths: np.ndarray | None = None,
    elevations: tuple[float, ...] = (0.0, 8.0, 16.0, 26.0, 38.0),
    size: int = SIZE,
    search_faces: int = SEARCH_FACES,
    refine: bool = True,
) -> BestView:
    """Coarse-to-fine search over the camera for the best silhouette overlap with the reference cut-out."""
    ref, ref_aspect = normalise_mask(ref_mask, size)
    v, f = _search_mesh(mesh, search_faces)
    best: tuple[float, float, float, float] | None = None  # iou, az, el, aspect

    def consider(az: float, el: float) -> None:
        nonlocal best
        m, aspect = silhouette(v, f, az, el, size)
        score = iou(m, ref)
        if best is None or score > best[0]:
            best = (score, az, el, aspect)

    for az in azimuths if azimuths is not None else np.arange(0, 360, 10):
        for el in elevations:
            consider(float(az), float(el))
    assert best is not None
    if refine:
        _, az0, el0, _ = best
        for az in np.arange(az0 - 8, az0 + 8.1, 2.0):
            for el in np.arange(max(-5.0, el0 - 6), el0 + 6.1, 3.0):
                consider(float(az % 360), float(el))
    assert best is not None
    return BestView(best[1], best[2], best[0], best[3], ref_aspect)


# -- native frame ------------------------------------------------------------------------------------------------------
# Rotation that carries a candidate "up" axis of the mesh onto +Y (the Studio's up axis).
_UP_TO_Y: dict[str, np.ndarray] = {
    "+Y": np.eye(3),
    "-Y": np.diag([-1.0, -1.0, 1.0]),
    "+Z": np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]]),  # Rx(-90 deg)
    "-Z": np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]]),  # Rx(+90 deg)
    "+X": np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]),  # Rz(+90 deg)
    "-X": np.array([[0.0, 1.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]),  # Rz(-90 deg)
}


def detect_up_axis(
    mesh: trimesh.Trimesh,
    ref_mask: np.ndarray,
    *,
    hint: str | None = None,
    margin: float = 0.03,
) -> dict[str, Any]:
    """Which native axis of ``mesh`` is up, judged by which orientation makes the model's silhouette match the reference cut-out best.

    The photo is a roughly level view of an upright object, so the right axis gives a clearly higher best-view IoU than the five wrong
    ones. ``confident`` is False when the winner leads the runner-up by less than ``margin`` (symmetric shapes, bad cut-out): the
    caller should then keep its engine hint. Cheap on purpose (coarse grid, small canvas, decimated copy).
    """
    v0, f0 = _search_mesh(mesh, 5_000)
    coarse: dict[str, BestView] = {}
    rotated_meshes: dict[str, trimesh.Trimesh] = {}
    for axis, rot in _UP_TO_Y.items():
        rotated = trimesh.Trimesh(v0 @ rot.T, f0, process=False)
        rotated_meshes[axis] = rotated
        coarse[axis] = best_view(
            rotated,
            ref_mask,
            azimuths=np.arange(0, 360, 20),
            elevations=(4.0, 18.0, 32.0),
            size=96,
            search_faces=len(f0),
            refine=False,
        )
    scores = {axis: bv.iou for axis, bv in coarse.items()}
    # the coarse grid can leave the right axis only slightly ahead; give the best three a fine search around their own best camera
    for axis in sorted(scores, key=lambda k: -scores[k])[:3]:
        c = coarse[axis]
        fine = best_view(
            rotated_meshes[axis],
            ref_mask,
            azimuths=np.arange(c.azimuth_deg - 20, c.azimuth_deg + 20.1, 5.0) % 360,
            elevations=tuple(np.clip(np.arange(c.elevation_deg - 12, c.elevation_deg + 12.1, 4.0), -5.0, 60.0)),
            size=128,
            search_faces=len(f0),
            refine=False,
        )
        scores[axis] = max(fine.iou, c.iou)
    scores = {k: round(v, 4) for k, v in scores.items()}
    order = sorted(scores, key=lambda k: -scores[k])
    lead = scores[order[0]] - scores[order[1]]
    chosen = order[0] if lead >= margin or hint is None else hint
    return {
        "up": chosen,
        "best_by_silhouette": order[0],
        "scores": scores,
        "lead": round(lead, 4),
        "confident": lead >= margin,
        "used_hint": chosen != order[0],
    }


# -- proportions -------------------------------------------------------------------------------------------------------
def proportion_check(extents_xyz: tuple[float, float, float], category: str) -> dict[str, Any]:
    """Ratios in the canonical frame (X width, Y height, Z length) against the heuristic band of the vehicle class."""
    w, h, length = (float(x) for x in extents_xyz)
    ratios = {"width_over_length": w / max(length, 1e-9), "height_over_length": h / max(length, 1e-9)}
    key = BAND_ALIASES.get(category, category)
    band = VEHICLE_BANDS.get(key)
    out: dict[str, Any] = {
        "ratios": {k: round(v, 3) for k, v in ratios.items()},
        "class": key if band else None,
        "bands_are_heuristic": True,
    }
    if band is None:
        out["verdict"] = "not_applicable"
        return out
    inside = {k: band[k][0] <= ratios[k] <= band[k][1] for k in band}
    out["bands"] = {k: list(v) for k, v in band.items()}
    out["inside"] = inside
    out["verdict"] = "plausible" if all(inside.values()) else "implausible"
    return out


# -- scoring -----------------------------------------------------------------------------------------------------------
def component_count(mesh: trimesh.Trimesh) -> int:
    """Face-connected components, counted on the adjacency graph.

    NOT ``len(mesh.split())``: split() builds a submesh per component and every one of them copies the texture image. On a textured
    model with a few hundred loose fragments that is gigabytes (Colab, 2026-10-29: 9.3 GB, killed by the 12.7 GB limit)."""
    if len(mesh.faces) == 0:
        return 0
    return len(trimesh.graph.connected_components(mesh.face_adjacency, nodes=np.arange(len(mesh.faces)), min_len=1))


def mesh_summary(mesh: trimesh.Trimesh) -> dict[str, Any]:
    uv = getattr(mesh.visual, "uv", None)
    return {
        "triangles": int(len(mesh.faces)),
        "vertices": int(len(mesh.vertices)),
        "watertight": bool(mesh.is_watertight),
        "components": component_count(mesh) if len(mesh.faces) < 400_000 else None,
        "has_uv": uv is not None,
        "extents": [round(float(x), 4) for x in mesh.extents],
    }


def score_model(mesh: trimesh.Trimesh, reference: Image.Image, category: str = "other") -> FidelityReport:
    ref = reference_mask(reference)
    bv = best_view(mesh, ref)
    e = mesh.extents
    prop = proportion_check((float(e[0]), float(e[1]), float(e[2])), category)
    notes = [
        "orthographic silhouette vs a perspective photo: compare engines on the SAME image, not against 1.0",
        "surface detail, colour and texture are not measured by this score",
    ]
    floor = bv.iou >= IOU_FLOOR and prop["verdict"] != "implausible"
    return FidelityReport(
        round(bv.iou, 4),
        round(bv.aspect_error, 4),
        bv.azimuth_deg,
        bv.elevation_deg,
        prop,
        mesh_summary(mesh),
        floor,
        notes,
    )
