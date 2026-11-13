# ARO RunPod Serverless worker: TripoSG image-to-3D behind runpod_handler, with the Studio's preparation pipeline in-process.
#
# Build context = the REPOSITORY ROOT. On RunPod: Serverless -> New Endpoint -> Import Git Repository -> branch -> Dockerfile Path
# `worker/runpod/Dockerfile` (RunPod rebuilds when you publish a GitHub release). Locally: docker build -f worker/runpod/Dockerfile -t aro-runpod .
#
# STATUS: NOT BUILT. Authored without Docker or a GPU. The first RunPod build and the first real generation are the open evidence items;
# send the build log and `scripts/runpod_smoke.py` output back. What is pinned, so a rebuild is reproducible and the licences you attest are
# the licences that run:
#   * base image   pytorch/pytorch 2.6.0 / CUDA 12.4 / cuDNN 9 runtime, by digest (read on Docker Hub 2026-11-08)
#   * TripoSG code VAST-AI-Research/TripoSG commit fc5c409... (repository MIT, BUT the model code includes Tencent Hunyuan DiT and
#     FlashVDM community licences: not valid in the EU, UK or South Korea. Read 2026-11-13; see docs/platform/runpod-worker.md)
#   * TripoSG weights VAST-AI/TripoSG revision 2c1c516... (model card: license mit, not gated, read 2026-11-08)
#   * matting      U^2-Net (rembg `u2net`), downloaded at build time so no run ever downloads a model it was not built with
# NOT installed on purpose: pymeshlab (GPL-3.0), diso (CC BY-NC; the CPU skimage stand-in in aro_worker/shims is used), BRIA RMBG (non-commercial),
# nvdiffrast / nvdiffrec, TRELLIS.2 and Hunyuan3D (evaluation-only, see docs/cto/05-models-and-licensing.md).
FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime@sha256:77f17f843507062875ce8be2a6f76aa6aa3df7f9ef1e31d9d7432f4b0f563dee

ARG TRIPOSG_COMMIT=fc5c40990181e2a756c4e0b1c2f4d6b5202faf8c
ARG TRIPOSG_WEIGHTS_REVISION=2c1c516d22d58db486a058d98d31bb6177344e06

ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/opt/TripoSG:/opt/TripoSG/scripts \
    TRIPOSG_DIR=/opt/TripoSG \
    ARO_WORKER_CACHE=/models \
    ARO_TRIPOSG_REVISION=${TRIPOSG_WEIGHTS_REVISION} \
    ARO_REMBG_MODEL=u2net U2NET_HOME=/opt/u2net \
    HF_HOME=/models/hf

RUN apt-get update && apt-get install -y --no-install-recommends git libgl1 libglib2.0-0 libjpeg-dev && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./requirements.txt
COPY worker/runpod/requirements.txt ./requirements-runpod.txt
# the base image already ships torch; pip must not replace it (requirements.txt has no torch line)
RUN pip install -r requirements.txt -r requirements-runpod.txt

# TripoSG code at a pinned commit (the `triposg` package and its scripts)
RUN git clone https://github.com/VAST-AI-Research/TripoSG.git /opt/TripoSG \
 && git -C /opt/TripoSG checkout ${TRIPOSG_COMMIT} && rm -rf /opt/TripoSG/.git

# Weights are fetched at build time into the image so a cold start never depends on Hugging Face being reachable or fast.
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='VAST-AI/TripoSG', revision='${TRIPOSG_WEIGHTS_REVISION}', local_dir='/models/TripoSG')"
# Matting model, explicit and allow-listed in aro_studio/imaging/matting.py
RUN python -c "import rembg; rembg.new_session('u2net')"

COPY aro_studio ./aro_studio
COPY aro_worker ./aro_worker
COPY aro_cloud/__init__.py aro_cloud/keys.py aro_cloud/schemas.py ./aro_cloud/

# Fail the BUILD, not the first customer job, if a dependency is missing or a restricted engine slipped in.
COPY scripts/check_engine_imports.py ./scripts/check_engine_imports.py
# (diso is expected to be unresolved: aro_worker/shims/diso_shim.py stands in for it; anything else unresolved fails the build)
RUN python -c "import aro_worker.runpod_handler, runpod, diffusers, rembg, cv2, skimage" \
 && python scripts/check_engine_imports.py /opt/TripoSG triposg/pipelines/pipeline_triposg.py triposg/inference_utils.py scripts/image_process.py | tee /tmp/imports.txt \
 && ! grep '^MISSING' /tmp/imports.txt | grep -v ' diso'

# Deployment configuration (set in the RunPod endpoint's environment, never in the image):
#   ARO_VERIFIED_MODEL_LICENSES=triposg      the deployer's attestation that TripoSG's licences (MIT weights + Tencent terms) permit your use
#   ARO_WORKER_ALLOWED_HOSTS=<account>.r2.cloudflarestorage.com   (default: any *.r2.cloudflarestorage.com)
#   ARO_WORKER_ENGINES=triposg               (default)
CMD ["python", "-u", "-m", "aro_worker.runpod_handler"]
