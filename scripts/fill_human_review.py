#!/usr/bin/env python
"""Record a PERSON's visual review of the real outputs in smoke-evidence.json.

    python scripts/fill_human_review.py --evidence docs/acceptance/evidence/ai/smoke/smoke-evidence.json \
        --reviews review.json --reviewer "Your Name"

review.json (after LOOKING at views/NN-*-raw-*.png and views/NN-*-prepared-*.png):
  {"Truck photo": {"recognisable": "yes|partially|no", "visual_defects": "...", "category_limitations": "...",
                   "orientation_up_front": "which way is up / front, and whether the prepare step guessed right"}, ...}

Refuses: test-double evidence, items that did not really run, empty fields, unknown item names. This script never invents text.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

FIELDS = ("recognisable", "visual_defects", "category_limitations", "orientation_up_front")
RECOGNISABLE = {"yes", "partially", "no"}


def apply_reviews(evidence: dict, reviews: dict, reviewer: str, when: str | None = None) -> dict:
    if evidence.get("mode") != "real_engine":
        raise SystemExit("refusing: this evidence is not from the real engine (a test double has no output to review)")
    if not reviewer.strip():
        raise SystemExit("refusing: --reviewer is required (who looked at the renders)")
    by_name = {i["name"]: i for i in evidence.get("items", [])}
    unknown = set(reviews) - set(by_name)
    if unknown:
        raise SystemExit(f"refusing: unknown item name(s) {sorted(unknown)}; known: {sorted(by_name)}")
    for name, rv in reviews.items():
        item = by_name[name]
        if not item.get("real_inference", {}).get("model_ran"):
            raise SystemExit(f"refusing: '{name}' produced no real output, so there is nothing to review")
        missing = [f for f in FIELDS if not isinstance(rv.get(f), str) or not rv[f].strip()]
        if missing:
            raise SystemExit(f"refusing: '{name}' is missing non-empty text for {missing}")
        if rv["recognisable"].strip().lower() not in RECOGNISABLE:
            raise SystemExit(f"refusing: '{name}'.recognisable must be one of {sorted(RECOGNISABLE)}")
        item["human_review"] = {
            "status": "REVIEWED",
            **{f: rv[f].strip() for f in FIELDS},
            "reviewed_by": reviewer.strip(),
            "reviewed_on": when or time.strftime("%Y-%m-%d"),
        }
    ran = [i for i in evidence["items"] if i.get("real_inference", {}).get("model_ran")]
    if ran and all(i["human_review"].get("status") == "REVIEWED" for i in ran):
        evidence["status"]["visual_quality"] = "REVIEWED"
    return evidence


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--reviews", required=True)
    ap.add_argument("--reviewer", required=True)
    a = ap.parse_args()
    path = Path(a.evidence)
    ev = apply_reviews(json.loads(path.read_text()), json.loads(Path(a.reviews).read_text()), a.reviewer)
    path.write_text(json.dumps(ev, indent=2, default=str) + "\n")
    print("updated", path, "| visual_quality:", ev["status"].get("visual_quality"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
