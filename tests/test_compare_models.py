"""The ARO-vs-other-model comparison: measured facts only, a blind mode that really hides the labels, and no winner declared."""

from __future__ import annotations

import json
import random

import numpy as np
import pytest
import trimesh
from PIL import Image, ImageDraw

from aro_studio.quality.compare import compare, face_colours, load_model, main


def reference_box(path):
    """A side view of a long box (length 3 x height 1) on a plain background."""
    im = Image.new("RGB", (900, 500), (240, 240, 240))
    ImageDraw.Draw(im).rectangle((150, 175, 750, 375), fill=(40, 40, 40))
    im.save(path)
    return path


def glb(path, mesh):
    path.write_bytes(bytes(trimesh.Scene(mesh).export(file_type="glb")))
    return path


def test_the_closer_shape_scores_higher_and_proportions_ignore_facing(tmp_path):
    ref = reference_box(tmp_path / "ref.png")
    long_box = glb(tmp_path / "box.glb", trimesh.creation.box((0.9, 1.0, 3.0)))  # length along Z
    turned = glb(tmp_path / "turned.glb", trimesh.creation.box((3.0, 1.0, 0.9)))  # same box, length along X
    ball = glb(tmp_path / "ball.glb", trimesh.creation.icosphere(subdivisions=2))
    data = compare(ref, [("Box", long_box), ("Turned", turned), ("Ball", ball)], "other", tmp_path / "out")
    m = data["models"]
    assert m["Box"]["silhouette_iou"] > m["Ball"]["silhouette_iou"] + 0.2
    assert (
        m["Box"]["proportions"]["ratios"]
        == m["Turned"]["proportions"]["ratios"]
        == {"width_over_length": 0.3, "height_over_length": 0.333}
    )
    assert (
        abs(m["Box"]["silhouette_iou"] - m["Turned"]["silhouette_iou"]) < 0.02
    )  # facing another axis is not a penalty
    for f in ("comparison.png", "comparison.json", "comparison.md"):
        assert (tmp_path / "out" / f).is_file()
    md = (tmp_path / "out" / "comparison.md").read_text()
    assert "Nothing here measures how good the surface" in md and "winner" not in md.lower()


def test_blind_mode_hides_labels_everywhere_but_the_key(tmp_path):
    ref = reference_box(tmp_path / "ref.png")
    a = glb(tmp_path / "aro_model.glb", trimesh.creation.box((0.9, 1.0, 3.0)))
    b = glb(tmp_path / "meshy_model.glb", trimesh.creation.icosphere(subdivisions=2))
    out = tmp_path / "blind"
    data = compare(ref, [("ARO", a), ("Meshy", b)], "other", out, blind=True, rng=random.Random(3))
    assert set(data["models"]) == {"Model A", "Model B"}
    key = json.loads((out / "key.json").read_text())
    assert sorted(key.values()) == ["ARO", "Meshy"]
    for f in ("comparison.json", "comparison.md"):
        text = (out / f).read_text()
        assert (
            "ARO" not in text.replace("ARO_", "")
            and "Meshy" not in text
            and "aro_model" not in text
            and "meshy_model" not in text
        )
    # the key maps back to the right model: the box is the one with the better outline
    box_label = next(k for k, v in key.items() if v == "ARO")
    other = next(k for k in key if k != box_label)
    assert data["models"][box_label]["silhouette_iou"] > data["models"][other]["silhouette_iou"]


def test_lod_and_collision_meshes_are_not_counted_as_the_model(tmp_path):
    scene = trimesh.Scene()
    scene.add_geometry(trimesh.creation.icosphere(subdivisions=3), node_name="Car_LOD0", geom_name="Car_LOD0")
    scene.add_geometry(trimesh.creation.icosphere(subdivisions=1), node_name="Car_LOD1", geom_name="Car_LOD1")
    scene.add_geometry(trimesh.creation.box((2, 2, 2)), node_name="COL_Hull", geom_name="COL_Hull")
    p = tmp_path / "game.glb"
    p.write_bytes(bytes(scene.export(file_type="glb")))
    m = load_model("ARO", p)
    assert (
        len(m.mesh.faces) == 1280
        and m.facts["lod_levels"] == 2
        and m.facts["collision_mesh"] is True
        and m.facts["meshes"] == 1
    )


def test_colours_come_from_the_texture_or_fall_back_to_grey():
    box = trimesh.creation.box((1, 1, 1))
    uv = np.column_stack([np.full(len(box.vertices), 0.25), np.full(len(box.vertices), 0.75)])
    tex = Image.new("RGB", (2, 2), (0, 0, 255))
    tex.putpixel((0, 0), (255, 0, 0))  # top-left: u=0.25 is the left column, v=0.75 (v points up) the top row
    box.visual = trimesh.visual.TextureVisuals(uv=uv, image=tex)
    assert np.allclose(face_colours(box)[0], [1.0, 0.0, 0.0])
    plain = trimesh.creation.box((1, 1, 1))
    assert face_colours(plain).shape == (12, 3)


def test_cli_rejects_bad_specs_and_duplicate_labels(tmp_path, capsys):
    ref = reference_box(tmp_path / "ref.png")
    a = glb(tmp_path / "a.glb", trimesh.creation.box((1, 1, 3)))
    with pytest.raises(SystemExit):
        main(["--reference", str(ref), "--model", "no-equals-sign", "--out", str(tmp_path / "o")])
    with pytest.raises(SystemExit):
        main(["--reference", str(ref), "--model", f"X={tmp_path / 'missing.glb'}", "--out", str(tmp_path / "o")])
    with pytest.raises(ValueError, match="unique"):
        compare(ref, [("Same", a), ("Same", a)], "other", tmp_path / "o")
    assert main(["--reference", str(ref), "--model", f"Only={a}", "--out", str(tmp_path / "o")]) == 0
    assert "outline" in capsys.readouterr().out
