# Model & component licence records

> Spec §3: *never assume a model is commercially usable because its code is public.* Status words: **verified** = the licence text was read by us for this exact artefact; **claimed** = stated by the publisher but not independently verified for these weights; **blocked** = must not be used.
>
> Environment limitation (stated honestly): the sandbox this was built in could reach GitHub raw files and PyPI but **not huggingface.co** (proxy policy 403). So model cards and weight files could not be read. Everything marked *claimed* needs a human to read the linked page before production use.

## 1. TripoSR (initial image-to-3D engine)

**Machine-readable record:** [`aro_studio/engines/locks/triposr.json`](../../aro_studio/engines/locks/triposr.json). The engine only loads — and its licence status only becomes `verified` — when that file is *complete*: licence evidence + weights revision pinned to a 40-hex commit + SHA-256/size of every file it loads (including the auxiliary `facebook/dino-vitb16` config the upstream code downloads). Run `tests/test_weights_security.py` to see the rules enforced.

### Licence evidence (verification date: **2026-10-10**)

| # | Source | Finding | How verified |
|---|---|---|---|
| 1 | https://github.com/VAST-AI-Research/TripoSR/blob/107cefdc244c39106fa830359024f6a2f1c78871/LICENSE | MIT License, "Copyright (c) 2024 Tripo AI & Stability AI" (file SHA-256 `ade0a666…620fb`) | **Independently fetched** by the engineering agent from a git clone at the pinned commit |
| 2 | …/blob/107cefd…/README.md, line 27 | "The model is released under the MIT license, which includes the source code, pretrained models, and an interactive online demo." (file SHA-256 `ed40f078…490b9`) | **Independently fetched** (same clone) |
| 3 | https://huggingface.co/stabilityai/TripoSR (model card) | MIT | **Project-owner statement** (post-audit task instruction, 2026-10-10). The agent could **not** fetch this page (HTTP 403 from the build sandbox). `scripts/pin_triposr_weights.py` additionally records the Hub's own licence tag at the pinned revision as machine-fetched evidence and aborts if it is not `mit`. |

Conclusion recorded: the upstream README states the MIT licence covers the source code **and** the pretrained models (evidence 1–2). That is a statement of *licence*; it says nothing about whether inference works, and it applies to a **specific artefact** only once the revision is pinned.

### Artefact pin and checksums — recorded 2026-10-11

| Item | Value |
|---|---|
| Code (`tsr`) | pinned: `107cefdc244c39106fa830359024f6a2f1c78871` (2026-06-04, "Update README.md") |
| Weights revision `stabilityai/TripoSR` | `5b521936b01fbe1890f6f9baed0254ab6351c04a` |
| `config.yaml` | sha256 `74ca708c…cc68e62`, 987 bytes (hash computed from the downloaded bytes: the Hub did not report one) |
| `model.ckpt` | sha256 `429e2c6b…d970ee`, 1,677,246,742 bytes |
| `facebook/dino-vitb16` `config.json` | revision `f205d5d8…7cc2`, sha256 `b87c0270…689c`; licence believed Apache-2.0, **unverified** (architecture hyper-parameters only) |

Provenance of the pin: written by `scripts/pin_triposr_weights.py` on a Colab T4 run (`pinned_by: Colab-T4-verification`, commit `587a0b6`); the Hub cross-check is performed by that script. The build sandbox cannot reach Hugging Face, so the author of this document did not re-fetch these values. Anyone with Hub access can re-verify at any time: `python scripts/verify_triposr_weights.py`. `ModelLock.missing()` is empty, which opens the licence gate **for this artefact identity only**; it says nothing about whether inference works.

### Remaining record

| Field | Record |
|---|---|
| Name / version | TripoSR; weights `stabilityai/TripoSR` (`config.yaml`, `model.ckpt`) at the revision in the lock |
| Commercial use | Allowed under MIT as stated by the sources above |
| Redistribution / derivatives | MIT: permitted with the licence and copyright notice retained |
| Output restrictions | None stated in the repository licence. Training-data provenance is not documented upstream; keep this in mind when relying on outputs commercially |
| Deployment restrictions | None in MIT |
| Attribution | Keep the MIT notice with any redistributed copy; credit "TripoSR (Tripo AI & Stability AI)" |
| Free-tier limitations | ≈ 6 GB VRAM at defaults (upstream README); Hugging Face free Docker Spaces have no GPU (verify current terms; not checkable from the sandbox) |
| Dependencies | From the repo's own `requirements.txt` at the pinned commit: `omegaconf==2.3.0`, `Pillow==10.1.0`, `einops==0.7.0`, `torchmcubes` (git), `transformers==4.35.0`, `trimesh==4.0.5`, `rembg`, `huggingface-hub`, `imageio[ffmpeg]`, `gradio`, `xatlas==0.0.9`, `moderngl==5.10.0`, PyTorch. **`torch >= 2.6.0` is additionally required by this Studio** (see the security review) |

How the Studio enforces this: `engines/registry.py::license_gate` (explicit licence gate, preserved: an unverified licence is refused with an exact instruction) **and**, independently, `engines/weights.py` (integrity gate: nothing is deserialised unless pinned + checksummed). The deployer attestation `ARO_VERIFIED_MODEL_LICENSES` can satisfy only the *licence* gate; it cannot make unpinned weights loadable.

## 2. Other components that join the AI path

| Component | Licence (source) | Status |
|---|---|---|
| PyTorch | BSD-3-Clause (publisher) | claimed — verify at install |
| transformers, huggingface-hub | Apache-2.0 (publisher) | claimed |
| omegaconf | BSD-3-Clause | claimed |
| einops | MIT | claimed |
| torchmcubes | MIT per its repository (not read here) | **unverified** |
| rembg (code) | MIT (publisher) | claimed |
| U²-Net weights used by rembg (`u2net`, `u2netp`, `isnet-general-use`) | Apache-2.0 per the upstream repositories (recalled, not read here) | **unverified**; the Studio allow-lists only these (`ARO_REMBG_MODEL`, default `u2net`) and records the downloaded file's SHA-256 |
| BRIA RMBG-2.0 (rembg 2.0.x default) | believed non-commercial | **BLOCKED** in `aro_studio/imaging/matting.py`; rembg's package default is never used |
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
3. For engines whose lock is complete the licence status is `verified` automatically. `ARO_VERIFIED_MODEL_LICENSES=<engine id>` remains an explicit deployer attestation for the licence gate only; weights still must be pinned and checksummed to load.
