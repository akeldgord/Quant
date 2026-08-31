"""Jupiter adapter (MASTER_SPEC.md section 12, PROV-004): quotes and
unsigned order construction only.

Deliberately has no signing, execution, or broadcast capability anywhere
in this module -- this is an absolute Phase 1 prohibition (MASTER_SPEC.md
section 108 / this instruction's mandatory prohibitions), not merely
unimplemented. :class:`argus.providers.ExecutionProvider` itself has no
``sign``/``execute`` method for exactly this reason.
"""

from __future__ import annotations

from typing import Any

import httpx

from argus.clock import Clock
from argus.providers.contract import require_dict, require_numeric_string, require_str
from argus.providers.http import send_with_usage
from argus.providers.models import ExecutableQuote, UnsignedOrderResult
from argus.providers.retry import RetryPolicy
from argus.providers.usage import UsageRecorder

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
        return await send_with_usage(
            send,
            policy=self._retry_policy,
            usage_recorder=self._usage_recorder,
            clock=self._clock,
            provider="jupiter",
            endpoint=endpoint,
            request_class=request_class,
        )

    async def get_quote(
        self, *, input_mint: str, output_mint: str, amount_raw: int, slippage_bps: int = 50
    ) -> ExecutableQuote:
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
        data = require_dict(response.json(), context="Jupiter get_quote")
        in_amount = require_numeric_string(
            data.get("inAmount"), context="Jupiter get_quote 'inAmount'"
        )
        out_amount = require_numeric_string(
            data.get("outAmount"), context="Jupiter get_quote 'outAmount'"
        )
        return ExecutableQuote(
            provider="jupiter",
            input_mint=input_mint,
            output_mint=output_mint,
            in_amount_raw=int(in_amount),
            out_amount_raw=int(out_amount),
            raw=data,
        )

    async def build_unsigned_order(
        self, *, quote: ExecutableQuote, wallet_address: str
    ) -> UnsignedOrderResult:
        """Returns an UNSIGNED transaction payload for inspection/research
        only. There is deliberately no method anywhere in this client that
        signs or submits it."""
        response = await self._send(
            lambda: self._http.post(
                f"{self._base_url}/v6/swap",
                json={
                    "quoteResponse": quote.raw,
                    "userPublicKey": wallet_address,
                    "wrapAndUnwrapSol": True,
                },
            ),
            endpoint="build_unsigned_order",
            request_class="order_construction",
        )
        response.raise_for_status()
        data = require_dict(response.json(), context="Jupiter build_unsigned_order")
        swap_transaction = require_str(
            data.get("swapTransaction"), context="Jupiter build_unsigned_order 'swapTransaction'"
        )
        return UnsignedOrderResult(
            provider="jupiter", unsigned_transaction_base64=swap_transaction, raw=data
        )
