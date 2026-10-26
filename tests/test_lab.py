"""The Colab engine-lab plumbing: engine planning, worker environment, packaging, the CPU marching-cubes stand-in and the bake-off baselines.

Nothing here runs a model (no GPU): it checks the parts around the engines that decide whether the first real run works.
"""

from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lab = load("lab_bootstrap")
nb = load("lab_notebook")
bake = load("engine_bakeoff")


# ---- engine planning ------------------------------------------------------------------------------
def test_plan_respects_the_gpu_memory_each_engine_documents():
    assert lab.plan(["triposg", "hunyuan3d"], 15_360)["run"] == ["triposg", "hunyuan3d"]  # a 15 GB T4
    small = lab.plan(["triposg", "hunyuan3d"], 7_000)  # 7 GB: only the 6 GB engine fits
    assert small["run"] == ["hunyuan3d"] and "8000" in small["skipped"]["triposg"]
    none = lab.plan(["triposg"], None)
    assert none["run"] == [] and "no CUDA GPU" in none["skipped"]["triposg"]


def test_trellis2_is_never_set_up_by_the_notebook_script():
    p = lab.plan(["trellis2", "triposg"], 80_000)
    assert "trellis2" in p["skipped"] and "24 GB" in p["skipped"]["trellis2"] and p["run"] == ["triposg"]


def test_unknown_engines_are_refused():
    with pytest.raises(SystemExit, match="unknown engine"):
        lab.plan(["mystery"], 16_000)


def test_the_restricted_engine_is_labelled_evaluation_only_where_users_see_it():
    assert "EVALUATION ONLY" in lab.ENGINES["hunyuan3d"]["notes"]
    assert "evaluation only" in lab.ENGINES["hunyuan3d"]["notes"].lower()


def test_worker_environment_points_each_engine_at_its_checkout_and_keeps_the_token_out_of_argv(tmp_path):
    env = lab.worker_env(tmp_path, "tok" * 10, ["triposg", "hunyuan3d"])
    assert env["TRIPOSG_DIR"] == str(tmp_path / "TripoSG") and env["HUNYUAN3D_DIR"] == str(tmp_path / "Hunyuan3D-2")
    assert env["ARO_WORKER_TOKEN"] == "tok" * 10 and env["PYTHONPATH"] == str(ROOT)
    assert env["ARO_WORKER_CACHE"] == str(tmp_path / "weights")


def test_every_engine_dependency_is_pinned_or_deliberately_open():
    for name, spec in lab.ENGINES.items():
        assert spec["pip"], name
        pins = [p for p in spec["pip"] if "==" in p]
        assert any(p.startswith("diffusers==") for p in pins) and any(p.startswith("transformers==") for p in pins), (
            name
        )
    assert lab.TORCH[0].startswith("torch==") and lab.TORCH[1].startswith("torchvision==")


# ---- packaging ------------------------------------------------------------------------------------
def test_packaging_keeps_raw_meshes_out_of_the_repo_zip_and_refuses_an_unfinished_run(tmp_path):
    out = tmp_path / "results"
    (out / "triposg-truck").mkdir(parents=True)
    with pytest.raises(SystemExit, match="did not finish"):
        nb.package(out, tmp_path / "lab", tmp_path / "pkg")
    (out / "bakeoff-summary.json").write_text("{}")
    (out / "triposg-truck" / "prepared.glb").write_bytes(b"glTF-prepared")
    (out / "triposg-truck" / "raw_output.glb").write_bytes(b"glTF-raw-big")
    (out / "triposg-truck" / "sheet.png").write_bytes(b"png")
    lab_root = tmp_path / "lab"
    lab_root.mkdir()
    (lab_root / "worker.log").write_text("line1\nline2\n")
    repo_zip, raw_zip = nb.package(out, lab_root, tmp_path / "pkg")
    names = zipfile.ZipFile(repo_zip).namelist()
    assert any(n.endswith("prepared.glb") for n in names) and any(n.endswith("sheet.png") for n in names)
    assert not any(n.endswith("raw_output.glb") for n in names)
    assert any(n.endswith("lab-environment.json") for n in names) and any(n.endswith("worker.log") for n in names)
    assert zipfile.ZipFile(raw_zip).namelist() == ["results/triposg-truck/raw_output.glb"]


# ---- the CPU stand-in for diso ---------------------------------------------------------------------
def test_diso_shim_extracts_an_outward_sphere_the_way_the_caller_expects():
    from aro_worker.shims.diso_shim import DiffDMC

    n = 49
    g = np.indices((n, n, n)).astype(np.float32)
    c = (n - 1) / 2
    sdf = (np.sqrt(((g - c) ** 2).sum(0)) - 15.0) / n  # negative inside, as TripoSG's -logits/res
    sdf[:4, :4, :4] = np.nan  # a region the octree never evaluated
    v, f = DiffDMC(dtype=None)(sdf, deform=None, return_quads=False, normalize=False)
    v = v.detach().cpu().numpy()
    f = f.detach().cpu().numpy()[:, ::-1]  # TripoSG flips the face order itself
    tri = v[f]
    volume = float(np.einsum("ij,ij->", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])) / 6.0)
    assert volume == pytest.approx(4 / 3 * np.pi * 15**3, rel=0.03)  # positive = outward-wound
    assert np.linalg.norm(v - c, axis=1).mean() == pytest.approx(15.0, abs=0.3)


def test_diso_shim_refuses_a_grid_without_a_surface():
    from aro_worker.shims.diso_shim import DiffDMC

    with pytest.raises(ValueError, match="no zero crossing"):
        DiffDMC()(np.ones((8, 8, 8), dtype=np.float32))


def test_ensure_diso_falls_back_when_the_compiled_package_is_missing(monkeypatch):
    import sys

    from aro_worker.engines import triposg

    monkeypatch.delitem(sys.modules, "diso", raising=False)
    if importlib.util.find_spec("diso") is not None:
        pytest.skip("the real diso is installed here")
    assert triposg.ensure_diso() == "skimage-shim"
    assert sys.modules["diso"].DiffDMC is not None
    sys.modules.pop("diso", None)


# ---- bake-off baselines -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "a,b",
    [
        ("01-ARO 480 Truck at Golden Hour.png", "ARO 480 Truck at Golden Hour.png"),
        ("01-ARO 480 Truck at Golden Hour (1).png", "aro_480_truck_at_golden_hour.PNG"),
    ],
)
def test_reference_names_match_across_upload_variants(a, b):
    assert bake._norm(a) == bake._norm(b)


def test_committed_triposr_baselines_are_found_for_the_same_reference_and_shown_first():
    baselines = bake.load_baselines(ROOT / "docs" / "acceptance" / "evidence" / "quality")
    key = bake._norm("ARO 480 Truck at Golden Hour.png")
    assert key in baselines and baselines[key]["meets_floor"] is False
    rows = [
        {
            "engine": "triposg",
            "image": "ARO 480 Truck at Golden Hour.png",
            "status": "PASS",
            "ratios": {"width_over_length": 0.38, "height_over_length": 0.52},
            "silhouette_iou": 0.93,
            "proportions": "plausible",
            "meets_floor": True,
            "prepared_triangles": 24000,
            "prepared_components": 1,
            "validation": "NEEDS_REVIEW",
            "total_seconds": 120.0,
        }
    ]
    md = bake.markdown(rows, baselines)
    lines = [ln for ln in md.splitlines() if ln.startswith("| ") and "Engine" not in ln and "---" not in ln]
    assert lines[0].startswith("| triposr (baseline)") and lines[1].startswith("| triposg")


def test_notebook_is_valid_json_and_never_contains_a_secret_or_a_fixed_token():
    nbk = json.loads((ROOT / "notebooks" / "aro_engine_lab_colab.ipynb").read_text())
    code = "\n".join("".join(c["source"]) for c in nbk["cells"] if c["cell_type"] == "code")
    assert "ghp_" not in code and "github_pat" not in code and "hf_" not in code
    assert (
        "I_HAVE_READ_THE_MODEL_CARDS = False" in code and "EVALUATE_RESTRICTED = False" in code
    )  # licence gates default closed
    assert "os.environ['ARO_WORKER_TOKEN'] = info['token']" in code and "print(info" not in code
