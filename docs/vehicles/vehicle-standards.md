# Vehicle asset standard

A vehicle is a **structured asset**, not one mesh. Everything below is enforced by the schema (`scene/model.py`), the rig builder and the validation rules.

## Coordinate conventions

metres · right-handed · **+Y up** · **+Z forward** · **+X = vehicle left** (left-hand-drive cab for right-hand traffic) · origin on the ground (tyre contact y = 0), x = 0 on the centreline, z = 0 at the centre of the wheelbase. Tyre/axle axes are X.

## Required structure

| Group | Content |
|---|---|
| Identity | manufacturer, brand, model, category, body type, drive configuration (`6x4` = 6 wheel *positions* on 3 axles, 4 driven), asset version |
| Geometry (component roles) | chassis, cabin, body, bumper, grille, door, window, mirror, headlight, taillight, exhaust, axle, wheel, tire, attachment, wiper, interior |
| Running gear | axles (position, track, steering, driven, suspension travel), wheels (position, radius, width, axle, steering, driven, rim + tyre + optional wheel-detail parts) |
| Physics preparation | collision (separate from visuals), wheel positions, centre of mass, suspension points, steering points, attachment points |
| Articulation | pivots with axis + limits: doors, mirrors, wipers, steering wheel; lights (kind, position, direction) |
| Materials | paint, glass, rubber, chrome, metal, plastic, lights, interior |
| LOD | LOD0–LOD3 |

## Rig node naming (exported hierarchy)

`Vehicle_Root` → `Susp_<axle>` → `Steer_<wheel>` (steered axles) → `Spin_<wheel>` → wheel + tyre parts · `Hinge_Door_L/R`, `Pivot_Mirror_L/R`, `Pivot_Wiper_L/R`, `Pivot_SteeringWheel` · `Light_*`, `Attach_*`. Names are Unity-safe (`[A-Za-z0-9_.-]`, ≤ 64, unique). Parts are `<Part>_LOD<n>` and `COL_*` for collision.

Rotation signs follow the right-hand rule about the listed axis. Left door (+X side) opens with **negative** angles about +Y; right door with positive. Mirror fold: left positive, right negative.

## What is NOT automatic

Wheel/axle/pivot positions come from the artist (or the reference spec). Automatic vehicle part detection/separation from a single reconstructed mesh is a future capability and is **not** faked. The Vehicle step provides role assignment and a validated JSON spec editor.
