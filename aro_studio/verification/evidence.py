"""Evidence readers. A status is derived ONLY from evidence files produced by the real verification runs.

* No file  -> BLOCKED (the verification has not been run anywhere).
* A file that is malformed, incomplete or contradicts itself -> FAIL ("evidence rejected"), never silently accepted.
* PASS needs every required check present and passing, recorded by the real tool on a real host.

These readers cannot prove a file was not hand-edited; they make accidental or lazy "passes" impossible and make the claim
auditable (hardware, versions, hashes and per-check detail are all in the file). Reviewers should read the raw evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PASS, PARTIAL, BLOCKED, FAIL = "PASS", "PARTIAL", "BLOCKED", "FAIL"

# every one of these check names (prefix match) must be present AND "PASS" for the Unity import to count as verified
REQUIRED_UNITY_CHECKS = (
    "Unity 6 editor",
    "glTFast installed",
    "GLB imports as a GameObject",
    "prefab was written",
    "no import errors in the Console",
    "scale (size in metres)",
    "orientation (+Y up, +Z forward",
    "origin on the ground plane",
    "handedness (left stays left",
    "part names / hierarchy",
    "materials resolve",
    "all expected materials present",
    "LOD count",
    "LOD switching by camera distance",
    "no missing scripts",
    "no broken object references",
)


@dataclass
class Evidence:
    status: str
    detail: str
    source: str | None = None
    facts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"status": self.status, "detail": self.detail, "source": self.source, "facts": self.facts}


def _load(path: Path) -> tuple[dict | None, str | None]:
    if not path.is_file():
        return None, None
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        return None, f"unreadable evidence file {path.name}: {e}"
    return (data, None) if isinstance(data, dict) else (None, f"{path.name} is not a JSON object")


def read_unity_evidence(path: Path) -> Evidence:
    data, err = _load(path)
    if err:
        return Evidence(FAIL, "evidence rejected: " + err, str(path))
    if data is None:
        return Evidence(
            BLOCKED,
            "Unity 6 import has not been run: no unity-verification.json. Run Unity in batch mode with "
            "ARO.Studio.Editor.AroUnityVerifier.Run (docs/verification/unity-verification-runbook.md).",
        )
    problems = []
    if data.get("schema") != 1:
        problems.append("schema != 1")
    ver = str(data.get("unityVersion", ""))
    if not ver.startswith("6000."):
        problems.append(f"unityVersion {ver!r} is not a Unity 6 (6000.x) editor")
    checks = data.get("checks")
    if not isinstance(checks, list) or not checks:
        return Evidence(FAIL, "evidence rejected: no checks recorded", str(path))
    by_name = {c.get("name", ""): c for c in checks if isinstance(c, dict)}
    for req in REQUIRED_UNITY_CHECKS:
        hit = [c for n, c in by_name.items() if n.startswith(req)]
        if not hit:
            problems.append(f"required check missing: {req}")
        elif any(c.get("status") == "FAIL" for c in hit):
            problems.append(f"{req}: FAIL - {hit[0].get('detail')}")
    if not any(n.startswith("collider ") for n in by_name):
        problems.append("no collider checks recorded")
    fails = [c for c in checks if isinstance(c, dict) and c.get("status") == "FAIL"]
    notest = [c for c in checks if isinstance(c, dict) and c.get("status") == "NOT_TESTABLE"]
    facts = {
        "unityVersion": ver,
        "renderPipeline": data.get("renderPipeline"),
        "gltfast": data.get("gltfastVersion"),
        "checks": len(checks),
        "failed": [c.get("name") for c in fails],
        "not_testable": [c.get("name") for c in notest],
        "not_verified": data.get("notVerified", []),
        "importErrors": data.get("importErrors", []),
    }
    if data.get("importErrors"):
        problems.append(f"{len(data['importErrors'])} import error(s) logged")
    if fails or any(p for p in problems if "FAIL" in p or "not a Unity 6" in p or "import error" in p):
        return Evidence(FAIL, "; ".join(problems) or "checks failed", str(path), facts)
    if problems or notest or data.get("notVerified") or data.get("overall") != PASS:
        why = problems + [f"not testable: {c.get('name')}" for c in notest] + list(data.get("notVerified", []))
        return Evidence(PARTIAL, "; ".join(why) or f"overall={data.get('overall')}", str(path), facts)
    return Evidence(PASS, f"Unity {ver}: {len(checks)} checks passed", str(path), facts)


def read_ai_evidence(path: Path) -> tuple[Evidence, Evidence, Evidence]:
    """(real AI-generated asset, pipeline on real output / validated production asset...) -> three statuses."""
    data, err = _load(path)
    if err:
        bad = Evidence(FAIL, "evidence rejected: " + err, str(path))
        return bad, bad, bad
    if data is None:
        b = Evidence(
            BLOCKED,
            "TripoSR has never been run: no inference-evidence.json. Needs a GPU host + Hugging Face access "
            "(docs/verification/gpu-host-runbook.md).",
        )
        return b, b, b
    st = data.get("status", {})
    blockers = data.get("blockers", [])
    facts = {
        "device": data.get("device"),
        "gpu": (data.get("environment") or {}).get("cuda"),
        "generation": {
            k: (data.get("generation") or {}).get(k) for k in ("job_state", "wall_seconds", "peak_vram_nvidia_smi_mb")
        },
        "blockers": blockers,
    }

    def one(key: str, label: str) -> Evidence:
        s = st.get(key, BLOCKED)
        if s not in (PASS, PARTIAL, BLOCKED, FAIL):
            return Evidence(FAIL, f"evidence rejected: invalid status {s!r} for {key}", str(path), facts)
        return Evidence(
            s, f"{label}: {s}" + (f" - {'; '.join(blockers)[:300]}" if blockers and s != PASS else ""), str(path), facts
        )

    real = one("real_inference", "real inference")
    if real.status == PASS:  # a PASS needs the receipts
        gen = data.get("generation") or {}
        raw = data.get("raw") or {}
        if (
            gen.get("job_state") != "COMPLETED"
            or not (gen.get("result") or {}).get("model_ran")
            or not raw.get("finite")
            or raw.get("triangles", 0) < 100
        ):
            real = Evidence(
                FAIL,
                "evidence rejected: PASS claimed without a completed, finite, model-run generation",
                str(path),
                facts,
            )
    return (
        real,
        one("pipeline", "post-reconstruction pipeline on the real mesh"),
        one("validated_production_asset", "validated production asset"),
    )


def read_docker_evidence(path: Path) -> Evidence:
    data, err = _load(path)
    if err:
        return Evidence(FAIL, "evidence rejected: " + err, str(path))
    if data is None:
        return Evidence(
            BLOCKED, "Docker image has not been built/run: no docker-verification.json (scripts/verify_docker.sh)."
        )
    steps = data.get("steps") or data.get("results") or []
    failed = [s for s in steps if isinstance(s, dict) and s.get("result") != "PASS"]
    http = data.get("http_checks") or data.get("deployment") or {}
    facts = {
        "steps": len(steps),
        "failed": [s.get("step") for s in failed],
        "http": http if isinstance(http, dict) else None,
        "caveats": data.get("caveats", []),
        "image_id": data.get("image_id"),
    }
    if not steps:
        return Evidence(FAIL, "evidence rejected: no steps recorded", str(path), facts)
    if failed:
        return Evidence(FAIL, f"{len(failed)} of {len(steps)} Docker steps failed", str(path), facts)
    note = f" Caveats: {'; '.join(facts['caveats'])}." if facts["caveats"] else ""
    return Evidence(
        PASS,
        f"{len(steps)}/{len(steps)} Docker steps passed (build, hardening, health, persistence, limits).{note}",
        str(path),
        facts,
    )


def read_smoke_evidence(path: Path) -> Evidence:
    """Evidence from scripts/real_inference_smoke.py: PASS needs receipts for every item, never a test double or cache hit."""
    data, err = _load(path)
    if err:
        return Evidence(FAIL, "evidence rejected: " + err, str(path))
    if data is None:
        return Evidence(
            BLOCKED,
            "the Studio-level real-inference smoke test has not been run: no smoke-evidence.json "
            "(docs/verification/real-inference-smoke.md).",
        )
    if data.get("mode") != "real_engine":
        return Evidence(
            BLOCKED,
            f"evidence is from mode '{data.get('mode')}': a test double proves wiring, never inference",
            str(path),
        )
    claimed = (data.get("status") or {}).get("real_inference")
    items = data.get("items") or []
    facts = {
        "claimed": claimed,
        "items": [
            {"name": i.get("name"), "category": i.get("category"), "result": i.get("result")}
            for i in items
            if isinstance(i, dict)
        ],
        "blockers": data.get("blockers", []),
        "visual_quality": (data.get("status") or {}).get("visual_quality"),
        "gpu": (data.get("environment") or {}).get("cuda"),
    }
    if claimed in (BLOCKED, FAIL, PARTIAL):
        return Evidence(
            claimed, f"smoke test reported {claimed}: {'; '.join(data.get('blockers', []))[:300]}", str(path), facts
        )
    if claimed != PASS:
        return Evidence(FAIL, f"evidence rejected: invalid status {claimed!r}", str(path), facts)
    problems = []
    if len(items) < 3:
        problems.append("fewer than 3 items")
    for i in items:
        ri = i.get("real_inference") or {}
        if not (
            ri.get("model_ran") is True
            and ri.get("cache_hit") is False
            and ri.get("finite") is True
            and ri.get("output_sha256")
        ):
            problems.append(f"{i.get('name')}: missing receipts (model_ran/cache_hit/finite/output_sha256)")
        if i.get("result") != PASS:
            problems.append(f"{i.get('name')}: item result {i.get('result')}")
        if ri.get("engine_id") == "plumbing_test_double":
            problems.append(f"{i.get('name')}: produced by the test double")
    if data.get("coverage_problems") != []:
        problems.append(f"coverage problems: {data.get('coverage_problems')}")
    if (data.get("negative_probe") or {}).get("result") != PASS:
        problems.append("the invalid-file probe did not pass")
    if problems:
        return Evidence(FAIL, "evidence rejected: PASS claimed but " + "; ".join(problems)[:400], str(path), facts)
    reviewed = [i for i in items if (i.get("human_review") or {}).get("status") == "REVIEWED"]
    facts["human_reviewed_items"] = len(reviewed)
    review_note = (
        f"visual quality REVIEWED by a person for {len(reviewed)}/{len(items)} items"
        if reviewed
        else "visual quality is PENDING_HUMAN_REVIEW (a person must inspect the renders)"
    )
    return Evidence(
        PASS,
        f"{len(items)} different images went through the real engine and the Studio path; {review_note}",
        str(path),
        facts,
    )
