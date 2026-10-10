# Docker deployment — verified procedure

Evidence: `docs/acceptance/evidence/docker/` (build log, per-step results, HTTP suite). Reproduce with one command.

## Build and run

```bash
docker build -t aro-3d-studio .                                   # Python 3.11-slim, digest-pinned, non-root uid 1000
docker volume create aro-data
docker run -d --name aro -p 7860:7860 \
  --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
  --memory 2g --cpus 2 --pids-limit 256 \
  -v aro-data:/home/user/data \
  -e ARO_ACCESS_TOKEN="$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')" \
  aro-3d-studio
curl -s localhost:7860/api/health          # {"status":"ok",...}; also: docker inspect --format '{{.State.Health.Status}}' aro
```

* **Auth:** set `ARO_ACCESS_TOKEN` (the API refuses non-health requests without it; the token is never baked into the image).
  Without it the service starts unauthenticated; `/api/system` reports `auth_enabled: false`.
* **Storage:** everything lives in `/home/user/data` (SQLite, versions, exports, HF cache via `HF_HOME`). Mount a volume or it is
  ephemeral. With `--read-only` and no volume, give the data dir a `--tmpfs /home/user/data:uid=1000,gid=1000`, otherwise the
  service exits with `ARO_DATA_DIR … is not writable`.
* **Limits:** `ARO_MAX_UPLOAD_MB` (default 25), archive/zip-bomb and path-traversal protections are on by default; resource
  monitoring reads the container's cgroup limit, not the host's RAM.
* **Real model:** the default image has no torch/TripoSR. `docker build --build-arg WITH_TRIPOSR=1 …` adds the CPU/GPU stack;
  inference additionally needs a complete model lock (see `docs/verification/gpu-host-runbook.md`). Inference failure is handled as
  a job error (`MODEL_ERROR` / `RESOURCE_LIMIT`), verified by the HTTP suite with the engine unavailable.

## Verifying the image yourself

```bash
scripts/verify_docker.sh        # build → inspect → hardened run → 34 HTTP checks → persistence → 160 MB limit; exit 0 only if all pass
```

Restricted sandboxes (no registry TLS, no bridge networking) can pass
`DOCKER_BUILD_ARGS="--network host --build-arg PYTHON_IMAGE=<local base> …"` and `DOCKER_RUN_ARGS`; every such deviation is
written to the `caveats` field of `docker-verification.json` and shown in the acceptance report.

## What this does and does not show

Verified: clean dependency install (`pip check`), all modules import on 3.11, non-root, read-only rootfs, no secrets/proxy in
the image or its history, health + HEALTHCHECK, auth, upload cap, archive and traversal protections, pipeline + export inside the
container, data persistence across restart and container replacement, no OOM under 768 MB, startup under 160 MB.
Not verified: a deployment on Hugging Face Spaces itself, GPU images, multi-arch builds, TLS termination (put a reverse proxy in front).
