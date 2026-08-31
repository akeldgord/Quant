"""Shared request-issuing helper: retry + usage accounting together.

Phase 1 remediation round 1, finding #7: when every retry attempt ends in
``httpx.TransportError``, :func:`argus.providers.retry.request_with_retry`
raises *before* returning a response, so an adapter that only records
usage after a successful call silently drops that real outbound attempt
from accounting. :func:`send_with_usage` centralizes retry + usage
recording for every provider adapter so that never happens again in any
one of them individually.

Phase 1 remediation round 2, finding #8: recording used to happen right
after the raw HTTP response arrived -- ``status="ok"`` was written as soon
as the status code wasn't an error, *before* the caller had decoded the
body, checked for a well-formed application-level error, or validated the
response contract. A response that then failed to decode, carried a
well-formed provider-level error, or failed contract validation still had
an "ok" row sitting in the ledger, contradicting the real outcome the
caller actually observed. ``send_with_usage`` now takes the adapter's own
``process`` step (``raise_for_status`` + decode + contract validation +
typed-model construction) as a parameter and records exactly one terminal
outcome, decided only once that step has actually finished, one way or
the other:

- ``"ok"`` -- ``process`` returned a value.
- ``"http_error"`` -- ``process`` raised ``httpx.HTTPStatusError``
  (typically because it called ``response.raise_for_status()``).
- ``"rpc_error"`` / ``"contract_error"`` / any other adapter-specific
  outcome -- ``process`` raised a
  :class:`argus.providers.contract.ProviderResponseError` subclass; the
  exact status recorded is that exception's own ``usage_status``.
- ``"decode_error"`` -- ``process`` raised anything else (e.g. the
  response body wasn't valid JSON) -- a catch-all for "the response could
  not be turned into a result" that no adapter has classified more
  specifically.
- ``"transport_error"`` / ``"timeout"`` -- no response was ever received;
  unchanged from finding #7's original behavior, just split into the two
  cases ``httpx.TimeoutException`` (a specific subclass of
  ``httpx.TransportError``) and every other transport failure, since a
  timeout budget being exhausted is a materially different signal from a
  refused/dropped connection.
- Cancellation (``asyncio.CancelledError``) is a ``BaseException``, not an
  ``Exception``, so it is never caught by any of the classification
  clauses above -- it propagates untouched and nothing is recorded. That
  is deliberate: no terminal outcome actually happened yet, so recording
  one (even a dedicated "cancelled" status) would itself be a fabricated
  row.

Whichever outcome is decided, if the usage recorder itself then raises
(e.g. a DB error), that failure is swallowed -- never propagated in place
of, or on top of, the actual provider outcome above.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Awaitable, Callable

import httpx

from argus.clock import Clock
from argus.providers.contract import ProviderResponseError
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


async def send_with_usage[T](
    send: Callable[[], Awaitable[httpx.Response]],
    *,
    process: Callable[[httpx.Response], T],
    policy: RetryPolicy,
    usage_recorder: UsageRecorder | None,
    clock: Clock,
    provider: str,
    endpoint: str,
    request_class: str,
) -> T:
    requested_at = clock.utc_now()
    start = time.monotonic()

    async def _record(*, status: str, bytes_received: int | None, retry_count: int) -> None:
        await _record_best_effort(
            usage_recorder,
            RequestUsageRecord(
                provider=provider,
                endpoint=endpoint,
                request_class=request_class,
                requested_at=requested_at,
                status=status,
                cache_hit=False,
                response_at=clock.utc_now(),
                latency_ms=int((time.monotonic() - start) * 1000),
                retry_count=retry_count,
                bytes_received=bytes_received,
            ),
        )

    try:
        outcome = await request_with_retry(send, policy=policy)
    except httpx.TimeoutException:
        await _record(
            status="timeout",
            bytes_received=None,
            retry_count=max(policy.max_attempts - 1, 0),
        )
        raise
    except httpx.TransportError:
        await _record(
            status="transport_error",
            bytes_received=None,
            retry_count=max(policy.max_attempts - 1, 0),
        )
        raise

    response = outcome.response
    try:
        result = process(response)
    except httpx.HTTPStatusError:
        await _record(
            status="http_error",
            bytes_received=len(response.content),
            retry_count=outcome.retry_count,
        )
        raise
    except ProviderResponseError as exc:
        await _record(
            status=exc.usage_status,
            bytes_received=len(response.content),
            retry_count=outcome.retry_count,
        )
        raise
    except Exception:
        await _record(
            status="decode_error",
            bytes_received=len(response.content),
            retry_count=outcome.retry_count,
        )
        raise

    await _record(
        status="ok", bytes_received=len(response.content), retry_count=outcome.retry_count
    )
    return result
