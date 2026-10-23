# Real image-to-3D smoke test (real_engine)

Recorded 2026-10-23T08:18:59Z · status: **{'real_inference': 'PARTIAL', 'scope': 'focused run: coverage requirement NOT met (needs >= 3 images incl. vehicle + non-vehicle)'}**

Hardware: Tesla T4, 580.82.07, 15360 MiB · torch 2.11.0+cu130 · python 3.13.15

Engine **triposr** `stabilityai/TripoSR@5b521936b01fbe1890f6f9baed0254ab6351c04a` · device cuda · runnable True · licence status verified

## Blockers
* coverage: only 1 image(s): at least 3 genuinely different images are required; no non-vehicle image

## Coverage problems
* only 1 image(s): at least 3 genuinely different images are required
* no non-vehicle image

Invalid-file probe: **PASS** (bad file FAILED, 1 valid siblings still queued)

| Item | Category | Result | Triangles | Load s | Infer s | Prep validation | Export |
|---|---|---|---|---|---|---|---|
| ARO African Roads Sunset Hauler (3) | heavy_truck | **PASS** | 156597 | 11.42 | 4.08 | NEEDS_REVIEW | COMPLETED |

Visual quality is **not** judged automatically: fill in `human_review` for each item in `smoke-evidence.json` after looking at `views/`.
