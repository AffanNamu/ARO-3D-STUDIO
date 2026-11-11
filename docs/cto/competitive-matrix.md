# Competitive capability matrix (ARO 3D AI STUDIO vs Meshy AI)

> Generated from [`competitive-matrix.json`](competitive-matrix.json) by `scripts/build_competitive_matrix.py`. Edit the JSON, not this file.
> Audit date: 2026-11-08. Ongoing competitive development tracker against Meshy AI. A capability is complete only when the whole user workflow works.

## How to read the evidence

* **R**: Verified in this repository.
* **G**: Read at the primary source during the audit: Meshy's published OpenAPI file and documentation, RunPod and Google Cloud pricing pages, Hugging Face model-card metadata, GitHub LICENSE and source files.
* **S**: Search summary citing an official page that was not opened. No Meshy claim in this file remains at this grade.
* **T**: Third-party site only; unreliable.
* **O**: Owner-reported or owner-provided screenshot; not independently verified.

## Status definitions

* **Not investigated**: Nothing looked at yet.
* **Investigated**: Researched; findings recorded; no code.
* **Planned**: Design accepted, no code.
* **In development**: Code being written on a branch.
* **Implemented**: Code exists and automated tests pass, but the complete user workflow has not been proven end to end on real data.
* **Implemented but unverified**: Code exists but has only been exercised with test doubles, synthetic data or not at all against the real thing it depends on.
* **Fully tested**: The complete workflow passes automated tests AND has been run on real data, with the evidence recorded in the repository.
* **Production ready**: Fully tested, security-reviewed, load- and cost-tested, monitored, with owner sign-off. No capability has this status.

## Priorities

* **P0**: Needed for the first end-to-end pipeline (phases 3-5).
* **P1**: Meshy-class core.
* **P2**: Extended parity.
* **P3**: Advanced / later.

## Totals

| Status | Capabilities |
|---|---|
| Not investigated | 11 |
| Investigated | 3 |
| Planned | 15 |
| In development | 0 |
| Implemented | 28 |
| Implemented but unverified | 11 |
| Fully tested | 1 |
| Production ready | 0 |

Total: 69. **No capability is Production ready; claiming parity with Meshy is not supported by any row.**

## Overview

| ID | Capability | Kind | Meshy offers it (evidence) | ARO status | Priority |
|---|---|---|---|---|---|
| A1 | Text-to-3D | AI | yes (G) | Investigated | P1 |
| A2 | Image-to-3D (single image) | AI | yes (G) | Implemented but unverified | P0 |
| A3 | Multi-image-to-3D | AI | yes (G) | Not investigated | P2 |
| A4 | Model versions and generation styles | AI | yes (G) | Implemented but unverified | P1 |
| A5 | Geometry controls (polycount, topology, pose) | Mixed | yes (G) | Implemented but unverified | P1 |
| A6 | Output format selection | Conventional | yes (G) | Implemented | P1 |
| A7 | Generation history and versions | Platform | yes (S) | Implemented | P0 |
| A8 | Regeneration and variations | AI | yes (G) | Implemented but unverified | P1 |
| A9 | Character generation | AI | yes (G) | Not investigated | P2 |
| A10 | Text-to-image and image-to-image (concept generation) | AI | yes (G) | Not investigated | P2 |
| A11 | Conversational creation agent | AI | yes (G) | Not investigated | P3 |
| B1 | AI texture on a generated shape (PBR) | AI | yes (G) | Planned | P1 |
| B2 | Retexture an existing mesh from text | AI | yes (G) | Investigated | P2 |
| B3 | Image-guided texturing | Mixed | yes (G) | Implemented but unverified | P1 |
| B4 | PBR map set (base, roughness, metallic, normal, AO) | Mixed | yes (G) | Implemented but unverified | P1 |
| B5 | Texture resolution control | Conventional | yes (G) | Implemented | P2 |
| B6 | Texture refinement and regeneration | AI | yes (G) | Planned | P2 |
| B7 | Material preview and inspection | Conventional | yes (S) | Implemented but unverified | P1 |
| C1 | Mesh cleanup and repair | Conventional | not found in the sources searched (none) | Implemented | P0 |
| C2 | Polygon reduction | Conventional | yes (S) | Implemented | P0 |
| C3 | Quad remesh | Conventional | yes (G) | Not investigated | P2 |
| C4 | UV generation and correction | Conventional | yes (G) | Implemented | P1 |
| C5 | Normals and normal-map transfer | Conventional | not found in the sources searched (none) | Implemented | P1 |
| C6 | Scale and orientation | Mixed | yes (G) | Implemented | P1 |
| C7 | Model validation | Conventional | not found in the sources searched (none) | Implemented | P0 |
| C8 | LOD and collision generation | Conventional | not found in the sources searched (none) | Implemented | P1 |
| C9 | AI geometry refinement / detail upscaling | AI | yes (S) | Not investigated | P3 |
| C10 | Format conversion service | Conventional | yes (G) | Implemented | P2 |
| D1 | Interactive viewport (orbit, pan, zoom) | Conventional | yes (S) | Implemented | P0 |
| D2 | Perspective and orthographic views | Conventional | unknown (none) | Planned | P2 |
| D3 | Selection and transform gizmos | Conventional | unknown (none) | Planned | P2 |
| D4 | Scene hierarchy | Conventional | unknown (none) | Planned | P2 |
| D5 | Lighting and environment controls | Conventional | unknown (none) | Implemented | P2 |
| D6 | Undo and redo | Conventional | unknown (none) | Planned | P3 |
| D7 | Save and restore projects | Platform | yes (S) | Implemented | P0 |
| D8 | Compare versions side by side | Conventional | unknown (none) | Planned | P1 |
| E1 | Auto-rigging (skeleton and skinning) | AI | yes (G) | Investigated | P3 |
| E2 | Animation library and motion | AI | yes (G) | Not investigated | P3 |
| E3 | Pose and animation preview | Conventional | yes (S) | Planned | P3 |
| E4 | Rigged export to game engines | Conventional | yes (S) | Planned | P3 |
| E5 | Text-to-motion | AI | yes (G) | Not investigated | P3 |
| F1 | GLB export | Conventional | yes (G) | Fully tested | P0 |
| F2 | glTF (separate files) | Conventional | yes (G) | Implemented | P2 |
| F3 | OBJ | Conventional | yes (G) | Implemented | P1 |
| F4 | FBX (Unity and Unreal conventions) | Conventional | yes (G) | Implemented | P1 |
| F5 | USD and .blend | Conventional | yes (G) | Implemented | P2 |
| F6 | STL | Conventional | yes (G) | Implemented | P2 |
| F7 | USDZ and 3MF | Conventional | yes (G) | Planned | P3 |
| F8 | Unity package with verifier | Conventional | not found in the sources searched (none) | Implemented but unverified | P1 |
| F9 | Engine and DCC plug-ins | Conventional | yes (G) | Not investigated | P3 |
| F10 | 3D-printing preparation | Conventional | yes (G) | Planned | P3 |
| G1 | Personal asset library with search and filter | Platform | yes (G) | Implemented | P1 |
| G2 | Projects and folders | Platform | yes (S) | Implemented | P1 |
| G3 | Preview thumbnails | Conventional | not found in the sources searched (none) | Implemented | P1 |
| G4 | Asset metadata and versioning | Platform | not found in the sources searched (none) | Implemented | P0 |
| G5 | Deletion and restoration policy | Platform | not found in the sources searched (none) | Implemented | P1 |
| G6 | Download management | Platform | not found in the sources searched (none) | Implemented | P0 |
| G7 | Usage and credit history | Platform | yes (G) | Implemented | P1 |
| G8 | Mobile capture app | Platform | yes (G) | Not investigated | P3 |
| H1 | Authentication and accounts | Platform | yes (G) | Implemented but unverified | P0 |
| H2 | Credit ledger and billing | Platform | yes (G) | Implemented but unverified | P1 |
| H3 | Production job lifecycle | Platform | yes (G) | Implemented | P0 |
| H4 | Public API with keys | Platform | yes (G) | Planned | P2 |
| H5 | Agent / MCP integration | Platform | yes (G) | Not investigated | P3 |
| H6 | Rate limits and per-user concurrency | Platform | yes (G) | Implemented but unverified | P0 |
| H7 | Cost tracking and observability | Platform | not found in the sources searched (none) | Planned | P0 |
| H8 | Security scanning | Platform | not found in the sources searched (none) | Implemented | P1 |
| H9 | Plan-based concurrency and queue priority | Platform | yes (G) | Planned | P2 |
| H10 | Asset retention policy | Platform | yes (G) | Planned | P2 |

## A. AI 3D generation

### A1 Text-to-3D

*Kind:* AI · *ARO status:* **Investigated** · *Priority:* P1

* **What it does:** Generate a 3D model from a text prompt.
* **User workflow:** Enter prompt and options, review a geometry preview, optionally refine/texture, open in the workspace.
* **Inputs:** Prompt, style/quality options, target polycount, pose.
* **Outputs:** GLB with textures, preview image, metadata, cost record.
* **Technology:** Two stages: text-to-image, then image-to-3D (or a native text-to-3D model).
* **Candidate models / services:** FLUX.1-schnell (Apache-2.0 per card mirrors, S) then TRELLIS.2 or TripoSG; Meshy itself uses preview then refine (S).
* **GPU requirements:** 24-48 GB for the image-to-3D stage; text-to-image can share the same card.
* **Implementation complexity:** High
* **Estimated operating cost:** Estimate only: ~$0.02-0.30 per job (two GPU stages; unmeasured, see 04-architecture cost model).
* **ARO today (evidence):** Design only. No text-to-3D code exists (grep over aro_studio, aro_worker, scripts: 0 matches).
* **Work required:** Text-to-image provider, prompt safety filter, two-stage job, UI, credit pricing.
* **Acceptance criteria:** 20 benchmark prompts each give a GLB that passes output validation; prompt adherence rated blind against Meshy on identical prompts; target set by the owner after the baseline.
* **Meshy:** offers: yes (evidence G). POST /v2/text-to-3d with mode=preview (geometry) then mode=refine (texture); prompt up to 800 characters, negative_prompt, art_style (realistic), texture_prompt or texture_image_url, seed, pose_mode, texture_resolution 2k/4k/8k, optional moderation. Preview 20 credits (meshy-7.1, meshy-6) or 5 (lite, t2, t2.5); refine 10 (15 at 8K). Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml), [docs.meshy.ai/api/pricing.md](https://docs.meshy.ai/api/pricing.md)

### A2 Image-to-3D (single image)

*Kind:* AI · *ARO status:* **Implemented but unverified** · *Priority:* P0

* **What it does:** Generate a 3D model from one reference image.
* **User workflow:** Upload image (cut-out made automatically), choose engine and quality, receive a prepared model.
* **Inputs:** One image (PNG/JPEG/WebP), category, optional real length.
* **Outputs:** Prepared GLB (LODs, collision, validation report), raw engine mesh, provenance.
* **Technology:** Reconstruction model on a GPU worker, then conventional preparation.
* **Candidate models / services:** TRELLIS.2, TripoSG, TripoSR (MIT, G); Hunyuan3D is evaluation-only (restricted licence).
* **GPU requirements:** TripoSR runs on a 15 GB T4; TripoSG ran on a T4 once; TRELLIS.2 README asks 24 GB+ (T).
* **Implementation complexity:** High
* **Estimated operating cost:** Estimate only: see cost model. TripoSR/TripoSG on Colab cost nothing so far.
* **ARO today (evidence):** Studio pipeline and engine plug-ins exist (aro_studio/engines, aro_worker). Real runs: TripoSR on a Colab T4 (a four-image run whose evidence reader reports PASS with visual quality PENDING_HUMAN_REVIEW, plus earlier single-image runs recorded as PARTIAL; vehicles fail the proportion floor). TripoSG finished one job on a T4 per the owner's pasted worker log (7.2 MB GLB; mesh never inspected by me). TRELLIS.2 and Hunyuan3D never run.
* **Work required:** Select the engine by experiment E1; deploy on RunPod; add output gates.
* **Acceptance criteria:** 20 images: GLB valid for all; vehicle proportions plausible for at least 90 percent; blind comparison with Meshy on identical images reported with raw ratings.
* **Meshy:** offers: yes (evidence G). POST /v1/image-to-3d: image_url or input_task_id, ai_model (meshy-6, 6-lite, 7, 7.1, latest, t2, t2.5), model_type standard or smart-topology, should_texture, enable_pbr, texture_model, geometry_resolution standard/2k/4k, image_enhancement, remove_lighting, auto_size, origin_at. 20 credits mesh only, 30 with textures (meshy-7.1). Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml), [docs.meshy.ai/api/pricing.md](https://docs.meshy.ai/api/pricing.md), [docs.meshy.ai/api/models.md](https://docs.meshy.ai/api/models.md)

### A3 Multi-image-to-3D

*Kind:* AI · *ARO status:* **Not investigated** · *Priority:* P2

* **What it does:** Generate a model from several views of one object.
* **User workflow:** Upload 1-4 views, optionally label them, generate.
* **Inputs:** 2-4 images of the same object.
* **Outputs:** As A2.
* **Technology:** Multi-view conditioned reconstruction.
* **Candidate models / services:** TRELLIS (multi-image mode: unverified), Hunyuan3D-2mv (restricted licence), others TBD.
* **GPU requirements:** Likely as A2.
* **Implementation complexity:** High
* **Estimated operating cost:** Estimate only: as A2.
* **ARO today (evidence):** None in the repository.
* **Work required:** Research which licensed model supports multi-view conditioning; then as A2.
* **Acceptance criteria:** 10 object sets: multi-view output beats the best single-view output on blind rating.
* **Meshy:** offers: yes (evidence G). POST /v1/multi-image-to-3d takes 1 to 4 images (the official limit; a third-party claim of 8 is wrong); 4K geometry is not supported on this endpoint. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml), [docs.meshy.ai/api/pricing.md](https://docs.meshy.ai/api/pricing.md)

### A4 Model versions and generation styles

*Kind:* AI · *ARO status:* **Implemented but unverified** · *Priority:* P1

* **What it does:** Select engine/quality tier or style.
* **User workflow:** Pick a preset (draft, standard, high) or engine in the generation form.
* **Inputs:** Preset or engine id.
* **Outputs:** Same output with different cost and quality.
* **Technology:** Provider registry with versioned model entries.
* **Candidate models / services:** Own registry; Meshy exposes ai_model values such as meshy-6 and meshy-7.1 (S).
* **GPU requirements:** n/a
* **Implementation complexity:** Medium
* **Estimated operating cost:** n/a
* **ARO today (evidence):** Engine picker and presets exist in the UI and worker (tests with a test double).
* **Work required:** Registry with licence/verification fields (see 05), per-engine presets measured in E1.
* **Acceptance criteria:** Every enabled engine has measured time, VRAM and cost on the benchmark set.
* **Meshy:** offers: yes (evidence G). Geometry models: meshy-7.1 (dense detail, up to about 890k faces in the doc example), meshy-6, meshy-6-lite (30k faces, 5 credits), Smart Topology meshy-t2 and t2.5 (triangle-only, set face count). Texture models: meshy-7 (PBR up to 8K), meshy-n1 (base colour, stylised), meshy-6, meshy-6-lite. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml), [docs.meshy.ai/api/models.md](https://docs.meshy.ai/api/models.md)

### A5 Geometry controls (polycount, topology, pose)

*Kind:* Mixed · *ARO status:* **Implemented but unverified** · *Priority:* P1

* **What it does:** Control triangle budget, topology style and pose.
* **User workflow:** Set target polycount; choose triangle or quad topology; choose A/T pose for characters.
* **Inputs:** Integer target, topology enum, pose enum.
* **Outputs:** Mesh meeting the budget.
* **Technology:** Conventional decimation/remesh after generation; pose is a generation-time hint.
* **Candidate models / services:** Own pipeline (decimation); quad remesh: QuadriFlow or Instant Meshes (licences to verify); Blender.
* **GPU requirements:** none for remesh
* **Implementation complexity:** Medium
* **Estimated operating cost:** CPU only; negligible.
* **ARO today (evidence):** Triangle budget presets and 5-stage decimation exist (aro_studio/processing/ai_pipeline.py); no quad topology; no pose control.
* **Work required:** Quad remesh option, pose parameter, expose target polycount per request.
* **Acceptance criteria:** Requested budget met within 5 percent on 20 models; quad mode produces a valid all-quad-dominant mesh.
* **Meshy:** offers: yes (evidence G). target_polycount 100 to 300,000 (Smart Topology models: up to 15,000 or 30,000), topology triangle or quad (quad not for t2/t2.5), pose_mode a-pose or t-pose, symmetry_mode deprecated and ignored, origin_at, decimation_mode 1-4. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml), [docs.meshy.ai/api/models.md](https://docs.meshy.ai/api/models.md)

### A6 Output format selection

*Kind:* Conventional · *ARO status:* **Implemented** · *Priority:* P1

* **What it does:** Choose export formats when generating.
* **User workflow:** Tick formats in the generation form.
* **Inputs:** Format list (max 8).
* **Outputs:** Files for each requested format.
* **Technology:** Exporters.
* **Candidate models / services:** Own exporters, Blender.
* **GPU requirements:** none
* **Implementation complexity:** Low
* **Estimated operating cost:** CPU only.
* **ARO today (evidence):** POST /api/convert takes a formats list; GLB/glTF/OBJ/Unity package built in, FBX/USD/.blend via Blender when available (tests/test_convert.py, tests/test_blender_export.py). Multi-user platform (2026-11-11): GLB plus on-demand OBJ (zip with material and texture), STL and PLY from the web app; FBX/USD/.blend are not offered there (no Blender in the API image).
* **Work required:** Add STL/3MF/USDZ (F6, F7).
* **Acceptance criteria:** Each selected format downloads and re-imports.
* **Meshy:** offers: yes (evidence G). target_formats on every task; model URLs returned: glb, fbx, gltf, usdz, obj, mtl, vox, blend, stl, 3mf, pre_remeshed_glb. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml), [docs.meshy.ai/llms-full.txt](https://docs.meshy.ai/llms-full.txt)

### A7 Generation history and versions

*Kind:* Platform · *ARO status:* **Implemented** · *Priority:* P0

* **What it does:** Keep every generation and let the user compare or revert.
* **User workflow:** Open history, pick a version, re-open in the workspace.
* **Inputs:** Asset id.
* **Outputs:** Version list with provenance.
* **Technology:** Versioned storage.
* **Candidate models / services:** Postgres + R2 (design).
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** Negligible.
* **ARO today (evidence):** Single-tenant versions, provenance, generations table, content cache (aro_studio/assets, generation). No per-user ownership.
* **Work required:** Migrate to Postgres with owner_id and RLS.
* **Acceptance criteria:** Two users cannot see each other's history (automated RLS test).
* **Meshy:** offers: yes (evidence S). History exists in the workspace (details not opened). Sources: [help.meshy.ai/en/articles/12618267-meshy-workspace-features-and-navigation](https://help.meshy.ai/en/articles/12618267-meshy-workspace-features-and-navigation)

### A8 Regeneration and variations

*Kind:* AI · *ARO status:* **Implemented but unverified** · *Priority:* P1

* **What it does:** Generate another version with the same or changed settings.
* **User workflow:** Press regenerate, optionally change seed/prompt/settings.
* **Inputs:** Previous job id + overrides.
* **Outputs:** New version linked to the old one.
* **Technology:** Seeded generation.
* **Candidate models / services:** Providers' seed parameters.
* **GPU requirements:** As A2
* **Implementation complexity:** Medium
* **Estimated operating cost:** As A2.
* **ARO today (evidence):** Multi-user platform: 'Make a variation' re-runs the same uploaded image with a new seed (apps/web AssetPanel, seed passed to the engine through WorkerInput; tests/cloud/test_exports_and_library.py checks the seed and upload id travel with the job). Never run with a real model, so whether seeds give useful variety is unmeasured.
* **Work required:** Seed in request schema, parent_version link, UI.
* **Acceptance criteria:** Same seed reproduces within tolerance; different seed differs.
* **Meshy:** offers: yes (evidence G). seed parameter exists on text-to-3D (0 means random) but not on image-to-3D; input_task_id reuses a previous task's input; the web app gives free retries per task on paid plans. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml)

### A9 Character generation

*Kind:* AI · *ARO status:* **Not investigated** · *Priority:* P2

* **What it does:** Humanoid/animal characters in A/T pose, ready for rigging.
* **User workflow:** Choose character mode, pose, generate.
* **Inputs:** Prompt or image, pose.
* **Outputs:** Character mesh suitable for E2.
* **Technology:** Generation with pose hint; post-checks.
* **Candidate models / services:** TRELLIS.2, TripoSG; pose-conditioned models TBD.
* **GPU requirements:** As A2
* **Implementation complexity:** High
* **Estimated operating cost:** As A2.
* **ARO today (evidence):** None.
* **Work required:** Research; benchmark set for characters.
* **Acceptance criteria:** 10 characters rig successfully with E2 and pose correctly.
* **Meshy:** offers: yes (evidence G). pose_mode a-pose/t-pose; the model guide recommends meshy-t2.5 + meshy-n1 for game characters to rig. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml), [docs.meshy.ai/api/models.md](https://docs.meshy.ai/api/models.md)

### A10 Text-to-image and image-to-image (concept generation)

*Kind:* AI · *ARO status:* **Not investigated** · *Priority:* P2

* **What it does:** Generate or edit concept images, including multi-view images prepared for 3D.
* **User workflow:** Describe or upload, pick a model, get images, send one to image-to-3D.
* **Inputs:** Prompt or image.
* **Outputs:** Images.
* **Technology:** Image diffusion/edit models.
* **Candidate models / services:** FLUX.1-schnell (Apache-2.0, gated=auto, read on the Hub card 2026-11-08); others unverified.
* **GPU requirements:** 12-24 GB
* **Implementation complexity:** Medium
* **Estimated operating cost:** Estimate only (a few GPU seconds per image).
* **ARO today (evidence):** None in the repository.
* **Work required:** Needed anyway as the first stage of text-to-3D (A1).
* **Acceptance criteria:** Images generated within the budget; moderation applied.
* **Meshy:** offers: yes (evidence G). Text to Image 3 to 9 credits and Image to Image 3 to 12 credits depending on the image model. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml), [docs.meshy.ai/api/pricing.md](https://docs.meshy.ai/api/pricing.md)

### A11 Conversational creation agent

*Kind:* AI · *ARO status:* **Not investigated** · *Priority:* P3

* **What it does:** Chat that turns an idea, photo or sketch into a set of concepts and then 3D models.
* **User workflow:** Chat, pick concepts, generate.
* **Inputs:** Conversation.
* **Outputs:** Concept batch and models.
* **Technology:** LLM orchestration over the generation tools.
* **Candidate models / services:** Any LLM with tool use.
* **GPU requirements:** none (LLM API)
* **Implementation complexity:** High
* **Estimated operating cost:** LLM API cost per conversation (not estimated).
* **ARO today (evidence):** None.
* **Work required:** After the generation journeys work; optional.
* **Acceptance criteria:** n/a
* **Meshy:** offers: yes (evidence G). Marketed as '3D Agent' on every paid plan. Sources: [www.meshy.ai/pricing](https://www.meshy.ai/pricing), [docs.meshy.ai/llms-full.txt](https://docs.meshy.ai/llms-full.txt)


## B. AI texturing and materials

### B1 AI texture on a generated shape (PBR)

*Kind:* AI · *ARO status:* **Planned** · *Priority:* P1

* **What it does:** Texture produced together with the shape.
* **User workflow:** Generate with texturing enabled.
* **Inputs:** Same as A2/A1.
* **Outputs:** GLB with base colour (+ metallic/roughness) maps applied.
* **Technology:** Textured 3D generator.
* **Candidate models / services:** TRELLIS.2 (PBR; code and weights MIT, but evaluation-only until its nvdiffrast, BRIA RMBG-2.0 and DINOv3 blockers are removed, see 05); Step1X-3D (Apache-2.0 code and weights; texture stage and dependencies not yet read); TRELLIS v1 (MIT; base colour only).
* **GPU requirements:** 24-48 GB
* **Implementation complexity:** High
* **Estimated operating cost:** Estimate only.
* **ARO today (evidence):** TRELLIS.2 plug-in written from upstream docs, never run (aro_worker/engines/trellis2.py). Studio reads vertex colours only; no ORM/PBR map transfer.
* **Work required:** Run E1; map engine PBR output onto the game mesh; validate texture-to-geometry alignment.
* **Acceptance criteria:** Rendering the exported GLB in Blender shows the texture on the right surfaces (automated sampling test, as in tests/test_blender_export.py).
* **Meshy:** offers: yes (evidence G). should_texture (default true), enable_pbr, texture_richness, texture_resolution 2k/4k/8k, texture_prompt/texture_image_url; texture adds 10 credits (15 at 8K) on top of the mesh. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml), [docs.meshy.ai/api/pricing.md](https://docs.meshy.ai/api/pricing.md)

### B2 Retexture an existing mesh from text

*Kind:* AI · *ARO status:* **Investigated** · *Priority:* P2

* **What it does:** Re-generate textures for an uploaded or earlier model.
* **User workflow:** Select asset, enter style prompt, retexture.
* **Inputs:** Mesh + prompt.
* **Outputs:** New texture set on the same geometry.
* **Technology:** Mesh-conditioned texture generation.
* **Candidate models / services:** Hunyuan3D-Paint is restricted (EU/UK/KR excluded, G); UniTEX, RomanTex, MV-Adapter licences unverified (S).
* **GPU requirements:** ~21 GB for Hunyuan Paint (T)
* **Implementation complexity:** Very high
* **Estimated operating cost:** Estimate only.
* **ARO today (evidence):** Licence survey only (05-models-and-licensing).
* **Work required:** Spike: find one licensed mesh-conditioned texture model; else build on multi-view diffusion with a clear licence.
* **Acceptance criteria:** Retextured GLB keeps geometry and UVs byte-identical and passes alignment test.
* **Meshy:** offers: yes (evidence G). POST /v1/retexture: input_task_id or a GLB model_url (meshes up to 7,999,999 triangles with meshy-n1); exactly one style source: text_style_prompt, image_style_url or 1 to 4 multiview_image_urls; art_style realistic/cartoon; enable_original_uv; 10 credits (15 at 8K). Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml), [docs.meshy.ai/api/pricing.md](https://docs.meshy.ai/api/pricing.md)

### B3 Image-guided texturing

*Kind:* Mixed · *ARO status:* **Implemented but unverified** · *Priority:* P1

* **What it does:** Texture a model from a reference photo.
* **User workflow:** Pick asset, supply reference image, apply.
* **Inputs:** Mesh + image.
* **Outputs:** Textured mesh.
* **Technology:** Photo projection (conventional); AI inpainting for unseen sides (future).
* **Candidate models / services:** Own projection code; diffusion inpainting TBD.
* **GPU requirements:** none (projection)
* **Implementation complexity:** Medium
* **Estimated operating cost:** CPU only.
* **ARO today (evidence):** Camera-by-silhouette projection with visibility and mirrored unseen side, fill by diffusion (aro_studio/texturing/projection.py, tests). Not yet seen on a real stronger-engine mesh.
* **Work required:** Verify on E1 meshes; AI inpainting for occluded regions.
* **Acceptance criteria:** Projected colours match the photo at visible surface points within a set tolerance (existing test) and look right to a human reviewer.
* **Meshy:** offers: yes (evidence G). Image style via image_style_url (at least 32 px per side) and multi-view texture references on retexture and multi-image generation. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml)

### B4 PBR map set (base, roughness, metallic, normal, AO)

*Kind:* Mixed · *ARO status:* **Implemented but unverified** · *Priority:* P1

* **What it does:** Full material maps applied to the model.
* **User workflow:** Toggle PBR; inspect maps in the material panel.
* **Inputs:** Texture request.
* **Outputs:** Maps packed into glTF materials.
* **Technology:** PBR generation or estimation; baking.
* **Candidate models / services:** TRELLIS.2 output; bake normal/AO with own code.
* **GPU requirements:** 24-48 GB for generation; CPU for baking
* **Implementation complexity:** High
* **Estimated operating cost:** Estimate only.
* **ARO today (evidence):** Base colour and tangent-space normal bake implemented and Blender-verified on test meshes (aro_studio/textures); roughness, metallic, AO not produced; material presets exist.
* **Work required:** Metallic-roughness (ORM) packing, AO bake, import of engine PBR.
* **Acceptance criteria:** Blender render shows all maps used; Khronos validator clean.
* **Meshy:** offers: yes (evidence G). Texture maps returned: base_color, metallic, roughness, normal, emission, metallic_roughness. meshy-n1 gives base colour only; meshy-6 adds an emission map. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml), [docs.meshy.ai/api/models.md](https://docs.meshy.ai/api/models.md)

### B5 Texture resolution control

*Kind:* Conventional · *ARO status:* **Implemented** · *Priority:* P2

* **What it does:** Pick texture size.
* **User workflow:** Select 1K/2K/4K/8K.
* **Inputs:** Resolution enum.
* **Outputs:** Texture of that size.
* **Technology:** Baking.
* **Candidate models / services:** Own baker.
* **GPU requirements:** none
* **Implementation complexity:** Low
* **Estimated operating cost:** CPU; memory grows with size.
* **ARO today (evidence):** 512/1024/2048 supported and validated by POST /api/convert (tests/test_convert.py); 4096 and 8192 not offered.
* **Work required:** Add 4096/8192 with memory guard.
* **Acceptance criteria:** Each size exports and loads in Blender.
* **Meshy:** offers: yes (evidence G). texture_resolution 2k, 4k or 8k (8K costs more: +5 credits; not on meshy-6-lite or meshy-n1). Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml), [docs.meshy.ai/api/pricing.md](https://docs.meshy.ai/api/pricing.md)

### B6 Texture refinement and regeneration

*Kind:* AI · *ARO status:* **Planned** · *Priority:* P2

* **What it does:** Improve or redo textures.
* **User workflow:** Select asset, refine/regenerate, compare.
* **Inputs:** Asset + options.
* **Outputs:** New texture version.
* **Technology:** Refine stage of texturing model.
* **Candidate models / services:** As B1/B2.
* **GPU requirements:** 24-48 GB
* **Implementation complexity:** High
* **Estimated operating cost:** Estimate only.
* **ARO today (evidence):** None.
* **Work required:** After B1/B2.
* **Acceptance criteria:** Refined version rated better than original in blind comparison.
* **Meshy:** offers: yes (evidence G). Text-to-3D refine and Retexture re-generate texture on existing geometry; both priced per task. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml), [docs.meshy.ai/api/pricing.md](https://docs.meshy.ai/api/pricing.md)

### B7 Material preview and inspection

*Kind:* Conventional · *ARO status:* **Implemented but unverified** · *Priority:* P1

* **What it does:** See materials on the model, inspect maps.
* **User workflow:** Orbit the model under lighting; open material panel.
* **Inputs:** Asset.
* **Outputs:** Rendered view and map list.
* **Technology:** three.js viewer.
* **Candidate models / services:** three.js, React Three Fiber, drei.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** Client side.
* **ARO today (evidence):** Viewer has orbit, perspective camera, hemisphere/directional lights, wireframe; no environment map, matcap, orthographic view or per-map inspector (grep over UI sources).
* **Work required:** Environment lighting, map inspector, matcap.
* **Acceptance criteria:** Maps toggle individually; screenshot tests.
* **Meshy:** offers: yes (evidence S). Details not opened. Sources: [help.meshy.ai/en/articles/12618267-meshy-workspace-features-and-navigation](https://help.meshy.ai/en/articles/12618267-meshy-workspace-features-and-navigation)


## C. Model refinement

### C1 Mesh cleanup and repair

*Kind:* Conventional · *ARO status:* **Implemented** · *Priority:* P0

* **What it does:** Remove invalid/degenerate geometry, fill holes, fix normals.
* **User workflow:** Automatic in preparation; manual re-run.
* **Inputs:** Mesh.
* **Outputs:** Repaired mesh + report.
* **Technology:** trimesh/own ops.
* **Candidate models / services:** Own code.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** CPU only.
* **ARO today (evidence):** aro_studio/geometry (unit tests; run on real TripoSR meshes). Not AI.
* **Work required:** Per-user job wrapper only.
* **Acceptance criteria:** Existing test suite plus 20 benchmark meshes pass validation.
* **Meshy:** offers: not found in the sources searched (evidence none). absence in search results is not proof Meshy lacks it Sources: none

### C2 Polygon reduction

*Kind:* Conventional · *ARO status:* **Implemented** · *Priority:* P0

* **What it does:** Reduce triangles to a budget.
* **User workflow:** Automatic; budget selectable.
* **Inputs:** Mesh + target.
* **Outputs:** Lower-poly mesh.
* **Technology:** Quadric decimation, staged.
* **Candidate models / services:** Own code.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** CPU only.
* **ARO today (evidence):** 5-stage decimation with manifold repair (ai_pipeline). Not AI.
* **Work required:** Expose budget (A5).
* **Acceptance criteria:** Budget met within 5 percent.
* **Meshy:** offers: yes (evidence S). target_polycount. Sources: [docs.meshy.ai/api/image-to-3d.md](https://docs.meshy.ai/api/image-to-3d.md)

### C3 Quad remesh

*Kind:* Conventional · *ARO status:* **Not investigated** · *Priority:* P2

* **What it does:** Rebuild as quad-dominant topology.
* **User workflow:** Choose quad topology.
* **Inputs:** Mesh + target.
* **Outputs:** Quad mesh.
* **Technology:** Field-aligned quad remeshing.
* **Candidate models / services:** QuadriFlow, Instant Meshes, Blender (licences to verify).
* **GPU requirements:** none
* **Implementation complexity:** High
* **Estimated operating cost:** CPU only.
* **ARO today (evidence):** None.
* **Work required:** Spike and licence check.
* **Acceptance criteria:** Quad ratio and flow quality on 20 meshes.
* **Meshy:** offers: yes (evidence G). POST /v1/remesh: topology triangle/quad, target_polycount 100 to 300,000, resize options; 5 credits; typical time about 2 minutes. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml), [docs.meshy.ai/api/pricing.md](https://docs.meshy.ai/api/pricing.md)

### C4 UV generation and correction

*Kind:* Conventional · *ARO status:* **Implemented** · *Priority:* P1

* **What it does:** Unwrap and pack UVs.
* **User workflow:** Automatic.
* **Inputs:** Mesh.
* **Outputs:** UV set without overlap.
* **Technology:** xatlas in a subprocess.
* **Candidate models / services:** xatlas (MIT).
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** CPU only.
* **ARO today (evidence):** aro_studio/textures; V-orientation bug found and fixed (all textured GLBs before commit 23ca783 were mirrored); regression tests decode the written GLB.
* **Work required:** UV quality metrics (stretch, seams) in validation.
* **Acceptance criteria:** Blender sampling test passes (existing).
* **Meshy:** offers: yes (evidence G). POST /v1/uv-unwrap (GLB input, availability limited, high-poly must be remeshed first): 5 credits, about 35 s. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml), [docs.meshy.ai/api/pricing.md](https://docs.meshy.ai/api/pricing.md)

### C5 Normals and normal-map transfer

*Kind:* Conventional · *ARO status:* **Implemented** · *Priority:* P1

* **What it does:** Correct normals; transfer detail from the dense mesh.
* **User workflow:** Automatic.
* **Inputs:** Mesh.
* **Outputs:** Smooth normals + normal map.
* **Technology:** Own code.
* **Candidate models / services:** Own code.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** CPU only.
* **ARO today (evidence):** Normal bake (aro_studio/textures/normal_bake.py) tested; fragment-count memory bug fixed.
* **Work required:** None.
* **Acceptance criteria:** Existing tests.
* **Meshy:** offers: not found in the sources searched (evidence none). absence in search results is not proof Meshy lacks it Sources: none

### C6 Scale and orientation

*Kind:* Mixed · *ARO status:* **Implemented** · *Priority:* P1

* **What it does:** Set real size, up axis, forward axis, pivot.
* **User workflow:** Automatic with manual override.
* **Inputs:** Mesh + optional dimensions.
* **Outputs:** Oriented mesh.
* **Technology:** Silhouette-based up-axis detection; heuristics.
* **Candidate models / services:** Own code.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** CPU only.
* **ARO today (evidence):** Up-axis detection recovers all six native frames in tests; forward axis is a heuristic (needs_human flag).
* **Work required:** Learned orientation check on E1 outputs.
* **Acceptance criteria:** Orientation correct on 20 benchmark models.
* **Meshy:** offers: yes (evidence G). POST /v1/resize (resize_height, resize_longest_side or auto_size, origin_at): 1 credit; auto_size flag also on generation endpoints. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml), [docs.meshy.ai/api/pricing.md](https://docs.meshy.ai/api/pricing.md)

### C7 Model validation

*Kind:* Conventional · *ARO status:* **Implemented** · *Priority:* P0

* **What it does:** Rule-based production-readiness check.
* **User workflow:** Automatic report.
* **Inputs:** Version.
* **Outputs:** Pass/warn/fail report.
* **Technology:** Own rule engine.
* **Candidate models / services:** Own code.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** CPU only.
* **ARO today (evidence):** 50 rules (aro_studio/validation), Khronos validator in CI.
* **Work required:** Output gates for generation (section 10 of the directive).
* **Acceptance criteria:** Fails a placeholder or empty mesh in tests.
* **Meshy:** offers: not found in the sources searched (evidence none). absence in search results is not proof Meshy lacks it Sources: none

### C8 LOD and collision generation

*Kind:* Conventional · *ARO status:* **Implemented** · *Priority:* P1

* **What it does:** Automatic LOD0-3 and collision hull.
* **User workflow:** Automatic.
* **Inputs:** Mesh.
* **Outputs:** LODs, collision mesh.
* **Technology:** Decimation, convex hulls.
* **Candidate models / services:** Own code.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** CPU only.
* **ARO today (evidence):** aro_studio/lod, aro_studio/collision with tests. Meshy: no mention found.
* **Work required:** None.
* **Acceptance criteria:** Existing tests.
* **Meshy:** offers: not found in the sources searched (evidence none). absence in search results is not proof Meshy lacks it Sources: none

### C9 AI geometry refinement / detail upscaling

*Kind:* AI · *ARO status:* **Not investigated** · *Priority:* P3

* **What it does:** Model-based detail improvement of geometry.
* **User workflow:** Select asset, refine.
* **Inputs:** Mesh.
* **Outputs:** Higher-detail mesh.
* **Technology:** Refine stage of a generator.
* **Candidate models / services:** TBD.
* **GPU requirements:** 24+ GB
* **Implementation complexity:** High
* **Estimated operating cost:** Estimate only.
* **ARO today (evidence):** None.
* **Work required:** Research after E1.
* **Acceptance criteria:** Blind rating improves on 20 meshes.
* **Meshy:** offers: yes (evidence S). geometry_resolution 2k option and a refine stage appear in the API. Sources: [docs.meshy.ai/api/image-to-3d.md](https://docs.meshy.ai/api/image-to-3d.md)

### C10 Format conversion service

*Kind:* Conventional · *ARO status:* **Implemented** · *Priority:* P2

* **What it does:** Convert any model to other formats on request.
* **User workflow:** Pick formats on an existing asset.
* **Inputs:** Asset + formats.
* **Outputs:** Files.
* **Technology:** Exporters.
* **Candidate models / services:** Own exporters + Blender.
* **GPU requirements:** none
* **Implementation complexity:** Low
* **Estimated operating cost:** CPU only.
* **ARO today (evidence):** Export service converts a stored version to GLB, glTF, OBJ, FBX, USD, .blend and Unity package (aro_studio/export, tests/test_export_validation.py, tests/test_blender_export.py).
* **Work required:** Per-user access and STL/USDZ/3MF.
* **Acceptance criteria:** Existing tests plus new formats.
* **Meshy:** offers: yes (evidence G). POST /v1/convert: 1 credit, about 7 s. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml), [docs.meshy.ai/api/pricing.md](https://docs.meshy.ai/api/pricing.md)


## D. Workspace and editing

### D1 Interactive viewport (orbit, pan, zoom)

*Kind:* Conventional · *ARO status:* **Implemented** · *Priority:* P0

* **What it does:** Inspect models in 3D.
* **User workflow:** Mouse/touch orbit, pan, zoom.
* **Inputs:** GLB.
* **Outputs:** Interactive view.
* **Technology:** three.js.
* **Candidate models / services:** three.js, React Three Fiber, drei.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** Client side.
* **ARO today (evidence):** Vendored three.js bundle with OrbitControls and LOD switch (aro_studio/ui). Not React.
* **Work required:** Rebuild as an R3F component with the same conventions.
* **Acceptance criteria:** Loads a 1M-triangle GLB at an interactive frame rate on a mid laptop (measured).
* **Meshy:** offers: yes (evidence S).  Sources: [help.meshy.ai/en/articles/12618267-meshy-workspace-features-and-navigation](https://help.meshy.ai/en/articles/12618267-meshy-workspace-features-and-navigation)

### D2 Perspective and orthographic views

*Kind:* Conventional · *ARO status:* **Planned** · *Priority:* P2

* **What it does:** Switch camera type, standard views.
* **User workflow:** Toolbar.
* **Inputs:** n/a
* **Outputs:** View.
* **Technology:** three.js.
* **Candidate models / services:** three.js.
* **GPU requirements:** none
* **Implementation complexity:** Low
* **Estimated operating cost:** Client side.
* **ARO today (evidence):** Perspective only (no OrthographicCamera in UI sources).
* **Work required:** Add.
* **Acceptance criteria:** Front/side/top ortho screenshots match expected extents.
* **Meshy:** offers: unknown (evidence none).  Sources: none

### D3 Selection and transform gizmos

*Kind:* Conventional · *ARO status:* **Planned** · *Priority:* P2

* **What it does:** Select an object; move, rotate, scale.
* **User workflow:** Click, drag gizmo.
* **Inputs:** n/a
* **Outputs:** Transformed scene.
* **Technology:** three.js TransformControls.
* **Candidate models / services:** drei TransformControls.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** Client side.
* **ARO today (evidence):** None (no raycasting or TransformControls in UI sources).
* **Work required:** Add with undo (D6).
* **Acceptance criteria:** Transform persists on save/reload.
* **Meshy:** offers: unknown (evidence none).  Sources: none

### D4 Scene hierarchy

*Kind:* Conventional · *ARO status:* **Planned** · *Priority:* P2

* **What it does:** Tree of nodes and materials.
* **User workflow:** Open outliner.
* **Inputs:** Scene.
* **Outputs:** Selectable tree.
* **Technology:** Scene graph.
* **Candidate models / services:** Own scene model.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** Client side.
* **ARO today (evidence):** Scene model has nodes (aro_studio/scene); no UI.
* **Work required:** Outliner panel.
* **Acceptance criteria:** Selecting a node highlights it.
* **Meshy:** offers: unknown (evidence none).  Sources: none

### D5 Lighting and environment controls

*Kind:* Conventional · *ARO status:* **Implemented** · *Priority:* P2

* **What it does:** Change lights, HDRI, background.
* **User workflow:** Panel.
* **Inputs:** n/a
* **Outputs:** View.
* **Technology:** three.js.
* **Candidate models / services:** drei Environment.
* **GPU requirements:** none
* **Implementation complexity:** Low
* **Estimated operating cost:** Client side.
* **ARO today (evidence):** Web viewer (apps/web/src/components/Viewer.tsx): studio, outdoor and soft lighting presets from a procedural RoomEnvironment (no network), plus textured, clay and wireframe modes; exercised in Chromium end to end against the dev stack (2026-11-11). Custom HDRIs and light placement are not offered.
* **Work required:** Add.
* **Acceptance criteria:** Screenshot tests.
* **Meshy:** offers: unknown (evidence none).  Sources: none

### D6 Undo and redo

*Kind:* Conventional · *ARO status:* **Planned** · *Priority:* P3

* **What it does:** Revert edits.
* **User workflow:** Ctrl+Z.
* **Inputs:** n/a
* **Outputs:** State.
* **Technology:** Command stack.
* **Candidate models / services:** Zustand + commands.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** Client side.
* **ARO today (evidence):** Versions give coarse history only.
* **Work required:** Command stack after D3.
* **Acceptance criteria:** Round-trip tests.
* **Meshy:** offers: unknown (evidence none).  Sources: none

### D7 Save and restore projects

*Kind:* Platform · *ARO status:* **Implemented** · *Priority:* P0

* **What it does:** Persist scene and settings.
* **User workflow:** Autosave/Save/Open.
* **Inputs:** Project.
* **Outputs:** Restored project.
* **Technology:** Postgres + R2.
* **Candidate models / services:** Supabase, R2.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** Negligible.
* **ARO today (evidence):** Projects, versions, archive/restore exist (single-tenant, SQLite).
* **Work required:** Migrate to Postgres.
* **Acceptance criteria:** Reload restores the same state (E2E).
* **Meshy:** offers: yes (evidence S).  Sources: [help.meshy.ai/en/articles/12618267-meshy-workspace-features-and-navigation](https://help.meshy.ai/en/articles/12618267-meshy-workspace-features-and-navigation)

### D8 Compare versions side by side

*Kind:* Conventional · *ARO status:* **Planned** · *Priority:* P1

* **What it does:** Two viewports synchronised.
* **User workflow:** Pick two versions.
* **Inputs:** Two versions.
* **Outputs:** Linked views.
* **Technology:** three.js.
* **Candidate models / services:** R3F.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** Client side.
* **ARO today (evidence):** None.
* **Work required:** Add; needed by the benchmark process.
* **Acceptance criteria:** Camera sync verified.
* **Meshy:** offers: unknown (evidence none).  Sources: none


## E. Character and animation

### E1 Auto-rigging (skeleton and skinning)

*Kind:* AI · *ARO status:* **Investigated** · *Priority:* P3

* **What it does:** Add a skeleton and skin weights.
* **User workflow:** Select character, rig.
* **Inputs:** Character mesh.
* **Outputs:** Skinned GLB/FBX.
* **Technology:** Learned skeleton + skinning prediction.
* **Candidate models / services:** UniRig (MIT code, G; weights licence unverified; ~8 GB, T).
* **GPU requirements:** 8 GB+
* **Implementation complexity:** High
* **Estimated operating cost:** Estimate only.
* **ARO today (evidence):** Only a mechanical vehicle node hierarchy exists (aro_studio/animation/rig.py: pivots for wheels/doors; no skeleton).
* **Work required:** Spike with UniRig on 10 characters.
* **Acceptance criteria:** Bone count, weight sanity, plays an animation in Blender.
* **Meshy:** offers: yes (evidence G). POST /v1/rigging: biped or quadruped, height_meters; models above 380,000 triangles are rejected (remesh first); 5 credits, about 40 s. Smart Rig (beta, any model type) exists in the web app but cannot use the animation library. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml), [docs.meshy.ai/api/pricing.md](https://docs.meshy.ai/api/pricing.md), [docs.meshy.ai/llms-full.txt](https://docs.meshy.ai/llms-full.txt)

### E2 Animation library and motion

*Kind:* AI · *ARO status:* **Not investigated** · *Priority:* P3

* **What it does:** Apply preset or generated motion.
* **User workflow:** Pick an animation.
* **Inputs:** Rigged character.
* **Outputs:** Animated GLB/FBX.
* **Technology:** Retargeting; motion generation.
* **Candidate models / services:** TBD (licence critical).
* **GPU requirements:** none to 24 GB
* **Implementation complexity:** High
* **Estimated operating cost:** Estimate only.
* **ARO today (evidence):** None.
* **Work required:** Licence-clean motion source.
* **Acceptance criteria:** Retargeted clip plays correctly.
* **Meshy:** offers: yes (evidence G). POST /v1/animations applies library action_ids (IDs run from 0 to 696; about 655 rows parsed from the reference table in categories DailyActions, WalkAndRun, Fighting, BodyMovements, Dancing, Idle), up to 10 per request at 3 credits per action; Text to Motion (prime 10 credits, swift 3 credits) generates custom clips. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml), [docs.meshy.ai/en/api/animation-library](https://docs.meshy.ai/en/api/animation-library), [docs.meshy.ai/api/pricing.md](https://docs.meshy.ai/api/pricing.md)

### E3 Pose and animation preview

*Kind:* Conventional · *ARO status:* **Planned** · *Priority:* P3

* **What it does:** Preview clips in the viewport.
* **User workflow:** Play/scrub.
* **Inputs:** Animated asset.
* **Outputs:** Playback.
* **Technology:** three.js AnimationMixer.
* **Candidate models / services:** R3F.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** Client side.
* **ARO today (evidence):** None.
* **Work required:** After E1.
* **Acceptance criteria:** Visual check.
* **Meshy:** offers: yes (evidence S). Animate module. Sources: [help.meshy.ai/en/articles/12618267-meshy-workspace-features-and-navigation](https://help.meshy.ai/en/articles/12618267-meshy-workspace-features-and-navigation)

### E4 Rigged export to game engines

*Kind:* Conventional · *ARO status:* **Planned** · *Priority:* P3

* **What it does:** Skinned FBX/GLB for Unity/Unreal.
* **User workflow:** Export.
* **Inputs:** Rigged asset.
* **Outputs:** Files.
* **Technology:** Blender export.
* **Candidate models / services:** Blender.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** CPU.
* **ARO today (evidence):** Static FBX verified; skinned not.
* **Work required:** After E1.
* **Acceptance criteria:** Blender re-import compares bones and weights.
* **Meshy:** offers: yes (evidence S).  Sources: [help.meshy.ai/en/articles/9991738-what-features-does-meshy-have](https://help.meshy.ai/en/articles/9991738-what-features-does-meshy-have)

### E5 Text-to-motion

*Kind:* AI · *ARO status:* **Not investigated** · *Priority:* P3

* **What it does:** Generate a custom animation clip from a text description.
* **User workflow:** Describe a motion, retarget it onto a rigged character.
* **Inputs:** Prompt + rigged character.
* **Outputs:** Animated GLB/FBX.
* **Technology:** Motion generation model + retargeting.
* **Candidate models / services:** TBD (licence critical).
* **GPU requirements:** TBD
* **Implementation complexity:** High
* **Estimated operating cost:** Estimate only.
* **ARO today (evidence):** None.
* **Work required:** Research after E1/E2.
* **Acceptance criteria:** Clip plays correctly on 5 characters.
* **Meshy:** offers: yes (evidence G). Text to Motion API: prime mode 10 credits, swift mode 3 credits (not in the OpenAPI file; documented on its own page). Sources: [docs.meshy.ai/api/pricing.md](https://docs.meshy.ai/api/pricing.md), [docs.meshy.ai/llms-full.txt](https://docs.meshy.ai/llms-full.txt)


## F. Export and integration

### F1 GLB export

*Kind:* Conventional · *ARO status:* **Fully tested** · *Priority:* P0

* **What it does:** Binary glTF with textures.
* **User workflow:** Download.
* **Inputs:** Version.
* **Outputs:** GLB.
* **Technology:** Own writer.
* **Candidate models / services:** Own code.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** CPU.
* **ARO today (evidence):** Writer tests; Khronos validator in CI; Blender re-import and texture sampling on real vehicle meshes; texture V-flip defect found and fixed with regression tests.
* **Work required:** Per-user signed URLs.
* **Acceptance criteria:** Existing tests + Blender job in CI.
* **Meshy:** offers: yes (evidence G). GLB is the default output format. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml), [docs.meshy.ai/llms-full.txt](https://docs.meshy.ai/llms-full.txt)

### F2 glTF (separate files)

*Kind:* Conventional · *ARO status:* **Implemented** · *Priority:* P2

* **What it does:** glTF + bin + textures.
* **User workflow:** Download zip.
* **Inputs:** Version.
* **Outputs:** Zip.
* **Technology:** Own writer.
* **Candidate models / services:** Own code.
* **GPU requirements:** none
* **Implementation complexity:** Low
* **Estimated operating cost:** CPU.
* **ARO today (evidence):** glTF writer exercised in tests/test_export_validation.py and tests/test_gltf_uv_orientation.py (Khronos validator available in CI); not opened in a third-party tool.
* **Work required:** None.
* **Acceptance criteria:** Existing tests.
* **Meshy:** offers: yes (evidence G). gltf listed among model URL formats. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml)

### F3 OBJ

*Kind:* Conventional · *ARO status:* **Implemented** · *Priority:* P1

* **What it does:** OBJ + MTL + textures.
* **User workflow:** Download.
* **Inputs:** Version.
* **Outputs:** Zip.
* **Technology:** Own writer.
* **Candidate models / services:** Own code.
* **GPU requirements:** none
* **Implementation complexity:** Low
* **Estimated operating cost:** CPU.
* **ARO today (evidence):** OBJ/MTL writer covered by tests/test_export_validation.py; texture V orientation (V up) pinned by tests/test_gltf_uv_orientation.py; not opened in a third-party DCC tool.
* **Work required:** None.
* **Acceptance criteria:** Existing tests.
* **Meshy:** offers: yes (evidence G). obj and mtl listed. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml)

### F4 FBX (Unity and Unreal conventions)

*Kind:* Conventional · *ARO status:* **Implemented** · *Priority:* P1

* **What it does:** FBX with correct axes and scale.
* **User workflow:** Choose target engine.
* **Inputs:** Version + target.
* **Outputs:** FBX zip.
* **Technology:** Blender export + Blender re-import check.
* **Candidate models / services:** Blender (bpy, GPL-3.0: legal review).
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** CPU.
* **ARO today (evidence):** 12 of 12 round trips of real vehicle meshes verified by Blender; CI job installs bpy. Never opened in Unity or Unreal.
* **Work required:** Open in Unity/Unreal and record.
* **Acceptance criteria:** Engine import verified by the owner.
* **Meshy:** offers: yes (evidence G). fbx listed; rigged FBX with skeleton templates (default Mixamo) for humanoids. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml), [docs.meshy.ai/llms-full.txt](https://docs.meshy.ai/llms-full.txt)

### F5 USD and .blend

*Kind:* Conventional · *ARO status:* **Implemented** · *Priority:* P2

* **What it does:** Other production formats.
* **User workflow:** Download.
* **Inputs:** Version.
* **Outputs:** Files.
* **Technology:** Blender export.
* **Candidate models / services:** Blender.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** CPU.
* **ARO today (evidence):** USD and .blend written and re-imported by Blender in tests/test_blender_export.py (CI job installs bpy); not opened in other tools.
* **Work required:** None.
* **Acceptance criteria:** Existing tests.
* **Meshy:** offers: yes (evidence G). usdz, blend and vox listed (USD proper not listed). Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml)

### F6 STL

*Kind:* Conventional · *ARO status:* **Implemented** · *Priority:* P2

* **What it does:** Mesh-only format for printing.
* **User workflow:** Download.
* **Inputs:** Version.
* **Outputs:** STL.
* **Technology:** trimesh.
* **Candidate models / services:** trimesh.
* **GPU requirements:** none
* **Implementation complexity:** Low
* **Estimated operating cost:** CPU.
* **ARO today (evidence):** Multi-user platform: STL export of the full-detail model, Z-up for slicers, converted once from the stored GLB and cached (aro_cloud/exports.py, tests/cloud/test_exports_and_library.py checks axis order and triangle count). Geometry only; no print-readiness checks (see F10).
* **Work required:** Add exporter + watertight check.
* **Acceptance criteria:** Opens in a slicer.
* **Meshy:** offers: yes (evidence G). stl listed. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml)

### F7 USDZ and 3MF

*Kind:* Conventional · *ARO status:* **Planned** · *Priority:* P3

* **What it does:** Apple AR and print formats.
* **User workflow:** Download.
* **Inputs:** Version.
* **Outputs:** Files.
* **Technology:** Blender or dedicated writers.
* **Candidate models / services:** TBD.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** CPU.
* **ARO today (evidence):** None.
* **Work required:** Add after F6.
* **Acceptance criteria:** Opens in Quick Look / slicer.
* **Meshy:** offers: yes (evidence G). usdz and 3mf listed. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml)

### F8 Unity package with verifier

*Kind:* Conventional · *ARO status:* **Implemented but unverified** · *Priority:* P1

* **What it does:** One-click Unity import package.
* **User workflow:** Download .unitypackage-style zip.
* **Inputs:** Version.
* **Outputs:** Package.
* **Technology:** Own generator + batch-mode verifier.
* **Candidate models / services:** Own code.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** CPU.
* **ARO today (evidence):** Generated and integrity-checked; verifier only syntax-checked; never imported in Unity 6.
* **Work required:** Owner imports it in Unity 6 per the runbook.
* **Acceptance criteria:** Verifier report from a real Unity run.
* **Meshy:** offers: not found in the sources searched (evidence none). absence in search results is not proof Meshy lacks it Sources: none

### F9 Engine and DCC plug-ins

*Kind:* Conventional · *ARO status:* **Not investigated** · *Priority:* P3

* **What it does:** Send assets into Blender/Unity/Unreal.
* **User workflow:** Install plug-in.
* **Inputs:** Account token.
* **Outputs:** Asset in the tool.
* **Technology:** Plug-ins / bridge.
* **Candidate models / services:** TBD.
* **GPU requirements:** none
* **Implementation complexity:** High
* **Estimated operating cost:** Engineering time.
* **ARO today (evidence):** None.
* **Work required:** Decide after the web product works.
* **Acceptance criteria:** n/a
* **Meshy:** offers: yes (evidence G). Official plug-ins plus a 'DCC Bridge' for Blender, Unreal Engine, Unity, Maya, Godot and 3ds Max (each has dedicated documentation); send animated rigged models at 30 fps. Sources: [docs.meshy.ai/llms-full.txt](https://docs.meshy.ai/llms-full.txt)

### F10 3D-printing preparation

*Kind:* Conventional · *ARO status:* **Planned** · *Priority:* P3

* **What it does:** Watertight, scaled, print formats.
* **User workflow:** Open print mode.
* **Inputs:** Model.
* **Outputs:** Print-ready file.
* **Technology:** Mesh repair + STL/3MF.
* **Candidate models / services:** trimesh, Blender.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** CPU.
* **ARO today (evidence):** None.
* **Work required:** After F6/F7.
* **Acceptance criteria:** Slicer accepts without repair.
* **Meshy:** offers: yes (evidence G). 3D Print endpoints: analyze printability (free), repair (10), auto split (10), multi-colour print (10), relief (20); plus Creative Lab physical-product generators (keychain, figure, lamp and others, not in the spec). Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml), [docs.meshy.ai/api/pricing.md](https://docs.meshy.ai/api/pricing.md)


## G. Assets and projects

### G1 Personal asset library with search and filter

*Kind:* Platform · *ARO status:* **Implemented** · *Priority:* P1

* **What it does:** Browse, search, filter own assets.
* **User workflow:** Library page.
* **Inputs:** Query.
* **Outputs:** Asset list.
* **Technology:** Postgres full-text + filters.
* **Candidate models / services:** Supabase.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** Negligible.
* **ARO today (evidence):** Multi-user platform: owner-scoped library API with name search (literal wildcards), rename and soft delete (GET/PATCH/DELETE /v1/assets, tests/cloud/test_exports_and_library.py, isolation tests in tests/cloud/test_api.py) and the web library with search; exercised in Chromium against the dev stack. No tags, folders or filters by category in the web app yet.
* **Work required:** Per-user, indexed search, pagination.
* **Acceptance criteria:** RLS test + filter tests.
* **Meshy:** offers: yes (evidence G). Web app library and a community model library (downloads unlimited on paid plans). Sources: [docs.meshy.ai/llms-full.txt](https://docs.meshy.ai/llms-full.txt)

### G2 Projects and folders

*Kind:* Platform · *ARO status:* **Implemented** · *Priority:* P1

* **What it does:** Group assets.
* **User workflow:** Create/move.
* **Inputs:** Names.
* **Outputs:** Tree.
* **Technology:** Postgres.
* **Candidate models / services:** Supabase.
* **GPU requirements:** none
* **Implementation complexity:** Low
* **Estimated operating cost:** Negligible.
* **ARO today (evidence):** Projects with archive/restore; no nested folders.
* **Work required:** parent_id folders.
* **Acceptance criteria:** Tests.
* **Meshy:** offers: yes (evidence S).  Sources: [help.meshy.ai/en/articles/12618267-meshy-workspace-features-and-navigation](https://help.meshy.ai/en/articles/12618267-meshy-workspace-features-and-navigation)

### G3 Preview thumbnails

*Kind:* Conventional · *ARO status:* **Implemented** · *Priority:* P1

* **What it does:** Rendered thumbnail per version.
* **User workflow:** Automatic.
* **Inputs:** Version.
* **Outputs:** PNG in storage.
* **Technology:** Server-side render.
* **Candidate models / services:** Existing render util or headless three.js.
* **GPU requirements:** none
* **Implementation complexity:** Low
* **Estimated operating cost:** CPU.
* **ARO today (evidence):** Worker renders a 512 px shaded thumbnail of LOD0 after preparation (aro_worker/headless.py), stored per version and shown in the web library through signed URLs; checked in the browser run against the dev stack. With the test-double engine only.
* **Work required:** Render on completion, store in R2.
* **Acceptance criteria:** Every completed job has a thumbnail.
* **Meshy:** offers: not found in the sources searched (evidence none). absence in search results is not proof Meshy lacks it Sources: none

### G4 Asset metadata and versioning

*Kind:* Platform · *ARO status:* **Implemented** · *Priority:* P0

* **What it does:** Provenance, stats, validation per version.
* **User workflow:** Automatic.
* **Inputs:** n/a
* **Outputs:** Metadata JSON.
* **Technology:** Own schema.
* **Candidate models / services:** Postgres jsonb.
* **GPU requirements:** none
* **Implementation complexity:** Low
* **Estimated operating cost:** Negligible.
* **ARO today (evidence):** Provenance and generation reports stored per version in SQLite (tests/test_db_and_assets.py); not yet per user.
* **Work required:** Move to Postgres.
* **Acceptance criteria:** Existing tests.
* **Meshy:** offers: not found in the sources searched (evidence none). absence in search results is not proof Meshy lacks it Sources: none

### G5 Deletion and restoration policy

*Kind:* Platform · *ARO status:* **Implemented** · *Priority:* P1

* **What it does:** Soft delete, restore, purge.
* **User workflow:** Delete/restore.
* **Inputs:** Id.
* **Outputs:** State change.
* **Technology:** Status fields + retention job.
* **Candidate models / services:** Postgres, R2 lifecycle.
* **GPU requirements:** none
* **Implementation complexity:** Low
* **Estimated operating cost:** Negligible.
* **ARO today (evidence):** Soft delete/restore at project level; permanent delete exists.
* **Work required:** Asset-level, retention window, R2 purge.
* **Acceptance criteria:** Restore within window works; purge removes objects.
* **Meshy:** offers: not found in the sources searched (evidence none). absence in search results is not proof Meshy lacks it Sources: none

### G6 Download management

*Kind:* Platform · *ARO status:* **Implemented** · *Priority:* P0

* **What it does:** Download files and exports.
* **User workflow:** Download buttons.
* **Inputs:** Id.
* **Outputs:** File via signed URL.
* **Technology:** Signed URLs.
* **Candidate models / services:** R2.
* **GPU requirements:** none
* **Implementation complexity:** Low
* **Estimated operating cost:** R2 egress is free (S).
* **ARO today (evidence):** Multi-user platform: every download is a short-lived pre-signed R2 URL issued after an ownership check (aro_cloud/assets.py, exports.py), with sanitised file names; deleted models can no longer be linked to (tests/cloud/test_exports_and_library.py). The single-user Studio keeps its own FileResponse downloads.
* **Work required:** Signed URLs.
* **Acceptance criteria:** Expired URL refused; other user refused.
* **Meshy:** offers: not found in the sources searched (evidence none). absence in search results is not proof Meshy lacks it Sources: none

### G7 Usage and credit history

*Kind:* Platform · *ARO status:* **Implemented** · *Priority:* P1

* **What it does:** Show credits spent per job.
* **User workflow:** Account page.
* **Inputs:** n/a
* **Outputs:** Ledger view.
* **Technology:** Ledger table.
* **Candidate models / services:** Postgres.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** Negligible.
* **ARO today (evidence):** Append-only credit ledger with reserve/capture/release per job (aro_cloud/migrations/0001_init.sql, property tests in tests/cloud/test_schema_and_credits.py), GET /v1/credits/ledger, and the web Credits and Activity tabs that show what each generation cost and that failed ones were not charged.
* **Work required:** Ledger (see 04).
* **Acceptance criteria:** Balance equals ledger sum (property test).
* **Meshy:** offers: yes (evidence G). GET /v1/balance and GET /v1/usage/tasks list usage records; every task carries consumed_credits. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml)

### G8 Mobile capture app

*Kind:* Platform · *ARO status:* **Not investigated** · *Priority:* P3

* **What it does:** Photograph an object on a phone and get a 3D model.
* **User workflow:** Take photo, upload, wait.
* **Inputs:** Photos.
* **Outputs:** Model.
* **Technology:** Mobile client calling the API.
* **Candidate models / services:** Native or PWA.
* **GPU requirements:** none
* **Implementation complexity:** High
* **Estimated operating cost:** Engineering time.
* **ARO today (evidence):** None.
* **Work required:** Only after the web product; a PWA with camera upload is the cheap first step.
* **Acceptance criteria:** n/a
* **Meshy:** offers: yes (evidence G). 'Meshy App: snap a photo, get a 3D model right from your phone' on the pricing page. Sources: [www.meshy.ai/pricing](https://www.meshy.ai/pricing)


## H. Platform

### H1 Authentication and accounts

*Kind:* Platform · *ARO status:* **Implemented but unverified** · *Priority:* P0

* **What it does:** Sign up/in, profiles.
* **User workflow:** Email/OAuth login.
* **Inputs:** n/a
* **Outputs:** Session.
* **Technology:** Supabase Auth.
* **Candidate models / services:** Supabase Auth.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** Free tier then plan fee (S).
* **ARO today (evidence):** Supabase JWT verification (HS256 or JWKS; algorithm confusion, expiry, audience, role and issuer tests in tests/cloud/test_auth.py), per-user Row Level Security, sign-in/sign-up/magic link in apps/web. Not yet run against a real Supabase project.
* **Work required:** Supabase Auth; server-side JWT verification.
* **Acceptance criteria:** Unauthenticated and cross-user requests refused (tests).
* **Meshy:** offers: yes (evidence G). Accounts with Free, Pro, Premium, Ultra, Studio and Enterprise plans; team accounts share limits. Sources: [docs.meshy.ai/llms-full.txt](https://docs.meshy.ai/llms-full.txt)

### H2 Credit ledger and billing

*Kind:* Platform · *ARO status:* **Implemented but unverified** · *Priority:* P1

* **What it does:** Reserve, capture, refund credits.
* **User workflow:** Buy/spend credits.
* **Inputs:** Job request.
* **Outputs:** Ledger entries.
* **Technology:** Transactional ledger.
* **Candidate models / services:** Postgres functions.
* **GPU requirements:** none
* **Implementation complexity:** High
* **Estimated operating cost:** Payment provider fees (owner decision).
* **ARO today (evidence):** Credit ledger implemented and property-tested on PostgreSQL 16 (reserve in the job's transaction, capture with the asset, release on failure or cancel). Billing (buying credits) is NOT built; credits come from admin grants or sign-up credits. Not yet run on the owner's Supabase.
* **Work required:** Ledger, reservation/refund tests; payment provider choice.
* **Acceptance criteria:** Property tests: balance never negative; failed jobs release reserve.
* **Meshy:** offers: yes (evidence G). Prepaid credits; failed generations are not charged; paid plans: Pro $20 per month for 1,000 credits, Premium $40 for 3,000, Ultra $100 for 8,000 (Free: 100 credits, 1 concurrent task); credits reset monthly, purchased credits do not expire. Sources: [docs.meshy.ai/api/pricing.md](https://docs.meshy.ai/api/pricing.md), [www.meshy.ai/pricing](https://www.meshy.ai/pricing), [docs.meshy.ai/en/webapp/pricing](https://docs.meshy.ai/en/webapp/pricing)

### H3 Production job lifecycle

*Kind:* Platform · *ARO status:* **Implemented** · *Priority:* P0

* **What it does:** Idempotent, reconcilable jobs.
* **User workflow:** Submit, watch, cancel.
* **Inputs:** Idempotency-Key.
* **Outputs:** Job record.
* **Technology:** Postgres state machine + provider reconciliation.
* **Candidate models / services:** Postgres, RunPod API.
* **GPU requirements:** none
* **Implementation complexity:** High
* **Estimated operating cost:** Negligible.
* **ARO today (evidence):** aro_cloud/orchestrator.py: idempotent submit, compare-and-set state machine with events, dispatch never repeated after an ambiguous answer, reconciliation from provider status or the storage marker, deadlines on database time, cancel, bounded retries, output gate before completion (48 tests in tests/cloud/test_orchestrator.py on a real PostgreSQL). Against RunPod only through a test double that follows its documented API.
* **Work required:** Implement per 04-architecture.
* **Acceptance criteria:** Duplicate submit makes one job; timeout never double-spends; killed worker is reconciled.
* **Meshy:** offers: yes (evidence G). Task lifecycle PENDING, IN_PROGRESS, SUCCEEDED, FAILED (credits refunded on failure); progress 0-100; poll, SSE stream per task, or webhook; asset retention 3 days for non-Enterprise plans. Sources: [docs.meshy.ai/llms-full.txt](https://docs.meshy.ai/llms-full.txt), [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml)

### H4 Public API with keys

*Kind:* Platform · *ARO status:* **Planned** · *Priority:* P2

* **What it does:** REST API for developers.
* **User workflow:** Create key, call API.
* **Inputs:** Bearer key.
* **Outputs:** Async task API.
* **Technology:** FastAPI, OpenAPI.
* **Candidate models / services:** FastAPI.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** Negligible.
* **ARO today (evidence):** Internal API with 58 routes; no keys, no versioning policy.
* **Work required:** After H1-H3.
* **Acceptance criteria:** Contract tests.
* **Meshy:** offers: yes (evidence G). OpenAPI 3.1 at https://api.meshy.ai/openapi, bearer API keys, 88 operations over 54 paths including per-task SSE streams; do not call from browser JavaScript. Sources: [docs.meshy.ai/openapi.yaml](https://docs.meshy.ai/openapi.yaml), [docs.meshy.ai/llms-full.txt](https://docs.meshy.ai/llms-full.txt)

### H5 Agent / MCP integration

*Kind:* Platform · *ARO status:* **Not investigated** · *Priority:* P3

* **What it does:** Tool interface for AI agents.
* **User workflow:** Connect agent.
* **Inputs:** Key.
* **Outputs:** Tool calls.
* **Technology:** MCP server.
* **Candidate models / services:** TBD.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** Negligible.
* **ARO today (evidence):** None.
* **Work required:** After H4.
* **Acceptance criteria:** n/a
* **Meshy:** offers: yes (evidence G). MCP server for AI agents (tool-calling access). Sources: [docs.meshy.ai/llms-full.txt](https://docs.meshy.ai/llms-full.txt)

### H6 Rate limits and per-user concurrency

*Kind:* Platform · *ARO status:* **Implemented but unverified** · *Priority:* P0

* **What it does:** Abuse and cost control.
* **User workflow:** n/a
* **Inputs:** n/a
* **Outputs:** 429.
* **Technology:** Redis or Postgres counters.
* **Candidate models / services:** Upstash/Redis, Postgres.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** Free tiers.
* **ARO today (evidence):** In-process sliding window keyed by address/token; not per user, not shared across processes.
* **Work required:** Per-user limits, max concurrent jobs.
* **Acceptance criteria:** Load tests.
* **Meshy:** offers: yes (evidence G). 20 requests per second on all plans (Enterprise 100); concurrent tasks Pro 10, Premium 30, Ultra 100, Studio 60; higher plans get queue priority; HTTP 429 with Retry-After. Sources: [docs.meshy.ai/llms-full.txt](https://docs.meshy.ai/llms-full.txt)

### H7 Cost tracking and observability

*Kind:* Platform · *ARO status:* **Planned** · *Priority:* P0

* **What it does:** Cost per successful generation, failure cost.
* **User workflow:** Dashboard.
* **Inputs:** n/a
* **Outputs:** Reports.
* **Technology:** Usage records + logs.
* **Candidate models / services:** Postgres, logs.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** Negligible.
* **ARO today (evidence):** Structured logs and metrics exist; no cost records.
* **Work required:** usage_records, per-job cost, alerts.
* **Acceptance criteria:** Reported cost equals provider invoice within tolerance.
* **Meshy:** offers: not found in the sources searched (evidence none). absence in search results is not proof Meshy lacks it Sources: none

### H8 Security scanning

*Kind:* Platform · *ARO status:* **Implemented** · *Priority:* P1

* **What it does:** Dependency, code and container scanning.
* **User workflow:** CI.
* **Inputs:** n/a
* **Outputs:** CI results.
* **Technology:** pip-audit, bandit, container scan.
* **Candidate models / services:** GitHub Actions.
* **GPU requirements:** none
* **Implementation complexity:** Low
* **Estimated operating cost:** Free.
* **ARO today (evidence):** pip-audit and bandit in CI (green at commit 313a864); no container image scan; no secret scanning job.
* **Work required:** Add trivy/grype and secret scan.
* **Acceptance criteria:** CI fails on high findings.
* **Meshy:** offers: not found in the sources searched (evidence none). absence in search results is not proof Meshy lacks it Sources: none

### H9 Plan-based concurrency and queue priority

*Kind:* Platform · *ARO status:* **Planned** · *Priority:* P2

* **What it does:** Different concurrent-task limits and queue priority per plan.
* **User workflow:** Automatic.
* **Inputs:** n/a
* **Outputs:** Faster start for higher plans.
* **Technology:** Per-user concurrency + priority queue.
* **Candidate models / services:** Postgres.
* **GPU requirements:** none
* **Implementation complexity:** Medium
* **Estimated operating cost:** Negligible.
* **ARO today (evidence):** Single FIFO queue with priority 1-9 exists inside the single-node Studio (aro_studio/jobs); no plans.
* **Work required:** Per-user concurrency (H6) first; priority later.
* **Acceptance criteria:** A user over the limit gets a clear error; priority is honoured in a test.
* **Meshy:** offers: yes (evidence G). Concurrent tasks and priority differ by plan. Sources: [docs.meshy.ai/llms-full.txt](https://docs.meshy.ai/llms-full.txt), [www.meshy.ai/pricing](https://www.meshy.ai/pricing)

### H10 Asset retention policy

*Kind:* Platform · *ARO status:* **Planned** · *Priority:* P2

* **What it does:** How long results are kept.
* **User workflow:** Automatic; users download what they keep.
* **Inputs:** n/a
* **Outputs:** Expiry timestamps.
* **Technology:** R2 lifecycle + soft delete.
* **Candidate models / services:** R2.
* **GPU requirements:** none
* **Implementation complexity:** Low
* **Estimated operating cost:** Storage only.
* **ARO today (evidence):** Local storage keeps everything until deleted.
* **Work required:** Retention rules per plan with warnings before deletion.
* **Acceptance criteria:** Expired objects are purged on schedule and users are warned.
* **Meshy:** offers: yes (evidence G). Generated assets are retained for 3 days on non-Enterprise plans; tasks expose expires_at. Sources: [docs.meshy.ai/llms-full.txt](https://docs.meshy.ai/llms-full.txt)
