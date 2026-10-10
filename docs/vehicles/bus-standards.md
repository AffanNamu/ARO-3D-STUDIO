# Bus standard (proposed — not yet exercised)

No bus asset has been built or validated yet. Buses use the same schema and rules as [vehicle-standards](vehicle-standards.md) with these proposed additions, **which the validation engine does not enforce today** (only the generic vehicle rules apply):

* `category: bus`, 2–3 axles, front axle steered; length typically 8–15 m (the generic 2–25 m range applies).
* Passenger doors as `door` parts with hinge/slide pivots (slide doors need a translation limit — the current `PivotDef` supports rotation limits only; extend the schema when the first bus is authored).
* Interior role for seats/handrails; window parts with glass material.
* Collision: one body hull + optional cabin hull; keep ≤ 255 triangles per convex hull.

Action to promote this to a real standard: author one bus, add bus-specific rules (door count, interior presence), and record the results in the acceptance report.
