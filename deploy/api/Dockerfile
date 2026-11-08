# ARO API (aro_cloud) for Cloud Run or any container host. Build context = the repository root:
#   docker build -f deploy/api/Dockerfile -t aro-api .
#
# STATUS: NOT BUILT here (no Docker in the authoring sandbox). The same dependency set was installed into a clean virtualenv and every
# aro_cloud module imported from it; CI runs the tests on Python 3.10 and 3.12. Pin by digest, scan the image, then deploy.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONPATH=/app ARO_ENV=production
RUN useradd --system --uid 10001 --no-create-home app
WORKDIR /app
COPY requirements.txt requirements-cloud.txt ./
RUN pip install -r requirements.txt -r requirements-cloud.txt
COPY aro_studio ./aro_studio
COPY aro_cloud ./aro_cloud
USER 10001
EXPOSE 8080
# Configuration comes from the environment (docs/platform/owner-setup.md); the process refuses to start in production with anything missing.
CMD ["python", "-m", "aro_cloud"]
