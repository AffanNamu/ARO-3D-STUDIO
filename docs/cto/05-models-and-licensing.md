# 05 · AI model assessment and licensing report (Phase 2)

Audit date: 2026-11-08 · Status: **PARTIAL.** Code licences were read from the projects' own `LICENSE` files on GitHub (grade G). Hugging Face is blocked in the sandbox, so **no weights licence was read at source**; weights are marked unverified until the owner or a session with access reads each model card. Hardware and speed figures come from secondary sources (T) and must be measured (experiments below). Nothing here is a quality ranking: **no stronger-engine output has been inspected yet.**

## 1. Licence classes used by the platform

| Class | Meaning | May be enabled for paying users |
|---|---|---|
| A | Code and weights licences read at source; commercial use of weights and outputs allowed; no territory limit | yes |
| B | Allowed with conditions we can meet (revenue cap, registration, attribution) | yes, after the owner accepts the conditions in writing |
| C | Evaluation only (restrictions we cannot accept for a global service) | **no** |
| D | Blocked (non-commercial or unknown) | **no** |

Rule, enforced twice: the Studio's existing licence gate refuses to run an unverified engine, and `schema.sql` makes it impossible to set `enabled = true` unless `licence_status = 'verified'`. A person (never the agent) records `verified_by` and `verified_at`.

## 2. Candidates

| Model | Task | Code licence (G) | Weights licence | VRAM / speed (T, unmeasured) | ARO experience | Class today |
|---|---|---|---|---|---|---|
| **TRELLIS.2** (Microsoft, 4B) | image to 3D with PBR textures | MIT | summaries say MIT; **unverified** | README asks 24 GB+; about 3 s at 512 and 17 s at 1024 on an H100 | plug-in written from docs, never run | pending (target A) |
| TRELLIS (v1) | image to 3D, textured | MIT | unverified | lower than TRELLIS.2 | not integrated | pending |
| **TripoSG** (VAST) | image to geometry (no texture) | MIT | unverified | documented as needing about 8 GB or more (`docs/architecture/gpu-worker.md`); one job completed on a 15 GB T4 with a CPU marching-cubes stand-in | one job completed on a T4 (owner log); mesh never inspected | pending (target A) |
| **TripoSR** | fast image to 3D | MIT | MIT: recorded from the **project owner's statement**; a pinning script also checks the Hub licence tag is `mit` at the locked revision. The model card itself was never fetched by the agent (`docs/models/model-licenses.md`) | fits a T4 | real runs; vehicle proportions fail | A (weights licence from owner statement + machine-checked tag) |
| **Step1X-3D** (StepFun) | geometry + texture | Apache-2.0 | unverified | not measured | never run | pending |
| Direct3D-S2 | high-resolution geometry | MIT | unverified | not measured | never run | pending |
| Hunyuan3D-2 / 2.1 | shape + PBR texture | **Tencent Community Licence: "does not apply in the European Union, United Kingdom and South Korea"** | same licence | shape about 10 GB, texture about 21 GB (T) | plug-in written, never run | **C** |
| Stable Fast 3D (Stability) | very fast image to 3D | Stability AI Community Licence: free below US$1,000,000 annual revenue, registration required, terminates above it | same | under 1 s (T) | not integrated | B (conditions) |
| Pixal3D | image to 3D | "MIT" per one blog (T) | unknown | unknown | none | D until read |
| UniRig (VAST) | auto-rigging | MIT | unverified | about 8 GB (T) | none | pending |
| FLUX.1-schnell | text to image (first stage of text-to-3D) | n/a | Apache-2.0 per card mirrors (S) | about 12B parameters, 1 to 4 steps | none | pending |
| FLUX.1-dev | text to image | n/a | non-commercial (T) | | | **D** |
| Hunyuan3D-Paint 2.1 | mesh-conditioned PBR texture | as Hunyuan | as Hunyuan | about 21 GB | none | **C** |
| UniTEX, RomanTex, MV-Adapter | texture/multiview | not checked | not checked | | none | D until read |

Other findings from the repository (R): `xatlas` (UV unwrap) and `trimesh` are MIT; Blender's `bpy` is GPL-3.0 and `pymeshlab` is believed GPL-3.0 (see audit R-06). The Hunyuan3D licence also forbids using its outputs to train other models and has a large-user threshold (`docs/models/model-licenses.md`, section 2b).

## 3. Hidden dependencies that decide whether a model is really usable

A model's own licence is not enough. For every candidate the audit must also read the licences of: the **image encoder** it loads (image encoders can carry their own terms), the **background-removal model** it calls (BRIA RMBG-2.0 is non-commercial; the Studio avoids this by requiring a cut-out and by allowing only `u2net`-class matting), any **diffusion base model** used for textures, and every file the pipeline downloads at runtime. For TRELLIS.2 this has **not** been done (the pipeline configuration was not reachable).

## 4. Recommended strategy (a choice per task, not one model for all)

| Task | Primary | Fallback | Condition |
|---|---|---|---|
| Image to 3D with PBR | TRELLIS.2 | TripoSG + our projection/bake pipeline; Step1X-3D | weights licence and hidden dependencies read; E1 shows valid GLBs and acceptable proportions |
| Geometry-only high detail | TripoSG or Direct3D-S2 | TripoSR | E2 |
| Text to 3D | FLUX.1-schnell then the image-to-3D primary | none | licence read; E3 |
| Retexture an existing mesh | **no clean candidate yet** | none | research spike; do not ship a restricted model |
| Character rigging | UniRig | none | weights licence; E4 |
| Remesh, UV, LOD, collision, validation | conventional code we already own | | none |

Reasons: TRELLIS.2 is the only candidate described as producing full PBR and under an MIT code licence (T for the PBR claim); Hunyuan3D is excluded by a territory limit that a global platform cannot meet; texturing arbitrary meshes is the weakest open area and is a research item, not a promise.

## 5. Experiments (small, controlled, capped)

Common rules: use an on-demand **Pod**, not a Serverless endpoint, so cold-start and idle billing do not blur the measurement; stop the Pod when finished and confirm in the console; record GPU, image tag, time, peak VRAM and cost per run; keep raw meshes out of git.

| ID | Question | Setup | Proposed cap | Pass criteria |
|---|---|---|---|---|
| E1 | Does TRELLIS.2 run, how fast, how good, what does it cost? | one 48 GB Pod (a quoted on-demand rate for an L40S is $0.79 per hour, S) for at most 2 hours; the 6-image benchmark subset; existing `scripts/engine_bakeoff.py` against `aro_worker` | $3 | at least 5 of 6 valid GLBs; measured VRAM/time/cost recorded; weights licence and hidden dependencies read and recorded; Pod confirmed stopped |
| E2 | Are TripoSG / Step1X-3D better or cheaper? | same Pod after E1 | $1.50 | same recorded metrics |
| E3 | Text to 3D through FLUX.1-schnell | same Pod | $1 | 10 prompts produce valid GLBs |
| E4 | Is UniRig usable on generated characters? | an 8 GB-class Pod | $1 | 5 characters get a skeleton and play an animation in Blender |
| E5 | A licence-clean retexture path | desk research only | $0 | a named candidate with licence read, or a documented "no" |

Proposed total experiment ceiling: **$7**, set by the owner before anything runs. Each experiment needs the owner's go-ahead because it spends money.

## 6. What this changes in the repository

No code change yet. Phase 4 adds a RunPod handler around the chosen engine plug-in, a `model_registry` row per enabled model, and the licence record (who read which card, when).
