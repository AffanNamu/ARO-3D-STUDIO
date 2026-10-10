# Common problems

| Symptom | Cause | What to do |
|---|---|---|
| Generation job ends **MODEL_ERROR**: "cannot run in this environment" | torch / `tsr` / weights missing, or no GPU | Read the job's `recommended_action`; see [model-requirements](../models/model-requirements.md). Meanwhile import a mesh or use the TITAN 480 reference. |
| MODEL_ERROR: "licence … not yet verified" | the weights licence gate | Read the model card, then set `ARO_VERIFIED_MODEL_LICENSES=<engine id>` |
| **RESOURCE_LIMIT** "GPU memory insufficient" | VRAM too small for the preset | LOW_RESOURCE preset, free the GPU, or CPU. The job is kept: **Re-queue** after fixing. |
| RESOURCE_LIMIT: disk/RAM | low free disk/RAM | Settings → clean temp files; delete exports; free memory |
| UV unwrap: "limited to 25,000 triangles" | native-library stability limit | decimate first (Geometry → Decimate), then bake colour from the raw version |
| UV unwrap: "crashed the native xatlas library" | xatlas bug (isolated in a subprocess) | clean the mesh (cleanup preset), reduce triangles; the Studio itself is unaffected |
| Validation `NEEDS_REVIEW` with a high score | a critical/major rule failed | open the report; fix the listed rule; re-validate the **new** version |
| "has not been validated" when designating production | designation requires a passing validation of that exact version | run Validate on that version |
| Export shows **FAILED** | verification failed or an exception | open Exports → report; failed exports are kept with their error |
| Khronos validator "not run" | Node.js / npm `gltf-validator` not installed | optional: `npm i -g gltf-validator`, set `ARO_GLTF_VALIDATOR_NODE_PATH` |
| 401 in the UI | `ARO_ACCESS_TOKEN` is set | enter the token (Settings or the prompt) |
| 429 | rate limit | wait the `Retry-After` seconds; polling job status is exempt |
| Viewer says WebGL unavailable | browser/GPU blocklist | enable hardware acceleration; processing/exports still work |
| Projects vanished on a Space | ephemeral disk after restart | export projects regularly; consider persistent storage (paid, opt-in) |
| Model faces the wrong way / lies on its side | orientation of the raw mesh | Geometry → *Re-orient* (pick current up/forward), confirm in the viewer, then *Scale* and *Pivot* |
| Left/right swapped in Unity | handedness | see [unity-integration](../unity/unity-integration.md) (`FlipX`) |
