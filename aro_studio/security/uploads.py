"""Upload validation by *content* (magic bytes), never by extension or declared MIME type."""

from __future__ import annotations

from dataclasses import dataclass

from aro_studio.core.errors import InvalidInputError

IMAGE_MAGIC = {
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpeg": (b"\xff\xd8\xff",),
    "webp": (b"RIFF",),  # plus WEBP at offset 8
}
MESH_EXTENSIONS = {".glb", ".gltf", ".obj", ".ply", ".stl"}


@dataclass(frozen=True)
class SniffedType:
    kind: str  # png | jpeg | webp | glb | zip | unknown
    mime: str


def sniff(data: bytes) -> SniffedType:
    head = data[:16]
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return SniffedType("png", "image/png")
    if head.startswith(b"\xff\xd8\xff"):
        return SniffedType("jpeg", "image/jpeg")
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return SniffedType("webp", "image/webp")
    if head[:4] == b"glTF":
        return SniffedType("glb", "model/gltf-binary")
    if head[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
        return SniffedType("zip", "application/zip")
    return SniffedType("unknown", "application/octet-stream")


def require_image_bytes(data: bytes, max_bytes: int) -> SniffedType:
    if not data:
        raise InvalidInputError("The uploaded file is empty.", recommended_action="Choose a PNG, JPG or WebP image.")
    if len(data) > max_bytes:
        raise InvalidInputError(
            f"The file is {len(data) / 1e6:.1f} MB, above the {max_bytes / 1e6:.0f} MB limit.",
            recommended_action="Downscale or compress the image and try again.",
        )
    t = sniff(data)
    if t.kind not in ("png", "jpeg", "webp"):
        raise InvalidInputError(
            "The file content is not a PNG, JPEG or WebP image (extension and declared type are ignored).",
            recommended_action="Export the concept as PNG, JPG or WebP.",
        )
    return t


def looks_like_text_mesh(data: bytes) -> bool:
    """Cheap sanity check for OBJ/PLY/glTF-JSON text meshes: must decode as UTF-8 and not contain NULs."""
    sample = data[:4096]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True
