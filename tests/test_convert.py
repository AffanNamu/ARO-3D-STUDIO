"""One-click "Convert to 3D": reconstruct -> prepare -> export as a single job, with honest failure behaviour.

The engine here is the plumbing TEST DOUBLE (labelled everywhere as not AI): these tests prove orchestration, state, failure
handling and the no-fake-asset rule - not model quality. Real inference is proven separately (docs/verification).
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from aro_studio import app_context as app_context_module
from tests.support import PlumbingEngine
from tests.test_api_integration import make_client, wait


def png(w=160, h=120, color=(180, 90, 40)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, "PNG")
    return b.getvalue()


@pytest.fixture
def api(tmp_path):
    c, ctx = make_client(tmp_path)
    yield c, ctx
    ctx.close()


def post(c, data=None, name="chair.png", **form):
    return c.post("/api/convert", files={"file": (name, data if data is not None else png(), "image/png")}, data=form)


def test_one_click_runs_all_stages_and_returns_a_downloadable_glb(api):
    c, ctx = api
    r = post(c, name="Wooden Chair.png", category="furniture", length_m="0.9", up="+Z", forward="+X")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["asset"]["category"] == "furniture" and body["project"]["name"] == "Quick conversions"
    assert body["source"]["width"] == 160
    done = wait(c, body["job"]["job_id"], timeout=180)
    assert done["state"] == "COMPLETED", done.get("error")
    res = done["result"]
    assert [s["status"] for s in res["stages"]] == ["COMPLETED", "COMPLETED", "COMPLETED"]
    assert [s["stage"] for s in res["stages"]] == ["reconstruct", "prepare", "export"]
    assert res["model_ran"] is True and res["raw_version_id"] != res["final_version_id"]
    assert not any("real-world size" in n for n in res["needs_human"])  # the length was supplied
    assert res["final_extents_m"] and max(res["final_extents_m"]) == pytest.approx(0.9, rel=1e-2)

    dl = c.get(res["download"])
    assert dl.status_code == 200 and dl.content[:4] == b"glTF"  # a real binary glTF, not a placeholder
    # raw stayed raw and immutable; the prepared version is a NEW version of the same asset
    raw = c.get(f"/api/versions/{res['raw_version_id']}").json()
    final = c.get(f"/api/versions/{res['final_version_id']}").json()
    assert (
        raw["stage"] == "raw"
        and final["stage"] != "raw"
        and raw["asset_id"] == final["asset_id"] == body["asset"]["asset_id"]
    )
    assert raw["scene"]["manifest"]["provenance"]["source"] == "ai_reconstruction"
    assert done["message"] == "Completed" and done["progress"] == 1.0


def test_unsupplied_size_is_flagged_as_a_placeholder(api):
    c, _ = api
    done = wait(c, post(c).json()["job"]["job_id"], timeout=180)
    assert done["state"] == "COMPLETED"
    assert any("real-world size is not recoverable" in n for n in done["result"]["needs_human"])


def test_engine_that_cannot_run_answers_immediately_and_creates_nothing(tmp_path):
    c, ctx = make_client(tmp_path, engines=[PlumbingEngine(available=False)])
    try:
        r = post(c)
        assert r.status_code == 503
        err = r.json()["error"]
        assert (
            err["code"] == "ENGINE_UNAVAILABLE"
            and "cannot run in this environment" in err["message"]
            and err["recommended_action"]
        )
        assert (
            c.get("/api/assets").json()["items"] == [] and c.get("/api/jobs").json()["items"] == []
        )  # no asset, no job, no placeholder
        assert c.get("/api/projects").json()["items"] == []
    finally:
        ctx.close()


def test_invalid_image_is_rejected_before_any_asset_exists(api):
    c, _ = api
    r = post(c, data=b"this is not an image at all", name="evil.png")
    assert r.status_code == 400 and "not a PNG, JPEG or WebP" in r.json()["error"]["message"]
    assert c.get("/api/assets").json()["items"] == [] and c.get("/api/jobs").json()["items"] == []


@pytest.mark.parametrize(
    "form",
    [
        {"category": "nope"},
        {"up": "+Z", "forward": "-Z"},
        {"length_m": "0"},
        {"texture_resolution": "999"},
        {"formats": "glb,exe"},
        {"preprocess_json": '{"bogus": 1}'},
        {"settings_json": "[1]"},
    ],
)
def test_bad_options_are_rejected_without_side_effects(api, form):
    c, _ = api
    assert post(c, **form).status_code in (400, 422)
    assert c.get("/api/assets").json()["items"] == [] and c.get("/api/jobs").json()["items"] == []


def test_reconstruction_failure_is_reported_at_its_stage_with_the_honest_job_state(tmp_path):
    c, ctx = make_client(tmp_path, engines=[PlumbingEngine(fail="load")])
    try:
        done = wait(c, post(c).json()["job"]["job_id"], timeout=60)
        assert done["state"] == "MODEL_ERROR"
        ann = done["error"]["context"]  # failure annotations live in the error context
        stages = ann["convert_stages"]
        assert [s["status"] for s in stages] == ["FAILED", "NOT_RUN", "NOT_RUN"]
        assert ann["convert_failed_stage"] == "reconstruct"
        assert c.get("/api/assets").json()["items"][0]["status"] == "FAILED"  # the asset exists but has no fake version
        assert ctx.db.query_one("SELECT COUNT(*) n FROM asset_versions")["n"] == 0
    finally:
        ctx.close()


def test_preparation_failure_keeps_the_raw_reconstruction_and_says_where_it_stopped(api, monkeypatch):
    c, ctx = api

    def broken_pipeline(processing, assets, raw_version_id, opts, *, progress=None, check_cancel=None):
        return {
            "ok": False,
            "raw_version_id": raw_version_id,
            "cleaned_version_id": None,
            "final_version_id": None,
            "validation": None,
            "needs_human": [],
            "steps": [{"step": "collision", "status": "FAIL", "seconds": 0.1, "detail": {"error": "boom"}}],
        }

    monkeypatch.setattr(app_context_module, "run_ai_pipeline", broken_pipeline)
    body = post(c).json()
    done = wait(c, body["job"]["job_id"], timeout=120)
    assert done["state"] == "FAILED"
    ann = done["error"]["context"]
    assert [s["status"] for s in ann["convert_stages"]] == ["COMPLETED", "FAILED", "NOT_RUN"]
    assert ann["convert_failed_stage"] == "prepare" and ann["raw_version_id"]
    assert "raw reconstruction is preserved" in done["error"]["recommended_action"]
    kept = c.get(f"/api/versions/{ann['raw_version_id']}").json()  # the successful stage was not thrown away
    assert kept["stage"] == "raw" and kept["asset_id"] == body["asset"]["asset_id"]


def test_identical_second_conversion_reuses_the_reconstruction_and_says_so(api):
    c, ctx = api
    first = wait(c, post(c, length_m="1").json()["job"]["job_id"], timeout=180)["result"]
    second = wait(c, post(c, length_m="1").json()["job"]["job_id"], timeout=180)["result"]
    assert (
        first["model_ran"] is True and second["model_ran"] is False and second["reused_from"] == first["generation_id"]
    )
    assert second["stages"][0]["reused_from"] == first["generation_id"]


def test_progress_messages_name_the_step(api):
    c, _ = api
    seen = set()
    jid = post(c).json()["job"]["job_id"]
    import time

    end = time.time() + 180
    while time.time() < end:
        j = c.get(f"/api/jobs/{jid}").json()
        seen.add((j.get("message") or "")[:9])
        if j["state"] == "COMPLETED":
            break
        time.sleep(0.02)
    assert j["state"] == "COMPLETED" and any(m.startswith("Step ") for m in seen)
