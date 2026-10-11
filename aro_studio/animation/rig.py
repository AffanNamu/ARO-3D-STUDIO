"""Animation / rig preparation (spec §20).

Builds the node hierarchy and pivots a game needs to animate steering, wheel rotation, suspension, doors,
mirrors, wipers, lights and articulated parts. This is *preparation* only - no vehicle physics and no
skeletal animation: every channel is a plain transform node with a documented axis and limit.

Hierarchy (asset space pivots; exporter converts to local transforms):
    Vehicle_Root
      Susp_<axle>                  vertical suspension travel (translation Y)
        Steer_<wheel>              steering about +Y   (steered axles only)
          Spin_<wheel>             wheel rotation about +X
            Wheel_*, Tire_*        parts
      Hinge_Door_* / Pivot_Mirror_* / Pivot_Wiper_* / Pivot_SteeringWheel     (limits in degrees)
      Light_* / Attach_*           empty nodes carrying position + direction
"""

from __future__ import annotations

from aro_studio.core.errors import InvalidInputError
from aro_studio.scene.model import RigNode, RigSpec
from aro_studio.scene.store import Scene

ROOT = "Vehicle_Root"


def build_rig(scene: Scene) -> RigSpec:
    man = scene.manifest
    v = man.vehicle
    if v is None:
        raise InvalidInputError(
            "Rig preparation requires vehicle metadata.",
            recommended_action="Configure the vehicle (axles, wheels) first.",
        )
    names = {p.name for p in man.parts}
    nodes: list[RigNode] = [RigNode(name=ROOT, parent=None, role="root", pivot=(0.0, 0.0, 0.0))]
    parent_of: dict[str, str] = {}
    pivot_of: dict[str, tuple[float, float, float]] = {}

    axle_node = {}
    for a in v.axles:
        n = f"Susp_{a.name}"
        axle_node[a.name] = n
        nodes.append(
            RigNode(name=n, parent=ROOT, role="suspension", pivot=a.position, axis=(0.0, 1.0, 0.0), limits_deg=None)
        )
        if a.name in names:
            parent_of[a.name], pivot_of[a.name] = n, a.position
    for w in v.wheels:
        parent = axle_node.get(w.axle, ROOT)
        if w.steering:
            sn = f"Steer_{w.name}"
            nodes.append(
                RigNode(
                    name=sn,
                    parent=parent,
                    role="steering",
                    pivot=w.position,
                    axis=(0.0, 1.0, 0.0),
                    limits_deg=(-35.0, 35.0),
                )
            )
            parent = sn
        pn = f"Spin_{w.name}"
        nodes.append(RigNode(name=pn, parent=parent, role="wheel_spin", pivot=w.position, axis=(1.0, 0.0, 0.0)))
        for part in (w.part, w.tire_part, *w.detail_parts):
            if part and part in names:
                parent_of[part], pivot_of[part] = pn, w.position
    for pv in v.pivots:
        nodes.append(
            RigNode(
                name=pv.name,
                parent=ROOT,
                role=pv.kind,
                pivot=pv.position,
                axis=pv.axis,
                limits_deg=pv.limits_deg,
                part=pv.part,
            )
        )
        for part in [pv.part, *pv.children]:
            if part and part in names:
                parent_of[part], pivot_of[part] = pv.name, pv.position
    for li in v.lights:
        nodes.append(
            RigNode(name=li.name, parent=ROOT, role="light", pivot=li.position, axis=li.direction, part=li.part)
        )
    for at in v.attachment_points:
        nodes.append(RigNode(name=at.name, parent=ROOT, role="attachment", pivot=at.position, axis=at.direction))

    seen: set[str] = set()
    for node in nodes:
        if node.name in seen or node.name in names:
            raise InvalidInputError(f"Rig node name '{node.name}' collides with another node/part name.")
        seen.add(node.name)

    for p in man.parts:
        p.parent = parent_of.get(p.name, ROOT)
        p.pivot = pivot_of.get(p.name, (0.0, 0.0, 0.0))
    for lod in man.lods:
        base = {p.name: p for p in man.parts}
        for p in lod.parts:
            src = base.get(p.name)
            if src:
                p.parent, p.pivot = src.parent, src.pivot
            else:  # merged static part
                p.parent, p.pivot = ROOT, (0.0, 0.0, 0.0)
    man.rig = RigSpec(nodes=nodes)
    return man.rig
