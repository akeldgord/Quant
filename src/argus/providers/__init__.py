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


class LiveChainStream(Protocol):
    """WebSocket-style live subscription (MASTER_SPEC.md section 10)."""

    async def subscribe_wallet(self, wallet_address: str) -> AsyncIterator[StreamNotification]:
        """An async-iterable of fast-path notifications for this wallet.
        Implementations must raise (not silently stop iterating) on
        disconnect, so callers can distinguish "no new activity" from
        "the connection dropped"."""
        ...

    async def unsubscribe_wallet(self, wallet_address: str) -> None: ...


class MarketDataProvider(Protocol):
    """DexScreener/GeckoTerminal-style market data (MASTER_SPEC.md section 10)."""

    async def token_snapshot(self, mint: str) -> dict[str, Any]:
        """Current price/liquidity/volume/pair-creation metadata."""
        ...

    async def historical_ohlcv(
        self, mint: str, *, start: datetime, end: datetime
    ) -> list[dict[str, Any]]: ...


class ExecutionProvider(Protocol):
    """Jupiter-style quote/order construction (MASTER_SPEC.md section 10).

    Deliberately has NO ``sign``/``execute``/``broadcast`` method anywhere
    on this protocol -- Phase 1 explicitly forbids signing or live
    execution (MASTER_SPEC.md section 108 / this instruction's absolute
    prohibitions). Any later phase that adds real execution must do so on
    a separate, explicitly-isolated interface, not by extending this one.
    """

    async def get_quote(
        self, *, input_mint: str, output_mint: str, amount_raw: int
    ) -> dict[str, Any]: ...

    async def build_unsigned_order(
        self, *, quote: dict[str, Any], wallet_address: str
    ) -> dict[str, Any]:
        """Constructs an unsigned order/transaction for inspection only."""
        ...
