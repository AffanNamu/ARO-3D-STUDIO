# ARO 3D AI Studio: the platform (what is built, what is tested, what is not)

Status words: PASS, PARTIAL, BLOCKED, FAIL, NOT STARTED. Written 2026-11-08.

**Bottom line.** The whole path from "user signs in and uploads an image" to "the finished GLB opens in the 3D viewer" is implemented and
tested end to end against a real PostgreSQL and an S3-compatible server, with the GPU model and RunPod replaced by **labelled test doubles**.
**No real AI model has run through it yet**: that needs your RunPod endpoint (one command, `python -m aro_cloud.smoke`, costs a few cents).
Nothing has been deployed, no cloud resource was created, and no account of yours was touched.

| Part | Status | Evidence |
|---|---|---|
| Database schema, Row Level Security, credit ledger | **PASS** (on PostgreSQL 16) | `tests/cloud/test_schema_and_credits.py` (23 tests, including 8 random operation sequences that check the credit invariants; this found and fixed a hole where credits could be reserved after a job had settled) |
| Job orchestration: submit, idempotency, dispatch, reconcile, retries, deadlines, cancel, output verification | **PASS** | `tests/cloud/test_orchestrator.py` (48 tests, real PostgreSQL + S3 API; a mutation check confirmed the "never resend after an ambiguous answer" tests fail when the rule is broken) |
| Supabase token verification | **PASS** (against locally signed tokens) | `tests/cloud/test_auth.py` (19: expired, wrong audience/issuer/role, `alg: none`, algorithm confusion, key rotation). Not yet run against your Supabase project's real keys |
| R2 access through the S3 API | **PASS** against moto; **NOT STARTED** against real R2 | `tests/cloud/test_storage.py` (14). moto does not check SigV4, so signature enforcement is R2's job and is untested here |
| RunPod client | **PASS** against a test double that follows RunPod's documented API | `tests/cloud/test_runpod_provider.py` (26). Not yet run against RunPod |
| RunPod worker handler | **PASS** with a test-double engine; **NOT STARTED** with a real model | `tests/cloud/test_runpod_handler.py` (31), including the real Studio preparation pipeline around the test double |
| Orchestrator -> RunPod client -> handler -> storage -> output gate -> ledger | **PASS** with test doubles | `tests/cloud/test_end_to_end.py` (3), `test_smoke.py` (4) |
| HTTP API | **PASS** | `tests/cloud/test_api.py` (13): auth, per-user isolation, idempotent replay, envelope, size caps, CORS |
| Web app | **PASS** (types, 28 tests, production build) | `apps/web/tests`; never driven in a real browser against a real API yet |
| Worker image (`worker/runpod/Dockerfile`) | **NOT STARTED** (never built; authored without Docker or a GPU) | the first RunPod build is the first evidence |
| API image (`deploy/api/Dockerfile`) | **NOT STARTED** (never built) | its dependency set was installed in a clean virtualenv and every module imported |
| Real inference, real quality, real latency | **NOT STARTED** | needs your RunPod endpoint |
| Payments / buying credits | **NOT STARTED** | no payment provider chosen; credits come from `admin grant-credits` or `ARO_SIGNUP_CREDITS` |

CI (`.github/workflows/ci.yml`): `quality` (ruff, format, mypy, bandit, pip-audit, licence audit), `tests` (Python 3.10/3.11/3.12),
`platform` (PostgreSQL 16 service, Python 3.10/3.12; a missing database is a failure there), `web` (typecheck, tests, npm audit, build),
`e2e`, `blender`.

## How it fits together

```
 browser (apps/web, Supabase sign-in)
    | Bearer <Supabase access token>                         GET glb via short-lived signed URL
    v                                                                          ^
 API (aro_cloud, FastAPI) -----------------------------------------------> Cloudflare R2 (private bucket)
    |  PostgreSQL (Supabase): jobs, assets, credits (source of truth)             ^   ^
    |  RunPod /run  (input = signed URLs only, no storage credentials)            |   | PUT outputs, result.json LAST
    v                                                                             |   |
 RunPod Serverless worker (aro_worker.runpod_handler) -- Studio pipeline in-process: matting -> TripoSG -> orientation/scale ->
 mesh preparation -> UVs/texture projection -> validation -> export
```

* **Postgres is the truth.** Every state change is a compare-and-set that also writes an event row, so a request, the scheduler and a
  second API instance can all advance the same job without double-processing it.
* **Credits.** Reserved in the transaction that creates the job, captured in the transaction that records the finished asset, released in
  the transaction that ends a failed or cancelled job. Only SQL functions the API's database role can call move credits; browsers cannot.
* **No double GPU run.** `dispatch_started_at` is written before RunPod is called. A timeout or 5xx after the request was sent is
  *ambiguous*: the job is never sent again, and the finished output (if any) is found through `result.json` in R2. Only a refusal that
  provably started nothing (HTTP 429, or the provider not reachable) is retried, up to `ARO_MAX_ATTEMPTS`.
* **A provider's answer is not a result.** The API re-downloads the GLB from R2 and checks its SHA-256, that it parses, that it has real
  geometry (minimum triangles, finite coordinates, sane size, non-degenerate triangles) before the job completes. A labelled test double
  is refused unless a test explicitly allows it, and production refuses to start with that switch on.
* **Deadlines use the database clock.** A job past its deadline is read from RunPod first (finished work is kept), then cancelled and
  failed, and the credits go back.
* **Nothing is faked.** If the model fails, the job fails. The web app shows the failure and says the credits were returned.

## Job states

`created -> validating -> queued -> initializing -> generating -> processing -> validating_output -> uploading -> completed`; any active
state can go to `failed`, and `created` through `processing` to `cancelled`. `initializing`, `generating` and `processing` can return to
`queued` for a permitted retry. `validating_output` and `uploading` cannot be cancelled (the model already exists).

## API as built (v1)

| Method and path | Purpose |
|---|---|
| `GET /healthz`, `GET /readyz` | liveness; readiness (database reachable) |
| `GET /v1/me` | creates the account on first call; credits, price, enabled engines, limits |
| `POST /v1/uploads` | the image itself as the body (`Content-Type: image/png|jpeg|webp`); validated by content; same bytes twice = one upload |
| `POST /v1/generations` | `Idempotency-Key` header required; 201 new job, 200 replay of the same key and body, 409 if the key was used for a different body, 402 not enough credits, 429 too many active jobs |
| `GET /v1/generations`, `GET /v1/generations/{id}`, `GET .../{id}/events` | list, status (also advances the job, throttled to one provider call per 2.5 s), history |
| `POST /v1/generations/{id}/cancel` | idempotent; 409 once the model is being saved |
| `GET /v1/assets`, `GET /v1/assets/{id}`, `GET /v1/assets/{id}/versions/{n}/files/{glb|raw_mesh|thumbnail}` | library; the last returns `{url, expires_at, filename}` (a signed URL, valid `ARO_SIGNED_URL_TTL_S` seconds) |
| `GET /v1/credits`, `GET /v1/credits/ledger` | balance and history |
| `POST /internal/reconcile` | `X-Internal-Token`; advances every unfinished job (Cloud Scheduler calls it) |

Errors always look like `{"error": {"code", "message", "recommended_action", "details"}}`.

**Differences from the proposal in `docs/cto/04-architecture.md` section 6**, so nobody is surprised: uploads go through the API rather than a
client-side pre-signed PUT (the API must validate the content before storing it); there are no server-sent events (the app polls); no
`/exports`, `/versions` (refine/retexture/rig) or provider webhook (a webhook body is untrusted, and polling plus the scheduler covers the same
need); `kind` is `image_to_3d` only (text-to-3D and multi-image are refused, not faked).

## Not built (so you know)

Credit purchase and invoicing; text-to-3D, multi-image-to-3D, retexture, remesh, rig, animate; PBR textures from a generative texturing model
(TripoSG produces geometry; the Studio projects colour from the reference image); content moderation; account deletion and data export
endpoints; per-IP and edge rate limiting (the in-process per-user limiter protects one instance only); asset delete/rename/search endpoints;
container image scanning in CI; an admin web UI (admin work is the `python -m aro_cloud.admin` CLI).

## Where things are

`aro_cloud/` the backend · `aro_cloud/migrations/` SQL · `aro_worker/runpod_handler.py`, `aro_worker/headless.py`, `aro_worker/inprocess.py` the worker ·
`worker/runpod/` worker image · `deploy/api/` API image · `apps/web/` the web app · `tests/cloud/` the tests · owner steps: [owner-setup.md](owner-setup.md) ·
worker image and licences: [runpod-worker.md](runpod-worker.md).
