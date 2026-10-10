"""Pre-reconstruction image analysis (spec §9).

Analysis ASSISTS the user: nothing here blocks generation. Capabilities that need a neural
classifier/detector (object category, confidence) are exposed through the ``ObjectClassifier``
interface and report ``None`` until such a model is registered - we never invent a category.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field

import numpy as np
from PIL import Image

from aro_studio.imaging.matting import BorderColorMatte, background_stats


@dataclass
class Classification:
    label: str
    confidence: float
    category: str | None = None


class ObjectClassifier(ABC):
    """Future extension point (e.g. CLIP/YOLO). Not implemented: see docs/models/model-registry.md."""

    id: str

    @abstractmethod
    def classify(self, image: Image.Image) -> Classification | None: ...


CLASSIFIERS: dict[str, ObjectClassifier] = {}


@dataclass
class ImageAnalysis:
    background: dict
    background_type: str  # transparent | uniform | complex
    foreground_bbox: tuple[int, int, int, int] | None
    foreground_fraction: float
    subject_aspect: float | None  # bbox width / height
    framing: str  # tight | good | small
    classification: dict | None
    recommendations: list[str] = field(default_factory=list)
    recommended_mode: str = "generic"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def analyze(image: Image.Image, *, declared_category_group: str | None = None) -> ImageAnalysis:
    rgba = image.convert("RGBA")
    alpha = np.asarray(rgba.getchannel("A"))
    has_cutout = bool((alpha < 250).mean() > 0.01)
    bg = background_stats(rgba.convert("RGB"))
    if has_cutout:
        bg_type, mask = "transparent", alpha > 16
    else:
        bg_type = "uniform" if bg["uniform"] else "complex"
        mask = np.asarray(BorderColorMatte().remove(rgba).getchannel("A")) > 16 if bg["uniform"] else None

    bbox, frac, aspect, framing = None, 0.0, None, "unknown"
    if mask is not None and mask.any():
        ys, xs = np.where(mask)
        bbox = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        frac = float(mask.mean())
        bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
        aspect = bw / max(bh, 1)
        edge = max(bbox[0], bbox[1], rgba.width - bbox[2], rgba.height - bbox[3])
        framing = "tight" if min(bbox[0], bbox[1], rgba.width - bbox[2], rgba.height - bbox[3]) <= 2 else ("small" if frac < 0.12 else "good")
        del edge

    cls = None
    for c in CLASSIFIERS.values():
        res = c.classify(image)
        if res:
            cls = asdict(res)
            break

    rec: list[str] = []
    notes: list[str] = []
    if bg_type == "complex":
        rec.append("Cluttered background: use neural background removal (rembg) or supply a cut-out PNG with transparency.")
    elif bg_type == "uniform":
        rec.append("Plain background detected: automatic matting is reliable for this image.")
    else:
        rec.append("Transparent cut-out detected: existing alpha will be used as the subject mask.")
    if framing == "tight":
        rec.append("The subject touches the image border; leave margin so the full silhouette is visible.")
    if framing == "small":
        rec.append("The subject is small in the frame; it will be cropped and enlarged, which can reduce detail.")
    if aspect is not None and aspect > 1.6:
        notes.append("Wide subject (likely a side or three-quarter view) - single-view reconstruction is least reliable on the unseen side.")
    notes.append("Single-image reconstruction invents the hidden sides; use the cleanest three-quarter or side view available.")
    if cls is None:
        notes.append("No object classifier is registered, so the object category is not auto-detected. The asset category you selected is used instead.")

    mode = "vehicle" if declared_category_group == "vehicles" else ("environment" if declared_category_group == "environment" else "generic")
    return ImageAnalysis(
        background=bg, background_type=bg_type, foreground_bbox=bbox, foreground_fraction=round(frac, 4),
        subject_aspect=round(aspect, 3) if aspect else None, framing=framing, classification=cls,
        recommendations=rec, recommended_mode=mode, notes=notes,
    )
