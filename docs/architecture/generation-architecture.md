# Generation architecture

## Engine contract (`engines/base.py`)

```python
class ImageTo3DEngine(ABC):
    info: EngineInfo                 # id, name, version, revision, licence record, requirements
    availability(device) -> Availability   # ok + exact reasons + activation steps
    presets() / normalize_settings(...)    # deterministic: feeds the cache key
    estimate_resources(settings, device)   # flags whether the number is measured
    load(device) / unload() / is_loaded
    generate(GenerationRequest) -> GenerationOutput   # real inference or an exception
```

The rest of the Studio only imports this module. Texture generation, segmentation, retopology etc. will get sibling interfaces in the same style when a real implementation exists (none is faked today).

## Job state machine

```
QUEUED → INITIALIZING → PREPROCESSING → GENERATING → POSTPROCESSING → VALIDATING → COMPLETED
                     failure states: FAILED · CANCELLED · TIMEOUT · RESOURCE_LIMIT · MODEL_ERROR · INVALID_INPUT
```

Every transition is persisted with a progress value and message (`jobs`, `job_events`) and streamed over SSE. Failure states are derived from the exception (`core/errors.py::explain_exception`): CUDA OOM → `RESOURCE_LIMIT` with a LOW_RESOURCE recommendation, bad input → `INVALID_INPUT`, engine/licence/runtime problems → `MODEL_ERROR`, etc.

## What `generation/service.py` does

1. Resolve the engine; record model info on the job **before** any gate can fail.
2. Licence gate → availability check → settings normalisation → cache key = `SHA256(image hash + engine + model version + settings + preprocessing)`.
3. **Cache hit** (and not `force`): copy the earlier raw scene into a *new* raw version for this asset; no model load, no GPU time (`model_ran: false`, `reused_from`).
4. Resource preflight (VRAM/RAM/disk vs the engine's estimate) → `RESOURCE_LIMIT` with advice instead of a crash.
5. Validate + preprocess the image; save `model_input.png` and `preprocess.json`.
6. `ModelManager.acquire` loads lazily (one resident model, idle unload, unload immediately if free VRAM < 1.5 GB), runs inference.
7. Reject empty/non-finite output (`MODEL_ERROR`); save the untouched engine file, build the raw scene, write an immutable **raw** version with provenance; record generation metadata (ids, model, version, input hash, settings, device, load/exec time, output format + hash, status, error).
8. Quick mesh sanity inspection → `COMPLETED`.

A failed generation keeps: error + explanation, input parameters, model info, resource snapshots (start/end), log, job id and timestamps. `requeue` re-runs it; nothing is deleted.

## Presets

`LOW_RESOURCE`, `BALANCED`, `HIGH_QUALITY` change the marching-cubes grid / chunk size. Only the default (`BALANCED` ≈ TripoSR's defaults) has a **published** VRAM figure (~6 GB); the others are labelled estimates. Quality is not promised by the names.
