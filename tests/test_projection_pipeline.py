"""A geometry-only engine (TripoSG-like) through the one-click flow: the Studio projects the reference photo onto the mesh.

The engine is a labelled TEST DOUBLE returning a truck-like mesh WITHOUT any colour, and the reference is a rendering whose colours are a
known function of position, so the projected result can be checked numerically. It proves the orchestration (reference found,
step run, texture baked, limits reported), not any model's quality.
"""

from __future__ import annotations

import io
import time

import numpy as np
import pytest
from PIL import Image

from aro_studio.engines.base import GenerationOutput, GenerationRequest
from tests.support import PlumbingEngine
from tests.test_api_integration import make_client, wait
from tests.test_fidelity import truckish
from tests.test_projection import known_colour, reference_photo


class GeometryOnlyDouble(PlumbingEngine):
    info = PlumbingEngine.info.__class__(
        **{**PlumbingEngine.info.__dict__, "id": "geom_test_double", "name": "Geometry-only truck test double (NOT AI)"}
    )

    def generate(self, request: GenerationRequest) -> GenerationOutput:
        t0 = time.perf_counter()
        mesh = truckish().subdivide_to_size(0.15, max_iter=6)  # dense, grey: no colours at all
        request.workdir.mkdir(parents=True, exist_ok=True)
        f = request.workdir / "raw_output.glb"
        mesh.export(f)
        return GenerationOutput(f, "glb", mesh, "cpu", time.perf_counter() - t0, {"test_double": True, "pbr": False})


@pytest.fixture
def api(tmp_path):
    c, ctx = make_client(
        tmp_path,
        engines=[GeometryOnlyDouble()],
        verified_model_licenses="geom_test_double",
        default_engine="geom_test_double",
    )
    yield c, ctx
    ctx.close()


def test_geometry_only_engine_gets_its_colour_from_the_reference_photo(api):
    c, ctx = api
    photo = reference_photo(truckish().subdivide_to_size(0.15, max_iter=6), 35.0, 10.0)
    buf = io.BytesIO()
    photo.save(buf, "PNG")
    r = c.post(
        "/api/convert",
        files={"file": ("truck.png", buf.getvalue(), "image/png")},
        data={"category": "heavy_truck", "length_m": "6.0"},
    )
    assert r.status_code == 202, r.text
    done = wait(c, r.json()["job"]["job_id"], timeout=300)
    assert done["state"] == "COMPLETED", done.get("error")
    res = done["result"]
    steps = {s["step"]: s["status"] for s in res["preparation_steps"]}
    proj = [k for k in steps if "project the reference image" in k]
    assert proj and steps[proj[0]] == "PASS", steps
    assert any("PROJECTED" in n for n in res["needs_human"]), res[
        "needs_human"
    ]  # the unseen side is declared as inferred

    final = ctx.assets.load_scene(res["final_version_id"])
    assert final.manifest.textures, "no baked texture: the projected colours never reached the prepared model"
    mesh = next(iter(final.meshes.values()))
    tex = np.asarray(Image.open(io.BytesIO(final.texture_data[final.manifest.textures[0].file])).convert("RGB")).astype(
        float
    )
    uv = np.asarray(mesh.visual.uv)
    h, w = tex.shape[:2]
    px = (uv[:, 0] * (w - 1)).round().astype(int).clip(0, w - 1)
    py = ((1.0 - uv[:, 1]) * (h - 1)).round().astype(int).clip(0, h - 1)
    baked = tex[py, px] / 255.0
    truth = known_colour(np.asarray(mesh.vertices))
    # red grows towards the front (+Z) and green with height in the reference: the baked texture must follow the prepared geometry
    assert np.corrcoef(baked[:, 0], truth[:, 0])[0, 1] > 0.7
    assert np.corrcoef(baked[:, 1], truth[:, 1])[0, 1] > 0.7
