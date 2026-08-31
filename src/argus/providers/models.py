"""Canonical, immutable ARGUS response models (Phase 1 remediation round
2, finding #7).

``MarketDataProvider``/``ExecutionProvider`` previously returned bare
``dict[str, Any]`` -- provider-shaped JSON handed straight to callers, who
had no choice but to index provider-specific keys directly (and every
provider shapes the *same* logical thing differently: DexScreener's
token snapshot is a list of pairs; GeckoTerminal's is a single
``data.attributes`` object). These dataclasses are the canonical shape
every adapter normalizes into, validated before construction, so no
domain/consumer code ever indexes a provider-specific dictionary again.

Financial fields use ``Decimal`` (never ``float``, which cannot represent
every decimal price/amount exactly) or raw integer base units, matching
the pattern already established for ``argus.parsing.generic_parser``'s
``ParsedTransaction``.

Provider-specific raw JSON stays inside each adapter -- except immutable
raw evidence explicitly preserved on ``raw`` here, for the rare consumer
that genuinely needs a provider-specific field these canonical models
don't surface. Raw Solana *transaction* evidence is a different case
(preserved verbatim in ``chain_events.raw_payload`` because its purpose
is immutable replay, not because it's read directly by domain code) and
is unaffected by this module.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from decimal import Decimal
from types import MappingProxyType
from typing import Any


def _frozen_mapping(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(raw))


@dataclasses.dataclass(frozen=True, slots=True)
class TokenSnapshot:
    """Current price/liquidity metadata for one mint -- the canonical
    shape :meth:`argus.providers.MarketDataProvider.token_snapshot`
    returns, normalized from whichever provider-specific shape (a list of
    DexScreener pairs, a single GeckoTerminal ``data.attributes`` object)
    produced it."""

    provider: str
    mint: str
    price_usd: Decimal | None
    pairs_found: int
    raw: Mapping[str, Any]


@dataclasses.dataclass(frozen=True, slots=True)
class OhlcvCandle:
    """One OHLCV bar. ``timestamp`` is Unix seconds (UTC); OHLC/volume are
    ``Decimal`` (a provider's own numeric encoding -- int or numeric
    string -- is normalized here once, not left for every consumer to
    re-parse)."""

    timestamp: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclasses.dataclass(frozen=True, slots=True)
class OhlcvPage:
    """The canonical shape :meth:`argus.providers.MarketDataProvider.historical_ohlcv`
    returns: an ordered page of :class:`OhlcvCandle`."""

    provider: str
    mint: str
    candles: tuple[OhlcvCandle, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class ExecutableQuote:
    """The canonical shape :meth:`argus.providers.ExecutionProvider.get_quote`
    returns. Raw base-unit integer amounts (never a float) -- exactly
    what a real swap instruction actually encodes."""

    provider: str
    input_mint: str
    output_mint: str
    in_amount_raw: int
    out_amount_raw: int
    raw: Mapping[str, Any]


@dataclasses.dataclass(frozen=True, slots=True)
class TokenAccountInfo:
    """One SPL token account entry from
    :meth:`argus.providers.ChainProvider.get_token_accounts` -- the
    canonical shape every adapter normalizes into (Phase 1 remediation
    round 4, finding #4), never the provider-shaped
    ``getTokenAccountsByOwner`` ``jsonParsed`` dict handed straight to
    callers. ``amount_raw`` is the token's raw base-unit balance (never a
    float-parsed UI amount)."""

    pubkey: str
    mint: str
    owner: str
    amount_raw: int
    decimals: int
    raw: Mapping[str, Any]


@dataclasses.dataclass(frozen=True, slots=True)
class UnsignedOrderResult:
    """The canonical shape :meth:`argus.providers.ExecutionProvider.build_unsigned_order`
    returns -- an unsigned transaction payload for inspection only. No
    method anywhere in this module (or ``ExecutionProvider``) ever signs,
    executes, or broadcasts it (MASTER_SPEC.md section 108)."""

    provider: str
    unsigned_transaction_base64: str
    raw: Mapping[str, Any]
