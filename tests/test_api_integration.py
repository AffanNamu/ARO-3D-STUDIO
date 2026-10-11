import io
import json
import time
import zipfile
from pathlib import Path

import pytest
import trimesh
from fastapi.testclient import TestClient

from aro_studio.api.app import create_app
from aro_studio.app_context import build_context
from aro_studio.config import Settings
from aro_studio.engines.triposr import TripoSREngine
from aro_studio.engines.weights import load_lock
from tests.support import PlumbingEngine


def make_client(tmp_path, engines=None, **kw):
    s = Settings(
        data_dir=tmp_path / "data",
        verified_model_licenses="plumbing_test_double",
        default_engine="plumbing_test_double",
        job_timeout_s=60,
        **kw,
    )
    ctx = build_context(s, engines=engines if engines is not None else [PlumbingEngine()])
    ctx.jobs.backoff_base_s = 0.02
    return TestClient(create_app(ctx)), ctx


@pytest.fixture
def api(tmp_path):
    c, ctx = make_client(tmp_path)
    yield c, ctx
    ctx.close()


def wait(c, jid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        j = c.get(f"/api/jobs/{jid}").json()
        if j["state"] in (
            "COMPLETED",
            "FAILED",
            "CANCELLED",
            "TIMEOUT",
            "RESOURCE_LIMIT",
            "MODEL_ERROR",
            "INVALID_INPUT",
        ):
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def new_asset(c, category="heavy_truck", name="ARO TITAN 480"):
    p = c.post("/api/projects", json={"name": name}).json()
    a = c.post(
        f"/api/projects/{p['project_id']}/assets",
        json={"name": name, "category": category, "metadata": {"manufacturer": "ARO Motors", "model": "TITAN 480"}},
    ).json()
    return p, a


def upload(c, pid, data, name="concept.png", category="heavy_truck"):
    return c.post(
        f"/api/projects/{pid}/sources", files={"file": (name, data, "image/png")}, data={"category": category}
    )


# ---- basics / security ---------------------------------------------------------------------------------
def test_health_system_taxonomy(api):
    c, _ = api
    assert c.get("/api/health").json()["status"] == "ok"
    s = c.get("/api/system").json()
    assert (
        s["resources"]["cpu_count"] >= 1
        and "gpu" in s["resources"]
        and s["schema_version"] == 2
        and s["queue"]["workers"] == 1
    )
    t = c.get("/api/taxonomy").json()
    assert {g["group"] for g in t["groups"]} == {"vehicles", "environment", "characters", "other"} and "geometry" in t[
        "processing_operations"
    ]
    assert next(x for g in t["groups"] for x in g["categories"] if x["id"] == "character")["available"] is False


def test_security_headers_and_no_traceback_leak(api):
    c, _ = api
    r = c.get("/api/projects/prj_notanid")
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_INPUT" and "Traceback" not in r.text
    assert (
        r.headers["x-content-type-options"] == "nosniff"
        and "frame-ancestors" in r.headers["content-security-policy"]
        and r.headers["cache-control"] == "no-store"
    )
    assert c.get("/api/projects/prj_" + "0" * 20).status_code == 404


def test_access_token_enforced(tmp_path):
    c, ctx = make_client(tmp_path, access_token="s3cret-token")
    try:
        assert c.get("/api/health").status_code == 200
        r = c.get("/api/projects")
        assert r.status_code == 401 and "token" in r.json()["error"]["recommended_action"].lower()
        assert c.get("/api/projects", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert c.get("/api/projects", headers={"Authorization": "Bearer s3cret-token"}).status_code == 200
        assert (
            "s3cret-token" not in c.get("/api/system", headers={"Authorization": "Bearer s3cret-token"}).text
        )  # secrets never echoed
    finally:
        ctx.close()


def test_rate_limit(tmp_path):
    c, ctx = make_client(tmp_path, rate_limit_per_minute=5)
    try:
        codes = [c.get("/api/projects").status_code for _ in range(8)]
        assert codes[:5] == [200] * 5 and 429 in codes[5:]
        r = c.get("/api/projects")
        assert r.status_code == 429 and "Retry-After" in r.headers
    finally:
        ctx.close()


# ---- projects / sources ----------------------------------------------------------------------------------
def test_project_api_lifecycle(api):
    c, _ = api
    p = c.post("/api/projects", json={"name": "ARO TITAN 480", "description": "d"}).json()
    pid = p["project_id"]
    assert c.patch(f"/api/projects/{pid}", json={"name": "Renamed"}).json()["name"] == "Renamed"
    assert c.post(f"/api/projects/{pid}/archive").json()["status"] == "archived"
    assert c.post(f"/api/projects/{pid}/restore").json()["status"] == "active"
    d = c.post(f"/api/projects/{pid}/duplicate", json={"name": "Copy"}).json()
    assert d["project_id"] != pid and c.get("/api/projects").json()["items"].__len__() == 2
    assert {e["type"] for e in c.get(f"/api/projects/{pid}/history").json()["items"]} >= {"project.created"}
    z = c.get(f"/api/projects/{pid}/archive.zip")
    assert z.status_code == 200 and "project.json" in zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert c.delete(f"/api/projects/{pid}").status_code == 204 and c.get(f"/api/projects/{pid}").status_code == 404
    assert c.post("/api/projects", json={"name": ""}).status_code == 422


def test_upload_validation_and_content_addressing(api, concept_png):
    c, ctx = api
    p, _ = new_asset(c)
    pid = p["project_id"]
    ok = upload(c, pid, concept_png, name="../../etc/passwd.png")
    assert ok.status_code == 201
    j = ok.json()
    assert (
        j["filename"] == "passwd.png" and len(j["sha256"]) == 64 and j["report"]["analysis"]["classification"] is None
    )
    stored = list((ctx.layout.source_dir(pid)).iterdir())
    assert [f.name for f in stored] == [f"{j['sha256']}.png"]  # stored by hash, never by the uploaded name
    assert upload(c, pid, b"<?php evil(); ?>", name="shell.png").status_code == 400
    assert upload(c, pid, b"", name="e.png").status_code == 400
    assert upload(c, pid, concept_png[:300], name="trunc.png").status_code == 400
    img = c.get(f"/api/projects/{pid}/sources/{j['sha256']}/image")
    assert img.status_code == 200 and img.content == concept_png
    pre = c.get(f"/api/projects/{pid}/sources/{j['sha256']}/preprocessed.png?foreground_ratio=0.8")
    assert pre.status_code == 200 and pre.headers["content-type"] == "image/png"
    from PIL import Image

    assert Image.open(io.BytesIO(pre.content)).size == (512, 512)


def test_oversize_upload_rejected_before_buffering(tmp_path, concept_png):
    c, ctx = make_client(tmp_path, max_upload_mb=0)
    try:
        p, _ = new_asset(c)
        r = upload(c, p["project_id"], concept_png)
        assert r.status_code == 400 and "limit" in r.json()["error"]["message"].lower()
    finally:
        ctx.close()


# ---- generation: job states, cache, failures ------------------------------------------------------------------
def gen(c, aid, sha, **kw):
    r = c.post(f"/api/assets/{aid}/generate", json={"image_sha256": sha, **kw})
    assert r.status_code == 202, r.text
    return r.json()["job_id"]


def test_batch_generation_queues_named_per_category_assets_and_reports_partial_failures(api, concept_png):
    c, ctx = api
    p = c.post("/api/projects", json={"name": "Batch mixed assets"}).json()
    pid = p["project_id"]
    r = c.post(
        f"/api/projects/{pid}/batch-generate",
        files=[
            ("files", ("first-object.png", concept_png, "image/png")),
            ("files", ("second-object.png", concept_png, "image/png")),
            ("files", ("invalid-object.png", b"not an image", "image/png")),
        ],
        data={
            "category": "other",
            "items_json": json.dumps(
                [
                    {"name": "First Prop", "category": "prop"},
                    {"name": "Small Building", "category": "building"},
                    {"name": "Invalid Image", "category": "prop"},
                ]
            ),
            "engine_id": "plumbing_test_double",
            "preset": "LOW_RESOURCE",
            "settings_json": "{}",
            "preprocess_json": "{}",
            "use_cache": "false",
            "force": "false",
            "priority": "5",
            "max_retries": "0",
        },
    )
    assert r.status_code == 202, r.text
    payload = r.json()
    assert payload["total"] == 3 and payload["queued"] == 2 and payload["failed"] == 1
    first, second, invalid = payload["items"]
    assert first["index"] == 0 and first["status"] == "QUEUED"
    assert first["asset"]["name"] == "First Prop" and first["asset"]["category"] == "prop"
    assert second["index"] == 1 and second["status"] == "QUEUED"
    assert second["asset"]["name"] == "Small Building" and second["asset"]["category"] == "building"
    assert invalid["index"] == 2 and invalid["status"] == "FAILED" and invalid["error"]["message"]
    first_asset = c.get(f"/api/assets/{first['asset']['asset_id']}").json()
    assert first_asset["metadata"]["ingestion_mode"] == "batch_image_to_3d"
    assert first_asset["metadata"]["batch_id"] == payload["batch_id"]
    for item in (first, second):
        finished = wait(c, item["job"]["job_id"])
        assert finished["state"] == "COMPLETED" and finished["result"]["model_ran"] is True
        assert c.get(f"/api/assets/{item['asset']['asset_id']}").json()["versions"]


def test_generation_records_everything_and_preserves_raw(api, concept_png):
    c, ctx = api
    p, a = new_asset(c)
    sha = upload(c, p["project_id"], concept_png).json()["sha256"]
    job = wait(c, gen(c, a["asset_id"], sha, preset="LOW_RESOURCE"))
    assert job["state"] == "COMPLETED" and job["result"]["model_ran"] is True
    states = [e["state"] for e in c.get(f"/api/jobs/{job['job_id']}/events").json()["items"] if e["state"]]
    order = ["QUEUED", "INITIALIZING", "PREPROCESSING", "GENERATING", "POSTPROCESSING", "VALIDATING", "COMPLETED"]
    assert [s for s in order if s in states] == order and [states.index(s) for s in order] == sorted(
        states.index(s) for s in order
    )
    g = c.get(f"/api/generations/{job['result']['generation_id']}").json()
    for k in (
        "generation_id",
        "project_id",
        "asset_id",
        "engine_id",
        "model_version",
        "input_image_sha256",
        "settings",
        "device",
        "execution_time_s",
        "output_format",
        "output_sha256",
        "status",
    ):
        assert g[k] not in (None, ""), k
    assert g["status"] == "COMPLETED" and g["input_image_sha256"] == sha and g["engine_id"] == "plumbing_test_double"
    v = c.get(f"/api/versions/{g['version_id']}").json()
    assert (
        v["stage"] == "raw"
        and v["scene"]["manifest"]["provenance"]["source"] == "ai_reconstruction"
        and v["scene"]["manifest"]["provenance"]["generation_id"] == g["generation_id"]
    )
    raw_file = ctx.layout.root / g["output_path"]
    assert (
        raw_file.is_file()
        and (raw_file.parent / "model_input.png").is_file()
        and (raw_file.parent / "generation.json").is_file()
    )
    assert c.get(f"/api/assets/{a['asset_id']}").json()["status"] == "DRAFT"


def test_cache_reuses_without_running_the_model(tmp_path, concept_png):
    eng = PlumbingEngine()
    c, ctx = make_client(tmp_path, engines=[eng])
    try:
        p, a = new_asset(c)
        sha = upload(c, p["project_id"], concept_png).json()["sha256"]
        j1 = wait(c, gen(c, a["asset_id"], sha, preset="LOW_RESOURCE"))
        assert eng.generate_count == 1
        j2 = wait(c, gen(c, a["asset_id"], sha, preset="LOW_RESOURCE"))
        assert (
            j2["state"] == "COMPLETED"
            and j2["result"]["model_ran"] is False
            and j2["result"]["reused_from"] == j1["result"]["generation_id"]
        )
        assert (
            eng.generate_count == 1 and j2["result"]["version_id"] != j1["result"]["version_id"]
        )  # new raw version, no GPU time
        g2 = c.get(f"/api/generations/{j2['result']['generation_id']}").json()
        assert g2["reused_from"] == j1["result"]["generation_id"] and g2["status"] == "COMPLETED"
        # different settings or force -> runs again
        j3 = wait(c, gen(c, a["asset_id"], sha, preset="BALANCED"))
        j4 = wait(c, gen(c, a["asset_id"], sha, preset="LOW_RESOURCE", force=True))
        j5 = wait(c, gen(c, a["asset_id"], sha, preset="LOW_RESOURCE", use_cache=False))
        assert [j["result"]["model_ran"] for j in (j3, j4, j5)] == [True, True, True] and eng.generate_count == 4
        assert ctx.generation.cache_stats()["cache_hits"] == 1
        assert eng.load_count == 1  # model stayed resident between jobs
    finally:
        ctx.close()


def test_engine_unavailable_ends_model_error_without_placeholder_geometry(tmp_path, concept_png):
    c, ctx = make_client(tmp_path, engines=[PlumbingEngine(available=False)])
    try:
        p, a = new_asset(c)
        sha = upload(c, p["project_id"], concept_png).json()["sha256"]
        j = wait(c, gen(c, a["asset_id"], sha))
        assert (
            j["state"] == "MODEL_ERROR" and "cannot run" in j["error"]["message"] and j["error"]["recommended_action"]
        )
        assert c.get(f"/api/assets/{a['asset_id']}").json()["versions"] == []  # NO version, NO placeholder mesh
        g = c.get("/api/generations").json()["items"][0]
        assert g["status"] == "MODEL_ERROR" and g["version_id"] is None and g["error"]["code"] == "ENGINE_UNAVAILABLE"
        assert c.get(f"/api/assets/{a['asset_id']}").json()["status"] == "FAILED"
        # failed job keeps error, params, model info, resources, timestamps
        assert (
            j["params"]["image_sha256"] == sha
            and j["error"]["context"]["model"]["id"] == "plumbing_test_double"
            and j["resources"]["at_start"]["cpu_count"] >= 1
            and j["finished_at"]
        )
    finally:
        ctx.close()


def test_real_triposr_adapter_refuses_without_licence_then_without_runtime(tmp_path, concept_png):
    s = Settings(data_dir=tmp_path / "data")
    lock = load_lock("triposr").model_copy(deep=True)
    lock.weights.revision = None  # simulate an unverified lock without weakening the production lock
    ctx = build_context(s, engines=[TripoSREngine(lock=lock)])
    c = TestClient(create_app(ctx))
    try:
        p, a = new_asset(c)
        sha = upload(c, p["project_id"], concept_png).json()["sha256"]
        j = wait(c, gen(c, a["asset_id"], sha))
        assert j["state"] == "MODEL_ERROR" and "ARO_VERIFIED_MODEL_LICENSES=triposr" in j["error"]["recommended_action"]
        ctx.settings.verified_model_licenses = "triposr"
        j = wait(c, gen(c, a["asset_id"], sha))
        assert (
            j["state"] == "MODEL_ERROR"
            and "tsr" in j["error"]["message"]
            and c.get(f"/api/assets/{a['asset_id']}").json()["versions"] == []
        )
        eng = c.get("/api/engines").json()
        assert eng["items"][0]["runnable"] is False and "nvidia-lyra-2.0" in eng["blocked"]
    finally:
        ctx.close()


def test_gpu_oom_is_explained_and_marked_resource_limit(tmp_path, concept_png):
    c, ctx = make_client(tmp_path, engines=[PlumbingEngine(fail="oom")])
    try:
        p, a = new_asset(c)
        sha = upload(c, p["project_id"], concept_png).json()["sha256"]
        j = wait(c, gen(c, a["asset_id"], sha))
        assert (
            j["state"] == "RESOURCE_LIMIT"
            and j["error"]["code"] == "GPU_OUT_OF_MEMORY"
            and "LOW_RESOURCE" in j["error"]["recommended_action"]
        )
        assert c.get("/api/system").status_code == 200  # the application is alive
        assert (
            wait(c, c.post(f"/api/jobs/{j['job_id']}/requeue").json()["job_id"])["state"] == "RESOURCE_LIMIT"
        )  # preserved + re-queueable
    finally:
        ctx.close()


def test_preflight_blocks_when_vram_insufficient(tmp_path, concept_png, monkeypatch):
    from aro_studio.observability import resources as r

    eng = PlumbingEngine(vram_mb=24000)
    c, ctx = make_client(tmp_path, engines=[eng], device="cuda")
    monkeypatch.setattr(
        "aro_studio.generation.service.snapshot",
        lambda d: type(
            "S",
            (),
            {"gpu": r.GpuInfo(True, "T4", 16000, 3000, "x", "t"), "ram_available_mb": 8000, "disk_free_mb": 9000},
        )(),
    )
    try:
        p, a = new_asset(c)
        sha = upload(c, p["project_id"], concept_png).json()["sha256"]
        j = wait(c, gen(c, a["asset_id"], sha))
        assert j["state"] == "RESOURCE_LIMIT" and "3000 MB free" in j["error"]["message"] and eng.generate_count == 0
    finally:
        ctx.close()


def test_empty_engine_output_is_a_model_error_not_success(tmp_path, concept_png):
    c, ctx = make_client(tmp_path, engines=[PlumbingEngine(fail="empty")])
    try:
        p, a = new_asset(c)
        sha = upload(c, p["project_id"], concept_png).json()["sha256"]
        j = wait(c, gen(c, a["asset_id"], sha))
        assert j["state"] == "MODEL_ERROR" and c.get(f"/api/assets/{a['asset_id']}").json()["versions"] == []
    finally:
        ctx.close()


def test_cancel_running_and_queued_generation(tmp_path, concept_png):
    c, ctx = make_client(tmp_path, engines=[PlumbingEngine(delay=4.0)])
    try:
        p, a = new_asset(c)
        sha = upload(c, p["project_id"], concept_png).json()["sha256"]
        j1 = gen(c, a["asset_id"], sha, preset="LOW_RESOURCE")
        j2 = gen(c, a["asset_id"], sha, preset="BALANCED", priority=9)
        end = time.time() + 20
        while c.get(f"/api/jobs/{j1}").json()["state"] != "GENERATING" and time.time() < end:
            time.sleep(0.05)
        assert c.post(f"/api/jobs/{j2}/cancel").json()["state"] == "CANCELLED"  # queued: immediate
        assert c.post(f"/api/jobs/{j1}/cancel").status_code == 200
        assert wait(c, j1)["state"] == "CANCELLED"
        assert c.get(f"/api/assets/{a['asset_id']}").json()["versions"] == []
        assert c.post(f"/api/jobs/{j1}/cancel").status_code == 400  # already terminal
    finally:
        ctx.close()


def test_invalid_image_hash_and_unknown_engine(api):
    c, _ = api
    _, a = new_asset(c)
    assert c.post(f"/api/assets/{a['asset_id']}/generate", json={"image_sha256": "z" * 64}).status_code == 202
    j = wait(c, c.get("/api/jobs").json()["items"][0]["job_id"])
    assert j["state"] == "INVALID_INPUT"


# ---- import ----------------------------------------------------------------------------------------------------------
def test_import_glb_creates_raw_version(api):
    c, _ = api
    _, a = new_asset(c, "prop", "Crate")
    glb = trimesh.creation.box((1, 1, 1)).export(file_type="glb")
    r = c.post(f"/api/assets/{a['asset_id']}/import", files={"file": ("crate.glb", glb, "model/gltf-binary")})
    assert r.status_code == 201, r.text
    v = r.json()["version"]
    assert v["stage"] == "raw" and v["triangle_count"] == 12 and r.json()["report"]["parts"] == 1


def test_import_rejects_bad_content_and_zip_slip(api):
    c, _ = api
    _, a = new_asset(c, "prop", "Crate")
    aid = a["asset_id"]
    assert c.post(f"/api/assets/{aid}/import", files={"file": ("x.glb", b"not a glb at all", "x/y")}).status_code == 400
    assert c.post(f"/api/assets/{aid}/import", files={"file": ("x.exe", b"MZ\x90\x00", "x/y")}).status_code == 400
    assert (
        c.post(f"/api/assets/{aid}/import", files={"file": ("x.obj", b"\x00\x01\x02binary", "x/y")}).status_code == 400
    )
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as zf:
        zf.writestr("../../evil.obj", "v 0 0 0")
    assert (
        c.post(f"/api/assets/{aid}/import", files={"file": ("a.zip", b.getvalue(), "application/zip")}).status_code
        == 400
    )
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("model/box.obj", trimesh.creation.box().export(file_type="obj"))
    ok = c.post(f"/api/assets/{aid}/import", files={"file": ("a.zip", z.getvalue(), "application/zip")})
    assert ok.status_code == 201 and ok.json()["version"]["triangle_count"] == 12


# ---- full post-reconstruction pipeline on the reference asset ---------------------------------------------------------------------
def run_op(c, vid, op, params=None):
    j = wait(
        c,
        c.post(f"/api/versions/{vid}/process", json={"operation": op, "params": params or {}}).json()["job_id"],
        timeout=120,
    )
    assert j["state"] == "COMPLETED", j.get("error")
    return j["result"]


def test_full_pipeline_on_reference_asset(api, tmp_path):
    c, ctx = api
    p, a = new_asset(c)
    aid = a["asset_id"]
    assert c.post(f"/api/assets/{aid}/reference/titan480").status_code == 201
    raw = c.get(f"/api/assets/{aid}").json()["versions"][0]
    assert raw["stage"] == "raw"
    raw_manifest = (ctx.assets.version_path(raw["version_id"]) / "manifest.json").read_bytes()

    r1 = run_op(c, raw["version_id"], "geometry", {"preset": "standard_cleanup"})
    r2 = run_op(c, r1["version_id"], "materials", {"apply_vehicle_palette": False})
    r3 = run_op(c, r2["version_id"], "collision", {})
    r4 = run_op(c, r3["version_id"], "lod", {})
    r5 = run_op(c, r4["version_id"], "rig", {})
    # validation as a job
    val = run_op(c, r5["version_id"], "validate", {"config": {"check_intersections": False}})
    assert (
        val["status"] == "PRODUCTION_READY"
        and val["critical_failures"] == 0
        and c.get(f"/api/assets/{aid}").json()["status"] == "APPROVED"
    )
    # cannot designate an unvalidated version; can designate the validated one
    r6 = run_op(c, r5["version_id"], "finalize", {})
    assert c.post(f"/api/versions/{r6['version_id']}/designate-production", json={}).status_code == 409
    assert (
        c.post(f"/api/versions/{r5['version_id']}/designate-production", json={"semver": "1.0.0"}).json()["status"]
        == "PRODUCTION_READY"
    )
    asset = c.get(f"/api/assets/{aid}").json()
    assert asset["production_version_id"] == r5["version_id"] and asset["metadata"]["asset_version"] == "1.0.0"
    assert [v["stage"] for v in asset["versions"]][:2] == ["raw", "processed"] and len(asset["versions"]) == 7

    # exports
    ej = wait(
        c,
        c.post(f"/api/versions/{r5['version_id']}/export", json={"formats": ["glb", "gltf", "obj", "unity"]}).json()[
            "job_id"
        ],
        timeout=180,
    )
    assert ej["state"] == "COMPLETED", ej.get("error")
    exports = {e["format"]: e for e in c.get(f"/api/exports?asset_id={aid}").json()["items"]}
    assert set(exports) == {"glb", "gltf", "obj", "unity"} and all(
        e["status"] == "COMPLETED" and e["sha256"] and e["size_bytes"] > 1000 for e in exports.values()
    )
    assert all(e["report"]["verification"]["ok"] for e in exports.values())
    dl = c.get(f"/api/exports/{exports['glb']['export_id']}/download")
    assert dl.status_code == 200 and dl.content[:4] == b"glTF"
    sc = trimesh.load(io.BytesIO(dl.content), file_type="glb")
    assert len(sc.geometry) > 60
    uz = zipfile.ZipFile(io.BytesIO(c.get(f"/api/exports/{exports['unity']['export_id']}/download").content))
    names = uz.namelist()
    assert any(n.endswith("Models/ARO-TITAN-480.glb") for n in names) and any(n.endswith("README.md") for n in names)
    meta = json.loads(next(uz.read(n) for n in names if n.endswith("Metadata/asset.json")))
    assert meta["validation"]["status"] == "PRODUCTION_READY"  # the package records the validation it passed

    # preview for the viewer + version listing
    pv = c.get(f"/api/versions/{r5['version_id']}/preview.glb")
    assert pv.status_code == 200 and pv.content[:4] == b"glTF"

    # raw is byte-identical after the whole pipeline
    assert (ctx.assets.version_path(raw["version_id"]) / "manifest.json").read_bytes() == raw_manifest
    assert ctx.assets.load_scene(raw["version_id"]).manifest.lods == []
    # history shows the work
    types = {e["type"] for e in c.get(f"/api/projects/{p['project_id']}/history").json()["items"]}
    assert {"version.created", "validation", "export", "job"} <= types
    assert ctx.audit.recent(500)


def test_processing_a_broken_vehicle_does_not_validate(api):
    c, _ = api
    _, a = new_asset(c)
    aid = a["asset_id"]
    c.post(f"/api/assets/{aid}/reference/titan480")
    raw = c.get(f"/api/assets/{aid}").json()["versions"][0]
    # skip collision/LOD/rig entirely: must not be production ready
    val = run_op(c, raw["version_id"], "validate", {"config": {"check_intersections": False}})
    assert val["status"] == "NEEDS_REVIEW" and val["critical_failures"] >= 1
    assert c.post(f"/api/versions/{raw['version_id']}/designate-production", json={}).status_code == 409
    assert c.get(f"/api/assets/{aid}").json()["status"] == "NEEDS_REVIEW"


def test_reference_requires_heavy_truck_and_unknown_op(api):
    c, _ = api
    _, a = new_asset(c, "prop", "Crate")
    assert c.post(f"/api/assets/{a['asset_id']}/reference/titan480").status_code == 400
    _, t = new_asset(c)
    c.post(f"/api/assets/{t['asset_id']}/reference/titan480")
    v = c.get(f"/api/assets/{t['asset_id']}").json()["versions"][0]
    j = wait(c, c.post(f"/api/versions/{v['version_id']}/process", json={"operation": "teleport"}).json()["job_id"])
    assert j["state"] == "INVALID_INPUT"


def test_job_sse_stream_and_priority_listing(api, concept_png):
    c, _ = api
    p, a = new_asset(c)
    sha = upload(c, p["project_id"], concept_png).json()["sha256"]
    jid = gen(c, a["asset_id"], sha)
    with c.stream("GET", f"/api/jobs/{jid}/stream") as r:
        body = "".join(r.iter_text())
    assert "event: progress" in body and "event: done" in body and '"state": "COMPLETED"' in body
    assert c.get("/api/jobs?state=COMPLETED").json()["items"]


def test_exports_failed_are_recorded_not_dropped(api, monkeypatch):
    c, ctx = api
    _, a = new_asset(c)
    c.post(f"/api/assets/{a['asset_id']}/reference/titan480")
    v = c.get(f"/api/assets/{a['asset_id']}").json()["versions"][0]
    import aro_studio.export.service as svc

    monkeypatch.setattr(svc, "export_glb", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk exploded")))
    j = wait(c, c.post(f"/api/versions/{v['version_id']}/export", json={"formats": ["glb"]}).json()["job_id"])
    assert j["state"] == "FAILED"
    e = c.get("/api/exports").json()["items"][0]
    assert (
        e["status"] == "FAILED"
        and e["report"]["error"]["message"]
        and c.get(f"/api/exports/{e['export_id']}/download").status_code == 404
    )


def test_restart_recovers_jobs_and_keeps_failed_ones(tmp_path, concept_png):
    c, ctx = make_client(tmp_path)
    p, a = new_asset(c)
    sha = upload(c, p["project_id"], concept_png).json()["sha256"]
    wait(c, gen(c, a["asset_id"], sha))
    ctx.db.execute(
        "INSERT INTO jobs(job_id,kind,state,progress,message,priority,attempts,max_retries,params,created_at) VALUES ('job_"
        + "a" * 20
        + "','generation','GENERATING',0.5,'x',5,1,0,'{}',0)"
    )
    ctx.close()
    ctx2 = build_context(
        Settings(data_dir=tmp_path / "data", verified_model_licenses="plumbing_test_double"), engines=[PlumbingEngine()]
    )
    try:
        j = ctx2.jobs.get("job_" + "a" * 20)
        assert (
            j["state"] == "FAILED" and j["error"]["code"] == "INTERRUPTED"
        )  # kept, with a reason - never silently dropped
        assert ctx2.projects.list() and ctx2.db.schema_version == 2
    finally:
        ctx2.close()


def test_secrets_never_logged(tmp_path, caplog):
    from aro_studio.observability.logging import redact

    assert "hf_" not in redact("token hf_abcdefghijklmnopqrstuvwx used").replace("hf_***", "")
    assert "abc123" not in redact("Authorization: Bearer abc123")
    assert "hunter2" not in redact("password=hunter2")
    assert Path("/dev/null").exists()
