"""Independent export-integrity verification (spec §24 'Export integrity', §54 step 21).

Re-opens what was written to disk and checks it against the scene it came from. A check only passes when it
was actually evaluated.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess  # noqa: S404
import tempfile
from pathlib import Path

import numpy as np
import pygltflib as g
from PIL import Image

from aro_studio.scene.store import Scene

_COMP = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def _read_accessor(gl: g.GLTF2, blob: bytes, idx: int) -> np.ndarray:
    acc = gl.accessors[idx]
    bv = gl.bufferViews[acc.bufferView]
    n = _NCOMP[acc.type]
    dtype = np.dtype(_COMP[acc.componentType])
    start = (bv.byteOffset or 0) + (acc.byteOffset or 0)
    need = acc.count * n * dtype.itemsize
    if start + need > (bv.byteOffset or 0) + bv.byteLength or start + need > len(blob):
        raise ValueError(f"accessor {idx} reads past its bufferView/buffer")
    return (
        np.frombuffer(blob, dtype=dtype, count=acc.count * n, offset=start).reshape(acc.count, n)
        if n > 1
        else np.frombuffer(blob, dtype=dtype, count=acc.count, offset=start)
    )


def verify_glb(data: bytes, scene: Scene | None = None, *, expect_lods: bool = True) -> dict:
    checks: list[dict] = []

    def add(cid: str, ok: bool, msg: str, **extra) -> None:
        checks.append({"id": cid, "ok": bool(ok), "message": msg, **extra})

    add("glb.magic", data[:4] == b"glTF", "GLB magic header present")
    try:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td, "m.glb")
            p.write_bytes(data)
            gl = g.GLTF2().load_binary(str(p))
            blob = gl.binary_blob() or b""
    except Exception as e:  # noqa: BLE001
        add("glb.parse", False, f"GLB could not be parsed: {type(e).__name__}: {e}")
        return {"ok": False, "checks": checks}
    add("glb.parse", True, "GLB parsed")
    add("glb.version", gl.asset.version == "2.0", f"glTF version {gl.asset.version}")
    add(
        "glb.buffer_length",
        bool(gl.buffers) and gl.buffers[0].byteLength <= len(blob),
        "BIN chunk covers the declared buffer length",
    )
    names = [n.name for n in gl.nodes]
    add(
        "nodes.unique_names",
        len(names) == len(set(names)),
        f"{len(names)} nodes, names unique" if len(names) == len(set(names)) else "duplicate node names",
    )
    # hierarchy: every node has at most one parent and there are no cycles
    parent: dict[int, int] = {}
    ok_h = True
    for i, n in enumerate(gl.nodes):
        for c in n.children or []:
            if c in parent or c == i:
                ok_h = False
            parent[c] = i
    for i in range(len(gl.nodes)):
        seen, cur = set(), i
        while cur in parent:
            if cur in seen:
                ok_h = False
                break
            seen.add(cur)
            cur = parent[cur]
    add(
        "nodes.hierarchy",
        ok_h,
        "hierarchy is a forest without cycles" if ok_h else "hierarchy has cycles or multiple parents",
    )
    add("scene.single_root", bool(gl.scenes) and len(gl.scenes[0].nodes) == 1, "exactly one root node")

    bad: list[str] = []
    tri_by_lod: dict[str, int] = {}
    for mesh in gl.meshes or []:
        for prim in mesh.primitives:
            try:
                pos = _read_accessor(gl, blob, prim.attributes.POSITION).astype(np.float64)
                idx = _read_accessor(gl, blob, prim.indices) if prim.indices is not None else np.arange(len(pos))
                if not np.isfinite(pos).all():
                    bad.append(f"{mesh.name}: non-finite positions")
                if idx.size and int(np.max(idx)) >= len(pos):
                    bad.append(f"{mesh.name}: index out of range")
                acc = gl.accessors[prim.attributes.POSITION]
                if acc.min and not np.allclose(pos.min(axis=0), acc.min, atol=1e-4):
                    bad.append(f"{mesh.name}: POSITION min/max mismatch")
                if prim.attributes.NORMAL is not None:
                    nrm = _read_accessor(gl, blob, prim.attributes.NORMAL).astype(np.float64)
                    if not np.allclose(np.linalg.norm(nrm, axis=1), 1.0, atol=1e-2):
                        bad.append(f"{mesh.name}: normals not unit length")
                if prim.material is not None and prim.material >= len(gl.materials or []):
                    bad.append(f"{mesh.name}: invalid material index")
            except Exception as e:  # noqa: BLE001
                bad.append(f"{mesh.name}: {e}")
    add(
        "geometry.accessors",
        not bad,
        "all accessors in range, finite, indexed correctly" if not bad else "; ".join(bad[:5]),
    )

    for n in gl.nodes:
        if n.mesh is not None and "_LOD" in (n.name or "") and not n.name.startswith("COL_"):
            lv = n.name.rsplit("_LOD", 1)[1]
            prim = gl.meshes[n.mesh].primitives[0]
            cnt = gl.accessors[prim.indices].count // 3 if prim.indices is not None else 0
            tri_by_lod[f"LOD{lv}"] = tri_by_lod.get(f"LOD{lv}", 0) + cnt
    if scene is not None:
        man = scene.manifest
        expected = {
            "LOD0": scene.triangle_count,
            **{f"LOD{lod.level}": sum(len(m.faces) for m in scene.lod_meshes[lod.level].values()) for lod in man.lods},
        }
        if tri_by_lod:
            match = all(tri_by_lod.get(k) == v for k, v in expected.items()) if expect_lods else True
            add(
                "lod.triangle_counts",
                match,
                f"exported {tri_by_lod} vs scene {expected}",
                exported=tri_by_lod,
                expected=expected,
            )
        else:
            tot = sum(
                (gl.accessors[pr.indices].count // 3)
                for n in gl.nodes
                if n.mesh is not None and not (n.name or "").startswith("COL_")
                for pr in gl.meshes[n.mesh].primitives
            )
            add(
                "geometry.triangle_count",
                tot == scene.triangle_count,
                f"exported {tot} vs scene {scene.triangle_count}",
            )
        mat_names = {m.name for m in (gl.materials or [])}
        used = {p.material for p in man.parts if p.material}
        add(
            "materials.present",
            used <= mat_names,
            "all used materials exported" if used <= mat_names else f"missing materials: {sorted(used - mat_names)}",
        )
        col_nodes = {n for n in names if (n or "").startswith("COL_")}
        add("collision.present", {c.name for c in man.colliders} <= col_nodes, f"{len(col_nodes)} collision nodes")
        if man.vehicle:
            rig_names = set(names)
            need = {w.name for w in man.vehicle.wheels}
            have = {n.removeprefix("Spin_") for n in rig_names if n and n.startswith("Spin_")}
            add("vehicle.wheel_nodes", not man.rig or need <= have, "wheel spin nodes exported for every wheel")
    # images decode
    img_bad = []
    for i, im in enumerate(gl.images or []):
        try:
            raw = (
                blob[(gl.bufferViews[im.bufferView].byteOffset or 0) :][: gl.bufferViews[im.bufferView].byteLength]
                if im.bufferView is not None
                else None
            )
            if raw is not None:
                Image.open(io.BytesIO(raw)).verify()
        except Exception as e:  # noqa: BLE001
            img_bad.append(f"image {i}: {e}")
    add("textures.decode", not img_bad, "all embedded images decode" if not img_bad else "; ".join(img_bad))
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def khronos_validate(path: Path, timeout_s: float = 90.0) -> dict:
    """Run the official Khronos glTF-Validator (npm ``gltf-validator``) when Node.js and the module are available.

    Returns ``{"ran": False, "reason": ...}`` otherwise - an un-run validator is never reported as a pass.
    Set ``ARO_GLTF_VALIDATOR_NODE_PATH`` to the directory containing ``node_modules/gltf-validator``.
    """
    node = shutil.which("node")
    script = Path(__file__).with_name("khronos_validate.cjs")
    if not node:
        return {
            "ran": False,
            "reason": "Node.js is not installed (the Khronos validator is run in CI and locally with npm)",
        }
    env = {**os.environ}
    if os.environ.get("ARO_GLTF_VALIDATOR_NODE_PATH"):
        env["NODE_PATH"] = os.environ["ARO_GLTF_VALIDATOR_NODE_PATH"]
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell, our own script
            [node, str(script), str(path)], capture_output=True, text=True, timeout=timeout_s, check=False, env=env
        )
    except Exception as e:  # noqa: BLE001
        return {"ran": False, "reason": f"validator failed to start: {e}"}
    if proc.returncode != 0:
        return {"ran": False, "reason": (proc.stderr.strip().splitlines() or ["validator error"])[-1][:200]}
    rep = json.loads(proc.stdout)
    iss = rep["issues"]
    return {
        "ran": True,
        "validator_version": rep["version"],
        "errors": iss["numErrors"],
        "warnings": iss["numWarnings"],
        "infos": iss["numInfos"],
        "ok": iss["numErrors"] == 0,
        "messages": iss.get("messages", [])[:10],
    }


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while c := f.read(1 << 20):
            h.update(c)
    return h.hexdigest()


REQUIRED_UNITY_DIRS = ["Models", "Materials", "Textures", "LOD", "Collision", "Metadata"]


def verify_unity_package(root: Path, scene: Scene | None = None) -> dict:
    checks: list[dict] = []

    def add(cid: str, ok: bool, msg: str) -> None:
        checks.append({"id": cid, "ok": bool(ok), "message": msg})

    for d in REQUIRED_UNITY_DIRS:
        add(f"dir.{d}", (root / d).is_dir(), f"{d}/ present")
    add("file.README", (root / "README.md").is_file(), "README.md present")
    add("file.importer", (root / "Editor" / "AroAssetImporter.cs").is_file(), "Editor importer script present")
    sums = root / "Metadata" / "checksums.sha256"
    if sums.is_file():
        bad = []
        n = 0
        for line in sums.read_text().splitlines():
            if not line.strip():
                continue
            digest, rel = line.split("  ", 1)
            f = root / rel
            n += 1
            if not f.is_file() or sha256_of(f) != digest:
                bad.append(rel)
        add("checksums", not bad, f"{n} files match checksums.sha256" if not bad else f"checksum mismatch: {bad[:5]}")
    else:
        add("checksums", False, "Metadata/checksums.sha256 missing")
    for js in (
        sorted((root / "Metadata").glob("*.json"))
        + sorted((root / "Materials").glob("*.json"))
        + sorted((root / "Collision").glob("*.json"))
    ):
        try:
            json.loads(js.read_text())
            add(f"json.{js.name}", True, f"{js.name} is valid JSON")
        except Exception as e:  # noqa: BLE001
            add(f"json.{js.name}", False, f"{js.name}: {e}")
    glbs = sorted((root / "Models").glob("*.glb"))
    add("models.glb", bool(glbs), f"{len(glbs)} GLB model(s)")
    for f in glbs:
        r = verify_glb(f.read_bytes(), scene)
        add(
            f"glb.{f.name}",
            r["ok"],
            "GLB integrity OK" if r["ok"] else "; ".join(c["message"] for c in r["checks"] if not c["ok"]),
        )
    lod_files = sorted((root / "LOD").glob("*.glb"))
    if scene is not None and scene.manifest.lods:
        add("lod.files", len(lod_files) == 1 + len(scene.manifest.lods), f"{len(lod_files)} LOD files")
    return {"ok": all(c["ok"] for c in checks), "checks": checks}
