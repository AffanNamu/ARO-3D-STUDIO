"""One-click "Convert to 3D": reconstruct -> prepare -> export, as ONE queued job built from the existing handlers.

No new reconstruction, preparation or export logic lives here: the generation, auto-preparation and export handlers run
unchanged, each behind a thin :class:`StageContext` that maps its progress into its share of the job and prefixes its status
messages ("Step 2 of 4 · ..."). Rules inherited from the parts and kept here:

* the real engine runs or the job fails - no placeholder geometry (the generation handler's rule);
* the raw version is immutable; preparation creates new versions (the pipeline's rule);
* a failure in a later stage never discards earlier results: the raw asset stays, and the job's annotations list every stage
  with its status, so the UI can say exactly where it stopped and what was kept;
* the ORIGINAL exception is re-raised, so job states (MODEL_ERROR, RESOURCE_LIMIT, CANCELLED, TIMEOUT...) stay honest.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from aro_studio.core.enums import JobState
from aro_studio.jobs.queue import JobContext

Handler = Callable[[Any], dict[str, Any]]

# (key, label, progress range inside the job). Step 1 ("check the image") happens synchronously when the file is uploaded.
STAGES = (
    ("reconstruct", "Reconstruct 3D", 0.0, 0.55),
    ("prepare", "Prepare mesh", 0.55, 0.90),
    ("export", "Export GLB", 0.90, 1.0),
)
TOTAL_STEPS = len(STAGES) + 1

GENERATION_KEYS = (
    "project_id",
    "asset_id",
    "image_sha256",
    "engine_id",
    "preset",
    "settings",
    "preprocess",
    "use_cache",
    "force",
)
PREPARE_KEYS = ("length_m", "length_supplied", "up", "forward", "target_triangles", "texture_resolution", "lod")


class StageContext:
    """The slice of a JobContext a stage handler uses, scoped to one stage of the parent job."""

    def __init__(
        self,
        parent: JobContext,
        params: dict[str, Any],
        index: int,
        label: str,
        lo: float,
        hi: float,
        state: JobState | None,
    ):
        self._parent, self.params, self._label, self._lo, self._hi, self._state = parent, params, label, lo, hi, state
        self._step = index + 2  # step 1 is the upload check
        self.job_id, self.kind, self.project_id, self.asset_id, self.cancel = (
            parent.job_id,
            parent.kind,
            parent.project_id,
            parent.asset_id,
            parent.cancel,
        )

    def _map(self, progress: float | None) -> float | None:
        if progress is None:
            return None
        return self._lo + (self._hi - self._lo) * max(0.0, min(1.0, float(progress)))

    def _msg(self, message: str) -> str:
        head = f"Step {self._step} of {TOTAL_STEPS} · {self._label}"
        return f"{head}: {message}" if message else head

    def set_state(self, state: JobState, progress: float | None = None, message: str = "") -> None:
        self._parent.set_state(self._state or state, self._map(progress), self._msg(message))

    def progress(self, progress: float, message: str = "") -> None:
        self._parent.progress(self._map(progress) or 0.0, self._msg(message))

    def log(self, message: str, level: str = "INFO") -> None:
        self._parent.log(message, level)

    def check(self) -> None:
        self._parent.check()

    def annotate(self, **kw: Any) -> None:
        self._parent.annotate(**kw)


def convert_handler(generation: Handler, prepare: Handler, export: Handler) -> Handler:
    def run(ctx: JobContext) -> dict[str, Any]:
        p = ctx.params
        stages: list[dict[str, Any]] = [{"stage": k, "label": lbl, "status": "NOT_RUN"} for k, lbl, _, _ in STAGES]
        by = {s["stage"]: s for s in stages}
        out: dict[str, Any] = {}

        def stage(key: str, handler: Handler, params: dict[str, Any], state: JobState | None) -> dict[str, Any]:
            idx = [k for k, *_ in STAGES].index(key)
            _, label, lo, hi = STAGES[idx]
            rec = by[key]
            rec["status"] = "RUNNING"
            t = time.perf_counter()
            try:
                res = handler(StageContext(ctx, params, idx, label, lo, hi, state))
            except BaseException as e:  # noqa: BLE001 - recorded, then the ORIGINAL error continues (honest job state)
                rec.update(
                    status="FAILED", seconds=round(time.perf_counter() - t, 2), error=f"{type(e).__name__}: {e}"[:400]
                )
                ctx.annotate(convert_stages=stages, convert_failed_stage=key, **out)
                raise
            rec.update(status="COMPLETED", seconds=round(time.perf_counter() - t, 2))
            return res

        gen = stage("reconstruct", generation, {k: p[k] for k in GENERATION_KEYS if k in p}, None)
        out["raw_version_id"] = gen["version_id"]
        out["generation_id"] = gen["generation_id"]
        by["reconstruct"].update(
            model_ran=bool(gen.get("model_ran")), reused_from=gen.get("reused_from"), version_id=gen["version_id"]
        )

        prep = stage(
            "prepare",
            prepare,
            {"raw_version_id": gen["version_id"], **{k: p[k] for k in PREPARE_KEYS if k in p}},
            JobState.PROCESSING,
        )
        out["final_version_id"] = prep["final_version_id"]
        by["prepare"].update(
            version_id=prep["final_version_id"], validation=(prep.get("validation") or {}).get("status")
        )

        exp = stage(
            "export",
            export,
            {"version_id": prep["final_version_id"], "formats": p.get("formats") or ["glb"]},
            JobState.PROCESSING,
        )
        exports = exp.get("exports", [])
        glb = next((e for e in exports if e.get("format") == "glb"), None)
        by["export"].update(exports=exports)
        return {
            "asset_id": ctx.asset_id,
            "model_ran": bool(gen.get("model_ran")),
            "reused_from": gen.get("reused_from"),
            "device": gen.get("device"),
            "generation_id": gen["generation_id"],
            "raw_version_id": gen["version_id"],
            "final_version_id": prep["final_version_id"],
            "raw_mesh": gen.get("mesh"),
            "validation": prep.get("validation"),
            "needs_human": prep.get("needs_human", []),
            "final_extents_m": prep.get("final_extents_m"),
            "preparation_steps": [{"step": s["step"], "status": s["status"]} for s in prep.get("steps", [])],
            "exports": exports,
            "export_id": glb["export_id"] if glb else None,
            "download": f"/api/exports/{glb['export_id']}/download" if glb else None,
            "stages": stages,
        }

    return run
