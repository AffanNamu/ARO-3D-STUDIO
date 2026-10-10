"""Cooperative cancellation + deadline for long jobs."""

from __future__ import annotations

import threading
import time

from aro_studio.core.errors import JobCancelledError, JobTimeoutError


class CancellationToken:
    def __init__(self, timeout_s: float | None = None):
        self._event = threading.Event()
        self._deadline = time.monotonic() + timeout_s if timeout_s else None

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        """Raise if the job was cancelled or timed out. Call between pipeline steps."""
        if self._event.is_set():
            raise JobCancelledError("The job was cancelled.", recommended_action="Re-queue it if needed.")
        if self._deadline is not None and time.monotonic() > self._deadline:
            raise JobTimeoutError(
                "The job exceeded its time limit.",
                recommended_action="Retry with a lighter preset or raise the timeout in Settings.",
            )
