# Model requirements and test strategy

## TripoSR runtime

| Requirement | Detail |
|---|---|
| Python | 3.9+ (Docker image uses 3.11) |
| Packages | `torch >= 2.6.0` (match host CUDA; older releases are refused), `omegaconf==2.3.0`, `einops==0.7.0`, `transformers==4.35.0`, `huggingface-hub`, `torchmcubes` (compiled; needs a CUDA toolkit for GPU marching cubes, otherwise CPU), the `tsr` package from the TripoSR repo on `PYTHONPATH` |
| Weights | `config.yaml` + `model.ckpt` from `stabilityai/TripoSR` **at the revision pinned in `aro_studio/engines/locks/triposr.json`**, SHA-256 verified before loading (first load needs outbound access to huggingface.co), or a local directory whose files match the lock (`ARO_TRIPOSR_MODEL_PATH`). Also `facebook/dino-vitb16/config.json` (pinned). The lock is complete (see [model-licenses](model-licenses.md)); re-run `scripts/pin_triposr_weights.py` only to move to a new revision, through a reviewed diff. |
| VRAM | ≈ 6 GB at default settings (TripoSR README). Other presets: estimates only, not measured here |
| CPU fallback | Supported by the code path (`ARO_DEVICE=cpu`); speed and RAM use **not measured** here; expect minutes, several GB RAM |

`GET /api/engines` and the Models page list exactly which of these are missing and the activation commands.

## What has and has not been executed

* **Build sandbox** (4 vCPU, 15 GB RAM, no GPU, no access to huggingface.co or the TripoSR repository): `availability()` correctly reports `tsr`/`torch`/… missing; generation jobs end `MODEL_ERROR` with activation instructions and **no asset is created**. **Real inference was not executed here.**
* **Colab T4** (project owner's session, 2026-10-11): the weights were downloaded and pinned (`587a0b6`), and the evidence recorder was run far enough to expose a pipeline-step schema bug (`2192c6c`). **No inference evidence was committed**, so no inference claim is made. The next step is the Studio-level smoke test: [../verification/real-inference-smoke.md](../verification/real-inference-smoke.md).
* The adapter follows the public API read from the repository (`TSR(cfg)` + `load_state_dict`, `renderer.set_chunk_size`, `model([image], device)`, `extract_mesh(scene_codes, has_vertex_color, resolution, threshold)`); expect to fix small integration details on the first full run.

## Test strategy that runs when the model is available

```bash
pip install -r requirements.txt -r requirements-triposr.txt        # + torch>=2.6 for your CUDA, + TripoSR on PYTHONPATH
ARO_RUN_MODEL_TESTS=1 pytest -m model -v -rs                       # tests/test_triposr_real.py; the licence gate opens from the lock alone
ARO_RUN_MODEL_TESTS=1 ARO_SMOKE_MANIFEST=manifest.json pytest -m model -v -rs   # + the full Studio path for >= 3 real images
python scripts/real_inference_smoke.py --manifest manifest.json    # evidence: docs/acceptance/evidence/ai/smoke
```

`tests/test_triposr_real.py` asserts: the model loads and reports load time; inference on a real image returns a non-empty finite mesh; a generation job through the Studio records provenance and the second identical request is a cache hit that does **not** call the model; a tiny VRAM budget produces a controlled error rather than a crash; and, with `ARO_SMOKE_MANIFEST`, that at least three different images (vehicle + non-vehicle) go through upload → batch job → raw asset → preparation → validation → verified GLB. They are skipped (never faked) when the environment lacks the model, and a skip is not a pass.

## Free GPU options (₦0) — honest summary

* Hugging Face free Spaces: CPU only for Docker Spaces. ZeroGPU is a separate product with its own eligibility rules (verify on Hugging Face); this project does **not** assume it.
* Local NVIDIA GPU or a free notebook GPU (Colab/Kaggle, subject to their quotas/terms): run TripoSR there and use **Import mesh** — the rest of the pipeline is independent of where the mesh came from.
