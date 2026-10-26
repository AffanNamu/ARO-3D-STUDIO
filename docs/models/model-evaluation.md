# Model evaluation plan and candidate screen

> **Superseded 2026-10-26.** Real TripoSR output has since been inspected and measured: it fails the proportion floor on a car and
> two trucks. The decision, engine matrix and roadmap are now in [../architecture/product-reassessment.md](../architecture/product-reassessment.md).
> The text below is kept as the original screening protocol.

**Original decision (superseded): do not add or swap an engine yet.** No real TripoSR output had been inspected, so there was no evidence that it is
too crude for ARO's use cases. First run the smoke test ([../verification/real-inference-smoke.md](../verification/real-inference-smoke.md)),
look at the renders, and attribute any poor result to its cause *before* considering another model:

| Symptom | Likely cause | Check |
|---|---|---|
| Blobby / merged geometry, missing back | single-image ambiguity, model limit | compare to the model's published examples |
| Holes / ragged silhouette | bad matte or clutter | open `model_input.png`; try `none` / `rembg`; cleaner photo |
| Squashed / wrong aspect | foreground ratio, perspective-heavy photo | change `foreground_ratio`; use a 3/4 view with little perspective |
| Low detail | marching-cubes grid | `HIGH_QUALITY` (320³) |
| Rotated / mirrored | native frame | `source_axes` in the preparation report; set `up`/`forward` |

## Candidate screen (from general knowledge — every licence below MUST be re-read from the source before use)

| Model | Task | Licence (to verify) | Notes | ARO fit |
|---|---|---|---|---|
| **TripoSR** (in use) | single image → mesh, feed-forward | MIT code + weights (evidence recorded) | ~6 GB VRAM, seconds on a GPU; coarse detail | baseline |
| InstantMesh | image → multi-view diffusion → mesh | Apache-2.0 code; components have their own terms | heavier, better texture; more dependencies | candidate to evaluate |
| Stable Fast 3D | single image → textured mesh | Stability AI Community Licence (revenue-gated, not OSI) | fast, UV-textured; licence needs legal reading | check terms first |
| TRELLIS | image → 3D (structured latents) | MIT per repository | high quality; large VRAM | likely above free-GPU limits |
| Hunyuan3D-2 family | image → 3D | Tencent community licence with territorial restrictions | quality leader; licence may exclude some regions | **licence risk** |
| Wonder3D | multi-view diffusion | AGPL-3.0 | copyleft | **incompatible with a closed product** unless owner decides |

Evaluation protocol for any candidate: the same ≥ 3 images; same smoke harness through a new `ImageTo3DEngine` adapter (registry,
availability, estimate, pinned artefacts with SHA-256, licence status `claimed` until the licence text is read for that exact
artefact); record VRAM/latency; judge by a person on the six renders; compare against TripoSR on ARO's requirements (vehicle
silhouette, wheel regions, texture usefulness). Do not mark a licence `verified` to enable execution.
