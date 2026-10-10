# Deploying to Hugging Face Spaces (free tier)

> Hugging Face specifics below could not be checked from the build sandbox (huggingface.co was unreachable). Confirm current limits at https://huggingface.co/docs/hub/spaces-overview before relying on them.

## Steps

1. Create a Space: **SDK = Docker**, hardware = **CPU basic (free)**. Do **not** pick a paid GPU; the Studio never selects hardware for you.
2. Push this repository (the `README.md` front-matter already declares `sdk: docker`, `app_port: 7860`).
3. Space → Settings → **Variables and secrets**: add `ARO_ACCESS_TOKEN` (secret — **do this on any public Space**), and optionally `ARO_VERIFIED_MODEL_LICENSES=triposr` once you have read the model card. Never commit tokens.
4. The default image has **no AI weights** and runs the full post-reconstruction pipeline (import a mesh or use the TITAN 480 reference).
5. To include TripoSR on CPU: build with `WITH_TRIPOSR=1` (Space → Settings → build args, or your own registry); pin `TRIPOSR_REF` to a reviewed commit, and `ARO_TRIPOSR_MODEL_PATH` to a weights revision.

## Limits you must plan around

| Limit | Consequence |
|---|---|
| Free Docker Spaces have **no GPU** | TripoSR runs on CPU (very slow, RAM-heavy) — or generate elsewhere and import. The Studio reports this instead of pretending. |
| Free Spaces **sleep** when idle and the **disk is ephemeral** | `ARO_DATA_DIR` is lost on restart/rebuild. Export projects (Projects → *Export project*) and downloads you care about. Persistent storage is paid and is **not** enabled automatically. |
| Container RAM limit | the Studio checks free RAM/disk before heavy jobs and fails with advice (`RESOURCE_LIMIT`) instead of crashing; `/api/system` shows the cgroup limit |
| Public by default | enable `ARO_ACCESS_TOKEN`; there are no user accounts |

## Verifying a deployment

`GET /api/health` → `ok`; Models page → engine status and activation hints; run the TITAN 480 reference pipeline; `python scripts/run_acceptance.py` inside the container for the 22-stage report.
