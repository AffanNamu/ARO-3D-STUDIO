"""Asset library taxonomy (spec §7, §58). Leaf ids are stored in ``assets.category``."""

from __future__ import annotations

from dataclasses import dataclass

from aro_studio.core.errors import InvalidInputError


@dataclass(frozen=True)
class Category:
    id: str
    label: str
    group: str
    available: bool = True  # False = reserved for the future; not creatable


_C = Category
CATEGORIES: list[Category] = [
    _C("heavy_truck", "Heavy Trucks", "vehicles"),
    _C("medium_truck", "Medium Trucks", "vehicles"),
    _C("light_truck", "Light Trucks", "vehicles"),
    _C("bus", "Buses", "vehicles"),
    _C("car", "Cars", "vehicles"),
    _C("suv", "SUVs", "vehicles"),
    _C("pickup", "Pickups", "vehicles"),
    _C("special_vehicle", "Special Vehicles", "vehicles"),
    _C("emergency_vehicle", "Emergency Vehicles", "vehicles"),
    _C("service_vehicle", "Service Vehicles", "vehicles"),
    _C("building", "Buildings", "environment"),
    _C("road", "Roads", "environment"),
    _C("bridge", "Bridges", "environment"),
    _C("sign", "Signs", "environment"),
    _C("street_furniture", "Street Furniture", "environment"),
    _C("prop", "Props", "environment"),
    _C("character", "Characters", "characters", available=False),
    _C("other", "Other", "other", available=True),
]
_BY_ID = {c.id: c for c in CATEGORIES}
GROUP_LABELS = {"vehicles": "Vehicles", "environment": "Environment", "characters": "Characters", "other": "Other"}


def get_category(category_id: str) -> Category:
    c = _BY_ID.get(category_id)
    if c is None:
        raise InvalidInputError(
            f"Unknown asset category '{category_id}'.",
            recommended_action="Choose one of: " + ", ".join(sorted(_BY_ID)),
        )
    return c


def require_creatable(category_id: str) -> Category:
    c = get_category(category_id)
    if not c.available:
        raise InvalidInputError(
            f"Category '{c.label}' is reserved for a future release and cannot be used yet.",
            recommended_action="Use 'Other' for now.",
        )
    return c


def is_vehicle(category_id: str) -> bool:
    return get_category(category_id).group == "vehicles"


def tree() -> list[dict]:
    out = []
    for g, label in GROUP_LABELS.items():
        out.append(
            {
                "group": g,
                "label": label,
                "categories": [
                    {"id": c.id, "label": c.label, "available": c.available} for c in CATEGORIES if c.group == g
                ],
            }
        )
    return out
