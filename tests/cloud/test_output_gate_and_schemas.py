from __future__ import annotations

import hashlib
import uuid

import numpy as np
import pytest
import trimesh
from pydantic import ValidationError

from aro_cloud.output_gate import validate_glb
from aro_cloud.schemas import CreateGeneration, WorkerResult
from aro_cloud.settings import CloudSettings, ConfigError
from tests.cloud.support import make_glb, sha

MAX = 150_000_000


def glb_of(mesh: trimesh.Trimesh) -> bytes:
    return bytes(trimesh.Scene(mesh).export(file_type="glb"))


def test_a_real_mesh_passes_and_reports_its_stats():
    data = make_glb(3)
    r = validate_glb(data, claimed_sha256=sha(data), max_bytes=MAX)
    assert r.ok and r.stats["triangles"] == 1280 and r.stats["meshes"] == 1 and r.sha256 == sha(data)
    assert any("UV" in w for w in r.warnings)


@pytest.mark.parametrize(
    ("data_fn", "needle"),
    [
        (lambda: b"", "not a binary glTF"),
        (lambda: b"glTF" + b"\x00" * 40, "cannot be parsed"),
        (lambda: make_glb(0), "too little geometry"),
        (
            lambda: glb_of(
                trimesh.Trimesh(vertices=np.zeros((4, 3)), faces=np.array([[0, 1, 2]] * 400 + [[1, 2, 3]] * 0))
            ),
            "no extent",
        ),
    ],
)
def test_unusable_output_is_refused(data_fn, needle):
    data = data_fn()
    r = validate_glb(data, claimed_sha256=None, max_bytes=MAX)
    assert not r.ok and any(needle in x for x in r.reasons), r.reasons


def test_checksum_mismatch_and_size_limit_and_test_double():
    data = make_glb(3)
    assert not validate_glb(data, claimed_sha256="0" * 64, max_bytes=MAX).ok
    assert not validate_glb(data, claimed_sha256=sha(data), max_bytes=100).ok
    refused = validate_glb(data, claimed_sha256=sha(data), max_bytes=MAX, engine_is_test_double=True)
    assert not refused.ok and "test double" in refused.reasons[0]
    assert validate_glb(
        data, claimed_sha256=sha(data), max_bytes=MAX, engine_is_test_double=True, allow_test_double=True
    ).ok


def test_degenerate_triangles_are_caught():
    mesh = trimesh.creation.icosphere(subdivisions=3)
    v = np.vstack([mesh.vertices, np.zeros((1, 3))])
    flat = np.array([[len(mesh.vertices)] * 3] * 1500)  # 1500 zero-area faces next to 1280 real ones
    bad = trimesh.Trimesh(vertices=v, faces=np.vstack([mesh.faces, flat]), process=False)
    r = validate_glb(glb_of(bad), claimed_sha256=None, max_bytes=MAX)
    assert not r.ok and any("no area" in x for x in r.reasons)


# ----------------------------------------------------------------------------------------------------------- schemas
def body(**over):
    b = {"kind": "image_to_3d", "upload_id": str(uuid.uuid4()), "name": "Car"}
    b.update(over)
    return b


def test_a_minimal_request_gets_safe_defaults():
    r = CreateGeneration.model_validate(body())
    assert r.engine == "triposg" and r.settings.preset == "STANDARD" and r.settings.target_faces == 24_000


@pytest.mark.parametrize(
    "bad",
    [
        body(kind="text_to_3d"),
        body(name=""),
        body(name="x" * 121),
        body(name="line\nbreak"),
        body(upload_id="not-a-uuid"),
        body(unknown_field=1),
        body(settings={"preset": "ULTRA"}),
        body(settings={"target_faces": 10}),
        body(settings={"target_faces": 10_000_000}),
        body(settings={"texture_resolution": 4096}),
        body(settings={"length_m": -1}),
        body(settings={"seed": -5}),
        body(settings={"decorative_knob": True}),
    ],
)
def test_requests_are_strict(bad):
    with pytest.raises(ValidationError):
        CreateGeneration.model_validate(bad)


def test_worker_results_are_parsed_leniently_but_typed():
    r = WorkerResult.model_validate(
        {
            "ok": True,
            "engine": {"id": "triposg"},
            "files": [{"role": "glb", "bytes": 3, "sha256": hashlib.sha256(b"abc").hexdigest()}],
            "extra": 1,
        }
    )
    assert r.files[0].role == "glb" and r.engine and not r.engine.test_double
    with pytest.raises(ValidationError):
        WorkerResult.model_validate({"ok": True, "files": [{"role": "glb", "bytes": 3, "sha256": "short"}]})


# ----------------------------------------------------------------------------------------------------------- settings
def test_production_refuses_to_start_unconfigured_or_with_the_test_double():
    with pytest.raises(ConfigError) as e:
        CloudSettings(env="production").validate_for_production()
    for name in (
        "ARO_DATABASE_URL",
        "ARO_R2_BUCKET",
        "ARO_RUNPOD_API_KEY",
        "ARO_INTERNAL_TOKEN",
        "ARO_ALLOWED_ORIGINS",
    ):
        assert name in str(e.value)
    full = dict(
        env="production",
        database_url="postgresql://u:p@h/db",
        supabase_url="https://x.supabase.co",
        r2_account_id="acc",
        r2_bucket="b",
        r2_access_key_id="k",
        r2_secret_access_key="s",
        runpod_api_key="r",
        runpod_endpoint_id="e",
        allowed_origins="https://app.example",
        internal_token="x" * 32,
    )
    CloudSettings(**full).validate_for_production()
    with pytest.raises(ConfigError, match="TEST_DOUBLE"):
        CloudSettings(**full, allow_test_double=True).validate_for_production()
    with pytest.raises(ConfigError, match="24 characters"):
        CloudSettings(**{**full, "internal_token": "short"}).validate_for_production()


def test_secrets_never_appear_in_repr():
    s = CloudSettings(
        runpod_api_key="rpa_TOPSECRET", database_url="postgresql://u:hunter2@h/db", r2_secret_access_key="r2secret"
    )
    text = repr(s) + str(s.model_dump())
    assert "TOPSECRET" not in text and "hunter2" not in text and "r2secret" not in text
