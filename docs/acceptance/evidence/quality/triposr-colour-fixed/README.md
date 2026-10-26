# TripoSR vehicles re-prepared with the texture fixes (2026-10-26)

The three real TripoSR reconstructions that exist so far (a car and two trucks), re-prepared from their **preserved raw meshes** with the
corrected pipeline (`scripts/reprepare_raw_mesh.py`, then `scripts/score_model.py`). **No new inference**: the raw meshes come from
the owner's earlier Colab runs (hashes below); only the preparation and the GLB writer changed. These replace the prepared GLBs listed in
[`../../ai/ERRATUM-texture-alignment.md`](../../ai/ERRATUM-texture-alignment.md), whose baked colour was scrambled AND, as a third defect
found by importing the files into Blender, mirrored vertically by the GLB writer.

| Label | Reference image | Raw mesh (SHA-256 prefix) | Prepared GLB (SHA-256 prefix) | IoU | W/L, H/L | Proportions | Validation |
|---|---|---|---|---|---|---|---|
| `blue-suv` | Premium Blue SUV Studio Render.png | `01-Premium Blue SUV Studio Render-raw.glb` `04515371fab2efc4…` | `89985541b74cb523…` | 0.94 | 0.64 / 0.50 | implausible | NEEDS_REVIEW |
| `golden-hour-truck` | ARO 480 Truck at Golden Hour.png | `01-ARO 480 Truck at Golden Hour-raw.glb` `8c5d0615ed8b88fa…` | `e7fba3a289243bba…` | 0.92 | 0.85 / 0.86 | implausible | NEEDS_REVIEW |
| `sunset-hauler-truck` | ARO African Roads Sunset Hauler.png | `01-ARO African Roads Sunset Hauler (3)-raw.glb` `376aa3541b91df68…` | `bff3f941141b3031…` | 0.90 | 0.76 / 0.77 | implausible | NEEDS_REVIEW |

What you can see now: `views/improved-*.png` come from the Studio's software renderer (baked texture, sampled per triangle, so they look
faceted). `views/blender-*.png` (truck golden hour and SUV) are **Blender 5.0.1 / Cycles renders of the exported GLB**: an independent reader
with real texture sampling and lighting. The SUV is blue with a dark grille, glass and wheels and a red tail-light where the reference has
one; the truck is black with orange running lights and rims in the right places. `*-sheet.png` is the reference-comparison sheet (grey
shading, outline overlay).

Independent checks (Blender 5.0.1, `tests/test_blender_export.py` and a run over these three files): each GLB re-imports with the same
triangles and real-world size, and FBX (Unity and Unreal conventions), USD and .blend written from them re-import intact (12 of 12 round
trips pass: triangles, size in metres, materials, base-colour map). Not done: opening any file in Unreal Engine or Unity.

What this does NOT show:

* **The geometry limits are unchanged**: all three still fail the proportion floor (see `../triposr-baseline/` and
  `docs/architecture/product-reassessment.md`), the SUV still stands on an invented ground disc, wheels are shallow relief.
* Size is a **1 m placeholder** (no real dimensions were supplied); forward direction is a guess; no vehicle specification, so validation is NEEDS_REVIEW.
* **Not production-ready, not human-reviewed, not imported into Unity** (no editor here).
* Khronos validator was not run in this sandbox (no Node package); the internal export verification passed.
