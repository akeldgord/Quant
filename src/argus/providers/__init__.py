"""Provider protocols (MASTER_SPEC.md section 10: PROVIDER ARCHITECTURE).

Domain and persistence code must never depend on a provider-specific
response object -- only on these protocols and the canonical dataclasses
they return. A concrete adapter (``argus.providers.helius``,
``argus.providers.dexscreener``, ...) implements one or more of these;
``argus.ingestion``/``argus.parsing`` code is written entirely against the
protocols, so a fake implementation is a first-class citizen for tests
(see ``tests/unit/test_reconciliation.py``), not a special case.
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Protocol

from argus.providers.models import ExecutableQuote, OhlcvPage, TokenSnapshot, UnsignedOrderResult


@dataclasses.dataclass(frozen=True, slots=True)
class SignatureInfo:
    """One entry from a provider's "signatures for address" history list."""

    signature: str
    slot: int
    block_time: datetime | None
    err: Any | None


@dataclasses.dataclass(frozen=True, slots=True)
class StreamNotification:
    """One fast-path notification from a live subscription."""

    wallet_address: str
    signature: str
    slot: int


@dataclasses.dataclass(frozen=True, slots=True)
class SignatureStatusInfo:
    """One entry from a provider's "signature statuses" batch query --
    the real code path for detecting FINALIZED commitment (Phase 1
    remediation round 1, finding #3: a schema-only ``finalized_at`` column
    with no writer is not real tracking)."""

    signature: str
    confirmation_status: str | None  # "processed" | "confirmed" | "finalized" | None (unknown)
    err: Any | None
    slot: int | None


class ChainProvider(Protocol):
    """RPC-style chain data access (MASTER_SPEC.md section 10)."""

    async def get_transaction(self, signature: str) -> dict[str, Any]:
        """Return the raw provider transaction payload (preserved verbatim
        by callers as ``chain_events.raw_payload``)."""
        ...

    async def get_signatures_for_address(
        self,
        wallet_address: str,
        *,
        until_signature: str | None = None,
        before_signature: str | None = None,
        limit: int = 1000,
    ) -> list[SignatureInfo]:
        """Signatures affecting ``wallet_address``, newest first.

        ``until_signature`` is the fixed lower boundary for an entire
        paginated fetch (exclusive) -- results never go older than it.
        ``before_signature`` is the per-page cursor (exclusive): the
        caller passes the oldest signature from the previous page to
        continue paging backward from there. A caller reconstructing a
        gap larger than ``limit`` must call this repeatedly, holding
        ``until_signature`` fixed and advancing ``before_signature`` each
        time, until a page returns fewer than ``limit`` entries (or none)
        -- mirroring real Solana ``getSignaturesForAddress`` pagination
        semantics exactly, not hiding them behind a single truncated
        list (Phase 1 remediation round 1, finding #2)."""
        ...

    async def get_signature_statuses(self, signatures: list[str]) -> list[SignatureStatusInfo]:
        """Batch commitment-status lookup (maps to Solana's
        ``getSignatureStatuses``) -- the real code path a finalization
        sweep uses to detect a CONFIRMED event's later promotion to
        FINALIZED."""
        ...

    async def get_balance(self, wallet_address: str) -> int:
        """Lamports balance."""
        ...

    async def get_token_accounts(self, wallet_address: str) -> list[dict[str, Any]]: ...

    async def get_slot(self) -> int: ...


class StreamSubscription(Protocol):
    """One live, already-acknowledged WebSocket subscription (Phase 1
    remediation round 2, finding #1). Only ever exists once the socket
    connection was opened, the subscribe request was actually sent, and a
    valid matching acknowledgement was actually received -- never before,
    and never merely because a caller constructed an async generator that
    hasn't been iterated yet (the exact defect finding #1 names: an
    implicit async-generator lifecycle lets a caller believe a
    subscription is live before any of that has genuinely happened)."""

    def notifications(self) -> AsyncIterator[StreamNotification]:
        """An async-iterable of fast-path notifications for this
        subscription. Implementations must raise (not silently stop
        iterating) on disconnect, so callers can distinguish "no new
        activity" from "the connection dropped". Declared as a plain
        (non-``async``) ``def`` for the same reason as
        :meth:`LiveChainStream.open_subscription` below is not -- see
        that method's docstring."""
        ...

    async def close(self) -> None:
        """Closes the underlying connection. Idempotent."""
        ...


class LiveChainStream(Protocol):
    """WebSocket-style live subscription (MASTER_SPEC.md section 10)."""

    async def open_subscription(self, wallet_address: str) -> StreamSubscription:
        """Connects, sends the subscribe request, and waits for a valid
        matching acknowledgement -- all of it, eagerly, before returning
        (Phase 1 remediation round 2, finding #1). Never returns (and a
        caller must never treat the stream dimension as ready) until all
        three have genuinely happened. Raises on any failure at any of
        those three steps; never returns a subscription for a failed or
        unacknowledged attempt.

        Declared ``async def`` (unlike :meth:`StreamSubscription.notifications`)
        specifically because callers *must* await it to completion before
        proceeding -- that awaiting is the whole point of this method
        existing separately from notification delivery."""
        ...

    async def unsubscribe_wallet(self, wallet_address: str) -> None: ...


class MarketDataProvider(Protocol):
    """DexScreener/GeckoTerminal-style market data (MASTER_SPEC.md section 10).

    Returns the canonical models in :mod:`argus.providers.models` (Phase 1
    remediation round 2, finding #7) -- never a provider-shaped
    ``dict[str, Any]``. Provider-specific raw JSON stays inside the
    adapter; only immutable raw evidence explicitly preserved on the
    model's ``raw`` field is exposed."""

    async def token_snapshot(self, mint: str) -> TokenSnapshot:
        """Current price/liquidity/volume/pair-creation metadata."""
        ...

    async def historical_ohlcv(self, mint: str, *, start: datetime, end: datetime) -> OhlcvPage: ...


class ExecutionProvider(Protocol):
    """Jupiter-style quote/order construction (MASTER_SPEC.md section 10).

    Deliberately has NO ``sign``/``execute``/``broadcast`` method anywhere
    on this protocol -- Phase 1 explicitly forbids signing or live
    execution (MASTER_SPEC.md section 108 / this instruction's absolute
    prohibitions). Any later phase that adds real execution must do so on
    a separate, explicitly-isolated interface, not by extending this one.

    Returns the canonical models in :mod:`argus.providers.models` (finding
    #7) -- never a provider-shaped ``dict[str, Any]``.
    """

    async def get_quote(
        self, *, input_mint: str, output_mint: str, amount_raw: int
    ) -> ExecutableQuote: ...

    async def build_unsigned_order(
        self, *, quote: ExecutableQuote, wallet_address: str
    ) -> UnsignedOrderResult:
        """Constructs an unsigned order/transaction for inspection only."""
        ...
