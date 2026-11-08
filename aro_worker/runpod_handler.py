"""RunPod Serverless handler: one image in, one validated, game-ready GLB out, written to storage through pre-signed URLs.

    input  (aro_cloud.schemas.WorkerInput): job id, engine, image GET url + sha256, settings, one PUT url per output file
    output (aro_cloud.schemas.WorkerResult): ok, engine {id, version, test_double}, files [{role, bytes, sha256}], stats
    failure: {"error": "<json {code, message, retryable}>"}   (RunPod marks a run FAILED when the handler returns an "error" key)

What this process is allowed to be trusted with, and what it is not:

* It holds NO storage credentials: it can read exactly one object and write exactly the fixed output keys, through URLs the API signed.
* URLs are checked before use: https only, no credentials in the URL, host on an allow-list, no redirects, and the address must be public.
* The image is verified against the SHA-256 the API recorded when it validated the upload.
* Engines are gated: only ``ARO_WORKER_ENGINES`` (default ``triposg``); evaluation-only engines need ``ARO_WORKER_EVALUATION_MODE=1``;
  the labelled test double needs ``ARO_WORKER_ALLOW_TEST_DOUBLE=1`` and is stamped ``test_double: true`` in its result. The Studio's own
  licence gate (``ARO_VERIFIED_MODEL_LICENSES``, the deployer's attestation) still applies inside the pipeline.
* ``result.json`` is written LAST. If RunPod's record of the run expires (30 minutes) the API still finds the finished job through it.
* Nothing is substituted: if the model fails, the run fails.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from aro_cloud.keys import JOB_FILES
from aro_cloud.schemas import WorkerInput
from aro_worker.engines.base import WorkerEngine, gpu_info
from aro_worker.headless import PipelineError, PipelineOutput, run_pipeline
from aro_worker.inprocess import InProcessEngine

log = logging.getLogger("aro_worker.runpod")

SCHEMA_VERSION = 1
EVALUATION_ONLY = {
    "trellis2",
    "hunyuan3d",
}  # licences / dependencies that do not allow commercial serving (docs/cto/05-models-and-licensing.md)
TEST_DOUBLES = {"fake"}
DEFAULT_HOSTS = (".r2.cloudflarestorage.com",)
EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
WRITE_ORDER = ("raw_mesh", "glb", "thumbnail", "report")  # then result.json, last


class HandlerError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable


@dataclass
class HandlerConfig:
    allowed_engines: tuple[str, ...] = ("triposg",)
    evaluation_mode: bool = False
    allow_test_double: bool = False
    verified_licenses: str = ""
    allowed_hosts: tuple[str, ...] = DEFAULT_HOSTS
    allow_insecure_urls: bool = False  # tests only: http and loopback addresses
    job_timeout_s: int = 840
    workdir: Path | None = None

    @classmethod
    def from_env(cls) -> HandlerConfig:
        def csv(name: str, default: str) -> tuple[str, ...]:
            return tuple(x.strip() for x in os.environ.get(name, default).split(",") if x.strip())

        return cls(
            allowed_engines=csv("ARO_WORKER_ENGINES", "triposg"),
            evaluation_mode=os.environ.get("ARO_WORKER_EVALUATION_MODE") == "1",
            allow_test_double=os.environ.get("ARO_WORKER_ALLOW_TEST_DOUBLE") == "1",
            verified_licenses=os.environ.get("ARO_VERIFIED_MODEL_LICENSES", ""),
            allowed_hosts=csv("ARO_WORKER_ALLOWED_HOSTS", ",".join(DEFAULT_HOSTS)),
            allow_insecure_urls=os.environ.get("ARO_WORKER_ALLOW_INSECURE_URLS") == "1",
            job_timeout_s=int(os.environ.get("ARO_WORKER_JOB_TIMEOUT_S", "840")),
            workdir=Path(os.environ["ARO_WORKER_WORKDIR"]) if os.environ.get("ARO_WORKER_WORKDIR") else None,
        )


@dataclass
class Deps:
    config: HandlerConfig
    engine_factory: Callable[[str], WorkerEngine]
    http: httpx.Client = field(
        default_factory=lambda: httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=False)
    )
    pipeline: Callable[..., PipelineOutput] = run_pipeline
    sleep: Callable[[float], None] = time.sleep
    _engines: dict[str, WorkerEngine] = field(default_factory=dict)

    def engine(self, engine_id: str) -> WorkerEngine:
        if engine_id not in self._engines:
            self._engines[engine_id] = self.engine_factory(engine_id)
        return self._engines[engine_id]


# ============================================================================================================== entry point
def handle(event: dict[str, Any], deps: Deps, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """RunPod calls this once per job. Never raises: every failure is returned in RunPod's ``{"error": ...}`` shape."""
    t0 = time.time()
    try:
        return _run(event, deps, progress or (lambda _m: None), t0)
    except HandlerError as e:
        log.warning("job failed: %s (%s)", e.code, e.message)
        return _failure(e.code, e.message, e.retryable)
    except Exception as e:  # noqa: BLE001 - the user gets a stable code; the traceback stays in the worker log
        log.exception("unexpected failure")
        return _failure("internal_error", f"The GPU worker hit an unexpected error ({type(e).__name__}).", False)


def _failure(code: str, message: str, retryable: bool) -> dict[str, Any]:
    return {
        "error": json.dumps({"code": code, "message": message[:300], "retryable": retryable}, separators=(",", ":"))
    }


def _run(event: dict[str, Any], deps: Deps, progress: Callable[[str], None], t0: float) -> dict[str, Any]:
    cfg = deps.config
    spec = _parse(event)
    _check_engine(spec.engine, cfg)
    for role, o in spec.outputs.items():
        _check_url(o.put_url, cfg, f"output {role}")
    _check_url(spec.image.get_url, cfg, "input image")
    engine = deps.engine(spec.engine)

    progress("Downloading the image")
    image = _download(spec.image.get_url, spec.image.bytes, spec.image.sha256, deps)

    progress("Generating the 3D model")
    s = spec.settings
    try:
        out = deps.pipeline(
            engine,
            image,
            filename=f"input.{EXT[spec.image.content_type]}",
            category=s.category,
            preset=s.preset,
            seed=s.seed,
            target_triangles=s.target_faces,
            texture_resolution=s.texture_resolution,
            length_m=s.length_m,
            verified_licenses=cfg.verified_licenses,
            timeout_s=cfg.job_timeout_s,
            progress=lambda p, m: progress(f"{m} ({p:.0%})" if m else f"{p:.0%}"),
            workdir=cfg.workdir,
        )
    except PipelineError as e:
        raise _from_pipeline(e) from e

    progress("Saving the result")
    blobs: dict[str, bytes] = {"raw_mesh": out.raw_glb, "glb": out.prepared_glb}
    if out.thumbnail_png:
        blobs["thumbnail"] = out.thumbnail_png
    blobs["report"] = json.dumps(out.report, separators=(",", ":"), default=str).encode()
    limit = int(spec.limits.get("max_glb_bytes", 150_000_000))
    for role in ("raw_mesh", "glb"):
        if len(blobs[role]) > limit:
            raise HandlerError(
                "output_too_large",
                f"The generated {role.replace('_', ' ')} is {len(blobs[role]) / 1e6:.0f} MB, above the limit.",
            )
    files = []
    for role in WRITE_ORDER:
        if role in blobs:
            _upload(spec.outputs[role].put_url, blobs[role], spec.outputs[role].content_type, deps)
            files.append({"role": role, "bytes": len(blobs[role]), "sha256": hashlib.sha256(blobs[role]).hexdigest()})
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "engine": {"id": engine.id, "version": engine.version, "test_double": bool(engine.test_double)},
        "files": files,
        "stats": {"total_s": round(time.time() - t0, 2), "pipeline_s": round(out.seconds, 2), "gpu": gpu_info()},
        "validation": (out.report.get("validation") or {}),
    }
    _upload(
        spec.outputs["result"].put_url,
        json.dumps(result, separators=(",", ":"), default=str).encode(),
        spec.outputs["result"].content_type,
        deps,
    )
    return result


# ================================================================================================================ checks
def _parse(event: dict[str, Any]) -> WorkerInput:
    raw = event.get("input") if isinstance(event, dict) else None
    if not isinstance(raw, dict):
        raise HandlerError("invalid_input", "The job has no input.")
    try:
        return WorkerInput.model_validate(raw)
    except ValidationError as e:
        problems = "; ".join(
            f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}"[:80] for err in e.errors()[:4]
        )  # never echoes values (URLs are signed)
        raise HandlerError("invalid_input", f"The job input is not valid ({problems}).") from None


def _check_engine(engine: str, cfg: HandlerConfig) -> None:
    if engine in TEST_DOUBLES and not cfg.allow_test_double:
        raise HandlerError("engine_not_allowed", "This worker does not run test-double engines.")
    if engine in EVALUATION_ONLY and not cfg.evaluation_mode:
        raise HandlerError(
            "engine_not_allowed", f"The engine '{engine}' is evaluation-only and this worker is not in evaluation mode."
        )
    if engine not in cfg.allowed_engines:
        raise HandlerError("engine_not_allowed", f"This worker does not serve the engine '{engine}'.")


def _check_url(url: str, cfg: HandlerConfig, what: str) -> None:
    """Defence in depth: the URLs come from our own API, but a worker must never be steerable to fetch an arbitrary address."""
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if u.scheme != "https" and not (cfg.allow_insecure_urls and u.scheme == "http"):
        raise HandlerError("invalid_input", f"The {what} URL must use https.")
    if u.username or u.password or not host:
        raise HandlerError("invalid_input", f"The {what} URL is not acceptable.")
    if not any(host == h.lstrip(".") or host.endswith(h if h.startswith(".") else "." + h) for h in cfg.allowed_hosts):
        raise HandlerError("invalid_input", f"The {what} URL points outside the allowed storage hosts.")
    if cfg.allow_insecure_urls:
        return
    try:
        infos = socket.getaddrinfo(host, u.port or 443, proto=socket.IPPROTO_TCP)
    except OSError:
        raise HandlerError("download_failed", f"The {what} host could not be resolved.", retryable=True) from None
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise HandlerError("invalid_input", f"The {what} URL resolves to a non-public address.")


def _from_pipeline(e: PipelineError) -> HandlerError:
    """The Studio's error codes become stable worker codes. Messages about the user's own image are passed through; everything about the
    worker's configuration is generic for end users (the detail is in the worker log)."""
    log.warning("pipeline stopped: %s %s - %s | %s", e.state, e.code, e.message, e.recommended_action)
    code = e.code.lower()
    if e.code in ("INVALID_INPUT", "UNSUPPORTED_INPUT", "IMAGE_REJECTED") or e.state == "INVALID_INPUT":
        return HandlerError("invalid_input", e.message)
    if e.code in ("ENGINE_UNAVAILABLE", "LICENSE_NOT_VERIFIED") or e.state == "REJECTED":
        return HandlerError("engine_unavailable", "The GPU worker cannot run this model right now.", retryable=False)
    if e.code == "RESOURCE_LIMIT" or e.state == "RESOURCE_LIMIT":
        return HandlerError(
            "resource_limit", "The GPU ran out of memory for this image and settings. Try the Draft preset."
        )
    if e.code in ("JOB_TIMEOUT", "TIMEOUT") or e.state == "TIMEOUT":
        return HandlerError("pipeline_timeout", "Generation took longer than the worker's time limit.")
    if e.code == "MODEL_ERROR" or e.state == "MODEL_ERROR":
        return HandlerError("model_error", "The model could not produce a valid result from this image.")
    return HandlerError(
        code if code.isidentifier() else "pipeline_failed", "The 3D pipeline could not finish this image."
    )


# ============================================================================================================== transfers
def _download(url: str, expected_bytes: int, expected_sha: str, deps: Deps) -> bytes:
    last = "no attempt"
    for attempt in range(3):
        try:
            with deps.http.stream("GET", url) as r:
                if r.status_code in (403, 404):
                    raise HandlerError("download_failed", f"The image could not be fetched (HTTP {r.status_code}).")
                if r.status_code >= 500 or r.status_code == 429:
                    last = f"HTTP {r.status_code}"
                    raise httpx.TransportError(last)
                if r.status_code != 200:
                    raise HandlerError("download_failed", f"The image could not be fetched (HTTP {r.status_code}).")
                buf = bytearray()
                for chunk in r.iter_bytes():
                    buf.extend(chunk)
                    if len(buf) > expected_bytes:
                        raise HandlerError("invalid_input", "The image is larger than the API recorded.")
        except httpx.HTTPError as e:
            last = type(e).__name__
            deps.sleep(0.5 * 2**attempt)
            continue
        data = bytes(buf)
        if len(data) != expected_bytes or hashlib.sha256(data).hexdigest() != expected_sha:
            raise HandlerError("invalid_input", "The downloaded image does not match the one the API validated.")
        return data
    raise HandlerError("download_failed", f"The image could not be fetched ({last}).", retryable=True)


def _upload(url: str, data: bytes, content_type: str, deps: Deps) -> None:
    last = "no attempt"
    for attempt in range(4):
        try:
            r = deps.http.put(url, content=data, headers={"Content-Type": content_type})
        except httpx.HTTPError as e:
            last = type(e).__name__
        else:
            if r.status_code in (200, 201, 204):
                return
            if r.status_code < 500 and r.status_code != 429:
                raise HandlerError("upload_failed", f"Storage refused the result (HTTP {r.status_code}).")
            last = f"HTTP {r.status_code}"
        deps.sleep(0.5 * 2**attempt)
    raise HandlerError("upload_failed", f"The result could not be saved ({last}).", retryable=True)


# ================================================================================================================== main
def main() -> None:  # pragma: no cover - needs the RunPod SDK and a GPU
    import runpod  # MIT; only imported on the worker

    logging.basicConfig(
        level=os.environ.get("ARO_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    from aro_worker.__main__ import build_engines

    cfg = HandlerConfig.from_env()
    deps = Deps(cfg, engine_factory=lambda name: build_engines([name])[0])

    def handler(job: dict[str, Any]) -> dict[str, Any]:
        return handle(job, deps, progress=lambda m: runpod.serverless.progress_update(job, m))

    runpod.serverless.start({"handler": handler})


__all__ = ["Deps", "HandlerConfig", "HandlerError", "InProcessEngine", "JOB_FILES", "handle", "main"]

if __name__ == "__main__":  # pragma: no cover
    main()
