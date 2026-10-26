"""Evidence readers must never turn missing, partial or forged-looking evidence into a PASS."""

from __future__ import annotations

import json

from aro_studio.verification import evidence as ev
from aro_studio.verification.components import compute, production_ready


def _unity_doc(**over):
    checks = [{"name": n + " x", "status": "PASS", "detail": ""} for n in ev.REQUIRED_UNITY_CHECKS]
    checks.append({"name": "collider COL_Body mesh", "status": "PASS", "detail": ""})
    d = {
        "schema": 1,
        "unityVersion": "6000.0.23f1",
        "checks": checks,
        "importErrors": [],
        "notVerified": [],
        "overall": "PASS",
    }
    d.update(over)
    return d


def _w(tmp_path, doc):
    p = tmp_path / "u.json"
    p.write_text(json.dumps(doc))
    return p


def test_missing_evidence_is_blocked_never_pass(tmp_path):
    assert ev.read_unity_evidence(tmp_path / "none.json").status == ev.BLOCKED
    assert all(e.status == ev.BLOCKED for e in ev.read_ai_evidence(tmp_path / "none.json"))
    assert ev.read_docker_evidence(tmp_path / "none.json").status == ev.BLOCKED


def test_complete_unity_evidence_passes(tmp_path):
    assert ev.read_unity_evidence(_w(tmp_path, _unity_doc())).status == ev.PASS


def test_unity_evidence_rejections(tmp_path):
    assert ev.read_unity_evidence(_w(tmp_path, _unity_doc(unityVersion="2022.3.1f1"))).status == ev.FAIL
    assert ev.read_unity_evidence(_w(tmp_path, _unity_doc(importErrors=["boom"]))).status == ev.FAIL
    bad = _unity_doc()
    bad["checks"][5]["status"] = "FAIL"
    assert ev.read_unity_evidence(_w(tmp_path, bad)).status == ev.FAIL
    short = _unity_doc()
    short["checks"] = short["checks"][:-3]
    assert ev.read_unity_evidence(_w(tmp_path, short)).status in (ev.FAIL, ev.PARTIAL)
    assert ev.read_unity_evidence(_w(tmp_path, short)).status != ev.PASS
    (tmp_path / "junk.json").write_text("{not json")
    assert ev.read_unity_evidence(tmp_path / "junk.json").status == ev.FAIL


def test_untestable_handedness_is_partial(tmp_path):
    d = _unity_doc()
    for c in d["checks"]:
        if c["name"].startswith("handedness"):
            c["status"] = "NOT_TESTABLE"
    r = ev.read_unity_evidence(_w(tmp_path, d))
    assert r.status == ev.PARTIAL


def test_ai_pass_requires_receipts(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(
        json.dumps({"status": {"real_inference": "PASS", "pipeline": "PASS", "validated_production_asset": "PASS"}})
    )
    real, _, _ = ev.read_ai_evidence(p)
    assert real.status == ev.FAIL and "without a completed" in real.detail


def test_components_report_seven_and_only_all_pass_is_production_ready(tmp_path):
    comps = compute(tmp_path)
    assert len(comps) == 7 and not production_ready(comps)
    assert {c["status"] for c in comps} <= {"PASS", "PARTIAL", "BLOCKED", "FAIL"}
    assert production_ready([{"status": "PASS"}] * 7)
    assert not production_ready([{"status": "PASS"}] * 6 + [{"status": "PARTIAL"}])


def _smoke_doc(**over):
    item = {
        "name": "x",
        "category": "car",
        "result": "PASS",
        "real_inference": {
            "model_ran": True,
            "cache_hit": False,
            "finite": True,
            "output_sha256": "ab" * 32,
            "engine_id": "triposr",
        },
        "export": {"lod_collision_audit": {"ok": True}},
    }
    d = {
        "mode": "real_engine",
        "status": {"real_inference": "PASS", "visual_quality": "PENDING_HUMAN_REVIEW"},
        "items": [dict(item, name=n) for n in "abc"],
        "coverage_problems": [],
        "negative_probe": {"result": "PASS"},
        "blockers": [],
    }
    d.update(over)
    return d


def test_smoke_evidence_rules(tmp_path):
    ok = ev.read_smoke_evidence(_w(tmp_path, _smoke_doc()))
    assert ok.status == ev.PASS and "visual quality" in ok.detail
    assert ev.read_smoke_evidence(tmp_path / "none.json").status == ev.BLOCKED
    assert ev.read_smoke_evidence(_w(tmp_path, _smoke_doc(mode="test_double"))).status == ev.BLOCKED
    cached = _smoke_doc()
    cached["items"][0]["real_inference"]["cache_hit"] = True
    assert ev.read_smoke_evidence(_w(tmp_path, cached)).status == ev.FAIL
    unaudited = _smoke_doc()
    unaudited["items"][1]["export"] = {}
    r = ev.read_smoke_evidence(_w(tmp_path, unaudited))
    assert r.status == ev.FAIL and "audit" in r.detail  # PASS needs the per-LOD / collision audit of every exported GLB
    few = _smoke_doc(items=_smoke_doc()["items"][:2])
    assert ev.read_smoke_evidence(_w(tmp_path, few)).status == ev.FAIL
    assert ev.read_smoke_evidence(_w(tmp_path, _smoke_doc(coverage_problems=["no vehicle image"]))).status == ev.FAIL
    assert ev.read_smoke_evidence(_w(tmp_path, _smoke_doc(status={"real_inference": "PARTIAL"}))).status == ev.PARTIAL


def test_a_real_smoke_pass_does_not_make_the_validated_production_asset_component_pass(tmp_path):
    """Real four-image run: the engine HAS run (component 3 PASS) but no asset is a validated production asset (component 4)."""
    d = tmp_path / "docs" / "acceptance" / "evidence" / "ai" / "smoke"
    d.mkdir(parents=True)
    (d / "smoke-evidence.json").write_text(json.dumps(_smoke_doc()))
    comps = {c["component"][0]: c for c in compute(tmp_path)}
    assert comps["3"]["status"] == "PASS"
    assert comps["4"]["status"] == "PARTIAL" and "never been run" not in comps["4"]["detail"]
    assert "none is a validated production asset" in comps["4"]["detail"]
    assert not production_ready(list(comps.values()))
