# Unity 6 integration

> **Status:** the Unity package is generated and integrity-verified by the Studio. It has **not** been imported into Unity 6 by the Studio (no Unity in the build environment). The importer script is untested until you run it once. Treat the first import as the integration test and report results.

## Import steps

1. In your Unity 6 project: Package Manager → *Add package by name* → `com.unity.cloud.gltfast` (glTFast; Unity has no built-in `.glb` importer).
2. Download the package zip from **Exports**, unzip into `Assets/ARO/<asset>/`.
3. Select `Models/<asset>.glb` → run **ARO ▸ Build Vehicle Prefab…** (`Editor/AroAssetImporter.cs`): groups `_LOD0.._LODn` renderers into a **LODGroup** (heights from `Metadata/lods.json`), adds colliders from `Collision/colliders.json` (box / sphere / capsule / convex `MeshCollider`), hides collision meshes, attaches `AroVehicleDescriptor` (plain data — wire it into **your** vehicle controller).
4. Create URP/HDRP Lit materials from `Materials/materials.json` (`unity` section gives `_BaseColor`, `_Metallic`, `_Smoothness = 1 − roughness`, surface type) — or keep glTFast's materials.
5. Configure `WheelCollider`s from `Metadata/vehicle.json` on the `Spin_*`/`Steer_*` nodes. **The Studio contains no vehicle controller and no physics.**

## Conventions (documented, to be confirmed on first import)

| Item | Value |
|---|---|
| Units / up / forward | m / +Y / +Z |
| Handedness | file is right-handed (glTF). Unity is left-handed; glTFast mirrors X on import so the vehicle's left stays left. The importer script applies the same X flip to collider/pivot metadata (`FlipX = true`). **Verify visually on first import**; if your glTFast version differs, flip the constant. |
| Origin | ground, centreline, wheelbase centre |
| Scale | 1 unit = 1 m (no scale factor needed) |
| LOD naming | `<Part>_LOD<n>`; transition heights in `Metadata/lods.json` |
| Collision | node group `Collision`, `COL_*`; convex hulls ≤ 255 triangles |
| Door/mirror limits | degrees about the listed axis (`Metadata/rig.json`); left door negative about +Y |
| Texture settings | `Metadata/texture_import_settings.json` (sRGB, mipmaps, max size) |
| Integrity | `Metadata/checksums.sha256` (`sha256sum -c`) |

## Why not FBX / why LODGroup via script

FBX is proprietary and has no bundled free writer; glTF is an open standard with a free Unity importer. glTF has no LOD concept Unity understands natively, so LODs travel as named nodes plus metadata and the editor script builds the `LODGroup`.

## Reporting back

After importing, record in `docs/acceptance/` whether: the model faces +Z, left/right are correct, LODGroup switches, colliders align, wheel nodes rotate about X. The acceptance report lists stage 22 as BLOCKED until then.
