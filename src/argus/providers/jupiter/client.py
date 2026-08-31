"""Jupiter adapter (MASTER_SPEC.md section 12, PROV-004): quotes and
unsigned order construction only.

Deliberately has no signing, execution, or broadcast capability anywhere
in this module -- this is an absolute Phase 1 prohibition (MASTER_SPEC.md
section 108 / this instruction's mandatory prohibitions), not merely
unimplemented. :class:`argus.providers.ExecutionProvider` itself has no
``sign``/``execute`` method for exactly this reason.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from argus.clock import Clock
from argus.providers.retry import RetryPolicy, request_with_retry
from argus.providers.usage import RequestUsageRecord, UsageRecorder

DEFAULT_BASE_URL = "https://quote-api.jup.ag"


class JupiterClient:
    """Implements :class:`argus.providers.ExecutionProvider`. No API key
    required for the public free-tier quote/swap-construction endpoints
    used here."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        base_url: str = DEFAULT_BASE_URL,
        retry_policy: RetryPolicy | None = None,
        usage_recorder: UsageRecorder | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._http = http_client
        self._base_url = base_url
        self._retry_policy = retry_policy or RetryPolicy()
        self._usage_recorder = usage_recorder
        self._clock = clock or Clock()

    async def _send(self, send: Any, *, endpoint: str, request_class: str) -> httpx.Response:
        requested_at = self._clock.utc_now()
        start = time.monotonic()
        outcome = await request_with_retry(send, policy=self._retry_policy)
        response = outcome.response
        if self._usage_recorder is not None:
            await self._usage_recorder.record_request(
                RequestUsageRecord(
                    provider="jupiter",
                    endpoint=endpoint,
                    request_class=request_class,
                    requested_at=requested_at,
                    status="ok" if not response.is_error else "http_error",
                    cache_hit=False,
                    response_at=self._clock.utc_now(),
                    latency_ms=int((time.monotonic() - start) * 1000),
                    retry_count=outcome.retry_count,
                    bytes_received=len(response.content),
                )
            )
        return response

    async def get_quote(
        self, *, input_mint: str, output_mint: str, amount_raw: int, slippage_bps: int = 50
    ) -> dict[str, Any]:
        response = await self._send(
            lambda: self._http.get(
                f"{self._base_url}/v6/quote",
                params={
                    "inputMint": input_mint,
                    "outputMint": output_mint,
                    "amount": amount_raw,
                    "slippageBps": slippage_bps,
                },
            ),
            endpoint="get_quote",
            request_class="quote",
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data

    async def build_unsigned_order(
        self, *, quote: dict[str, Any], wallet_address: str
    ) -> dict[str, Any]:
        """Returns an UNSIGNED transaction payload for inspection/research
        only. There is deliberately no method anywhere in this client that
        signs or submits it."""
        response = await self._send(
            lambda: self._http.post(
                f"{self._base_url}/v6/swap",
                json={
                    "quoteResponse": quote,
                    "userPublicKey": wallet_address,
                    "wrapAndUnwrapSol": True,
                },
            ),
            endpoint="build_unsigned_order",
            request_class="order_construction",
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data
