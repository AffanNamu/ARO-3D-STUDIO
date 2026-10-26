# Rehearsal of the Colab engine-lab environment (2026-10-26)

The engine lab ([notebook](../../notebooks/aro_engine_lab_colab.ipynb), [`scripts/lab_bootstrap.py`](../../scripts/lab_bootstrap.py)) builds an
isolated Python 3.10 environment and runs TripoSG (and optionally Hunyuan3D-2 mini) in a GPU worker. Nobody has run it on a GPU yet. This
page records what was checked **in the authoring sandbox (CPU only, no Hugging Face access)**, so the first Colab run starts from a verified
baseline, and what could not be checked.

## Checked, and how

| Check | Result | How |
|---|---|---|
| A managed Python 3.10 can be created with `uv` without root | PASS | `uv venv --python 3.10` (the interpreter is downloaded from GitHub release assets) |
| The pinned package set resolves with no conflicts on Python 3.10 | PASS | `uv pip install --dry-run`, then a real install of the same 33 requirements: torch 2.5.1, torchvision 0.20.1, diffusers 0.32.2, transformers 4.49.0, peft 0.14.0, numpy 1.26.4, scikit-image 0.25.2, pymeshlab 2025.7, trimesh, fastapi, uvicorn and the rest of `lab_bootstrap.py`'s lists |
| PyPI's torch 2.5.1 wheel is the CUDA 12.4 build and brings its own CUDA libraries (no `nvcc`, no compiler) | PASS (by the installed `nvidia-*-cu12==12.4.x` wheels) | the install log |
| Every third-party name TripoSG imports exists in that environment | PASS: 0 unresolved except `diso` | `scripts/check_engine_imports.py` over the 12 TripoSG source files that make up the pipeline, VAE, transformer, helpers and `prepare_image`: 63 distinct third-party imports resolved and 1 not (`diso`), including diffusers' `Attention`, `apply_rotary_emb`, `PeftAdapterMixin`, `FlowMatchEulerDiscreteScheduler` and transformers' `Dinov2Model`, `BitImageProcessor`. The engine's code was parsed, not executed |
| `diso` (a CUDA extension) is the only missing name, and the stand-in replaces it | PASS | `aro_worker/shims/diso_shim.py` run with REAL torch 2.5.1 in that environment: returns torch tensors in the shape the caller expects; an SDF sphere comes back with 0.997 of the analytic volume, outward-wound after the caller's face flip, unevaluated (NaN) regions treated as outside |
| Every third-party name Hunyuan3D-2's shape stage imports exists | PASS: 0 unresolved | same script over `pipelines.py`, `postprocessors.py`, `preprocessors.py`. `pymeshlab` prints "Unable to load plugins ... libOpenGL.so.0" without OpenGL libraries; the plug-in never calls its filters (it simplifies with `fast_simplification`), but `apt-get install libopengl0` removes the warning if it matters |
| The worker package runs under Python 3.10 | PASS | `python -m aro_worker --engines fake` in that environment: `/ping`, `/v1/engines`, a job to completion with its SHA-256 |
| Both engine plug-ins report why they cannot run instead of failing | PASS | on the CPU sandbox: "checkout not found" and "no CUDA GPU" |

## Not checked (needs a GPU session, or Hugging Face)

* Downloading the weights, loading them, and running inference. Nothing about quality, speed or VRAM is known yet.
* That `torch 2.5.1+cu124` works with the Colab driver at the time of the run (a current driver supports CUDA 12.4 binaries; expected, not seen).
* The first real iso-surface extraction with the stand-in at 512^3 (time and RAM: estimated seconds to a minute and a few GB; unmeasured).
* TripoSG's TRELLIS-style pitfalls that only show at runtime: `prepare_image` needs CUDA tensors, the step callback signature, the output tuple. They were read from the source, not executed.
* The Hunyuan3D checkout's own local modules (only the three files above were fetched: GitHub archive downloads are blocked here).

If the first Colab run fails, `aro-lab-logs.zip` (the notebook's last cell) holds `setup.log` and `worker.log` with the traceback.
