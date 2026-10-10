"""Guards against 'works on my machine': every third-party import must be declared, and runtime-implied
dependencies of libraries we call (e.g. trimesh's triangulation engine) must be pinned too."""

from __future__ import annotations

import ast
import re
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# imported lazily inside functions, only on hosts with the AI extras (requirements-triposr.txt)
OPTIONAL = {
    "torch",
    "tsr",
    "rembg",
    "omegaconf",
    "einops",
    "transformers",
    "huggingface_hub",
    "torchmcubes",
    "onnxruntime",
    "playwright",
}
# libraries trimesh/fastapi/uvicorn load at runtime without us importing them
RUNTIME_IMPLIED = {"mapbox-earcut", "rtree", "networkx", "scipy", "shapely", "python-multipart", "uvicorn", "pygltflib"}


def norm(n: str) -> str:
    return re.sub(r"[-_.]+", "-", n).lower()


def declared(path: str) -> set[str]:
    out = set()
    for line in (ROOT / path).read_text().splitlines():
        line = line.split("#")[0].strip()
        if line and not line.startswith("-"):
            out.add(norm(re.split(r"[<>=!~\[ ;]", line)[0]))
    return out


def third_party_imports() -> set[str]:
    mods: set[str] = set()
    for f in (ROOT / "aro_studio").rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.Import):
                mods |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods.add(node.module.split(".")[0])
    return {m for m in mods if m not in sys.stdlib_module_names and m not in {"aro_studio", "__future__"}}


def test_every_third_party_import_is_declared_in_requirements():
    dist_map = metadata.packages_distributions()
    req = declared("requirements.txt")
    missing = []
    for m in sorted(third_party_imports() - OPTIONAL):
        dists = {norm(d) for d in dist_map.get(m, [m])}
        if not dists & req:
            missing.append(f"{m} (distribution {sorted(dists)})")
    assert not missing, f"imported but not in requirements.txt: {missing}"


def test_runtime_implied_dependencies_are_declared():
    assert declared("requirements.txt") >= RUNTIME_IMPLIED


def test_pyproject_dependencies_match_requirements():
    text = (ROOT / "pyproject.toml").read_text()
    block = text.split("dependencies = [", 1)[1].split("]", 1)[0]
    py = {
        norm(re.split(r"[<>=!~\[ ]", x.strip().strip('",'))[0]) for x in block.splitlines() if x.strip().startswith('"')
    }
    assert py == declared("requirements.txt"), py ^ declared("requirements.txt")


def test_no_secrets_or_env_files_committed():
    assert not (ROOT / ".env").exists() or ".env" in (ROOT / ".gitignore").read_text()
    for f in ("Dockerfile", ".env.example", ".github/workflows/ci.yml"):
        text = (ROOT / f).read_text()
        assert not re.search(r"hf_[A-Za-z0-9]{20,}", text) and "BEGIN PRIVATE KEY" not in text, f
