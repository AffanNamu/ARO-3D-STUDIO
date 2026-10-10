# Texture pipeline

Resolutions: **512 / 1024 / 2048 / 4096** (your choice per operation — never forced to maximum).

| Step | Implementation |
|---|---|
| UV preparation | `xatlas` joint unwrap of all parts that share a material into **one atlas** per material, executed in a **child process** with a timeout |
| Projection / baking | rasterise UV space, interpolate 3D positions, project vertex colour from a *source* mesh (typically the raw reconstruction) by nearest vertex, dilate for seam padding |
| Resize | Lanczos, never upscales |
| Compression | JPEG for opaque colour textures (never for normal/data maps or alpha) |
| Mipmaps | Unity import settings (`generateMipMaps`, sRGB, max size) are emitted per texture; chain size helpers exist. No pre-baked mip files are shipped (the engine generates them) |
| PBR packing | roughness/metallic/occlusion → glTF ORM texture at export |
| Atlas packing | shelf-packing + UV remap implemented as a **library function** (`textures/process.py::pack_atlas`, tested); not wired to a UI operation yet |

## Limits (measured)

* xatlas **segfaulted** on an 82k-face mesh and took 3.7 s for 20k faces with the pinned wheel. UV unwrapping is therefore capped at **25,000 triangles per atlas** (`ARO_*` not exposed; error message tells you to decimate first). The recommended flow: raw (300k faces, vertex colour) → decimate to ≤ 25k → bake colour from the raw mesh.
* Texture *generation* (AI) is not implemented; vertex-colour baking is real projection, not generation.
* Baking uses nearest-vertex colour; very sparse sources give blocky colour (the report includes the maximum projection distance).
