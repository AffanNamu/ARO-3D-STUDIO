"""Stable, prefixed identifiers. Entities are never addressed by filename alone."""

from __future__ import annotations

import re
import uuid

PREFIXES = {
    "project": "prj",
    "asset": "ast",
    "version": "ver",
    "generation": "gen",
    "job": "job",
    "export": "exp",
    "validation": "val",
    "processing": "prc",
    "audit": "aud",
}
_ID_RE = re.compile(r"^(prj|ast|ver|gen|job|exp|val|prc|aud)_[0-9a-f]{20}$")


def new_id(kind: str) -> str:
    """Return a new random id such as ``prj_3f2a...`` (80 bits of randomness)."""
    return f"{PREFIXES[kind]}_{uuid.uuid4().hex[:20]}"


def is_valid_id(value: str, kind: str | None = None) -> bool:
    """True if ``value`` is a well-formed id (optionally of ``kind``)."""
    if not isinstance(value, str) or not _ID_RE.match(value):
        return False
    return kind is None or value.startswith(PREFIXES[kind] + "_")


def require_id(value: str, kind: str) -> str:
    """Validate an id received from outside (URL, JSON) before it touches the filesystem."""
    from aro_studio.core.errors import InvalidInputError

    if not is_valid_id(value, kind):
        raise InvalidInputError(f"Malformed {kind} id.", recommended_action=f"Use an id returned by the API.")
    return value
