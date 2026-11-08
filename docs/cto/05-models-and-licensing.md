# 05 · AI model assessment and licensing report (Phase 2)

Audit date: 2026-11-08 · Status: **PARTIAL.** Weights licences were read from the Hugging Face model-card metadata and code licences from the projects' own files (evidence grade **G**). The licence **texts** of Meta's DINOv3 and of Stability AI's community licence on the Hub, and the dependency chains of Step1X-3D, TRELLIS v1 and UniRig beyond what is listed, were not fully read. Hardware and speed figures are the projects' own statements or third-party reports and must be measured. **No stronger-engine output has been inspected, so nothing here ranks quality.**

## 1. The finding that changes the plan

**TRELLIS.2 is not commercially usable as shipped, although its code and weights are MIT.** Read from its own files:

| Component | What it is | Licence (G) | Why it matters |
|---|---|---|---|
| TRELLIS.2 code | repository | MIT | fine |
| TRELLIS.2-4B weights | `microsoft/TRELLIS.2-4B` | MIT (Hub card) | fine |
| **nvdiffrast** | imported at the top of `o_voxel/postprocess.py`, the function that produces the textured GLB (it rasterises into UV space to bake textures) | NVIDIA Source Code License (1-Way Commercial), section 3.3: use limited to "research or evaluation purposes only and not for any direct or indirect monetary gain" for everyone except NVIDIA | **blocks commercial use of the upstream export path** |
| **nvdiffrec** | only the preview renderer (`EnvironmentLight`) | same non-commercial limit | never install or import it (our worker already avoids it) |
| **BRIA RMBG-2.0** | `pipeline.json` sets `rembg_model` to `briaai/RMBG-2.0`; `from_pretrained` loads it even when a cut-out means it is never run | CC BY-NC 4.0 (Hub card: non-commercial) | must be replaced or removed from the config before any commercial use |
| **DINOv3** | `facebook/dinov3-vitl16-pretrain-lvd1689m`, the image encoder | Meta's own "dinov3-license", gated with **manual approval** | the licence text must be read and access obtained |

**Correction of an earlier statement.** Earlier work in this repository (a comment in the TRELLIS.2 plug-in, a row in `docs/models/model-licenses.md`, the install script) said nvdiffrast's "1-way commercial" licence was acceptable. That was a misreading: "1-way" means NVIDIA may use it commercially and others may not. Those places were corrected in the same change as this report, and TRELLIS.2 is now registered as **restricted, evaluation only**.

**Remediation (engineering, not legal):** (1) replace `to_glb`'s nvdiffrast rasterisation with our own UV-space bake (the Studio already has a CPU barycentric rasteriser in `aro_studio/textures/normal_bake.py`; sampling the voxel attributes is the new part); (2) load the pipeline from a modified config with the BRIA model removed or replaced by an MIT background remover (`ZhengPeng7/BiRefNet` is MIT on the Hub; compatibility untested); (3) read the DINOv3 licence and obtain access; (4) keep nvdiffrec out. Estimated at days of work plus a verification run; until done, TRELLIS.2 may be used for **evaluation only** (see section 5, rule 4).

Also verified: **`diso`**, the CUDA iso-surface package that TripoSG needs, is **CC BY-NC 4.0**. Our worker replaces it with a scikit-image marching-cubes stand-in written for build reasons, which is also the licence-safe choice.

## 2. Licence classes

| Class | Meaning | May be enabled for paying users |
|---|---|---|
| A | code, weights **and the whole dependency chain** read at source; commercial use allowed; no territory limit | yes |
| B | allowed with conditions we can meet (revenue cap, registration, attribution) | yes, after the owner accepts the conditions in writing |
| C | evaluation only | **no** |
| D | blocked (non-commercial or unknown) | **no** |

Enforced twice: the Studio's licence gate refuses unverified engines, and `aro_cloud/migrations/0001_init.sql` forbids `enabled = true` unless `licence_status = 'verified'`. A person, never the agent, records `verified_by` and `verified_at`.

## 3. Candidates (weights licences from Hub model-card metadata, G, 2026-11-08)

| Model | Task | Code licence | Weights licence | Dependency findings | Class today |
|---|---|---|---|---|---|
| **TRELLIS.2-4B** | image to 3D with PBR | MIT | MIT | nvdiffrast (non-commercial) in the export; nvdiffrec preview; BRIA RMBG-2.0 loaded; DINOv3 gated (section 1) | **C** until remediated |
| TRELLIS (v1, `TRELLIS-image-large`) | image to 3D, base colour | MIT | MIT | `postprocessing_utils.py` contains no nvdiffrast import (checked by text search); DINOv2 via `torch.hub` (Apache-2.0 per its project, not re-read); `rembg` library default; preview renderer `diffoctreerast` licence unread | B pending (promising commercial-clean fallback; lower fidelity, no PBR per T) |
| **TripoSG** | image to geometry only | MIT | MIT | requirements list `diso` (CC BY-NC, replaced by our stand-in) and `pymeshlab` (GPL-3.0 per PyPI; used by the example's face reduction); the example script loads BRIA **RMBG-1.4** (licence `bria-rmbg-1.4`, BRIA's own agreement, text not read) which our worker never loads because it is given a cut-out | B pending: confirm with `scripts/check_engine_imports.py` on the final plug-in |
| **TripoSR** | fast image to 3D | MIT | MIT (Hub card; matches the owner's earlier statement) | upstream `run.py` calls `rembg.new_session()` (default model; the Studio supplies a cut-out instead) | A (dependency chain beyond this not re-read) |
| **Step1X-3D** | geometry + texture | Apache-2.0 | Apache-2.0 | `requirements.txt` has no flagged package; the texture stage was not read | pending |
| Direct3D-S2 | high-resolution geometry | MIT | not read | not read | pending |
| UniRig | auto-rigging | MIT | MIT | `open3d` in requirements (MIT per PyPI); rest unread | A pending dependency read |
| Hunyuan3D-2 / 2.1 | shape + PBR texture | Tencent Community Licence | same | **licence "does not apply in the European Union, United Kingdom and South Korea"** (first lines of the LICENSE) | **C** |
| Stable Fast 3D | very fast image to 3D | Stability AI Community Licence | `stabilityai-ai-community` (gated) | free below US$1,000,000 annual revenue, registration required, terminates above it (LICENSE text) | B |
| FLUX.1-schnell | text to image | n/a | Apache-2.0 (Hub card; gated, automatic acceptance) | none read | A pending |
| FLUX.1-dev | text to image | n/a | non-commercial licence | | **D** |
| BRIA RMBG-2.0 and 1.4 | background removal | n/a | RMBG-2.0: CC BY-NC 4.0 (Hub licence link); RMBG-1.4: BRIA's own agreement (`bria-rmbg-1.4`, text not read) | | **D** |
| BiRefNet (ZhengPeng7) | background removal | n/a | MIT (Hub card) | candidate replacement for BRIA | A pending test |
| DINOv3 | image encoder | n/a | Meta "dinov3-license", manual gating | text not read | pending |
| nvdiffrast, nvdiffrec | rendering | NVIDIA source licences | n/a | research or evaluation only | **D** for a commercial service |
| diso | iso-surface CUDA op | CC BY-NC 4.0 | n/a | | **D** |
| Hunyuan3D-Paint, UniTEX, RomanTex, MV-Adapter | texturing | Hunyuan: restricted; others not read | | | C / unread |

Other components: `xatlas` MIT, `open3d` MIT, `scikit-image` BSD (PyPI metadata, G); `trimesh` MIT (earlier dependency audit, R); `pymeshlab` GPL-3.0 (PyPI, G) and Blender's `bpy` GPL-3.0 (audit finding R-06).

## 4. Recommended strategy (a choice per task, not one model for all)

| Task | Primary | Fallback | Condition |
|---|---|---|---|
| Image to 3D with PBR | **TRELLIS.2 after remediation** (own export, no BRIA, DINOv3 read) | TRELLIS v1 or TripoSG with our own projection and bake; Step1X-3D | evaluation run shows it is worth the remediation; weights and chain read |
| Geometry-only, high detail | TripoSG or Direct3D-S2 | TripoSR | dependency read |
| Text to 3D | FLUX.1-schnell then the image-to-3D primary | none | Hub gating accepted; evaluation run |
| Retexture an existing mesh | **no clean candidate** | none | research spike; do not ship a restricted model |
| Character rigging | UniRig | none | dependency read; evaluation run |
| Remesh, UV, LOD, collision, validation | own conventional code | | |

Why TRELLIS.2 stays first in line despite section 1: it is the only open candidate reported to produce full PBR (T), its own repository is MIT, and the blockers are replaceable components rather than the model. If the evaluation run is not clearly better than TripoSG plus our texturing, the remediation work is not worth doing.

## 5. Experiments (small, controlled, capped)

Rules: (1) use an on-demand **Pod**, not a Serverless endpoint, so cold start and idle billing do not blur the measurement; (2) stop the Pod and confirm in the console; (3) record GPU, image tag, time, peak VRAM and cost per run; keep raw meshes out of git; (4) **an evaluation run may use TRELLIS.2 with its upstream code, because the nvdiffrast licence allows research and evaluation, but nothing produced by it may be served to users or sold, and the owner should confirm with counsel that deciding whether to build a product counts as evaluation**; (5) record the licence class of every component actually loaded.

Pod prices read from RunPod's pricing page on 2026-11-08 (G): 48 GB RTX A6000 or A40 **$0.59 per hour**, L40S **$1.09**, RTX 4090 (24 GB) **$0.89**, A100 80 GB $1.79, RTX Pro 6000 96 GB $2.49.

| ID | Question | Setup | Proposed cap | Pass criteria |
|---|---|---|---|---|
| E1 | How fast, how good and how expensive are TRELLIS.2, TRELLIS v1, TripoSG and Step1X-3D on the same images? | one 48 GB Pod (A6000 or A40 at $0.59 per hour; L40S at $1.09 if speed matters) for at most 2 hours, the 6-image benchmark subset, the existing `scripts/engine_bakeoff.py` against `aro_worker` | $3 (about $1.20 to $2.20 of compute plus a few cents of disk) | at least 5 of 6 valid GLBs from the engine(s) that run; VRAM, time and cost recorded; every loaded component's licence recorded; Pod confirmed stopped |
| E1b | Can we replace nvdiffrast's UV bake with our own? | CPU only, no spend | $0 | our bake reproduces the upstream texture within a measured tolerance on 3 outputs |
| E3 | Text to 3D through FLUX.1-schnell | same Pod | $1 | 10 prompts give valid GLBs |
| E4 | Is UniRig usable on generated characters? | an 8 GB-class Pod | $1 | 5 characters get a skeleton and play an animation in Blender |
| E5 | A licence-clean retexture path | desk research | $0 | a named candidate with licence read, or a documented "no" |

Proposed ceiling across all experiments: **$7**, set by the owner before anything runs; each needs the owner's go-ahead.

## 6. What changed in the repository because of this report

* `aro_worker/engines/trellis2.py`, `aro_studio/engines/remote.py`, `worker/install_engines.sh`, `docs/models/model-licenses.md` and `docs/architecture/product-reassessment.md`: the incorrect "nvdiffrast is acceptable" statements were corrected and TRELLIS.2 is registered as restricted, evaluation only (the Studio then asks for an explicit attestation before it will run, as it does for Hunyuan3D).
* Next code change (Phase 4): a worker plug-in that loads the pipeline from a local config without the BRIA model and, once E1b passes, exports through our own bake.
