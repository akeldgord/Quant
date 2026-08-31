"""GeckoTerminal adapter (MASTER_SPEC.md section 12, PROV-003): historical
OHLCV / pool-history market-data fallback only -- MASTER_SPEC.md is
explicit that no live functionality may depend on GeckoTerminal at high
frequency. No API key required for the public free-tier endpoints used
here.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx

from argus.clock import Clock
from argus.providers.retry import RetryPolicy, request_with_retry
from argus.providers.usage import RequestUsageRecord, UsageRecorder

DEFAULT_BASE_URL = "https://api.geckoterminal.com/api/v2"


class GeckoTerminalClient:
    """Implements :class:`argus.providers.MarketDataProvider`, primarily
    for :meth:`historical_ohlcv`."""

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

    async def _get(
        self, url: str, *, endpoint: str, params: dict[str, Any] | None = None
    ) -> httpx.Response:
        requested_at = self._clock.utc_now()
        start = time.monotonic()
        outcome = await request_with_retry(
            lambda: self._http.get(
                url, params=params, headers={"Accept": "application/json;version=20230302"}
            ),
            policy=self._retry_policy,
        )
        response = outcome.response
        if self._usage_recorder is not None:
            await self._usage_recorder.record_request(
                RequestUsageRecord(
                    provider="geckoterminal",
                    endpoint=endpoint,
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
        return response

    async def token_snapshot(self, mint: str) -> dict[str, Any]:
        response = await self._get(
            f"{self._base_url}/networks/solana/tokens/{mint}", endpoint="token_snapshot"
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data

    async def historical_ohlcv(
        self, mint: str, *, start: datetime, end: datetime, timeframe: str = "hour"
    ) -> list[dict[str, Any]]:
        response = await self._get(
            f"{self._base_url}/networks/solana/tokens/{mint}/ohlcv/{timeframe}",
            endpoint="historical_ohlcv",
            params={"before_timestamp": int(end.timestamp())},
        )
        response.raise_for_status()
        payload = response.json()
        candles: list[Any] = payload.get("data", {}).get("attributes", {}).get("ohlcv_list", [])
        return [
            {
                "timestamp": row[0],
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "volume": row[5],
            }
            for row in candles
            if row[0] >= int(start.timestamp())
        ]
