# TripoSR baselines (measured 2026-10-26)

Prepared TripoSR models scored against the image they came from with `scripts/score_model.py` (method and limits:
`aro_studio/quality/fidelity.py`, `docs/architecture/product-reassessment.md` section 3).

| Label | Reference | Prepared model scored |
|---|---|---|
| `tripoSR-suv` | Premium Blue SUV Studio Render.png | `improved-prepared.glb` (real TripoSR output, prepared) |
| `tripoSR-truck-goldenhour` | ARO 480 Truck at Golden Hour.png | `01-prepared.glb` (real TripoSR output, prepared) |
| `tripoSR-truck-sunsethauler` | ARO African Roads Sunset Hauler.png | `improved-prepared.glb` (real TripoSR output, prepared) |

Each `*-sheet.png`: reference, outline overlay (yellow = agreement, red = reference only, green = model only), best-matching view,
front, side, rear, top, three-quarter. All three **fail** the floor (proportions implausible) despite IoU 0.91-0.94: silhouette overlap
cannot see depth. Visual quality is PENDING human review; nothing here is production-ready.
