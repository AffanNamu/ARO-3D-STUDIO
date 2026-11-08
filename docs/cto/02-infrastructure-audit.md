# 02 · Infrastructure audit (Phase 0, task 2)

Audit date: 2026-11-08 · Status: **RunPod PARTIAL** (one owner-provided console screenshot); **Google Cloud, Supabase and Cloudflare R2 BLOCKED** (no access from the engineering sandbox). This document records what was verified, what was not and why, and gives the owner a short, read-only way to close the gap **without sharing any secret**.

The repository is public. Do not add balances, account identifiers, keys or invoice data to it. This file therefore contains no amounts.

## 1. What could be verified

| Item | Result | How (grade) |
|---|---|---|
| Code that talks to Google Cloud, RunPod, Supabase, Cloudflare R2, Redis | **none exists** | grep over `aro_studio`, `aro_worker`, `scripts`, `tests` found no import, URL or client for any of them (R) |
| Deployment files | `Dockerfile` (CPU Studio image, built and started in CI), `worker/Dockerfile` and `worker/install_engines.sh` (GPU worker, **never built or run**), no compose file, no Terraform, no cloud config | `ls`, CI workflow (R) |
| Studio container | CI builds the CPU image and starts it on every push; green at commit `313a864` | CI run 75 (R) |
| GPU worker | speaks a documented protocol (`docs/architecture/gpu-worker.md`); runs on Colab through a notebook; has **no RunPod handler** | repository (R) |

## 2. What could not be verified, and why

| Provider | Blocker or state | Evidence |
|---|---|---|
| Google Cloud | `gcloud` 570.0.0 is installed in the sandbox but has **no credentialed account**; only `cloud.google.com` documentation is reachable | `gcloud auth list` printed "No credentialed accounts" (R) |
| RunPod | **Account confirmed by an owner-provided screenshot of the console Home page (2026-11-08, grade O):** it shows a prepaid balance matching what the owner reported (amount withheld here), **no Pods listed** (empty "Deploy Pod" panel), and a banner saying **multi-factor authentication is not enabled**. Not yet seen: Serverless endpoints, Storage volumes, Billing page, API keys, auto-pay setting. The sandbox cannot call RunPod's API (`api.runpod.io` returned 403; only the public site and docs were later allowed) | screenshot (O); `curl` (R) |
| Supabase | `api.supabase.com` returns 403 | same (R) |
| Cloudflare R2 | `api.cloudflare.com` returns 403 | same (R) |
| Meshy and Hugging Face | also 403; only search summaries were available | same (R) |

**Network:** the first request to widen the sandbox's network could not be shown on the owner's phone app. After the owner opened a computer session the same request was approved (2026-11-08): the public sites and documentation of Meshy and RunPod and Hugging Face became readable, which is how the Meshy audit, the RunPod prices and the model licences were completed. No provider **account** access was granted by that change.

The sandbox also exposes `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and `AWS_CA_BUNDLE` environment variables. They were **not** identified as belonging to ARO, were not used, and their values were never printed.

## 3. The directive's statements, classified

| Statement (owner-reported, O) | Status |
|---|---|
| A funded RunPod account exists | **unverified** |
| No production RunPod endpoint is confirmed | consistent with the repository (no handler exists) |
| A Google Cloud project named "ARO 3D AI STUDIO" and a paid billing account exist; a small payment was confirmed on 31 October; the console shows no cost for the current month | **unverified**; how the payment is classified (prepayment, credit, verification charge) is unknown |
| No Compute Engine VM is confirmed | consistent with the repository |
| Supabase is the preferred database and auth | **no project, schema or integration is verified** |
| Cloudflare R2 is the preferred storage | **no bucket or integration is verified** |
| No external VPS was purchased | consistent with the repository |

Conclusion, matching rule 16 of the directive: **purchased resources are not shown to be deployed resources.** Nothing in the codebase would use them today.

## 4. Owner-run, read-only checklist (no secrets leave your account)

Do these in your own browser or Cloud Shell and send back screenshots or pasted output. **Never paste a key, token or password.** Blur account numbers if you prefer.

### Google Cloud (Cloud Shell, read-only)

```bash
gcloud config list
gcloud projects list --format="table(projectId,name,lifecycleState)"
gcloud billing accounts list
gcloud billing projects describe PROJECT_ID
gcloud compute instances list
gcloud run services list
gcloud run jobs list
gcloud storage buckets list --project=PROJECT_ID
gcloud billing budgets list --billing-account=BILLING_ACCOUNT_ID
```

If a command offers to enable an API, answer **no**; "API not enabled" is itself a useful answer. In the console also screenshot **Billing > Payment activity** (what the 31 October payment line is), **Billing > Credits** and **Billing > Budgets & alerts**.

### RunPod (console screenshots)

Billing (balance, auto-pay, spend limit), Serverless (every endpoint with min/max workers and idle timeout), Pods (anything running), Storage (network volumes), Settings > API Keys (names and permission scope only, never the key).

### Supabase (dashboard)

Project Settings > General (project reference, region, plan). In the SQL editor, read-only:

```sql
select schemaname, tablename, rowsecurity from pg_tables where schemaname = 'public' order by 1, 2;
select count(*) as users from auth.users;
```

### Cloudflare R2 (dashboard)

R2 > Overview (bucket names, stored size, operation counts) and R2 > Manage API tokens (names and permissions only). Note whether any bucket has public access enabled.

## 5. Cost protection to put in place before any paid experiment (owner actions plus code rules)

Owner actions:

1. Google Cloud: create a budget with alerts at low thresholds (for example 20, 50, 90 and 100 percent of the amount you are willing to lose). Budgets alert, they do not stop spending, so also keep no resource running that you do not need.
2. RunPod: turn **auto-pay off**, keep a small balance, set a spend limit if the console offers one, and keep Serverless **max workers = 1** until a benchmark justifies more.
3. Supabase and R2: use the free tiers until real usage requires more; enable the Supabase spend cap if you move to a paid plan (on by default on Pro per secondary sources).

Code rules (enforced in the design in `04-architecture.md`): per-job deadline, maximum duration, maximum workers, per-user concurrency, cost recorded per job, no automatic retry of a timed-out GPU job before the provider's state is checked, no endpoint created or left running without an owner-approved reason.

## 6. Findings

| ID | Finding |
|---|---|
| INF-01 | No provider can currently be shown to be in use. All four need owner-run verification (section 4) before Phase 3. |
| INF-02 | The GPU worker has no RunPod entry point; a RunPod handler plus a CPU-processing worker are new work (Phase 4). |
| INF-03 | **Resolved 2026-11-08:** research hosts are now allowed in a dedicated environment; account-level access (billing, endpoints, keys) is still not granted and should stay read-only if it is. |
| INF-05 | The RunPod account holds prepaid money **without multi-factor authentication**. Enable MFA before any key is created or any endpoint is deployed. |
| INF-06 | RunPod's default account spend limit is $80 per hour (RunPod docs, G), which is far above any budget here; set the per-endpoint worker maximum to 1 and keep auto-pay off. |
| INF-04 | Hosting for ordinary backend traffic can plausibly cost nothing to a few dollars a month (see the cost model); the owner's low monthly hosting budget is workable only if heavy CPU work is kept off that machine. |
