# Real-model verification on a GPU host (Phase 2)

**Status in this repository: real inference is NOT yet proven.** The build environment has no GPU and cannot reach
huggingface.co. The model lock was completed from a Colab run on 2026-10-11 (so the licence gate opens), but no inference
evidence has been committed. The processing code downstream of inference is proven only on a *synthetic* TripoSR-shaped mesh
(`tests/test_ai_pipeline.py`, plumbing test, not AI output). The **preferred proof is the Studio-level smoke test**
([real-inference-smoke.md](real-inference-smoke.md)); this runbook's `record_real_inference.py` is the lower-level recorder.

## What you need (all free)

* A machine with an NVIDIA GPU (the `LOW_RESOURCE` preset is intended for ~6 GB VRAM; **not yet measured**) and driver.
  Free options: your own PC, a Kaggle/Colab free GPU session, a Hugging Face ZeroGPU/community-grant Space. Do not buy
  compute for this without a decision from the project owner.
* Outbound HTTPS to `huggingface.co`, `github.com`, `pypi.org`, `download.pytorch.org`.
* Python 3.11+, git. A concept image of a heavy truck (your own artwork or a licensed image - **do not commit an image you
  do not own**). `--titan-render` uses a render of the procedural TITAN 480 as the *input*; that is recorded in the evidence.

## One command

```bash
git clone https://github.com/AffanNamu/ARO-3D-STUDIO && cd ARO-3D-STUDIO
git checkout claude/zen-johnson-je3dzk
CONCEPT_IMAGE=/path/to/concept.png PINNED_BY="you@example.com" scripts/verify_on_gpu_host.sh
```

It: (1) checks the GPU, (2) builds a venv with `torch>=2.6.0` (CVE-2025-32434) and the TripoSR code at the pinned commit,
(3) **pins** revision + SHA-256 + size of `config.yaml`, `model.ckpt` and the DINO `config.json` into the lock, cross-checking
the Hub's own LFS hashes and licence tag, (4) re-verifies the downloaded files, (5) runs `pytest -m model`, (6) runs
`scripts/record_real_inference.py`, which records hardware, VRAM peaks (torch and `nvidia-smi`), timings, mesh statistics, six
reference renders of the raw output, then runs the *real* mesh through the post-reconstruction pipeline and exports/validates a GLB.

### Step 3 changes tracked files

`aro_studio/engines/locks/triposr.json` is edited by the script. **Review `git diff` and commit it** - the revision and
hashes are a security decision made by a person. Never type those values by hand. Once the lock is complete the licence
status becomes `verified` automatically (evidence entries for the MIT licence are already recorded in the lock);
`ARO_VERIFIED_MODEL_LICENSES` alone never opens the integrity gate.

### Manual steps, if you prefer

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pip install "torch>=2.6.0" torchvision --index-url https://download.pytorch.org/whl/cu121   # match your CUDA
git clone https://github.com/VAST-AI-Research/TripoSR ~/TripoSR && git -C ~/TripoSR checkout 107cefdc244c39106fa830359024f6a2f1c78871
pip install -r requirements-triposr.txt && export PYTHONPATH=~/TripoSR
python scripts/pin_triposr_weights.py --by you@example.com          # --dry-run first to preview
python scripts/verify_triposr_weights.py
ARO_RUN_MODEL_TESTS=1 pytest -m model -v -rs tests/test_triposr_real.py
python scripts/record_real_inference.py --image concept.png --up +Z --forward +X
```

## What counts as PASS

| Claim | PASS requires |
|---|---|
| Real AI inference | `generation.job_state == COMPLETED`, `model_ran == true`, finite mesh with >100 triangles, six renders that a human looked at |
| Pipeline on real output | every pipeline step PASS on the *real* raw version (orientation/forward axis confirmed by a person) |
| Validated production asset | validation `PRODUCTION_READY` **and** exported GLB passes Khronos validation. Without a vehicle specification (wheel/axle positions, component roles) validation reports `NEEDS_REVIEW` - that is `PARTIAL`, by design. |

Skipped tests are not passes. `pytest -rs` prints the skip reasons; the evidence JSON must show `real_inference: PASS`
before anything is reported as successful inference.

## Things to confirm and write down (currently unknown)

* The model's native axes. `ORIENTATION_HINT` says `native_up +Z`, forward **unconfirmed**; look at `raw-views/` and pass
  `--up/--forward` accordingly, then update `aro_studio/engines/triposr.py` if it is consistently different.
* VRAM peak and duration for each preset on your GPU. Add the numbers to `docs/models/model-requirements.md`.
* The first load downloads ~1.7 GB. Set `HF_HOME` somewhere persistent.

## Expected failure modes (handled, not hidden)

| Symptom | Meaning |
|---|---|
| `Supply-chain lock incomplete` | the lock lost a pin (it is complete at the time of writing); re-run step 3 and commit the diff |
| `Checksum mismatch` | file differs from the pinned bytes - do not load; investigate |
| `config references a class outside tsr.` | the config tries to instantiate foreign code; refused |
| `RESOURCE_LIMIT` job state | CUDA OOM; use `LOW_RESOURCE` or a larger GPU |
| `MODEL_ERROR` | model raised during load/inference; see the job error and `logs/` |
