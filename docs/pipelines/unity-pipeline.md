# Unity pipeline

Formats: **GLB**, **glTF** (+bin/textures), **OBJ/MTL** (LOD0), and the **Unity 6 package**. FBX is not offered (proprietary format; no free, legally clean writer is bundled).

Every export is read back from disk and verified (`export/verify.py`): GLB magic/version/buffer length, unique node names, acyclic hierarchy, accessor ranges/finite data/index bounds/POSITION min-max/unit normals, per-LOD triangle counts equal to the scene, materials present, collision nodes present, wheel spin nodes present, embedded images decode; the Unity package additionally checks directory structure, JSON validity, SHA-256 of every file and each GLB. When Node.js and the npm `gltf-validator` are available the **official Khronos validator** also runs (0 errors / 0 warnings on the TITAN 480 GLB); if it is not available the report says "not run" rather than passing.

Package layout and conventions: see [unity/unity-integration.md](../unity/unity-integration.md). The package is **not** import-tested in Unity by the Studio.
