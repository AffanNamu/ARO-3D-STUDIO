# 01 · Repository audit (Phase 0, task 1)

Audit date: 2026-11-08 · Commit audited: `313a864` (CI run 75 green) · Method: file counts, grep over the tree, reading the entry points, `pytest --collect-only`, `git log`, and the evidence already committed under `docs/acceptance/`. Evidence grades are defined in [`competitive-matrix.md`](competitive-matrix.md) (R = verified in the repository).

## 1. What the repository is today

A **single-user, single-machine image-to-3D preparation tool**, strongest at conventional 3D processing and verification, with a thin AI layer.

| Fact | Value (R) |
|---|---|
| History | 81 commits, 2026-10-10 to 2026-10-29 |
| Studio code (`aro_studio`) | 135 files, about 18,300 lines of Python, JavaScript, HTML and CSS (the vendored 809 KB three.js bundle excluded) |
| GPU worker (`aro_worker`) | 11 files, about 1,100 lines |
| Scripts / tests | about 4,100 lines of scripts; 445 tests (about 7,800 lines) |
| API | FastAPI, 58 routes (`/api/projects` 15, `/api/versions` 10, `/api/assets` 8, `/api/jobs` 6, `/api/exports` 4, others) |
| UI | vanilla JavaScript views (12 files) on a vendored three.js build; no framework, no TypeScript |
| Persistence | SQLite file, local file tree, in-process job threads |
| CI | ruff, mypy, bandit, pip-audit, licence audit, tests on Python 3.10/3.11/3.12, Blender round-trip job, Playwright browser tests, Docker build; green at `313a864` |
| Docs | 51 files under `docs/` |

## 2. Capabilities that really exist (and how they were verified)

| Area | State | Evidence |
|---|---|---|
| Geometry preparation: orient, scale, pivot, cleanup, hole fill, smoothing, 5-stage decimation | works on real TripoSR meshes | unit tests; `docs/acceptance/evidence/quality/` |
| UV unwrap + colour bake + normal-map transfer | works; two serious defects were found and fixed during this audit period (below) | `tests/test_textures.py`, `tests/test_normal_*.py`, Blender sampling test |
| LOD0-3 and collision generation | works | `tests/test_collision_hull.py`, LOD tests |
| Validation (50 rules) | works | validation tests; Khronos validator in CI |
| Exports: GLB, glTF, OBJ, Unity package; FBX, USD, .blend through Blender | GLB fully tested; others verified by Blender re-import; Unity package never imported in Unity | `tests/test_export_validation.py`, `tests/test_blender_export.py` |
| Engines | TripoSR (local) real; GPU worker with TRELLIS.2, TripoSG, Hunyuan3D plug-ins | see section 3 |
| Reference-quality scoring (silhouette IoU, proportions, contact sheet) | works | `tests/test_fidelity.py` |
| Licence gate (engines refuse to run until the owner attests the weights licence) | works | `tests/test_remote_engine.py` |
| Web UI: projects, library, generation, convert, batch, studio viewer, exports, validation | works against test doubles; not audited screen by screen | Playwright tests |

## 3. Real AI inference: what has actually happened

| Engine | Evidence | Grade |
|---|---|---|
| TripoSR | Colab T4: a four-image run (truck, chair, teapot, robot) whose evidence reader reports PASS with visual quality still `PENDING_HUMAN_REVIEW`, and earlier single-image truck and SUV runs recorded as PARTIAL. On vehicles the silhouettes match (IoU 0.91 to 0.94) but all three proportion checks fail (stubby proportions, ground disc) | R |
| TripoSG | One job finished on a Colab T4 on 2026-10-29: the worker log shows `final grids shape = torch.Size([505, 505, 505])` and a served result; the diagnose output lists a 7,197,064-byte GLB. The mesh itself was never inspected by the engineering agent. The bake-off that consumed it was killed by an out-of-memory error (fixed) | O |
| TRELLIS.2 | plug-in written from upstream documentation, **never run** (needs a 24 GB-class GPU per secondary sources) | R |
| Hunyuan3D-2 mini | plug-in written, **never run**; restricted licence, evaluation only | R |

**No stronger-engine output has been inspected by a human or by the quality metrics.** The README status table states this correctly.

## 4. What is mocked, procedural or a test double

* `aro_worker/engines/fake.py`: procedural car-like mesh, labelled "TEST DOUBLE (procedural, NOT AI)" in its manifest and every result. Used by worker, Studio and browser tests. Not registered unless `--engines fake` is given.
* `aro_studio/vehicles/titan480.py` (764 lines): a **procedural** reference vehicle, not AI output; labelled as such in the acceptance reports.
* Texture colour for geometry-only engines comes from projecting the reference photo (conventional computer graphics, not AI); the unseen side is mirrored and marked as inferred.
* Everything marked "AI" in the matrix is either unrun or run only in the cases listed in section 3.

## 5. Gaps against the directive (not present at all)

Verified by grep (0 matches) or by reading the code:

* No user accounts: the only access control is one optional shared bearer token (`aro_studio/config.py`). No `user_id` or `owner_id` anywhere in the data layer.
* No Supabase, Cloudflare R2, Redis, Stripe/payments, Next.js/React, RunPod, Google Cloud or JWT code. (Two "r2" and "stripe" substring hits are inside the vendored three.js bundle.)
* No text-to-3D, multi-image input, AI texturing or retexturing, quad remeshing, skeletal rigging or animation (the only rig is a mechanical node hierarchy for vehicle wheels and doors), STL/3MF/USDZ export, thumbnails stored with assets, credit ledger, usage history, public API keys.
* Viewer: orbit and perspective camera, lights, wireframe, LOD switch. Missing: orthographic view, selection, transform gizmos, hierarchy panel, environment/matcap, undo/redo, side-by-side compare.

## 6. Security review

Implemented and tested (see `SECURITY.md`): content-based upload validation with size and pixel limits, filename sanitising, path-traversal and symlink guards, safe archive extraction, no unpickling, CSP and related headers, log redaction, an audit log, rate limiting, job timeouts. `pip-audit` and `bandit` run in CI.

Findings:

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| R-01 | High | The server binds `0.0.0.0` by default and authentication is **off unless a token is configured**. It must never be exposed to the internet in this form. | `app.py:12`, `aro_studio/config.py:17` |
| R-02 | High | No per-user identity or ownership, so row-level security, per-user quotas, credits and "records belong to the correct user" cannot be added without changing every service. | no `user_id`/`owner_id` in `aro_studio/db` |
| R-03 | High | SQLite, local files and in-process threads limit the system to one node. Fine for a local tool, wrong for a hosted product. | `aro_studio/db/database.py`, `aro_studio/jobs/queue.py` |
| R-04 | Medium | Rate limiting is in-process and keyed by address or token, not by user, and not shared across processes. | `aro_studio/security/ratelimit.py` |
| R-05 | Medium | No container image scan and no secret-scanning job in CI. | `.github/workflows/ci.yml` |
| R-06 | Medium | GPL-licensed components are in use: Blender's `bpy` (GPL-3.0, FBX/USD export) and `pymeshlab` (GPL-3.0 per PyPI metadata) in the worker environment. A hosted service is not distribution, but shipping container images is; needs a licence review before any image is published. | `aro_studio/export/blender.py`, `scripts/lab_bootstrap.py` |
| R-07 | Low | The repository is public and no project licence has been chosen (owner's decision, recorded in `docs/repository-safety.md`). Do not commit balances, keys or account identifiers. | README |

## 7. Technical debt and quality history

Defects found and fixed in the last weeks, recorded because each one escaped earlier tests:

1. **Mirrored textures.** The GLB writer kept texture V pointing up while glTF counts from the top, so every textured GLB and Unity package made before commit `23ca783` showed its texture mirrored vertically in Blender, Unity and three.js. Found only by re-importing in Blender. Fixed; regression tests decode the written GLB.
2. **Colour bake misaligned** with the cleaned mesh frame, and hole filling dropped colours. Fixed.
3. **Out-of-memory in scoring.** Counting loose fragments with `trimesh.split()` copied the texture per fragment (about 16 MB each); a mesh with a few hundred fragments exhausted a 12.7 GB Colab VM. Fixed; a fresh-process memory test guards it.
4. **Cleanup failed for non-root users** because saved version folders are read-only; the working folder was silently left behind. Fixed; found by CI.
5. Earlier: stale status claims and an FastAPI behaviour change that silently disabled caching (fixed).

Remaining debt: the UI has no component structure; large modules such as `validation/engine.py` (537 statements) and `processing/service.py` are dense; `aro_studio/ui` is excluded from bandit.

## 8. Reuse, replace, retire

| Component | Decision | Reason |
|---|---|---|
| `aro_studio/geometry`, `textures`, `texturing`, `lod`, `collision`, `validation`, `export`, `quality`, `scene`, `materials` | **Reuse** as the processing core (a library called by workers) | tested, verified on real meshes, no equivalent elsewhere |
| `aro_worker` protocol, engine plug-ins, licence gate | **Reuse**, adapt to RunPod's handler model | already isolates engines behind one contract |
| `aro_studio/engines/remote.py` provider contract | **Reuse** the idea as the provider abstraction | model-agnostic by design |
| SQLite database, local storage layout, in-process job queue | **Replace** with Postgres, R2 and a database-backed queue | single-node, no ownership |
| Vanilla-JS UI | **Replace** progressively with Next.js + React Three Fiber (keep it running until parity) | cannot grow into the required workspace |
| Single shared token | **Replace** with Supabase Auth + server-side authorization | R-01, R-02 |
| `vehicles/titan480.py` and acceptance scripts | **Keep** as a test fixture and regression reference; not product | procedural, not AI |

The directive asks us not to build duplicate systems and not to overwrite working code without justification. The decision above keeps all working processing code and replaces only the layers that cannot satisfy multi-user hosting.
