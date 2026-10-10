"""Convex-hull reduction must terminate within budget for smooth, high-vertex surfaces."""

from __future__ import annotations

import numpy as np
import trimesh

from aro_studio.collision.generate import MAX_CONVEX_TRIANGLES, convex_hull


def test_smooth_blob_hull_respects_triangle_budget():
    blob = trimesh.creation.icosphere(subdivisions=6)
    blob.apply_scale([1.0, 0.45, 0.4])
    hull = convex_hull(blob)
    assert 4 <= len(hull.faces) <= MAX_CONVEX_TRIANGLES
    assert hull.is_watertight
    # The reduced hull stays inside the true hull and keeps nearly the same extents.
    ratio = hull.volume / blob.convex_hull.volume
    assert 0.9 < ratio <= 1.0001
    assert np.allclose(hull.extents, blob.extents, rtol=0.05)


def test_small_input_hull_unchanged():
    box = trimesh.creation.box(extents=(1, 2, 3))
    assert len(convex_hull(box).faces) == 12
