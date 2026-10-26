"""Reference-image projection texturing: colours must land where the photo shows them, and the unseen side must be flagged as inferred."""

from __future__ import annotations

import numpy as np
import pytest
import trimesh
from PIL import Image

from aro_studio.texturing.projection import project_reference
from aro_studio.utils.render import render_scene
from tests.test_fidelity import truckish


def known_colour(v: np.ndarray, length=6.0, height=3.0) -> np.ndarray:
    """A smooth colour field, symmetric left-right (x -> -x), so the mirrored side has a known right answer."""
    r = np.clip(v[:, 2] / length + 0.5, 0, 1)  # red grows towards the front
    g = np.clip(v[:, 1] / height, 0, 1)  # green grows with height
    b = np.clip(0.2 + 0.6 * (np.abs(v[:, 0]) / 1.25), 0, 1)  # blue grows towards the sides
    return np.stack([r, g, b], axis=1)


@pytest.fixture(scope="module")
def dense_truck() -> trimesh.Trimesh:
    m = truckish().subdivide_to_size(0.12, max_iter=6)
    assert len(m.vertices) > 8_000
    return m


def reference_photo(mesh: trimesh.Trimesh, az: float, el: float) -> Image.Image:
    col = known_colour(np.asarray(mesh.vertices))
    face_col = col[np.asarray(mesh.faces)].mean(axis=1)
    img = render_scene(
        [(mesh, face_col)],
        azimuth_deg=az,
        elevation_deg=el,
        size=640,
        fov_deg=3.0,
        background=(255, 255, 255),
        shaded=False,
    ).convert("RGB")
    arr = np.asarray(img)
    alpha = (np.abs(arr.astype(int) - 255).sum(axis=2) > 12).astype(np.uint8) * 255
    return Image.fromarray(np.dstack([arr, alpha]), "RGBA")


def test_visible_colours_come_from_the_photo_with_a_known_camera(dense_truck):
    photo = reference_photo(dense_truck, 35.0, 10.0)
    cols, rep = project_reference(dense_truck, photo, camera=(35.0, 10.0))
    truth = known_colour(np.asarray(dense_truck.vertices)) * 255
    assert cols.shape == (len(dense_truck.vertices), 4) and (cols[:, 3] == 255).all()
    err = np.abs(cols[:, :3].astype(float) - truth).mean(axis=1) / 255
    # the vertices facing this camera head-on are the ones the photo actually shows
    _, to_cam = (
        None,
        np.array(
            [
                np.sin(np.radians(35)) * np.cos(np.radians(10)),
                np.sin(np.radians(10)),
                np.cos(np.radians(35)) * np.cos(np.radians(10)),
            ]
        ),
    )
    facing = np.asarray(dense_truck.vertex_normals) @ to_cam > 0.8
    assert facing.sum() > 500
    assert err[facing].mean() < 0.06, err[facing].mean()
    assert 0.1 < rep.seen_fraction < 0.8 and rep.mirrored_fraction > 0.05
    assert any("mirroring" in n for n in rep.notes)


def test_the_camera_is_found_from_the_silhouette_when_not_given(dense_truck):
    photo = reference_photo(dense_truck, 140.0, 15.0)
    cols, rep = project_reference(dense_truck, photo)
    assert rep.silhouette_iou > 0.9
    truth = known_colour(np.asarray(dense_truck.vertices)) * 255
    err = np.abs(cols[:, :3].astype(float) - truth).mean(axis=1) / 255
    assert err.mean() < 0.12, err.mean()  # everything, including the inferred and filled surfaces


def test_without_symmetry_the_unseen_side_is_filled_not_mirrored(dense_truck):
    photo = reference_photo(dense_truck, 35.0, 10.0)
    _, rep = project_reference(dense_truck, photo, camera=(35.0, 10.0), symmetric=False)
    assert rep.mirrored_fraction == 0.0 and rep.filled_fraction > 0.3
    assert not any("mirroring" in n for n in rep.notes)


def test_an_empty_cutout_is_refused(dense_truck):
    with pytest.raises(ValueError, match="empty"):
        project_reference(dense_truck, Image.new("RGBA", (64, 64), (0, 0, 0, 0)))
