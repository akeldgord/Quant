"""GeckoTerminal adapter (MASTER_SPEC.md section 12, PROV-003): historical
OHLCV / pool-history market-data fallback only -- MASTER_SPEC.md is
explicit that no live functionality may depend on GeckoTerminal at high
frequency. No API key required for the public free-tier endpoints used
here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from argus.clock import Clock
from argus.providers.contract import ProviderContractError, require_dict, require_list
from argus.providers.http import send_with_usage
from argus.providers.retry import RetryPolicy
from argus.providers.usage import UsageRecorder

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
        return await send_with_usage(
            lambda: self._http.get(
                url, params=params, headers={"Accept": "application/json;version=20230302"}
            ),
            policy=self._retry_policy,
            usage_recorder=self._usage_recorder,
            clock=self._clock,
            provider="geckoterminal",
            endpoint=endpoint,
            request_class="rest",
        )

    async def token_snapshot(self, mint: str) -> dict[str, Any]:
        response = await self._get(
            f"{self._base_url}/networks/solana/tokens/{mint}", endpoint="token_snapshot"
        )
        response.raise_for_status()
        data = require_dict(response.json(), context="GeckoTerminal token_snapshot")
        top = data.get("data")
        if top is not None:
            top_obj = require_dict(top, context="GeckoTerminal token_snapshot 'data'")
            attributes = top_obj.get("attributes")
            if attributes is not None:
                require_dict(attributes, context="GeckoTerminal token_snapshot 'data.attributes'")
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
        payload = require_dict(response.json(), context="GeckoTerminal historical_ohlcv")
        data_obj = require_dict(
            payload.get("data", {}), context="GeckoTerminal historical_ohlcv 'data'"
        )
        attributes = require_dict(
            data_obj.get("attributes", {}),
            context="GeckoTerminal historical_ohlcv 'data.attributes'",
        )
        candles = require_list(
            attributes.get("ohlcv_list", []), context="GeckoTerminal historical_ohlcv 'ohlcv_list'"
        )
        result = []
        for row in candles:
            row_list = require_list(row, context="GeckoTerminal historical_ohlcv candle row")
            if len(row_list) != 6:
                raise ProviderContractError(
                    f"GeckoTerminal historical_ohlcv: expected a 6-element candle row, got {row_list!r}"
                )
            timestamp, open_, high, low, close, volume = row_list
            if not isinstance(timestamp, int | float):
                raise ProviderContractError(
                    f"GeckoTerminal historical_ohlcv: non-numeric candle timestamp: {row_list!r}"
                )
            if timestamp < start.timestamp():
                continue
            result.append(
                {
                    "timestamp": timestamp,
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                }
            )
        return result
