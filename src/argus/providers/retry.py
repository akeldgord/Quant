"""Generic retry/backoff wrapper for provider HTTP calls (MASTER_SPEC.md
section 12 adapter reliability; Phase 1 mandatory acceptance criterion #15:
"retry/backoff honors configured limits and never fabricates data").

Retries only transient failures -- a connection-level error
(``httpx.TransportError``) or a 5xx response -- and always replays the
exact same real request; it never returns a synthesized response. A
well-formed 4xx response or JSON-RPC application-level error is never
retried here (retrying a deterministic rejection wastes request budget
without recovering anything -- see each client's own error handling).
After the configured attempt budget is exhausted, the last real failure
(exception or still-erroring response) is returned/raised unchanged, so
the caller's own ``raise_for_status()``/contract-validation logic decides
what happens next exactly as it would for a single, unretried call.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Awaitable, Callable

import httpx

from argus.config import ArgusConfig


@dataclasses.dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0

    def delay_for(self, retry_number: int) -> float:
        """Exponential backoff. ``retry_number`` is 0-indexed: the first
        retry (after the initial attempt fails) waits
        ``base_delay_seconds``."""
        return min(self.base_delay_seconds * (2**retry_number), self.max_delay_seconds)


def retry_policy_from_config(config: ArgusConfig) -> RetryPolicy:
    """Reads the shared, top-level ``retry:`` block from
    ``config/providers.yaml`` (merged flat like every other provider
    config key -- see ``argus.config.load_config``). Falls back to
    :class:`RetryPolicy`'s conservative defaults when unset."""
    defaults = RetryPolicy()
    max_attempts = config.get("retry.max_attempts", defaults.max_attempts)
    base_delay = config.get("retry.base_delay_seconds", defaults.base_delay_seconds)
    max_delay = config.get("retry.max_delay_seconds", defaults.max_delay_seconds)
    return RetryPolicy(
        max_attempts=int(max_attempts),
        base_delay_seconds=float(base_delay),
        max_delay_seconds=float(max_delay),
    )


async def _default_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


@dataclasses.dataclass(frozen=True, slots=True)
class RetryOutcome:
    response: httpx.Response
    retry_count: int  # 0 if the first attempt succeeded


async def request_with_retry(
    send: Callable[[], Awaitable[httpx.Response]],
    *,
    policy: RetryPolicy,
    sleep: Callable[[float], Awaitable[None]] = _default_sleep,
) -> RetryOutcome:
    """Calls ``send()`` up to ``policy.max_attempts`` times, always issuing
    a genuine new request on each attempt. Returns as soon as a
    non-server-error response is received. On persistent failure, returns
    the last real (still-erroring) response, or re-raises the last real
    ``httpx.TransportError`` -- never fabricates a response."""
    last_transport_exc: httpx.TransportError | None = None
    last_response: httpx.Response | None = None
    for attempt in range(policy.max_attempts):
        try:
            response = await send()
        except httpx.TransportError as exc:
            last_transport_exc = exc
            last_response = None
        else:
            last_transport_exc = None
            last_response = response
            if not response.is_server_error:
                return RetryOutcome(response=response, retry_count=attempt)
        if attempt < policy.max_attempts - 1:
            await sleep(policy.delay_for(attempt))
    if last_response is not None:
        return RetryOutcome(response=last_response, retry_count=policy.max_attempts - 1)
    assert last_transport_exc is not None
    raise last_transport_exc
