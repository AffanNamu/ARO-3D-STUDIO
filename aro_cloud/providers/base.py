"""The GPU-provider contract. The platform never imports a provider's SDK outside ``providers/``: swapping RunPod for another host (or
for several) is a new class here, not a change in the orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderStatus:
    state: str  # queued | running | succeeded | failed | cancelled | timed_out | unknown
    output: dict[str, Any] | None = None
    error: str | None = None
    execution_ms: int | None = None
    delay_ms: int | None = None
    raw_status: str | None = None


class ProviderRejected(Exception):
    """The provider definitely did NOT accept the job (bad request, auth failure, rate limited, never reached). Safe to fail the job and refund.

    ``retryable`` is True only when sending the very same job again later can succeed (rate limited, provider not reachable): nothing
    was started, so a second send cannot become a second paid run."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class ProviderAmbiguous(Exception):
    """The request may or may not have started a run (timeout or 5xx after the request was sent). The job must NEVER be sent again automatically."""


class ProviderUnavailable(Exception):
    """A status/cancel call failed for a reason that is probably temporary. Try again later."""


class ModelProvider(Protocol):
    name: str

    def submit(self, payload: dict[str, Any], *, execution_timeout_s: int, ttl_s: int) -> str:
        """Start one run and return the provider's run id."""

    def status(self, run_id: str) -> ProviderStatus: ...

    def cancel(self, run_id: str) -> None: ...
