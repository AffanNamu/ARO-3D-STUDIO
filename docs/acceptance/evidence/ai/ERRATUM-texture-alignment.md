# Erratum: baked colour textures in earlier prepared GLBs are mis-projected (found 2026-10-26)

**Affected:** every prepared GLB committed before this fix whose baked colour texture came from the AI preparation pipeline, in
particular `partial-runs/2026-10-25-golden-hour-single-image/01-prepared.glb` and `reprepared/2026-10-23-sunset-hauler/improved-prepared.glb`
(and any prepared model built from them, e.g. the Unity packages and the four-image run's prepared meshes).

**What was wrong:** the pipeline projected colour from the RAW reconstruction, which is still in the engine's own frame (its native
axes, unit scale), onto a mesh that had meanwhile been rotated to the Studio axes, yaw-aligned, scaled to the requested length and moved
to the ground. The nearest-vertex lookup therefore compared positions from two different coordinate frames, and the texture came out
scrambled (colours plausible in overall hue, wrong in place). Measured with a synthetic mesh whose colour encodes position: correlation
between the baked colour and the true position was about 0.05 with the old code and 1.000 with the fix.

**What was not affected:** geometry, orientation, scale, LODs, collision and the fidelity numbers (they do not use colour). The raw
reconstructions are untouched (they never carried the error) and every raw hash in the evidence is still valid.

**Why it went unnoticed:** the tests checked that the bake step ran and produced coverage, never that colour landed in the right place,
and the contact sheets are grey-shaded. `tests/test_ai_pipeline.py::test_baked_colour_lands_where_the_raw_colour_was_after_orient_scale_and_pivot`
now fails with the old behaviour and passes with the fix.

**Second defect, found while verifying the first fix on the real truck:** closing holes (`fill_holes`) rebuilt the mesh without its vertex colours, so any real reconstruction (they always have openings) reached the bake with no colours and the step reported PASS while baking nothing. Colours now survive hole filling, and a bake that produces no texture is reported as SKIPPED with a reason. (Meshes that had no openings, such as the synthetic test spheres, never showed it.)

**Third defect (the largest in effect), found by importing the exports into Blender:** the GLB writer wrote the Studio's texture
coordinates unchanged. The Studio keeps V pointing up (like OBJ); glTF puts the origin at the TOP-left of the image. Every textured GLB the
Studio ever exported (and every Unity package, which contains the GLB) therefore showed its texture **mirrored vertically** in any
glTF-conforming reader: Blender, Unity, three.js, so also the Studio's own viewer. It went unnoticed because every colour check used a field
that varies only horizontally and our renderer shares the writer's convention. Fixed in `export/gltf.py`; regression tests:
`tests/test_gltf_uv_orientation.py` (decodes the written GLB) and `tests/test_blender_export.py::test_the_texture_lands_where_the_asset_says_not_mirrored`
(Blender samples the texture at each UV corner; both fail on the old writer, the Blender one with a correlation of 0.58 instead of > 0.9).
OBJ was always correct (its V points up as well).

**Fix:** the bake now samples the cleaned full-resolution mesh (`cleaned_version_id`), which carries the raw vertex colours and is in
the same frame as the target.

**To correct the committed assets:** re-export (the V flip lives in the writer) or re-prepare the preserved raw meshes (`scripts/reprepare_raw_mesh.py --raw <raw>.glb ...`). The raw
meshes are not committed (size policy); they are in the evidence zips returned from the Colab runs. Until then treat the textures of
those GLBs as wrong.
