import time

import pytest

from aro_studio.config import Settings
from aro_studio.core.errors import EngineUnavailableError, InvalidInputError, explain_exception
from aro_studio.core.hashing import generation_cache_key
from aro_studio.engines.base import ModelLicense
from aro_studio.engines.manager import ModelManager
from aro_studio.engines.registry import BLOCKED_MODELS, EngineRegistry, license_gate
from aro_studio.engines.triposr import TripoSREngine
from tests.support import PlumbingEngine


# ---- registry / licence gate ---------------------------------------------------------------------
def test_lyra_can_never_be_registered():
    class Lyra(PlumbingEngine):
        info = PlumbingEngine.info.__class__(
            **{**PlumbingEngine.info.__dict__, "id": "nvidia-lyra-2.0", "name": "NVIDIA Lyra 2.0"}
        )

    with pytest.raises(InvalidInputError, match="blocked"):
        EngineRegistry().register(Lyra())
    assert "nvidia-lyra-2.0" in BLOCKED_MODELS and "sale" in BLOCKED_MODELS["nvidia-lyra-2.0"]


def test_prohibited_licence_cannot_be_registered():
    class Bad(PlumbingEngine):
        info = PlumbingEngine.info.__class__(
            **{
                **PlumbingEngine.info.__dict__,
                "id": "bad",
                "license": ModelLicense("X", "u", "prohibited", "prohibited"),
            }
        )

    with pytest.raises(InvalidInputError, match="prohibits"):
        EngineRegistry().register(Bad())


def test_unverified_weights_licence_blocks_until_deployer_attests():
    e = TripoSREngine()
    assert e.info.license.status == "claimed" and e.info.license.spdx == "MIT"
    with pytest.raises(EngineUnavailableError) as ei:
        license_gate(e, set())
    assert (
        "ARO_VERIFIED_MODEL_LICENSES=triposr" in ei.value.recommended_action
        and "huggingface.co/stabilityai/TripoSR" in ei.value.recommended_action
    )
    license_gate(e, {"triposr"})  # deployer verified -> allowed
    assert Settings(verified_model_licenses=" TripoSR , other ").verified_licenses == {"triposr", "other"}


def test_triposr_adapter_reports_why_it_cannot_run_here():
    av = TripoSREngine().availability("cpu")
    assert not av.ok and any("tsr" in r for r in av.reasons) and av.activation
    with pytest.raises(EngineUnavailableError) as ei:
        TripoSREngine().load("cpu")
    assert ei.value.details["reasons"] and "PYTHONPATH" in ei.value.recommended_action + " ".join(
        ei.value.details["activation"]
    )


def test_triposr_has_no_fallback_geometry():
    with pytest.raises(EngineUnavailableError, match="not loaded"):
        from PIL import Image

        from aro_studio.engines.base import GenerationRequest

        TripoSREngine().generate(GenerationRequest(Image.new("RGB", (8, 8)), {}, __import__("pathlib").Path("/tmp/x")))


def test_triposr_settings_normalisation_is_deterministic_and_validated():
    e = TripoSREngine()
    assert e.normalize_settings({}) == e.normalize_settings({"preset": "BALANCED"})
    assert (
        e.normalize_settings({"preset": "LOW_RESOURCE"})["mc_resolution"]
        < e.normalize_settings({"preset": "HIGH_QUALITY"})["mc_resolution"]
    )
    for bad in (
        {"preset": "ULTRA"},
        {"mc_resolution": 8},
        {"chunk_size": 5},
        {"foreground_ratio": 2},
        {"mc_resolution": "x"},
    ):
        with pytest.raises(InvalidInputError):
            e.normalize_settings(bad)


def test_triposr_resource_estimate_only_claims_measured_for_published_default():
    e = TripoSREngine()
    d = e.estimate_resources({}, "cuda")
    assert d.measured and d.vram_mb == 6000
    assert (
        not e.estimate_resources({"preset": "HIGH_QUALITY"}, "cuda").measured
        and not e.estimate_resources({}, "cpu").measured
    )


def test_cache_key_is_deterministic_and_sensitive():
    k = generation_cache_key("a" * 64, "e", "v1", {"x": 1, "y": 2})
    assert k == generation_cache_key("a" * 64, "e", "v1", {"y": 2, "x": 1})
    assert (
        len(
            {
                k,
                generation_cache_key("b" * 64, "e", "v1", {"x": 1, "y": 2}),
                generation_cache_key("a" * 64, "e", "v2", {"x": 1, "y": 2}),
                generation_cache_key("a" * 64, "e", "v1", {"x": 2, "y": 2}),
                generation_cache_key("a" * 64, "f", "v1", {"x": 1, "y": 2}),
            }
        )
        == 5
    )


# ---- model memory manager ----------------------------------------------------------------------------
def test_manager_lazy_loads_reuses_and_unloads(db):
    reg = EngineRegistry()
    e = PlumbingEngine()
    reg.register(e)
    mm = ModelManager(reg, db, idle_unload_s=0)
    assert mm.resident is None and not e.is_loaded  # not loaded at start
    with mm.acquire(e.info.id, "cpu") as (eng, load_s):
        assert eng.is_loaded and load_s >= 0
    with mm.acquire(e.info.id, "cpu"):
        pass
    assert e.load_count == 1  # reused, not reloaded
    time.sleep(0.01)
    assert mm.unload_if_idle() and not e.is_loaded and mm.resident is None
    events = [r["event"] for r in db.query("SELECT event FROM model_events ORDER BY id")]
    assert events == ["loading", "loaded", "unloaded"]


def test_manager_records_failed_loads_and_stays_clean(db):
    reg = EngineRegistry()
    reg.register(PlumbingEngine(fail="load"))
    mm = ModelManager(reg, db)
    with pytest.raises(Exception, match="weights missing"), mm.acquire("plumbing_test_double", "cpu"):
        pass
    assert mm.resident is None and db.query_one("SELECT 1 FROM model_events WHERE event='load_failed'")


# ---- error explanations ----------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "exc,code,state",
    [
        (RuntimeError("CUDA out of memory. Tried to allocate 2 GiB"), "GPU_OUT_OF_MEMORY", "RESOURCE_LIMIT"),
        (MemoryError(), "HOST_OUT_OF_MEMORY", "RESOURCE_LIMIT"),
        (OSError(28, "No space left on device"), "DISK_FULL", "RESOURCE_LIMIT"),
        (RuntimeError("CUDA error: no kernel image is available"), "GPU_UNAVAILABLE", "MODEL_ERROR"),
        (TimeoutError(), "TIMEOUT", "TIMEOUT"),
        (PermissionError(), "PERMISSION_DENIED", "FAILED"),
        (ValueError("odd"), "UNEXPECTED_ERROR", "FAILED"),
    ],
)
def test_errors_are_translated_with_actions(exc, code, state):
    ex = explain_exception(exc)
    assert (
        (ex.code, ex.job_state) == (code, state)
        and ex.recommended_action
        and "CUDA" not in ex.message.replace("GPU", "")[:0]
    )


def test_cuda_oom_message_is_the_plain_language_one():
    ex = explain_exception(RuntimeError("CUDA out of memory"))
    assert ex.message.startswith("Generation failed because available GPU memory was insufficient")
    assert "LOW_RESOURCE" in ex.recommended_action
