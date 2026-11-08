# The RunPod worker image: contents, pins and licences

Status: **NOT BUILT.** `worker/runpod/Dockerfile` was written without Docker or a GPU. Its first build on RunPod and the first real generation are the open evidence items.
Licence facts below were read on 2026-11-08 from the sources named; "attested" is a decision only the owner makes (`docs/platform/owner-setup.md` step 6).

## What runs

`python -m aro_worker.runpod_handler` starts RunPod's serverless loop. Per job: download the one input image from a signed URL (SHA-256 checked) ->
Studio pipeline in-process (background removal with U²-Net -> **TripoSG** shape generation -> orientation and scale -> mesh preparation -> UVs and colour projection
-> validation -> GLB export) -> upload `raw.glb`, `model.glb`, `thumbnail.png`, `report.json` to signed URLs, then `result.json` last. Weights stay in memory between jobs on a warm worker.

## Pins

| Item | Pin | Source (read 2026-11-08) |
|---|---|---|
| Base image | `pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime` @ `sha256:77f17f84...` | Docker Hub tag API |
| TripoSG code | `VAST-AI-Research/TripoSG` commit `fc5c40990181e2a756c4e0b1c2f4d6b5202faf8c` | `git ls-remote`; `LICENSE` is MIT |
| TripoSG weights | `VAST-AI/TripoSG` revision `2c1c516d22d58db486a058d98d31bb6177344e06` | Hugging Face API: `license: mit`, not gated |
| Matting model | rembg `u2net`, allow-listed in `aro_studio/imaging/matting.py` | the Studio refuses any model not on its list (BRIA RMBG is blocked) |

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
