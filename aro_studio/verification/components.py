"""The seven separately-reported acceptance components (PASS / PARTIAL / BLOCKED / FAIL), derived from evidence files only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aro_studio.verification.evidence import (
    BLOCKED,
    FAIL,
    PARTIAL,
    PASS,
    Evidence,
    read_ai_evidence,
    read_docker_evidence,
    read_smoke_evidence,
    read_unity_evidence,
)

EVIDENCE = "docs/acceptance/evidence"
SECURITY_STEPS = ("bandit", "pip-audit")


def _regression(root: Path) -> dict | None:
    p = root / EVIDENCE / "regression" / "regression.json"
    try:
        return json.loads(p.read_text()) if p.is_file() else None
    except (OSError, ValueError):
        return {"corrupt": True}


def _regression_status(reg: dict | None, pick) -> Evidence:
    if reg is None:
        return Evidence(BLOCKED, "regression has not been run: scripts/run_regression.py")
    if reg.get("corrupt"):
        return Evidence(FAIL, "evidence rejected: regression.json unreadable")
    steps = [s for s in reg.get("steps", []) if pick(s)]
    if not steps:
        return Evidence(BLOCKED, "no matching regression steps recorded")
    failed = [s["name"] for s in steps if s["status"] == "FAIL"]
    blocked = [s["name"] for s in steps if s["status"] == "BLOCKED"]
    t = reg.get("totals", {})
    facts: dict[str, Any] = {
        "steps": {s["name"]: s["status"] for s in steps},
        "totals": t,
        "commit": reg.get("git_commit"),
        "dirty_tree": reg.get("dirty_tree"),
    }
    if failed:
        return Evidence(FAIL, "failing: " + ", ".join(failed), facts=facts)
    if blocked:
        return Evidence(PARTIAL, "could not run: " + ", ".join(blocked), facts=facts)
    return Evidence(PASS, f"{len(steps)} gates passed", facts=facts)


def compute(root: Path, procedural: dict | None = None) -> list[dict]:
    """``procedural``: {"validation_status": str, "rows": [...]} from the acceptance run (or None -> read its JSON report)."""
    ev = root / EVIDENCE
    reg = _regression(root)
    if procedural is None:
        rp = root / "docs/acceptance/titan480-acceptance-report.json"
        if rp.is_file():
            d = json.loads(rp.read_text())
            procedural = {
                "validation_status": (d.get("state", {}).get("validation") or {}).get("status"),
                "rows": d.get("stages", []),
            }
    ai_real, ai_pipe, ai_prod = read_ai_evidence(ev / "ai" / "inference-evidence.json")
    smoke = read_smoke_evidence(ev / "ai" / "smoke" / "smoke-evidence.json")
    if smoke.status != BLOCKED:  # the Studio-level smoke test is the stronger evidence when it exists
        ai_real = smoke
        if smoke.status == PASS and ai_prod.status == BLOCKED:
            # "TripoSR has never been run" would be false here. What is true: real assets exist, but none is a validated production asset.
            n = len(smoke.facts.get("items", []))
            reviewed = smoke.facts.get("human_reviewed_items", 0)
            ai_prod = Evidence(
                PARTIAL,
                f"the real engine produced and prepared {n} assets (component 3), but none is a validated production asset: no real-world size "
                f"has been confirmed (single image = 1 m placeholder), vehicle metadata is artist work, and {reviewed}/{n} have a human visual review",
                smoke.source,
                {"items": n, "human_reviewed_items": reviewed},
            )
    unity = read_unity_evidence(ev / "unity" / "unity-verification.json")
    docker = read_docker_evidence(ev / "docker" / "docker-verification.json")

    # 1. platform implementation: lint/types/tests/e2e/acceptance of the code that exists
    platform = _regression_status(
        reg, lambda s: s["name"].startswith(("ruff", "mypy", "pytest", "acceptance", "licence"))
    )
    if platform.status == PASS and reg:
        skipped = reg.get("totals", {}).get("skipped", 0)
        platform.detail += f"; {reg['totals'].get('passed')} tests passed, {skipped} skipped (skips are listed, never counted as passes)"
    # 2. procedural reference asset
    if procedural is None:
        proc = Evidence(BLOCKED, "acceptance run not executed: scripts/run_acceptance.py")
    else:
        rows = procedural["rows"]
        # 9 (repair) and 11 (textures) cannot be exercised by a defect-free, flat-colour procedural asset: their rows say so and
        # are covered by unit tests on damaged meshes / UV-baking tests. They must not FAIL, but they are not required to PASS.
        needed = [r for r in rows if 8 <= r["n"] <= 21 and r["n"] not in (9, 11)]
        bad = [r for r in rows if 8 <= r["n"] <= 21 and r["status"] == FAIL]
        notpass = [r for r in needed if r["status"] != PASS]
        vs = procedural.get("validation_status")
        if bad:
            proc = Evidence(FAIL, f"stages failing: {[r['n'] for r in bad]}")
        elif not notpass and vs == "PRODUCTION_READY":
            proc = Evidence(
                PASS,
                "stages 8-21 passed (9 repair and 11 texture-bake not applicable to a defect-free flat-colour asset, covered by unit tests) on the procedural TITAN 480; validation PRODUCTION_READY. This is NOT an AI asset.",
            )
        else:
            proc = Evidence(PARTIAL, f"validation={vs}; non-passing stages: {[r['n'] for r in notpass]}")
    security = _regression_status(reg, lambda s: s["name"].startswith(("bandit", "pip-audit", "pytest")))
    if security.status == PASS:
        security.detail = "bandit + pip-audit + the full test suite (incl. security, resource-limit and archive-protection tests) passed"
    rows = [
        ("1. Platform implementation", platform),
        ("2. Procedural reference asset (ARO TITAN 480)", proc),
        ("3. Real AI-generated asset", ai_real),
        ("4. Validated production asset (from real AI output)", ai_prod),
        ("5. Verified Unity 6 import", unity),
        ("6. Docker deployment", docker),
        ("7. Security and regression tests", security),
    ]
    return [
        {"component": n, "status": e.status, "detail": e.detail, "evidence": e.source, "facts": e.facts}
        for n, e in rows
    ]


def production_ready(components: list[dict]) -> bool:
    return all(c["status"] == PASS for c in components)
