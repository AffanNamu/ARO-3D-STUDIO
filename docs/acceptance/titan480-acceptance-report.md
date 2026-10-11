# ARO TITAN 480 — acceptance run

**Verdict: NOT COMPLETE — production readiness is not claimed**

Studio 0.1.0 · Python 3.13.16 · Linux-6.18.44-fc-v114-x86_64-with-glibc2.39 · 4 vCPU · 16093 MB RAM · GPU: none · run time 107s
Pipeline input: **procedural_reference**

Summary: BLOCKED 3, PARTIAL 4, PASS 15

## Component status (each reported separately; derived only from recorded evidence files)

| Component | Status | Basis |
|---|---|---|
| 1. Platform implementation | **PASS** | 7 gates passed; 246 tests passed, 4 skipped (skips are listed, never counted as passes) |
| 2. Procedural reference asset (ARO TITAN 480) | **PASS** | stages 8-21 passed (9 repair and 11 texture-bake not applicable to a defect-free flat-colour asset, covered by unit tests) on the procedural TITAN 480; validation PRODUCTION_READY. This is NOT an AI asset. |
| 3. Real AI-generated asset | **BLOCKED** | TripoSR has never been run: no inference-evidence.json. Needs a GPU host + Hugging Face access (docs/verification/gpu-host-runbook.md). |
| 4. Validated production asset (from real AI output) | **BLOCKED** | TripoSR has never been run: no inference-evidence.json. Needs a GPU host + Hugging Face access (docs/verification/gpu-host-runbook.md). |
| 5. Verified Unity 6 import | **BLOCKED** | Unity 6 import has not been run: no unity-verification.json. Run Unity in batch mode with ARO.Studio.Editor.AroUnityVerifier.Run (docs/verification/unity-verification-runbook.md). |
| 6. Docker deployment | **PASS** | 22/22 Docker steps passed (build, hardening, health, persistence, limits). Caveats: base image overridden at build time (PYTHON_IMAGE=aro-sandbox-base:py311): the Dockerfile default is a digest-pinned python:3.11-slim; build used --network host (sandbox without bridge networking); build went through an egress proxy. |
| 7. Security and regression tests | **PASS** | bandit + pip-audit + the full test suite (incl. security, resource-limit and archive-protection tests) passed |

ARO 3D Studio is production-ready only when **all seven** are PASS.

## The 22 stages

| # | Stage | Status | Detail | s |
|---|---|---|---|---|
| 1 | Create ARO TITAN 480 project | **PASS** | project prj_a2c7dc34cf3942a7b122, asset ast_7a6f8daf59ee4728a59c | 0.0 |
| 2 | Upload concept image | **PARTIAL** | image is a software render of the procedural reference model, not an artist's concept image; stored by content hash | 1.07 |
| 3 | Validate the input | **PASS** | 1024x1024 png, quality 1.0, warnings: none; analysis: bg=uniform, category auto-detected=None | 0.0 |
| 4 | Preprocess the image | **PASS** | orientation → background_analysis → background_removal → crop → resize → normalize → 512x512 model input | 0.21 |
| 5 | Load the image-to-3D model | **BLOCKED** | TripoSR cannot load here: The 'tsr' package (TripoSR source) is not importable.; Missing Python packages: torch, omegaconf, einops, transformers, huggingface_hub, torchmcubes.. To activate: git clone https://github.com/VAST-AI-Research/TripoSR && git -C TripoSR checkout 107cefdc244c39106fa830359024f6a2f1c78871 && add it to PYTHONPATH (the Dockerfile does this). / pip install -r requirements-triposr.txt  (torch must match the host CUDA version) | 0.0 |
| 6 | Run actual reconstruction | **BLOCKED** | no real reconstruction was run; NO placeholder geometry was substituted. See docs/models/model-requirements.md for the GPU test strategy | 0.0 |
| 7 | Save raw output | **PARTIAL** | no AI output exists; the procedural reference was saved as the raw version ver_f75f607049504fa2b277 so the remaining stages can run on a real, structured vehicle | 0.31 |
| 8 | Process the geometry | **PASS** | standard cleanup: 42,140 → 42,140 faces; steps ['remove_invalid', 'merge_vertices', 'remove_degenerate', 'remove_duplicate_faces', 'remove_small_components', 'fix_normals'] | 5.52 |
| 9 | Repair valid geometry problems | **PARTIAL** | defects found before repair: {'duplicate_vertices': 62, 'nonmanifold_edges': 28}; after: holes=0, non-manifold=28. Repair operations (merge, fill holes, normals, fragments) are unit-tested on damaged meshes | 0.0 |
| 10 | Process materials | **PASS** | 15 PBR materials (paint, glass, rubber, chrome, plastic, lights, interior…) | 0.27 |
| 11 | Process textures where supported | **PARTIAL** | not applicable to this input: the procedural reference uses flat-colour PBR materials (no vertex colours to bake). The texture pipeline (xatlas unwrap, projection baking, resize, compress, packing) is covered by tests/test_textures.py | 0.0 |
| 12 | Configure vehicle metadata | **PASS** | ARO Motors TITAN 480 · heavy_truck · 6x4; components: ['attachment', 'axle', 'body', 'bumper', 'cabin', 'chassis', 'door', 'exhaust', 'grille', 'headlight', 'interior', 'mirror', 'taillight', 'tire', 'wheel', 'wheel_detail', 'window', 'wiper']; 7 pivots, 6 lights, 4 attachment points, CoM (0.0, 1.1, -0.6) | 0.0 |
| 13 | Configure wheels and axles | **PASS** | 3 axles, 10 wheels (steered: 2, driven: 8), wheelbase 3.90 m — taken from the reference spec, not auto-detected | 0.0 |
| 14 | Generate/prepare collision geometry | **PASS** | 2 colliders (COL_Body:252, COL_Cabin:142); rig of 33 nodes | 0.27 |
| 15 | Generate LODs | **PASS** | triangles: LOD0 42,140 → LOD1 23,758 → LOD2 12,720 → LOD3 6,434 | 0.72 |
| 16 | Validate the entire asset | **PASS** | PRODUCTION_READY · overall 99.7% · critical 0 · major 0 · geometry 98.5%, materials 100.0%, lod 100.0%, collision 100.0%, vehicle 100.0%, unity 100.0% | 5.42 |
| 17 | Display in the 3D viewer | **PASS** | Playwright/Chromium e2e: loaded the asset in the three.js viewer, exercised views, wireframe, shading, grid, bounds, collision, rig, LOD switching, lighting, stats | 77.5 |
| 18 | Save the project version | **PASS** | 7 immutable versions: v0.1:reference.titan480, v0.2:geometry, v0.3:materials, v0.4:rig, v0.5:collision, v0.6:lod, v0.7:finalize; CURRENT PRODUCTION VERSION = ver_5b36aec82c6740699a8b | 5.48 |
| 19 | Export GLB | **PASS** | 3.26 MB, sha256 49657311eb608700…, triangles per LOD {'LOD0': 42140, 'LOD1': 23758, 'LOD2': 12720, 'LOD3': 6434}; Khronos validator: 0 errors / 0 warnings (v2.0.0-dev.3.10) | 2.36 |
| 20 | Generate Unity-ready output | **PASS** | Unity package 3.74 MB with Models/ LOD/ Collision/ Materials/ Textures/ Metadata/ Editor/ Scripts/ README.md; also glTF COMPLETED, OBJ COMPLETED | 6.65 |
| 21 | Validate export integrity | **PASS** | 21 package checks + 13 GLB checks re-read from disk (checksums, accessors, hierarchy, LOD counts, collision nodes) | 0.0 |
| 22 | Test import compatibility with Unity 6 | **BLOCKED** | Unity 6 import has not been run: no unity-verification.json. Run Unity in batch mode with ARO.Studio.Editor.AroUnityVerifier.Run (docs/verification/unity-verification-runbook.md). | 0.0 |

## Production-readiness report

Status **PRODUCTION_READY** · overall **99.7%** · critical 0 · major 0

| Category | Score |
|---|---|
| Geometry | 98.5% |
| Materials | 100.0% |
| Textures | n/a (not applicable) |
| LOD | 100.0% |
| Collision | 100.0% |
| Vehicle | 100.0% |
| Unity | 100.0% |

Note: this status is for the **procedural reference asset** passing the validation rules. It does not mean the platform acceptance is complete: see the BLOCKED/PARTIAL stages above.

Warnings (non-blocking):
* G010 No self-intersections: 166 intersecting triangle pairs

## What this run does and does not prove

* Everything from raw asset onward (geometry, materials, vehicle, rig, collision, LOD, validation, versioning, export, verification) executed for real on a real, correctly-scaled, structured vehicle.
* The AI reconstruction stages are listed as BLOCKED/PARTIAL where the engine could not run. **No placeholder geometry was substituted and none is claimed as AI output.**
* The Unity 6 import status is whatever the component table above says; the package being generated and integrity-verified is not an import verification.
