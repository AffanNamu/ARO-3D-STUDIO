# Partial real-inference runs (NOT the acceptance evidence)

Each folder is the unmodified `smoke-evidence.json` + `smoke-report.md` of ONE single-image run of `scripts/real_inference_smoke.py`
on a Colab Tesla T4 (real TripoSR `stabilityai/TripoSR@5b521936…`, licence verified, pinned weights). Every one reports **PARTIAL**
because a run needs ≥ 3 genuinely different images including a vehicle and a non-vehicle. They show that real inference, preparation and
verified export worked for these images; they do **not** satisfy the coverage rule, and `human_review` is still PENDING.

| Folder | Studio commit | Image | Raw mesh SHA-256 | Triangles (raw) |
|---|---|---|---|---|
| `2026-10-23-hauler-single-image` | `72ad96c6` | ARO African Roads Sunset Hauler (truck) | `376aa354…bb646` | 156,597 |
| `2026-10-25-golden-hour-single-image` | `9540e801` | ARO 480 Truck at Golden Hour (truck) | `8c5d0615…268cd` | 176,628 |
| `2026-10-23-suv-single-image` | `60eadb39` | Premium Blue SUV Studio Render (categorised `heavy_truck` by mistake) | `04515371…` | 117,262 |

The same truck image produced the identical raw mesh hash in two different runs (`376aa354…`), i.e. inference is deterministic here.
The complete evidence (≥ 3 images) goes to `../smoke/` only after a full run has finished.

## `2026-10-25-golden-hour-single-image` (the first complete, self-consistent package)

Studio `9540e801`, transformers 4.46.3, Tesla T4. Besides the JSON and report it holds the **prepared GLB** and its six smooth-shaded views.
Checked independently of the Colab run: the GLB SHA-256 equals `export.sha256_download`, the raw mesh equals `output_sha256`, the input equals
`input_sha256`; the per-node audit passes (5 nodes, all manifold, LOD0 + collider closed, collider convex, 252 ≤ 255 triangles); the Khronos
glTF-Validator reports 0 errors / 0 warnings; validation is NEEDS_REVIEW 75.3 % (vehicle metadata missing, placeholder 1 m size). Still
**PARTIAL** (one image) and `human_review` PENDING.

The same preserved raw mesh re-prepared with yaw alignment and smoothing switched off, for comparison: surface roughness 18.6° → **14.1°**
with them on; the footprint was rotated −35.4° (aspect 1.17 — close to the 1.15 threshold below which alignment is skipped, so a less confident
call than on the Sunset Hauler mesh, where it was 1.32). The prepared GLB's longest axis is a 1 m PLACEHOLDER.
