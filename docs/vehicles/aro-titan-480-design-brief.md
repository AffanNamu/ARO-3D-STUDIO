# ARO TITAN 480 — Vehicle Design and Asset Brief

**Status:** Concept approved for modelling; engineering values and final dimensions require verification.  
**Vehicle role:** First hero vehicle for African Roads Online (ARO).  
**Brand:** ARO Motors — original fictional brand and visual identity.

## 1. Source references and decision

The owner supplied two concept boards in chat:
- **ARO TITAN 480 Truck Design Board** — primary styling reference with front, rear, side and three-quarter views, cab/interior and detail panels.
- **ARO Built for Africa Vehicle Lineup** — wider brand and future vehicle-family direction.

These images are visual design references, not engineering drawings. Printed technical values are treated as **provisional fictional product targets**, not as verified real-world specifications. Do not represent them as certified or legally approved specifications.

The hero image shows a tractor with a trailer attached, but the first vehicle asset to build is the **tractor unit only**. Make a trailer a separate asset so the fifth-wheel joint, trailers and cargo can be implemented and tested independently.

## 2. Visual direction

- Primary launch finish: pearl white cab, black front fascia and trim, refined ARO gold accents, dark chassis, realistic black rubber, machined-metal wheel details and glass with believable reflections.
- Body language: high-roof sleeper cab-over tractor; confident, rugged, premium long-haul appearance suited to the ARO brand.
- Front details: multi-level dark grille with original ARO mark, shaped bumper, distinct headlamp assemblies, indicators, roof marker lamps, mirrors, windshield and paired wipers.
- Side details: door and window frames, handles, steps, fuel tanks, wheel arches, exhaust/air hardware as appropriate, chassis rails and exposed running gear.
- Rear details: visible chassis end, fifth wheel, rear lamps, mud flaps, airlines/couplers and service access features.
- Cabin: build enough dashboard, steering wheel, seats and interior surfaces to support a future first-person driving camera. The reference interior image is a target direction, not a complete measured cabin layout.
- Keep brand marks original to ARO; do not copy a real manufacturer's badges or distinctive trade dress.
- Planned colour variants for later: sapphire blue, deep red, graphite grey, sunset orange and forest green. Do not delay the first vehicle to implement every variant.

## 3. Provisional product targets from the concept board

| Property | Concept-board target | Status |
|---|---|---|
| Model | ARO TITAN 480 | Brand/model decision |
| Vehicle | Heavy-duty tractor unit | Approved role |
| Configuration | 6x4, three axle groups | Approved target; drive logic must be tested |
| Engine identity | Fictional ARO D12 turbo-diesel, 12.0 L | Fictional design target; not a real engine claim |
| Rated power | 480 hp at 1,800 rpm | Provisional gameplay/marketing target |
| Maximum torque | 2,300 Nm at 1,000–1,400 rpm | Provisional gameplay target |
| Transmission | 12-speed automated manual | Provisional gameplay target |
| Fuel capacity | 1,200 L across dual tanks | Provisional packaging target |
| Suspension | Heavy-duty air suspension | Functional target |
| Braking | Disc brakes, ABS and retarder | Functional/gameplay target |
| Cab | High-roof sleeper | Styling target |
| Wheelbase | 3,900 mm shown on board | Provisional; define measurement datum and reconcile with axle positions before locking geometry |
| Weight | 60,000 kg shown as GVW | Ambiguous/market-dependent; verify whether this means vehicle gross weight or combination gross weight before using as a factual specification |

The gameplay physics profile must remain data-driven, so engine output, gear ratios, torque curve, mass, braking and suspension can be adjusted after vehicle testing without remodelling the exterior.

## 4. Coordinate system and packaging

Follow the repository's canonical vehicle convention:
- Units: metres, right-handed.
- **+Y up; +Z forward; +X vehicle-left.**
- Ground plane at **Y = 0** at tyre contact; X = 0 on the vehicle centreline.
- Z = 0 at the centre of the wheelbase, using a clearly documented wheelbase datum.
- Wheel and tyre spin axes run along X.

The current procedural TITAN reference in `aro_studio/vehicles/titan480.py` is a useful source of initial proportions and structural metadata, not the final visual-quality target. Its current front/rear axle coordinates imply a wheelbase that must be reconciled with the concept board's 3,900 mm before dimensions are frozen. Change coordinates as a coherent parameter set; never change only the displayed wheelbase number.

## 5. Required model structure

The vehicle must be a hierarchy of identifiable and individually assignable parts, not a single merged mesh.

Required visual/component roles:
- Chassis rails and cross-members.
- Cab shell, roof, bumper, grille, doors, windshield, side glass, mirrors, steps and handles.
- Headlamp, indicator, marker and tail-lamp assemblies.
- Axle groups, wheels, tyres, rims/hubs, fenders and mud flaps.
- Dual fuel tanks, exhaust and visible chassis equipment.
- Fifth wheel, trailer airline/coupling attachment points.
- Basic driver cabin parts: dashboard, steering wheel, driver/passenger seats and interior trim.

Where rear dual tyres are represented, distinguish **six primary wheel positions over three axles** from the additional physical tyre/rim meshes used for dual-wheel assemblies. The front axle steers; the two rear axle groups provide drive in the 6x4 target.

## 6. Materials and rendering

Use physically based metallic/roughness materials that export to glTF 2.0 and map well to Unity materials:
- Pearl-white paint with controlled clear-coat-like highlights where supported by the target renderer.
- ARO gold metallic accent, not a flat yellow substitute.
- Black painted/plastic fascia and dark chassis.
- Rubber tyres with distinguishable sidewalls and tread.
- Metallic rims, hubs, fuel tanks and chassis parts.
- Glass with appropriate transparency/reflection settings for the intended Unity render pipeline.
- Separate emissive/light geometry for lamps where useful.

Do not bake the entire identity into a flat image texture. The grille, lights, glass, tyres and cab silhouette need actual geometry and material definition.

## 7. Rig, physics and exports

The final asset should include:
- Stable root and named part hierarchy using Unity-safe unique names.
- Three axle definitions with realistic track widths; front steering axle and two driven rear groups.
- Correct wheel centres/radii and wheel-spin pivots; steering pivots on the front wheels.
- Suspension points/travel and a plausible centre-of-mass starting point for gameplay tuning.
- Door/mirror/wiper pivots if their animation is included in the first release.
- Fifth-wheel and camera attachment points.
- Separate simple collision shapes/hulls; do not use every high-detail exterior mesh as a physics collider.
- LOD0–LOD3, with triangle counts and transition thresholds tested on target hardware.
- Verified GLB/glTF export and a real Unity 6 import/test, including material, hierarchy, scale and pivot review.

## 8. Acceptance gates

Do not call the asset production-ready until all applicable gates pass:

1. **Visual review:** coherent front, rear, both side, top and three-quarter views; body silhouette and tyre layout match the approved references; no obvious holes, self-intersections or floating details.
2. **Geometry:** finite coordinates, no degenerate geometry, normals/material boundaries reviewed, no accidental tiny disconnected islands; deliberate open geometry is documented.
3. **Dimensions:** measured overall size, axle locations, ride height and tyre radii match the locked design specification; wheel contacts are at Y = 0.
4. **Vehicle structure:** required component roles, six primary wheel positions, three axles, steering/driven flags, pivots, attachment points and collider roles are present and internally consistent.
5. **Export:** GLB integrity verification and independent Khronos glTF validation report are both recorded; do not claim independent validation when the validator did not run.
6. **Unity 6:** actual import test succeeds; hierarchy, materials, scale, wheel pivots, collision and LODs are inspected in Unity.
7. **Driving test:** the truck accelerates, brakes, steers and behaves acceptably under the selected handling profile on the test route; performance is measured against an explicit target device budget.
8. **Provenance:** distinguish the original procedural reference and AI experiment from the final artist-authored/refined production asset. Never present the single-image TripoSR output as the finished realistic truck.

A passing code test alone is insufficient. The visual review and Unity import are explicit human acceptance gates.

## 9. Production order

1. Freeze this brief's open decisions and block out proportions from consistent views.
2. Build and review a clean low-poly/medium-poly cab, chassis and running gear with separate components.
3. Refine silhouette, panel breaks, tyres/rims, lighting assemblies and interior; author UVs and PBR materials.
4. Set up pivots, VehicleSpec, collision, attachments and LODs.
5. Export, validate, import into Unity 6 and run the first driving test.
6. Add the planned colour variants and separate trailer only after the base tractor passes.

## 10. Explicit non-goals

- Do not rerun single-image TripoSR repeatedly expecting production-quality geometry.
- Do not automatically infer mechanical parts or exact hidden surfaces from one image.
- Do not treat the concept board's printed values as verified legal/engineering data.
- Do not add the trailer mesh into the tractor's rigid hierarchy.
- Do not mark production-ready before visual inspection, export validation and Unity testing.
