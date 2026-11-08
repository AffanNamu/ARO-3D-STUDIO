# 04 · Technical architecture (Phase 2, proposal)

Status: **proposal for owner approval; nothing here is built or deployed.** Evidence grades as in [`competitive-matrix.md`](competitive-matrix.md). Companion files: [`schema.sql`](schema.sql) (database, syntax-checked only), [`05-models-and-licensing.md`](05-models-and-licensing.md), [`06-roadmap.md`](06-roadmap.md).

## 1. Decisions (ADRs)

| # | Decision | Why | Alternatives rejected |
|---|---|---|---|
| ADR-1 | **Keep the existing processing code as a library** (`aro_studio` geometry, textures, LOD, collision, validation, export, quality) and build the product shell around it | 18k lines tested and verified on real meshes; the directive forbids duplicate systems and unjustified rewrites (`01-repository-audit.md`, section 8) | Rewrite from scratch: months lost, regressions of the defects already fixed |
| ADR-2 | **Split GPU inference from CPU processing.** RunPod runs only the model; a CPU job (Cloud Run Job) runs decimation, UV, bake, LOD, validation, export | Measured in the audit sandbox on a synthetic 398k-face mesh the size of the real TripoSG output (R): preparation takes about 100 to 150 s of CPU and peaks at about 1.2 GB RAM, with Blender adding about 0.4 GB. Paying GPU seconds for CPU work is waste, and a $10 VM cannot also host it | One fat GPU worker doing everything; processing on the API host |
| ADR-3 | **PostgreSQL (Supabase) is the only source of truth** for users, assets, jobs and credits. **Redis is deferred**: Postgres (`FOR UPDATE SKIP LOCKED`, advisory locks) is enough for the first queue and rate limits | Fewer moving parts and no extra paid service; Redis stays a coordination option, never authoritative (directive section 9) | Redis-first queues (lost-state risk, extra cost) |
| ADR-4 | **Cloud Run (service + job) is the default backend host; a Compute Engine VM is the fallback** | Google's own page (G, fetched 2026-11-08): Cloud Run bills per 100 ms with a monthly free tier of 180,000 vCPU-s, 360,000 GiB-s and 2 million requests, so low traffic costs about nothing; jobs bill only while running (1-minute minimum). A VM runs 24/7 and still needs patching | VM + Docker Compose from the start (the directive's preference) remains valid if a persistent process such as Redis or a websocket hub is needed; the code is container-based either way |
| ADR-5 | **Provider abstraction:** every model sits behind one contract (`ModelProvider`); the model registry in the database decides what is enabled | Directive section 7: never bind the platform to one model or host | Hard-wiring TRELLIS or RunPod |
| ADR-6 | **Workers hold no storage credentials.** The API hands them short-lived pre-signed URLs to read inputs and write outputs | Limits blast radius of a compromised worker (directive section 11) | Giving workers R2 keys |
| ADR-7 | **Credits are a reservation ledger** (reserve, capture, release) in Postgres functions; the frontend never computes billing | Directive sections 9 and 11; matches Meshy's "failed generations are not charged" (S) | Counters updated by application code |
| ADR-8 | **Frontend: Next.js + React + TypeScript + React Three Fiber**, built beside the current UI (strangler pattern) until parity | Needed for the workspace in section D of the directive | Extending the vanilla-JS UI |
| ADR-9 | **A second GPU provider is a configuration change, not a rewrite.** Cloud Run now lists NVIDIA L4 and RTX PRO 6000 GPUs billed per second (G); availability and quota for this account are unknown | Cost and capacity hedge; to evaluate after E1 | Betting everything on one GPU marketplace |

## 2. System overview

```
USER (browser)
   |  HTTPS
   v
NEXT.JS APP  --(Supabase Auth session, signed-URL downloads)-->  CLOUDFLARE R2
   |  REST + SSE (job status)                                         ^   ^
   v                                                                  |   | pre-signed PUT/GET
FASTAPI API  (Cloud Run service)  ---- SQL / RLS ---->  SUPABASE POSTGRES (truth: users, assets, jobs, credits)
   |  creates job, reserves credits, signs URLs                       ^
   |                                                                  | state changes, events
   v                                                                  |
JOB ORCHESTRATOR (in the API process + Cloud Run Job "reconciler") ---+
   |  submit / poll / cancel                           |  start
   v                                                   v
RUNPOD SERVERLESS (GPU worker, versioned image)   CLOUD RUN JOB (CPU processing worker = aro_studio pipeline)
   |  model inference -> raw GLB + textures -> R2          |  decimate, UV, bake, LOD, collision, validate, export -> R2
   +---------------------------------------------------->  register asset version + files in Postgres
                                                           |
                                                           v
                                              3D VIEWER (R3F) loads GLB via signed URL
```

The directive's chain is preserved; the only addition is the CPU processing stage between inference and storage registration.

## 3. Responsibilities

| Component | Does | Must never |
|---|---|---|
| Next.js app | UI, viewer, uploads via signed URLs, shows credits and history | hold provider keys; compute billing |
| FastAPI API | authenticate (verify Supabase JWT), authorise, validate, create jobs, reserve credits, sign URLs, expose status | run models; trust client prices |
| Orchestrator | move jobs through states, call providers, reconcile, settle credits | retry an expensive call before reading provider state |
| RunPod worker | load a model, run one job, upload outputs with the given URLs, report stats | have bucket credentials, execute user-supplied code, reach the database |
| CPU processing job | run the existing pipeline, validate output, register files and metadata | mark success without output validation |
| Postgres | authoritative records, RLS, ledger functions | be bypassed by the frontend for writes to money or jobs |
| R2 | store objects | be public; serve without signed URLs |

## 4. Job lifecycle

States (directive section 9): `created, validating, queued, initializing, generating, processing, validating_output, uploading, completed, failed, cancelled`.

| From | To | Trigger | Side effect |
|---|---|---|---|
| (none) | created | `POST /v1/generations` with an `Idempotency-Key` | row inserted (unique on owner + key); same key and same request body returns the existing job; same key with a different body is a 409 |
| created | validating | immediately | check input type, size, pixels, prompt rules, per-user concurrency and quota |
| validating | queued | valid | `reserve_credits` (atomic; fails with "insufficient credits") |
| validating | failed | invalid | no credits touched |
| queued | initializing | worker slot available | provider run submitted; `provider_run_id` stored **before** anything else happens |
| initializing | generating | provider reports running | |
| generating | processing | provider reports success and files uploaded | CPU job started |
| processing | validating_output | pipeline finished | |
| validating_output | uploading | geometry checks pass (valid GLB, mesh and triangle counts, bounds, normals, UVs, materials and texture references, file size, orientation) | |
| uploading | completed | files hashed, `asset_versions` and `files` rows written | `capture_credits` |
| any active | failed | error, deadline passed with provider failure, output rejected | `release_credits`; error code recorded |
| any active | cancelled | user cancel | provider cancel requested; `release_credits` |

Rules:

* **Postgres decides.** Every transition writes a `job_events` row in the same transaction as the state change.
* **Idempotency:** the unique `(owner_id, idempotency_key)` index makes duplicate submissions impossible.
* **Timeouts and retries:** a job has a `deadline_at`. When it passes (or a poller loses contact) the orchestrator **reads the provider's state first**. Finished: ingest the result, do not resubmit. Still running: cancel at the provider, then release credits. Failed before any output: retry only if `attempt < max_attempts` (default 1 for GPU jobs). A timeout never triggers a second expensive generation by itself.
* **Reconciliation:** a scheduled job scans active jobs, compares each `provider_run_id` with the provider, and repairs drift. Provider webhooks (if used) only speed this up; polling is the safety net.
* **Output validation** is mandatory. HTTP 200 from a provider is not success; a placeholder or empty mesh is `failed`.

## 5. Credits

`credit_accounts` (cached balance), `credit_ledger` (append-only), `reserve_credits / capture_credits / release_credits` (SECURITY DEFINER, callable only with the service role). Invariants, each with a property test planned: balance never negative; at most one reserve, one capture and one release per job (unique partial indexes); a job is either captured or released, never both; ledger sum equals the cached balance. Prices per action come from a server-side table, never from the client. How credits are purchased is an owner decision (payment provider not chosen; none is assumed).

## 6. API contract (v1, REST/JSON, bearer = Supabase access token)

| Method and path | Purpose | Notes |
|---|---|---|
| `POST /v1/uploads` | request a pre-signed PUT for an image | body: content type, bytes, sha256; limits enforced server-side; response: `upload_id`, `url`, `expires_at` |
| `POST /v1/generations` | create a job | header `Idempotency-Key` required; body `{kind, model_id?, prompt?, image_upload_ids[], settings{target_polycount, topology, pbr, texture_resolution, pose, seed}, formats[]}`; 202 with job |
| `GET /v1/generations/{id}` | status | `{state, progress, credits_reserved, events[], result_version_id?, error?}` |
| `GET /v1/generations/{id}/events` | server-sent events | state changes |
| `POST /v1/generations/{id}/cancel` | cancel | idempotent |
| `GET /v1/assets`, `GET /v1/assets/{id}` | library, filters, search | owner-scoped |
| `POST /v1/assets/{id}/versions` | refine (`remesh`, `retexture`, `rig`) | creates a job of that kind |
| `GET /v1/assets/{id}/versions/{n}/files/{role}` | 302 to a short-lived signed GET | TTL 5 to 15 minutes |
| `POST /v1/assets/{id}/exports` | request formats | validated before the link is issued |
| `GET /v1/credits`, `GET /v1/credits/ledger` | balance and history | read-only |
| `POST /internal/webhooks/runpod` | provider callback | authenticated with a secret path/header; body is untrusted, the handler re-reads state from the provider |

Errors use one envelope `{error:{code,message,recommended_action}}` (already the Studio's convention). A public API with developer keys comes later (matrix H4).

## 7. Provider contract and worker I/O

```python
class ModelProvider(Protocol):
    def capabilities(self) -> list[Capability]: ...
    def estimate_cost(self, request) -> CostEstimate: ...
    def submit(self, job) -> ProviderRun: ...  # stores provider_run_id first
    def status(self, run) -> ProviderStatus: ...  # queued | running | succeeded | failed | cancelled, with timings
    def cancel(self, run) -> None: ...
```

RunPod worker input (all references are pre-signed URLs; no bytes, no keys): `{job_id, kind, model_id, model_version, inputs:{image_url}, settings, outputs:{raw_glb_put_url, textures_put_url_prefix}, limits:{max_seconds}}`. Output: `{ok, files:[{role, sha256, bytes}], stats:{gpu_seconds, peak_vram_mb, model_version}, error?}`. The existing `aro_worker` already uses a cut-out-only rule (no non-commercial matting model runs) and a licence gate; both carry over.

Images are versioned (`aro-worker-trellis2:<git-sha>`); the model registry stores the exact image tag per model version.

## 8. Storage (R2)

* One private bucket; keys `users/<owner_id>/assets/<asset_id>/v<n>/<role>/<sha256>.<ext>` so a key reveals nothing guessable and identical content deduplicates.
* Access only through pre-signed URLs issued by the API after an ownership check; uploads use a content-length range and content type; the API verifies the hash after upload and re-validates the file type by content (the Studio already does this).
* Pricing (S, cited from Cloudflare's page): standard storage $0.015 per GB-month, first 10 GB-month, 1 million write-class and 10 million read-class operations free each month, **no egress charge**. Egress-free storage is why R2 fits large GLB downloads.
* Lifecycle: temporary inputs expire after a short window; soft-deleted assets purge after the retention policy.

## 9. Security architecture (directive section 11)

| Requirement | Design | Verified by |
|---|---|---|
| Secure authentication | Supabase Auth; API verifies the JWT signature and expiry on every request | auth tests |
| Server-side authorisation | `owner_id` checked in every query and by RLS | cross-user access tests (must return 404/403) |
| Row Level Security | policies in `schema.sql`; money and job tables are read-only for clients | RLS tests against a real Postgres in CI |
| Secrets | environment or secret manager only; provider keys never reach the browser or the repository | secret-scan job (to add) |
| Signed URLs | TTL minutes; scope one object | expiry test |
| Input validation, file limits | content sniffing, size, pixel and prompt limits (existing code reused) | existing tests |
| Rate limiting, per-user concurrency | Postgres counters first, Redis when needed | load test |
| Worker isolation | no DB or bucket credentials, no inbound access, input only through signed URLs, no user code execution | design review |
| Secure temporary files | per-job temp directory, removed in `finally` (including for unprivileged users, see the cleanup defect) | existing tests |
| Audit logging | `audit_log` for sensitive actions | tests |
| Dependency and container scanning | pip-audit and bandit exist; add npm audit, a container scanner and secret scanning | CI |
| Path traversal, unauthorised asset access | keys derived from validated ids; no user-supplied path reaches storage | existing and new tests |

## 10. Cost model

All numbers are estimates with their basis stated. They are placeholders until experiment E1 measures real time and cost.

**Fixed monthly (early stage)**

| Item | Estimate | Basis |
|---|---|---|
| Cloud Run API service and CPU jobs at low volume | about $0 | free tier: 180,000 vCPU-s, 360,000 GiB-s, 2 million requests; jobs 240,000 vCPU-s and 450,000 GiB-s (G) |
| Supabase | $0 on the free plan while building; $25 per month Pro before real users | S (search summary citing Supabase's pricing page; not opened) |
| R2 | $0 up to 10 GB-month; then $0.015 per GB-month; egress $0 | S |
| Redis | $0 (deferred) | ADR-3 |
| RunPod | $0 idle (scale to zero); network volume or cached-model storage cost not yet researched | S for scale-to-zero |

**Per successful 3D generation**

| Part | Estimate | Basis |
|---|---|---|
| GPU inference, warm | $0.004 to $0.08 | 10 to 60 s (assumption; a secondary source reports about 3 s at 512 resolution and 17 s at 1024 on an H100, T) times $0.00044 to $0.0013 per second (RunPod flex 4090 and A100 80 GB quotes, S, undated) |
| GPU cold start (model load) | $0.01 to $0.23 | 30 to 180 s (assumption, unmeasured) at the same rates |
| CPU processing | about $0.007 | 2 vCPU, 4 GiB, 150 s at $0.000018 per vCPU-s and $0.000002 per GiB-s (G prices, measured memory and time R) |
| Storage per job | about $0.0003 per month | 20 MB at $0.015 per GB-month |
| **Total** | **about $0.03 to $0.31** | wide on purpose; experiment E1 narrows it |

For comparison, a textured Meshy-6 image-to-3D task is about $0.60 at the Pro-plan credit price (derived from S figures in `03-meshy-competitive-audit.md`).

**Runway** for any prepaid GPU balance: `jobs = balance / cost_per_job`. At $0.03 per job one dollar buys about 33 jobs; at $0.31, about 3. Cold starts dominate, so keep Serverless **max workers 1**, a short idle timeout, and cache models on the worker image or a volume instead of downloading them each time (RunPod's documentation ranks cached models first, then baked images, then network volumes, S).

## 11. Frontend

Next.js (App Router) with TypeScript, Tailwind, TanStack Query for server state, Zustand for editor state, Zod for schemas shared with the API, React Three Fiber and drei for the viewport. The viewer reuses the Studio's conventions (metres, +Y up, LOD names, texture V orientation fixed in `23ca783`). Performance target for the viewer is measured, not assumed: a 1M-triangle GLB must orbit smoothly on a mid-range laptop (matrix D1).

## 12. Repository layout (no move now)

```
aro_studio/            existing: processing core + local UI (kept until the new app reaches parity)
aro_worker/            existing GPU worker; add runpod_handler.py
services/api/          new FastAPI service (auth, jobs, credits, storage)
services/processing/   Cloud Run Job entry point calling aro_studio
apps/web/              new Next.js application
infra/                 Dockerfiles, deploy scripts, budget-alert setup
benchmarks/            dataset manifest and result reports
docs/cto/              this directory
```

## 13. Observability and cost control

Structured logs with `job_id` on every line, `usage_records` per job (gpu seconds, bytes, estimated and actual USD), a daily report of **cost per successful generation and cost of failures**, alerts when daily spend or failure rate crosses thresholds, hard limits: maximum job duration, maximum workers, per-user concurrency, no resource left running without a reason.
