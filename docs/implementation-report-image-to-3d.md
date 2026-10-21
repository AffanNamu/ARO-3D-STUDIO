# Implementation report — general-purpose image-to-3D milestone

Code verified at `b1b6a8a` — **CI run 44: all 7 jobs green**; the report-only commit `10c1c3f` — **CI run 45: green**
(lint/format/types/security, Python 3.10 / 3.11 / 3.12 tests, browser e2e, Docker build, reference-asset acceptance).
The evidence-completion commit that follows is listed in the changelog below with its own CI result.

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

## Verification matrix — what is established, and by what

| Claim | Implemented & unit-tested | Browser e2e | **Actual AI inference** | **Generic prep + export of real AI output** | State |
|---|---|---|---|---|---|
| Image upload, content validation, invalid-file rejection | ✅ | ✅ (batch screen) | n/a | n/a | verified |
| **One-click Convert to 3D** (`/api/convert`, `processing/convert.py`): reconstruct → prepare → export in one job, per-step status, fail-fast without creating anything, earlier results kept on a later failure | ✅ (15 tests, test double) | ✅ (full flow + rejected file + real GLB download) | ❌ not run | ❌ | verified for orchestration only |
| Batch: independent jobs/assets, per-image name+category, partial failure | ✅ (API) | ✅ (test-double engine, labelled in the UI) | ❌ not run | ❌ | verified for plumbing only |
| TripoSR adapter, licence gate, weight SHA-256 verification, safe load, class allow-list | ✅ (stand-ins that record call order) | n/a | ❌ **never executed on real weights in committed evidence** | n/a | **unverified on real hardware** |
| Model lock (revision `5b521936…`, checksums) | ✅ | n/a | recorded from a Colab run (`587a0b6`); not re-fetched by the author | n/a | identity pin only |
| Real inference through the Studio, ≥ 3 different images | harness + tests (`--double`, BLOCKED path) | n/a | ❌ **OUTSTANDING** | ❌ | **blocked: no GPU / no Hugging Face in the agent environment** |
| Automatic preparation: raw immutable, steps reported, texture failure honest | ✅ synthetic mesh | n/a | n/a | ❌ not yet on real output | synthetic only |
| Verified GLB export reopened | ✅ (procedural + synthetic) | n/a | n/a | ❌ not yet on real output | procedural only |
| Unity 6 import | script syntax-checked only | n/a | n/a | n/a | **never executed** |
| Human visual review of real outputs | script + schema (refuses empty/unknown) | n/a | ❌ nothing to review yet | ❌ | pending |

## Real inference: status and the exact outstanding step

**No real inference has been executed or committed.** The agent environment (re-probed for this milestone) has no GPU and cannot
reach `huggingface.co`, `cdn-lfs`, GitHub git/codeload or PyTorch wheels (only PyPI, npm and `raw.githubusercontent.com`), so
neither the weights nor the TripoSR source can be fetched here. I therefore prepared the run for you to execute; **this milestone is
not complete until you do.**

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
