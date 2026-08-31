"""GeckoTerminal adapter (MASTER_SPEC.md section 12, PROV-003): historical
OHLCV / pool-history market-data fallback only -- MASTER_SPEC.md is
explicit that no live functionality may depend on GeckoTerminal at high
frequency. No API key required for the public free-tier endpoints used
here.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, TypeVar

import httpx

from argus.clock import Clock
from argus.providers.contract import ProviderContractError, require_dict, require_list
from argus.providers.http import send_with_usage
from argus.providers.models import OhlcvCandle, OhlcvPage, TokenSnapshot
from argus.providers.retry import RetryPolicy
from argus.providers.usage import UsageRecorder

T = TypeVar("T")

DEFAULT_BASE_URL = "https://api.geckoterminal.com/api/v2"


def _to_decimal(value: Any, *, context: str) -> Decimal:
    """Coerces a provider-supplied numeric value (int, float, or numeric
    string -- GeckoTerminal's OHLCV/price fields may arrive as any of
    these) to ``Decimal``, never silently accepting a non-numeric value."""
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ProviderContractError(f"{context}: expected a numeric value, got {value!r}") from exc


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
        self,
        url: str,
        *,
        endpoint: str,
        process: Callable[[httpx.Response], T],
        params: dict[str, Any] | None = None,
    ) -> T:
        return await send_with_usage(
            lambda: self._http.get(
                url, params=params, headers={"Accept": "application/json;version=20230302"}
            ),
            process=process,
            policy=self._retry_policy,
            usage_recorder=self._usage_recorder,
            clock=self._clock,
            provider="geckoterminal",
            endpoint=endpoint,
            request_class="rest",
        )

    async def token_snapshot(self, mint: str) -> TokenSnapshot:
        def _process(response: httpx.Response) -> TokenSnapshot:
            response.raise_for_status()
            data = require_dict(response.json(), context="GeckoTerminal token_snapshot")
            price_usd: Decimal | None = None
            pairs_found = 0
            top = data.get("data")
            if top is not None:
                top_obj = require_dict(top, context="GeckoTerminal token_snapshot 'data'")
                pairs_found = 1
                attributes = top_obj.get("attributes")
                if attributes is not None:
                    attributes_obj = require_dict(
                        attributes, context="GeckoTerminal token_snapshot 'data.attributes'"
                    )
                    raw_price = attributes_obj.get("price_usd")
                    if raw_price is not None:
                        price_usd = _to_decimal(
                            raw_price,
                            context="GeckoTerminal token_snapshot 'data.attributes.price_usd'",
                        )
            return TokenSnapshot(
                provider="geckoterminal",
                mint=mint,
                price_usd=price_usd,
                pairs_found=pairs_found,
                raw=data,
            )

        return await self._get(
            f"{self._base_url}/networks/solana/tokens/{mint}",
            endpoint="token_snapshot",
            process=_process,
        )

    async def historical_ohlcv(
        self, mint: str, *, start: datetime, end: datetime, timeframe: str = "hour"
    ) -> OhlcvPage:
        def _process(response: httpx.Response) -> OhlcvPage:
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
                attributes.get("ohlcv_list", []),
                context="GeckoTerminal historical_ohlcv 'ohlcv_list'",
            )
            result: list[OhlcvCandle] = []
            for row in candles:
                row_list = require_list(row, context="GeckoTerminal historical_ohlcv candle row")
                if len(row_list) != 6:
                    raise ProviderContractError(
                        f"GeckoTerminal historical_ohlcv: expected a 6-element candle row, "
                        f"got {row_list!r}"
                    )
                timestamp, open_, high, low, close, volume = row_list
                if not isinstance(timestamp, int | float):
                    raise ProviderContractError(
                        f"GeckoTerminal historical_ohlcv: non-numeric candle timestamp: {row_list!r}"
                    )
                if timestamp < start.timestamp():
                    continue
                result.append(
                    OhlcvCandle(
                        timestamp=int(timestamp),
                        open=_to_decimal(
                            open_, context="GeckoTerminal historical_ohlcv candle 'open'"
                        ),
                        high=_to_decimal(
                            high, context="GeckoTerminal historical_ohlcv candle 'high'"
                        ),
                        low=_to_decimal(low, context="GeckoTerminal historical_ohlcv candle 'low'"),
                        close=_to_decimal(
                            close, context="GeckoTerminal historical_ohlcv candle 'close'"
                        ),
                        volume=_to_decimal(
                            volume, context="GeckoTerminal historical_ohlcv candle 'volume'"
                        ),
                    )
                )
            return OhlcvPage(provider="geckoterminal", mint=mint, candles=tuple(result))

        return await self._get(
            f"{self._base_url}/networks/solana/tokens/{mint}/ohlcv/{timeframe}",
            endpoint="historical_ohlcv",
            process=_process,
            params={"before_timestamp": int(end.timestamp())},
        )
