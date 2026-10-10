"""Image input validation (spec §8). Validates by content; filenames and MIME are ignored."""

from __future__ import annotations

import io
from dataclasses import asdict, dataclass, field

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from scipy import ndimage

from aro_studio.core.errors import InvalidInputError
from aro_studio.security.uploads import require_image_bytes

# Reject decompression bombs before pixel decoding.
Image.MAX_IMAGE_PIXELS = 200_000_000


@dataclass
class ImageReport:
    format: str
    width: int
    height: int
    mode: str
    file_size: int
    exif_orientation: int
    needs_rotation: bool
    has_alpha: bool
    transparent_fraction: float
    frames: int
    sharpness: float  # variance of Laplacian on a normalised grayscale copy
    contrast: float  # std of luminance 0..1
    brightness: float  # mean luminance 0..1
    clipped_fraction: float  # share of pixels at pure black/white
    quality_score: float  # 0..1 heuristic combining the above
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _open(data: bytes) -> Image.Image:
    try:
        im = Image.open(io.BytesIO(data))
        im.load()  # full decode: truncated/corrupt files raise here
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError) as e:
        raise InvalidInputError(
            "The image is corrupt or cannot be decoded.",
            recommended_action="Re-export the image from its source application and upload again.",
            details={"reason": type(e).__name__},
        ) from e
    return im


def load_image(data: bytes, *, max_bytes: int, max_pixels: int, min_side: int) -> tuple[Image.Image, ImageReport]:
    """Validate ``data`` and return the decoded first frame plus a quality report. Raises InvalidInputError."""
    sniffed = require_image_bytes(data, max_bytes)
    # Cheap header read first so absurd dimensions are rejected before a full decode.
    try:
        with Image.open(io.BytesIO(data)) as probe:
            w0, h0 = probe.size
    except Exception as e:  # noqa: BLE001
        raise InvalidInputError("The image header is invalid.", recommended_action="Upload a different file.") from e
    if w0 * h0 > max_pixels:
        raise InvalidInputError(
            f"The image is {w0}x{h0} ({w0 * h0 / 1e6:.0f} MP), above the {max_pixels / 1e6:.0f} MP limit.",
            recommended_action="Downscale the image before uploading.",
        )
    im = _open(data)
    frames = getattr(im, "n_frames", 1)
    if min(im.size) < min_side:
        raise InvalidInputError(
            f"The image is too small ({im.width}x{im.height}); the shortest side must be at least {min_side}px.",
            recommended_action="Provide a higher-resolution concept image.",
        )
    exif_orientation = 1
    try:
        exif_orientation = int(im.getexif().get(0x0112, 1))
    except Exception:  # noqa: BLE001
        pass
    has_alpha = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
    rgba = im.convert("RGBA")
    alpha = np.asarray(rgba.getchannel("A"), dtype=np.float32) / 255.0
    transparent_fraction = float((alpha < 0.05).mean()) if has_alpha else 0.0

    gray_img = ImageOps.exif_transpose(rgba).convert("L")
    scale = 1024 / max(gray_img.size)
    if scale < 1:
        gray_img = gray_img.resize((max(1, int(gray_img.width * scale)), max(1, int(gray_img.height * scale))), Image.LANCZOS)
    g = np.asarray(gray_img, dtype=np.float32) / 255.0
    sharp = float(ndimage.laplace(g).var()) * 1000.0  # scaled for readability
    contrast, brightness = float(g.std()), float(g.mean())
    clipped = float(((g <= 0.004) | (g >= 0.996)).mean())

    warnings: list[str] = []
    if min(im.size) < 512:
        warnings.append("Resolution is below 512px on the short side; reconstruction detail will be limited.")
    if sharp < 0.15:
        warnings.append("The image looks blurry; reconstruction may be soft or distorted.")
    if contrast < 0.06:
        warnings.append("Very low contrast; the subject may not separate from the background.")
    if brightness < 0.08 or brightness > 0.95:
        warnings.append("The image is very dark or very bright; details may be lost.")
    if frames > 1:
        warnings.append(f"Animated/multi-frame image ({frames} frames): only the first frame is used.")
    if exif_orientation != 1:
        warnings.append("EXIF orientation will be applied automatically.")
    if has_alpha and transparent_fraction > 0.97:
        warnings.append("The image is almost entirely transparent.")

    # Heuristic 0..1 score (documented in docs/pipelines/image-to-3d.md). Advisory only.
    score = 1.0
    score -= 0.25 if min(im.size) < 512 else 0.0
    score -= 0.25 if sharp < 0.15 else 0.0
    score -= 0.15 if contrast < 0.06 else 0.0
    score -= 0.15 if (brightness < 0.08 or brightness > 0.95) else 0.0
    score -= 0.10 if clipped > 0.6 else 0.0

    report = ImageReport(
        format=sniffed.kind, width=im.width, height=im.height, mode=im.mode, file_size=len(data),
        exif_orientation=exif_orientation, needs_rotation=exif_orientation != 1, has_alpha=has_alpha,
        transparent_fraction=round(transparent_fraction, 4), frames=frames, sharpness=round(sharp, 4),
        contrast=round(contrast, 4), brightness=round(brightness, 4), clipped_fraction=round(clipped, 4),
        quality_score=round(max(0.0, score), 3), warnings=warnings,
    )
    if im.format and im.format.lower().replace("jpeg", "jpeg") not in (sniffed.kind, "mpo"):
        raise InvalidInputError("The image content does not match its container format.")
    return im, report
