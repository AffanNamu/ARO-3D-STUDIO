# Partial real-inference runs (NOT the acceptance evidence)

Each folder is the unmodified `smoke-evidence.json` + `smoke-report.md` of ONE single-image run of `scripts/real_inference_smoke.py`
on a Colab Tesla T4 (real TripoSR `stabilityai/TripoSR@5b521936…`, licence verified, pinned weights). Every one reports **PARTIAL**
because a run needs ≥ 3 genuinely different images including a vehicle and a non-vehicle. They show that real inference, preparation and
verified export worked for these images; they do **not** satisfy the coverage rule, and `human_review` is still PENDING.

| Folder | Studio commit | Image | Raw mesh SHA-256 | Triangles (raw) |
|---|---|---|---|---|
| `2026-10-23-hauler-single-image` | `72ad96c6` | ARO African Roads Sunset Hauler (truck) | `376aa354…bb646` | 156,597 |
| `2026-10-23-suv-single-image` | `60eadb39` | Premium Blue SUV Studio Render (categorised `heavy_truck` by mistake) | `04515371…` | 117,262 |

The same truck image produced the identical raw mesh hash in two different runs (`376aa354…`), i.e. inference is deterministic here.
The complete evidence (≥ 3 images) goes to `../smoke/` only after a full run has finished.
