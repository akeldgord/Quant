"""DexScreener adapter (MASTER_SPEC.md section 12, PROV-002): pair/token
lookup, current liquidity/price/volume, and pair-creation metadata. No API
key required for the public free-tier endpoints used here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from argus.clock import Clock
from argus.providers.contract import require_dict, require_key, require_list, require_numeric_string
from argus.providers.http import send_with_usage
from argus.providers.retry import RetryPolicy
from argus.providers.usage import UsageRecorder

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
        response = await send_with_usage(
            lambda: self._http.get(f"{self._base_url}/latest/dex/tokens/{mint}"),
            policy=self._retry_policy,
            usage_recorder=self._usage_recorder,
            clock=self._clock,
            provider="dexscreener",
            endpoint="token_snapshot",
            request_class="rest",
        )
        response.raise_for_status()
        data = require_dict(response.json(), context="DexScreener token_snapshot")
        pairs = data.get("pairs")
        if pairs is not None:
            for pair in require_list(pairs, context="DexScreener token_snapshot 'pairs'"):
                pair_obj = require_dict(pair, context="DexScreener token_snapshot pair entry")
                price = pair_obj.get("priceUsd")
                if price is not None:
                    require_numeric_string(price, context="DexScreener pair 'priceUsd'")
                for side in ("baseToken", "quoteToken"):
                    token = pair_obj.get(side)
                    if token is not None:
                        require_key(
                            require_dict(token, context=f"DexScreener pair {side!r}"),
                            "address",
                            context=f"DexScreener pair {side!r}",
                        )
        return data

    async def historical_ohlcv(
        self, mint: str, *, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "DexScreener does not provide historical OHLCV; use "
            "argus.providers.geckoterminal.GeckoTerminalClient (MASTER_SPEC.md PROV-003)"
        )
