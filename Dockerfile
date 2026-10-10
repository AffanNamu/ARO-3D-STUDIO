# ARO 3D Studio - Hugging Face Spaces (Docker SDK) / any container host.
# Default build is CPU-safe and contains NO AI weights. Add TripoSR with:
#   docker build --build-arg WITH_TRIPOSR=1 --build-arg TRIPOSR_REF=<commit-sha> .
FROM python:3.11-slim

ARG WITH_TRIPOSR=0
# Pin to a reviewed commit of github.com/VAST-AI-Research/TripoSR for reproducible builds ("main" is a moving target).
ARG TRIPOSR_REF=main
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 PORT=7860 ARO_DATA_DIR=/home/user/data

RUN apt-get update && apt-get install -y --no-install-recommends git build-essential libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

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
