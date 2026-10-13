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
        # inputs and raw artefacts are preserved byte-for-byte, with their provenance recorded
        assert (tmp_path / "out" / it["input_preserved_as"]).read_bytes() == (tmp_path / it["input_file"]).read_bytes()
        assert it["input_image"]["width"] == 320 and it["category_group"] in ("vehicles", "environment", "objects")
        raw = tmp_path / "out" / it["raw_mesh_file"]
        assert raw.is_file() and it["real_inference"]["raw_copy_sha256"] == it["real_inference"]["output_sha256"]
        assert it["real_inference"]["input_bytes_equal_stored_source"] is True
    assert ev["studio_commit"] and ev["environment"]["packages"]["numpy"]


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


def test_package_splits_repo_safe_files_from_raw_meshes(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import zipfile

    import package_smoke_evidence as pk

    src = tmp_path / "smoke"
    (src / "raw").mkdir(parents=True)
    (src / "inputs").mkdir()
    (src / "smoke-evidence.json").write_text("{}")
    (src / "inputs" / "01-a.png").write_bytes(b"png")
    (src / "raw" / "01-a-raw.glb").write_bytes(b"x" * 100)
    (src / "01-prepared.glb").write_bytes(b"y" * (pk.MAX_REPO_FILE + 1))
    r = pk.package(src, tmp_path / "out")
    assert sorted(zipfile.ZipFile(r["repo_zip"]).namelist()) == ["inputs/01-a.png", "smoke-evidence.json"]
    assert zipfile.ZipFile(r["raw_zip"]).namelist() == ["raw/01-a-raw.glb"]
    assert r["too_large_for_git"] and r["too_large_for_git"][0][0] == "01-prepared.glb"


def _real_evidence():
    return {
        "mode": "real_engine",
        "status": {"real_inference": "PASS", "visual_quality": "PENDING_HUMAN_REVIEW"},
        "items": [
            {
                "name": "Chair",
                "real_inference": {"model_ran": True},
                "human_review": {"status": "PENDING_HUMAN_REVIEW"},
            },
            {"name": "Crash", "real_inference": {}, "human_review": {"status": "PENDING_HUMAN_REVIEW"}},
        ],
    }


def test_human_review_is_only_accepted_when_complete_and_for_real_outputs():
    sys.path.insert(0, str(ROOT / "scripts"))
    import fill_human_review as fh

    good = {
        "recognisable": "partially",
        "visual_defects": "back legs fused",
        "category_limitations": "thin parts",
        "orientation_up_front": "+Z up, front unknown",
    }
    ev = _real_evidence()
    fh.apply_reviews(ev, {"Chair": good}, "Reviewer", "2026-10-12")
    assert (
        ev["items"][0]["human_review"]["status"] == "REVIEWED"
        and ev["items"][0]["human_review"]["reviewed_by"] == "Reviewer"
    )
    assert ev["status"]["visual_quality"] == "REVIEWED"  # the only item that really ran is reviewed
    for bad, why in (
        ({"Chair": {**good, "visual_defects": " "}}, "missing"),
        ({"Chair": {**good, "recognisable": "maybe"}}, "recognisable"),
        ({"Crash": good}, "no real output"),
        ({"Nope": good}, "unknown"),
    ):
        with pytest.raises(SystemExit) as e:
            fh.apply_reviews(_real_evidence(), bad, "Reviewer")
        assert why in str(e.value).lower() or why in str(e.value)
    with pytest.raises(SystemExit):
        fh.apply_reviews({**_real_evidence(), "mode": "test_double"}, {"Chair": good}, "Reviewer")
    with pytest.raises(SystemExit):
        fh.apply_reviews(_real_evidence(), {"Chair": good}, " ")


def test_colab_notebook_is_runnable_in_order_and_cannot_fake_inference():
    nb = json.loads((ROOT / "notebooks" / "aro_real_inference_colab.ipynb").read_text())
    assert nb["nbformat"] == 4 and len({c["id"] for c in nb["cells"]}) == len(nb["cells"])
    code = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")
    assert all(not c.get("outputs") for c in nb["cells"] if c["cell_type"] == "code"), (
        "commit the notebook without outputs"
    )
    # runs the real harness in real mode; no test double, no licence override, no bypass of weight verification
    assert "real_inference_smoke.py" in code and "--double" not in code
    assert "ARO_VERIFIED_MODEL_LICENSES" not in code and "verify_triposr_weights.py" in code
    assert "availability ok: True" in code and "TSR_COMMIT" in code
    for script in (
        "real_inference_smoke.py",
        "fill_human_review.py",
        "package_smoke_evidence.py",
        "verify_triposr_weights.py",
    ):
        assert script in code and (ROOT / "scripts" / script).is_file()
    # the images are documented and pinned; the vehicle needs a stated source
    assert "VEHICLE_SOURCE.strip()" in code and code.count("sha256") >= 3
    # optional push cell: token only from Colab Secrets, separate evidence branch, never a literal token
    assert "userdata.get('GITHUB_TOKEN')" in code and "push_smoke_evidence.py" in code
    assert "ghp_" not in code and "github_pat_" not in code and "x-access-token" not in code
    pinned = json.loads((ROOT / "aro_studio/engines/locks/triposr.json").read_text())["code"]["commit"]
    assert pinned and "TSR_COMMIT = lock['code']['commit']" in code


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _evidence_repo(tmp_path, mode="real_engine"):
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", str(remote))
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(remote), str(work))
    _git(work, "config", "user.email", "t@example.invalid")
    _git(work, "config", "user.name", "t")
    (work / "README.md").write_text("x")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "init")
    _git(work, "branch", "-M", "claude/work")
    d = work / "docs/acceptance/evidence/ai/smoke"
    (d / "raw").mkdir(parents=True)
    (d / "smoke-evidence.json").write_text(
        json.dumps({"mode": mode, "status": {"real_inference": "PASS"}, "studio_commit": "abc"})
    )
    (d / "raw" / "01-raw.glb").write_bytes(b"raw")
    (work / "secret-note.txt").write_text("must not be pushed")
    return remote, work


def _push(work, *args, token="dummy-token"):
    env = (
        {**__import__("os").environ, "GITHUB_TOKEN": token}
        if token
        else {k: v for k, v in __import__("os").environ.items() if k != "GITHUB_TOKEN"}
    )
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "push_smoke_evidence.py"), "--repo", str(work), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_push_goes_to_a_separate_branch_with_only_the_evidence_folder(tmp_path):
    remote, work = _evidence_repo(tmp_path)
    r = _push(work, "--branch", "evidence/smoke-test")
    assert r.returncode == 0, r.stdout + r.stderr
    files = _git(remote, "ls-tree", "-r", "--name-only", "evidence/smoke-test").splitlines()
    assert "docs/acceptance/evidence/ai/smoke/smoke-evidence.json" in files
    assert "secret-note.txt" not in files and "README.md" in files  # history carries the base; nothing extra was added
    assert not [f for f in files if "/raw/" in f]  # raw meshes are never committed (also .gitignored in the real repo)
    assert "dummy-token" not in r.stdout + r.stderr


def test_push_refuses_unsafe_requests(tmp_path):
    remote, work = _evidence_repo(tmp_path)
    for branch in ("claude/zen-johnson-je3dzk", "main", "claude/work"):
        r = _push(work, "--branch", branch)
        assert r.returncode != 0 and "refusing to push" in (r.stdout + r.stderr)
    assert _push(work, "--branch", "evidence/x", token="").returncode != 0  # no token, no push
    (work / "docs/acceptance/evidence/ai/smoke/big.glb").write_bytes(b"x" * 8_000_001)
    r = _push(work, "--branch", "evidence/x")
    assert r.returncode != 0 and "larger than 8 MB" in (r.stdout + r.stderr)
    assert not _git(remote, "branch", "--list", "evidence/x")


def test_push_refuses_test_double_evidence(tmp_path):
    _, work = _evidence_repo(tmp_path, mode="test_double")
    r = _push(work, "--branch", "evidence/x")
    assert r.returncode != 0 and "not from the real engine" in (r.stdout + r.stderr)


def test_single_image_focused_run_is_allowed_but_never_counts_as_the_full_proof(tmp_path):
    m = _manifest(tmp_path, [("truck", "heavy_truck", (200, 40, 40))])
    # without the flag a single image is a coverage problem (BLOCKED in real mode)
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--manifest", str(m), "--out", str(tmp_path / "o1")],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=600,
    )
    assert r.returncode == 3
    # with the flag (double mode here) the wiring still works for one image, and coverage stays recorded
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--manifest",
            str(m),
            "--out",
            str(tmp_path / "o2"),
            "--double",
            "--allow-partial-coverage",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=600,
    )
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-800:]
    ev = json.loads((tmp_path / "o2" / "smoke-evidence.json").read_text())
    assert ev["coverage_problems"] and ev["items"][0]["export"]["reopened_vertices_finite"] is True
    assert str(ev["status"]["real_inference"]).startswith("NOT_RUN")


def test_notebook_stage_report_refuses_to_complete_inference_stages_for_a_test_double():
    nb = json.loads((ROOT / "notebooks" / "aro_real_inference_colab.ipynb").read_text())
    code = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")
    assert "REAL = ev['mode'] == 'real_engine' and eng.get('id') == 'triposr'" in code
    assert "stage(3, 'real inference', REAL and" in code and "stage(2, 'model/weights/licence', REAL and" in code
    assert (
        "REUSED, not rebuilt" in code and "FOCUSED_TRUCK_ONLY" in code and "Luxury ARO 480 Heavy-Duty Truck.png" in code
    )
