# ARO 3D Studio — architecture overview

ARO 3D Studio is the internal **asset factory** for African Online Roads: it turns a reference image (or an existing mesh) into a validated, optimised, versioned, Unity-ready asset. It prepares assets; it does **not** contain vehicle physics, a vehicle controller or any gameplay (those belong to the game).

```
Concept image → Analysis → Preprocessing → Image-to-3D engine → RAW asset
   → Geometry → Materials → Textures → Vehicle setup → Rig → Collision → LOD
   → Validation → 3D viewer → Immutable version → Export (GLB/glTF/OBJ/Unity package) → Unity 6
```

## Honesty rules the code enforces

| Rule | Where it is enforced |
|---|---|
| No placeholder geometry when inference fails; a failed generation creates **no** version | `generation/service.py`, tested in `test_engine_unavailable_ends_model_error_without_placeholder_geometry` |
| A model that cannot run reports exactly why and how to activate it | `engines/triposr.py::availability` |
| A model whose weights licence is unverified cannot run until the deployer attests | `engines/registry.py::license_gate` |
| Blocked models (Lyra 2.0) can never be registered | `engines/registry.py::BLOCKED_MODELS` |
| Scores never override critical failures | `validation/engine.py::run_validation` |
| `PRODUCTION_READY` only via a validated version | `assets/service.py::designate_production_version` |
| Raw reconstructions are immutable and never deleted individually | `assets/service.py`, `scene/store.py` (hash-verified on load) |
| Exports are re-opened and verified; failed exports are kept with their report | `export/service.py`, `export/verify.py` |
| The procedural TITAN 480 reference is labelled "not AI" everywhere | `vehicles/titan480.py`, provenance field, UI, package README |

## Package map

| Package (`aro_studio/…`) | Responsibility | Spec § |
|---|---|---|
| `config.py`, `app_context.py` | environment-driven settings; composition root | 52–53 |
| `core/` | ids, enums, errors + plain-language explanations, hashing/cache keys, cancellation | 10, 36 |
| `security/` | filename sanitising, path-traversal guard, content sniffing, safe zip extraction, rate limit, audit log | 35, 52 |
| `db/` | SQLite + versioned migrations | 28 |
| `storage/` | on-disk layout, stage dirs, read-only versions, temp isolation | 12, 27 |
| `projects/`, `assets/` | project lifecycle, source images, asset taxonomy/metadata, immutable versions, status machine, mesh import | 6, 7, 26, 43, 45 |
| `imaging/` | validation, orientation, matting (replaceable), preprocessing, analysis | 8, 9 |
| `engines/` | `ImageTo3DEngine` interface, registry, TripoSR adapter, model memory manager | 4, 10, 31 |
| `generation/` | generation job, cache, resource preflight | 10, 11, 30, 32 |
| `jobs/` | persistent priority queue, retry, cancel, timeout, recovery | 29, 44 |
| `geometry/` | inspection (11 defect classes), operations, scene pipeline, self-intersection test | 13 |
| `materials/`, `textures/` | PBR library, UV unwrap (isolated), bake, resize/compress/pack | 14, 15 |
| `vehicles/`, `animation/` | component roles, vehicle spec, TITAN 480 reference, rig/pivots | 16, 17, 20, 42 |
| `collision/`, `lod/` | colliders (box/sphere/capsule/hull/mesh/vehicle), configurable LODs | 18, 19 |
| `validation/` | rule engine, readiness report | 24, 25 |
| `export/` | glTF/GLB/OBJ writers, Unity package, verifier | 21, 22 |
| `observability/` | JSON logs with redaction, metrics, resource monitor | 30, 36 |
| `api/`, `ui/` | FastAPI + static SPA with three.js viewer | 23, 33 |

Differences from the suggested repository layout (spec §47 allows this): one Python package instead of ~25 top-level folders, so imports, typing and packaging stay simple; no empty folders were created for appearance; `workers/` and `queue/` are folded into `jobs/`.

## Key decisions

* **SQLite, not a server database.** Zero infrastructure, transactional, works on Hugging Face and any container. WAL mode; one writer lock.
* **In-process worker threads, not Celery/Redis.** Free hosts give one small container. Jobs are persisted rows, so they survive restarts (interrupted jobs are marked `FAILED/INTERRUPTED`, never dropped).
* **Immutable versions + a declarative scene manifest.** A version is a directory (`manifest.json` + `.npz` meshes + textures + reports) hashed file-by-file and verified on load.
* **Canonical conventions:** metres, right-handed, +Y up, +Z forward, +X = vehicle left, origin on the ground at the wheelbase centre.
* **Replaceable models.** Everything that uses AI talks to an interface; adding an engine is one class + one registry line (see [model-registry](../models/model-registry.md)).

## Real vs. not-yet-implemented

| Capability | State |
|---|---|
| Image validation / preprocessing / classical matting / analysis | implemented, tested |
| Neural background removal (rembg) | adapter present; optional dependency, **not run here** |
| Image-to-3D (TripoSR) | real adapter written against the published `tsr` API; **not executed here** (no weights/GPU/network to Hugging Face) — see [model-requirements](../models/model-requirements.md) |
| Object classification / detection, segmentation, retopology, auto-rigging, vehicle part detection, text-to-3D, multi-view | **not implemented**; interfaces/extension points only where noted; nothing is faked |
| Geometry / materials / textures / vehicle / rig / collision / LOD / validation / versioning / export | implemented, tested (see `docs/acceptance`) |
| Unity 6 import | package generated and integrity-verified; **import not executed** (no Unity here) |
