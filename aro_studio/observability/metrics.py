"""In-process performance metrics (counters + timing summaries)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from contextlib import contextmanager


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, float] = defaultdict(float)
        self._timings: dict[str, list[float]] = defaultdict(list)
        self.started = time.time()

    def incr(self, name: str, value: float = 1.0) -> None:
        with self._lock:
            self._counters[name] += value

    def observe(self, name: str, seconds: float) -> None:
        with self._lock:
            t = self._timings[name]
            t.append(seconds)
            if len(t) > 500:
                del t[: len(t) - 500]

    @contextmanager
    def timer(self, name: str):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.observe(name, time.perf_counter() - t0)

    def snapshot(self) -> dict:
        with self._lock:
            timings = {
                k: {"count": len(v), "mean_s": sum(v) / len(v), "max_s": max(v), "last_s": v[-1]}
                for k, v in self._timings.items()
                if v
            }
            return {"uptime_s": time.time() - self.started, "counters": dict(self._counters), "timings": timings}
