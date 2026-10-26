#!/usr/bin/env bash
# Install the heavy image-to-3D engines for the ARO GPU worker (see docs/architecture/gpu-worker.md).
#
#   worker/install_engines.sh [trellis2,triposg]        default: both
#
# Target: Ubuntu 22.04, Python 3.10, an NVIDIA driver, and the CUDA 12.4 TOOLKIT (nvcc) - the CUDA extensions are compiled here.
#
# STATUS: written from the upstream READMEs and setup scripts read in October 2026 (microsoft/TRELLIS.2, VAST-AI-Research/TripoSG).
# It has NOT been run on a GPU host yet (the authoring sandbox has no GPU and cannot reach huggingface.co). Expect to adjust it on
# the first real run and send the log back. Each step prints what it does and stops at the first error.
#
# Deliberate differences from the upstream TRELLIS.2 setup.sh:
#   * nvdiffrec is NOT installed: its licence is non-commercial, and it is only used upstream for rendering previews;
#   * pillow-simd, gradio and tensorboard are skipped (not needed for serving);
#   * the attention backend defaults to xformers (flash-attn needs a long compile and Ampere or newer); set ATTN=flash-attn to use it.
set -euo pipefail

ENGINES="${1:-trellis2,triposg}"
ROOT="${ARO_WORKER_ROOT:-/opt}"
VENV="${ARO_WORKER_VENV:-$ROOT/aro-worker-venv}"
PY="${PYTHON:-python3.10}"
ATTN="${ATTN:-xformers}"
EXT="${EXT_DIR:-/tmp/aro-extensions}"

say() { printf '\n==> %s\n' "$*"; }
want() { [[ ",$ENGINES," == *",$1,"* ]]; }

command -v nvidia-smi >/dev/null || { echo "no NVIDIA driver found (nvidia-smi missing)"; exit 1; }
command -v nvcc >/dev/null || { echo "nvcc not found: install the CUDA 12.4 toolkit (the engines compile CUDA extensions)"; exit 1; }
nvcc --version | tail -n 2
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

say "python environment: $VENV"
"$PY" -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install --upgrade pip wheel setuptools
pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124

say "worker runtime"
pip install fastapi uvicorn python-multipart pillow numpy trimesh huggingface_hub fast-simplification
pip install -e "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." --no-deps  # the aro_worker package itself

mkdir -p "$EXT"

if want trellis2; then
  say "TRELLIS.2 (MIT code; read the weights model card before production use)"
  [[ -d "$ROOT/TRELLIS.2" ]] || git clone --recursive https://github.com/microsoft/TRELLIS.2.git "$ROOT/TRELLIS.2"
  pip install imageio imageio-ffmpeg tqdm easydict opencv-python-headless ninja trimesh transformers pandas lpips zstandard kornia timm
  pip install "git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8"
  if [[ "$ATTN" == "flash-attn" ]]; then
    pip install flash-attn==2.7.3
  else
    # A build matching torch 2.6.0 / cu124 is required; pip refuses a mismatch rather than replacing torch (--no-deps).
    pip install --no-deps xformers==0.0.29.post3 --index-url https://download.pytorch.org/whl/cu124 \
      || { echo "xformers build for torch 2.6 not found: pick the matching version from https://pypi.org/project/xformers/ and re-run"; exit 1; }
  fi
  [[ -d "$EXT/nvdiffrast" ]] || git clone -b v0.4.0 https://github.com/NVlabs/nvdiffrast.git "$EXT/nvdiffrast"   # NVIDIA 1-way commercial licence
  pip install "$EXT/nvdiffrast" --no-build-isolation
  [[ -d "$EXT/CuMesh" ]]   || git clone --recursive https://github.com/JeffreyXiang/CuMesh.git "$EXT/CuMesh"
  pip install "$EXT/CuMesh" --no-build-isolation
  [[ -d "$EXT/FlexGEMM" ]] || git clone --recursive https://github.com/JeffreyXiang/FlexGEMM.git "$EXT/FlexGEMM"
  pip install "$EXT/FlexGEMM" --no-build-isolation
  pip install "$ROOT/TRELLIS.2/o-voxel" --no-build-isolation
  echo "export ATTN_BACKEND=$ATTN"
  echo "export PYTHONPATH=$ROOT/TRELLIS.2:\${PYTHONPATH:-}"
  echo "TRELLIS.2 conditioning uses DINOv3 (gated on Hugging Face): accept the licence there and export HF_TOKEN for the worker."
fi

if want triposg; then
  say "TripoSG (MIT code; geometry only; read the weights model card before production use)"
  [[ -d "$ROOT/TripoSG" ]] || git clone https://github.com/VAST-AI-Research/TripoSG.git "$ROOT/TripoSG"
  # Upstream pins numpy==1.22.3 and old libraries; install their requirements in a separate venv if they clash with TRELLIS.2.
  pip install diffusers einops omegaconf scikit-image scipy opencv-python-headless peft jaxtyping
  echo "export TRIPOSG_DIR=$ROOT/TripoSG"
  echo "TripoSG's own script removes backgrounds with BRIA RMBG-1.4 (NON-COMMERCIAL): the worker never calls it; it feeds the Studio's cut-out."
fi

say "done. Start the worker:  ARO_WORKER_TOKEN=<random 24+ chars> python -m aro_worker --engines $ENGINES --port 8000"
