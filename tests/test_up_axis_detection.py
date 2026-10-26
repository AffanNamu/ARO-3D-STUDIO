"""An engine may return its mesh in any frame. The Studio finds the up axis from the reference image instead of trusting a guess.

The engine here is a labelled TEST DOUBLE (a procedural truck-like block shape handed back in a Z-up frame): it proves the
orchestration (detection at generation time -> provenance -> the preparation uses it), not any model's behaviour.
"""

from __future__ import annotations

import io
import time

import numpy as np
import pytest
import trimesh
from PIL import Image

from aro_studio.engines.base import GenerationOutput, GenerationRequest
from aro_studio.quality import fidelity as fd
from aro_studio.utils.render import render_scene
from tests.support import PlumbingEngine
from tests.test_api_integration import make_client, wait
from tests.test_fidelity import truckish


class ZUpTruckDouble(PlumbingEngine):
    """Returns a truck-like mesh whose native up axis is +Z (like TripoSR's, but this id is not 'triposr', so nothing is assumed)."""

    info = PlumbingEngine.info.__class__(
        **{**PlumbingEngine.info.__dict__, "id": "zup_test_double", "name": "Z-up truck test double (NOT AI)"}
    )

    def generate(self, request: GenerationRequest) -> GenerationOutput:
        t0 = time.perf_counter()
        canonical = truckish()
        rot = fd._UP_TO_Y["+Z"]
        mesh = trimesh.Trimesh(np.asarray(canonical.vertices) @ rot, canonical.faces, process=False)
        request.workdir.mkdir(parents=True, exist_ok=True)
        f = request.workdir / "raw_output.glb"
        mesh.export(f)
        return GenerationOutput(f, "glb", mesh, "cpu", time.perf_counter() - t0, {"test_double": True})


def reference_png() -> bytes:
    mesh = truckish()
    img = render_scene(
        [(mesh, (0.2, 0.35, 0.8, 1.0))],
        azimuth_deg=35,
        elevation_deg=10,
        size=480,
        background=(255, 255, 255),
        fov_deg=6.0,
    )
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


@pytest.fixture
def api(tmp_path):
    c, ctx = make_client(
        tmp_path,
        engines=[ZUpTruckDouble()],
        verified_model_licenses="zup_test_double",
        default_engine="zup_test_double",
    )
    yield c, ctx
    ctx.close()


def test_native_up_is_detected_recorded_and_used_by_the_preparation(api):
    c, ctx = api
    r = c.post(
        "/api/convert",
        files={"file": ("truck.png", reference_png(), "image/png")},
        data={"category": "heavy_truck", "length_m": "6.0"},
    )
    assert r.status_code == 202, r.text
    done = wait(c, r.json()["job"]["job_id"], timeout=180)
    assert done["state"] == "COMPLETED", done.get("error")
    res = done["result"]
    raw = ctx.assets.load_scene(res["raw_version_id"])
    assert raw.manifest.provenance.native_up == "+Z"
    det = raw.reports["generation"]["up_axis_detection"]
    assert det["best_by_silhouette"] == "+Z" and det["confident"]
    # the prepared model stands on its wheels: a truck 6 m long is lower than it is long, not 6 m tall
    h = res["final_extents_m"]
    assert h[2] == pytest.approx(6.0, rel=0.02) and h[1] < h[2], h


def test_triposr_keeps_its_known_frame_without_running_detection():
    from aro_studio.generation.service import GenerationService

    assert GenerationService._detect_up("triposr", trimesh.creation.box(), Image.new("RGBA", (8, 8))) == (None, None)
