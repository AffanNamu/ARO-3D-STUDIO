"""CPU self-test of the BUILT worker image, run by .github/workflows/worker-image.yml before the image is pushed.

    docker run --rm -v "$PWD/worker/runpod/selftest.py:/selftest.py:ro" aro-worker python /selftest.py

It proves what can be proven without a GPU, so a broken image fails for free on GitHub instead of on paid GPU time:

1. the pinned TripoSG weights are in the image, complete, and loadable as safetensors headers;
2. the TripoSG code checkout and its Python dependencies are present (the engine's only complaint must be "no CUDA GPU");
3. the U^2-Net matting model is baked in and cuts a subject out of an image without any network access;
4. one complete job runs through the REAL RunPod handler and the REAL Studio pipeline in direct (inline) mode, with the labelled test-double
   engine standing in for the GPU model. Its result is stamped ``test_double: true`` and is never presented as AI output.

What it does NOT prove: that TripoSG produces a good mesh. That needs the GPU, and is the first real generation on the endpoint.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import struct
import sys
import time
import uuid
from pathlib import Path

from PIL import Image, ImageDraw

WEIGHTS = Path(os.environ.get("ARO_WORKER_CACHE", "/models")) / "TripoSG"
EXPECTED = {  # file -> minimum bytes, from the Hugging Face tree at the pinned revision (read 2026-11-23)
    "image_encoder_dinov2/model.safetensors": 1_200_000_000,
    "transformer/diffusion_pytorch_model.safetensors": 5_700_000_000,
    "vae/diffusion_pytorch_model.safetensors": 950_000_000,
}
results: dict[str, object] = {}


def check(name: str, ok: bool, detail: object) -> None:
    results[name] = {"ok": ok, "detail": detail}
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}", flush=True)


def safetensors_tensor_count(path: Path) -> int:
    with path.open("rb") as f:
        (n,) = struct.unpack("<Q", f.read(8))
        header = json.loads(f.read(n))
    return sum(1 for k in header if k != "__metadata__")


def synthetic_vehicle() -> bytes:
    """A flat, clearly separated subject on a plain background: enough for matting and the pipeline, obviously not a real photo."""
    img = Image.new("RGB", (768, 512), (236, 238, 242))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((120, 170, 560, 330), radius=24, fill=(30, 40, 60))  # body
    d.rounded_rectangle((520, 120, 660, 330), radius=18, fill=(40, 52, 78))  # cab
    d.rectangle((560, 140, 640, 200), fill=(150, 190, 220))  # window
    for x in (200, 330, 590):
        d.ellipse((x - 48, 290, x + 48, 386), fill=(15, 15, 15))
        d.ellipse((x - 20, 318, x + 20, 358), fill=(120, 120, 125))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def check_weights() -> None:
    for rel, minimum in EXPECTED.items():
        p = WEIGHTS / rel
        ok = p.is_file() and p.stat().st_size >= minimum
        detail = (
            f"{p.stat().st_size / 1e9:.2f} GB, {safetensors_tensor_count(p)} tensors"
            if ok
            else f"missing or short: {p}"
        )
        check(f"weights {rel}", ok, detail)
    check("weights model_index.json", (WEIGHTS / "model_index.json").is_file(), str(WEIGHTS / "model_index.json"))


def check_engine() -> None:
    from aro_worker.engines.triposg import TripoSGEngine, ensure_diso

    available, reasons = TripoSGEngine().available()
    only_gpu = all("CUDA GPU" in r for r in reasons)
    check("triposg checkout + packages", only_gpu, reasons or "available")
    check("marching cubes", True, ensure_diso())
    from triposg.pipelines.pipeline_triposg import TripoSGPipeline  # noqa: F401  - the import the engine's load() makes

    check("triposg pipeline import", True, "triposg.pipelines.pipeline_triposg")


def check_matting(image: bytes) -> None:
    import numpy as np
    import rembg

    t = time.time()
    cut = rembg.remove(
        Image.open(io.BytesIO(image)), session=rembg.new_session(os.environ.get("ARO_REMBG_MODEL", "u2net"))
    )
    alpha = np.asarray(cut.convert("RGBA"))[:, :, 3]
    share = float((alpha > 128).mean())
    check(
        "u2net matting (offline)",
        0.05 < share < 0.6,
        f"subject covers {share:.0%} of the frame, {time.time() - t:.1f}s",
    )


def check_job(image: bytes) -> None:
    """One job through the real handler and the real Studio pipeline, inline mode, with the labelled test double."""
    from aro_worker.__main__ import build_engines
    from aro_worker.runpod_handler import Deps, HandlerConfig, handle

    cfg = HandlerConfig(
        allowed_engines=("fake",),
        allow_test_double=True,
        verified_licenses="fake",
        allow_inline=True,
        job_timeout_s=600,
    )
    deps = Deps(cfg, engine_factory=lambda name: build_engines([name])[0])
    from aro_worker.engines.fake import FakeEngine

    # the dev stack's setting: boxes the Studio's smoothing does not collapse
    deps._engines["fake"] = FakeEngine(detail=3)
    payload = {
        "schema_version": 1,
        "job_id": str(uuid.uuid4()),
        "kind": "image_to_3d",
        "engine": "fake",
        "image": {
            "data_b64": base64.b64encode(image).decode(),
            "sha256": hashlib.sha256(image).hexdigest(),
            "bytes": len(image),
            "content_type": "image/png",
        },
        "settings": {"preset": "STANDARD", "category": "heavy_truck", "length_m": 6.9},
        "outputs": "inline",
        "limits": {"max_glb_bytes": 150_000_000},
    }
    t = time.time()
    out = handle({"id": "selftest", "input": payload}, deps)
    if "error" in out:
        check("handler job (test double)", False, json.loads(out["error"]))
    else:
        inline = out.get("inline_files", {})
        declared = {f["role"]: f for f in out.get("files", [])}
        intact = all(
            role in declared and hashlib.sha256(base64.b64decode(b64)).hexdigest() == declared[role]["sha256"]
            for role, b64 in inline.items()
        )
        ok = bool(out.get("ok")) and out["engine"]["test_double"] is True and "glb" in inline and intact
        check(
            "handler job (test double)",
            ok,
            {
                "seconds": round(time.time() - t, 1),
                "files": sorted(inline),
                "glb_bytes": declared.get("glb", {}).get("bytes"),
                "engine": out["engine"],
                "checks": {k: (out.get("validation") or {}).get(k) for k in ("status", "overall")},
            },
        )


def main() -> int:
    check_weights()
    check_engine()
    image = synthetic_vehicle()
    check_matting(image)
    check_job(image)
    failed = [k for k, v in results.items() if not v["ok"]]  # type: ignore[index]
    print(json.dumps({"selftest": "PASS" if not failed else "FAIL", "failed": failed}), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
