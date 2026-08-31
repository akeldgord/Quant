"""Tests for `argus.providers.retry` (Phase 1 mandatory acceptance
criterion #15: "retry/backoff honors configured limits and never
fabricates data")."""

from __future__ import annotations

import httpx
import pytest

from argus.config import ArgusConfig
from argus.providers.retry import RetryPolicy, request_with_retry, retry_policy_from_config


class _RecordingSleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def _response(status_code: int, *, body: bytes = b"{}") -> httpx.Response:
    request = httpx.Request("GET", "https://example.test/x")
    return httpx.Response(status_code, content=body, request=request)


async def test_succeeds_first_try_never_sleeps() -> None:
    sleep = _RecordingSleep()
    calls = 0

    async def send() -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response(200)

    outcome = await request_with_retry(send, policy=RetryPolicy(max_attempts=3), sleep=sleep)
    assert outcome.retry_count == 0
    assert calls == 1
    assert sleep.delays == []


async def test_retries_on_5xx_then_succeeds_with_exact_backoff_schedule() -> None:
    sleep = _RecordingSleep()
    responses = iter([_response(503), _response(502), _response(200)])

    async def send() -> httpx.Response:
        return next(responses)

    policy = RetryPolicy(max_attempts=3, base_delay_seconds=0.5, max_delay_seconds=8.0)
    outcome = await request_with_retry(send, policy=policy, sleep=sleep)
    assert outcome.response.status_code == 200
    assert outcome.retry_count == 2
    # Exponential backoff: 0.5 * 2**0, 0.5 * 2**1 -- exactly two delays for
    # two retries, never fabricated, never skipped.
    assert sleep.delays == [0.5, 1.0]


async def test_retries_on_transport_error_then_succeeds() -> None:
    sleep = _RecordingSleep()
    attempts = 0

    async def send() -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise httpx.ConnectError(
                "connection refused", request=httpx.Request("GET", "https://x")
            )
        return _response(200)

    outcome = await request_with_retry(send, policy=RetryPolicy(max_attempts=3), sleep=sleep)
    assert outcome.retry_count == 1
    assert attempts == 2


async def test_exhausts_retries_and_returns_last_real_response_never_fabricated() -> None:
    sleep = _RecordingSleep()
    call_count = 0

    async def send() -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return _response(500, body=f"real failure #{call_count}".encode())

    policy = RetryPolicy(max_attempts=3)
    outcome = await request_with_retry(send, policy=policy, sleep=sleep)
    assert call_count == 3  # never attempted more than the configured limit
    assert outcome.retry_count == 2
    assert outcome.response.status_code == 500
    assert (
        outcome.response.content == b"real failure #3"
    )  # the actual last response, not synthesized
    assert len(sleep.delays) == 2  # never sleeps after the final attempt


async def test_exhausts_retries_and_reraises_last_real_transport_error() -> None:
    sleep = _RecordingSleep()
    call_count = 0

    async def send() -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError(
            f"failure #{call_count}", request=httpx.Request("GET", "https://x")
        )

    with pytest.raises(httpx.ConnectError, match="failure #3"):
        await request_with_retry(send, policy=RetryPolicy(max_attempts=3), sleep=sleep)
    assert call_count == 3


async def test_4xx_is_never_retried() -> None:
    sleep = _RecordingSleep()
    call_count = 0

    async def send() -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return _response(404)

    outcome = await request_with_retry(send, policy=RetryPolicy(max_attempts=5), sleep=sleep)
    assert call_count == 1  # a well-formed 4xx is returned immediately, not retried
    assert outcome.retry_count == 0
    assert sleep.delays == []


def test_delay_for_is_exponential_and_capped() -> None:
    policy = RetryPolicy(base_delay_seconds=1.0, max_delay_seconds=3.0)
    assert policy.delay_for(0) == 1.0
    assert policy.delay_for(1) == 2.0
    assert policy.delay_for(2) == 3.0  # capped, would otherwise be 4.0
    assert policy.delay_for(5) == 3.0


def test_retry_policy_from_config_reads_flat_top_level_retry_block() -> None:
    config = ArgusConfig(
        values={"retry": {"max_attempts": 5, "base_delay_seconds": 0.25, "max_delay_seconds": 4.0}},
        sources=(),
        env={},
    )
    policy = retry_policy_from_config(config)
    assert policy.max_attempts == 5
    assert policy.base_delay_seconds == 0.25
    assert policy.max_delay_seconds == 4.0


def test_retry_policy_from_config_defaults_when_unset() -> None:
    policy = retry_policy_from_config(ArgusConfig(values={}, sources=(), env={}))
    assert policy == RetryPolicy()
