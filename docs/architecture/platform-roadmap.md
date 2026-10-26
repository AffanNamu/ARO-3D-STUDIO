# ARO 3D Studio: platform vision and roadmap

Written 2026-10-26, after the owner widened the goal: not a TripoSR fixer or a basic converter, but a 3D creation and asset-production
platform that serves African Roads Online (ARO) first (vehicles, interiors, roads, buildings, environments, with a GTA-level visual
ambition) and other creators after. This document is the map from that vision to the repository. The engine decision and the measured
baselines are in [product-reassessment.md](product-reassessment.md); the worker is in [gpu-worker.md](gpu-worker.md); the conditional
training plan is in [fine-tuning-plan.md](fine-tuning-plan.md).

Status words: PASS / PARTIAL / BLOCKED / FAIL / NOT STARTED. "Evidence" means committed output of a real run, never a claim.

## 1. Principles that drive every decision

1. **Asset quality is the product.** A valid GLB is not a result. Every generator is judged by the reference-fidelity gate
   (`aro_studio/quality/`) and then by a person looking at multi-view sheets. Validation green with poor geometry is a FAIL.
2. **The Studio and the generator are separate.** The Studio (UI, jobs, preparation, validation, export) is light and runs anywhere.
   Engines run in a GPU worker (`aro_worker/`) over HTTP: Colab now, a rented GPU server or VPS later, with no rebuild.
3. **Engines are replaceable; licences are enforced.** Engines are plug-ins behind one contract. Each carries a licence record kept in the
   Studio; nothing runs until a person attests it. Restricted engines (Hunyuan3D) are evaluation yardsticks, never product dependencies.
4. **Honest evidence.** Measured numbers, sheets, hashes, commits, GPU and versions are saved with every run so results reproduce.
   Failures are reported with their cause; nothing is mocked into a pass.
5. **Spend nothing without authorisation.** Colab free tier is the lab. Anything that needs money (rented GPU, paid APIs, training
   compute) is proposed with a cost and waits for an explicit yes.

## 2. What a creator can do, versus Meshy, and what we add

| Capability | Meshy-class service | ARO 3D Studio today | Target |
|---|---|---|---|
| Image to 3D | Closed model, very dense textured mesh (about 6 M triangles in the owner's screenshots) | TripoSR local; TripoSG and Hunyuan3D shape (Colab-ready, unrun); TRELLIS.2 (24 GB GPU, unrun) | Best open engine per use, side by side, measured |
| Colour / PBR | Generated texture | Colour from the engine, or projected from the photo for geometry-only engines; PBR carried only as the raw file | PBR base/normal/ORM baked onto the game mesh |
| Game-ready output | Not the focus (triangle-count control only) | Orientation, real size, decimation to budget, UV atlas, LOD0-3, collision hull, 50-rule validation, exact-size restore | Same, plus high-to-low normal bake and wheel separation |
| Viewport | Interactive | three.js viewer: orbit, LOD switch, overlays | Wireframe, matcap, turntable, measure, side-by-side compare |
| Export | Many formats | GLB, glTF, OBJ, Unity package (integrity-verified); FBX, USD, .blend through the optional Blender backend, each re-imported by Blender | Unreal and Unity import verified in the editors |
| Evidence and benchmarking | None visible | Fidelity score, sheets, bake-off harness, committed baselines | Public benchmark page per engine and image |
| Vehicles | Generic | Category-aware proportions; vehicle spec, collision, rig pivots (artist-supplied) | Automatic wheel/axle detection, steering and suspension rig hints |
| Environments | Single objects | Not started | Modular kits: generate pieces, snap into roads, buildings, interiors |

The differentiator is not a bigger mesh: it is **an asset a game can use** (budget, LODs, collision, correct scale and axes, tested
import), with **evidence** attached, from a platform the owner controls.

## 3. Architecture (what exists, what is next)

```
 UI (upload, settings, progress, viewport, history, compare)
        |
 Studio API + job queue (aro_studio/)       ---- Unity 6 / Blender / Unreal / glTF viewers
   matting -> cut-out                                       ^
   engine registry + licence gate                          |  verified exports
   |-- local: TripoSR                                      |
   |-- remote: aro_studio/engines/remote.py --HTTP--> GPU worker (aro_worker/)  [Colab now, server later]
   |                                                        TripoSG | Hunyuan3D (eval) | TRELLIS.2 (24 GB)
   v
 raw GLB (kept untouched)
   v
 frame detection (up axis from the reference) -> orient, yaw-align, scale to real size
   v
 geometry-only engines: reference-photo projection (seen / mirrored / filled, declared)
   v
 cleanup, smooth, decimate to budget, UV, bake colour (and next: high-to-low normal/ORM bake)
   v
 collision, LOD0-3, validation (50 rules) + fidelity score -> export + evidence
```

Implemented in this repository: everything above except the items marked "next" and the compare viewer.

## 4. Work packages

Each package has an exit test that fails if the capability is not really there.

| # | Package | Files | Exit test | Status |
|---|---|---|---|---|
| P0 | **Stronger-engine evidence on real images** (Colab): TripoSG (and optional Hunyuan3D yardstick) on the owner's truck and car, compared with the committed TripoSR numbers | `notebooks/aro_engine_lab_colab.ipynb`, `scripts/lab_bootstrap.py`, `scripts/engine_bakeoff.py`, `aro_worker/engines/` | `lab-evidence-repo.zip` committed; table shows the engines against TripoSR; sheets reviewed by the owner | Notebook and plug-ins BUILT; real run BLOCKED on a Colab session |
| P0b | Verify the best result in **Unity 6** | `docs/verification/unity-verification-runbook.md`, Unity package from the lab run | Verifier output committed from a real editor | BLOCKED on the editor |
| P1 | **Game-ready detail**: keep the engine's dense mesh and PBR maps, bake normal/ORM onto the budget mesh | `textures/normal_bake.py`, `textures/pipeline.py`, `processing/ai_pipeline.py` | Prepared car and truck keep panel detail at 20-50 k triangles with a normal map; PBR channels present | PARTIAL: the normal-map bake is built and tested (recovers analytic normals within 3 degrees on a synthetic surface; a dense engine mesh produces a normal map in the prepared asset and its GLB; on by default for every engine except TripoSR). Not yet seen on a real engine mesh; ORM (roughness/metallic) transfer from an engine's PBR texture not built |
| P2 | **Vehicle intelligence**: wheel detection and separation, pivots, symmetry, ground-plate removal | `vehicles/`, `geometry/` | Wheels are separate nodes with correct pivots on the car and the truck | NOT STARTED |
| P3 | **Workspace**: three-pane layout, wireframe/matcap/turntable, compare two results side by side | `ui/static/js/` | Owner can upload, generate, inspect and export from one screen | PARTIAL (viewer and engine picker exist) |
| P4 | **Export for other tools**: FBX/USD/Blend through an optional Blender backend, verified by re-import; preserve scale, axes, materials and (where present) animation | `export/blender.py`, `export/blender_worker.py`, `export/service.py`, `tests/test_blender_export.py`, CI job `blender` | Re-import report: triangle count, extents, materials, unit scale match | BUILT: formats `fbx` (Unity and Unreal conventions), `usd`, `blend`, API `/api/export-formats`, UI checkboxes; every export is re-imported by Blender and compared. Animation is not exported (the Studio has none yet). Opening the files in Unreal Engine or Unity is NOT done |
| P5 | **Environments**: roads, buildings, interiors from modular generated kits and a scene assembler | new `scenes/` | A road junction with buildings assembled and exported with correct scale | NOT STARTED |
| P6 | **Server deployment**: Docker worker on a rented GPU, TLS, token, queue | `worker/`, `docs/architecture/gpu-worker.md` | Same bake-off run against a remote URL | Scripts written, unrun |
| P7 | **Specialised model** (conditional): fine-tune only if the gate in `fine-tuning-plan.md` trips | none yet | Gate evidence recorded first | NOT STARTED, correctly |

### P1 design: high-to-low detail transfer

TRELLIS.2 and TripoSG return hundreds of thousands of triangles. A game mesh has 20-50 k. The detail must move into textures:

1. Keep the dense raw mesh as the source; decimate a copy to the budget; unwrap it (xatlas, already used).
2. For every texel on the low mesh find the closest point on the dense mesh (k-d tree over its triangle centroids, barycentric refinement);
   read the dense surface normal there and express it in the low mesh's tangent frame: the normal map. Read colour and ORM the same way
   (from the engine's own texture when it has one, otherwise from vertex colours).
3. Test with a synthetic dense surface with known bumps (the recovered normals must match the analytic ones) before any real mesh.

This is the step that makes a 24 k-triangle truck read as detailed under lights, and it is independent of which engine produced the dense mesh.

### P4 design: export backends

glTF/GLB, OBJ and the Unity package are written natively. FBX, USD and `.blend` are produced by an optional Blender backend (a headless
Blender, `pip install bpy` on a supported Python, or the distribution package) behind the same "available or here is exactly why not"
contract as engines. Every export is re-imported (Blender for glTF/FBX, the Unity batch verifier for Unity) and compared: triangle count,
extents in metres, material count, up axis. Animation is carried only where the source has it (the Studio's rig data), and the report says
what was dropped.

## 5. How results are proven

1. Real engine on real reference images (Colab or server), through the Studio's pipeline, not a side script.
2. `fidelity.json` + contact sheet + raw hash + prepared hash + environment + commit saved per run (`engine_bakeoff.py`, `lab_notebook.py`).
3. A person reviews the sheets and records a verdict; the numbers never substitute for that.
4. Import into Unity 6 (and Blender) with the verifier outputs committed.
5. Only then does the status table change.

## 6. Colab now, servers later

Colab runs the same worker code in an isolated Python 3.10 environment that the notebook builds (`scripts/lab_bootstrap.py`); the Studio
side calls it on `127.0.0.1`. Moving to a server changes one URL. Limits to remember: a free T4 (about 15 GB, no bf16) runs TripoSG and the
Hunyuan3D shape model, not TRELLIS.2; sessions end and cache is lost, so every run packages its evidence; weights download each time.
