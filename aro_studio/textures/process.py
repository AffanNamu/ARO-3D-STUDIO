"""Texture processing: resize, compress, mip metadata, PBR channel packing, atlas packing (spec §15)."""

from __future__ import annotations

import io
import math
from dataclasses import dataclass

import numpy as np
from PIL import Image

from aro_studio.core.errors import InvalidInputError
from aro_studio.textures.bake import ALLOWED_RESOLUTIONS


def open_image(data: bytes) -> Image.Image:
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
        return im
    except Exception as e:  # noqa: BLE001
        raise InvalidInputError("Texture could not be decoded.") from e


def encode(img: Image.Image, fmt: str = "png", quality: int = 90) -> bytes:
    buf = io.BytesIO()
    fmt = fmt.lower()
    if fmt in ("jpg", "jpeg"):
        img.convert("RGB").save(buf, "JPEG", quality=int(quality), optimize=True, progressive=True)
    elif fmt == "png":
        img.save(buf, "PNG", optimize=True)
    else:
        raise InvalidInputError("Texture format must be png or jpeg.")
    return buf.getvalue()


def resize_texture(data: bytes, size: int) -> bytes:
    """Resize (square or not: the long side becomes ``size``) with Lanczos; never upscales."""
    if size not in ALLOWED_RESOLUTIONS:
        raise InvalidInputError(f"Resolution must be one of {ALLOWED_RESOLUTIONS}.")
    im = open_image(data)
    scale = size / max(im.size)
    if scale >= 1.0:
        return data
    return encode(
        im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.Resampling.LANCZOS)
    )


def is_power_of_two(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0


def mip_chain(width: int, height: int) -> list[tuple[int, int]]:
    out = [(width, height)]
    while max(out[-1]) > 1:
        w, h = out[-1]
        out.append((max(1, w // 2), max(1, h // 2)))
    return out


def mip_chain_memory_bytes(width: int, height: int, bytes_per_pixel: int = 4) -> int:
    return sum(w * h * bytes_per_pixel for w, h in mip_chain(width, height))


def pack_metallic_roughness(
    roughness: bytes | None,
    metallic: bytes | None,
    occlusion: bytes | None = None,
    *,
    default_roughness: float = 1.0,
    default_metallic: float = 1.0,
) -> bytes:
    """glTF packing: R=occlusion, G=roughness, B=metallic (images resized to the largest input)."""
    imgs = [open_image(b).convert("L") for b in (roughness, metallic, occlusion) if b]
    if not imgs:
        raise InvalidInputError("Nothing to pack.")
    w, h = max(i.width for i in imgs), max(i.height for i in imgs)

    def ch(b: bytes | None, default: float) -> np.ndarray:
        if b is None:
            return np.full((h, w), int(default * 255), dtype=np.uint8)
        return np.asarray(open_image(b).convert("L").resize((w, h), Image.Resampling.LANCZOS))

    arr = np.stack([ch(occlusion, 1.0), ch(roughness, default_roughness), ch(metallic, default_metallic)], axis=-1)
    return encode(Image.fromarray(arr, "RGB"))


@dataclass
class AtlasRect:
    name: str
    x: int
    y: int
    w: int
    h: int


def pack_atlas(
    images: dict[str, Image.Image], max_size: int = 4096, padding: int = 4
) -> tuple[Image.Image, dict[str, AtlasRect]]:
    """Shelf-pack ``images`` into one atlas (<= ``max_size``) and return it with per-image pixel rects."""
    if not images:
        raise InvalidInputError("No images to atlas.")
    items = sorted(images.items(), key=lambda kv: -kv[1].height)
    total_area = sum((im.width + padding) * (im.height + padding) for _, im in items)
    side = max(max(im.width for _, im in items) + padding, 2 ** math.ceil(math.log2(max(16, math.sqrt(total_area)))))
    while side <= max_size:
        x = y = shelf_h = 0
        rects: dict[str, AtlasRect] = {}
        ok = True
        for name, im in items:
            if x + im.width + padding > side:
                x, y, shelf_h = 0, y + shelf_h + padding, 0
            if y + im.height + padding > side or im.width + padding > side:
                ok = False
                break
            rects[name] = AtlasRect(name, x, y, im.width, im.height)
            x += im.width + padding
            shelf_h = max(shelf_h, im.height)
        if ok:
            atlas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            for name, im in items:
                r = rects[name]
                atlas.paste(im.convert("RGBA"), (r.x, r.y))
            return atlas, rects
        side *= 2
    raise InvalidInputError(
        f"The images do not fit in a {max_size}px atlas.",
        recommended_action="Reduce texture sizes or use more atlases.",
    )


def remap_uv_to_atlas(uv: np.ndarray, rect: AtlasRect, atlas_size: int) -> np.ndarray:
    """Map 0..1 UVs of a source texture into the atlas sub-rectangle."""
    uv = np.asarray(uv, dtype=np.float64)
    out = np.empty_like(uv)
    out[:, 0] = (rect.x + uv[:, 0] * rect.w) / atlas_size
    out[:, 1] = 1.0 - (rect.y + (1.0 - uv[:, 1]) * rect.h) / atlas_size
    return out
