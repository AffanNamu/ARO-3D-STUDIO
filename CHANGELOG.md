# Changelog

## 0.1.0 — initial platform build

* Platform: projects, asset library/taxonomy, immutable versioning with integrity hashes, asset status machine, production-version designation gated by validation, SQLite persistence with migrations, persistent priority job queue (retry/cancel/timeout/recovery), audit log, observability, security layer.
* Image pipeline: content-validated intake, orientation, quality metrics, classical + optional neural matting, preprocessing, advisory analysis (no invented categories).
* Engines: `ImageTo3DEngine` abstraction, registry with licence gate and blocked models (Lyra 2.0), TripoSR adapter (not executed in the build environment), model memory manager, generation job with cache, resource preflight, failure preservation.
* Geometry/materials/textures/vehicle/rig/collision/LOD: inspection (incl. self-intersections), operations, scene-wide transforms, PBR library, isolated xatlas unwrap + projection baking, ARO TITAN 480 procedural reference, rig builder, convex collision, configurable LODs.
* Validation: 46 rules, readiness report where scores never override critical failures.
* Export: GLB/glTF/OBJ + Unity package, independent verification, Khronos validator hook.
* UI: dark production UI with 9 sections and a three.js viewer (views, wireframe, shading modes, lighting, grid, bounds, collision/rig overlays, LOD switching, statistics).
* Docs, CI, Dockerfile for Hugging Face Spaces, acceptance script and report.
* **Not done:** real TripoSR inference, Unity 6 import verification, any "future capability" listed in the spec.
