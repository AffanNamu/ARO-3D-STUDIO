"""ARO TITAN 480 - original, procedurally authored REFERENCE asset.

Heavy-duty 6x4 cab-over tractor unit by the fictional manufacturer ARO Motors. The design is original:
no real manufacturer's logos, badges, trademarks or distinctive styling are reproduced.

IMPORTANT: this is a hand-parameterised geometric model (boxes, extrusions, revolves). It is NOT an AI
reconstruction and is never labelled as one (provenance.source = "procedural_reference"). Its purpose is
to give the post-reconstruction pipeline (vehicle setup, collision, rig, LOD, validation, export) a real,
structured, correctly-scaled vehicle to run on, and to serve as the reference asset for the Studio.

Conventions: metres, +Y up, +Z forward, +X = vehicle LEFT (LHD cab, right-hand traffic), origin on the ground
at the centre of the wheelbase on the centreline.
"""

from __future__ import annotations

import numpy as np
import trimesh

from aro_studio.materials.library import REFERENCE_MATERIALS
from aro_studio.scene.model import (
    AttachmentPoint,
    AxleDef,
    LightDef,
    PartDef,
    PivotDef,
    Provenance,
    SceneManifest,
    SuspensionPoint,
    VehicleIdentity,
    VehicleSpec,
    WheelDef,
)
from aro_studio.scene.store import Scene
from aro_studio.vehicles import primitives as P
from aro_studio.vehicles.components import ComponentRole as R

TIRE_R, TIRE_W = 0.52, 0.315
RIM_R = 0.30
AXLES = {"Axle_Front": 1.90, "Axle_Rear1": -1.25, "Axle_Rear2": -2.55}  # z of each axle centreline
FRONT_X = 1.04
REAR_INNER_X, REAR_OUTER_X = 0.72, 1.08
CAB_HALF_W = 1.22


def _tire(center) -> trimesh.Trimesh:
    h = TIRE_W / 2
    prof = [
        (RIM_R - 0.02, -h + 0.02),
        (TIRE_R - 0.07, -h),
        (TIRE_R - 0.02, -h + 0.05),
        (TIRE_R, -h + 0.12),
        (TIRE_R, h - 0.12),
        (TIRE_R - 0.02, h - 0.05),
        (TIRE_R - 0.07, h),
        (RIM_R - 0.02, h - 0.02),
    ]
    return P.revolve_x(prof, center)


def _rim(center, outward: float) -> trimesh.Trimesh:
    """Steel disc wheel; the dish faces ``outward`` (+1 / -1 along X)."""
    h = 0.12
    prof = [(0.06, -h), (RIM_R, -h), (RIM_R, h), (0.12, h), (0.12, h - 0.03 * outward), (0.06, h - 0.05)]
    m = P.revolve_x(prof, center, sections=40)
    hub = P.cylinder_x([center[0] + outward * 0.10, center[1], center[2]], 0.07, 0.05, 24)
    return P.merge([m, hub])


def build_titan480(name: str = "ARO TITAN 480") -> Scene:
    parts: list[tuple[str, R, str, trimesh.Trimesh]] = []

    def add(pname: str, role: R, material: str, mesh: trimesh.Trimesh) -> None:
        parts.append((pname, role, material, mesh))

    # --- chassis ---------------------------------------------------------------------------
    rails = [P.box([sx * 0.46, 0.88, -0.45], [0.11, 0.30, 6.1]) for sx in (-1, 1)]
    cross = [P.box([0, 0.86, z], [0.92, 0.12, 0.14]) for z in (2.45, 1.4, 0.2, -1.0, -2.0, -3.2)]
    add("Chassis_Frame", R.CHASSIS, "chassis_steel", P.merge(rails + cross))

    # --- cab ---------------------------------------------------------------------------------
    profile = [(0.20, 1.15), (2.55, 1.15), (2.63, 2.35), (2.22, 3.55), (0.58, 3.62), (0.20, 3.42)]
    add("Cab_Shell", R.CABIN, "body_paint", P.extrude_profile_zy(profile, 2 * CAB_HALF_W))
    add("Roof_Deflector", R.BODY, "body_paint", P.box([0, 3.78, 0.45], [2.1, 0.32, 0.55]))

    # --- front end ---------------------------------------------------------------------------
    add("Bumper_Front", R.BUMPER, "plastic", P.box([0, 0.93, 2.78], [2.34, 0.42, 0.30]))
    add("Grille", R.GRILLE, "plastic", P.box([0, 1.85, 2.66], [1.40, 0.82, 0.07]))
    add(
        "Grille_Trim",
        R.GRILLE,
        "chrome",
        P.merge([P.box([0, 1.55 + 0.14 * i, 2.70], [1.34, 0.025, 0.03]) for i in range(5)]),
    )
    for sx, s in ((1, "L"), (-1, "R")):
        add(f"Headlight_{s}", R.HEADLIGHT, "headlight", P.box([sx * 0.98, 1.62, 2.66], [0.34, 0.20, 0.08]))
        add(f"Indicator_{s}", R.HEADLIGHT, "indicator", P.box([sx * 0.98, 1.90, 2.66], [0.34, 0.08, 0.07]))

    # windscreen: raked panel offset slightly outside the cab skin
    d = np.array([2.22 - 2.63, 3.55 - 2.35])
    length = float(np.linalg.norm(d))
    ang = float(np.arctan2(d[0], d[1]))  # lean from vertical toward -Z
    glass = trimesh.creation.box(extents=[2.2, length * 0.84, 0.03])
    glass.apply_transform(trimesh.transformations.rotation_matrix(ang, [1, 0, 0]))
    nrm = np.array([0.0, d[1], -d[0]]) / length  # (x, y, z) outward normal
    mid = np.array([0.0, (2.35 + 3.55) / 2, (2.63 + 2.22) / 2])
    glass.apply_translation(mid + nrm * 0.03)
    add("Window_Windshield", R.WINDOW, "glass", glass)
    for sx, s in ((1, "L"), (-1, "R")):
        wip = P.box([0, 0, 0], [0.025, 0.04, 0.75])
        wip.apply_transform(trimesh.transformations.rotation_matrix(ang, [1, 0, 0]))
        wip.apply_translation([sx * 0.45, 2.55, 2.58])
        add(f"Wiper_{s}", R.WIPER, "plastic", wip)

    # --- doors / door glass / mirrors -------------------------------------------------------
    for sx, s in ((1, "L"), (-1, "R")):
        add(f"Door_{s}", R.DOOR, "body_paint", P.box([sx * (CAB_HALF_W + 0.025), 2.30, 1.55], [0.05, 1.70, 1.30]))
        add(f"Window_Door_{s}", R.WINDOW, "glass", P.box([sx * (CAB_HALF_W + 0.060), 2.95, 1.55], [0.02, 0.65, 1.0]))
        arm = P.tube_between([sx * 1.24, 2.60, 2.18], [sx * 1.62, 2.60, 2.18], 0.018)
        head = P.box([sx * 1.66, 2.62, 2.16], [0.12, 0.46, 0.10])
        add(f"Mirror_{s}", R.MIRROR, "plastic", P.merge([arm, head]))
        add(f"Handle_{s}", R.DOOR, "chrome", P.box([sx * (CAB_HALF_W + 0.065), 2.20, 1.00], [0.03, 0.04, 0.22]))

    # --- body ---------------------------------------------------------------------------------
    add(
        "Exhaust_Stack",
        R.EXHAUST,
        "chrome",
        P.merge([P.cylinder_y([1.12, 2.55, -0.08], 0.075, 2.7), P.cylinder_y([1.12, 3.95, -0.08], 0.095, 0.10)]),
    )
    for sx, s in ((1, "L"), (-1, "R")):
        add(f"Fuel_Tank_{s}", R.BODY, "aluminium", P.cylinder_z([sx * 0.98, 0.85, -0.55], 0.30, 1.0))
        fenders = [
            P.box([sx * 0.90, 1.12, -1.90], [0.84, 0.05, 1.7]),
            P.box([sx * FRONT_X, 1.14, 1.90], [0.46, 0.04, 1.15]),
        ]
        add(f"Fender_{s}", R.BODY, "body_paint", P.merge(fenders))
        add(f"Mudflap_{s}", R.BODY, "rubber", P.box([sx * 0.90, 0.55, -3.30], [0.55, 0.60, 0.02]))
        add(f"Taillight_{s}", R.TAILLIGHT, "taillight", P.box([sx * 0.88, 0.98, -3.52], [0.16, 0.22, 0.06]))
    add(
        "Fifth_Wheel",
        R.ATTACHMENT,
        "chassis_steel",
        P.merge([P.box([0, 1.12, -1.30], [1.25, 0.10, 1.05]), P.box([0, 1.00, -1.30], [0.50, 0.16, 0.60])]),
    )
    add(
        "Air_Hose_Connectors",
        R.ATTACHMENT,
        "plastic",
        P.merge([P.cylinder_z([sx * 0.22, 1.35, -0.28], 0.04, 0.12, 12) for sx in (-1, 1)]),
    )
    add("Rear_Light_Bar", R.TAILLIGHT, "taillight", P.box([0, 0.80, -3.54], [0.40, 0.06, 0.04]))

    # --- interior -----------------------------------------------------------------------------
    add("Dashboard", R.INTERIOR, "interior", P.box([0, 2.05, 2.30], [2.1, 0.36, 0.40]))
    wheel = P.torus_z(
        [0.50, 2.25, 1.88], 0.19, 0.018, rot=trimesh.transformations.rotation_matrix(np.radians(-20), [1, 0, 0])
    )
    add("Steering_Wheel", R.INTERIOR, "interior", wheel)
    for seat_x, s in ((0.5, "Driver"), (-0.5, "Passenger")):
        add(
            f"Seat_{s}",
            R.INTERIOR,
            "interior",
            P.merge([P.box([seat_x, 1.55, 1.15], [0.55, 0.14, 0.55]), P.box([seat_x, 2.0, 0.90], [0.55, 0.80, 0.12])]),
        )

    # --- running gear ------------------------------------------------------------------------
    axle_defs, wheel_defs, susp = [], [], []
    for ax, z in AXLES.items():
        front = ax == "Axle_Front"
        outer = FRONT_X if front else REAR_OUTER_X
        track = 2 * (FRONT_X if front else (REAR_INNER_X + REAR_OUTER_X) / 2)
        add(ax, R.AXLE, "chassis_steel", P.cylinder_x([0, TIRE_R, z], 0.085, 2 * outer, 20))
        axle_defs.append(
            AxleDef(name=ax, position=(0.0, TIRE_R, z), track_width=track, steering=front, driven=not front)
        )
        for sx, side in ((1, "left"), (-1, "right")):
            sfx = "L" if sx > 0 else "R"
            susp.append(
                SuspensionPoint(name=f"Susp_{ax}_{sfx}", axle=ax, side=side, position=(sx * 0.46, 0.98, z), travel=0.15)
            )
            xs = [(FRONT_X, "")] if front else [(REAR_INNER_X, "I"), (REAR_OUTER_X, "O")]
            for x, tag in xs:
                key = ax.replace("Axle_", "").replace("Front", "F").replace("Rear", "R")
                wn, tn = f"Wheel_{key}_{sfx}{tag}", f"Tire_{key}_{sfx}{tag}"
                c = [sx * x, TIRE_R, z]
                add(wn, R.WHEEL, "rim_steel", _rim(c, outward=sx if tag != "I" else -sx))
                add(tn, R.TIRE, "rubber", _tire(c))
                wheel_defs.append(
                    WheelDef(
                        name=wn,
                        axle=ax,
                        side=side,
                        position=tuple(c),
                        radius=TIRE_R,
                        width=TIRE_W,
                        steering=front,
                        driven=not front,
                        part=wn,
                        tire_part=tn,
                    )
                )

    # --- vehicle metadata ---------------------------------------------------------------------
    pivots: list[PivotDef] = []
    for sx, s in ((1, "L"), (-1, "R")):
        # Door hinges on the cab's front edge. Left door opens with negative rotation about +Y (see docs).
        pivots.append(
            PivotDef(
                name=f"Hinge_Door_{s}",
                kind="door",
                position=(sx * (CAB_HALF_W + 0.025), 2.30, 2.20),
                axis=(0, 1, 0),
                limits_deg=(-70.0, 0.0) if sx > 0 else (0.0, 70.0),
                part=f"Door_{s}",
                children=[f"Window_Door_{s}", f"Handle_{s}"],
            )
        )
        pivots.append(
            PivotDef(
                name=f"Pivot_Mirror_{s}",
                kind="mirror",
                position=(sx * 1.24, 2.60, 2.18),
                axis=(0, 1, 0),
                limits_deg=(0.0, 90.0) if sx > 0 else (-90.0, 0.0),
                part=f"Mirror_{s}",
            )
        )
        pivots.append(
            PivotDef(
                name=f"Pivot_Wiper_{s}",
                kind="wiper",
                position=(sx * 0.45, 2.45, 2.60),
                axis=(0, 0.94, 0.33),
                limits_deg=(0.0, 80.0),
                part=f"Wiper_{s}",
            )
        )
    pivots.append(
        PivotDef(
            name="Pivot_SteeringWheel",
            kind="steering_wheel",
            position=(0.50, 2.25, 1.88),
            axis=(0, 0.342, 0.940),
            limits_deg=(-540.0, 540.0),
            part="Steering_Wheel",
        )
    )
    lights = [
        *[
            LightDef(
                name=f"Light_Head_{s}",
                kind="head",
                side="left" if sx > 0 else "right",
                position=(sx * 0.98, 1.62, 2.70),
                direction=(0, 0, 1),
                part=f"Headlight_{s}",
            )
            for sx, s in ((1, "L"), (-1, "R"))
        ],
        *[
            LightDef(
                name=f"Light_Indicator_{s}",
                kind="indicator",
                side="left" if sx > 0 else "right",
                position=(sx * 0.98, 1.90, 2.70),
                direction=(0, 0, 1),
                color=(1.0, 0.55, 0.0),
                part=f"Indicator_{s}",
            )
            for sx, s in ((1, "L"), (-1, "R"))
        ],
        *[
            LightDef(
                name=f"Light_Tail_{s}",
                kind="tail",
                side="left" if sx > 0 else "right",
                position=(sx * 0.88, 0.98, -3.56),
                direction=(0, 0, -1),
                color=(1.0, 0.05, 0.05),
                part=f"Taillight_{s}",
            )
            for sx, s in ((1, "L"), (-1, "R"))
        ],
    ]
    identity = VehicleIdentity(
        manufacturer="ARO Motors",
        brand="ARO",
        model="TITAN 480",
        category="heavy_truck",
        body_type="tractor_unit",
        drive_configuration="6x4",
        asset_version="0.1.0",
    )
    vehicle = VehicleSpec(
        identity=identity,
        axles=axle_defs,
        wheels=wheel_defs,
        suspension_points=susp,
        steering_points=[(FRONT_X, TIRE_R, AXLES["Axle_Front"]), (-FRONT_X, TIRE_R, AXLES["Axle_Front"])],
        center_of_mass=(0.0, 1.10, -0.60),
        pivots=pivots,
        mirror_positions=[(1.66, 2.62, 2.16), (-1.66, 2.62, 2.16)],
        lights=lights,
        wheelbase=AXLES["Axle_Front"] - (AXLES["Axle_Rear1"] + AXLES["Axle_Rear2"]) / 2,
        attachment_points=[
            AttachmentPoint(
                name="Attach_FifthWheel", kind="fifth_wheel", position=(0.0, 1.17, -1.30), direction=(0, 1, 0)
            ),
            AttachmentPoint(
                name="Attach_TrailerConnector_L", kind="air_hose", position=(0.22, 1.35, -0.34), direction=(0, 0, -1)
            ),
            AttachmentPoint(
                name="Attach_TrailerConnector_R", kind="air_hose", position=(-0.22, 1.35, -0.34), direction=(0, 0, -1)
            ),
            AttachmentPoint(
                name="Attach_Camera_Chase", kind="camera", position=(0.0, 4.2, -4.5), direction=(0, -0.2, 1)
            ),
        ],
    )

    manifest = SceneManifest(
        name=name,
        category="heavy_truck",
        parts=[PartDef(name=n, component=r.value, material=m, mesh_file="") for n, r, m, _ in parts],
        materials=[m.model_copy(deep=True) for m in REFERENCE_MATERIALS],
        vehicle=vehicle,
        provenance=Provenance(
            source="procedural_reference",
            note="Original procedurally authored reference model. Not AI-generated. Geometry is simplified.",
        ),
    )
    vehicle.components = {}
    for n, r, _, _ in parts:
        vehicle.components.setdefault(r.value, []).append(n)
    scene = Scene(manifest=manifest, meshes={n: mesh for n, _, _, mesh in parts})
    scene.refresh_counts()
    return scene
