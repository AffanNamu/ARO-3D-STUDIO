# Implementation report — general-purpose image-to-3D milestone

Code verified at `b1b6a8a` — **CI run 44: all 7 jobs green**; the report-only commit `10c1c3f` — **CI run 45: green**
(lint/format/types/security, Python 3.10 / 3.11 / 3.12 tests, browser e2e, Docker build, reference-asset acceptance).
The evidence-completion commit that follows is listed in the changelog below with its own CI result.

## Verdict

| Requirement | Status |
|---|---|
| Baseline CI green (format failure fixed) | **PASS** (`de73a8d`, runs 38–39; run 44 on the final code) |
| Batch upload UI works, no browser errors | **PASS** — browser test with a labelled test-double engine; **now runs in CI** |
| Real image-to-3D proven through the Studio with the real engine | **PARTIAL.** Real TripoSR inference ran through the Studio on a Colab T4 for single images (truck Sunset Hauler twice, same raw hash; a second truck, Golden Hour, at `9540e801` with the per-node audit; SUV once): [`partial-runs/`](acceptance/evidence/ai/partial-runs/README.md). Each run is PARTIAL by the coverage rule. The complete ≥ 3-image run is **outstanding** |
| Real raw outputs from ≥ 3 non-procedural images | **NOT YET** (truck + SUV exist, from separate runs; no non-vehicle, no single run with ≥ 3) |
| Generic preparation preserves raw, reports steps, versions outputs | **PASS on a synthetic mesh** (not AI output) |
| Verified GLB export reopened and checked | **PASS** (checksum + re-open + Khronos in CI) |
| Limitations documented | **PASS** ([audit](architecture/image-to-3d-audit.md), [evaluation plan](models/model-evaluation.md)) |
| Production-ready | **NOT CLAIMED** |

## What changed (this milestone)

* **CI honesty:** the browser job had been reporting `1 skipped` (Chromium not found) — it never ran, and three assertions were stale
  (TITAN model/triangle count, licence wording, a viewer race). Fixed; `ARO_E2E_REQUIRED=1` makes a missing browser a failure.
* **Batch screen** (`ui/static/js/views/batch.js`): thumbnails, client-side validation per image, independent name/category,
  remove, drag-and-drop, per-item progress, plain-language failures + recommended action, Edit-and-retry / Re-queue, Open asset,
  explicit "batch is not multi-view". A server-rejected file leaves its valid siblings running (tested in a browser).
* **Preparation path** (`processing/ai_pipeline.py`): category-aware notes (no vehicle guidance for a chair), an unsupplied size is
  flagged as a PLACEHOLDER (the UI no longer pre-fills one), a failed texture bake degrades to untextured geometry and says so,
  final extents reported; convex-hull budget fix for smooth meshes (earlier).
* **Taxonomy:** `furniture`, `household_object`, `equipment` (group `objects`), additive.
* **Real-inference proof tooling:** `scripts/real_inference_smoke.py` (drives the Studio API; ≥ 3 images incl. vehicle + non-vehicle;
  invalid-file probe; `force=true`; licence from the lock only; BLOCKED when the engine cannot run; `--double` can never count),
  `notebooks/aro_real_inference_colab.ipynb`, extended gated tests, smoke evidence reader feeding the acceptance components.
* **Docs reconciled** with the lock (revision + checksums are pinned; `ModelLock.missing()` is empty) — stated as a complete
  *identity* pin, not as proof that inference works.
* UI bug: finished job cards printed the text "null".

## Tests run

| Gate | Result |
|---|---|
| Local regression (`scripts/run_regression.py`, before the last two small fixes) | 272 tests: **267 passed, 5 skipped, 0 failed**; ruff, format, mypy, bandit, pip-audit, licence audit, browser e2e (2 tests), acceptance run all PASS |
| CI run 44 (`b1b6a8a`) | **all green**; browser e2e executed for real |
| Skipped (5) | `tests/test_triposr_real.py` — need `ARO_RUN_MODEL_TESTS=1` and the model. **A skip is not a pass** |
| Not run | Unity 6 import (no editor); any real model inference |

## Verification matrix — what is established, and by what

| Claim | Implemented & unit-tested | Browser e2e | **Actual AI inference** | **Generic prep + export of real AI output** | State |
|---|---|---|---|---|---|
| Image upload, content validation, invalid-file rejection | ✅ | ✅ (batch screen) | n/a | n/a | verified |
| **One-click Convert to 3D** (`/api/convert`, `processing/convert.py`): reconstruct → prepare → export in one job, per-step status, fail-fast without creating anything, earlier results kept on a later failure | ✅ (15 tests, test double) | ✅ (full flow + rejected file + real GLB download) | ❌ not run | ❌ | verified for orchestration only |
| Batch: independent jobs/assets, per-image name+category, partial failure | ✅ (API) | ✅ (test-double engine, labelled in the UI) | ❌ not run | ❌ | verified for plumbing only |
| TripoSR adapter, licence gate, weight SHA-256 verification, safe load, class allow-list | ✅ (stand-ins that record call order) | n/a | ✅ **executed on real weights** (T4, Colab, evidence in `partial-runs/`); a first run failed honestly on a `transformers` 5.x key mismatch (see below) | ✅ truck: prepared + exported | verified on the Colab stack named below; single-image runs |
| Model lock (revision `5b521936…`, checksums) | ✅ | n/a | recorded from a Colab run (`587a0b6`); not re-fetched by the author | n/a | identity pin only |
| Real inference through the Studio, ≥ 3 different images (one run) | harness + tests (`--double`, BLOCKED path) | n/a | ❌ **OUTSTANDING** (needs the 4-image notebook run: truck + chair + teapot + robot) | ❌ | **PARTIAL: only single-image runs so far** |
| Automatic preparation: raw immutable, steps reported, texture failure honest | ✅ synthetic mesh | n/a | n/a | ✅ on the real truck mesh (7 steps PASS, raw unchanged); validation NEEDS_REVIEW | verified on one real output |
| Verified GLB export reopened; **every LOD and the collision mesh audited** | ✅ (procedural + synthetic; `tests/test_glb_audit.py`) | n/a | n/a | ✅ truck: 5 nodes, all finite, LOD ladder 24k/12k/6k/2.4k, manifold, collider convex + closed + 252 ≤ 255 tris, Khronos 0 errors | verified on one real output |
| Unity 6 import | script syntax-checked only | n/a | n/a | n/a | **never executed** |
| Human visual review of real outputs | script + schema (refuses empty/unknown) | n/a | ❌ nothing to review yet | ❌ | pending |

## Quality work on the real truck output (this iteration)

Measured on the preserved raw mesh of the real truck run (raw SHA-256 `376aa354…`; [`reprepared/2026-10-23-sunset-hauler/`](acceptance/evidence/ai/reprepared/2026-10-23-sunset-hauler/README.md)), not on a synthetic mesh:

* **The reconstruction was yawed ~38° in its own frame**, so the axis-aligned box (1.054 × 1.028) hid the real footprint and the
  "longest horizontal extent = forward" guess was a coin flip. New `align_yaw` step: minimum-area footprint rectangle, long side on
  the forward axis, smallest rotation (keeps the front guess), skipped when the footprint is nearly square or `forward` is given.
* **Smoothing** (Taubin, 40 iterations, full resolution, before decimation): surface roughness 18.4° → 14.1°; max deviation from the
  raw surface < 0.04 % of the model size. Wheel arches survive at 40; they start to soften at ~200.
* **Topology**: the full-resolution mesh was closed and manifold; one-step quadric decimation then pinched it (23 non-manifold edges).
  Staged decimation (5 stages, 3 left) + `remove_non_manifold` (drops the smallest triangles on over-shared edges, judged on the welded
  topology so UV seams are untouched) + small-hole fill gives a manifold, watertight, consistently wound LOD0. Same for LOD1–3.
* **Validation** 67.8 % → 75.3 % (G003/G004/G005/G008/G009 cleared). The remaining failures are by design: vehicle metadata
  (V001–V010 — wheels/axles/pivots are artist work, nothing detects them), U001 (placeholder size), U004, M005.
* **New per-node audit** (`verification/glb_audit.py`, in the harness evidence; a PASS now requires it): every visual LOD and the
  collision mesh re-opened from the exported bytes — finite, no degenerate triangles, unit normals, UVs in 0..1, manifold, LOD ladder
  strictly decreasing, LOD/collider bounds consistent with LOD0, collider convex + closed + ≤ 255 triangles. It caught that LOD1–3
  were still pinched after the LOD0 fix, which the Studio's own validation (LOD0 only) did not report.
* **Optional real dimensions**: `width_m` / `height_m` (API, `reprepare_raw_mesh.py`, notebook cell 5b) stretch the model to the
  stated proportions — **only when a person supplies them; they are never guessed**; the distortion is reported.
* Evidence renders are now smooth-shaded (the export carries vertex normals; flat shading exaggerated the facet noise).

**What did not improve, and cannot with post-processing:** the cab is a box with a flat, featureless back (a single view cannot see
it), wheels are shallow embossed rings rather than separate tyres and rims, and width/height relative to length are TripoSR's
estimate (too stubby: 0.76 wide for 1.0 long after alignment). A higher marching-cubes resolution (`--preset HIGH_QUALITY`, 320) may
add detail on the GPU; it has **not been run**. A stronger model or multi-view input is the real fix
(see [model evaluation](models/model-evaluation.md)).

### Bugs the real runs exposed (all fixed, each with a test)
`transformers` 5.x renamed the ViT parameters → "Missing key(s) in state_dict" (availability check now fails fast; notebook installs
4.46.3); rembg's default model silently became BRIA RMBG-2.0 (≈ 1 GB, believed non-commercial) → explicit allow-list, `bria*` blocked;
a new run overwrote the previous run's evidence → whole previous run archived, packaging refuses an unfinished run; recent FastAPI
turns an absent `bool = Form(True)` into `False` → cache and LOD were silently off for clients omitting the field.

## Real inference: status and the exact outstanding step

**Real inference has been executed (by the project owner, on a Colab T4) for single images; the complete ≥ 3-image run has not.**
The agent environment has no GPU and cannot reach `huggingface.co`, `cdn-lfs`, GitHub git/codeload or PyTorch wheels (only PyPI,
npm and `raw.githubusercontent.com`), so every inference here was run by the owner and returned as evidence zips; **this milestone
is not complete until the 4-image run (truck + chair + teapot + robot) finishes and its evidence is committed under `smoke/`.**
Colab stack of the successful runs: Python 3.13.15, torch 2.11.0+cu130, **transformers 4.46.3** (TripoSR pins 4.35.0, which has no
Python 3.13 wheels), tokenizers 0.20.3, huggingface-hub 0.36.2, torchmcubes `a9ac95aa` (CUDA kernels), rembg 2.0.86 with `u2net`.

Prepared (and verified here): `notebooks/aro_real_inference_colab.ipynb` — 12 ordered cells with expected output and a failure
bundle; commit-pinned TripoSR clone with a checkout assertion; the Studio's own availability report + `verify_triposr_weights.py`
**before** any generation; no licence override, no test double (a unit test fails if either appears); test images documented and
SHA-256-pinned (TripoSR `examples/` chair, teapot, robot — fetched and inspected from the pinned commit) plus your own vehicle
photo with a mandatory source statement. The harness now preserves input images byte-for-byte, records dimensions/hashes/source,
job ids, model revision, device and package versions, copies each raw artefact (kept out of git) and its hash, records preparation
steps and the re-opened export per item, and `fill_human_review.py` / `package_smoke_evidence.py` finish the evidence.
A dry run of the whole flow with the real example images and the test double passed; the real mode correctly ended BLOCKED
here with the exact missing-dependency reasons.

Outstanding: run the notebook (≈ 10–25 min on a T4), look at the renders, record the review, send back
`smoke-evidence-repo.zip`. I will then commit it under `docs/acceptance/evidence/ai/smoke/` and update the matrix above.

## Known limitations

* Single-image reconstruction cannot recover hidden surfaces, true size, or the front; all three stay flagged for a person.
* TripoSR's native up axis (+Z) is inferred from source; never confirmed on a real output.
* Collision is a ≤ 255-triangle convex hull of the whole mesh. No part detection, rigging or semantic parts.
* Multi-view reconstruction does not exist (not faked). Unity import unverified. Repo is public with no licence chosen.
* VRAM/latency figures for TripoSR presets are unmeasured here.

## Recommended next milestone

1. Run the Colab smoke test; commit its evidence; judge quality by eye; set the real orientation hint.
2. Only if outputs are too crude, run the [model evaluation](models/model-evaluation.md) protocol before adding any engine.
3. Then: user-supplied scale/forward in the Studio prepare form with a 3D axis preview; per-category collision (box/capsule/compound).
