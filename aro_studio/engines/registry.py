"""Engine registry + licence gate."""

from __future__ import annotations

from aro_studio.core.errors import EngineUnavailableError, InvalidInputError
from aro_studio.engines.base import EngineInfo, ImageTo3DEngine

# Models that must never become part of the production pipeline, with the reason (spec §3).
BLOCKED_MODELS: dict[str, str] = {
    "nvidia-lyra-2.0": "NVIDIA Lyra 2.0: its published licence restricts production use and generating works for "
    "sale/distribution, which is incompatible with ARO's commercial workflow.",
    "lyra": "See nvidia-lyra-2.0.",
}


class EngineRegistry:
    def __init__(self) -> None:
        self._engines: dict[str, ImageTo3DEngine] = {}

    def register(self, engine: ImageTo3DEngine) -> None:
        eid = engine.info.id.lower()
        if eid in BLOCKED_MODELS or any(b in eid for b in ("lyra",)):
            raise InvalidInputError(
                f"Engine '{engine.info.id}' is blocked: {BLOCKED_MODELS.get(eid, BLOCKED_MODELS['nvidia-lyra-2.0'])}"
            )
        if engine.info.license.status == "prohibited" or engine.info.license.commercial_use == "prohibited":
            raise InvalidInputError(
                f"Engine '{engine.info.id}' has a licence that prohibits our use and cannot be registered."
            )
        self._engines[engine.info.id] = engine

    def get(self, engine_id: str) -> ImageTo3DEngine:
        try:
            return self._engines[engine_id]
        except KeyError:
            raise InvalidInputError(
                f"Unknown engine '{engine_id}'.", recommended_action=f"Available engines: {sorted(self._engines)}"
            ) from None

    def all(self) -> list[ImageTo3DEngine]:
        return list(self._engines.values())

    def infos(self) -> list[EngineInfo]:
        return [e.info for e in self._engines.values()]


def license_gate(engine: ImageTo3DEngine, verified_ids: set[str]) -> None:
    """Refuse to run a model whose weights licence has not been verified by the deployer."""
    lic = engine.info.license
    if lic.status == "verified" or engine.info.id.lower() in verified_ids:
        if lic.commercial_use in ("prohibited", "restricted") and engine.info.id.lower() not in verified_ids:
            raise EngineUnavailableError(f"{engine.info.name}: commercial use is {lic.commercial_use}.")
        return
    raise EngineUnavailableError(
        f"The licence of the '{engine.info.name}' weights ({lic.spdx}) is {lic.status}, not yet verified for production use.",
        recommended_action=(
            f"Read the model card at {lic.source_url}, confirm it permits commercial use of the weights AND outputs, "
            f"then set ARO_VERIFIED_MODEL_LICENSES={engine.info.id} in the environment. See docs/models/model-licenses.md."
        ),
        details={"engine": engine.info.id, "license": lic.spdx, "license_status": lic.status},
    )
