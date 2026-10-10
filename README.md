---
title: ARO 3D Studio
emoji: 🚚
colorFrom: orange
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
license: other
short_description: Production 3D asset pipeline for African Online Roads
---

# ARO 3D Studio

The internal **3D asset factory** for [African Online Roads](#relationship-to-african-online-roads): reference image → analysis → preprocessing → image-to-3D → geometry → materials → textures → vehicle setup → collision → LOD → validation → 3D preview → immutable versions → GLB / glTF / OBJ / **Unity 6 package**.

Zero-budget by design (₦0): open-source stack, no paid APIs, no paid hosting, no paid GPU. Nothing is faked: where something cannot run, the Studio says exactly why and how to activate it.

## Current status (read this first)

| Area | Status |
|---|---|
| Studio platform (projects, library, versioning, jobs, security, observability, UI + 3D viewer) | ✅ implemented and tested |
| Geometry inspection/repair, materials, textures, vehicle setup, rig, collision, LOD | ✅ implemented and tested |
| Validation / production-readiness engine (46 rules; scores never override critical failures) | ✅ implemented and tested |
| Export: GLB, glTF, OBJ, Unity package + independent verification (Khronos glTF-Validator: 0 errors/0 warnings on the TITAN 480 GLB) | ✅ implemented and tested |
| **AI reconstruction (TripoSR)** | ⚠️ adapter written against the published API; **not executed** in the development environment (no GPU, no access to huggingface.co). Gated real-inference tests + exact activation steps provided. **Not claimed to work until run on a GPU host.** |
| **Unity 6 import** | ⚠️ package generated and integrity-verified; **import not executed** (no Unity available). Importer script untested until first run. |
| TITAN 480 reference asset | ✅ original, procedural, clearly labelled *not AI* — used to exercise every post-reconstruction stage |
| Future capabilities (text-to-3D, retopology, auto-rigging, part detection, …) | ⛔ not implemented, not faked |

The full 22-stage acceptance run with per-stage results: [docs/acceptance/titan480-acceptance-report.md](docs/acceptance/titan480-acceptance-report.md). **Production readiness of the platform as a whole is not claimed** until stages 5–7 (real inference) and 22 (Unity import) pass; see that report.

## Quick start (local, CPU, no AI)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # optional
python -m uvicorn app:app --port 7860
# open http://localhost:7860 → Projects → New project → New asset (Heavy Trucks)
# → 3D Studio → "Create ARO TITAN 480 reference" → run the pipeline steps → Validate → Export
```

With a GPU and TripoSR: see [docs/models/model-requirements.md](docs/models/model-requirements.md).

## Typical workflow

1. **Projects** → create a project, upload a concept image (validated, hashed, analysed).
2. **Generation** → choose engine + preset, preview the exact model input, queue the job (progress, cancel, retry, cache). Or **3D Studio → Import mesh**.
3. **3D Studio** → Geometry → Materials → Textures → Vehicle → Collision → LOD → Validate → Export. Each operation creates a new immutable version; the raw reconstruction stays recoverable.
4. **Validation** → production-readiness report; mark one version as the **current production version** (only possible after a passing validation).
5. **Exports** → download the GLB or the Unity package (README, LOD, collision, materials, metadata, checksums, editor importer inside).

## Tests

```bash
pip install -r requirements-dev.txt
pytest                                   # 200+ unit/integration/security/export/validation/performance tests
pytest tests/e2e                         # browser end-to-end (needs Playwright Chromium)
ARO_RUN_MODEL_TESTS=1 pytest -m model    # real TripoSR inference (GPU host + weights + verified licence)
ruff check . && ruff format --check . && mypy aro_studio app.py
python scripts/run_acceptance.py         # 22-stage TITAN 480 acceptance report
python scripts/audit_licenses.py --check # dependency licence audit
```

## Documentation

[Architecture](docs/architecture/overview.md) · [Generation](docs/architecture/generation-architecture.md) · [Assets](docs/architecture/asset-architecture.md) · [Models & licences](docs/models/model-licenses.md) · [Pipelines](docs/pipelines/mesh-processing.md) · [Vehicle standards](docs/vehicles/vehicle-standards.md) · [Production readiness](docs/validation/production-readiness.md) · [Unity integration](docs/unity/unity-integration.md) · [Hugging Face deployment](docs/deployment/huggingface.md) · [Troubleshooting](docs/troubleshooting/common-problems.md)

## Licences

* Third-party components: [docs/dependency-licenses.md](docs/dependency-licenses.md) (generated from installed metadata) and [docs/models/model-licenses.md](docs/models/model-licenses.md). three.js is bundled under MIT.
* **This project's own licence is not yet chosen** — see [LICENSE](LICENSE). The Hugging Face metadata uses `license: other` until the owner decides.
* NVIDIA Lyra 2.0 is **blocked** and can never be registered.

## Relationship to African Online Roads

ARO 3D Studio is the asset factory; African Online Roads is the game (Unity 6: vehicle controller, physics, multiplayer, traffic, AI, weather, world). The Studio prepares correct scale, orientation, pivots, materials, LODs, collision and vehicle metadata — it does not implement gameplay.
