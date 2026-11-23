# The RunPod worker image: contents, pins and licences

Status (2026-11-23): **BUILT and self-tested on CPU** by `.github/workflows/worker-image.yml`; published as
`ghcr.io/affannamu/aro-worker` (public: RunPod pulls it without a registry credential). Endpoint `aro-worker` runs it pinned by digest.
First real GPU generation on that endpoint: **PASS** (2026-11-23, RTX 4090; evidence in `docs/platform/first-real-generation.md`, part E0).
Licence facts below were read on 2026-11-08 from the sources named; "attested" is a decision only the owner makes (`docs/platform/owner-setup.md` step 6).

## What runs

`python -m aro_worker.runpod_handler` starts RunPod's serverless loop. Per job: download the one input image from a signed URL (SHA-256 checked) ->
Studio pipeline in-process (background removal with U²-Net -> **TripoSG** shape generation -> orientation and scale -> mesh preparation -> UVs and colour projection
-> validation -> GLB export) -> upload `raw.glb`, `model.glb`, `thumbnail.png`, `report.json` to signed URLs, then `result.json` last. Weights stay in memory between jobs on a warm worker.

## How the image is built and deployed

RunPod's GitHub integration builds only from the RunPod console, so the image is built by GitHub Actions instead (free for a public
repository, no GPU): `.github/workflows/worker-image.yml` runs on every push to the worker's code. In order:

1. `docker build -f worker/runpod/Dockerfile .` (about 10 minutes; the image is about 20 GB unpacked, most of it PyTorch and the 7.95 GB of weights).
2. `worker/runpod/selftest.py` inside the built image, **with no network**. Before anything is pushed it must show:
   * the pinned weights are complete (sizes and safetensors headers);
   * the TripoSG checkout and packages are importable (the engine's only complaint is "no CUDA GPU");
   * U²-Net matting works offline;
   * the weights resolve offline exactly as the engine's `load()` asks for them (`HF_HUB_OFFLINE=1`);
   * TripoSG runs through our engine's `generate()` on the CPU (4 flow steps, 128³ grid). This is a smoke test of the code path, not a quality result;
   * one job runs through the real handler and the Studio pipeline in direct mode with the labelled test-double engine.
3. Push to GHCR. The job summary prints the digest to pin, and whether the package can be pulled anonymously.

To deploy a new image, update the endpoint's image to the new digest (RunPod rolls it out as workers cycle). Each build's digest is in its
run summary under **Actions -> Worker image**.

What the self-test caught on the first build (2026-11-23): upstream pins no library versions, so pip installed diffusers 0.43,
transformers 5.24 and huggingface_hub 2.4. TripoSG imports `diffusers.models.normalization.LayerNorm`, which diffusers 0.43 removed.
`worker/runpod/requirements.txt` now pins the libraries TripoSG's model code touches to releases from its own period.

## Pins

| Item | Pin | Source (read 2026-11-08) |
|---|---|---|
| Base image | `pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime` @ `sha256:77f17f84...` | Docker Hub tag API |
| TripoSG code | `VAST-AI-Research/TripoSG` commit `fc5c40990181e2a756c4e0b1c2f4d6b5202faf8c` | `git ls-remote`; root `LICENSE` is MIT, **but see the Tencent section below** |
| TripoSG weights | `VAST-AI/TripoSG` revision `2c1c516d22d58db486a058d98d31bb6177344e06` | Hugging Face API: `license: mit`, not gated |
| Matting model | rembg `u2net`, allow-listed in `aro_studio/imaging/matting.py` | the Studio refuses any model not on its list (BRIA RMBG is blocked) |

## TripoSG is not plain MIT (correction, read 2026-11-13 at the pinned commit)

* `triposg/models/transformers/triposg_transformer.py`, the core model, says it is "based on Tencent HunyuanDiT" and carries the
  **Tencent Hunyuan Community License**: not valid in the European Union; Tencent's Acceptable Use Policy applies; Outputs may not be used
  to improve another large language model; the use restrictions must be written into your terms of use; above 100 million monthly users
  you need Tencent's licence.
* `triposg/LICENSE` is the **Tencent Hunyuan FlashVDM Community License**, for the FlashVDM-derived decoder the pipeline uses: not valid in
  the EU, the United Kingdom or South Korea; Acceptable Use Policy; Outputs may not be used to improve any other AI model; above 1 million
  monthly users you need Tencent's licence.
* The weights card says MIT, but the weights cannot run without this code.

What it means for you: testing in Nigeria is inside the licence territory. Before a public launch you must decide (ideally with legal
advice) either to accept the Tencent terms (block users in the EU, UK and South Korea, add the use restrictions to your terms of use, stay
under 1M monthly users) or to switch to an engine with no territorial terms. Migration 0002 records these terms in the database and
withdraws any verification made before this correction.

## Deliberately not installed

`pymeshlab` (GPL-3.0; upstream lists it for an optional face-reduction example), `diso` (CC BY-NC; `aro_worker/shims/diso_shim.py` replaces it with scikit-image marching cubes, slower on large grids and recorded in each result), BRIA RMBG-1.4 / 2.0 (non-commercial), `nvdiffrast` / `nvdiffrec` (research or evaluation only), TRELLIS.2 and Hunyuan3D (evaluation-only; the handler refuses them unless `ARO_WORKER_EVALUATION_MODE=1`). The build fails if any import the TripoSG source needs is unresolved other than `diso`.

## Dependency licences

Method (2026-11-08): `worker/runpod/requirements.txt` and the Studio's `requirements.txt` were installed into a clean virtualenv (159 distributions) and each one's declared
licence was read from its installed metadata. `torch` was stubbed because the image takes it from its base image (PyTorch is BSD-3-Clause; the base image also carries NVIDIA CUDA runtime libraries
under NVIDIA's own terms and the usual Ubuntu/GNU system packages, which matters if you ever **publish** the image). Not scanned: the base image's contents and the TripoSG repository's own imports beyond what the build check
resolves. Every scanned package declares a permissive licence (MIT, BSD, Apache-2.0, PSF, ISC, MPL-2.0) except these, which were read or noted individually:

| Package | Licence | Why it is there, and why it is acceptable here |
|---|---|---|
| `paramiko` 5.1.0 | **LGPL-2.1** | a dependency of the `runpod` SDK, imported only by the SDK's SSH/CLI helper modules (`runpod/cli/...`), never by the serverless loop or by our code. Installed unmodified as its own package; LGPL permits that. Keep its licence file in any image you redistribute, and do not modify it. Have counsel confirm if you plan to **publish** the image |
| FFmpeg libraries bundled in `opencv-python-headless` wheels | LGPL | dynamically linked, unmodified, shipped by the OpenCV project. Same note about redistribution |
| `python-dateutil` 2.9.0 | Apache-2.0 for contributions after 2017-12-01, BSD-3-Clause before (its LICENSE file, read) | transitive; permissive |
| `rembg` model download (`u2net`) | Apache-2.0 per the upstream repository (recalled, not read in this audit) | **unverified: read it before attesting** |
| DINOv2 image encoder inside the TripoSG weights | Apache-2.0 per Meta's repository (recalled, not read in this audit) | covered by the TripoSG card's `mit` metadata only as far as the publisher's claim goes; read the card |

The API's own closure (`requirements.txt` + `requirements-cloud.txt`) is audited in CI: `docs/dependency-licenses.md` (53 packages, 0 unreviewed).
`moto`, used only by the tests, is Apache-2.0 (its closure: BSD and Apache-2.0 packages).

## Cold starts and cost

Weights are baked into the image, so a cold start is an image pull plus loading about 8 GB onto the GPU, not a download. With min workers 0 you pay nothing while idle;
the first request after idle waits for that. The API records each run's GPU seconds (from RunPod's `executionTime`) and, if `ARO_GPU_USD_PER_SECOND` is set, a cost estimate.
