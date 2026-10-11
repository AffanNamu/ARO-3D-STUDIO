"""Regression tests for recording real-inference pipeline evidence."""

from __future__ import annotations

from scripts.record_real_inference import summarize_pipeline_steps


def test_summarize_pipeline_steps_accepts_current_steprecord_schema():
    rows = summarize_pipeline_steps(
        [
            {"step": "geometry: orient", "status": "PASS", "seconds": 0.25, "version_id": "v1", "detail": {}},
            {"step": "textures: bake", "status": "FAIL", "seconds": 0.5, "detail": {"error": "unwrap failed"}},
        ]
    )
    assert rows == [
        {"name": "geometry: orient", "status": "PASS", "seconds": 0.25},
        {
            "name": "textures: bake",
            "status": "FAIL",
            "seconds": 0.5,
            "detail": {"error": "unwrap failed"},
        },
    ]


def test_summarize_pipeline_steps_accepts_legacy_name_field():
    assert summarize_pipeline_steps([{"name": "legacy step", "status": "PASS", "seconds": 0.1}]) == [
        {"name": "legacy step", "status": "PASS", "seconds": 0.1}
    ]


def test_summarize_pipeline_steps_ignores_non_dict_entries():
    assert summarize_pipeline_steps([None, "bad record", {"step": "ok", "status": "PASS", "seconds": 0.1}]) == [
        {"name": "ok", "status": "PASS", "seconds": 0.1}
    ]
