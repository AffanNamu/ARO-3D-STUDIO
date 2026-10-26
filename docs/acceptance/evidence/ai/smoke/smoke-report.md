# Real image-to-3D smoke test (real_engine)

Recorded 2026-10-26T07:52:11Z · status: **{'real_inference': 'PASS', 'visual_quality': 'PENDING_HUMAN_REVIEW', 'production_ready': 'NOT_CLAIMED'}**

Hardware: Tesla T4, 580.82.07, 15360 MiB · torch 2.11.0+cu130 · python 3.13.16

Engine **triposr** `stabilityai/TripoSR@5b521936b01fbe1890f6f9baed0254ab6351c04a` · device cuda · runnable True · licence status verified

Invalid-file probe: **PASS** (bad file FAILED, 4 valid siblings still queued)

| Item | Category | Result | Triangles | Load s | Infer s | Prep validation | Export |
|---|---|---|---|---|---|---|---|
| ARO 480 Truck at Golden Hour | heavy_truck | **PASS** | 176628 | 10.784 | 5.883 | NEEDS_REVIEW | COMPLETED |
| Chair | furniture | **PASS** | 82833 | 0.0 | 13.435 | PRODUCTION_READY | COMPLETED |
| Teapot | household_object | **PASS** | 83476 | 0.0 | 3.078 | PRODUCTION_READY | COMPLETED |
| Toy robot | equipment | **PASS** | 158779 | 0.0 | 3.145 | PRODUCTION_READY | COMPLETED |

Visual quality is **not** judged automatically: fill in `human_review` for each item in `smoke-evidence.json` after looking at `views/`.
