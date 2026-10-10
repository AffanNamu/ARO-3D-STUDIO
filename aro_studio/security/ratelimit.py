"""Small in-process sliding-window rate limiter (per client key)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from aro_studio.core.errors import RateLimitedError


class RateLimiter:
    def __init__(self, per_minute: int, window_s: float = 60.0, clock=time.monotonic):
        self.limit = per_minute
        self.window = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = self._clock()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                retry = int(self.window - (now - q[0])) + 1
                raise RateLimitedError(
                    "Too many requests.", recommended_action=f"Wait about {retry}s and retry.", details={"retry_after_s": retry}
                )
            q.append(now)
            if len(self._hits) > 10_000:  # bound memory
                for k in [k for k, v in self._hits.items() if not v]:
                    self._hits.pop(k, None)
