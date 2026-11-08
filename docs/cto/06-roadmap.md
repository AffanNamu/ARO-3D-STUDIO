# 06 · Production roadmap, milestones and benchmark protocol (Phase 2)

Status words: PASS, PARTIAL, BLOCKED, FAIL, NOT STARTED. Audit date 2026-11-08.

## 1. Phase status

| Phase | Name | Status | Note |
|---|---|---|---|
| 0 | Repository and infrastructure audit | **PARTIAL** | repository audited; infrastructure BLOCKED (no access; owner checklist in `02-infrastructure-audit.md`) |
| 1 | Meshy competitive audit | **PARTIAL** | matrix of 62 capabilities delivered; Meshy sources read only through search summaries |
| 2 | Technical architecture | **PARTIAL** | architecture, schema, model and licence assessment delivered as a proposal; awaiting owner approval; weights licences unverified |
| 3-9 | Infrastructure to hardening | NOT STARTED | below |

## 2. Phases 3 to 9

Costs are estimates (basis in `04-architecture.md`). "Owner approval" marks anything that spends money or changes a paid account.

### Phase 3 · Infrastructure (reversible, mostly free)

* **Deliver:** Supabase dev project with `schema.sql` applied; R2 bucket (private) with CORS and a scoped token; Google Cloud budget alerts and a Cloud Run API skeleton; secrets in environment or secret manager; CI additions (secret scan, container scan, Postgres service for RLS tests).
* **Depends on:** owner's checklist results; owner approval for any paid plan.
* **Acceptance:** the health endpoint is live; RLS tests run against a real Postgres in CI and prove user A cannot read user B's rows; a signed-URL upload and download round trip works and an expired URL is refused; budget alerts are visible in the console screenshot.
* **Cost:** expected $0; Supabase Pro ($25 per month, S) only before real users and only with approval.

### Phase 4 · First real generation pipeline (the first honest milestone)

1. **E1** (`05-models-and-licensing.md`): TRELLIS.2 on one 48 GB Pod, capped. *Owner approval.*
2. RunPod handler and a versioned worker image for the winning engine; CPU processing job; job state machine with reconciliation and credit reserve/capture/release.
3. One image in, one validated GLB out: R2, a Postgres asset record and the viewer.

* **Acceptance (all measured, none assumed):** 20 benchmark images run; every success passes the output gates (valid GLB, mesh and triangle counts, bounds, normals, UVs, materials and texture references, file size, orientation); time, GPU, VRAM and cost recorded per job; a killed worker is reconciled and the credit released; a duplicate request creates one job; the endpoint is scaled to zero afterwards (console screenshot).
* **Cost:** E1 cap plus up to a few dollars of endpoint testing. *Owner approval.*

### Phase 5 · Complete generation experience

* **Deliver:** text-to-3D (two-stage) and image-to-3D journeys with real controls (target polycount, topology, PBR, texture size, pose, seed, model tier), status stream, history, regenerate/variations, cancel, recovery from errors, credits shown and spent correctly.
* **Acceptance:** Playwright journeys for both inputs against staging with a real engine at least once; failure-injection tests (provider timeout, worker crash, output rejected) all end in a consistent job state and a correct ledger; ledger property tests pass.

### Phase 6 · AI texturing and refinement

* **Deliver:** PBR maps from the engine mapped onto the game mesh (metallic-roughness packing, AO bake), texture refinement, quad remesh option, retexture **only if** a licence-clean model exists (E5), every operation labelled AI or conventional in the provenance.
* **Acceptance:** Blender-rendered sampling test proves textures land on the right surfaces; Khronos validator clean; geometry and UVs unchanged by retexture (hash check).

### Phase 7 · Professional 3D workspace

* **Deliver:** React Three Fiber viewport (orbit, pan, zoom, perspective/orthographic), selection and transform gizmos, hierarchy, lighting and environment, material inspector, compare view, undo/redo, projects and versions, export panel, thumbnails.
* **Acceptance:** a 1M-triangle model orbits smoothly on a mid-range laptop (frame time measured); save/reload restores the scene exactly; undo/redo round-trip tests.

### Phase 8 · Characters and advanced capabilities

* **Deliver:** character mode (A/T pose), UniRig-based rigging if E4 passes, animation preview, skinned export.
* **Acceptance:** rigged export re-imported in Blender with matching bones and plausible weights; nothing is announced until it passes.

### Phase 9 · Competitive quality and production hardening

* **Deliver:** benchmark reports against Meshy, load and cost tests, penetration-style review, licence and legal review (GPL components, model terms, content policy), backup/restore drill, monitoring and on-call basics.
* **Acceptance:** the production-readiness checklist is signed by the owner; no capability is called "Production ready" without it.

## 3. Milestones

| ID | Milestone | Measurable exit |
|---|---|---|
| M0 | Audit complete | owner checklist returned; weights licences read for the shortlisted models |
| M1 | E1 done | recorded VRAM, time, cost, validity for TRELLIS.2; engine chosen or rejected with evidence |
| M2 | First end-to-end job | one image becomes a validated GLB in R2, a Postgres record and the viewer |
| M3 | Benchmark v1 baseline | the 30-item dataset run on ARO and on Meshy; raw ratings published |
| M4 | Public alpha | accounts, credits, history, text and image journeys, with limits and alerts live |
| M5 | Texturing and refinement | B1, B4, C3 rows reach "Implemented" with tests |
| M6 | Workspace | D rows reach "Implemented"; performance target met |

## 4. Benchmark protocol (directive section 14)

Nothing has been measured yet; this defines how it will be done so results are reproducible and cannot be invented.

**Dataset v1 (30 items, versioned manifest with SHA-256 per file):** 10 text prompts (props, vehicles, characters, environment pieces), 15 single images (5 ARO vehicles, 5 props, 5 characters or organic shapes) and 5 multi-view sets (added when multi-image input exists). Images must be owned by the owner or CC0, with the licence recorded. Prompts and images are frozen before any run.

**Runs:** identical inputs on ARO and Meshy. For Meshy record: date, `ai_model` and settings, whether PBR/remesh were on, credits spent and the converted price, wall time. For ARO record: commit, model id and version, image tag, settings, GPU, wall time, cost. One run per item per system unless variance is being studied; every output is kept.

| Dimension | How it is measured |
|---|---|
| Prompt adherence | blind human rating, 1 to 5, at least 3 raters, randomised order, written rubric |
| Shape accuracy and proportions | silhouette overlap and proportion checks against the reference (existing `quality` tools) |
| Geometry quality | automated: watertight, components, self-intersections, normals, degenerate faces |
| Polygon efficiency | triangles at equal human rating |
| Surface detail, texture realism, material consistency | blind human rating; automated PBR map presence and value ranges |
| UV quality | automated: overlap, stretch, texel-density variance |
| Export integrity | Khronos validator, Blender round trip, engine import where the owner can test |
| Speed and cost | measured per job |

**Reporting rules:** publish raw ratings, medians and spread; no composite score unless defined before the runs; a statement such as "ARO is better" is allowed only when the difference exceeds rater noise and the sample is large enough to say so; failures are reported, not dropped. Reports live in `benchmarks/reports/YYYY-MM-DD.md` and are regenerated whenever a model or pipeline change can affect quality. If ARO loses on a dimension, the report says so.

## 5. Risks

| Risk | Mitigation |
|---|---|
| Open models do not match Meshy's quality | choose by measured evidence; consider fine-tuning only through the gate in `docs/architecture/fine-tuning-plan.md` |
| TRELLIS.2 needs more VRAM or time than assumed | E1 measures before any endpoint is built; provider abstraction allows another host (ADR-9) |
| Licence surprise in a hidden dependency | read the full dependency chain (`05` section 3) before a model is enabled; DB constraint blocks unverified models |
| GPU cold starts and availability | scale-to-zero with one worker, cached model images, measure; alternative provider |
| Budget overrun | per-experiment caps, per-job deadline and cost record, auto-pay off, budget alerts |
| Prompt abuse / unsafe content | prompt and image moderation policy before text-to-3D goes public |
| GPL components in shipped images | legal review before publishing any container image |
| Owner time and tooling friction (mobile app cannot show approvals) | keep owner tasks small; ask for a newer app or a computer session for approvals |
| Scope sprawl | one vertical slice first (M2), then widen |

## 6. Recommended next actions

1. **Owner:** approve or amend the architecture (ADR-1 to ADR-9).
2. **Owner:** run the read-only infrastructure checklist (about 15 minutes) so Phase 0 can close.
3. **Owner:** set the E1 ceiling and choose how to give access (run the Pod from a runbook, or use a newer app/computer session so the access request can be approved). Nothing is spent until then.
4. **Engineering, no accounts needed:** a Postgres-backed test harness for `schema.sql` (RLS and ledger property tests in CI), an API skeleton with JWT verification, and CI secret/container scanning. All reversible and free.
