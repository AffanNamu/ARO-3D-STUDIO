"""Vehicle configuration (spec §16, §42): assign components and attach structured vehicle metadata."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from aro_studio.core.errors import InvalidInputError
from aro_studio.scene.model import VehicleSpec
from aro_studio.scene.store import Scene
from aro_studio.vehicles.components import ComponentRole, components_from_parts


def configure_vehicle(scene: Scene, spec: dict[str, Any] | None, component_map: dict[str, str] | None = None) -> dict:
    """Apply ``component_map`` (part → role) and a ``VehicleSpec`` (validated). Returns a summary.

    Positions must be given in the asset's current coordinate frame (metres, +Y up, +Z forward).
    """
    man = scene.manifest
    changed_roles = {}
    if component_map:
        valid = {r.value for r in ComponentRole}
        for part, role in component_map.items():
            p = man.part(part)
            if p is None:
                raise InvalidInputError(f"Unknown part '{part}' in component map.")
            if role not in valid:
                raise InvalidInputError(
                    f"Unknown component role '{role}'.", recommended_action=f"Use one of {sorted(valid)}."
                )
            p.component = role
            changed_roles[part] = role
        for lod in man.lods:
            for lp in lod.parts:
                if lp.name in changed_roles:
                    lp.component = changed_roles[lp.name]
    if spec is not None:
        try:
            veh = VehicleSpec.model_validate(spec)
        except ValidationError as e:
            raise InvalidInputError(
                "Vehicle metadata is invalid.",
                recommended_action="; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:5]),
            ) from e
        names = {p.name for p in man.parts}
        axle_names = {a.name for a in veh.axles}
        for w in veh.wheels:
            if w.axle not in axle_names:
                raise InvalidInputError(f"Wheel '{w.name}' references unknown axle '{w.axle}'.")
            for ref in (w.part, w.tire_part):
                if ref and ref not in names:
                    raise InvalidInputError(f"Wheel '{w.name}' references unknown part '{ref}'.")
        for pv in veh.pivots:
            for ref in (pv.part, *pv.children):
                if ref and ref not in names:
                    raise InvalidInputError(f"Pivot '{pv.name}' references unknown part '{ref}'.")
        if veh.wheelbase is None and veh.axles:
            zs = sorted(a.position[2] for a in veh.axles)
            veh.wheelbase = zs[-1] - sum(zs[:-1]) / max(len(zs) - 1, 1) if len(zs) > 1 else None
        man.vehicle = veh
    if man.vehicle is not None:
        man.vehicle.components = components_from_parts(man.parts)
    return {
        "roles_changed": changed_roles,
        "wheels": len(man.vehicle.wheels) if man.vehicle else 0,
        "axles": len(man.vehicle.axles) if man.vehicle else 0,
    }
