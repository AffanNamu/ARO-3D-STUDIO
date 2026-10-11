"""The smoke harness: wiring is proven with a test double; the REAL path must report BLOCKED when it cannot run."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "real_inference_smoke.py"


def _manifest(tmp_path, specs):
    items = []
    for i, (name, cat, col) in enumerate(specs):
        im = Image.new("RGB", (320, 240), (235, 235, 235))
        ImageDraw.Draw(im).rectangle([80 + i, 60, 240, 200], fill=col)
        im.save(tmp_path / f"{name}.png")
        items.append({"path": f"{name}.png", "category": cat, "name": name})
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps({"items": items}))
    return m


def _run(args, tmp_path):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=ROOT, timeout=600)


def test_double_mode_proves_wiring_but_never_claims_inference(tmp_path):
    m = _manifest(
        tmp_path, [("a", "heavy_truck", (200, 40, 40)), ("b", "furniture", (40, 80, 200)), ("c", "prop", (40, 200, 80))]
    )
    r = _run(["--manifest", str(m), "--out", str(tmp_path / "out"), "--double"], tmp_path)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
    ev = json.loads((tmp_path / "out" / "smoke-evidence.json").read_text())
    assert ev["mode"] == "test_double" and ev["status"]["wiring_selftest"] == "PASS"
    assert str(ev["status"]["real_inference"]).startswith("NOT_RUN")
    assert ev["negative_probe"]["result"] == "PASS"  # invalid file rejected, valid siblings still queued
    for it in ev["items"]:
        assert it["result"] == "PASS" and it["raw_immutable"] and it["real_inference"]["finite"]
        assert it["human_review"]["status"] == "PENDING_HUMAN_REVIEW"  # quality is never auto-judged
        assert it["export"]["sha256_matches_record"] and it["preparation"]["steps"]


def test_real_mode_reports_blocked_when_the_engine_cannot_run(tmp_path):
    from aro_studio.engines.triposr import TripoSREngine

    if TripoSREngine().availability("cpu").ok:
        pytest.skip("TripoSR is runnable here; the real smoke test would run for real")
    m = _manifest(
        tmp_path, [("a", "heavy_truck", (200, 40, 40)), ("b", "furniture", (40, 80, 200)), ("c", "prop", (40, 200, 80))]
    )
    r = _run(["--manifest", str(m), "--out", str(tmp_path / "out")], tmp_path)
    assert r.returncode == 3, r.stdout[-1500:] + r.stderr[-1500:]
    ev = json.loads((tmp_path / "out" / "smoke-evidence.json").read_text())
    assert ev["mode"] == "real_engine" and ev["status"]["real_inference"] == "BLOCKED"
    assert ev["blockers"] and "engine not runnable" in ev["blockers"][0] and not ev["items"]


def test_coverage_rules_require_three_images_with_vehicle_and_non_vehicle(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import real_inference_smoke as smoke

    two_vehicles = [
        {"category": "car", "abs_path": tmp_path / "x.png"},
        {"category": "bus", "abs_path": tmp_path / "y.png"},
    ]
    Image.new("RGB", (8, 8), (1, 2, 3)).save(tmp_path / "x.png")
    Image.new("RGB", (8, 8), (9, 9, 9)).save(tmp_path / "y.png")
    probs = " ".join(smoke.coverage_problems(two_vehicles))
    assert "at least 3" in probs and "no non-vehicle" in probs
