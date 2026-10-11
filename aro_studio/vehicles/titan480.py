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

from aro_studio.materials.library import REFERENCE_MATERIALS, make_material
from aro_studio.scene.model import (
    AttachmentPoint,
    AxleDef,
    LightDef,
    MaterialCategory,
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
# Axle coordinates are tuned to the concept brief's provisional 3.90 m wheelbase.
# Front axle centre +1.95 m; mean of the tandem rear axles -1.95 m.
AXLES = {"Axle_Front": 1.95, "Axle_Rear1": -1.30, "Axle_Rear2": -2.60}
FRONT_X = 1.04
REAR_INNER_X, REAR_OUTER_X = 0.72, 1.08
CAB_HALF_W = 1.22

# Titan-specific palette. Keep the generic Studio reference palette unchanged for other asset families.
TITAN_PAINT = make_material(
    "aro_pearl_white",
    MaterialCategory.PAINT,
    base_color=(0.91, 0.90, 0.86, 1.0),
    metallic=0.28,
    roughness=0.25,
)
TITAN_GOLD = make_material(
    "aro_gold",
    MaterialCategory.METAL,
    base_color=(0.83, 0.67, 0.27, 1.0),
    metallic=0.86,
    roughness=0.25,
)
TITAN_BLACK = make_material(
    "aro_black_paint",
    MaterialCategory.PAINT,
    base_color=(0.025, 0.032, 0.042, 1.0),
    metallic=0.42,
    roughness=0.30,
)


def _tire(center) -> trimesh.Trimesh:
    """Tyre with a rounded sidewall and shallow circumferential tread channels."""
    h = TIRE_W / 2
    prof = [
        (RIM_R - 0.02, -h + 0.02),
        (TIRE_R - 0.07, -h),
        (TIRE_R - 0.03, -0.13),
        (TIRE_R - 0.012, -0.105),
        (TIRE_R, -0.08),
        (TIRE_R, -0.06),
        (TIRE_R - 0.028, -0.04),
        (TIRE_R, -0.02),
        (TIRE_R, 0.02),
        (TIRE_R - 0.028, 0.04),
        (TIRE_R, 0.06),
        (TIRE_R, 0.08),
        (TIRE_R - 0.012, 0.105),
        (TIRE_R - 0.03, 0.13),
        (TIRE_R - 0.07, h),
        (RIM_R - 0.02, h - 0.02),
    ]
    return P.revolve_x(prof, center)


def _rim(center, outward: float) -> trimesh.Trimesh:
    """Steel disc wheel; the dish faces ``outward`` (+1 / -1 along X)."""
    h = 0.12
    prof = [(0.06, -h), (RIM_R, -h), (RIM_R, h), (0.12, h), (0.12, h - 0.03 * outward), (0.06, h - 0.05)]
    return P.revolve_x(prof, center, sections=40)


def _wheel_hub(center, outward: float) -> trimesh.Trimesh:
    """Separate hub piece; it follows the wheel rig without corrupting rim topology."""
    return P.cylinder_x([center[0] + outward * 0.10, center[1], center[2]], 0.07, 0.05, 24)


def _wheel_detail(center, outward: float) -> trimesh.Trimesh:
    """Gold outer rim ring and ten raised wheel fasteners on the visible side."""
    rot = trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0])
    ring = P.torus_z(
        [center[0] + outward * 0.132, center[1], center[2]],
        0.235,
        0.012,
        rot=rot,
        major_sections=32,
        minor_sections=8,
    )
    bolts = []
    for i in range(10):
        angle = 2 * np.pi * i / 10
        bolt_center = [
            center[0] + outward * 0.148,
            center[1] + 0.185 * np.cos(angle),
            center[2] + 0.185 * np.sin(angle),
        ]
        bolts.append(P.cylinder_x(bolt_center, 0.022, 0.035, 8))
    return P.merge([ring, *bolts])


def _fender_arch(center_z: float, side_x: float, radius: float, tube_radius: float) -> trimesh.Trimesh:
    """Create a closed tube sweep with shared vertices and capped endpoints."""
    path_steps, ring_steps = 25, 12
    theta = np.linspace(0.0, np.pi, path_steps)
    phi = np.arange(ring_steps) * (2 * np.pi / ring_steps)
    vertices: list[np.ndarray] = []
    faces: list[tuple[int, int, int]] = []

    for angle in theta:
        center = np.array([side_x, TIRE_R + radius * np.sin(angle), center_z + radius * np.cos(angle)])
        normal = np.array([0.0, np.sin(angle), np.cos(angle)])
        for around in phi:
            offset = tube_radius * np.array([np.cos(around), np.sin(around) * normal[1], np.sin(around) * normal[2]])
            vertices.append(center + offset)

    for step in range(path_steps - 1):
        for around in range(ring_steps):
            nxt = (around + 1) % ring_steps
            a = step * ring_steps + around
            b = (step + 1) * ring_steps + around
            c = (step + 1) * ring_steps + nxt
            d = step * ring_steps + nxt
            faces.extend(((a, b, c), (a, c, d)))

    start_center = len(vertices)
    vertices.append(np.array([side_x, TIRE_R, center_z + radius], dtype=np.float64))
    end_center = len(vertices)
    vertices.append(np.array([side_x, TIRE_R, center_z - radius], dtype=np.float64))
    end_start = (path_steps - 1) * ring_steps
    for around in range(ring_steps):
        nxt = (around + 1) % ring_steps
        faces.append((start_center, around, nxt))
        faces.append((end_center, end_start + nxt, end_start + around))

    mesh = trimesh.Trimesh(
        vertices=np.asarray(vertices),
        faces=np.asarray(faces),
        process=False,
    )
    mesh.fix_normals()
    if mesh.volume < 0:
        mesh.invert()
    return mesh


def _front_aro_logo_parts(z: float) -> list[tuple[str, trimesh.Trimesh]]:
    """Return each raised ARO logo stroke as its own watertight solid."""
    radius = 0.008
    strokes = [
        # A
        ((-0.235, 2.105, z), (-0.180, 2.245, z)),
        ((-0.180, 2.245, z), (-0.125, 2.105, z)),
        ((-0.211, 2.165, z), (-0.149, 2.165, z)),
        # R
        ((-0.075, 2.105, z), (-0.075, 2.245, z)),
        ((-0.075, 2.245, z), (-0.010, 2.245, z)),
        ((-0.010, 2.245, z), (0.005, 2.222, z)),
        ((0.005, 2.222, z), (-0.010, 2.185, z)),
        ((-0.010, 2.185, z), (-0.075, 2.185, z)),
        ((-0.043, 2.185, z), (0.012, 2.105, z)),
    ]
    parts = [
        (f"ARO_Grille_Stroke_{index:02d}", P.tube_between(start, end, radius, sections=8))
        for index, (start, end) in enumerate(strokes, start=1)
    ]
    parts.append(
        (
            "ARO_Grille_Stroke_10",
            P.torus_z([0.105, 2.175, z], 0.038, radius, major_sections=24, minor_sections=8),
        )
    )
    return parts


def _side_aro_logo_parts(
    side_x: float, center_y: float, center_z: float, side: str
) -> list[tuple[str, trimesh.Trimesh]]:
    """Return door-logo strokes separately so every mesh remains manifold and riggable."""
    radius = 0.007
    z = center_z
    y = center_y
    strokes = [
        # A
        ((side_x, y - 0.055, z - 0.135), (side_x, y + 0.055, z - 0.090)),
        ((side_x, y + 0.055, z - 0.090), (side_x, y - 0.055, z - 0.045)),
        ((side_x, y - 0.018, z - 0.118), (side_x, y - 0.018, z - 0.062)),
        # R
        ((side_x, y - 0.055, z - 0.012), (side_x, y + 0.055, z - 0.012)),
        ((side_x, y + 0.055, z - 0.012), (side_x, y + 0.055, z + 0.045)),
        ((side_x, y + 0.055, z + 0.045), (side_x, y - 0.055, z + 0.045)),
        ((side_x, y - 0.055, z + 0.045), (side_x, y - 0.055, z - 0.012)),
        ((side_x, y + 0.055, z - 0.012), (side_x, y - 0.055, z + 0.045)),
    ]
    parts = [
        (f"Logo_Door_{side}_{index:02d}", P.tube_between(start, end, radius, sections=8))
        for index, (start, end) in enumerate(strokes, start=1)
    ]
    rot = trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0])
    parts.append(
        (
            f"Logo_Door_{side}_09",
            P.torus_z([side_x, y, z + 0.125], 0.038, radius, rot=rot, major_sections=24, minor_sections=8),
        )
    )
    return parts


def build_titan480(name: str = "ARO TITAN 480") -> Scene:
    parts: list[tuple[str, R, str, trimesh.Trimesh]] = []

    def add(pname: str, role: R, material: str, mesh: trimesh.Trimesh) -> None:
        parts.append((pname, role, material, mesh))

    # --- chassis ---------------------------------------------------------------------------
    rails = [P.box([sx * 0.46, 0.88, -0.45], [0.11, 0.30, 6.1]) for sx in (-1, 1)]
    crossmember_z = (2.45, 1.4, 0.2, -1.0, -2.0, -3.2)
    add("Chassis_Frame", R.CHASSIS, "chassis_steel", P.merge(rails))
    for index, z in enumerate(crossmember_z, start=1):
        add(
            f"Chassis_Crossmember_{index:02d}",
            R.CHASSIS,
            "chassis_steel",
            P.box([0, 0.86, z], [0.92, 0.12, 0.14]),
        )

    # --- cab ---------------------------------------------------------------------------------
    profile = [
        (0.20, 1.15),
        (2.36, 1.15),
        (2.48, 1.22),
        (2.57, 1.46),
        (2.63, 2.35),
        (2.22, 3.55),
        (2.10, 3.62),
        (0.64, 3.62),
        (0.46, 3.56),
        (0.20, 3.42),
    ]
    add("Cab_Shell", R.CABIN, "body_paint", P.extrude_profile_zy(profile, 2 * CAB_HALF_W))

    # Profiled roof deflector: the sloped ends blend toward the cab roof instead of
    # reading as a rectangular block when seen from the side.
    fairing_profile = [
        (0.04, 3.62),
        (0.12, 3.82),
        (0.29, 3.96),
        (0.62, 3.96),
        (0.81, 3.82),
        (0.90, 3.62),
    ]
    add("Roof_Deflector", R.BODY, "aro_pearl_white", P.extrude_profile_zy(fairing_profile, 2.10))
    add("Cab_Roof_Accent", R.BODY, "aro_gold", P.box([0, 3.965, 0.455], [1.84, 0.018, 0.42]))

    # --- front end ---------------------------------------------------------------------------
    # Layered front fascia: the bumper projects furthest forward, with the grille
    # and headlamp modules sitting on a deeper backing panel.
    add("Bumper_Front", R.BUMPER, "plastic", P.box([0, 0.93, 2.88], [2.34, 0.42, 0.38]))
    add("Cab_Fascia", R.BODY, "aro_black_paint", P.box([0, 1.79, 2.72], [2.30, 1.10, 0.18]))
    add("Grille", R.GRILLE, "plastic", P.box([0, 1.83, 2.84], [1.42, 0.76, 0.10]))
    add(
        "Grille_Trim",
        R.GRILLE,
        "aro_gold",
        P.merge([P.box([0, 1.55 + 0.14 * i, 2.895], [1.34, 0.025, 0.02]) for i in range(5)]),
    )
    # A narrow secondary intake breaks up the blank area between the main grille and bumper.
    add("Lower_Intake", R.GRILLE, "plastic", P.box([0, 1.31, 2.87], [0.88, 0.10, 0.06]))
    add("Lower_Intake_Trim", R.GRILLE, "aro_gold", P.box([0, 1.365, 2.905], [0.84, 0.012, 0.018]))

    for sx, s in ((1, "L"), (-1, "R")):
        add(
            f"Headlight_Bezel_{s}",
            R.BODY,
            "aro_black_paint",
            P.box([sx * 0.96, 1.64, 2.80], [0.34, 0.25, 0.04]),
        )
        add(
            f"Headlight_{s}",
            R.HEADLIGHT,
            "headlight",
            P.box([sx * 0.96, 1.64, 2.86], [0.28, 0.18, 0.08]),
        )
        add(
            f"Indicator_{s}",
            R.HEADLIGHT,
            "indicator",
            P.box([sx * 0.96, 1.87, 2.86], [0.28, 0.06, 0.06]),
        )
        add(
            f"Bumper_Corner_Accent_{s}",
            R.BUMPER,
            "aro_gold",
            P.box([sx * 1.04, 0.94, 3.078], [0.045, 0.23, 0.018]),
        )

    for logo_name, logo_mesh in _front_aro_logo_parts(2.89):
        add(logo_name, R.GRILLE, "aro_gold", logo_mesh)
    add("Gold_Bumper_Trim", R.BUMPER, "aro_gold", P.box([0, 0.94, 3.078], [2.16, 0.035, 0.018]))
    add("Front_Nameplate", R.BODY, "aro_black_paint", P.box([0, 0.89, 3.079], [0.54, 0.12, 0.018]))

    # Five small amber marker lamps across the cab roof edge.
    for i, x in enumerate((-0.72, -0.36, 0.0, 0.36, 0.72), start=1):
        add(f"Roof_Marker_{i}", R.HEADLIGHT, "indicator", P.box([x, 3.65, 2.20], [0.085, 0.045, 0.045]))

    # windscreen: raked panel offset slightly outside the cab skin
    d = np.array([2.22 - 2.63, 3.55 - 2.35])
    length = float(np.linalg.norm(d))
    ang = float(np.arctan2(d[0], d[1]))  # lean from vertical toward -Z
    glass = trimesh.creation.box(extents=[2.2, length * 0.84, 0.03])
    glass.apply_transform(trimesh.transformations.rotation_matrix(ang, [1, 0, 0]))
    # d is ordered (delta_z, delta_y), so the perpendicular in world (y, z)
    # is (delta_y, -delta_z); map that back to (x, y, z) coordinates.
    nrm = np.array([0.0, -d[0], d[1]]) / length
    mid = np.array([0.0, (2.35 + 3.55) / 2, (2.63 + 2.22) / 2])
    glass.apply_translation(mid + nrm * 0.03)
    add("Window_Windshield", R.WINDOW, "glass", glass)

    # Distinct black windshield surround follows the actual rake of the glass.
    glass_half_height = length * 0.42
    panel_mid_y, panel_mid_z = mid[1], mid[2]
    upper_y = panel_mid_y + (d[1] / length) * glass_half_height
    upper_z = panel_mid_z + (d[0] / length) * glass_half_height
    lower_y = panel_mid_y - (d[1] / length) * glass_half_height
    lower_z = panel_mid_z - (d[0] / length) * glass_half_height
    frame_offset = nrm * 0.052
    upper = np.array([0.0, upper_y, upper_z]) + frame_offset
    lower = np.array([0.0, lower_y, lower_z]) + frame_offset
    frame_half_width = 1.06
    add(
        "Windshield_Frame_Bottom",
        R.BODY,
        "aro_black_paint",
        P.tube_between(
            [-frame_half_width, lower[1], lower[2]],
            [frame_half_width, lower[1], lower[2]],
            0.018,
            sections=10,
        ),
    )
    add(
        "Windshield_Frame_Top",
        R.BODY,
        "aro_black_paint",
        P.tube_between(
            [-frame_half_width, upper[1], upper[2]],
            [frame_half_width, upper[1], upper[2]],
            0.018,
            sections=10,
        ),
    )
    for sx, side in ((1, "L"), (-1, "R")):
        add(
            f"Windshield_Pillar_{side}",
            R.BODY,
            "aro_black_paint",
            P.tube_between(
                [sx * frame_half_width, lower[1], lower[2]],
                [sx * frame_half_width, upper[1], upper[2]],
                0.018,
                sections=10,
            ),
        )

    for sx, s in ((1, "L"), (-1, "R")):
        wip = P.box([0, 0, 0], [0.025, 0.04, 0.75])
        wip.apply_transform(trimesh.transformations.rotation_matrix(ang, [1, 0, 0]))
        wip.apply_translation([sx * 0.45, 2.55, 2.58])
        add(f"Wiper_{s}", R.WIPER, "plastic", wip)

    # --- doors / door glass / mirrors -------------------------------------------------------
    for sx, s in ((1, "L"), (-1, "R")):
        # The door follows the cab side profile instead of appearing as a rectangular slab.
        door_profile = [
            (0.32, 1.28),
            (2.22, 1.28),
            (2.08, 2.44),
            (1.91, 3.30),
            (0.58, 3.34),
            (0.43, 3.12),
        ]
        add(
            f"Door_{s}",
            R.DOOR,
            "aro_pearl_white",
            P.extrude_profile_zy(door_profile, 0.05, center_x=sx * (CAB_HALF_W + 0.025)),
        )

        # A dark outer seal sits behind a smaller, opaque tinted pane. The angular
        # polygon matches the sloping A-pillar and keeps a visible black border.
        window_frame_profile = [
            (0.76, 2.48),
            (1.81, 2.48),
            (1.98, 3.19),
            (0.92, 3.25),
        ]
        window_glass_profile = [
            (0.82, 2.54),
            (1.75, 2.54),
            (1.90, 3.13),
            (0.99, 3.19),
        ]
        add(
            f"Window_Door_Frame_{s}",
            R.BODY,
            "aro_black_paint",
            P.extrude_profile_zy(window_frame_profile, 0.018, center_x=sx * (CAB_HALF_W + 0.055)),
        )
        add(
            f"Window_Door_{s}",
            R.WINDOW,
            "glass",
            P.extrude_profile_zy(window_glass_profile, 0.01, center_x=sx * (CAB_HALF_W + 0.069)),
        )
        arm = P.tube_between([sx * 1.24, 2.60, 2.18], [sx * 1.62, 2.60, 2.18], 0.018)
        head = P.box([sx * 1.66, 2.62, 2.16], [0.12, 0.46, 0.10])
        add(f"Mirror_{s}", R.MIRROR, "plastic", P.merge([arm, head]))
        add(f"Handle_{s}", R.DOOR, "chrome", P.box([sx * (CAB_HALF_W + 0.065), 2.20, 1.00], [0.03, 0.04, 0.22]))

    # Gold side pinstripes, raised ARO marks and robust access steps.
    for sx, s in ((1, "L"), (-1, "R")):
        x = sx * 1.277
        stripe = [
            P.tube_between([x, 1.43, 0.28], [x, 1.43, 1.32], 0.016, sections=8),
            P.tube_between([x, 1.43, 1.32], [x, 1.68, 1.86], 0.016, sections=8),
            P.tube_between([x, 1.68, 1.86], [x, 1.82, 2.08], 0.016, sections=8),
        ]
        add(f"Gold_Pinstripe_{s}", R.BODY, "aro_gold", P.merge(stripe))
        add(f"Gold_Sill_Trim_{s}", R.BODY, "aro_gold", P.box([sx * 1.275, 1.29, 1.02], [0.024, 0.028, 1.45]))
        for logo_name, logo_mesh in _side_aro_logo_parts(sx * 1.292, 2.10, 1.22, s):
            add(logo_name, R.DOOR, "aro_gold", logo_mesh)
        add(f"Side_Step_{s}", R.BODY, "aro_black_paint", P.box([sx * 1.08, 0.80, 0.98], [0.34, 0.09, 0.58]))
        add(f"Side_Step_Grip_{s}", R.BODY, "aro_gold", P.box([sx * 1.22, 0.853, 0.98], [0.035, 0.012, 0.46]))

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
            P.box([sx * 0.90, 1.12, (AXLES["Axle_Rear1"] + AXLES["Axle_Rear2"]) / 2], [0.84, 0.05, 1.7]),
            P.box([sx * FRONT_X, 1.14, AXLES["Axle_Front"]], [0.46, 0.04, 1.15]),
        ]
        add(f"Fender_{s}", R.BODY, "aro_pearl_white", P.merge(fenders))
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
                outward = sx if tag != "I" else -sx
                detail_name = f"Wheel_Detail_{key}_{sfx}{tag}"
                hub_name = f"Wheel_Hub_{key}_{sfx}{tag}"
                add(wn, R.WHEEL, "rim_steel", _rim(c, outward=outward))
                add(tn, R.TIRE, "rubber", _tire(c))
                add(detail_name, R.WHEEL_DETAIL, "aro_gold", _wheel_detail(c, outward))
                add(hub_name, R.WHEEL_DETAIL, "rim_steel", _wheel_hub(c, outward))
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
                        detail_parts=[detail_name, hub_name],
                    )
                )

    # Fender lips follow the actual wheel coordinates, not independent guessed offsets.
    for ax, center_z in AXLES.items():
        axle_key = ax.replace("Axle_", "")
        outer_x = FRONT_X + TIRE_W / 2 if ax == "Axle_Front" else REAR_OUTER_X + TIRE_W / 2
        for sx, side in ((1, "L"), (-1, "R")):
            x = sx * (outer_x + 0.04)
            add(
                f"Fender_Arch_{axle_key}_{side}",
                R.BODY,
                "aro_black_paint",
                _fender_arch(center_z, x, TIRE_R + 0.12, 0.028),
            )
            add(
                f"Fender_Accent_{axle_key}_{side}",
                R.BODY,
                "aro_gold",
                _fender_arch(center_z, x + sx * 0.022, TIRE_R + 0.135, 0.010),
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
                children=[
                    f"Window_Door_{s}",
                    f"Window_Door_Frame_{s}",
                    f"Handle_{s}",
                    *[f"Logo_Door_{s}_{i:02d}" for i in range(1, 10)],
                ],
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

    titan_materials = [m.model_copy(deep=True) for m in REFERENCE_MATERIALS]
    for material in titan_materials:
        if material.name == "body_paint":
            material.base_color = (0.86, 0.85, 0.80, 1.0)
            material.metallic = 0.28
            material.roughness = 0.25
        elif material.name == "glass":
            # Keep the established export material name while tinting this scene locally.
            material.base_color = (0.025, 0.075, 0.11, 0.9)
            material.metallic = 0.12
            material.roughness = 0.18
            material.alpha_mode = "BLEND"
            material.double_sided = True
    titan_materials.extend(
        [
            TITAN_PAINT.model_copy(deep=True),
            TITAN_GOLD.model_copy(deep=True),
            TITAN_BLACK.model_copy(deep=True),
        ]
    )

    manifest = SceneManifest(
        name=name,
        category="heavy_truck",
        parts=[PartDef(name=n, component=r.value, material=m, mesh_file="") for n, r, m, _ in parts],
        materials=titan_materials,
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
