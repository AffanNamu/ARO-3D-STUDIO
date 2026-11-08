"""The competitive tracker must stay honest: fixed vocabulary, all required fields, evidence for strong claims, Markdown in sync.

A capability is only complete when the whole user workflow works. These tests do not judge the product; they stop the tracker from
quietly claiming more than it can show.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "docs" / "cto" / "competitive-matrix.json").read_text(encoding="utf-8"))
CAPS = DATA["capabilities"]

spec = importlib.util.spec_from_file_location(
    "build_competitive_matrix", ROOT / "scripts" / "build_competitive_matrix.py"
)
assert spec and spec.loader
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

REQUIRED = {
    "id", "category", "name", "kind", "what", "workflow", "inputs", "outputs", "technology", "candidates", "gpu", "complexity",
    "cost", "aro_status", "aro_evidence", "required_work", "acceptance", "meshy", "priority",
}  # fmt: skip


def test_every_capability_has_every_required_field_filled_in():
    for c in CAPS:
        assert set(c) >= REQUIRED, (c.get("id"), REQUIRED - set(c))
        for k in REQUIRED - {"meshy"}:
            assert isinstance(c[k], str) and c[k].strip(), (c["id"], k)


def test_ids_are_unique_and_statuses_use_the_agreed_vocabulary():
    ids = [c["id"] for c in CAPS]
    assert len(ids) == len(set(ids))
    for c in CAPS:
        assert c["aro_status"] in build.STATUSES, (c["id"], c["aro_status"])
        assert c["priority"] in DATA["priority_definitions"]
        assert c["kind"] in {"AI", "Conventional", "Mixed", "Platform"}
    assert set(DATA["status_definitions"]) == set(build.STATUSES)


def test_nothing_is_production_ready_and_strong_claims_name_their_evidence():
    for c in CAPS:
        assert c["aro_status"] != "Production ready", c["id"]
        if c["aro_status"] in ("Fully tested", "Implemented"):
            assert len(c["aro_evidence"]) > 25 and c["aro_evidence"] != "None.", c["id"]


def test_ai_capabilities_that_were_never_run_are_not_marked_implemented():
    """Rule: do not claim a feature because a plug-in or button exists. AI rows may be 'Implemented but unverified' at best until a real run is recorded."""
    for c in CAPS:
        if c["kind"] == "AI":
            assert c["aro_status"] in {
                "Not investigated",
                "Investigated",
                "Planned",
                "In development",
                "Implemented but unverified",
            }, c["id"]


def test_meshy_claims_carry_an_evidence_grade_and_official_sources_are_urls():
    for c in CAPS:
        m = c["meshy"]
        assert m["evidence_grade"] in {"G", "S", "T", "none"}, c[
            "id"
        ]  # G = read in Meshy's own OpenAPI file or documentation
        if m["evidence_grade"] != "none":
            assert m["sources"], c["id"]
        for u in m["sources"]:
            assert u.startswith("https://") and ("meshy.ai" in u), (c["id"], u)


def test_the_markdown_is_generated_from_the_json_and_up_to_date():
    expected = build.render(DATA)
    assert (ROOT / "docs" / "cto" / "competitive-matrix.md").read_text(encoding="utf-8") == expected
