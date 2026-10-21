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
| **TripoSR licence & supply chain** | ✅ MIT evidence recorded ([model-licenses](docs/models/model-licenses.md)); weights revision + SHA-256 + sizes **pinned in the lock** (recorded from a Colab run on 2026-10-11 by `scripts/pin_triposr_weights.py`; not re-fetched by the author of this note); loader verifies SHA-256 before deserialising, uses `weights_only`, class allow-list. `ModelLock.missing()` is empty, so the licence gate opens from the lock. A complete lock proves artefact identity — **not** that inference works. |
| **One-click “Convert to 3D”** (Generation page, `POST /api/convert`) | ✅ implemented: one image → reconstruct → prepare → export a verified GLB as a single job with per-step status; unit- and browser-tested **with a labelled test-double engine only**. It fails fast, creating nothing, if the real engine cannot run. Not yet run with the real model. |
| **AI reconstruction (TripoSR)** | ⚠️ **Not yet proven through the Studio.** The adapter, licence gate and weights verification are in place and unit-tested with stand-ins. The committed evidence contains **no real inference run**; the build sandbox has no GPU and cannot reach Hugging Face. Reproduce with [docs/verification/real-inference-smoke.md](docs/verification/real-inference-smoke.md) (`notebooks/aro_real_inference_colab.ipynb`). |
| **Unity 6 import** | ⛔ **BLOCKED — never run.** Package is generated and integrity-verified; a Unity batch-mode verifier ships in every package but has only been syntax-checked. See [docs/verification/unity-verification-runbook.md](docs/verification/unity-verification-runbook.md). |
| **Docker** | ✅ image built and run for real (hardened, 22/22 steps, 34/34 HTTP checks) — see [docs/deployment/docker.md](docs/deployment/docker.md) for caveats. Not deployed to a Hugging Face Space. |
| TITAN 480 reference asset | ✅ original, procedural, clearly labelled *not AI* — used to exercise every post-reconstruction stage |
| Future capabilities (text-to-3D, retopology, auto-rigging, part detection, …) | ⛔ not implemented, not faked |

The full 22-stage acceptance run with per-stage results: [docs/acceptance/titan480-acceptance-report.md](docs/acceptance/titan480-acceptance-report.md). The report lists **seven separate component statuses** (platform, procedural asset, real AI asset, validated production asset, Unity import, Docker, security/regression) derived only from recorded evidence. **Production readiness is not claimed** until all seven are PASS; today the real-AI and Unity components are BLOCKED. Repository hygiene (public repo, no licence chosen): [docs/repository-safety.md](docs/repository-safety.md).

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
python scripts/run_regression.py         # every gate with real counts → docs/acceptance/evidence/regression/
python scripts/run_acceptance.py         # 22-stage TITAN 480 acceptance report + seven component statuses
scripts/verify_docker.sh                 # real Docker build + hardened run + HTTP suite
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
