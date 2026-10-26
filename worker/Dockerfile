# ARO GPU worker image (heavy image-to-3D engines behind an HTTP API). Build and run on a host with an NVIDIA GPU and driver:
#
#   docker build -f worker/Dockerfile -t aro-worker .
#   docker run --gpus all -p 8000:8000 -e ARO_WORKER_TOKEN=<24+ random chars> -e HF_TOKEN=<gated DINOv3 access> \
#              -v aro-hf-cache:/root/.cache/huggingface aro-worker
#
# NOT BUILT YET: authored without Docker or a GPU. The install script it calls is itself unverified on hardware (see its header).
FROM nvidia/cuda:12.4.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3.10 python3.10-venv python3-pip git build-essential ninja-build libjpeg-dev libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY aro_worker ./aro_worker
COPY worker ./worker
RUN ARO_WORKER_ROOT=/opt bash worker/install_engines.sh trellis2,triposg

ENV PATH=/opt/aro-worker-venv/bin:$PATH \
    ATTN_BACKEND=xformers \
    PYTHONPATH=/opt/TRELLIS.2 \
    TRIPOSG_DIR=/opt/TripoSG \
    ARO_WORKER_CACHE=/models
VOLUME ["/models"]
EXPOSE 8000
# Set ARO_WORKER_TOKEN (24+ random characters) at run time; without it the worker generates one and prints it once in its log.
CMD ["python", "-m", "aro_worker", "--engines", "trellis2,triposg", "--port", "8000"]
