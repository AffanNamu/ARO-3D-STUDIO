# ARO 3D AI STUDIO · CTO audit and plan (2026-11-08)

Response to the Master CTO Directive. Phases 0 to 2 are delivered as an evidence-graded audit and a proposal. **Nothing here is built, deployed or spent.** Status words: PASS, PARTIAL, BLOCKED, FAIL, NOT STARTED.

| Document | Content | Status |
|---|---|---|
| [01-repository-audit](01-repository-audit.md) | what the code really is, what is real, mocked or missing, security findings, reuse/replace decisions | PASS (complete for the repository) |
| [02-infrastructure-audit](02-infrastructure-audit.md) | Google Cloud, RunPod, Supabase, R2: what could and could not be verified; owner-run read-only checklist; cost controls | **BLOCKED** (no access) |
| [03-meshy-competitive-audit](03-meshy-competitive-audit.md) | Meshy capabilities, parameters, versions, pricing, with evidence grades | **PARTIAL** (search summaries only; no page opened) |
| [competitive-matrix](competitive-matrix.md) / [.json](competitive-matrix.json) | 62 capabilities, 13 required fields each, status, priority; tested tracker | PASS (as a tracker; its Meshy column is grade S/T) |
| [04-architecture](04-architecture.md) · [schema.sql](schema.sql) | ADRs, system design, job lifecycle, credits, API, storage, security, cost model | PARTIAL (proposal; schema syntax-checked only) |
| [05-models-and-licensing](05-models-and-licensing.md) | candidate models, licence classes, strategy per task, capped experiments | **PARTIAL** (code licences read; weights licences unverified) |
| [06-roadmap](06-roadmap.md) | phases 3 to 9, milestones, benchmark protocol, risks | PARTIAL (needs owner approvals) |

## Evidence grades

R verified in this repository · G read from a primary source fetched in the audit · S search summary citing an official page that could not be opened · T third-party only · O owner-reported. A claim is never presented above its grade.

## The findings that matter

1. **The repository is a strong single-user processing tool, not yet a platform.** About 18,000 lines, 445 tests, CI green. Geometry cleanup, UV and normal baking, LOD, collision, a 50-rule validator and verified exports are real. There are no user accounts, no database other than SQLite, no object storage, no credits, no Supabase, R2, Redis, RunPod or Next.js code. Text-to-3D, AI texturing, retexture, quad remesh, rigging and animation do not exist.
2. **No stronger-engine result has been inspected.** TripoSR has real runs and fails vehicle proportions. TripoSG finished one job on a free T4 (owner's log) but its mesh was never examined. TRELLIS.2 and Hunyuan3D never ran. The competitive claim therefore rests on zero measured comparisons today.
3. **Purchased is not deployed.** None of the four providers can be shown to be in use; the code has no integration for any of them. Verification needs the owner's read-only checklist.
4. **Meshy is a broad product** (text, image and multi-image to 3D; retexture; remesh with quad topology; rigging and animation; 3D-printing tools; plug-ins for Blender, Unity, Unreal and Maya; REST API and MCP server) with a simple credit model in which failed jobs are free. A textured image-to-3D task works out to roughly $0.60 at its Pro price (derived). This audit could not open Meshy's own pages.
5. **Keep the processing code, replace the shell.** The architecture keeps `aro_studio`'s pipeline as a library, moves identity, data, storage and queues to Supabase, R2 and Cloud Run, and runs only the model on a GPU worker. Google's own pricing page shows Cloud Run's monthly free tier and per-second GPU billing, which may also give a second GPU option.
6. **Licensing steers the model choice.** Hunyuan3D's licence excludes the EU, UK and South Korea, so it cannot power a global service. TRELLIS.2 (MIT code) is the most promising PBR candidate but its weights licence and hidden dependencies are unverified. Texturing arbitrary meshes has no licence-clean open candidate yet.
7. **Honest cost picture:** about $0.03 to $0.31 per successful generation (estimate, wide, to be measured); about $0 to $25 a month fixed while small.

## Decisions and actions needed from the owner

1. **Approve or amend the architecture** (ADR-1 to ADR-9 in `04-architecture.md`).
2. **Run the infrastructure checklist** in `02-infrastructure-audit.md` section 4 (about 15 minutes, read-only, no secrets).
3. **Set an experiment ceiling** for E1 to E4 (proposed $7 in total, E1 first at $3) and choose how to grant access. This session's network could not be widened because the mobile app cannot show that approval; a newer app or claude.ai on a computer fixes this.
4. **Provide a Meshy account** (or run the benchmark inputs yourself) for the comparison, and read the Meshy pages listed in `03-meshy-competitive-audit.md` section 9 if direct reading stays blocked.

## What the audit did not do

It did not open any Meshy, RunPod, Supabase, Cloudflare or Hugging Face page, did not touch any provider account, did not run any model, spent nothing, and measured no output quality. Every one of those is listed as work to do in the roadmap, not as done.
