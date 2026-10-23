"""Yaw alignment, dimension fitting and the smoothing step of the AI preparation pipeline."""

from __future__ import annotations

import numpy as np
import pytest
import trimesh

from aro_studio.core.errors import InvalidInputError
from aro_studio.geometry import ops


def _yawed_box(yaw_deg: float, length=3.0, width=1.0, height=1.0):
    """A box whose long side lies along +Z in its own frame, then rotated about Y by ``yaw_deg``."""
    box = trimesh.creation.box(extents=[width, height, length])
    box.apply_transform(trimesh.transformations.rotation_matrix(np.radians(yaw_deg), [0, 1, 0]))
    return box


@pytest.mark.parametrize("yaw", [0, 10, 30, 38, -25, 44, -44, 60, 90, 135])
def test_a_yawed_footprint_is_squared_up_with_the_long_side_on_z(yaw):
    box = _yawed_box(yaw)
    m, info = ops.footprint_yaw_matrix(np.asarray(box.vertices))
    aligned = box.copy()
    if m is not None:
        aligned.apply_transform(m)
    ext = aligned.extents
    assert ext[2] == pytest.approx(3.0, abs=1e-6) and ext[0] == pytest.approx(1.0, abs=1e-6), (yaw, info, ext)


def test_the_smallest_rotation_is_used_so_the_front_guess_is_kept():
    box = _yawed_box(20)
    m, info = ops.footprint_yaw_matrix(np.asarray(box.vertices))
    assert info["aligned"] and abs(info["yaw_deg"]) <= 90
    assert np.linalg.det(m[:3, :3]) == pytest.approx(1.0)  # a proper rotation, never a mirror


def test_a_nearly_square_footprint_is_left_alone_and_says_why():
    m, info = ops.footprint_yaw_matrix(np.asarray(trimesh.creation.box(extents=[1.0, 1.0, 1.05]).vertices))
    assert m is None and not info["aligned"] and "nearly square" in info["reason"]


def test_the_pipeline_scene_ops_align_and_fit_and_refuse_when_colliders_exist():
    from aro_studio.geometry.pipeline import _scene_op
    from tests.conftest import make_scene_from_mesh

    scene = make_scene_from_mesh(_yawed_box(30), category="heavy_truck")
    out, rep = _scene_op(scene, "align_yaw", {}, "vehicles")
    assert rep["aligned"] and out.meshes[next(iter(out.meshes))].extents[2] == pytest.approx(3.0, abs=1e-4)
    fitted, rep = _scene_op(out, "fit_dimensions", {"width_m": 2.0, "height_m": 1.5, "length_m": 6.0}, "vehicles")
    ext = np.asarray(fitted.meshes[next(iter(fitted.meshes))].extents)
    assert ext == pytest.approx([2.0, 1.5, 6.0], abs=1e-4)
    assert set(rep["distortion_vs_uniform"]) == {"width", "height", "length"}
    with pytest.raises(InvalidInputError):
        _scene_op(out, "fit_dimensions", {}, "vehicles")  # nothing to fit
