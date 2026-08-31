"""DexScreener adapter (MASTER_SPEC.md section 12, PROV-002): pair/token
lookup, current liquidity/price/volume, and pair-creation metadata. No API
key required for the public free-tier endpoints used here.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx

from argus.clock import Clock
from argus.providers.retry import RetryPolicy, request_with_retry
from argus.providers.usage import RequestUsageRecord, UsageRecorder

DEFAULT_BASE_URL = "https://api.dexscreener.com"


class DexScreenerClient:
    """Implements :class:`argus.providers.MarketDataProvider` for current
    market state. DexScreener does not provide historical OHLCV
    (GeckoTerminal is the historical/fallback source -- PROV-003)."""

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

    async def token_snapshot(self, mint: str) -> dict[str, Any]:
        requested_at = self._clock.utc_now()
        start = time.monotonic()
        outcome = await request_with_retry(
            lambda: self._http.get(f"{self._base_url}/latest/dex/tokens/{mint}"),
            policy=self._retry_policy,
        )
        response = outcome.response
        if self._usage_recorder is not None:
            await self._usage_recorder.record_request(
                RequestUsageRecord(
                    provider="dexscreener",
                    endpoint="token_snapshot",
                    request_class="rest",
                    requested_at=requested_at,
                    status="ok" if not response.is_error else "http_error",
                    cache_hit=False,
                    response_at=self._clock.utc_now(),
                    latency_ms=int((time.monotonic() - start) * 1000),
                    retry_count=outcome.retry_count,
                    bytes_received=len(response.content),
                )
            )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data

    async def historical_ohlcv(
        self, mint: str, *, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "DexScreener does not provide historical OHLCV; use "
            "argus.providers.geckoterminal.GeckoTerminalClient (MASTER_SPEC.md PROV-003)"
        )
