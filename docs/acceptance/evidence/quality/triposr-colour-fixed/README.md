# TripoSR vehicles re-prepared with the colour fixes (2026-10-26)

The three real TripoSR reconstructions that exist so far (a car and two trucks), re-prepared from their **preserved raw meshes** with
the corrected pipeline (`scripts/reprepare_raw_mesh.py`, then `scripts/score_model.py`). **No new inference**: the raw meshes come from
the owner's earlier Colab runs (hashes below); only the preparation changed. Superseded by these: the prepared GLBs listed in
[`../../ai/ERRATUM-texture-alignment.md`](../../ai/ERRATUM-texture-alignment.md), whose baked colour was scrambled.

| Label | Reference image | Raw mesh (SHA-256 prefix) | Prepared GLB (SHA-256 prefix) | IoU | W/L, H/L | Proportions | Validation |
|---|---|---|---|---|---|---|---|
| `blue-suv` | Premium Blue SUV Studio Render.png | `01-Premium Blue SUV Studio Render-raw.glb` `04515371fab2efc4…` | `0f1fd355ad957cd1…` | 0.94 | 0.64 / 0.50 | implausible | NEEDS_REVIEW |
| `golden-hour-truck` | ARO 480 Truck at Golden Hour.png | `01-ARO 480 Truck at Golden Hour-raw.glb` `8c5d0615ed8b88fa…` | `fe43ae986fe48e0a…` | 0.92 | 0.85 / 0.86 | implausible | NEEDS_REVIEW |
| `sunset-hauler-truck` | ARO African Roads Sunset Hauler.png | `01-ARO African Roads Sunset Hauler (3)-raw.glb` `376aa3541b91df68…` | `a1129b8b8e6ce7ee…` | 0.90 | 0.76 / 0.77 | implausible | NEEDS_REVIEW |

What you can see now: `views/improved-*.png` are rendered **with the baked base-colour texture** (sampled per triangle by the Studio's
software renderer, so they look faceted; a viewer shows the texture smoothly). The SUV is blue with a dark grille, glass and wheels and a
red tail-light where the reference has one; the trucks are black with the orange/gold accents in the right places. `*-sheet.png` is the
reference-comparison sheet (grey shading, outline overlay).

What this does NOT show:

* **The geometry limits are unchanged**: all three still fail the proportion floor (see `../triposr-baseline/` and
  `docs/architecture/product-reassessment.md`), the SUV still stands on an invented ground disc, wheels are shallow relief.
* Size is a **1 m placeholder** (no real dimensions were supplied); forward direction is a guess; no vehicle specification, so validation is NEEDS_REVIEW.
* **Not production-ready, not human-reviewed, not imported into Unity** (no editor here).
* Khronos validator was not run in this sandbox (no Node package); the internal export verification passed.
