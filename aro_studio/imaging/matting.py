"""Background removal behind a replaceable interface (spec §4, §8)."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

from aro_studio.core.errors import EngineUnavailableError


class BackgroundRemover(ABC):
    id: str
    name: str

    @abstractmethod
    def available(self) -> tuple[bool, str]:
        """(usable, reason-if-not)."""

    @abstractmethod
    def remove(self, image: Image.Image) -> Image.Image:
        """Return an RGBA image whose alpha is the foreground matte."""


def border_pixels(rgb: np.ndarray, width: int = 4) -> np.ndarray:
    top, bottom = rgb[:width].reshape(-1, 3), rgb[-width:].reshape(-1, 3)
    left, right = rgb[:, :width].reshape(-1, 3), rgb[:, -width:].reshape(-1, 3)
    return np.concatenate([top, bottom, left, right])


def background_stats(image: Image.Image) -> dict:
    """Describe the image border: dominant colour and how uniform it is."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    bp = border_pixels(rgb)
    med = np.median(bp, axis=0)
    dist = np.linalg.norm(bp - med, axis=1)
    return {
        "color": [int(c) for c in med],
        "spread": float(np.percentile(dist, 90)),  # 90th pct distance from median, in 0..441 RGB units
        "uniform": bool(np.percentile(dist, 90) < 18.0),
    }


class BorderColorMatte(BackgroundRemover):
    """Classical matting for plain/studio backgrounds.

    Estimates the background colour from the image border, marks pixels whose colour differs, and keeps
    only background that is *connected to the border* so interior regions that happen to share the
    background colour (e.g. white windows) are kept. Works for uniform backgrounds; it is NOT a general
    segmentation model - use RembgRemover (or a future segmentation engine) for cluttered scenes.
    """

    id = "border_color_matte"
    name = "Border-colour matte (classical)"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def remove(self, image: Image.Image) -> Image.Image:
        rgba = image.convert("RGBA")
        rgb = np.asarray(rgba.convert("RGB"), dtype=np.float32)
        stats = background_stats(rgba)
        dist = np.linalg.norm(rgb - np.array(stats["color"], dtype=np.float32), axis=2)
        thr = max(22.0, stats["spread"] * 2.5 + 8.0)
        bg_candidate = dist < thr
        labels, _n = ndimage.label(bg_candidate)
        border_labels = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
        border_labels = border_labels[border_labels != 0]
        background = np.isin(labels, border_labels)
        fg = ~background
        fg = ndimage.binary_opening(fg, iterations=1)
        fg = ndimage.binary_closing(fg, iterations=2)
        fg = ndimage.binary_fill_holes(fg)
        # keep only the largest connected foreground components (drops speckle)
        lab, n = ndimage.label(fg)
        if n > 1:
            sizes = ndimage.sum(fg, lab, range(1, n + 1))
            keep = [i + 1 for i, s in enumerate(sizes) if s >= 0.02 * sizes.max()]
            fg = np.isin(lab, keep)
        alpha = Image.fromarray((fg * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.0))
        out = rgba.copy()
        out.putalpha(alpha)
        return out


class RembgRemover(BackgroundRemover):
    """Neural matting via the MIT-licensed ``rembg`` package (U^2-Net family). Optional dependency."""

    id = "rembg"
    name = "rembg (U²-Net)"

    def __init__(self) -> None:
        self._session = None

    def available(self) -> tuple[bool, str]:
        try:
            import rembg  # noqa: F401
        except Exception as e:  # noqa: BLE001
            return False, f"'rembg' is not installed ({type(e).__name__}). Install with: pip install rembg onnxruntime"
        return True, ""

    def remove(self, image: Image.Image) -> Image.Image:
        ok, why = self.available()
        if not ok:
            raise EngineUnavailableError(why, recommended_action="Install rembg or choose the 'border_color_matte' remover.")
        import rembg

        if self._session is None:
            self._session = rembg.new_session()
        return rembg.remove(image.convert("RGBA"), session=self._session).convert("RGBA")


REMOVERS: dict[str, BackgroundRemover] = {r.id: r for r in (BorderColorMatte(), RembgRemover())}


def get_remover(remover_id: str) -> BackgroundRemover:
    try:
        return REMOVERS[remover_id]
    except KeyError:
        from aro_studio.core.errors import InvalidInputError

        raise InvalidInputError(f"Unknown background remover '{remover_id}'.", recommended_action=f"Use one of: {sorted(REMOVERS)}") from None
