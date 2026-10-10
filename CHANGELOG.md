# Changelog

## Unreleased — post-audit completion and verification

* TripoSR: licence evidence recorded; machine-readable lock (`engines/locks/triposr.json`) with revision/checksum pinning tool, SHA-256 verification before load, `weights_only=True` (torch ≥ 2.6), config class allow-list. Gate stays closed until the lock is complete — by design.
* `ai_pipeline`: orient → scale → clean → decimate → re-ground → UV/bake → collision → LOD → validate for single-mesh AI output (tested on a synthetic mesh only). Fixed convex-hull reduction for smooth meshes.
* Evidence tooling: `record_real_inference.py` + `verify_on_gpu_host.sh` (GPU), Unity batch-mode verifier + expectations file in every package, `verify_docker.sh`, `run_regression.py`, evidence readers and the seven-component status in the acceptance report.
* Docker: digest-pinned base, cgroup-aware resource limits, clear error for an unwritable data dir; build/run verified in a sandbox.
* Repository safety tests; project licence deliberately left to the owner.
* **Still not done:** real TripoSR inference, Unity 6 import verification, Hugging Face Space deployment.

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
