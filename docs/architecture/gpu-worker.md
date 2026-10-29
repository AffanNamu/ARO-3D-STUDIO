# GPU worker (`aro_worker`)

Heavy image-to-3D engines (TRELLIS.2, TripoSG) need a CUDA toolchain and a 24 GB-class GPU that the Studio host usually does not
have. The worker runs them in their own environment and serves them over HTTP. The Studio side is
`aro_studio/engines/remote.py` (`RemoteEngine`); to the rest of the Studio a remote engine is an ordinary `ImageTo3DEngine`.

**Status:** the protocol, authentication, queue, cancellation, checksum check and Studio integration are tested with a procedural
test double (`tests/test_remote_engine.py`; the double is labelled NOT AI everywhere). The TRELLIS.2 and TripoSG plug-ins and the
install script were written from the upstream READMEs and **have not been run on a GPU**; expect to adjust them on the first run.

## What you need

* A machine with an NVIDIA GPU of **at least 24 GB** for TRELLIS.2 (about 8 GB for TripoSG), a current NVIDIA driver, Ubuntu 22.04
  or a container host, and the CUDA 12.4 toolkit (`nvcc`) if you install without Docker.
* A Hugging Face account that has accepted the licence of the gated DINOv3 model used by TRELLIS.2 conditioning, and a read token.
* Your own reading of the model-card licences of the weights you intend to use (the Studio refuses to run an engine whose licence is
  not attested, see "Licences").

## Start the worker

Without Docker (on the GPU host):

```bash
git clone <this repository> && cd ARO-3D-STUDIO
worker/install_engines.sh trellis2,triposg          # compiles CUDA extensions: allow a while; prints the exports to set
export HF_TOKEN=<your Hugging Face read token>
export ARO_WORKER_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')   # keep it secret
export ATTN_BACKEND=xformers PYTHONPATH=/opt/TRELLIS.2 TRIPOSG_DIR=/opt/TripoSG             # the install script prints these
source /opt/aro-worker-venv/bin/activate
python -m aro_worker --engines trellis2,triposg --port 8000
```

With Docker (`--gpus all` needs the NVIDIA container toolkit): see the header of `worker/Dockerfile`.

Smoke the worker with no model at all: `python -m aro_worker --engines fake --port 8000` serves a procedural test double that is
labelled NOT AI in its name. Never use it for assets.

## Connect the Studio

```bash
export ARO_WORKER_URL=http://<gpu-host>:8000
export ARO_WORKER_TOKEN=<the same token>
export ARO_WORKER_ENGINES=trellis2,triposg            # default
export ARO_VERIFIED_MODEL_LICENSES=trellis2,triposg   # ONLY after you read the model cards (see below)
```

The Generation page then lists the engines (TripoSR, TRELLIS.2, TripoSG). An engine that cannot run says why: worker unreachable,
token rejected, engine missing, GPU too small, package not importable, licence not attested. Pick one and use "Convert to 3D" as
before.

Use the worker over a trusted network or behind TLS; it is protected only by the bearer token.

## First real measurement (the open item)

On the GPU host, with the worker running:

```bash
python scripts/engine_bakeoff.py --worker-url http://127.0.0.1:8000 --token "$ARO_WORKER_TOKEN" \
  --engines trellis2,triposg --verified-licences trellis2,triposg \
  --case "ARO 480 Truck at Golden Hour.png:heavy_truck:7.0" --case "Premium Blue SUV Studio Render.png:car:4.5" \
  --preset STANDARD --out bakeoff/
zip -r bakeoff.zip bakeoff/
```

`--verified-licences` is your attestation, exactly like `ARO_VERIFIED_MODEL_LICENSES`; without it the run is refused by the licence gate.
Real lengths in the `--case` suffix (metres) are optional; without them the prepared model keeps a 1 m placeholder and says so.
The output (raw GLB as the engine returned it with its SHA-256, prepared GLB, `fidelity.json`, an inspection sheet per run, and
`bakeoff-summary.md`) is what the next step needs. Visual quality stays PENDING until a person has looked at the sheets.

### Google Colab (free T4): the lab notebook

`notebooks/aro_engine_lab_colab.ipynb` does all of the above in a Colab runtime: it builds an isolated Python 3.10 environment with `uv`
(`scripts/lab_bootstrap.py setup`), starts the worker on `127.0.0.1`, uploads your images, runs TripoSG (and, only if you switch it on,
the evaluation-only Hunyuan3D-2 mini) through the Studio, prints the table with the earlier TripoSR numbers for the same images and
packages the evidence. A T4 cannot run TRELLIS.2 (24 GB class), so it is not offered there. The CPU marching-cubes stand-in replaces
TripoSG's `diso` CUDA extension, so no compiler is needed.

**A cell that stops (`^C`).** Colab can interrupt a running cell (stop button, `Ctrl+M I`, a reconnect), and a plain `!python ...` cell dies
with it. So the bake-off runs *detached* (`lab_notebook.run_detached`): its own process, `/content/lab/bakeoff.log`, an exit-code file; the
cell only follows the log, and running it again re-attaches instead of starting a second GPU run. The worker keeps every finished job's raw
GLB for an hour in `/content/lab/worker-jobs`, and the bake-off copies the raw mesh out before it deletes its working folder, so an
interrupted run reports `INTERRUPTED (SIGINT, not an engine fault)` and still leaves `raw_output.glb`. Section 11 of the notebook
(`lab_notebook.diagnose`, `rescue_raw_meshes`) prints what happened on the VM and downloads the raw meshes. Exit code 130 means an interrupt
signal reached the run; an out-of-memory kill would instead show up in the kernel log lines `diagnose` prints.

### No GPU of your own: try a hosted demo first

If you can open a hosted TRELLIS.2 demo (for example a Hugging Face Space from Microsoft; I could not confirm one from the authoring
sandbox, so check the project's README), upload the truck and the car image there and download the GLBs. They can be prepared and
scored here without any GPU:

```bash
python scripts/reprepare_raw_mesh.py --raw trellis2-truck.glb --name "ARO 480 truck" --category heavy_truck \
       --length-m 7.0 --up +Y --out out/
python scripts/score_model.py --model out/improved-prepared.glb --reference "ARO 480 Truck at Golden Hour.png" \
       --category heavy_truck --label trellis2-hosted-truck --out out/
```

`--up +Y` matters: the script's default `+Z` is TripoSR's frame, glTF files from other engines are normally `+Y` up. Note the source
("hosted demo, not our worker") when you send the files; the hosted service's own terms apply to its outputs. The check of the
orientation is the six-view sheet.

## Protocol 1

All calls except `/ping` need `Authorization: Bearer <token>`.

| Call | Meaning |
|---|---|
| `GET /ping` | liveness and protocol number; no secrets |
| `GET /v1/engines` | per engine: id, name, version (the revision that actually ran), licence claim, availability and the exact reasons it is not available, presets, warnings; plus GPU name and memory |
| `POST /v1/generate` | multipart: `image` (RGBA cut-out), `engine`, `settings` (JSON). `202 {job_id}`. `409` engine unavailable, `404` unknown engine, `413` too large, `422` unreadable image |
| `GET /v1/jobs/{id}` | state (`queued` / `running` / `done` / `failed` / `cancelled`), progress, message, queue position, error, details (seconds, peak VRAM, engine version) |
| `DELETE /v1/jobs/{id}` | cancel; a running job stops between stages |
| `GET /v1/jobs/{id}/result` | the GLB with `X-ARO-SHA256`; the Studio verifies it and keeps the file untouched as the raw version |

Rules the code enforces:

* One GPU job at a time; one model resident at a time (the previous one is unloaded first).
* A failed engine returns its error verbatim (GPU out of memory is called out); **no fallback geometry is ever produced**.
* The input must be a matted cut-out with real transparency (`require_cutout`). The upstream pipelines would otherwise run their own
  background-removal models, whose licences are non-commercial. The worker never loads them.
* The licence of every remote engine comes from the Studio's own table (`engines/remote.py::KNOWN`), never from the worker's reply.

## Licences

Both engines' **code** is MIT. Their **weights** licences were not readable from the authoring sandbox, so the Studio records them as
`claimed`. Before production: open the model cards (TRELLIS.2: `huggingface.co/microsoft/TRELLIS.2-4B`; TripoSG:
`huggingface.co/VAST-AI/TripoSG`), confirm commercial use of weights **and outputs**, then set `ARO_VERIFIED_MODEL_LICENSES`.
Things the install script deliberately avoids: `nvdiffrec` (non-commercial) and BRIA RMBG (non-commercial). DINOv3 is gated and
must be accepted individually. Details and the Hunyuan3D caution: `docs/architecture/product-reassessment.md` section 4.

## Adding another engine

Implement `aro_worker.engines.base.WorkerEngine` (`available`, `presets`, `load`, `unload`, `generate`), register its name in
`aro_worker/__main__.py::build_engines`, add its licence record to `aro_studio/engines/remote.py::KNOWN`, then add a row to the
bake-off. Heavy imports belong inside methods so the worker starts (and reports why an engine is unavailable) without them.
