"""Owner-run proof that the real chain works: R2 -> RunPod endpoint -> worker -> R2 -> output gate. No database, no Supabase.

    python -m aro_cloud.smoke --image path/to/concept.png [--preset DRAFT] [--category car] [--keep]

It needs ONLY the environment you give the API for storage and RunPod (ARO_R2_*, ARO_RUNPOD_API_KEY, ARO_RUNPOD_ENDPOINT_ID). It spends GPU
time on your RunPod account (a cold start plus one generation: a few cents), so it is never run by CI or by the assistant.

The evidence it prints (and writes with --out) says ``ai_inference: true`` only when the worker reports a non-test-double engine AND the
downloaded GLB passed the output gate. Secrets and signed URLs are never printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from aro_cloud import keys
from aro_cloud.envfile import load_env_file
from aro_cloud.orchestrator import Orchestrator
from aro_cloud.output_gate import validate_glb
from aro_cloud.providers.base import ModelProvider, ProviderUnavailable
from aro_cloud.schemas import GenerationSettings, WorkerResult
from aro_cloud.settings import CloudSettings
from aro_cloud.storage import ObjectStore

CONTENT_TYPES = {b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg", b"RIFF": "image/webp"}


def run_endpoint_smoke(
    store: ObjectStore,
    provider: ModelProvider,
    settings: CloudSettings,
    image: bytes,
    *,
    engine: str = "triposg",
    preset: str = "DRAFT",
    category: str = "car",
    timeout_s: int = 1200,
    poll_s: float = 5.0,
    keep: bool = False,
    sleep: Any = time.sleep,
) -> dict[str, Any]:
    ctype = next((v for k, v in CONTENT_TYPES.items() if image.startswith(k)), "")
    if not ctype:
        raise SystemExit("The image must be a PNG, JPEG or WebP file.")
    owner, upload_id, job_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[ctype]
    in_key = keys.upload_key(owner, upload_id, ext)
    store.put_bytes(in_key, image, ctype)
    orch = Orchestrator(None, store, provider, settings)  # type: ignore[arg-type]  # only worker_input() is used: no database
    job = {
        "owner_id": str(owner),
        "job_id": str(job_id),
        "request": {
            "kind": "image_to_3d",
            "engine": engine,
            "settings": GenerationSettings(preset=preset, category=category).model_dump(mode="json"),
        },
    }
    payload = orch.worker_input(
        job, {"r2_key": in_key, "sha256": hashlib.sha256(image).hexdigest(), "bytes": len(image), "content_type": ctype}
    )
    ev: dict[str, Any] = {
        "engine_requested": engine,
        "preset": preset,
        "image_bytes": len(image),
        "ai_inference": False,
    }
    t0 = time.time()
    created: list[str] = [in_key] + [keys.job_key(owner, job_id, r) for r in keys.JOB_FILES]
    try:
        run_id = provider.submit(payload, execution_timeout_s=settings.execution_timeout_s, ttl_s=timeout_s)
        ev["run_id_suffix"] = run_id[-6:]
        status = None
        while time.time() - t0 < timeout_s:
            try:
                status = provider.status(run_id)
            except ProviderUnavailable as e:
                ev.setdefault("status_hiccups", []).append(str(e)[:80])
                sleep(poll_s)
                continue
            if status.state in ("succeeded", "failed", "cancelled", "timed_out"):
                break
            sleep(poll_s)
        else:
            provider.cancel(run_id)
            ev.update(status="FAIL", reason=f"no result within {timeout_s}s; the run was cancelled")
            return ev
        assert status is not None
        ev["provider_state"] = status.state
        ev["provider_execution_ms"] = status.execution_ms
        ev["provider_queue_delay_ms"] = status.delay_ms
        ev["wall_seconds"] = round(time.time() - t0, 1)
        if status.state != "succeeded":
            ev.update(status="FAIL", reason=(status.error or status.state)[:400])
            return ev
        try:
            result = WorkerResult.model_validate(status.output or {})
        except ValueError:
            ev.update(status="FAIL", reason="the worker's output is not a WorkerResult")
            return ev
        glb_entry = next((f for f in result.files if f.role == "glb"), None)
        if not result.ok or glb_entry is None or result.engine is None:
            ev.update(status="FAIL", reason="the worker reported no GLB")
            return ev
        data = store.get_bytes(keys.job_key(owner, job_id, "glb"), settings.max_glb_mb * 1_000_000)
        gate = validate_glb(
            data,
            claimed_sha256=glb_entry.sha256,
            max_bytes=settings.max_glb_mb * 1_000_000,
            engine_is_test_double=result.engine.test_double,
            allow_test_double=False,
        )
        marker_ok = store.head(keys.job_key(owner, job_id, "result")) is not None
        ev.update(
            engine_reported={
                "id": result.engine.id,
                "version": result.engine.version,
                "test_double": result.engine.test_double,
            },
            gate_ok=gate.ok,
            gate_reasons=gate.reasons,
            gate_stats=gate.stats,
            glb_sha256=gate.sha256,
            completion_marker_written=marker_ok,
            worker_stats={k: v for k, v in result.stats.items() if k in ("total_s", "pipeline_s", "gpu")},
            ai_inference=bool(gate.ok and not result.engine.test_double and marker_ok),
        )
        ev["status"] = "PASS" if ev["ai_inference"] else "FAIL"
        if not gate.ok:
            ev["reason"] = "; ".join(gate.reasons)
        if keep and gate.ok:
            (Path.cwd() / f"smoke-{job_id}.glb").write_bytes(data)
            ev["glb_saved_as"] = f"smoke-{job_id}.glb"
        return ev
    finally:
        if not keep:
            for k in created:
                try:
                    store.delete(k)
                except Exception:  # noqa: BLE001, S110 - cleanup is best effort
                    pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", help="private file with ARO_* settings (see aro_cloud/envfile.py)")
    ap.add_argument("--image", type=Path, required=True)
    ap.add_argument("--engine", default="triposg")
    ap.add_argument("--preset", default="DRAFT", choices=["DRAFT", "STANDARD", "HIGH"])
    ap.add_argument("--category", default="car")
    ap.add_argument("--timeout", type=int, default=1200)
    ap.add_argument("--keep", action="store_true", help="keep the objects in R2 and save the GLB next to you")
    ap.add_argument("--out", type=Path, help="write the evidence JSON here")
    a = ap.parse_args(argv)
    load_env_file(a.env_file)
    from aro_cloud.settings import load_settings
    from aro_cloud.wiring import build_provider, build_store

    s = load_settings()
    evidence = run_endpoint_smoke(
        build_store(s),
        build_provider(s),
        s,
        a.image.read_bytes(),
        engine=a.engine,
        preset=a.preset,
        category=a.category,
        timeout_s=a.timeout,
        keep=a.keep,
    )
    text = json.dumps(evidence, indent=2, default=str)
    print(text)
    if a.out:
        a.out.write_text(text + "\n")
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
