# Image-to-3D path audit (branch head `0cc6100` + this change set)

What exists, what is partial, what is missing. Every row names the code that implements it.

| Capability | State | Where |
|---|---|---|
| Image upload, content validation (magic bytes, not filename/MIME), size + pixel limits, content-hash storage, sanitised names | **Implemented, tested** | `projects/sources.py`, `imaging/validate.py`, `security/`, `POST /api/projects/{pid}/sources` |
| Preprocessing (EXIF, background analysis, matte/rembg, crop, resize, 50 % grey composite = upstream TripoSR input) | **Implemented, tested** | `imaging/preprocess.py` (matches upstream `run.py`) |
| Engine abstraction, registry, licence gate, blocked models | **Implemented, tested** | `engines/base.py`, `registry.py`, `manager.py` |
| TripoSR adapter: pinned code commit, verified weights, safe load, config class allow-list | **Implemented; unit-tested with stand-ins; never executed on real weights in committed evidence** | `engines/triposr.py`, `weights.py`, `locks/triposr.json` |
| Licence/availability reporting | **Implemented**: `ModelLock.missing()` is empty at head; availability still reports missing `torch`/`tsr` in the CPU image | `GET /api/engines` |
| Persistent generation job, cache keyed on image + model version + settings, resource preflight, failure preserved, no fake asset on failure | **Implemented, tested (test double)** | `generation/service.py`, `jobs/queue.py` |
| Raw asset provenance (engine, model version, generation id, input hash), raw immutability | **Implemented, tested** | `scene/factory.py`, `assets/service.py` |
| Batch image-to-3D (≤ 10, per-image name/category, partial failure) | **API implemented, tested**; **UI rebuilt in this change set** (previews, per-image validation, progress, retry, open asset) | `POST /api/projects/{pid}/batch-generate`, `ui/static/js/views/batch.js` |
| Automatic preparation (orient, scale, clean, decimate, bake, collision, LOD, validate) | **Implemented, tested on a synthetic mesh**; made category-aware, assumed-size flagged, texture step optional in this change set | `processing/ai_pipeline.py`, `POST /api/versions/{vid}/auto-process` |
| Verified GLB export, re-open check, Khronos validator | **Implemented, tested** | `export/`, `POST /api/versions/{vid}/export` |
| Viewer (preview GLB) | **Implemented, browser-tested** | `ui/static/js/viewer`, `GET /api/versions/{vid}/preview.glb` |
| **Real inference through the Studio with ≥ 3 representative images** | **Missing evidence.** Harness + Colab notebook + gated tests added; not yet run | `scripts/real_inference_smoke.py`, `notebooks/aro_real_inference_colab.ipynb` |
| Multi-view reconstruction (several photos → one model) | **Not implemented, not faked.** UI says so | — |
| Automatic part detection, rigging, semantic parts | **Not implemented**; flagged in `needs_human` | — |
| Unity 6 import | **Not executed** (no editor); verifier + runbook only | `docs/verification/unity-verification-runbook.md` |

## Defects found while auditing (fixed in this change set)

1. **The CI browser gate was green without running.** `_chromium()` did not find the Playwright-installed browser, so the e2e
   job reported `1 skipped`. Several assertions had gone stale unnoticed (TITAN triangle count/length, licence wording).
   Fixed: Playwright's own browser is used, `ARO_E2E_REQUIRED=1` in CI turns a missing browser into a failure, assertions derive
   from the model/lock instead of hard-coded numbers.
2. **Size was guessed silently.** The prepare form pre-filled a length and the API defaulted to 1 m; the result looked like a
   decision. Now an omitted length is reported as a PLACEHOLDER in `needs_human`.
3. **Vehicle-only guidance for every asset.** Non-vehicles were told to supply a vehicle specification. Now category-aware.
4. **One failed texture bake discarded the whole preparation.** Texturing is optional; it degrades to untextured geometry and
   says so (an over-limit triangle target is still a hard error).
5. **UI printed the text "null"** in finished job cards (`replaceChildren(null)`), and the batch screen had no previews,
   progress, per-image validation or retry.
6. **Taxonomy had no home for furniture / household objects / equipment.** Added (`objects` group), additive and compatible.

## Known limitations of the generic path

* Orientation: TripoSR's native up axis is inferred from upstream source (`+Z`); which end is the front is unknown and always flagged.
* Collision is a convex hull of the whole mesh (≤ 255 triangles); concave shapes (chair, mug handle) are approximated.
* Colour is baked from the cleaned full-resolution mesh, which carries the raw vertex colours (until 2026-10-26 it was projected from the unaligned raw mesh: see evidence/ai/ERRATUM-texture-alignment.md); geometry detail is bounded by TripoSR (≈ 256³ marching cubes).
