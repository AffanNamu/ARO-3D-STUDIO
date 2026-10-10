# Model & component licence records

> Spec §3: *never assume a model is commercially usable because its code is public.* Status words: **verified** = the licence text was read by us for this exact artefact; **claimed** = stated by the publisher but not independently verified for these weights; **blocked** = must not be used.
>
> Environment limitation (stated honestly): the sandbox this was built in could reach GitHub raw files and PyPI but **not huggingface.co** (proxy policy 403). So model cards and weight files could not be read. Everything marked *claimed* needs a human to read the linked page before production use.

## 1. TripoSR (initial image-to-3D engine)

| Field | Record |
|---|---|
| Name / version | TripoSR; weights `stabilityai/TripoSR` (`config.yaml`, `model.ckpt`). **Revision not pinned** — pin a Hugging Face commit hash in `ARO_TRIPOSR_MODEL_PATH` for production. |
| Source | Code: https://github.com/VAST-AI-Research/TripoSR · Weights/model card: https://huggingface.co/stabilityai/TripoSR |
| Licence — code | **MIT** — *verified*: `LICENSE` read from the repository ("MIT License, Copyright (c) 2024 Tripo AI & Stability AI"). |
| Licence — weights | **MIT** — *claimed*: the repository README states "source code, pretrained models, and an interactive online demo" are MIT. The Hugging Face model card could not be fetched here → **unverified**. The Studio refuses to run it until the deployer sets `ARO_VERIFIED_MODEL_LICENSES=triposr`. |
| Commercial use | Allowed under MIT as stated; confirm on the model card. |
| Redistribution / derivatives | MIT: permitted with the licence + copyright notice retained. |
| Output restrictions | None stated in the repository licence. Training-data provenance is not documented in the repo; consider this when relying on outputs commercially. |
| Deployment restrictions | None in MIT. |
| Attribution | Keep the MIT notice with any redistributed copy of the code/weights. Recommended: credit "TripoSR (Tripo AI & Stability AI)" in credits. |
| Free-tier limitations | Needs ~6 GB VRAM at default settings (README). Hugging Face *free CPU* Spaces have no GPU; CPU inference is possible but slow and RAM-heavy. Free GPU access is not available to Docker-SDK Spaces on the free plan (verify current terms at https://huggingface.co/docs/hub/spaces-gpus — not verifiable from this sandbox). |
| Dependencies (from the repo's `requirements.txt`, read here) | `omegaconf==2.3.0`, `Pillow==10.1.0`, `einops==0.7.0`, `torchmcubes` (git), `transformers==4.35.0`, `trimesh==4.0.5`, `rembg`, `huggingface-hub`, `imageio[ffmpeg]`, `gradio`, `xatlas==0.0.9`, `moderngl==5.10.0`, plus PyTorch. Licences of these are listed below / in `dependency-licenses.md`; **torchmcubes' licence was not verified here**. |

## 2. Other components that join the AI path

| Component | Licence (source) | Status |
|---|---|---|
| PyTorch | BSD-3-Clause (publisher) | claimed — verify at install |
| transformers, huggingface-hub | Apache-2.0 (publisher) | claimed |
| omegaconf | BSD-3-Clause | claimed |
| einops | MIT | claimed |
| torchmcubes | MIT per its repository (not read here) | **unverified** |
| rembg (code) | MIT (publisher) | claimed |
| U²-Net weights used by rembg | Apache-2.0 per the U²-Net repository (not read here) | **unverified**; rembg is optional and off by default |
| xatlas (UV unwrap) | MIT; Python wheel declares MIT (read from installed metadata) | verified (metadata) |

Runtime Python dependencies of the Studio itself are audited from installed metadata in [../dependency-licenses.md](../dependency-licenses.md).

## 3. NVIDIA Lyra 2.0 — BLOCKED

| Field | Record |
|---|---|
| Source of this restriction | The project owner's supplied model information, which states restrictions against production use and generating works for sale/distribution. **Not independently re-read by us** (could not reach the model page). |
| Decision | Not used. `EngineRegistry` refuses any engine whose id contains `lyra`. Re-evaluation requires an independent licence review and a code change. |

## 4. How to verify a licence before production

1. Open the model card / licence file linked above and confirm it grants commercial use of the **weights** and the **generated outputs**, and note the exact revision.
2. Record the revision hash here and in `ARO_TRIPOSR_MODEL_PATH`.
3. Set `ARO_VERIFIED_MODEL_LICENSES=<engine id>` (a deployer attestation, logged in the model record). Without it generation fails with `MODEL_ERROR` and this exact instruction.
