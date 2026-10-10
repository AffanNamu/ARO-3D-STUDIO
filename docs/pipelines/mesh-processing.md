# Mesh processing

## Detection (`geometry/inspect.py`)

Duplicate vertices · degenerate triangles · duplicate triangles · invalid/NaN data · disconnected components (and tiny ones) · inverted/flipped winding · non-manifold edges · holes (boundary loops, figure-8 safe) · self-intersections (R-tree broad phase + vectorised edge-vs-triangle narrow phase, time-budgeted; coplanar overlaps and exactly edge-on-edge contacts are not detected) · excessive polygon count · incorrect scale (vehicle 2–25 m) · incorrect orientation (advisory) · incorrect pivot.

## Operations (`geometry/ops.py`, pure functions → new mesh + report)

| Operation | Notes |
|---|---|
| `remove_invalid`, `merge_vertices`, `remove_degenerate`, `remove_duplicate_faces` | cleanup |
| `remove_small_components` | keeps ≥ ratio of the largest; never removes everything |
| `fix_normals` | consistent winding, outward when closed |
| `fill_holes` | centroid fan for loops ≤ N edges; larger openings are left open and reported |
| `smooth` | Taubin (shrinkage-free), bounded shift reported |
| `decimate` | quadric decimation (`fast-simplification`), UV/vertex colours transferred by nearest vertex (warns) |
| `orient`, `scale`, `uniform_scale`, `set_pivot` | scene-wide transforms: meshes, LODs, colliders and all vehicle/rig data move together; shear and non-axis-aligned rotation with colliders are rejected |

`suggest_orientation` is advisory (longest axis = forward; "up" from vertex density) — confirm in the viewer; it is never applied automatically.

## Versioning

`geometry` runs create a **new** version (`processed`, or `optimized` when decimating) containing a before/after report. The source version is untouched (verified by tests that compare manifests byte-for-byte).
