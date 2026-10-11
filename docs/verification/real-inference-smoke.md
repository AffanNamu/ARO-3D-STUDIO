# Real image-to-3D smoke test (through the Studio)

**Status: not yet run.** No committed evidence shows TripoSR producing a mesh through the Studio. The build sandbox has no GPU
and cannot reach Hugging Face. Until `docs/acceptance/evidence/ai/smoke/smoke-evidence.json` exists with
`"mode": "real_engine"` and `real_inference: PASS`, the acceptance report keeps the real-AI components at BLOCKED.

## What it proves (and what it does not)

`scripts/real_inference_smoke.py` drives the real FastAPI app in-process (same code as the server) with the real engine:

1. **Upload + validation:** one `batch-generate` request with ≥ 3 real images (a vehicle and at least one non-vehicle) plus a
   deliberately invalid file. The invalid file must be rejected **while the valid siblings are still queued**.
2. **Licence gate from the lock only** (no `ARO_VERIFIED_MODEL_LICENSES` override) and `force=true`, so a cache hit can never pass.
3. **Persistent generation jobs → real inference.** Per item it records: input hash/category/source note, engine id, exact model
   version (`repo@revision`), device, `model_ran`/`cache_hit`, model-load and inference seconds, vertices/triangles, native
   extents, finite check, output size + SHA-256, generation id, raw version id, full provenance, source-hash ↔ provenance match,
   peak GPU memory (`nvidia-smi`, whole run).
4. **Viewer:** the raw version's preview GLB is fetched (what the 3D viewer loads); six reference renders are written.
5. **Automatic preparation** (queued job; raw stays immutable): steps, `needs_human` notes, validation status, final extents.
   Raw immutability is checked by manifest hash before/after.
6. **Verified export:** GLB export job, download, SHA-256 equals the record, re-opened with trimesh (triangle count, all LODs),
   internal verification and Khronos validator result.

It does **not** judge quality. Every item carries `human_review: {status: PENDING_HUMAN_REVIEW, recognisable, visual_defects,
category_limitations, orientation_up_front}`; a person looks at `views/` and fills these in. Single-image reconstruction cannot
recover hidden surfaces, true size, or which end is the front; those stay flagged.

PASS requires: ≥ 3 distinct images, vehicle + non-vehicle, every item `model_ran: true` and not a cache hit, finite mesh,
provenance match, raw immutable, viewer preview 200, export checksum + verification OK (and Khronos 0 errors when the validator is
installed), and the invalid-file probe passing. Anything less is PARTIAL / FAIL; an engine that cannot run is BLOCKED (exit 3)
with the exact reasons. `--double` runs the same wiring with the test double and can never report real inference.

## Run it

**Colab (free T4) — the supported path:** open `notebooks/aro_real_inference_colab.ipynb` and run the 12 cells in order. Each cell
states what output to expect and what to send back if it fails. In short:

| Cell | Does | You should see |
|---|---|---|
| 1 | GPU check | `Tesla T4`, `cuda True` |
| 2 | clone the Studio at `STUDIO_REF`, install requirements | `STUDIO COMMIT <hash>` |
| 3 | clone TripoSR at the lock's pinned commit, install `requirements-triposr.txt` (torchmcubes compiles: 3–10 min) | `TSR COMMIT 107cefdc…` |
| 4 | the Studio's own availability report + `verify_triposr_weights.py` (≈ 1.7 GB download, SHA-256 checked) | `lock missing: []`, `availability ok: True`, `OK: all files match the lock` |
| 5 | Khronos validator (optional) | nothing |
| 6 | **upload your vehicle photo**, state its owner/licence; the three object images come from the pinned TripoSR repo and are SHA-256-checked | four thumbnails with sizes and hashes |
| 7 | **the real run** | `"mode": "real_engine"`, `"real_inference": "PASS"` (or BLOCKED/PARTIAL/FAIL with reasons) |
| 8 | re-reads the evidence with the acceptance-report reader | `PASS - 4 different images went through the real engine…` |
| 9 | shows raw vs prepared renders per image | you look at them |
| 10 | **you record your review** (script refuses empty or unknown entries) | `visual_quality: REVIEWED` |
| 11 | packages evidence | two zips downloaded |
| 12 | failure bundle (any failure) | `aro-logs.zip` |

Test images (documented): `chair.png` (furniture), `teapot.png` (household object), `robot.png` (equipment/consumer product), all from
the TripoSR repository's `examples/` at the pinned commit (repository MIT-licensed; per-image authorship not stated upstream);
SHA-256 `2503c12a…b5bf`, `66b0b8f7…6b8c`, `092ee61f…657a`. The vehicle photo is yours, with a stated source. A fifth file, an
invalid text file, is added by the harness to prove the partial-failure behaviour.

Elsewhere (own GPU machine):

```bash
pip install -r requirements.txt -r requirements-triposr.txt      # torch >= 2.6 matching your CUDA
git clone https://github.com/VAST-AI-Research/TripoSR ~/TripoSR && git -C ~/TripoSR checkout 107cefdc244c39106fa830359024f6a2f1c78871
export PYTHONPATH=~/TripoSR
python scripts/verify_triposr_weights.py
python scripts/real_inference_smoke.py --manifest manifest.json --out docs/acceptance/evidence/ai/smoke
python scripts/fill_human_review.py --evidence docs/acceptance/evidence/ai/smoke/smoke-evidence.json --reviews review.json --reviewer "Your Name"
python scripts/package_smoke_evidence.py --dir docs/acceptance/evidence/ai/smoke --out ./package
ARO_RUN_MODEL_TESTS=1 ARO_SMOKE_MANIFEST=manifest.json pytest -m model -v -rs
```

`manifest.json`: `{"items": [{"path": "truck.jpg", "category": "heavy_truck", "name": "Truck", "source": "owner / licence",
"length_m": 7.2}, ...]}`. `length_m`, `up`, `forward` are optional; without `length_m` the prepared size is a flagged placeholder.

## What gets committed (and what does not)

`package_smoke_evidence.py` splits the output. **Commit** `smoke-evidence-repo.zip` contents under
`docs/acceptance/evidence/ai/smoke/`: `smoke-evidence.json`, `smoke-report.md`, `inputs/` (the original images — only if you may
redistribute them; the TripoSR examples are in an MIT repository), `views/` (renders) and the prepared GLBs (each ≤ 8 MB).
**Do not commit** `raw/` (the untouched raw meshes, tens of MB; `.gitignore`d and enforced by `tests/test_repository_safety.py`):
keep `smoke-raw-meshes.zip` yourself; each raw mesh's SHA-256 and size are in the evidence. Never commit model weights or logs
containing tokens (the notebook needs none).

## Resource expectations (to be measured and recorded here after the first run)

TripoSR README: ≈ 6 GB VRAM at the default 256³ marching-cubes grid; `LOW_RESOURCE` (160³) is smaller; first load downloads
≈ 1.7 GB. Measured VRAM/latency on a T4 for each preset: **not recorded yet**.
