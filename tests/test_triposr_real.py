"""REAL inference tests for the TripoSR engine.

These run only where the model can actually run (torch + the `tsr` package + weights + a verified licence) and are
opt-in:

    ARO_RUN_MODEL_TESTS=1 ARO_VERIFIED_MODEL_LICENSES=triposr pytest -m model -v

In any other environment they are SKIPPED - they are never replaced by a fake that "passes". See
docs/models/model-requirements.md for the full test strategy.
"""

from __future__ import annotations

import io
import os
import time

import numpy as np
import pytest
from PIL import Image

from aro_studio.config import Settings
from aro_studio.engines.base import GenerationRequest
from aro_studio.engines.triposr import TripoSREngine
from aro_studio.imaging.preprocess import PreprocessOptions, preprocess
from aro_studio.utils.render import render_asset_scene
from aro_studio.vehicles.titan480 import build_titan480

pytestmark = pytest.mark.model


def _device() -> str:
    from aro_studio.engines.manager import resolve_device

    return resolve_device(os.environ.get("ARO_DEVICE", "auto"))


@pytest.fixture(scope="module")
def engine():
    if os.environ.get("ARO_RUN_MODEL_TESTS") != "1":
        pytest.skip("set ARO_RUN_MODEL_TESTS=1 on a host with torch, tsr and the TripoSR weights")
    e = TripoSREngine(os.environ.get("ARO_TRIPOSR_MODEL_PATH", "stabilityai/TripoSR"))
    av = e.availability(_device())
    if not av.ok:
        pytest.skip("TripoSR cannot run here: " + "; ".join(av.reasons))
    if "triposr" not in Settings().verified_licenses:
        pytest.skip("weights licence not verified by the deployer (ARO_VERIFIED_MODEL_LICENSES=triposr)")
    yield e
    e.unload()


@pytest.fixture(scope="module")
def model_input():
    img = render_asset_scene(build_titan480(), azimuth_deg=40, elevation_deg=10, size=1024, background=(236, 236, 236))
    return preprocess(img, PreprocessOptions()).image


def test_model_loads_and_reports_load_time(engine):
    t0 = time.perf_counter()
    engine.load(_device())
    assert engine.is_loaded and time.perf_counter() - t0 > 0


def test_real_inference_returns_a_real_finite_mesh(engine, model_input, tmp_path):
    if not engine.is_loaded:
        engine.load(_device())
    out = engine.generate(
        GenerationRequest(
            image=model_input, settings=engine.normalize_settings({"preset": "LOW_RESOURCE"}), workdir=tmp_path
        )
    )
    assert len(out.mesh.faces) > 1000 and np.isfinite(np.asarray(out.mesh.vertices)).all()
    assert out.raw_file.is_file() and out.raw_file.stat().st_size > 1000 and out.execution_time_s > 0
    ext = out.mesh.extents
    assert 0.2 < float(max(ext)) < 4.0, "TripoSR output is normalised to roughly a unit cube"


def test_full_generation_job_caches_the_second_identical_request(engine, tmp_path):
    from aro_studio.app_context import build_context

    ctx = build_context(Settings(data_dir=tmp_path / "d", verified_model_licenses="triposr", device=_device()))
    try:
        p = ctx.projects.create("real")
        a = ctx.assets.create_asset(p["project_id"], "real", "heavy_truck")
        buf = io.BytesIO()
        render_asset_scene(build_titan480(), azimuth_deg=40, size=1024, background=(236, 236, 236)).save(buf, "PNG")
        sha = ctx.sources.add_image(p["project_id"], "c.png", buf.getvalue())["sha256"]
        params = {
            "project_id": p["project_id"],
            "asset_id": a["asset_id"],
            "image_sha256": sha,
            "engine_id": "triposr",
            "preset": "LOW_RESOURCE",
        }
        j1 = ctx.jobs.wait(ctx.jobs.submit("generation", params)["job_id"], timeout=1800)
        assert j1["state"] == "COMPLETED" and j1["result"]["model_ran"] is True
        j2 = ctx.jobs.wait(ctx.jobs.submit("generation", params)["job_id"], timeout=60)
        assert (
            j2["state"] == "COMPLETED"
            and j2["result"]["model_ran"] is False
            and j2["result"]["reused_from"] == j1["result"]["generation_id"]
        )
        raw = ctx.assets.load_scene(j1["result"]["version_id"])
        assert raw.manifest.provenance.source == "ai_reconstruction" and raw.manifest.provenance.engine_id == "triposr"
    finally:
        ctx.close()


def test_tiny_vram_budget_is_a_resource_limit_not_a_crash(engine):
    pytest.importorskip("torch")
    import torch

    if not torch.cuda.is_available():
        pytest.skip("VRAM behaviour needs a CUDA device")
    # an absurd chunk-less high-resolution request must end as a controlled error on small GPUs, never an unhandled crash
    from aro_studio.core.errors import explain_exception

    try:
        engine.generate(
            GenerationRequest(
                image=Image.new("RGB", (512, 512), (128, 128, 128)),
                settings={"mc_resolution": 512, "chunk_size": 0},
                workdir=__import__("pathlib").Path("/tmp/aro_oom"),
            )
        )
    except Exception as e:  # noqa: BLE001
        assert explain_exception(e).job_state in ("RESOURCE_LIMIT", "MODEL_ERROR", "FAILED")
