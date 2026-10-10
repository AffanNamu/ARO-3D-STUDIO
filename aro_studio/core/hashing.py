"""Content hashing and deterministic cache keys (spec §32)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

_CHUNK = 1024 * 1024


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(obj: Any) -> str:
    """Stable JSON: sorted keys, no whitespace, floats rendered deterministically."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def generation_cache_key(input_image_sha256: str, engine_id: str, model_version: str, settings: dict) -> str:
    """Deterministic key: input image hash + model version + generation settings."""
    payload = canonical_json(
        {"image": input_image_sha256, "engine": engine_id, "model_version": model_version, "settings": settings}
    )
    return sha256_bytes(payload.encode())
