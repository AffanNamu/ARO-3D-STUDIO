#!/usr/bin/env python
"""Full regression (Phase 5). Runs every gate CI runs, records real counts, never edits or filters tests.

    python scripts/run_regression.py [--skip-e2e] [--skip-acceptance] [--skip-audit]

Evidence: docs/acceptance/evidence/regression/regression.json (+ per-step logs, junit XML).
Statuses per step: PASS / FAIL / BLOCKED (tool unavailable or needs network that is not reachable - with the reason).
Skipped tests are counted and listed with their reasons; a skipped test is never counted as passed.
Exit 0 only if no step FAILED. BLOCKED steps are reported, not hidden.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/acceptance/evidence/regression"
STEPS: list[dict] = []


def run(
    name: str, cmd: list[str], *, timeout: int = 3000, env: dict | None = None, blocked_if: tuple[str, ...] = ()
) -> dict:
    t = time.perf_counter()
    log = OUT / (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") + ".log")
    try:
        p = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, **(env or {})},
            check=False,
        )
        text = (p.stdout or "") + (p.stderr or "")
        rc = p.returncode
    except subprocess.TimeoutExpired:
        text, rc = f"TIMEOUT after {timeout}s", 124
    except FileNotFoundError as e:
        text, rc = f"tool not found: {e}", 127
    log.write_text(text)
    status = "PASS" if rc == 0 else "FAIL"
    if rc != 0 and (rc == 127 or any(b in text for b in blocked_if)):
        status = "BLOCKED"
    rec = {
        "name": name,
        "status": status,
        "exit_code": rc,
        "seconds": round(time.perf_counter() - t, 1),
        "command": " ".join(cmd),
        "log": str(log.relative_to(ROOT)),
        "tail": text.strip().splitlines()[-6:],
    }
    STEPS.append(rec)
    print(f"[{status}] {name} ({rec['seconds']}s)", flush=True)
    return rec


def junit_counts(path: Path) -> dict:
    if not path.is_file():
        return {}
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root)
    c = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    skipped: list[dict] = []
    for s in suites:
        for k in c:
            c[k] += int(s.get(k, 0))
        for tc in s.iter("testcase"):
            sk = tc.find("skipped")
            if sk is not None:
                skipped.append(
                    {"test": f"{tc.get('classname')}::{tc.get('name')}", "reason": (sk.get("message") or "")[:200]}
                )
    c["passed"] = c["tests"] - c["failures"] - c["errors"] - c["skipped"]
    c["skipped_tests"] = skipped
    return c


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-e2e", action="store_true")
    ap.add_argument("--skip-acceptance", action="store_true")
    ap.add_argument("--skip-audit", action="store_true", help="skip pip-audit (needs network)")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    net = ("Connection", "connect", "Temporary failure", "Max retries", "Name or service", "SSL", "ProxyError", "403")

    run("ruff check", [py, "-m", "ruff", "check", "."])
    run("ruff format --check", [py, "-m", "ruff", "format", "--check", "."])
    run("mypy", [py, "-m", "mypy", "aro_studio", "app.py"])
    run("bandit (medium+ severity)", [py, "-m", "bandit", "-q", "-r", "aro_studio", "-x", "aro_studio/ui", "-ll"])
    if not a.skip_audit:
        run("pip-audit (requirements.txt)", [py, "-m", "pip_audit", "-r", "requirements.txt"], blocked_if=net)
    run("licence audit", [py, "scripts/audit_licenses.py", "--check"])

    gv = os.environ.get("ARO_GLTF_VALIDATOR_NODE_PATH", "")
    unit_xml = OUT / "pytest-unit.xml"
    r = run(
        "pytest (unit + integration + security + performance)",
        [py, "-m", "pytest", "--ignore=tests/e2e", "-q", "-p", "no:cacheprovider", f"--junitxml={unit_xml}", "-rs"],
        timeout=3500,
    )
    r["counts"] = junit_counts(unit_xml)
    r["khronos_validator_path_set"] = bool(gv) and Path(gv).exists()
    if not a.skip_e2e:
        e2e_xml = OUT / "pytest-e2e.xml"
        r = run(
            "pytest browser e2e (Playwright)",
            [py, "-m", "pytest", "tests/e2e", "-q", f"--junitxml={e2e_xml}", "-rs"],
            timeout=1800,
        )
        r["counts"] = junit_counts(e2e_xml)
    if not a.skip_acceptance:
        r = run(
            "acceptance run (TITAN 480, 22 stages)", [py, "scripts/run_acceptance.py", "--with-browser"], timeout=3000
        )
        rep = ROOT / "docs/acceptance/titan480-acceptance-report.json"
        if rep.is_file():
            stages = json.loads(rep.read_text()).get("stages", [])
            r["stage_counts"] = {
                s: sum(1 for x in stages if x["status"] == s) for s in ("PASS", "PARTIAL", "BLOCKED", "FAIL")
            }

    totals = {"tests": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    skipped: list[dict] = []
    for s in STEPS:
        c = s.get("counts")
        if c:
            totals["tests"] += c["tests"]
            totals["passed"] += c["passed"]
            totals["failed"] += c["failures"]
            totals["errors"] += c["errors"]
            totals["skipped"] += c["skipped"]
            skipped += c["skipped_tests"]
    doc = {
        "schema": 1,
        "when": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
        ).stdout.strip(),
        "dirty_tree": bool(
            subprocess.run(
                ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=False
            ).stdout.strip()
        ),
        "python": sys.version.split()[0],
        "steps": STEPS,
        "totals": totals,
        "skipped_tests": skipped,
    }
    (OUT / "regression.json").write_text(json.dumps(doc, indent=2) + "\n")
    print(
        json.dumps(
            {
                "totals": totals,
                "failed_steps": [s["name"] for s in STEPS if s["status"] == "FAIL"],
                "blocked_steps": [s["name"] for s in STEPS if s["status"] == "BLOCKED"],
            },
            indent=2,
        )
    )
    return 1 if any(s["status"] == "FAIL" for s in STEPS) else 0


if __name__ == "__main__":
    sys.exit(main())
