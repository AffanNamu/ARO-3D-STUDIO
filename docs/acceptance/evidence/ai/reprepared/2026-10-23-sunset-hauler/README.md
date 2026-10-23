# Re-prepared truck mesh (from a preserved raw TripoSR reconstruction)

**What this is.** The raw mesh produced by real TripoSR inference on a Colab T4 (image "ARO African Roads Sunset Hauler", input
SHA-256 `5ea7f52c…caa716`) was run through the Studio's preparation pipeline again, offline, with the improved settings:
`scripts/reprepare_raw_mesh.py` (raw → auto-process → validate → export → per-LOD audit → six views).

**What this is not.**
* **Not new inference.** The raw mesh's SHA-256 (`376aa3541b91df6800d8e1da3e5ca69bb27b342e18c25b7db4040040134bb646`) equals the
  `output_sha256` / `raw_copy_sha256` in [`partial-runs/2026-10-23-hauler-single-image/smoke-evidence.json`](../../partial-runs/2026-10-23-hauler-single-image/smoke-evidence.json),
  which is where the inference evidence lives. The raw mesh itself (3.1 MB) is kept out of git.
* **Not production-ready, not human-reviewed.** Validation is **NEEDS_REVIEW (75.3 %)**. `human_review` has not been filled in.
* **Not to scale.** The real length was not supplied: the model is 1 m long (a PLACEHOLDER; check U001 fails on purpose).
  Width and height relative to the length are TripoSR's one-view estimate and are too stubby; supply the real dimensions
  (`--length-m --width-m --height-m`) to correct them.
* **Front/back unconfirmed.** The yaw is aligned automatically (long side = forward), but which END is the front is a guess.
* **Not imported into Unity.** The Unity package (`improved-unity-package.zip`, not committed: 5 MB) is integrity-verified by the Studio only.

| File | |
|---|---|
| `improved-prepared.glb` | the prepared export (LOD0 + LOD1-3 + `COL_Hull`), 1,684,208 bytes, SHA-256 `79effb04…83073a` |
| `views/improved-*.png` | six views, smooth-shaded (vertex normals, as exported) |
| `views/baseline-*.png` | the same pipeline with yaw alignment and smoothing switched off, for comparison |
| `report.json` | options, every preparation step, validation checks that failed, Khronos result, per-node audit, roughness |

## Measured on this mesh

| | baseline (no yaw alignment, no smoothing) | improved |
|---|---|---|
| validation | NEEDS_REVIEW 75.0 % | NEEDS_REVIEW **75.3 %** |
| footprint | diagonal in its frame (axis-aligned box 1.054 × 1.028) | squared up: rotated −37.6° (0.987 × 0.749) |
| surface roughness (mean angle between neighbouring triangles, LOD0) | 18.4° | **14.1°** |
| Khronos glTF-Validator 2.0.0-dev.3.10 | 0 errors / 0 warnings | 0 errors / 0 warnings |
| per-LOD / collision audit | pass | pass |

Earlier pipeline (the Colab run, before these changes): validation 67.8 %, with non-manifold edges (G003), degenerate triangles (G004)
and inconsistent normals (G005). Most of the gain to 75 % comes from the topology repair (staged decimation + `remove_non_manifold`);
yaw alignment and smoothing change orientation and appearance far more than the score.

Remaining validation failures on the improved variant: vehicle metadata (V001–V010: wheels/axles/pivots are artist work, nothing
detects them), U001 scale (placeholder size), U004 hierarchy (flat), M005 materials, G007 duplicate vertices (UV seams).
