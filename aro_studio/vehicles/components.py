"""Vehicle component roles (spec §16, §42)."""

from __future__ import annotations

from enum import Enum


class ComponentRole(str, Enum):
    CHASSIS = "chassis"
    CABIN = "cabin"
    BODY = "body"
    BUMPER = "bumper"
    GRILLE = "grille"
    DOOR = "door"
    WINDOW = "window"
    MIRROR = "mirror"
    HEADLIGHT = "headlight"
    TAILLIGHT = "taillight"
    EXHAUST = "exhaust"
    AXLE = "axle"
    WHEEL = "wheel"
    TIRE = "tire"
    ATTACHMENT = "attachment"
    WIPER = "wiper"
    INTERIOR = "interior"
    OTHER = "other"


# Roles a heavy truck must provide for the vehicle checks (see validation.rules)
REQUIRED_TRUCK_ROLES = [
    ComponentRole.CHASSIS,
    ComponentRole.CABIN,
    ComponentRole.WHEEL,
    ComponentRole.TIRE,
    ComponentRole.AXLE,
]


def components_from_parts(parts) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for p in parts:
        out.setdefault(p.component, []).append(p.name)
    return out
