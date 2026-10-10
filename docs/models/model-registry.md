# Model registry

Registered at startup in `app_context.py` and recorded in the `models` / `model_versions` tables; shown in the **Models** page.

| Engine id | Capability | Status |
|---|---|---|
| `triposr` | single-image → 3D | adapter implemented; **runnable only where torch + `tsr` + weights + a verified licence exist** (not in the development sandbox) |

## Blocked models

| Id | Reason |
|---|---|
| `nvidia-lyra-2.0` (and any id containing `lyra`) | Per the project owner's supplied licence summary, Lyra 2.0 restricts production use and generating works for sale/distribution. `EngineRegistry.register` refuses it. It can only be unblocked by an independent licence review **and** a code change. |

## Adding an engine

1. Subclass `ImageTo3DEngine` (`engines/base.py`); fill `EngineInfo` with the exact weights version/revision and a `ModelLicense` (`status="claimed"` until *you* have read the licence of the weights).
2. Implement `availability` (return exact reasons + activation steps), `normalize_settings` (deterministic), `estimate_resources` (set `measured=True` only for measured numbers), `load`/`unload`, and `generate` (real inference or an exception — never fallback geometry).
3. Register it in `build_context` (or pass `engines=[…]`).
4. Add its record to [model-licenses.md](model-licenses.md) and requirements to [model-requirements.md](model-requirements.md).
5. Add a gated real-inference test (`@pytest.mark.model`) like `tests/test_triposr_real.py`.

The cache key includes `info.version`, so changing the weights version never reuses stale reconstructions.

## Capabilities with no implementation yet

Text-to-3D, multi-view reconstruction, texture generation/enhancement, AI retopology/UV/rigging/collision, vehicle part detection and separation, AI mesh repair, AI material classification, AI quality scoring, object classification/detection/segmentation. The only extension hook that exists in code is `imaging.analysis.ObjectClassifier` (empty registry → analysis reports *no category*, never an invented one) and the `BackgroundRemover` interface (classical matte + rembg adapter). Nothing else is stubbed to look functional.
