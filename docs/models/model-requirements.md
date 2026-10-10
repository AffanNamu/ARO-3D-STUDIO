# Model requirements and test strategy

## TripoSR runtime

| Requirement | Detail |
|---|---|
| Python | 3.9+ (Docker image uses 3.11) |
| Packages | `torch >= 2.6.0` (match host CUDA; older releases are refused), `omegaconf==2.3.0`, `einops==0.7.0`, `transformers==4.35.0`, `huggingface-hub`, `torchmcubes` (compiled; needs a CUDA toolkit for GPU marching cubes, otherwise CPU), the `tsr` package from the TripoSR repo on `PYTHONPATH` |
| Weights | `config.yaml` + `model.ckpt` from `stabilityai/TripoSR` **at the revision pinned in `aro_studio/engines/locks/triposr.json`**, SHA-256 verified before loading (first load needs outbound access to huggingface.co), or a local directory whose files match the lock (`ARO_TRIPOSR_MODEL_PATH`). Also `facebook/dino-vitb16/config.json` (pinned). **The lock is not yet complete** — run `scripts/pin_triposr_weights.py` first. |
| VRAM | ≈ 6 GB at default settings (TripoSR README). Other presets: estimates only, not measured here |
| CPU fallback | Supported by the code path (`ARO_DEVICE=cpu`); speed and RAM use **not measured** here; expect minutes, several GB RAM |

`GET /api/engines` and the Models page list exactly which of these are missing and the activation commands.

## What was executed in the development sandbox

4 vCPU, 15 GB RAM, no GPU, **no access to huggingface.co**. Result: the TripoSR adapter's `availability()` correctly reports `tsr`/`torch`/… missing; generation jobs end `MODEL_ERROR` with activation instructions and **no asset is created**. **Real inference was not executed.** The adapter code follows the public API read from the repository (`TSR.from_pretrained`, `renderer.set_chunk_size`, `model([image], device)`, `extract_mesh(scene_codes, has_vertex_color, resolution, threshold)`) but has not been run against real weights; expect to fix small integration details on first GPU run.

## Test strategy that runs when the model is available

```bash
pip install -r requirements.txt -r requirements-triposr.txt        # + torch for your CUDA, + TripoSR on PYTHONPATH
export ARO_VERIFIED_MODEL_LICENSES=triposr                         # after reading the model card
ARO_RUN_MODEL_TESTS=1 pytest -m model -v                           # tests/test_triposr_real.py
python scripts/run_acceptance.py --verify-licence triposr          # full 22-stage run; stages 5-7 execute for real
```

`tests/test_triposr_real.py` asserts: the model loads and reports load time; inference on a real image returns a non-empty finite mesh; the raw artefact is hashed and immutable; the second identical request is a cache hit that does **not** call the model; a tiny VRAM budget produces `RESOURCE_LIMIT` rather than a crash. They are skipped (never faked) when the environment lacks the model.

## Free GPU options (₦0) — honest summary

* Hugging Face free Spaces: CPU only for Docker Spaces. ZeroGPU is a separate product with its own eligibility rules (verify on Hugging Face); this project does **not** assume it.
* Local NVIDIA GPU or a free notebook GPU (Colab/Kaggle, subject to their quotas/terms): run TripoSR there and use **Import mesh** — the rest of the pipeline is independent of where the mesh came from.
