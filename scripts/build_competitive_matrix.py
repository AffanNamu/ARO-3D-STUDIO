#!/usr/bin/env python
"""Render docs/cto/competitive-matrix.md from docs/cto/competitive-matrix.json (the source of truth).

    python scripts/build_competitive_matrix.py            # rewrite the Markdown
    python scripts/build_competitive_matrix.py --check    # exit 1 if the Markdown is out of date

The tracker records, per Meshy-class capability, what it is, how it would be built, what ARO has TODAY and how it will be accepted.
tests/test_competitive_matrix.py enforces the vocabulary and the rule that an overclaiming status needs recorded evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "docs" / "cto" / "competitive-matrix.json"
MD_PATH = ROOT / "docs" / "cto" / "competitive-matrix.md"

STATUSES = (
    "Not investigated",
    "Investigated",
    "Planned",
    "In development",
    "Implemented",
    "Implemented but unverified",
    "Fully tested",
    "Production ready",
)
FIELDS = (
    ("what", "What it does"),
    ("workflow", "User workflow"),
    ("inputs", "Inputs"),
    ("outputs", "Outputs"),
    ("technology", "Technology"),
    ("candidates", "Candidate models / services"),
    ("gpu", "GPU requirements"),
    ("complexity", "Implementation complexity"),
    ("cost", "Estimated operating cost"),
    ("aro_evidence", "ARO today (evidence)"),
    ("required_work", "Work required"),
    ("acceptance", "Acceptance criteria"),
)


def render(data: dict) -> str:
    caps = data["capabilities"]
    out = [
        "# Competitive capability matrix (ARO 3D AI STUDIO vs Meshy AI)",
        "",
        "> Generated from [`competitive-matrix.json`](competitive-matrix.json) by `scripts/build_competitive_matrix.py`. Edit the JSON, not this file.",
        f"> Audit date: {data['generated_on']}. {data['purpose']}",
        "",
        "## How to read the evidence",
        "",
    ]
    out += [f"* **{k}**: {v}" for k, v in data["evidence_grades"].items()]
    out += ["", "## Status definitions", ""]
    out += [f"* **{k}**: {v}" for k, v in data["status_definitions"].items()]
    out += ["", "## Priorities", ""]
    out += [f"* **{k}**: {v}" for k, v in data["priority_definitions"].items()]
    counts = {s: sum(1 for c in caps if c["aro_status"] == s) for s in STATUSES}
    out += ["", "## Totals", "", "| Status | Capabilities |", "|---|---|"]
    out += [f"| {s} | {n} |" for s, n in counts.items()]
    out += [
        "",
        f"Total: {len(caps)}. **No capability is Production ready; claiming parity with Meshy is not supported by any row.**",
        "",
    ]
    out += [
        "## Overview",
        "",
        "| ID | Capability | Kind | Meshy offers it (evidence) | ARO status | Priority |",
        "|---|---|---|---|---|---|",
    ]
    for c in caps:
        m = c["meshy"]
        out.append(
            f"| {c['id']} | {c['name']} | {c['kind']} | {m['offers']} ({m['evidence_grade']}) | {c['aro_status']} | {c['priority']} |"
        )
    cat = None
    for c in caps:
        if c["category"] != cat:
            cat = c["category"]
            out += ["", f"## {cat}", ""]
        m = c["meshy"]
        out += [
            f"### {c['id']} {c['name']}",
            "",
            f"*Kind:* {c['kind']} · *ARO status:* **{c['aro_status']}** · *Priority:* {c['priority']}",
            "",
        ]
        for key, label in FIELDS:
            out.append(f"* **{label}:** {c[key]}")
        src = ", ".join(f"[{u.split('//', 1)[1]}]({u})" for u in m["sources"]) or "none"
        out.append(f"* **Meshy:** offers: {m['offers']} (evidence {m['evidence_grade']}). {m['note']} Sources: {src}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="fail if the Markdown is not up to date")
    a = ap.parse_args()
    text = render(json.loads(JSON_PATH.read_text(encoding="utf-8")))
    if a.check:
        if not MD_PATH.exists() or MD_PATH.read_text(encoding="utf-8") != text:
            print(
                "competitive-matrix.md is out of date: run python scripts/build_competitive_matrix.py", file=sys.stderr
            )
            return 1
        return 0
    MD_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {MD_PATH.relative_to(ROOT)} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
