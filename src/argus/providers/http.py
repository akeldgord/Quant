"""Shared request-issuing helper: retry + usage accounting together.

Phase 1 remediation round 1, finding #7: when every retry attempt ends in
``httpx.TransportError``, :func:`argus.providers.retry.request_with_retry`
raises *before* returning a response, so an adapter that only records
usage after a successful call silently drops that real outbound attempt
from accounting. :func:`send_with_usage` centralizes retry + usage
recording for every provider adapter so that never happens again in any
one of them individually, and so a transport-exhaustion failure and a
usage-recorder failure can never mask each other:

- a transport-exhaustion failure is recorded (status ``transport_error``,
  the real attempt count) and then the original exception is re-raised
  unchanged;
- if the usage recorder itself raises (e.g. a DB error) while recording
  either outcome, that failure is swallowed, never propagated in place of
  -- or on top of -- the actual provider outcome.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Awaitable, Callable

import httpx

from argus.clock import Clock
from argus.providers.retry import RetryPolicy, request_with_retry
from argus.providers.usage import RequestUsageRecord, UsageRecorder


async def _record_best_effort(
    usage_recorder: UsageRecorder | None, record: RequestUsageRecord
) -> None:
    if usage_recorder is None:
        return
    # Usage accounting must never mask the real provider outcome -- a
    # recorder failure (e.g. a DB error) is swallowed here, not raised.
    with contextlib.suppress(Exception):
        await usage_recorder.record_request(record)


async def send_with_usage(
    send: Callable[[], Awaitable[httpx.Response]],
    *,
    policy: RetryPolicy,
    usage_recorder: UsageRecorder | None,
    clock: Clock,
    provider: str,
    endpoint: str,
    request_class: str,
) -> httpx.Response:
    requested_at = clock.utc_now()
    start = time.monotonic()
    try:
        outcome = await request_with_retry(send, policy=policy)
    except httpx.TransportError:
        await _record_best_effort(
            usage_recorder,
            RequestUsageRecord(
                provider=provider,
                endpoint=endpoint,
                request_class=request_class,
                requested_at=requested_at,
                status="transport_error",
                cache_hit=False,
                response_at=clock.utc_now(),
                latency_ms=int((time.monotonic() - start) * 1000),
                retry_count=max(policy.max_attempts - 1, 0),
                bytes_received=None,
            ),
        )
        raise

    response = outcome.response
    await _record_best_effort(
        usage_recorder,
        RequestUsageRecord(
            provider=provider,
            endpoint=endpoint,
            request_class=request_class,
            requested_at=requested_at,
            status="ok" if not response.is_error else "http_error",
            cache_hit=False,
            response_at=clock.utc_now(),
            latency_ms=int((time.monotonic() - start) * 1000),
            retry_count=outcome.retry_count,
            bytes_received=len(response.content),
        ),
    )
    return response
