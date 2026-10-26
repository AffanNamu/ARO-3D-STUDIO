"""A dense, accurate engine mesh through the one-click flow keeps its fine surface detail as a NORMAL MAP on the game-budget mesh.

The engine is a labelled TEST DOUBLE (a bumpy, coloured sphere): it proves the orchestration and the export, not any model's quality.
"""

from __future__ import annotations

import io
import time

import numpy as np
import pytest
import trimesh
from PIL import Image

from aro_studio.engines.base import GenerationOutput, GenerationRequest
from tests.support import PlumbingEngine
from tests.test_api_integration import make_client, wait


class DenseBumpyDouble(PlumbingEngine):
    info = PlumbingEngine.info.__class__(
        **{**PlumbingEngine.info.__dict__, "id": "dense_test_double", "name": "Dense bumpy test double (NOT AI)"}
    )

    def generate(self, request: GenerationRequest) -> GenerationOutput:
        t0 = time.perf_counter()
        m = trimesh.creation.icosphere(subdivisions=7)  # about 164k triangles: well above the 24k budget
        v = np.asarray(m.vertices)
        theta, phi = np.arccos(np.clip(v[:, 2], -1, 1)), np.arctan2(v[:, 1], v[:, 0])
        m.vertices = v * (1.0 + 0.03 * np.sin(14 * theta) * np.sin(14 * phi))[:, None]
        m.apply_scale([1.0, 0.6, 0.5])
        col = ((np.asarray(m.vertices) - m.vertices.min(0)) / np.ptp(m.vertices, axis=0) * 255).astype(np.uint8)
        m.visual = trimesh.visual.ColorVisuals(mesh=m, vertex_colors=np.c_[col, np.full(len(col), 255, np.uint8)])
        request.workdir.mkdir(parents=True, exist_ok=True)
        f = request.workdir / "raw_output.glb"
        m.export(f)
        return GenerationOutput(f, "glb", m, "cpu", time.perf_counter() - t0, {"test_double": True})


@pytest.fixture
def api(tmp_path):
    c, ctx = make_client(
        tmp_path,
        engines=[DenseBumpyDouble()],
        verified_model_licenses="dense_test_double",
        default_engine="dense_test_double",
    )
    yield c, ctx
    ctx.close()


def png() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (160, 120), (180, 90, 40)).save(b, "PNG")
    return b.getvalue()


def test_dense_engine_detail_becomes_a_normal_map_in_the_prepared_asset_and_its_glb(api):
    c, ctx = api
    r = c.post(
        "/api/convert",
        files={"file": ("bumpy.png", png(), "image/png")},
        data={"category": "equipment", "length_m": "2.0"},
    )
    assert r.status_code == 202, r.text
    done = wait(c, r.json()["job"]["job_id"], timeout=400)
    assert done["state"] == "COMPLETED", done.get("error")
    res = done["result"]
    final = ctx.assets.load_scene(res["final_version_id"])
    channels = {t.channel for t in final.manifest.textures}
    assert {"base_color", "normal"} <= channels, channels
    mat = next(m for m in final.manifest.materials if m.textures.get("normal"))
    nt = final.manifest.texture(mat.textures["normal"])
    assert nt is not None and nt.colorspace == "linear"
    ts = (
        np.asarray(Image.open(io.BytesIO(final.texture_data[nt.file])).convert("RGB")).astype(float) / 255.0 * 2.0 - 1.0
    )
    covered = np.abs(ts - np.array([0.0, 0.0, 1.0])).sum(axis=-1) > 1e-3
    assert covered.mean() > 0.2
    assert ts[covered][:, :2].std() > 0.03, "the normal map is flat: the dense mesh's bumps were not transferred"
    assert ts[covered][:, 2].mean() > 0.8
    steps = res["preparation_steps"]
    assert any("bake colour" in s["step"] and s["status"] == "PASS" for s in steps)

    glb = c.get(res["download"]).content
    scene = trimesh.load(io.BytesIO(glb), file_type="glb", force="scene")
    lod0 = next(
        g for n, g in scene.geometry.items() if n.endswith("_LOD0") or "LOD" not in n and not n.startswith("COL_")
    )
    assert lod0.visual.material.normalTexture is not None, "the exported GLB lost the normal map"
