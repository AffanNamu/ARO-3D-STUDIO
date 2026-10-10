# Asset architecture

## Entities and ids

`project_id` (`prj_…`) → `asset_id` (`ast_…`) → `version_id` (`ver_…`); plus `generation_id`, `job_id`, `export_id`, `validation_id`. Ids are 80-bit random, prefixed, regex-validated at every boundary. Filenames are never identity.

## Storage layout (`data/`)

```
studio.sqlite3                       projects, assets, asset_versions, generations, jobs, job_events, models, model_versions,
                                     model_events, materials, textures, lods, exports, validation_results, source_images, audit_log
logs/ tmp/ cache/preview/
projects/<project_id>/
  source/                            concept images, named <sha256>.<ext>
  generations/<generation_id>/       raw engine output, model_input.png, preprocess.json, generation.json
  assets/<asset_id>/{raw,processed,optimized,final}/<version_id>/
  exports/<export_id>/
```

Stage meaning: `raw` = original reconstruction/import/reference (never modified); `processed` = geometry/material/vehicle/rig changes; `optimized` = decimation/collision/LOD/texture size; `final` = explicitly finalised.

## A version directory

```
manifest.json          SceneManifest (below) incl. SHA-256 of every file
parts/<name>.npz       LOD0 meshes (float32 vertices, uint32 faces, optional uv / vertex colours)
lods/<n>/<name>.npz    LOD n
collision/<name>.npz   hull / custom collision meshes
textures/*.png|jpg
reports/<operation>.json   the report that produced this version (before/after geometry stats, fidelity, …)
```

Versions are written to a staging directory then renamed (atomic), made read-only, and **never modified**. `load_scene` re-hashes everything and refuses a tampered version; `.npz` is loaded with `allow_pickle=False`.

## SceneManifest

`parts` (name, component role, material, hierarchy parent, pivot) · `materials` (PBR metallic-roughness + category) · `textures` · `lods` (per-level parts, ratio, screen height) · `colliders` (box/sphere/capsule/convex hull/mesh/vehicle mesh) · `vehicle` (identity, axles, wheels, suspension/steering points, centre of mass, attachment points, door/mirror/wiper pivots with limits, lights) · `rig` (node hierarchy with roles/axes/limits) · `provenance` (source, engine, model version, generation id, input hash, note).

## Versioning rules

* `add_version` is the only writer; each operation returns a **new** version with `parent_version_id`.
* Raw versions have no parent and cannot be deleted individually; the current production version cannot be deleted; a version with children cannot be deleted.
* One version per asset can be the **CURRENT PRODUCTION VERSION** (`assets.production_version_id`), and only if its latest validation is `PRODUCTION_READY` with 0 critical failures.

## Asset status

`DRAFT · GENERATING · PROCESSING · VALIDATING · NEEDS_REVIEW · APPROVED · PRODUCTION_READY · ARCHIVED · FAILED`. `PRODUCTION_READY` cannot be set directly. Validation moves an asset to `APPROVED` (passed automated validation, eligible) or `NEEDS_REVIEW`/`FAILED`; a human then designates the production version. (`APPROVED` here means *passed automated validation*; a multi-person approval workflow is a future capability.)

## Asset library

Categories (`assets/taxonomy.py`): vehicles (heavy/medium/light trucks, buses, cars, SUVs, pickups, special/emergency/service vehicles), environment (buildings, roads, bridges, signs, street furniture, props), characters (reserved, not creatable yet), other. Structured metadata (`manufacturer`, `brand`, `model`, `category`, `drive_configuration`, `asset_version`, `status`, tags).
