# Infrastructure and resource requirements

| Mode | CPU | RAM | Disk | GPU | Cost |
|---|---|---|---|---|---|
| Studio without AI (import / reference / processing / export) | 1–2 vCPU | ≥ 2 GB (4 GB for 300k-face meshes) | ≥ 1 GB + your projects | none | ₦0 |
| + TripoSR on CPU | 4+ vCPU recommended | ≥ 8 GB (estimate, **not measured**) | + ~2–3 GB (torch + weights) | none | ₦0 (slow) |
| + TripoSR on GPU | any | ≥ 8 GB | + ~5 GB | ≈ 6 GB VRAM at defaults (published) | ₦0 on your own GPU / free notebook quotas |

Measured in the development sandbox (4 vCPU Xeon @ 2.1 GHz, 15 GB RAM, no GPU; `pytest tests/test_performance.py -s`):

| Operation | Input | Time |
|---|---|---|
| Mesh inspection (11 defect classes, no intersection test) | 327,680 triangles (≈ TripoSR 256³ output) | 3.3 s |
| Standard cleanup (merge, degenerate, duplicates, fragments, normals) | 327,680 triangles | 4.8 s |
| Quadric decimation to 25k | 327,680 → 25,000 triangles | 0.4 s |
| Self-intersection test | 327,680 triangles, 3 s budget | honours the budget (22,528 faces tested → reported `partial`) |
| UV unwrap (xatlas, subprocess) | 20,480 triangles | 3.7 s |
| TITAN 480 reference: build / LOD / validate / GLB export / verify | 15,736 triangles | 0.06 / 0.10 / 0.81 / 0.17 / 0.37 s |
| Full 22-stage acceptance run (4 exports + verification) | TITAN 480 | ≈ 14 s |

TripoSR inference time and VRAM were **not measured** (no GPU, no weights here). The only published figure is ~6 GB VRAM at defaults.

* **Backups:** the whole state is `ARO_DATA_DIR`. Back up `studio.sqlite3` (WAL; use `sqlite3 .backup`) together with `projects/`.
* **Scaling:** more workers (`ARO_WORKERS`) only help non-GPU jobs; a single GPU should keep one worker.
* **Hardening checklist:** set `ARO_ACCESS_TOKEN`; run behind HTTPS; keep `ARO_MAX_UPLOAD_MB` modest; mount `ARO_DATA_DIR` on its own volume; review `audit_log`; keep dependencies updated (CI runs `pip-audit` + `bandit`).
* **No paid dependency** is introduced anywhere. If a future component would cost money, stop and report it (COMPONENT / WHY / COST / FREE ALTERNATIVE / TRADE-OFF / RECOMMENDATION).
