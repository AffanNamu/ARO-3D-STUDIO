# Owner setup: exact configuration and the steps only you can do

Written 2026-11-08. Nothing in this file has been run for you: no account was touched and no resource created. Steps that **spend money or
change a paid account** are marked **COST**. The agent that wrote this has no access to your Supabase, Cloudflare, RunPod or Google Cloud
accounts and never sees their secrets; you paste secrets only into your own host's secret store, never into chat, issues or commits.
Dashboard wording changes over time: where a step names a button, treat the name as a hint and follow the vendor's current page.

## 0. Order of work (about 2 hours the first time)

| # | Step | Cost | Proves |
|---|---|---|---|
| 1 | Turn on MFA for RunPod, Cloudflare, Supabase, GitHub, Google; set a RunPod spending limit; create a Google Cloud budget alert | none | you cannot be surprised by a bill |
| 2 | Supabase project, apply the migration | free tier | accounts, jobs, credits exist |
| 3 | R2 bucket, token, CORS | free tier (10 GB) | files can be stored and shown |
| 4 | RunPod endpoint from this repository | **COST** (the image build; then pennies per generation) | a worker image builds |
| 5 | `python -m aro_cloud.smoke` | **COST** (a few cents of GPU) | **a real model produced a validated GLB** (the milestone nobody can fake) |
| 6 | Read the model licences, record your verification, enable the model | none | the legal gate is yours |
| 7 | Run the API and the web app on your computer against 2 to 4 | none | sign in, generate, view |
| 8 | Deploy the API (Cloud Run) and the web app | **COST** (small) | other people can use it |

Do 1 to 7 before 8. Step 5 is the one that matters most: send the printed evidence JSON back (it contains no secrets or URLs).

## 0a. Your computer and the private env file (do this once)

Every command below runs on **your** computer, so your secrets never leave it. You need Python 3.10 or newer and git.

```
git clone https://github.com/AffanNamu/ARO-3D-STUDIO.git
cd ARO-3D-STUDIO
git checkout claude/zen-johnson-je3dzk
python -m venv .venv
source .venv/bin/activate            # Windows PowerShell:  .venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-cloud.txt
```

Create ONE private file **outside the repository**, for example `~/aro-secrets/aro.env` (Windows: `C:\Users\<you>\aro-secrets\aro.env`), one `NAME=value` per line (see `.env.example` for the names).
Every command takes `--env-file <that file>`, so you never type a secret into a terminal, a chat or a commit. On macOS/Linux run `chmod 600` on it.
Check each step with `python -m aro_cloud.doctor --env-file <file> supabase|r2|runpod` (read-only apart from tiny test objects in R2; it prints no secrets and submits no GPU job).

## 1. Safety rails first

* RunPod: Settings -> enable two-factor authentication; Billing -> keep auto-pay **off** and set a spending limit you are comfortable with.
* Google Cloud project `aro-3d-ai-studio` has no budget (owner-verified 2026-11-08, `docs/cto/02-infrastructure-audit.md` INF-07): Billing -> Budgets & alerts -> create a monthly budget with alerts at 50 %, 90 % and 100 %. A budget alert does not stop spending; it tells you.
* Never put a service-role key, database URL, R2 key or RunPod key in the web app, in a notebook, or in a commit. The repository's tests refuse committed `.env` files.

## 2. Supabase (database and sign-in)

1. Create a project (a **dev** project first). Note the **Project URL** (`https://<ref>.supabase.co`) and the **anon / publishable key** (public by design; used by the web app).
2. Get the database connection string from the project's **Connect** dialog. Cloud Run and most hosts are IPv4-only: use the **pooler** string (session mode, port 5432, is the simplest; `ARO_DATABASE_SSL=auto` verifies TLS for any non-localhost host). Treat the password as a secret.
3. Apply the schema from your computer (the same command later applies new migrations; applied migrations are checksummed and refuse to be edited):
   ```
   pip install -r requirements.txt -r requirements-cloud.txt
   python -m aro_cloud.migrate --env-file ~/aro-secrets/aro.env
   python -m aro_cloud.doctor --env-file ~/aro-secrets/aro.env supabase      # must end with RESULT: PASS
   ```
   **Do not** pass `--stub-auth` (that creates a fake `auth` schema for throwaway test databases; the command refuses it when `auth.users` exists).
4. Authentication -> Providers: enable Email. For production, require email confirmation. URL configuration: Site URL = your web app's origin; add it (and `http://localhost:3000` while developing) to the redirect allow-list.
5. Tokens: projects on Supabase's asymmetric signing keys need only `ARO_SUPABASE_URL` (the API reads the public keys from `<url>/auth/v1/.well-known/jwks.json`). A project that still uses the legacy shared secret also needs `ARO_SUPABASE_JWT_SECRET`. The API accepts only tokens with audience `authenticated`, role `authenticated` and a user id that is a UUID; `anon` and service tokens are refused.
6. Row Level Security is enabled on every table by the migration. Verify after applying: Table editor shows RLS enabled on all tables; `audit_log` has no policy (clients cannot read it).

## 3. Cloudflare R2 (generated files)

1. R2 -> create a bucket (private: no public access, no custom domain, no `r2.dev` URL). Note the **Account ID** and the bucket name.
2. R2 -> Manage API tokens -> create a token with **Object Read & Write**, restricted to this bucket. Note the **Access Key ID** and **Secret Access Key** (shown once). These go only to the API.
3. CORS on the bucket (the browser downloads GLBs and thumbnails straight from R2 using signed URLs): allowed origin = your web origin(s), method `GET`, allowed headers `*`, max age 3600. Writes never come from a browser, so no `PUT` is needed.
4. Optional lifecycle rule: expire `users/*/uploads/` objects after a retention period you choose.
5. R2 pre-signed URLs are generated by the API with the S3 API (`https://<account>.r2.cloudflarestorage.com`, region `auto`). Your RunPod worker uses only URLs the API signed for it.

## 4. RunPod endpoint (the GPU)

1. Confirm the GitHub connection you made covers this repository. Serverless -> **New Endpoint** -> **Import Git Repository** -> branch `claude/zen-johnson-je3dzk` (or `main` once merged) -> **Dockerfile path** `worker/runpod/Dockerfile`. RunPod builds the image; later changes deploy when you publish a GitHub release.
2. GPU: a 24 GB-class GPU is enough for TripoSG (about 8 GB VRAM documented). Rates on 2026-11-08 are in `docs/cto/02-infrastructure-audit.md`.
3. Scaling (keeps the bill small while testing): **min workers 0**, **max workers 1**, short idle timeout. Execution timeout 900 s. Container disk at least 25 GB (image plus weights).
4. Environment variables on the endpoint (non-secret):

   | Variable | Value | Why |
   |---|---|---|
   | `ARO_VERIFIED_MODEL_LICENSES` | `triposg` | **your** attestation that you read the weights licence. Leave unset until step 6 |
   | `ARO_WORKER_ALLOWED_HOSTS` | `<account-id>.r2.cloudflarestorage.com` | the only host the worker will fetch from or write to |
   | `ARO_WORKER_ENGINES` | `triposg` | engines this worker serves (default) |
   | `ARO_WORKER_JOB_TIMEOUT_S` | `840` (default) | keep below the execution timeout |

   Do **not** set `ARO_WORKER_EVALUATION_MODE`, `ARO_WORKER_ALLOW_TEST_DOUBLE` or `ARO_WORKER_ALLOW_INSECURE_URLS` on a production endpoint.
5. Create an API key for the API (RunPod Settings -> API Keys; use the narrowest scope offered). Note the **endpoint ID**.
6. First build: send the build log back if it fails (the Dockerfile has never been built; expect one round of fixes).

## 5. Prove it: one real generation

```
python -m aro_cloud.smoke --env-file ~/aro-secrets/aro.env --image my_concept.png --preset DRAFT --keep --out evidence.json
```
It uploads the image to R2, runs your endpoint, downloads the GLB, runs the same output gate as the API and prints evidence. `status: PASS`
and `ai_inference: true` appear only if the worker reports a real (non-test-double) engine and the GLB passed the gate. The first run includes
a cold start (image pull, weights load): expect minutes, not seconds. `--keep` leaves the objects in R2 and saves the GLB next to you so you can look at it.

## 6. Licences: your decision, recorded in the database

The platform will not run a model until a person records that they read its licence. Read, at least: the TripoSG model card
(`https://huggingface.co/VAST-AI/TripoSG`, metadata says MIT, not gated) and its repository licence; the U²-Net licence used for background removal; and
`docs/platform/runpod-worker.md` (the LGPL and bundled-library notes). If you agree:
```
python -m aro_cloud.admin verify-model --model triposg --verified-by "Your Name" --weights-licence "MIT" --attest-licence-read
python -m aro_cloud.admin enable-model --model triposg
```
and set `ARO_VERIFIED_MODEL_LICENSES=triposg` on the RunPod endpoint. TRELLIS.2 and Hunyuan3D are registered `evaluation_only`; the CLI refuses to verify them and the database refuses to enable them.

## 7. Run the API and the web app locally

```
# API (reads the ARO_* variables below from your shell)
python -m aro_cloud                      # http://localhost:8080  (docs at /docs while ARO_ENV is not production)
# give yourself credits: sign in once on the web app, copy your user id from /v1/me, then
python -m aro_cloud.admin grant-credits --user <uuid> --amount 100 --note "owner test"
# web app
cd apps/web && cp .env.example .env.local   # fill the three NEXT_PUBLIC_ values
npm ci && npm run dev                    # http://localhost:3000
```

## 8. Deploy (needs your explicit go-ahead; each command is yours to run)

API on Cloud Run (project `aro-3d-ai-studio`, budget alert first). **COST: small; Cloud Run, Artifact Registry and Secret Manager charges apply.**
```
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com cloudbuild.googleapis.com cloudscheduler.googleapis.com
gcloud artifacts repositories create aro --repository-format=docker --location=REGION
gcloud builds submit --tag REGION-docker.pkg.dev/aro-3d-ai-studio/aro/api:TAG -f deploy/api/Dockerfile .   # or build elsewhere
# store each SECRET from the table below in Secret Manager, then:
gcloud run deploy aro-api --image REGION-docker.pkg.dev/aro-3d-ai-studio/aro/api:TAG --region REGION \
  --min-instances 0 --max-instances 3 --concurrency 20 --timeout 300 --allow-unauthenticated \
  --set-env-vars ARO_ENV=production,ARO_SUPABASE_URL=...,ARO_R2_ACCOUNT_ID=...,ARO_R2_BUCKET=...,ARO_RUNPOD_ENDPOINT_ID=...,ARO_ALLOWED_ORIGINS=https://YOUR-WEB-ORIGIN \
  --set-secrets ARO_DATABASE_URL=...,ARO_R2_ACCESS_KEY_ID=...,ARO_R2_SECRET_ACCESS_KEY=...,ARO_RUNPOD_API_KEY=...,ARO_INTERNAL_TOKEN=...
gcloud scheduler jobs create http aro-reconcile --location REGION --schedule "* * * * *" \
  --uri https://YOUR-API-URL/internal/reconcile --http-method POST --headers "X-Internal-Token=VALUE"   # use a secret-backed method in production
```
`--allow-unauthenticated` is intended: the API itself verifies a Supabase token on every `/v1` route. Cloud Run throttles background CPU between requests, so job
progress is driven by the web app's polling plus the one-minute scheduler call (`ARO_RUN_RECONCILER_THREAD` is for always-on hosts only). In production the process
refuses to start unless every required variable is set, `ARO_INTERNAL_TOKEN` has 24 or more characters, origins are set, and `ARO_ALLOW_TEST_DOUBLE` is off.

Web app: any Node host (Vercel, Cloudflare Pages with Node support, a container). Set the three `NEXT_PUBLIC_*` values **at build time** (the CSP in `next.config.mjs` is built from them), and put the web origin into `ARO_ALLOWED_ORIGINS` and into Supabase's redirect allow-list.

## 9. Environment variables

### API (`python -m aro_cloud`, also `admin`, `migrate`, `smoke`)

Variables marked **S** are secrets: keep them in the host's secret store. Empty values count as unset.

| Variable | Default | Notes |
|---|---|---|
| `ARO_ENV` | `development` | `production` enables the start-up checks and hides `/docs` |
| `ARO_DATABASE_URL` **S** | none | `postgresql://user:password@host:5432/db`; required in production |
| `ARO_DATABASE_SSL` / `ARO_DATABASE_CA_FILE` | `auto` | `auto` = verify TLS except on localhost; `verify`, `require` (encrypted, unauthenticated), `disable` |
| `ARO_SUPABASE_URL` | none | required in production; issuer and JWKS URL derive from it |
| `ARO_SUPABASE_JWKS_URL` | derived | override only if needed |
| `ARO_SUPABASE_JWT_SECRET` **S** | none | legacy HS256 projects only |
| `ARO_JWT_AUDIENCE` | `authenticated` | |
| `ARO_R2_ACCOUNT_ID` / `ARO_R2_ENDPOINT_URL` | none | account id, or a full endpoint URL |
| `ARO_R2_BUCKET`, `ARO_R2_REGION` | none, `auto` | |
| `ARO_R2_ACCESS_KEY_ID` **S**, `ARO_R2_SECRET_ACCESS_KEY` **S** | none | |
| `ARO_SIGNED_URL_TTL_S` | 600 | lifetime of download links (30 to 3600) |
| `ARO_RUNPOD_API_KEY` **S**, `ARO_RUNPOD_ENDPOINT_ID` | none | |
| `ARO_RUNPOD_BASE_URL` | `https://api.runpod.ai/v2` | |
| `ARO_EXECUTION_TIMEOUT_S` | 900 | RunPod `executionTimeout` per run |
| `ARO_JOB_DEADLINE_S` | 1500 | whole life of a job; keep under RunPod's 30-minute result retention |
| `ARO_DISPATCH_GRACE_S` | 120 | a send RunPod never confirmed is declared uncertain after this (never re-sent) |
| `ARO_MAX_ATTEMPTS` / `ARO_RETRY_BACKOFF_S` | 2 / 15 | sends per job when RunPod refused with nothing started, or the worker flagged an error retryable |
| `ARO_INGEST_STALE_S` | 120 | another process may take over a stalled result check after this |
| `ARO_GPU_USD_PER_SECOND` | none | your GPU price; when set, each job records a cost estimate |
| `ARO_ALLOWED_ORIGINS` | none | comma-separated web origins; required in production |
| `ARO_INTERNAL_TOKEN` **S** | none | 24+ characters; `X-Internal-Token` for `/internal/reconcile` |
| `ARO_MAX_UPLOAD_MB`, `ARO_MAX_IMAGE_PIXELS`, `ARO_MIN_IMAGE_SIDE` | 10, 40 000 000, 256 | |
| `ARO_MAX_ACTIVE_JOBS_PER_USER`, `ARO_REQUESTS_PER_MINUTE` | 2, 120 | per user, per instance |
| `ARO_PRICE_IMAGE_TO_3D` | 10 | credits per generation (your pricing decision) |
| `ARO_MAX_GLB_MB` | 150 | |
| `ARO_ENABLED_ENGINES` | `triposg` | a request may name only these, and each must also be verified and enabled in the database |
| `ARO_SIGNUP_CREDITS` | 0 | free credits at first sign-in (your decision) |
| `ARO_ALLOW_TEST_DOUBLE` | off | **tests only**; production refuses to start with it on |
| `ARO_RUN_RECONCILER_THREAD` | off | background reconcile loop for always-on hosts |

### RunPod worker (set on the endpoint; none of these is secret)

`ARO_VERIFIED_MODEL_LICENSES`, `ARO_WORKER_ALLOWED_HOSTS`, `ARO_WORKER_ENGINES`, `ARO_WORKER_JOB_TIMEOUT_S` as in step 4. Baked into the image: `TRIPOSG_DIR`, `ARO_TRIPOSG_REVISION`, `ARO_REMBG_MODEL`, `U2NET_HOME`, `HF_HOME`, `ARO_WORKER_CACHE`. The worker needs **no** database, R2 or Supabase credential.

### Web app (build time, public by design)

`NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`.

## 10. What still needs your account access (the short list)

1. Supabase project: create it, give the API its pooler connection string, apply `python -m aro_cloud.migrate`, configure Auth URLs.
2. Cloudflare R2: bucket, scoped token, CORS.
3. RunPod: build the endpoint from `worker/runpod/Dockerfile`, set its environment, create the API key. **First real generation: `python -m aro_cloud.smoke`.**
4. Licences: read, then `admin verify-model` / `enable-model`, and `ARO_VERIFIED_MODEL_LICENSES=triposg` on the endpoint.
5. Google Cloud: budget alert, then (with your approval) Artifact Registry, Cloud Run, Secret Manager, Cloud Scheduler.
6. Decisions: credit price and sign-up credits, how credits are sold (not built), web hosting.
7. MFA and spending limits on every account (section 1).
