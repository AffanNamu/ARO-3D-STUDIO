# Heavy-truck standard

* Length 2–25 m (validation range); a rigid/tractor unit is typically 6–9 m, articulated combinations are longer.
* Drive configuration maps to minimum structure: `NxM` ⇒ ≥ N/2 axles and ≥ N wheel positions (validation `V002`). Dual rear tyres are separate wheels (`…I` inner / `…O` outer).
* Tractor units (`body_type = tractor_unit`) must provide a `fifth_wheel` attachment point (`V009`); trailers' connectors (`air_hose`) are optional attachment points.
* Wheel centre y = tyre radius (±3 cm) (`V006`); axle z equals its wheels' z (`V007`); centre of mass inside the body and between the outer axles (`V008`).
* Collision: convex hulls ≤ 255 triangles (PhysX/Unity limit for convex mesh colliders), body + cabin hulls; wheel physics is left to the game's WheelColliders.
* Budget: LOD0 ≤ `ARO_TRI_BUDGET_LOD0` (default 150,000).

## Reference asset: ARO TITAN 480

Original design, fictional manufacturer ARO Motors, heavy-duty 6×4 cab-over tractor unit, LHD. Procedurally authored from primitives/extrusions/revolves — **no real manufacturer's logos, badges, trademarks or distinctive styling** and **not AI-generated** (provenance `procedural_reference`). 60 parts, 15,736 triangles, 6.50 × 3.44 × 4.00 m (mirrors included), 3 axles / 10 wheels (dual rears), 12 PBR materials, 13 pivots/lights/attachments. Geometry is simplified by design; it exists to exercise and validate the pipeline, not to be the final art. Replace it with artist or AI-assisted work that passes the same validation.
