"""The shortest honest proof that the AI works: one image straight to your RunPod endpoint, the finished model straight back.

    python -m aro_cloud.direct_test --env-file ~/aro-secrets/aro.env --image truck.png \\
        --category heavy_truck --length 6.9 --preset STANDARD --out first_run

Needs only ARO_RUNPOD_API_KEY and ARO_RUNPOD_ENDPOINT_ID, and the endpoint must allow inline transfers (ARO_WORKER_ALLOW_INLINE=1).
No database, no Supabase, no R2: the image travels inside the job (up to 6 MB) and the model comes back inside the result (RunPod keeps
results up to ~10 MB for 30 minutes). It spends GPU time on your account, so it is never run by CI.

Writes ``model.glb`` (the game-ready model), ``thumbnail.png``, ``report.json`` and ``evidence.json``. ``ai_inference`` in the evidence
is true only when the worker reports a real (non-test-double) engine AND the returned GLB passes the same output gate the platform uses.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from aro_cloud.envfile import load_env_file
from aro_cloud.output_gate import validate_glb
from aro_cloud.providers.base import ModelProvider, ProviderAmbiguous, ProviderRejected, ProviderUnavailable
from aro_cloud.schemas import INLINE_IMAGE_MAX_BYTES, GenerationSettings, WorkerResult

CONTENT_TYPES = {b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg", b"RIFF": "image/webp"}
EXT = {"glb": "model.glb", "thumbnail": "thumbnail.png", "report": "report.json", "raw_mesh": "raw_engine_output.glb"}


def build_input(
    image: bytes, *, engine: str, preset: str, category: str, length_m: float | None, seed: int | None
) -> dict[str, Any]:
    ctype = next((v for k, v in CONTENT_TYPES.items() if image.startswith(k)), "")
    if not ctype:
        raise SystemExit("The image must be a PNG, JPEG or WebP file.")
    if len(image) > INLINE_IMAGE_MAX_BYTES:
        raise SystemExit(
            f"The image is {len(image) / 1e6:.1f} MB; a direct test takes up to {INLINE_IMAGE_MAX_BYTES / 1e6:.0f} MB. Save it smaller (e.g. JPEG)."
        )
    settings = GenerationSettings(preset=preset, category=category, length_m=length_m, seed=seed)
    return {
        "schema_version": 1,
        "job_id": str(uuid.uuid4()),
        "kind": "image_to_3d",
        "engine": engine,
        "image": {
            "data_b64": base64.b64encode(image).decode(),
            "sha256": hashlib.sha256(image).hexdigest(),
            "bytes": len(image),
            "content_type": ctype,
        },
        "settings": settings.model_dump(mode="json"),
        "outputs": "inline",
        "limits": {"max_glb_bytes": 150_000_000},
    }


def run(
    provider: ModelProvider,
    image: bytes,
    out: Path,
    *,
    engine: str = "triposg",
    preset: str = "STANDARD",
    category: str = "other",
    length_m: float | None = None,
    seed: int | None = None,
    timeout_s: int = 2400,
    execution_timeout_s: int = 900,
    poll_s: float = 5.0,
    sleep: Any = time.sleep,
    say: Any = print,
) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    payload = build_input(image, engine=engine, preset=preset, category=category, length_m=length_m, seed=seed)
    ev: dict[str, Any] = {
        "engine_requested": engine,
        "preset": preset,
        "category": category,
        "length_m": length_m,
        "ai_inference": False,
        "status": "FAIL",
    }
    t0 = time.time()
    try:
        run_id = provider.submit(payload, execution_timeout_s=execution_timeout_s, ttl_s=timeout_s)
    except (ProviderRejected, ProviderAmbiguous) as e:
        ev["reason"] = f"the endpoint did not accept the job: {e}"
        return _finish(ev, out)
    ev["run_id_suffix"] = run_id[-6:]
    say(f"submitted (run ...{run_id[-6:]}); the first run includes a cold start and can take many minutes")
    status = None
    last = ""
    while time.time() - t0 < timeout_s:
        try:
            status = provider.status(run_id)
        except ProviderUnavailable:
            sleep(poll_s)
            continue
        if status.state != last:
            say(f"  {int(time.time() - t0)}s: {status.state}")
            last = status.state
        if status.state in ("succeeded", "failed", "cancelled", "timed_out"):
            break
        sleep(poll_s)
    else:
        provider.cancel(run_id)
        ev["reason"] = f"no result within {timeout_s}s; the job was cancelled"
        return _finish(ev, out)
    assert status is not None
    ev.update(
        provider_state=status.state,
        execution_ms=status.execution_ms,
        queue_delay_ms=status.delay_ms,
        wall_seconds=round(time.time() - t0, 1),
    )
    if status.state != "succeeded":
        ev["reason"] = (status.error or status.state)[:500]
        return _finish(ev, out)
    raw = status.output or {}
    inline = raw.get("inline_files") if isinstance(raw, dict) else None
    try:
        result = WorkerResult.model_validate(raw)
    except ValueError:
        result = None
    if result is None or not result.ok or result.engine is None or not isinstance(inline, dict) or "glb" not in inline:
        ev["reason"] = "the worker's answer has no inline model (is ARO_WORKER_ALLOW_INLINE=1 set on the endpoint?)"
        return _finish(ev, out)
    declared = {f.role: f for f in result.files}
    for role, b64 in inline.items():
        if role not in EXT:
            continue
        data = base64.b64decode(b64)
        f = declared.get(role)
        if f is None or len(data) != f.bytes or hashlib.sha256(data).hexdigest() != f.sha256:
            ev["reason"] = f"the returned {role} does not match what the worker declared"
            return _finish(ev, out)
        (out / EXT[role]).write_bytes(data)
    glb = (out / EXT["glb"]).read_bytes()
    gate = validate_glb(
        glb,
        claimed_sha256=declared["glb"].sha256,
        max_bytes=150_000_000,
        engine_is_test_double=result.engine.test_double,
        allow_test_double=False,
    )
    facts = (
        gate if gate.stats else validate_glb(glb, claimed_sha256=None, max_bytes=150_000_000)
    )  # the model's facts even when the verdict is a refusal
    ev.update(
        engine_reported={
            "id": result.engine.id,
            "version": result.engine.version,
            "test_double": result.engine.test_double,
        },
        gate_ok=gate.ok,
        gate_reasons=gate.reasons,
        model=facts.stats,
        glb_sha256=gate.sha256,
        files_written=sorted(p.name for p in out.iterdir() if p.name != "evidence.json"),
        not_returned=raw.get("not_returned", []),
        worker_stats={k: v for k, v in result.stats.items() if k in ("total_s", "pipeline_s", "gpu")},
        studio_checks={
            k: (result.validation or {}).get(k) for k in ("status", "overall", "critical_failures", "major_failures")
        },
        ai_inference=bool(gate.ok and not result.engine.test_double),
    )
    ev["status"] = "PASS" if ev["ai_inference"] else "FAIL"
    if not gate.ok:
        ev["reason"] = "; ".join(gate.reasons)
    return _finish(ev, out)


def _finish(ev: dict[str, Any], out: Path) -> dict[str, Any]:
    (out / "evidence.json").write_text(json.dumps(ev, indent=2, default=str) + "\n")
    return ev


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", help="private file with ARO_* settings")
    ap.add_argument("--image", type=Path, required=True)
    ap.add_argument("--engine", default="triposg")
    ap.add_argument("--preset", default="STANDARD", choices=["DRAFT", "STANDARD", "HIGH"])
    ap.add_argument("--category", default="other")
    ap.add_argument("--length", type=float, default=None, help="real length in metres, e.g. 6.9")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument(
        "--timeout", type=int, default=2400, help="seconds to wait in total (the first run includes a cold start)"
    )
    ap.add_argument("--out", type=Path, default=Path("first_run"))
    a = ap.parse_args(argv)
    load_env_file(a.env_file)
    from aro_cloud.settings import CloudSettings
    from aro_cloud.wiring import build_provider

    s = CloudSettings()
    ev = run(
        build_provider(s),
        a.image.read_bytes(),
        a.out,
        engine=a.engine,
        preset=a.preset,
        category=a.category,
        length_m=a.length,
        seed=a.seed,
        timeout_s=a.timeout,
        execution_timeout_s=s.execution_timeout_s,
    )
    print(json.dumps(ev, indent=2, default=str))
    print(f"\nfiles in {a.out}/" + (" - open model.glb in any glTF viewer" if ev["status"] == "PASS" else ""))
    return 0 if ev["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
