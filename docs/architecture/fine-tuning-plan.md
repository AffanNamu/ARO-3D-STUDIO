# Fine-tuning plan (conditional: nothing here is started or authorised)

Written 2026-10-26. The owner asked for a concrete plan covering datasets, licensing, compute, cost and measurable targets, to be executed
only if real experiments show it is necessary. This is that plan. **No training, no data purchase and no GPU rental happens until a
benchmark gate trips and the owner explicitly authorises the spend.**

## 1. Decision

* **Not from scratch.** A competitive image-to-3D generator is trained on millions of 3D assets with many GPU-weeks; neither the data nor the
  budget exists, and pretrained engines already exceed what we could build.
* **Fine-tuning is the only form worth planning**: a low-rank adapter (LoRA-style) on the shape model of the best engine, and optionally
  on its texture model, specialised on the vehicles ARO needs.
* **The most plausible reason it will be needed is domain gap, not general weakness.** Open generators are trained mostly on Western and
  hobbyist 3D collections. ARO's world (danfo and molue buses, matatu minibuses, keke tricycles, okada motorcycles, tipper and tanker
  trucks, heavily modified or worn vehicles, roadside buildings and market stalls) is under-represented. If the best off-the-shelf engine
  handles a Toyota-style sedan and a standard tractor unit but fails on those, that is the evidence for a specialised model.

## 2. The gate (must be met before any spend)

All of the following, recorded in committed evidence:

1. At least **10 varied reference images** (4+ cars, 4+ trucks, 2+ buses or minibuses), run through the best pretrained engine at its best
   preset, with the Studio's measured gate (`aro_studio/quality/`) and a human verdict on the sheets (P0 in `platform-roadmap.md`).
2. The cheap levers already tried and recorded: higher-resolution presets, a cleaner cut-out, supplied real dimensions, a second and third
   view where an engine accepts them, wheel detection/separation (P2) and photo projection for colour.
3. A **systematic** residual failure, defined as any of: proportion verdict "implausible" on more than 20 % of the set; wheels fused to the
   body on more than half; a recognisable-class failure (a minibus returned as a box truck) on more than 20 %.
4. A written estimate of the fine-tuning cost (section 5) accepted by the owner.

If the gate does not trip, the answer is: do not train.

## 3. What would be fine-tuned

| Option | What | Cost/benefit | Verdict |
|---|---|---|---|
| LoRA on the shape DiT of the chosen engine | Adapts geometry to vehicle proportions and classes | Smallest compute, most direct effect on the failure the gate measures | First choice |
| Texture/PBR stage adapter | Adapts surface appearance (paint, rust, dust) | Needs paired textured data; only worth it if geometry is solved | Second |
| Conditioning adapter (multi-view input) | Accept front/side/back photos | Larger change, needs multi-view training pairs | Only if single-view stays weak |
| Full fine-tune or from scratch | | Data and compute out of proportion | No |

The base engine must be chosen by the P0 results and by licence: TRELLIS.2 ships training code and has an MIT code licence (weights licence
to be read); TripoSG is MIT code (training code availability to be checked); **Hunyuan3D is excluded**: its licence forbids using its Outputs to
improve other models, and a derived model would inherit its territory limits.

## 4. Data

The data must be legally trainable, commercially usable and of known provenance. Every item goes in a **data bill of materials**: file hash,
source, licence text and date, author, permitted uses, and the decision (included / excluded / why).

| Source | Licence position | Use |
|---|---|---|
| ARO's own assets and artist work | Owned | Best: clear, curated, on-brand; the core of the set |
| Commissioned models of African vehicles (paid artists) | Contracted, with an AI-training clause | Fills the domain gap; the main cost driver |
| Objaverse / Objaverse-XL | Per-object licences (CC0, CC-BY, CC-BY-SA, CC-BY-NC, others) | Filter to CC0 and CC-BY (and decide with legal advice about CC-BY-SA, whose effect on model weights is unsettled); curate vehicles by tag and by our own quality score; exclude NC |
| ShapeNet | Non-commercial terms | Exclude from a commercial model; research baselines only |
| Marketplace or Sketchfab assets | Per-asset licence and site terms; many forbid AI training | Do not scrape; only items whose licence explicitly allows it |
| Procedural vehicles from our own generator | Owned | Variety of proportions and poses; limited realism: augmentation only |
| Outputs of other AI models | Often forbidden (Hunyuan) or unclear | Do not use |

Volume: for an adapter, hundreds to a few thousand clean vehicles can matter, mixed with general data to avoid forgetting; the licence work and
curation cost more than the compute. Training pairs are renders of each asset from many cameras with cut-outs, in the format the chosen engine's
trainer expects (for TRELLIS.2, encoded structured latents: a heavy preprocessing job of its own).

## 5. Compute and cost (illustrative arithmetic, not quotes)

Prices below are placeholders to show the arithmetic: **verify current rental prices before relying on any figure**; none has been checked.

| Scenario | Assumption | Arithmetic | Order of magnitude |
|---|---|---|---|
| Pilot adapter | 1 GPU with 40-80 GB, 24 h, 200-500 assets, to see whether the failure moves at all | 24 h x (price per GPU hour) | tens of dollars at typical hourly rates |
| Real adapter | 8 GPUs of the A100/H100 class, 2-4 days, 2-5 k assets | 8 x 72 h = 576 GPU-hours x price | hundreds to low thousands of dollars per run, several runs expected |
| Data preparation (latent encoding, renders) | Several GPU-days | similar scale | comparable to one real run |
| Commissioned assets | n artists x assets x price per asset | not estimated: ask for quotes | likely the largest line |
| Evaluation | 30 held-out references, blind human comparison | people time | small |

The number of GPU-hours for a given engine is **unmeasured**: the pilot exists to measure it before committing to the real run.

## 6. Measurable targets

On a **held-out set** of at least 30 references (never in the training or tuning data), compared with the unmodified base engine at the same preset:

| Metric | Target for success |
|---|---|
| Proportion verdict "plausible" | at least 90 % (baseline measured first), and at least +15 points over the base |
| Median silhouette IoU at the best view | at least 0.90 |
| Wheels as distinct round shapes (from P2 detection) | at least 90 % |
| Blind human preference, fine-tuned vs base, at least 3 raters, 30 pairs | at least 70 % prefer the fine-tuned |
| Regression on generic objects (chair, teapot, robot) | IoU within 2 points of the base |
| Licence | Every training item allowed; base licence permits derivatives; derived weights carry the required notices |

Stop rule: if the pilot does not move the proportion rate by at least 10 points, do not scale.

## 7. Steps

| Phase | Work | Spend |
|---|---|---|
| A | Collect P0 evidence; decide whether the gate trips | none |
| B | Data audit: inventory ARO assets, draw up the data bill of materials, legal review of the Objaverse subset, ask for quotes for commissioned models | none (people time) |
| C | Build the render and training-pair pipeline against a tiny set; run it on Colab to prove it works | none |
| D | Pilot adapter on one rented GPU | needs the owner's explicit approval and a stated cap |
| E | Evaluate on the held-out set against the targets; decide | none |
| F | Real training run, then the same evaluation | needs approval with a cap |

## 8. Alternatives that may make training unnecessary

* **Multi-view input:** the user supplies front, side and back photos; engines that accept several views recover depth far better than one photo.
* **Dimensions as input:** supplying the real length, width and height already corrects proportions (stretch is reported).
* **Class priors:** snap detected wheels to round primitives, enforce left-right symmetry, remove ground plates.
* **Kitbash plus generation:** generate a body and combine it with a library of wheels, mirrors and lights (the hybrid game studios actually use).
* **A better base model:** the open field moves quickly; re-run the bake-off before training (the harness exists).
