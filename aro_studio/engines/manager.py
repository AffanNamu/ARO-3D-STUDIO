"""Model memory management (spec §31): lazy load, single resident model, idle unload, load metrics."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

from aro_studio.db.database import Database, dumps
from aro_studio.engines.base import ImageTo3DEngine
from aro_studio.engines.registry import EngineRegistry
from aro_studio.observability.logging import get_logger

log = get_logger("models")


def resolve_device(requested: str) -> str:
    """``auto`` → cuda if torch sees one, else cpu. Never imports torch unless needed."""
    if requested != "auto":
        return requested
    import importlib.util

    if importlib.util.find_spec("torch") is None:
        return "cpu"
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:  # noqa: BLE001
        return "cpu"


class ModelManager:
    """Only one model is resident at a time (free GPUs are small). Models load on first use."""

    def __init__(self, registry: EngineRegistry, db: Database | None = None, idle_unload_s: int = 300):
        self.registry, self.db, self.idle_unload_s = registry, db, idle_unload_s
        self._lock = threading.RLock()
        self._resident: str | None = None
        self._last_used = 0.0
        self.last_load_time_s: dict[str, float] = {}

    def _event(
        self, model_id: str, event: str, device: str | None = None, duration: float | None = None, **details
    ) -> None:
        log.info("model %s: %s", model_id, event, extra={"stage": "model"})
        if self.db:
            self.db.execute(
                "INSERT INTO model_events(ts,model_id,event,device,duration_s,details) VALUES (?,?,?,?,?,?)",
                (time.time(), model_id, event, device, duration, dumps(details)),
            )

    @property
    def resident(self) -> str | None:
        return self._resident

    @contextmanager
    def acquire(self, engine_id: str, device: str) -> Iterator[tuple[ImageTo3DEngine, float]]:
        """Yield ``(engine, model_load_seconds)``. Holds the lock: one generation at a time per process."""
        with self._lock:
            engine = self.registry.get(engine_id)
            load_s = 0.0
            if self._resident and self._resident != engine_id:
                self.unload()
            if not engine.is_loaded:
                self._event(engine_id, "loading", device)
                t0 = time.perf_counter()
                try:
                    engine.load(device)
                except Exception as e:
                    self._event(engine_id, "load_failed", device, error=f"{type(e).__name__}: {e}"[:500])
                    raise
                load_s = time.perf_counter() - t0
                self.last_load_time_s[engine_id] = load_s
                self._resident = engine_id
                self._event(engine_id, "loaded", device, load_s)
            self._last_used = time.time()
            try:
                yield engine, load_s
            finally:
                self._last_used = time.time()

    def unload(self) -> None:
        with self._lock:
            if self._resident:
                eng = self.registry.get(self._resident)
                eng.unload()
                self._event(self._resident, "unloaded")
                self._resident = None

    def unload_if_idle(self) -> bool:
        with self._lock:
            if self._resident and time.time() - self._last_used > self.idle_unload_s:
                self.unload()
                return True
            return False

    def status(self) -> dict:
        return {
            "resident": self._resident,
            "idle_unload_s": self.idle_unload_s,
            "last_load_time_s": self.last_load_time_s,
        }
