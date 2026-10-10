"""Image preprocessing pipeline (spec §8).

Validation → orientation → background analysis → background removal → cropping → resizing →
normalisation → AI input.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageOps

from aro_studio.imaging.matting import background_stats, get_remover

AI_BACKGROUND = 0.5  # TripoSR expects the subject composited on 50% grey


@dataclass
class PreprocessOptions:
    remove_background: str = "auto"  # auto | none | border_color_matte | rembg
    foreground_ratio: float = 0.85
    output_size: int = 512

    def as_settings(self) -> dict:
        return {"remove_background": self.remove_background, "foreground_ratio": self.foreground_ratio, "output_size": self.output_size}


@dataclass
class PreprocessResult:
    image: Image.Image  # RGB, square, subject on grey: the model input
    rgba: Image.Image  # RGBA cut-out after cropping (for the viewer / debugging)
    steps: list[dict] = field(default_factory=list)
    background: dict = field(default_factory=dict)
    foreground_bbox: tuple[int, int, int, int] | None = None

    def to_model_array(self) -> np.ndarray:
        """Normalised float32 HxWx3 in [0,1]."""
        return np.asarray(self.image, dtype=np.float32) / 255.0


def _bbox(alpha: np.ndarray, thr: int = 16) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(alpha > thr)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def preprocess(image: Image.Image, opts: PreprocessOptions | None = None) -> PreprocessResult:
    opts = opts or PreprocessOptions()
    steps: list[dict] = []

    im = ImageOps.exif_transpose(image) or image
    steps.append({"step": "orientation", "size": list(im.size)})

    rgba = im.convert("RGBA")
    existing_alpha = np.asarray(rgba.getchannel("A"))
    has_cutout = bool((existing_alpha < 250).mean() > 0.01)
    bg = background_stats(rgba.convert("RGB")) if not has_cutout else {"uniform": True, "color": None, "spread": 0.0, "from_alpha": True}
    steps.append({"step": "background_analysis", **bg})

    mode = opts.remove_background
    if mode == "auto":
        mode = "none" if has_cutout else ("border_color_matte" if bg["uniform"] else "rembg")
    if mode == "rembg":
        remover = get_remover("rembg")
        ok, why = remover.available()
        if not ok:
            if bg["uniform"]:
                mode = "border_color_matte"
                steps.append({"step": "background_removal", "note": f"rembg unavailable ({why}); fell back to border-colour matte"})
            else:
                steps.append({"step": "background_removal", "warning": "Cluttered background and no neural matting available; background kept. " + why})
                mode = "none"
    if mode not in ("none",):
        rgba = get_remover(mode).remove(rgba)
        steps.append({"step": "background_removal", "method": mode})
    else:
        steps.append({"step": "background_removal", "method": "none" if not has_cutout else "existing_alpha"})

    alpha = np.asarray(rgba.getchannel("A"))
    bbox = _bbox(alpha) if (alpha < 250).any() else (0, 0, rgba.width, rgba.height)
    if bbox is None:
        bbox = (0, 0, rgba.width, rgba.height)
        steps.append({"step": "crop", "warning": "No foreground found; using full frame."})
    fg = rgba.crop(bbox)
    steps.append({"step": "crop", "bbox": list(bbox), "size": list(fg.size)})

    # Fit the subject into a square canvas so it occupies `foreground_ratio` of it.
    canvas = int(opts.output_size)
    inner = max(1, int(round(canvas * float(np.clip(opts.foreground_ratio, 0.3, 1.0)))))
    scale = inner / max(fg.size)
    new_size = (max(1, round(fg.width * scale)), max(1, round(fg.height * scale)))
    fg = fg.resize(new_size, Image.LANCZOS)
    cutout = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    cutout.paste(fg, ((canvas - new_size[0]) // 2, (canvas - new_size[1]) // 2))
    steps.append({"step": "resize", "canvas": canvas, "subject_size": list(new_size)})

    arr = np.asarray(cutout, dtype=np.float32) / 255.0
    a = arr[:, :, 3:4]
    rgb = arr[:, :, :3] * a + (1.0 - a) * AI_BACKGROUND
    out = Image.fromarray((rgb * 255.0 + 0.5).astype(np.uint8), "RGB")
    steps.append({"step": "normalize", "composite_background": AI_BACKGROUND, "range": [0.0, 1.0]})
    return PreprocessResult(image=out, rgba=cutout, steps=steps, background=bg, foreground_bbox=bbox)
