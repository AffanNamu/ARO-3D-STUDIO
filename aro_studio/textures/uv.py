"""UV preparation (spec §15): joint xatlas unwrap of one or many parts into a single atlas."""

from __future__ import annotations

import subprocess  # noqa: S404
import sys
import tempfile
from pathlib import Path

import numpy as np
import trimesh

from aro_studio.core.errors import InvalidInputError, ModelError, ResourceLimitError

DEFAULT_MAX_FACES = 25_000
_WORKER = Path(__file__).with_name("_xatlas_worker.py")


def _run_xatlas(
    positions: np.ndarray, indices: np.ndarray, timeout_s: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    with tempfile.TemporaryDirectory(prefix="xatlas_") as td:
        src, dst = Path(td, "in.npz"), Path(td, "out.npz")
        np.savez(src, positions=positions.astype(np.float32), indices=indices.astype(np.uint32))
        try:
            proc = subprocess.run(  # noqa: S603
                [sys.executable, "-I", str(_WORKER), str(src), str(dst)],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise ResourceLimitError(
                f"UV unwrapping exceeded {timeout_s:.0f}s.",
                recommended_action="Decimate the mesh (e.g. to <= 25,000 triangles) before unwrapping.",
            ) from e
        if proc.returncode != 0:
            crashed = proc.returncode < 0
            raise ModelError(
                "UV unwrapping crashed the native xatlas library (the Studio itself is unaffected)."
                if crashed
                else f"UV unwrapping failed: {proc.stderr.strip()[-300:]}",
                recommended_action="Decimate the mesh to <= 25,000 triangles and make sure it is clean (merge vertices, remove degenerate faces) before unwrapping.",
                details={"returncode": proc.returncode},
            )
        with np.load(dst, allow_pickle=False) as z:
            return z["vmapping"].copy(), z["indices"].copy(), z["uvs"].copy()


def unwrap_jointly(
    meshes: dict[str, trimesh.Trimesh], *, max_faces: int = DEFAULT_MAX_FACES, timeout_s: float = 180.0
) -> dict[str, trimesh.Trimesh]:
    """Unwrap all ``meshes`` into ONE shared 0..1 UV atlas. Returns new meshes (vertex-split, with UVs)."""
    names = list(meshes)
    if not names:
        raise InvalidInputError("No meshes to unwrap.")
    total = sum(len(m.faces) for m in meshes.values())
    if total > max_faces:
        raise InvalidInputError(
            f"UV unwrapping is limited to {max_faces:,} triangles per atlas (this selection has {total:,}).",
            recommended_action="Decimate first (Geometry → decimate), then unwrap; high-resolution colour can still be baked from the original.",
        )
    v_off, pos, idx = 0, [], []
    for n in names:
        m = meshes[n]
        pos.append(np.asarray(m.vertices, dtype=np.float32))
        idx.append(np.asarray(m.faces, dtype=np.uint32) + v_off)
        v_off += len(m.vertices)
    positions, indices = np.concatenate(pos), np.concatenate(idx)
    vmapping, new_idx, uvs = _run_xatlas(positions, indices, timeout_s)
    # xatlas keeps face order; verify rather than assume.
    old_c = positions[indices].mean(axis=1)
    new_c = positions[vmapping][new_idx].mean(axis=1)
    if len(new_idx) != len(indices) or not np.allclose(old_c, new_c, atol=1e-4):
        raise ModelError("UV unwrapping changed the face order unexpectedly; refusing to split the atlas.")
    out: dict[str, trimesh.Trimesh] = {}
    f0 = 0
    for n in names:
        m = meshes[n]
        nf = len(m.faces)
        faces_g = new_idx[f0 : f0 + nf]
        f0 += nf
        used, inv = np.unique(faces_g, return_inverse=True)
        verts = positions[vmapping[used]].astype(np.float64)
        nm = trimesh.Trimesh(verts, inv.reshape(-1, 3), process=False)
        nm.visual = trimesh.visual.TextureVisuals(uv=uvs[used].astype(np.float64))
        # index into the ORIGINAL part's vertices (vertex split can duplicate vertices) - lets callers carry colours over
        nm.metadata["source_vertex_index"] = vmapping[used] - sum(
            len(meshes[k].vertices) for k in names[: names.index(n)]
        )
        out[n] = nm
    return out
