"""Level-of-detail aware statistics, format conversion, and the library operations the web app uses."""

from __future__ import annotations

import io
import time
import uuid
import zipfile

import httpx
import pytest
import trimesh
from fastapi.testclient import TestClient

from aro_cloud.api import create_app
from aro_cloud.auth import JwtVerifier
from aro_cloud.exports import ConversionError, convert_glb
from aro_cloud.glb import full_detail, load_scene, lod_table, parts_of
from aro_cloud.output_gate import validate_glb
from tests.cloud.support import (
    ScriptedProvider,
    enable_model,
    finish_run,
    make_game_glb,
    make_glb,
    make_user,
    png_bytes,
    sha,
)
from tests.cloud.test_api import SECRET, bearer, generate, upload

GAME = make_game_glb()


# ------------------------------------------------------------------------------------------------------ LOD awareness
def test_the_model_is_lod0_not_the_sum_of_every_level():
    parts = parts_of(load_scene(GAME))
    assert sorted(p.name for p in parts) == ["COL_Hull", "Car_LOD0", "Car_LOD1", "Car_LOD2"]
    assert [p.name for p in full_detail(parts)] == ["Car_LOD0"]
    assert lod_table(parts) == [
        {"level": 0, "triangles": 1280},
        {"level": 1, "triangles": 320},
        {"level": 2, "triangles": 80},
    ]
    gate = validate_glb(GAME, claimed_sha256=sha(GAME), max_bytes=10**8)
    assert gate.ok and gate.stats["triangles"] == 1280  # LOD0 only: not 1280 + 320 + 80, and not the collision box
    assert (
        gate.stats["collision_meshes"] == 1 and gate.stats["collision_triangles"] == 12 and gate.stats["has_uv"] is True
    )


def test_a_file_without_lod_names_is_one_full_detail_model():
    plain = make_glb(3)
    assert len(full_detail(parts_of(load_scene(plain)))) == 1
    gate = validate_glb(plain, claimed_sha256=None, max_bytes=10**8)
    assert gate.stats["triangles"] == 1280 and gate.stats["lods"] == [] and gate.stats["collision_meshes"] == 0


def test_a_tiny_lod0_is_refused_even_when_the_other_levels_add_up():
    scene = trimesh.Scene()
    scene.add_geometry(
        trimesh.creation.icosphere(subdivisions=0), node_name="X_LOD0", geom_name="X_LOD0"
    )  # 20 triangles
    scene.add_geometry(trimesh.creation.icosphere(subdivisions=3), node_name="X_LOD1", geom_name="X_LOD1")
    gate = validate_glb(bytes(scene.export(file_type="glb")), claimed_sha256=None, max_bytes=10**8)
    assert not gate.ok and "too little geometry" in gate.reasons[0]


# --------------------------------------------------------------------------------------------------------- conversion
def test_obj_is_a_zip_with_geometry_material_and_texture_of_lod0_only():
    z = zipfile.ZipFile(io.BytesIO(convert_glb(GAME, "obj")))
    names = z.namelist()
    assert (
        "model.obj" in names
        and any(n.endswith(".mtl") for n in names)
        and any(n.endswith(".png") for n in names)
        and "README.txt" in names
    )
    obj = z.read("model.obj").decode()
    assert obj.count("\nf ") == 1280 and "mtllib" in obj and "\nvt " in obj
    assert all(".." not in n and not n.startswith("/") for n in names)


def test_stl_is_geometry_only_and_z_up():
    stl = trimesh.load(io.BytesIO(convert_glb(GAME, "stl")), file_type="stl")
    assert len(stl.faces) == 1280
    src = trimesh.creation.box((1.0, 3.0, 2.0))  # tall along +Y in glTF
    out = trimesh.load(
        io.BytesIO(convert_glb(bytes(trimesh.Scene(src).export(file_type="glb")), "stl")), file_type="stl"
    )
    assert [round(float(x), 3) for x in out.extents] == [1.0, 2.0, 3.0]  # the tall axis is now Z, as slicers expect


def test_ply_keeps_colour_as_vertex_colours():
    ply = trimesh.load(io.BytesIO(convert_glb(GAME, "ply")), file_type="ply")
    assert len(ply.faces) == 1280 and ply.visual.kind == "vertex"
    assert tuple(int(c) for c in ply.visual.vertex_colors[0][:3]) == (200, 60, 50)


def test_conversion_is_deterministic_and_refuses_nonsense():
    assert convert_glb(GAME, "obj") == convert_glb(GAME, "obj")
    with pytest.raises(ConversionError):
        convert_glb(GAME, "fbx")
    with pytest.raises(ConversionError):
        convert_glb(b"not a glb", "obj")


# ------------------------------------------------------------------------------------------------------- through the API
@pytest.fixture
def lib(pg, store, settings):
    enable_model(pg)
    provider = ScriptedProvider()
    client = TestClient(
        create_app(settings, db=pg, store=store, provider=provider, verifier=JwtVerifier(secret=SECRET)),
        raise_server_exceptions=False,
    )
    user = make_user(pg, credits=100)

    def make(name: str, key: str) -> str:
        up = upload(client, user).json()["upload_id"]
        job = generate(client, user, up, key=key, name=name).json()
        finish_run(provider, provider.last, glb=GAME)
        deadline = time.time() + 10
        while time.time() < deadline:
            j = client.get(f"/v1/generations/{job['job_id']}", headers=bearer(user)).json()
            if j["state"] == "completed":
                return j["result"]["asset_id"]
            time.sleep(0.5)
        raise AssertionError("generation did not complete")

    return client, user, pg, store, make


def test_asset_detail_summarises_the_model(lib):
    client, user, _, _, make = lib
    asset = make("Blue bus", "lib-key-0001")
    d = client.get(f"/v1/assets/{asset}", headers=bearer(user)).json()
    m = d["model"]
    assert m["triangles"] == 1280 and [x["level"] for x in m["lods"]] == [0, 1, 2] and m["collision_triangles"] == 12
    assert m["ai_inference"] is True and m["engine"] == "triposg" and len(m["extents_m"]) == 3
    assert {f["role"] for f in m["files"]} == {"glb", "raw_mesh", "thumbnail"}
    assert d["metadata"]["upload_id"]


def test_exports_convert_once_and_download(lib):
    client, user, pg, store, make = lib
    asset = make("My Car", "lib-key-0002")
    first = client.get(f"/v1/assets/{asset}/versions/1/exports/obj", headers=bearer(user)).json()
    assert first["filename"] == "My_Car_obj.zip" and first["format"] == "obj"
    body = httpx.get(first["url"]).content
    assert zipfile.ZipFile(io.BytesIO(body)).read("model.obj").decode().count("\nf ") == 1280
    again = client.get(f"/v1/assets/{asset}/versions/1/exports/obj", headers=bearer(user)).json()
    assert httpx.get(again["url"]).content == body
    with pg.transaction() as tx:
        assert tx.one("select count(*) as n from files where role = 'export'")["n"] == 1  # stored once, not per request
    stl = client.get(f"/v1/assets/{asset}/versions/1/exports/STL", headers=bearer(user)).json()
    assert stl["filename"] == "My_Car.stl" and httpx.get(stl["url"]).status_code == 200
    assert (
        client.get(f"/v1/assets/{asset}/versions/1/exports/fbx", headers=bearer(user)).json()["error"]["code"]
        == "unknown_format"
    )
    assert client.get(f"/v1/assets/{asset}/versions/9/exports/obj", headers=bearer(user)).status_code == 404


def test_rename_search_and_delete(lib):
    client, user, pg, _, make = lib
    a = make("Red truck", "lib-key-0003")
    b = make("Blue bus 100%", "lib-key-0004")
    r = client.patch(f"/v1/assets/{a}", json={"name": "  Red pickup  "}, headers=bearer(user))
    assert r.status_code == 200 and r.json()["name"] == "Red pickup"
    assert client.patch(f"/v1/assets/{a}", json={"name": ""}, headers=bearer(user)).status_code == 422
    assert (
        client.patch(
            f"/v1/assets/{a}", json={"name": "x", "owner_id": str(uuid.uuid4())}, headers=bearer(user)
        ).status_code
        == 422
    )

    def names(q: str) -> list[str]:
        return [x["name"] for x in client.get("/v1/assets", params={"q": q}, headers=bearer(user)).json()["items"]]

    assert names("PICK") == ["Red pickup"] and names("bus") == ["Blue bus 100%"] and names("zzz") == []
    assert (
        names("100%") == ["Blue bus 100%"] and names("%") == ["Blue bus 100%"] and names("_") == []
    )  # wildcards are literal

    assert client.delete(f"/v1/assets/{b}", headers=bearer(user)).status_code == 204
    assert client.delete(f"/v1/assets/{b}", headers=bearer(user)).status_code == 404
    assert [x["asset_id"] for x in client.get("/v1/assets", headers=bearer(user)).json()["items"]] == [a]
    for path in (f"/v1/assets/{b}", f"/v1/assets/{b}/versions/1/files/glb", f"/v1/assets/{b}/versions/1/exports/obj"):
        assert client.get(path, headers=bearer(user)).status_code == 404  # a deleted model can no longer be linked to
    with pg.transaction() as tx:
        row = tx.one("select status::text as s, deleted_at from assets where asset_id = CAST(:a AS uuid)", a=b)
        assert row["s"] == "deleted" and row["deleted_at"] is not None  # soft delete: recoverable by an operator
        assert tx.one("select count(*) as n from audit_log where action = 'delete_asset'")["n"] == 1


def test_library_operations_are_owner_scoped(lib):
    client, user, pg, _, make = lib
    asset = make("Mine", "lib-key-0005")
    other = make_user(pg)
    assert client.patch(f"/v1/assets/{asset}", json={"name": "Stolen"}, headers=bearer(other)).status_code == 404
    assert client.delete(f"/v1/assets/{asset}", headers=bearer(other)).status_code == 404
    assert client.get(f"/v1/assets/{asset}/versions/1/exports/obj", headers=bearer(other)).status_code == 404
    assert client.get(f"/v1/assets/{asset}", headers=bearer(user)).json()["name"] == "Mine"


def test_reference_image_link_is_owner_scoped(lib):
    client, user, pg, _, _ = lib
    up = upload(client, user).json()["upload_id"]
    link = client.get(f"/v1/uploads/{up}", headers=bearer(user)).json()
    assert link["width"] == 512 and httpx.get(link["url"]).content == png_bytes()
    assert client.get(f"/v1/uploads/{up}", headers=bearer(make_user(pg))).status_code == 404


def test_job_view_carries_what_a_variation_needs(lib):
    client, user, _, _, _ = lib
    up = upload(client, user).json()["upload_id"]
    job = generate(client, user, up, key="lib-key-0006", settings={"preset": "DRAFT", "seed": 7}).json()
    assert job["upload_id"] == up and job["settings"]["seed"] == 7 and "idempotency_key" not in job


def test_cors_allows_the_new_methods(lib):
    client, *_ = lib
    for method in ("PATCH", "DELETE"):
        r = client.options(
            "/v1/assets/x", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": method}
        )
        assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"
