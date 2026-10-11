# Implementation report — general-purpose image-to-3D milestone

Code state verified: `b1b6a8a` on `claude/zen-johnson-je3dzk` — **CI run 44: all 7 jobs green** (lint/format/types/security,
Python 3.10 / 3.11 / 3.12 tests, browser e2e, Docker build, reference-asset acceptance). This report is committed afterwards.

## Verdict

| Requirement | Status |
|---|---|
| Baseline CI green (format failure fixed) | **PASS** (`de73a8d`, runs 38–39; run 44 on the final code) |
| Batch upload UI works, no browser errors | **PASS** — browser test with a labelled test-double engine; **now runs in CI** |
| Real image-to-3D proven through the Studio with the real engine | **NOT PROVEN.** Harness, gated tests and Colab notebook exist; no committed run. Sandbox: no GPU, Hugging Face blocked |
| Real raw outputs from ≥ 3 non-procedural images | **NOT PRODUCED** |
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

## Real inference evidence

None. The lock was completed from a Colab run (`587a0b6`), and that run exposed a recorder bug (`2192c6c`), but no inference output
was committed. Exact next step: run `notebooks/aro_real_inference_colab.ipynb` (free T4) with a vehicle photo you may use plus two
TripoSR example objects, look at the renders, fill in `human_review`, and commit `docs/acceptance/evidence/ai/smoke/`. Until
then the acceptance report keeps components 3 and 4 at BLOCKED.

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
