"""The RunPod client against a labelled HTTP test double that follows RunPod's documented queue-endpoint API (docs.runpod.io, read 2026-11-08).

This proves our request shapes, error classification and secret hygiene. It does not prove RunPod's behaviour: that needs the owner's endpoint
(scripts/runpod_smoke.py).
"""

from __future__ import annotations

import json

import httpx
import pytest

from aro_cloud.providers import ProviderAmbiguous, ProviderRejected, ProviderUnavailable, RunPodProvider

KEY = "rpa_SECRET_KEY_VALUE_123"


def provider(handler):
    return RunPodProvider(
        api_key=KEY,
        endpoint_id="ep123abc",
        base_url="https://api.test/v2",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_submit_sends_input_and_policy_and_returns_the_id():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"], seen["body"] = str(req.url), req.headers["authorization"], json.loads(req.content)
        return httpx.Response(200, json={"id": "abc-123-u1", "status": "IN_QUEUE"})

    run_id = provider(handler).submit({"engine": "triposg"}, execution_timeout_s=900, ttl_s=1500)
    assert run_id == "abc-123-u1"
    assert seen["url"] == "https://api.test/v2/ep123abc/run" and seen["auth"] == f"Bearer {KEY}"
    assert seen["body"] == {
        "input": {"engine": "triposg"},
        "policy": {"executionTimeout": 900_000, "ttl": 1_500_000, "lowPriority": False},
    }


@pytest.mark.parametrize(
    ("status", "retryable"), [(400, False), (401, False), (403, False), (404, False), (422, False), (429, True)]
)
def test_4xx_means_nothing_was_started(status, retryable):
    with pytest.raises(ProviderRejected) as e:
        provider(lambda r: httpx.Response(status, text=f"nope {KEY}")).submit({}, execution_timeout_s=60, ttl_s=120)
    assert e.value.retryable is retryable
    assert KEY not in str(e.value)


def test_unreachable_provider_is_a_retryable_refusal():
    def handler(req):
        raise httpx.ConnectError("connection refused", request=req)

    with pytest.raises(ProviderRejected) as e:
        provider(handler).submit({}, execution_timeout_s=60, ttl_s=120)
    assert e.value.retryable


@pytest.mark.parametrize(
    "make",
    [
        lambda req: httpx.Response(500),
        lambda req: httpx.Response(502),
        lambda req: httpx.Response(200, text="not json"),
        lambda req: httpx.Response(200, json={"status": "IN_QUEUE"}),
    ],
)
def test_5xx_and_malformed_answers_are_ambiguous(make):
    with pytest.raises(ProviderAmbiguous):
        provider(make).submit({}, execution_timeout_s=60, ttl_s=120)


def test_a_timeout_after_sending_is_ambiguous_and_never_retried_by_the_client():
    calls = []

    def handler(req):
        calls.append(1)
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(ProviderAmbiguous):
        provider(handler).submit({}, execution_timeout_s=60, ttl_s=120)
    assert len(calls) == 1


def test_oversized_input_is_refused_before_it_is_sent():
    with pytest.raises(ProviderRejected):
        provider(lambda r: pytest.fail("must not be sent")).submit(
            {"blob": "x" * 9_500_000}, execution_timeout_s=60, ttl_s=120
        )


@pytest.mark.parametrize(
    ("raw", "state"),
    [
        ("IN_QUEUE", "queued"),
        ("IN_PROGRESS", "running"),
        ("COMPLETED", "succeeded"),
        ("FAILED", "failed"),
        ("CANCELLED", "cancelled"),
        ("TIMED_OUT", "timed_out"),
        ("SOMETHING_NEW", "unknown"),
    ],
)
def test_status_mapping(raw, state):
    st = provider(
        lambda r: httpx.Response(200, json={"id": "x", "status": raw, "executionTime": 12000, "delayTime": 300})
    ).status("x")
    assert st.state == state and st.execution_ms == 12000 and st.delay_ms == 300


def test_status_carries_output_and_error():
    ok = provider(lambda r: httpx.Response(200, json={"status": "COMPLETED", "output": {"ok": True}})).status("x")
    assert ok.output == {"ok": True}
    bad = provider(lambda r: httpx.Response(200, json={"status": "FAILED", "error": '{"code":"oom"}'})).status("x")
    assert bad.error == '{"code":"oom"}'


def test_status_404_is_unknown_and_outages_are_unavailable():
    assert provider(lambda r: httpx.Response(404)).status("x").state == "unknown"
    for code in (429, 500, 503, 401):
        with pytest.raises(ProviderUnavailable):
            provider(lambda r, c=code: httpx.Response(c)).status("x")


def test_run_ids_cannot_inject_paths():
    with pytest.raises(ProviderUnavailable):
        provider(lambda r: pytest.fail("must not be sent")).status("../../other/endpoint")


def test_cancel_tolerates_404_and_reports_outages():
    p404 = provider(lambda r: httpx.Response(404))
    p404.cancel("x")
    with pytest.raises(ProviderUnavailable):
        provider(lambda r: httpx.Response(500)).cancel("x")


def test_endpoint_id_is_validated():
    with pytest.raises(ValueError):
        RunPodProvider(api_key=KEY, endpoint_id="../evil", base_url="https://api.test/v2")
