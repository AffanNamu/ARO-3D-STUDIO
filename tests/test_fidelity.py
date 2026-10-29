"""Reference-fidelity metrics: they must measure what they claim to (a valid GLB is not a good result)."""

from __future__ import annotations

import numpy as np
import pytest
import trimesh
from PIL import Image

from aro_studio.quality import fidelity as fd
from aro_studio.utils.render import render_scene


def truckish(length=6.0, width=2.5, height=3.0) -> trimesh.Trimesh:
    """Asymmetric on purpose: a long low chassis with a tall cab at ONE end and four wheel blocks (Z = length, Y up)."""
    parts = [
        trimesh.creation.box((width, height * 0.3, length)).apply_translation((0, height * 0.35, 0)),
        trimesh.creation.box((width, height * 0.7, length * 0.28)).apply_translation((0, height * 0.5, length * 0.36)),
    ]
    for x in (-width / 2, width / 2):
        for z in (-length * 0.3, length * 0.2):
            parts.append(
                trimesh.creation.box((0.3, height * 0.28, height * 0.28)).apply_translation(
                    (x * 0.94, height * 0.14, z)
                )
            )
    return trimesh.util.concatenate(parts)


def reference_mask_from(mesh: trimesh.Trimesh, az: float, el: float) -> np.ndarray:
    """A high-resolution orthographic silhouette stands in for a cut-out photo."""
    m, _ = fd.silhouette(np.asarray(mesh.vertices), np.asarray(mesh.faces), az, el, size=512)
    return m


def test_camera_convention_matches_the_studio_renderer():
    """An angle found by the search must reproduce the same view in the contact sheet (no mirrored or rotated azimuth)."""
    mesh = truckish()
    az, el = 40.0, 15.0
    img = render_scene(
        [(mesh, (0.2, 0.4, 0.9, 1.0))], azimuth_deg=az, elevation_deg=el, size=384, background=(0, 0, 0), fov_deg=2.0
    )
    rendered = np.asarray(img.convert("L")) > 8  # a 2-degree field of view is near-orthographic
    ref, _ = fd.normalise_mask(rendered, fd.SIZE)
    v, f = np.asarray(mesh.vertices), np.asarray(mesh.faces)
    same, _ = fd.silhouette(v, f, az, el)
    mirrored, _ = fd.silhouette(v, f, -az, el)
    assert fd.iou(same, ref) > 0.93, fd.iou(same, ref)
    assert fd.iou(mirrored, ref) < fd.iou(same, ref) - 0.05


@pytest.mark.parametrize("az,el", [(35.0, 10.0), (140.0, 20.0), (250.0, 5.0)])
def test_the_view_search_recovers_a_known_camera(az, el):
    mesh = truckish()
    bv = fd.best_view(mesh, reference_mask_from(mesh, az, el))
    assert bv.iou > 0.93
    diff = abs((bv.azimuth_deg - az + 180) % 360 - 180)
    assert diff <= 6 and abs(bv.elevation_deg - el) <= 6, (bv, az, el)


def test_wrong_proportions_score_lower_than_right_ones_against_the_same_reference():
    right = truckish()
    stubby = truckish(length=3.2, width=2.5, height=3.0)  # the TripoSR failure mode: too short for its width/height
    ref = reference_mask_from(right, 40.0, 10.0)
    good, bad = fd.best_view(right, ref), fd.best_view(stubby, ref)
    assert good.iou > bad.iou + 0.08, (good.iou, bad.iou)
    assert good.aspect_error < 0.05 < bad.aspect_error


def test_a_different_object_scores_far_below_the_right_one():
    ref = reference_mask_from(truckish(), 40.0, 10.0)
    ball = trimesh.creation.icosphere(subdivisions=3)
    assert fd.best_view(ball, ref).iou < 0.6 < fd.best_view(truckish(), ref).iou


def test_proportion_bands_are_explicit_and_flag_implausible_vehicles():
    ok = fd.proportion_check((1.8, 1.5, 4.5), "car")
    assert ok["verdict"] == "plausible" and ok["bands_are_heuristic"]
    stubby = fd.proportion_check((0.96, 0.72, 1.0), "heavy_truck")  # what TripoSR produced (width ~ length)
    assert stubby["verdict"] == "implausible" and stubby["inside"]["width_over_length"] is False
    assert fd.proportion_check((1, 1, 1), "furniture")["verdict"] == "not_applicable"
    assert fd.proportion_check((1.8, 1.5, 4.5), "suv")["class"] == "car"  # alias


def test_score_model_reports_the_numbers_and_the_caveats(monkeypatch):
    mesh = truckish()
    ref_mask = reference_mask_from(mesh, 40.0, 10.0)
    monkeypatch.setattr(fd, "reference_mask", lambda image: ref_mask)
    rep = fd.score_model(mesh, Image.new("RGB", (64, 64)), "heavy_truck")
    assert (
        rep.silhouette_iou > 0.93
        and rep.proportions["class"] == "heavy_truck"
        and rep.mesh["triangles"] == len(mesh.faces)
    )
    assert any("orthographic" in n for n in rep.notes) and any("not measured" in n for n in rep.notes)
    assert rep.meets_floor is True  # right outline AND proportions inside the band


def test_a_good_outline_with_stubby_depth_does_not_meet_the_floor():
    """The measured TripoSR failure: the outline matches the photo from some camera, the proportions are wrong."""
    stubby = truckish(length=3.0, width=2.5, height=3.0)
    ref = reference_mask_from(stubby, 40.0, 10.0)  # a photo of THIS stubby model: perfect outline
    bv = fd.best_view(stubby, ref)
    assert bv.iou > 0.95
    p = fd.proportion_check(tuple(float(x) for x in stubby.extents[:3]), "heavy_truck")
    assert p["verdict"] == "implausible" and not (bv.iou >= fd.IOU_FLOOR and p["verdict"] != "implausible")


@pytest.mark.parametrize("native_up", ["+Y", "-Y", "+Z", "-Z", "+X", "-X"])
def test_up_axis_is_recovered_from_the_reference_silhouette(native_up):
    """An engine may emit any frame. Rotating the mesh into each of the six possible ones, the reference match must name the right one."""
    canonical = truckish()
    ref = reference_mask_from(canonical, 35.0, 10.0)
    rot = fd._UP_TO_Y[native_up]  # carries the native up axis onto +Y
    native = trimesh.Trimesh(np.asarray(canonical.vertices) @ rot, canonical.faces, process=False)
    res = fd.detect_up_axis(native, ref)
    assert res["best_by_silhouette"] == native_up, res
    assert res["confident"] and res["up"] == native_up


def test_up_axis_keeps_the_hint_when_the_shape_is_ambiguous():
    ball = trimesh.creation.icosphere(subdivisions=3)
    ref = reference_mask_from(ball, 0.0, 10.0)
    res = fd.detect_up_axis(ball, ref, hint="+Z")
    assert not res["confident"] and res["up"] == "+Z" and res["used_hint"]


def fragmented_textured(n: int = 60, texture: int = 1024) -> trimesh.Trimesh:
    """n disjoint boxes sharing one large texture: what a real engine mesh with loose fragments looks like after UV baking."""
    boxes = [trimesh.creation.box((0.2, 0.2, 0.2)).apply_translation((i * 0.5, 0, 0)) for i in range(n)]
    m: trimesh.Trimesh = trimesh.util.concatenate(boxes)  # type: ignore[assignment]
    img = Image.fromarray(np.random.default_rng(0).integers(0, 255, (texture, texture, 3), dtype=np.uint8))
    m.visual = trimesh.visual.TextureVisuals(
        uv=np.random.default_rng(1).random((len(m.vertices), 2)),
        material=trimesh.visual.material.PBRMaterial(baseColorTexture=img),
    )
    return m


def test_component_count_matches_split_but_never_builds_a_submesh_per_fragment(monkeypatch):
    """REGRESSION (Colab, 2026-10-29): mesh_summary used mesh.split(), which copies the texture once per fragment: 9.3 GB, killed by the
    12.7 GB limit. The count must be the same number without creating submeshes."""
    m = fragmented_textured(40, 256)
    expected = len(m.split(only_watertight=False))
    assert expected == 40
    monkeypatch.setattr(
        trimesh.Trimesh, "split", lambda *a, **k: (_ for _ in ()).throw(AssertionError("split() copies the texture"))
    )
    assert fd.component_count(m) == 40
    assert fd.mesh_summary(m)["components"] == 40
    assert fd.component_count(trimesh.Trimesh()) == 0
    one = trimesh.creation.icosphere()
    assert fd.component_count(one) == 1


def test_scoring_a_fragmented_textured_model_stays_within_a_small_memory_budget(tmp_path):
    """Measured in a fresh process (peak resident memory is per process): 120 fragments x a 2048 px texture was 2 GB+ with split()."""
    import subprocess
    import sys
    import textwrap

    code = textwrap.dedent(
        f"""
        import resource, sys
        sys.path.insert(0, {str(__import__("pathlib").Path(__file__).resolve().parents[1])!r})
        sys.path.insert(0, {str(__import__("pathlib").Path(__file__).resolve().parent.parent)!r})
        from tests.test_fidelity import fragmented_textured
        from aro_studio.quality import fidelity as fd
        m = fragmented_textured(120, 2048)
        base = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e3
        s = fd.mesh_summary(m)
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e3
        print(s["components"], round(peak - base))
        """
    )
    r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=300)  # noqa: S603
    assert r.returncode == 0, r.stderr[-800:]
    components, extra_mb = (int(x) for x in r.stdout.split()[-2:])
    assert components == 120
    assert extra_mb < 300, f"summarising used {extra_mb} MB on top of the model"
