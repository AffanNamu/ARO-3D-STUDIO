# Car / SUV / pickup standard (proposed — not yet exercised)

No car asset has been built or validated yet; the generic vehicle rules apply (2 axles, 4 wheel positions for `4x2`/`4x4`, front axle steered, wheel centre = tyre radius). Typical dimensions: length 3.5–5.5 m, width 1.6–2.0 m, height 1.3–1.9 m (not enforced beyond the generic 2–25 m length range).

Recommendations: separate wheels/tyres for rotation, door pivots with limits, mirror pivots, lights as `Light_*` nodes, a single convex body hull (+ optional cabin hull) for collision, LOD0 budget well under the global default for crowd/traffic use (the budget is configurable per validation run).

Action to promote to a real standard: author one reference car, add category-specific rules and thresholds, and extend the acceptance report.
