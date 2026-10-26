# Product reassessment: from a TripoSR wrapper to a game-asset generation platform

Written 2026-10-26 after the owner rejected the direction of the project. This document is the decision, the evidence behind it,
the roadmap tied to this repository, and an honest account of what exists and what does not. Status words: PASS / PARTIAL /
BLOCKED / FAIL only.

## 1. Decision

1. **The quality ceiling is the generator, not our post-processing.** TripoSR (2024, feed-forward, one image, 256³ marching
   cubes) produces lumpy surfaces, stubby proportions and, on cars, an invented ground platform. We measured it (section 3):
   all three baselines fail the proportion floor although their silhouettes match the photo at IoU 0.91-0.94. Cleaning,
   smoothing, decimating and baking cannot restore depth or detail the model never produced. Weeks of preparation fixes were
   necessary (the pipeline is now sound for game budgets) but they were never going to close this gap.
2. **Direction: a hybrid pipeline with a swappable, GPU-hosted generator.**
   * The Studio stays the light product layer: upload, settings, progress, 3D viewport, preparation (orientation, scale, cleanup,
     decimation, UV and texture bake, LODs, collision), validation, Unity export. It keeps working with no GPU at all.
   * Generation moves behind a **GPU worker** (`aro_worker/`, protocol in `docs/architecture/gpu-worker.md`) that hosts
     heavyweight engines in their own CUDA environment. The Studio talks to it through `aro_studio/engines/remote.py` using the
     same `ImageTo3DEngine` contract as TripoSR.
   * **Primary engine: TRELLIS.2** (Microsoft, 4B parameters, MIT code, native PBR output, 512-1536³ structured latents).
     **Secondary: TripoSG** (MIT, 1.5B, geometry only, about 8 GB VRAM) for small GPUs. **TripoSR remains** as the free local
     draft engine and the fallback.
   * A **fidelity gate** (`aro_studio/quality/`) compares every result with its reference image. A valid GLB is no longer a pass.
3. **Training / fine-tuning: not now, and never from scratch.** Section 5 gives the reasoning and the measurable trigger.
4. **Not recommended:** Hunyuan3D (licence territory and output restrictions, section 4), any paid hosted API as the engine
   (earlier project rule; Meshy is a visual benchmark only), training a model from scratch (cost and data are out of proportion).
5. **What I cannot claim yet.** No TRELLIS.2 or TripoSG output exists in this repository. The sandbox has no GPU and cannot
   reach huggingface.co, so the new engines are **implemented but unrun on hardware (BLOCKED on a 24 GB-class GPU session)**.
   The statement "the studio produces convincing vehicles" is therefore **not** made by this change. The path to making it
   true is section 8, first item.

## 2. What the Meshy screenshots show, and what we copy or beat

From the three screenshots the owner supplied: Meshy 7.1 "Flagship", triangle topology, **6,354,660 faces / 3,460,732 vertices**,
a textured tractor unit with a detailed chassis and rims, generated from the dark ARO sunset image (the result in the screenshot
is white, so even the benchmark does not reproduce appearance faithfully). It is a hosted commercial service; its model and
pipeline are not public and nothing here claims to know them.

What it demonstrates, and what we do with it:

| Meshy shows | ARO 3D Studio response |
|---|---|
| Much more surface detail and a coherent texture | Engine upgrade (TRELLIS.2 PBR output) plus a high-to-low bake in the preparation step (roadmap P1) |
| Upload, settings, progress, interactive viewport, history in one workspace | Existing views already cover upload, queue, progress, viewport (`ui/static/js/viewer.js`); engine picker added in this change; a single three-pane workspace is roadmap P3 |
| 6.35 M triangles | Not usable in a game. This is where ARO should be better: budgeted LOD0-3, collision hull, one atlas, Unity package, validation (all exist today) |

The product promise ARO can make that a generic generator cannot: **a vehicle that is the right size, oriented correctly, within
a polygon budget, with LODs and collision, validated and importable in Unity 6.**

## 3. Measured baseline: TripoSR on a car and two trucks

`scripts/score_model.py` scores a prepared model against the reference image. Evidence (JSON + inspection sheets with
reference, outline overlay, best-matching view, front, side, rear, top, three-quarter) is committed in
[`docs/acceptance/evidence/quality/triposr-baseline/`](../acceptance/evidence/quality/triposr-baseline/).

| Reference | Class | Silhouette IoU (best view) | W/L | H/L | Plausible band W/L, H/L | Proportion verdict | Floor |
|---|---|---|---|---|---|---|---|
| Blue SUV studio render | car | 0.94 | 0.64 | 0.50 | 0.34-0.50, 0.27-0.45 | implausible | FAIL |
| ARO 480 truck, golden hour | heavy truck | 0.92 | 0.85 | 0.86 | 0.25-0.46, 0.40-0.66 | implausible | FAIL |
| ARO sunset hauler | heavy truck | 0.91 | 0.76 | 0.77 | 0.25-0.46, 0.40-0.66 | implausible | FAIL |

How to read this honestly:

* **Silhouette IoU is blind to depth.** One photograph is one viewpoint, so a model of the wrong length still reproduces that
  outline from some camera. That is exactly what happened: IoU 0.91-0.94 while the models are about 35-55 % shorter than a
  real vehicle of that width and height (length implied by the width ratio against the middle of the plausible band). IoU is kept as a sanity floor (right object, right outline), not as a quality score.
* **The proportion bands are my estimates** of typical vehicle dimensions, not a standard. They flag implausible results; they
  do not certify correct ones. The SUV figure is inflated by the invented ground disc; the truck failures are not.
* Looking at the sheets: the truck cab is a tall box with relief where the grille and windows should be, the chassis behind it
  is a short slab, wheels are shallow bumps, the rear is flat. The SUV reads as a car from the side but has soft panels, merged
  wheel arches and the platform. These are generator limits, which is why the next step is a different generator.
* Not measured by any number here: texture fidelity, surface detail, wheel separation, whether it "looks right". Those need eyes
  (section 9).

## 4. Engine assessment

Facts below were read from each project's own README and licence files on 2026-10 (copies kept outside the repository while
researching); nothing was run. **Weights licences must be read on the model cards before production use**: those pages were not
reachable from this sandbox, so every remote engine is recorded as licence status `claimed`, never `verified`
(`aro_studio/engines/remote.py::KNOWN`; the Studio's licence gate still applies).

| Engine | Output | Documented hardware | Code licence / restrictions that matter for ARO | Verdict |
|---|---|---|---|---|
| **TRELLIS.2** (Microsoft, 4B) | Geometry + PBR (base colour, metallic, roughness, alpha), up to 1536³; README mentions about 17 s at 1024 and about 60 s at 1536 on H100 | At least 24 GB (verified by the authors on A100/H100); Python 3.10, torch 2.6.0 cu124, compiled CUDA extensions | MIT. The upstream setup script also installs `nvdiffrec`, which is **non-commercial**: our install script omits it and the worker never imports it. `nvdiffrast` is NVIDIA's one-way commercial licence (acceptable). Image conditioning uses DINOv3, a **gated** Hugging Face model (accept terms, supply a token). The pipeline's own background removal must never run (we always pass a cut-out) | **Primary.** Best permissive quality; includes training code |
| TRELLIS (v1, 1.2B) | Geometry + texture | At least 16 GB | MIT | Fallback if 24 GB is not available; not integrated yet |
| **TripoSG** (VAST-AI, 1.5B) | High-resolution geometry only, no texture | At least 8 GB (fits a T4-class card, unmeasured) | MIT. Upstream's script uses BRIA RMBG-1.4 (**non-commercial**): we bypass it with the Studio cut-out. Pins old libraries (numpy 1.22.3 etc.) so it needs its own environment | **Secondary**; texture comes from reference-image projection (roadmap P2) |
| Hunyuan3D-2.1 (Tencent) | Geometry + PBR | 10 GB shape, 21 GB texture, 29 GB both | Tencent community licence: excludes the EU, UK and South Korea (including use of outputs there), needs a separate licence above 1 M monthly active users, forbids using outputs to improve other AI models | **Off by default.** A game sold in the EU/UK, and any plan to train on outputs, collide with it. Needs legal review before any use |
| Hunyuan3D-2 / 2-mini | Geometry (+ texture) | 6 GB shape, 16 GB both | Same company, community licence; I only read the 2.1 text, so read the exact release | Same caution |
| Step1X-3D (StepFun) | Geometry + texture | 27-29 GB for both stages | Apache-2.0 | Heavier than TRELLIS.2 for no documented advantage; revisit only if TRELLIS.2 disappoints |
| SAM 3D Objects (Meta) | Objects / scenes | Not evaluated in depth | Custom SAM licence | Not a vehicle-asset generator; skipped |
| TripoSR (current) | Vertex-coloured mesh | About 6 GB; seconds on a T4 | MIT, weights pinned and checksummed here | Keep as local draft and fallback |

Colab is the wrong host for TRELLIS.2: it needs Python 3.10 with torch 2.6/cu124 and a matching `nvcc`, while Colab ships
Python 3.13/CUDA 13, and a T4 has no bf16. That is why the heavy engines live in a worker with their own environment
(`worker/install_engines.sh`, `worker/Dockerfile`) rather than in the notebook.

## 5. Do we need to train or fine-tune?

**Recommendation: no training now. Measure the best pretrained engine first; fine-tune only if it fails specific, measured gates.**

* *From scratch:* not justified. It needs millions of 3D assets with clean licences and many GPU-weeks. No part of ARO's budget
  or data supports it, and pretrained models already exceed what we could build.
* *Fine-tuning TRELLIS.2 on vehicles* is possible in principle (the repository ships training code). What it would need:
  1. **Data:** thousands of vehicle meshes (cars, trucks, buses) with licences that permit training and commercial use, each
     with rendered views. Public collections mix per-object licences and need filtering; ARO's own assets are far too few. Output
     of Hunyuan3D must not be used (its licence forbids it). Estimating cost here would be guessing: the data work (licensing,
     cleaning, rendering) is likely larger than the compute.
  2. **Compute:** at least A100/H100-class GPUs, several of them, for days. Unmeasured; do not budget from this document.
  3. **Gate (the trigger):** run the bake-off (`scripts/engine_bakeoff.py`) on at least 10 varied vehicle images. Fine-tuning
     becomes justified only if, after the other fixes below, the failure is systematic (for example proportion verdict
     "implausible" on more than 20 % of cases, or wheels fused to the body in most), and it is not fixable by cheaper means.
* *Cheaper levers first:* better input (clean three-quarter renders, cut-out quality), the engine's higher-resolution presets,
  supplying real width/height to correct proportions (already supported), multi-view input when an engine supports it, vehicle
  priors in preparation (wheel detection and separation, symmetry), and reference-image projection for texture.

## 6. Target architecture

```
 Browser (upload, settings, progress, viewport, history)                       Unity 6 project
        |                                                                          ^
        v                                                                          | verified package
 ARO 3D Studio (FastAPI, aro_studio/)                                              |
   matting -> cut-out RGBA ---------------------------------------------+          |
   engine registry + licence gate                                        |          |
        |  local: TripoSR                                                v          |
        |  remote: aro_studio/engines/remote.py  --HTTP, bearer token-->  GPU worker (aro_worker/)
        |                                                                   TRELLIS.2 | TripoSG   (one GPU job at a time)
        v                                                                          |
   raw GLB kept untouched  <------------- checksummed GLB ------------------------+
        v
   preparation (processing/ai_pipeline.py): orient, yaw-align, scale to the real size, cleanup, hole fill, smooth,
   decimate to budget, UV + colour bake, LOD0-3, collision hull, final size restore
        v
   validation (50 rules) + fidelity score (quality/fidelity.py) -> export GLB / Unity package
```

## 7. What this change delivers

| Item | Status | Evidence / limit |
|---|---|---|
| Fidelity metrics: silhouette IoU with camera search, aspect error, proportion bands, inspection sheet | PASS | `aro_studio/quality/`, `scripts/score_model.py`, `tests/test_fidelity.py` (9 tests). Heuristic, documented as such |
| Three TripoSR baselines (one car, two trucks) with multi-view sheets | PASS | Section 3; evidence committed |
| GPU worker: authenticated HTTP service, one job at a time, queue, cancel, checksummed result, no placeholder geometry | PASS (protocol) | `aro_worker/`, `tests/test_remote_engine.py` (19 tests, procedural test double, not AI) |
| Studio `RemoteEngine`, registration through `ARO_WORKER_URL/TOKEN/ENGINES`, licence table kept in the Studio, availability reasons, cancel propagation, checksum check | PASS | same tests; licence gate still applies |
| Engine picker in the Generation view, one-click convert sends the chosen engine | PASS | Browser test with labelled test doubles (`tests/e2e/test_engine_picker.py`): lists engines, an unavailable one is marked and blocks conversion, the choice reaches the server. No real remote engine has been selected yet |
| TRELLIS.2 and TripoSG worker plug-ins | BLOCKED | Written from the upstream READMEs; **never run** (no GPU, no huggingface.co). Cut-out is mandatory so no non-commercial matting model can run |
| `worker/install_engines.sh`, `worker/Dockerfile` | BLOCKED | Syntax-checked only; not executed, not built |
| Bake-off harness `scripts/engine_bakeoff.py` | PASS (harness) | Run end to end over real HTTP against the test-double worker; no engine result exists |
| Final-size restore after smoothing/decimation (prepared model now has exactly the requested length) | PASS | Pipeline change; found by the bake-off run |
| Two colour-bake defects: colour was projected from the unaligned raw mesh (scrambled texture), and hole filling threw the vertex colours away so real meshes silently got no texture | PASS (fixed, regression tests, negative control run) | Found while checking the texture of a prepared SUV and then the real truck; `docs/acceptance/evidence/ai/ERRATUM-texture-alignment.md`. A bake that produces nothing is now reported as SKIPPED. Earlier prepared GLBs must be regenerated from their raw meshes; the six-view renders now show the baked texture |
| Real TRELLIS.2 / TripoSG car and truck results | BLOCKED | Needs a 24 GB-class GPU session (section 8, P0) |
| Texture/PBR carried into the prepared asset | PARTIAL | The raw PBR GLB is stored untouched; preparation still bakes from vertex colours, so PBR maps are not yet carried through (P1) |
| Meshy-style single workspace UI | FAIL (not started) | P3 |
| Unity 6 import of any new output | BLOCKED | No editor here; runbook exists (`docs/verification/unity-verification-runbook.md`) |
| Human visual review of any output | BLOCKED | Pending the owner |

## 8. Roadmap

| Phase | Work | Repository touch points | Exit criterion |
|---|---|---|---|
| **P0 first real results** | Run `worker/install_engines.sh` on a 24 GB GPU host, start the worker, run `scripts/engine_bakeoff.py` on the truck and the car, return the zip. Zero-cost alternative to see the quality ceiling first: try Microsoft's hosted TRELLIS.2 demo (I could not confirm its location from here), download the GLBs and send them; they can be prepared with `scripts/reprepare_raw_mesh.py` and scored | `worker/`, `aro_worker/engines/`, `scripts/engine_bakeoff.py`, `docs/architecture/gpu-worker.md` | Bake-off table with real engines; sheets reviewed by the owner |
| **P1 game-ready conversion** | High-to-low bake: keep the engine's high-poly mesh and PBR maps, decimate to budget, bake normal / base colour / ORM onto the UV atlas of the low mesh (needs a ray-cast baker; the current baker is vertex-colour only). Lift the 25,000-triangle UV limit (atlas pack/xatlas settings). Remove the ground-platform artefact automatically | `processing/ai_pipeline.py`, `textures/`, `lod/generator.py`, `engines/remote.py::_load_single_mesh` | Prepared car and truck keep visible panel detail at 20-50k triangles with a normal map, PBR channels present, validation green |
| **P2 vehicle intelligence** | Wheel detection and separation (distinct, rotatable wheel meshes and pivots), left-right symmetry, reference-image projection texturing for geometry-only engines (TripoSG), proportion correction hints from the fidelity score | `vehicle/`, `quality/`, `geometry/` | Wheels are separate nodes with correct pivots on the car and the truck; texture visible without the engine |
| **P3 workspace UX** | Three-pane workspace like the Meshy screenshots: settings and history left, viewport centre (wireframe, matcap, LOD switch, turntable), asset and export panel right; progress per stage | `ui/static/js/views/`, `viewer.js` | Owner can upload, generate, inspect and export from one screen |
| **P4 conditional** | Fine-tuning plan only if the section 5 gate trips | new `training/` (not created) | Gate evidence recorded before any data or compute is spent |

## 9. Acceptance gates: when I may say "this works"

All must hold for the car and the truck, on real engine output, recorded in committed evidence:

1. **Fidelity:** silhouette IoU at least 0.85 and the proportion verdict "plausible" (`meets_floor`), on the prepared LOD0.
2. **Structure:** one main component (no floating fragments, no ground platform), wheels visibly distinct in the sheets.
3. **Game readiness:** LOD0 within budget with LOD1-3, collision hull of at most 255 triangles, requested real size exact, single
   UV atlas, validation not NEEDS_REVIEW for reasons other than the declared human decisions.
4. **Human review:** the owner has looked at the six views and the sheet and recorded a verdict (`human_review` in the evidence).
5. **Unity 6:** import verified in the editor following the runbook.

Items 1-3 are measurable by the tools in this repository. Items 4-5 cannot be done by me and are never marked done without
the owner's evidence.

## 10. Costs, risks and decisions for the owner

* **Compute:** the first bake-off needs a few hours of one 24 GB-class GPU (install and compile, model downloads, then minutes
  per generation). Models are tens of GB (unmeasured). Rental of such GPUs by the hour is common and usually low single-digit
  dollars or less per hour, but I could not check current prices from here: verify before committing. I will not purchase
  anything. A GPU you already own works equally well (the worker runs anywhere with Docker and an NVIDIA driver).
* **Licences to settle before production:** read the TRELLIS.2 and TripoSG model cards (weights and outputs), accept DINOv3
  terms, and decide on Hunyuan3D only with legal advice. Then set `ARO_VERIFIED_MODEL_LICENSES` yourself.
* **Operational:** the worker is a network service protected by a bearer token; expose it only over a trusted network or TLS.
  One GPU job runs at a time, others queue.
* **Unknowns that may change this plan:** TRELLIS.2's real output on ARO vehicles (the whole plan hinges on it), whether the
  24 GB path is affordable for the team, and whether the installer works unchanged on your host. If TRELLIS.2 disappoints, the
  fallbacks are TripoSG with texture projection, then Step1X-3D, then the fine-tuning gate.

## 11. Addendum (later on 2026-10-26): what changed after the owner widened the goal

The owner asked for a platform (generation, viewport, refinement, materials, LODs, collision, reliable exports for Unity, Blender, Unreal)
and for the next milestone to be real stronger-engine results on a Colab T4, compared with TripoSR. What was built, and what it found:

* **Colab engine lab** (`notebooks/aro_engine_lab_colab.ipynb`): TripoSG on a free T4 (the Hunyuan3D shape model only if switched on, as an
  evaluation yardstick under a restricted licence), in an isolated Python 3.10 environment, through the Studio, compared with the
  committed TripoSR numbers for the same image. The environment was rehearsed on CPU here ([lab-environment-rehearsal.md](../verification/lab-environment-rehearsal.md)):
  the pinned stack resolves and installs, every third-party import of TripoSG and of Hunyuan3D's shape stage resolves, the `diso` stand-in
  works with real torch, the worker runs under Python 3.10. **Not rehearsed:** weights, GPU inference, speed, memory. **Still no result from
  any stronger engine.**
* **Independent verification with Blender** (`aro_studio/export/blender*.py`): Blender 5.0.1 re-imports what the Studio exports. This found
  a defect no earlier check could see: **the GLB writer mirrored every texture vertically** (also in Unity packages and, by implication,
  the in-app viewer). Fixed, with two regression tests that fail on the old writer. Details in `evidence/ai/ERRATUM-texture-alignment.md`.
* **FBX (Unity and Unreal conventions), USD, .blend export**, each re-imported by Blender and compared; 12 of 12 round trips of the three
  real vehicles pass (triangles, size in metres, materials, base-colour map). Opening them in Unreal or Unity: not done.
* **Normal-map transfer** from a dense engine mesh to the game mesh (P1): built and tested on synthetic surfaces (analytic normals recovered
  within 3 degrees); on by default for every engine except TripoSR; not yet seen on a real dense mesh.
* **Up-axis detection** from the reference image and **photo projection texturing** for geometry-only engines: built, tested against known
  answers; not yet seen on real TripoSG output.
* A bigger vision document (`platform-roadmap.md`) and a conditional fine-tuning plan with a gate (`fine-tuning-plan.md`).

The decision in section 1 stands: the quality ceiling is the generator, and the evidence that would move it is the lab run.

