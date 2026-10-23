import io

import numpy as np
import pytest
from PIL import Image, ImageDraw

from aro_studio.core.errors import InvalidInputError
from aro_studio.imaging.analysis import analyze
from aro_studio.imaging.matting import (
    REMBG_ALLOWED_MODELS,
    REMBG_DEFAULT_MODEL,
    BorderColorMatte,
    RembgRemover,
    background_stats,
    rembg_model_name,
)
from aro_studio.imaging.preprocess import PreprocessOptions, preprocess
from aro_studio.imaging.validate import load_image

LIM = dict(max_bytes=25_000_000, max_pixels=64_000_000, min_side=64)


def png(im: Image.Image, **kw) -> bytes:
    b = io.BytesIO()
    im.save(b, "PNG", **kw)
    return b.getvalue()


def test_valid_image_report(concept_png):
    img, rep = load_image(concept_png, **LIM)
    assert (rep.width, rep.height, rep.format) == (800, 600, "png")
    assert 0 <= rep.quality_score <= 1 and not rep.has_alpha


def test_rejects_non_image_and_corrupt(concept_png):
    with pytest.raises(InvalidInputError):
        load_image(b"GIF89a" + b"0" * 100, **LIM)
    with pytest.raises(InvalidInputError, match="corrupt"):
        load_image(concept_png[: len(concept_png) // 2], **LIM)  # truncated PNG
    with pytest.raises(InvalidInputError):
        load_image(concept_png, max_bytes=100, max_pixels=10**9, min_side=1)


def test_rejects_too_small_and_too_many_pixels(concept_png):
    small = png(Image.new("RGB", (32, 32), "white"))
    with pytest.raises(InvalidInputError, match="too small"):
        load_image(small, **LIM)
    with pytest.raises(InvalidInputError, match="MP"):
        load_image(concept_png, max_bytes=10**9, max_pixels=1000, min_side=1)


def test_exif_orientation_applied():
    im = Image.new("RGB", (200, 100), (240, 240, 240))
    ImageDraw.Draw(im).rectangle((10, 10, 60, 90), fill=(200, 0, 0))
    exif = im.getexif()
    exif[0x0112] = 6  # rotate 270 CW to display
    b = io.BytesIO()
    im.save(b, "JPEG", exif=exif)
    img, rep = load_image(b.getvalue(), **LIM)
    assert rep.exif_orientation == 6 and rep.needs_rotation
    pre = preprocess(img)
    assert pre.steps[0]["size"] == [100, 200]  # width/height swapped by orientation correction


def test_transparency_detected():
    im = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse((50, 50, 150, 150), fill=(200, 10, 10, 255))
    _, rep = load_image(png(im), **LIM)
    assert rep.has_alpha and 0.4 < rep.transparent_fraction < 0.8


def test_blurry_and_flat_images_warn():
    flat = Image.new("RGB", (400, 400), (128, 128, 128))
    _, rep = load_image(png(flat), **LIM)
    assert any("blurry" in w or "contrast" in w for w in rep.warnings) and rep.quality_score < 1


def test_border_matte_keeps_interior_holes(concept_png):
    img, _ = load_image(concept_png, **LIM)
    out = BorderColorMatte().remove(img)
    a = np.asarray(out.getchannel("A"))
    assert a[300, 400] > 200  # body
    assert a[10, 10] < 30  # background removed
    assert a[275, 330] > 200  # same colour as background but enclosed -> kept (window)


def test_background_stats_uniform_vs_noisy():
    assert background_stats(Image.new("RGB", (100, 100), (200, 200, 200)))["uniform"]
    rng = np.random.default_rng(0)
    noisy = Image.fromarray(rng.integers(0, 255, (100, 100, 3), dtype=np.uint8))
    assert not background_stats(noisy)["uniform"]


def test_preprocess_output_contract(concept_png):
    img, _ = load_image(concept_png, **LIM)
    pre = preprocess(img, PreprocessOptions(output_size=512, foreground_ratio=0.8))
    assert pre.image.size == (512, 512) and pre.image.mode == "RGB"
    arr = pre.to_model_array()
    assert arr.dtype == np.float32 and arr.min() >= 0.0 and arr.max() <= 1.0
    # corners are the neutral grey background (0.5)
    assert abs(arr[2, 2].mean() - 0.5) < 0.02
    # subject occupies ~foreground_ratio of the canvas
    nonbg = np.abs(arr - 0.5).sum(axis=2) > 0.05
    ys, xs = np.where(nonbg)
    assert 0.7 * 512 < max(xs.max() - xs.min(), ys.max() - ys.min()) < 0.85 * 512
    assert [s["step"] for s in pre.steps] == [
        "orientation",
        "background_analysis",
        "background_removal",
        "crop",
        "resize",
        "normalize",
    ]


def test_preprocess_uses_existing_alpha():
    im = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    ImageDraw.Draw(im).rectangle((100, 100, 200, 200), fill=(10, 200, 10, 255))
    pre = preprocess(im)
    assert any(s.get("method") == "existing_alpha" for s in pre.steps)


def test_rembg_reports_unavailable_without_pretending():
    ok, why = RembgRemover().available()
    if not ok:
        assert "rembg" in why
        with pytest.raises(Exception, match="rembg"):
            RembgRemover().remove(Image.new("RGB", (64, 64)))


def test_rembg_model_is_chosen_explicitly_never_the_package_default(monkeypatch):
    monkeypatch.delenv("ARO_REMBG_MODEL", raising=False)
    assert rembg_model_name() == REMBG_DEFAULT_MODEL == "u2net"
    for ok in REMBG_ALLOWED_MODELS:
        monkeypatch.setenv("ARO_REMBG_MODEL", ok)
        assert rembg_model_name() == ok


@pytest.mark.parametrize("name", ["bria-rmbg", "BRIA-RMBG-2.0", "briaai", "silueta", "", "u2net_human_seg"])
def test_rembg_blocked_and_unknown_models_are_refused_before_any_download(monkeypatch, name):
    monkeypatch.setenv("ARO_REMBG_MODEL", name)
    with pytest.raises(InvalidInputError):
        rembg_model_name()


def test_rembg_remover_passes_the_pinned_model_to_rembg_and_records_it(monkeypatch):
    import sys
    import types

    seen: list[str | None] = []
    fake = types.ModuleType("rembg")

    def new_session(model=None, *a, **k):
        seen.append(model)
        return object()

    fake.new_session = new_session  # type: ignore[attr-defined]
    fake.remove = lambda im, session=None: im  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "rembg", fake)
    monkeypatch.delenv("ARO_REMBG_MODEL", raising=False)
    r = RembgRemover()
    r.remove(Image.new("RGB", (64, 64)))
    assert seen == ["u2net"] and r.model_name == "u2net"
    monkeypatch.setenv("ARO_REMBG_MODEL", "bria-rmbg")
    with pytest.raises(InvalidInputError):
        RembgRemover().remove(Image.new("RGB", (64, 64)))
    assert seen == ["u2net"]  # the blocked model never reached rembg


def test_analysis_does_not_invent_category(concept_png):
    img, _ = load_image(concept_png, **LIM)
    a = analyze(img, declared_category_group="vehicles")
    assert a.classification is None  # no classifier registered -> no fabricated category/confidence
    assert a.background_type == "uniform" and a.recommended_mode == "vehicle"
    assert any("classifier" in n for n in a.notes)
