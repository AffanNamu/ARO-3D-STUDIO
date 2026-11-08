"""RunPod Serverless (queue-based endpoint) over its documented HTTP API.

    POST {base}/{endpoint}/run            {"input": {...}, "policy": {"executionTimeout": ms, "ttl": ms}}  ->  {"id", "status"}
    GET  {base}/{endpoint}/status/{id}    ->  {"id", "status", "output"?, "error"?, "delayTime"?, "executionTime"?}
    POST {base}/{endpoint}/cancel/{id}

Statuses: IN_QUEUE, IN_PROGRESS, COMPLETED, FAILED, CANCELLED, TIMED_OUT (docs.runpod.io, read 2026-11-08). Results of /run jobs are kept
for 30 minutes after completion and TTL is a hard limit, so the orchestrator also writes a completion marker to storage.

Error policy (this is what keeps a timeout from becoming a second, paid generation):
  * 4xx (including 429) and connection errors BEFORE the request is sent -> ``ProviderRejected``: nothing was started.
  * a timeout or 5xx after the request was sent                          -> ``ProviderAmbiguous``: do not send again.
The API key is only ever sent in the Authorization header and never appears in an exception message or a log line.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from aro_cloud.providers.base import ProviderAmbiguous, ProviderRejected, ProviderStatus, ProviderUnavailable

MAX_PAYLOAD_BYTES = 9_000_000  # RunPod's /run limit is 10 MB
_STATES = {
    "IN_QUEUE": "queued",
    "IN_PROGRESS": "running",
    "COMPLETED": "succeeded",
    "FAILED": "failed",
    "CANCELLED": "cancelled",
    "TIMED_OUT": "timed_out",
}


class RunPodProvider:
    name = "runpod"

    def __init__(
        self,
        *,
        api_key: str,
        endpoint_id: str,
        base_url: str = "https://api.runpod.ai/v2",
        client: httpx.Client | None = None,
    ):
        if not endpoint_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError("invalid RunPod endpoint id")
        self._root = f"{base_url.rstrip('/')}/{endpoint_id}"
        self._h = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._c = client or httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0), follow_redirects=False)

    # -- run -----------------------------------------------------------------------------------------------------------------
    def submit(self, payload: dict[str, Any], *, execution_timeout_s: int, ttl_s: int) -> str:
        body = {
            "input": payload,
            "policy": {"executionTimeout": execution_timeout_s * 1000, "ttl": ttl_s * 1000, "lowPriority": False},
        }
        raw = json.dumps(body, separators=(",", ":")).encode()
        if len(raw) > MAX_PAYLOAD_BYTES:
            raise ProviderRejected("the job input is too large for the provider")
        try:
            r = self._c.post(f"{self._root}/run", content=raw, headers=self._h)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise ProviderRejected("the GPU provider could not be reached", retryable=True) from None
        except httpx.HTTPError as e:  # the request may have been delivered
            raise ProviderAmbiguous(f"no answer from the GPU provider ({type(e).__name__})") from None
        if 400 <= r.status_code < 500:
            raise ProviderRejected(
                f"the GPU provider refused the job (HTTP {r.status_code})", retryable=r.status_code == 429
            )
        if r.status_code >= 500 or r.status_code != 200:
            raise ProviderAmbiguous(f"the GPU provider answered HTTP {r.status_code}")
        try:
            run_id = r.json().get("id")
        except ValueError:
            run_id = None
        if not isinstance(run_id, str) or not run_id or len(run_id) > 200:
            raise ProviderAmbiguous("the GPU provider's answer had no job id")
        return run_id

    # -- status / cancel -------------------------------------------------------------------------------------------------------
    def status(self, run_id: str) -> ProviderStatus:
        try:
            r = self._c.get(f"{self._root}/status/{_safe_id(run_id)}", headers=self._h)
        except httpx.HTTPError as e:
            raise ProviderUnavailable(f"status check failed ({type(e).__name__})") from None
        if r.status_code == 404:
            return ProviderStatus("unknown", raw_status="404")
        if r.status_code == 429 or r.status_code >= 500:
            raise ProviderUnavailable(f"status check answered HTTP {r.status_code}")
        if r.status_code != 200:
            raise ProviderUnavailable(f"status check refused (HTTP {r.status_code})")
        try:
            d = r.json()
        except ValueError:
            raise ProviderUnavailable("status answer was not JSON") from None
        raw = str(d.get("status", ""))
        out = d.get("output")
        err = d.get("error")
        return ProviderStatus(
            _STATES.get(raw, "unknown"),
            output=out if isinstance(out, dict) else None,
            error=str(err)[:500]
            if err
            else (str(out.get("error"))[:500] if isinstance(out, dict) and out.get("error") else None),
            execution_ms=_int(d.get("executionTime")),
            delay_ms=_int(d.get("delayTime")),
            raw_status=raw,
        )

    def cancel(self, run_id: str) -> None:
        try:
            r = self._c.post(f"{self._root}/cancel/{_safe_id(run_id)}", headers=self._h)
        except httpx.HTTPError as e:
            raise ProviderUnavailable(f"cancel failed ({type(e).__name__})") from None
        if r.status_code not in (200, 404):
            raise ProviderUnavailable(f"cancel answered HTTP {r.status_code}")


def _safe_id(run_id: str) -> str:
    if not run_id or not all(ch.isalnum() or ch in "-_" for ch in run_id):
        raise ProviderUnavailable("invalid provider job id")
    return run_id


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
