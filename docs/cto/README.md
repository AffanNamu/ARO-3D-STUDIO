# ARO 3D AI STUDIO · CTO audit and plan (2026-11-08)

Response to the Master CTO Directive. Phases 0 to 2 are an evidence-graded audit and a proposal; **nothing is deployed or spent.** The backend, GPU worker handler and web app that implement the proposal are in `aro_cloud/`, `aro_worker/runpod_handler.py` and `apps/web/`; what is built, what is tested and what still needs the owner's accounts is in [../platform/README.md](../platform/README.md). Status words: PASS, PARTIAL, BLOCKED, FAIL, NOT STARTED.

| Document | Content | Status |
|---|---|---|
| [01-repository-audit](01-repository-audit.md) | what the code really is, what is real, mocked or missing, security findings, reuse/replace decisions | PASS (complete for the repository) |
| [02-infrastructure-audit](02-infrastructure-audit.md) | Google Cloud, RunPod, Supabase, R2: what could and could not be verified; owner-run read-only checklist; cost controls | RunPod **PARTIAL** (owner screenshot); the other three **BLOCKED** |
| [03-meshy-competitive-audit](03-meshy-competitive-audit.md) | Meshy's API, models, pricing, speed, limits and ecosystem, read from its OpenAPI file and docs | **PASS** for documentation; product experience and quality **NOT STARTED** |
| [competitive-matrix](competitive-matrix.md) / [.json](competitive-matrix.json) | 69 capabilities, 13 required fields each, status, priority; tested tracker | PASS (as a tracker; Meshy column at grade G) |
| [04-architecture](04-architecture.md) · [schema (migration 0001)](../../aro_cloud/migrations/0001_init.sql) | ADRs, system design, job lifecycle, credits, API, storage, security, cost model | PARTIAL (implemented and tested against a real PostgreSQL in CI; not yet applied to the owner's Supabase project) |
| [05-models-and-licensing](05-models-and-licensing.md) | candidate models, licence classes, strategy per task, capped experiments | **PARTIAL** (code and weights licences read from source; two licence texts and several dependency chains unread) |
| [06-roadmap](06-roadmap.md) | phases 3 to 9, milestones, benchmark protocol, risks | PARTIAL (needs owner approvals) |

## Evidence grades

R verified in this repository · G read at the primary source during the audit (Meshy's OpenAPI file and docs, RunPod and Google pricing pages, Hugging Face card metadata, GitHub LICENSE and source files) · S search summary of an unopened page · T third-party only · O owner-reported or owner-provided screenshot. A claim is never presented above its grade.

## The findings that matter

1. **The repository is a strong single-user processing tool, not yet a platform.** About 18,000 lines, 445 tests, CI green. Geometry cleanup, UV and normal baking, LOD, collision, a 50-rule validator and verified exports are real. There are no user accounts, no database other than SQLite, no object storage, no credits, no Supabase, R2, Redis, RunPod or Next.js code. Text-to-3D, AI texturing, retexture, quad remesh, rigging and animation do not exist.
2. **No stronger-engine result has been inspected.** TripoSR has real runs and fails vehicle proportions. TripoSG finished one job on a free T4 (owner's log) but its mesh was never examined. TRELLIS.2 and Hunyuan3D never ran. The competitive claim therefore rests on zero measured comparisons today.
3. **Purchased is not deployed.** None of the four providers can be shown to be in use; the code has no integration for any of them. Verification needs the owner's read-only checklist.
4. **Meshy is a broad and fast-moving product**, now read from its own OpenAPI file and docs: 88 API operations (text, image and multi-image to 3D; retexture; remesh with quad topology; UV unwrap; resize; convert; rigging with an animation library whose action IDs run from 0 to 696; text-to-motion; a five-tool 3D-print suite), plug-ins for Blender, Unity, Unreal, Maya, Godot and 3ds Max, an MCP server, a chat agent and a mobile app, a 3-day asset retention rule, and a credit model in which failed jobs are free. A textured image-to-3D task costs 30 credits: **$0.60 on Pro, $0.375 on Ultra**. Median time is about 2 to 3 minutes. It publishes changes every few days. Using the web app and judging output quality has not been done.
5. **Keep the processing code, replace the shell.** The architecture keeps `aro_studio`'s pipeline as a library, moves identity, data, storage and queues to Supabase, R2 and Cloud Run, and runs only the model on a GPU worker. Google's own pricing page shows Cloud Run's monthly free tier and per-second GPU billing, which may also give a second GPU option.
6. **Licensing steers the model choice, and one earlier claim of mine was wrong.** Hunyuan3D's licence excludes the EU, UK and South Korea. **TRELLIS.2's code and weights are MIT, but its GLB export imports NVIDIA's nvdiffrast (research or evaluation use only for everyone but NVIDIA), its pipeline loads BRIA RMBG-2.0 (non-commercial) and it needs Meta's gated DINOv3.** An earlier note in this repository called nvdiffrast acceptable; that was a misreading and has been corrected in the code and docs, and TRELLIS.2 is now evaluation-only until those parts are replaced. TripoSG's `diso` package is also non-commercial (our stand-in avoids it). Texturing arbitrary meshes still has no licence-clean open candidate.
7. **Honest cost picture:** about $0.01 to $0.13 per successful generation (estimate from RunPod's and Google's published rates; time and cold start unmeasured); about $0 to $25 a month fixed while small.

## Decisions and actions needed from the owner

1. **Approve or amend the architecture** (ADR-1 to ADR-9 in `04-architecture.md`).
2. **Run the infrastructure checklist** in `02-infrastructure-audit.md` section 4 (about 15 minutes, read-only, no secrets).
3. **Set an experiment ceiling** for E1 to E4 (proposed $7 in total, E1 first at $3 on a $0.59 to $1.09 per hour 48 GB Pod) and enable **multi-factor authentication on the RunPod account first**.
4. **Use your Meshy account yourself** for the benchmark inputs and the web-app audit (never share the password, and change the one pasted into the chat).

## What the audit did not do

It did not use the Meshy web app, did not touch any provider account (the RunPod account was seen only in one owner-provided screenshot), did not run any model, spent nothing, and measured no output quality. Supabase and Cloudflare pages were not read (their prices are still search summaries). Every one of those is listed as work to do in the roadmap, not as done.
