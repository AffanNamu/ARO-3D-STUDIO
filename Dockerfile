# ARO 3D Studio - Hugging Face Spaces (Docker SDK) / any container host.
# Default build is CPU-safe and contains NO AI weights. Add TripoSR with:
#   docker build --build-arg WITH_TRIPOSR=1 --build-arg TRIPOSR_REF=<commit-sha> .
# Base image pinned by digest (python:3.11-slim as pulled on 2026-10-10); override with --build-arg PYTHON_IMAGE=... only deliberately.
ARG PYTHON_IMAGE=python:3.11-slim@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce
FROM ${PYTHON_IMAGE}

ARG WITH_TRIPOSR=0
# Reviewed upstream commit of github.com/VAST-AI-Research/TripoSR (HEAD on 2026-10-10: "Update README.md"); never "main".
ARG TRIPOSR_REF=107cefdc244c39106fa830359024f6a2f1c78871
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 PORT=7860 ARO_DATA_DIR=/home/user/data

# System packages are only needed to clone/compile the optional TripoSR stack (git, torchmcubes build); the default image has none.
RUN if [ "$WITH_TRIPOSR" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends git build-essential libgl1 libglib2.0-0 \
      && rm -rf /var/lib/apt/lists/*; \
    fi

# Hugging Face Spaces run as uid 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH
WORKDIR /home/user/app

COPY --chown=user requirements.txt requirements-triposr.txt ./
RUN pip install --user -r requirements.txt

RUN if [ "$WITH_TRIPOSR" = "1" ]; then \
      pip install --user torch torchvision --index-url "$TORCH_INDEX" \
      && pip install --user -r requirements-triposr.txt \
      && git clone https://github.com/VAST-AI-Research/TripoSR /home/user/TripoSR \
      && git -C /home/user/TripoSR checkout "$TRIPOSR_REF"; \
    fi
ENV PYTHONPATH=/home/user/TripoSR

COPY --chown=user . .
RUN pip install --user --no-deps -e . && mkdir -p "$ARO_DATA_DIR"

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:%s/api/health'%os.environ.get('PORT','7860'),timeout=4)"
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
