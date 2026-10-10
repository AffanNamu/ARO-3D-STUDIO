# ARO TITAN 480 — acceptance run

**Verdict: NOT COMPLETE — production readiness is not claimed**

Studio 0.1.0 · Python 3.13.16 · Linux-6.18.44-fc-v114-x86_64-with-glibc2.39 · 4 vCPU · 16093 MB RAM · GPU: none · run time 63s
Pipeline input: **procedural_reference**

Summary: BLOCKED 3, PARTIAL 3, PASS 15, SKIPPED 1

| # | Stage | Status | Detail | s |
|---|---|---|---|---|
| 1 | Create ARO TITAN 480 project | **PASS** | project prj_48a8147ac75f4c439e95, asset ast_cbea93097eb24026ae6b | 0.0 |
| 2 | Upload concept image | **PARTIAL** | image is a software render of the procedural reference model, not an artist's concept image; stored by content hash | 0.65 |
| 3 | Validate the input | **PASS** | 1024x1024 png, quality 1.0, warnings: none; analysis: bg=uniform, category auto-detected=None | 0.0 |
| 4 | Preprocess the image | **PASS** | orientation → background_analysis → background_removal → crop → resize → normalize → 512x512 model input | 0.18 |
| 5 | Load the image-to-3D model | **BLOCKED** | TripoSR cannot load here: The 'tsr' package (TripoSR source) is not importable.; Missing Python packages: torch, omegaconf, einops, transformers, huggingface_hub, torchmcubes.; weights licence 'claimed' not yet verified (set ARO_VERIFIED_MODEL_LICENSES=triposr). To activate: git clone https://github.com/VAST-AI-Research/TripoSR && add it to PYTHONPATH (the Dockerfile does this). / pip install -r requirements-triposr.txt  (torch must match the host CUDA version) | 0.0 |
| 6 | Run actual reconstruction | **BLOCKED** | no real reconstruction was run; NO placeholder geometry was substituted. See docs/models/model-requirements.md for the GPU test strategy | 0.0 |
| 7 | Save raw output | **PARTIAL** | no AI output exists; the procedural reference was saved as the raw version ver_e9f660cc8aee4f8eacad so the remaining stages can run on a real, structured vehicle | 0.09 |
| 8 | Process the geometry | **PASS** | standard cleanup: 15,736 → 15,736 faces; steps ['remove_invalid', 'merge_vertices', 'remove_degenerate', 'remove_duplicate_faces', 'remove_small_components', 'fix_normals'] | 1.92 |
| 9 | Repair valid geometry problems | **PARTIAL** | defects found before repair: {'duplicate_vertices': 1}; after: holes=0, non-manifold=0. Repair operations (merge, fill holes, normals, fragments) are unit-tested on damaged meshes | 0.0 |
| 10 | Process materials | **PASS** | 12 PBR materials (paint, glass, rubber, chrome, plastic, lights, interior…) | 0.1 |
| 11 | Process textures where supported | **SKIPPED** | the procedural reference uses flat-colour PBR materials (no vertex colours to bake). The texture pipeline (xatlas unwrap, projection baking, resize, compress, packing) is covered by tests/test_textures.py | 0.0 |
| 12 | Configure vehicle metadata | **PASS** | ARO Motors TITAN 480 · heavy_truck · 6x4; components: ['attachment', 'axle', 'body', 'bumper', 'cabin', 'chassis', 'door', 'exhaust', 'grille', 'headlight', 'interior', 'mirror', 'taillight', 'tire', 'wheel', 'window', 'wiper']; 7 pivots, 6 lights, 4 attachment points, CoM (0.0, 1.1, -0.6) | 0.0 |
| 13 | Configure wheels and axles | **PASS** | 3 axles, 10 wheels (steered: 2, driven: 8), wheelbase 3.80 m — taken from the reference spec, not auto-detected | 0.0 |
| 14 | Generate/prepare collision geometry | **PASS** | 2 colliders (COL_Body:96, COL_Cabin:68); rig of 33 nodes | 0.1 |
| 15 | Generate LODs | **PASS** | triangles: LOD0 15,736 → LOD1 8,922 → LOD2 4,664 → LOD3 2,356 | 0.36 |
| 16 | Validate the entire asset | **PASS** | PRODUCTION_READY · overall 99.7% · critical 0 · major 0 · geometry 98.5%, materials 100.0%, lod 100.0%, collision 100.0%, vehicle 100.0%, unity 100.0% | 1.98 |
| 17 | Display in the 3D viewer | **PASS** | Playwright/Chromium e2e: loaded the asset in the three.js viewer, exercised views, wireframe, shading, grid, bounds, collision, rig, LOD switching, lighting, stats | 51.94 |
| 18 | Save the project version | **PASS** | 7 immutable versions: v0.1:reference.titan480, v0.2:geometry, v0.3:materials, v0.4:rig, v0.5:collision, v0.6:lod, v0.7:finalize; CURRENT PRODUCTION VERSION = ver_dbe70de6fbf34b8faa38 | 2.11 |
| 19 | Export GLB | **PASS** | 1.12 MB, sha256 5ab462e66e087903…, triangles per LOD {'LOD0': 15736, 'LOD1': 8922, 'LOD2': 4664, 'LOD3': 2356}; Khronos validator: 0 errors / 0 warnings (v2.0.0-dev.3.10) | 0.92 |
| 20 | Generate Unity-ready output | **PASS** | Unity package 1.13 MB with Models/ LOD/ Collision/ Materials/ Textures/ Metadata/ Editor/ Scripts/ README.md; also glTF COMPLETED, OBJ COMPLETED | 2.08 |
| 21 | Validate export integrity | **PASS** | 20 package checks + 13 GLB checks re-read from disk (checksums, accessors, hierarchy, LOD counts, collision nodes) | 0.0 |
| 22 | Test import compatibility with Unity 6 | **BLOCKED** | Unity 6 is not installed in this environment, so the package was NOT imported into Unity. Structural compatibility is covered by stage 21 (+ Khronos glTF-Validator). To complete: install glTFast in a Unity 6 project, import the package, run ARO ▸ Build Vehicle Prefab (see Metadata/README.md in the package) and report the result. | 0.0 |

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
* G010 No self-intersections: 1298 intersecting triangle pairs

## What this run does and does not prove

* Everything from raw asset onward (geometry, materials, vehicle, rig, collision, LOD, validation, versioning, export, verification) executed for real on a real, correctly-scaled, structured vehicle.
* The AI reconstruction stages are listed as BLOCKED/PARTIAL where the engine could not run. **No placeholder geometry was substituted and none is claimed as AI output.**
* The Unity 6 import was not executed. The package is integrity-verified, not import-verified.

## Evidence

Screenshots captured by the browser end-to-end test (headless Chromium, software GL): [`screenshots/`](screenshots/) — dashboard (honest engine warning), the reference in the viewer, LOD/collision/rig overlays, the exports panel and the validation report. The exported GLB from this run is [`ARO-TITAN-480.glb`](ARO-TITAN-480.glb) (open it in any glTF viewer; Khronos glTF-Validator: 0 errors / 0 warnings).

## To close the remaining gaps

1. **Stages 5–6 (real reconstruction):** on a host with torch + TripoSR + weights, after reading the model card: `ARO_VERIFIED_MODEL_LICENSES=triposr ARO_RUN_MODEL_TESTS=1 pytest -m model` then `python scripts/run_acceptance.py --verify-licence triposr`. Fix any first-run integration details the real weights reveal.
2. **Stage 22 (Unity 6 import):** follow `docs/unity/unity-integration.md` in a Unity 6 project with glTFast and record the outcome here.
3. **Stage 2:** supply an artist-made ARO TITAN 480 concept image (this run used a render of the procedural reference).
