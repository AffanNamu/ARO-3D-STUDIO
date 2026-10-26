"""The bake-off script's parsing and reporting (the engine runs themselves need a GPU worker; see tests/test_remote_engine.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "engine_bakeoff", Path(__file__).resolve().parents[1] / "scripts" / "engine_bakeoff.py"
)
assert SPEC and SPEC.loader
bakeoff = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bakeoff)


@pytest.mark.parametrize(
    "text, image, category, length",
    [
        ("truck.png:heavy_truck:7.0", "truck.png", "heavy_truck", 7.0),
        ("truck.png:heavy_truck", "truck.png", "heavy_truck", None),
        ("ARO 480 Truck at Golden Hour.png:heavy_truck:6.5", "ARO 480 Truck at Golden Hour.png", "heavy_truck", 6.5),
        ("C:\\imgs\\suv.png:car:4.5", "C:\\imgs\\suv.png", "car", 4.5),
    ],
)
def test_case_parsing(text, image, category, length):
    assert bakeoff.parse_case(text) == (Path(image), category, length)


def test_case_without_a_category_is_refused():
    with pytest.raises(SystemExit):
        bakeoff.parse_case("truck.png")


def test_summary_table_never_hides_a_failure():
    rows = [
        {"engine": "trellis2", "image": "a.png", "status": "FAIL", "reason": "GPU out of memory"},
        {"engine": "triposg", "image": "a.png", "status": "BLOCKED", "reason": "licence not verified"},
        {
            "engine": "trellis2",
            "image": "b.png",
            "status": "PASS",
            "ratios": {"width_over_length": 0.4, "height_over_length": 0.35},
            "silhouette_iou": 0.9,
            "proportions": "plausible",
            "meets_floor": True,
            "prepared_triangles": 30000,
            "prepared_components": 1,
            "validation": "NEEDS_REVIEW",
            "total_seconds": 90.0,
        },
    ]
    md = bakeoff.markdown(rows)
    assert "**FAIL**" in md and "GPU out of memory" in md and "**BLOCKED**" in md and "PENDING human review" in md
    assert (
        "| trellis2 | b.png | **PASS** | 0.90 | 0.40 | 0.35 | plausible | yes | 30000 | 1 | NEEDS_REVIEW | 90.0 |" in md
    )
