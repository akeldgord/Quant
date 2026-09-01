"""Deterministic V1 weighted-average-cost position reconstruction
(MASTER_SPEC.md section 35 WALLET POSITION RECONSTRUCTION; Phase 3,
`argus-phase-3-001`).

Consumes the existing, immutable, append-only ``swaps`` ledger (Phase 1)
directly -- this module never introduces a new raw-event table; ``swaps``
itself already IS "raw position events... so alternative accounting
remains recomputable" (section 35's own persistence requirement),
re-derivable at any time from ``chain_events.raw_payload`` under a new
``parser_version``/``ALGORITHM_VERSION`` without losing anything.

For each token a wallet touched, every economically-relevant ``swaps``
row is classified into exactly one of four evidence tiers, in order of
increasing distrust:

- a **SWAP_SIMPLE** leg with exactly one quote-asset side (native SOL,
  normalized by the Phase 1 parser to the literal ``"SOL"``, or USDC) and
  exactly one non-quote side is a genuine, unambiguous BUY or SELL --
  the only evidence this module ever uses to update quantity/cost-basis
  math.
- a **TRANSFER_IN**/**TRANSFER_OUT** touching the token is of uncertain
  economic origin and is NEVER "magically" treated as a purchase or sale
  (section 35's own explicit rule) -- it only ever downgrades this
  position's confidence tier, never its quantity or cost basis.
- an **UNKNOWN**/**SWAP_COMPLEX** leg touching the token is similarly
  uncertain (balance deltas alone cannot prove direction/counterparty
  for a multi-hop route) and also only downgrades confidence.
- a token touched ONLY by uncertain evidence (no genuine SWAP_SIMPLE leg
  at all) gets an ``UNRESOLVED``-confidence position with every
  quantity/value field left ``None`` -- there is no unambiguous entry
  to derive a cost basis from, and this module never fabricates one.

MFE/MAE/peak-value/peak-profit-capture are derived ONLY from the prices
implied by the wallet's own observed fills (quote paid or received
divided by token quantity at each fill) -- this project has no
continuous intraday price feed for arbitrary historical moments, and
never fabricates one. This is an honest, disclosed, fill-price-only
approximation, not a claim of continuous mark-to-market precision.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from argus.domain.swaps import Swap

from argus.domain.wallet_positions import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_UNRESOLVED,
    STATUS_CLOSED,
    STATUS_OPEN,
)

ALGORITHM_VERSION: Final[str] = "position_reconstruction_v1"

CLASSIFICATION_SWAP_SIMPLE: Final[str] = "SWAP_SIMPLE"
CLASSIFICATION_SWAP_COMPLEX: Final[str] = "SWAP_COMPLEX"
CLASSIFICATION_TRANSFER_IN: Final[str] = "TRANSFER_IN"
CLASSIFICATION_TRANSFER_OUT: Final[str] = "TRANSFER_OUT"
CLASSIFICATION_TOKEN_CREATE: Final[str] = "TOKEN_CREATE"
CLASSIFICATION_LP_ACTION: Final[str] = "LP_ACTION"
CLASSIFICATION_UNKNOWN: Final[str] = "UNKNOWN"

# Matches argus.parsing.generic_parser.NATIVE_SOL_ASSET's own normalized
# literal, plus USDC's real mint -- the two quote assets pump.fun/Jupiter/
# Raydium/Orca activity in this project's evidence actually uses. Never
# re-derives this from a live price feed; a swap whose quote leg is
# neither is simply excluded from position math (ambiguous quote asset),
# not guessed at.
QUOTE_ASSETS: Final[frozenset[str]] = frozenset(
    {"SOL", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"}
)

_UNCERTAIN_CLASSIFICATIONS: Final[frozenset[str]] = frozenset(
    {
        CLASSIFICATION_TRANSFER_IN,
        CLASSIFICATION_TRANSFER_OUT,
        CLASSIFICATION_UNKNOWN,
        CLASSIFICATION_SWAP_COMPLEX,
    }
)


@dataclasses.dataclass(frozen=True, slots=True)
class ReconstructedPosition:
    """One derived weighted-average-cost position, not yet persisted."""

    token_mint: str
    quote_asset_mint: str
    first_entry_at: datetime | None
    last_entry_at: datetime | None
    final_exit_at: datetime | None
    entry_quantity: Decimal | None
    entry_value_quote: Decimal | None
    average_cost_quote: Decimal | None
    partial_exit_count: int
    realized_pnl_quote: Decimal | None
    unrealized_pnl_quote: Decimal | None
    holding_duration_seconds: int | None
    mfe_quote: Decimal | None
    mae_quote: Decimal | None
    peak_value_quote: Decimal | None
    peak_profit_capture: Decimal | None
    confidence: str
    status: str
    # Diagnostic-only, never persisted: how many uncertain (transfer/
    # unknown/complex) events touched this mint, for tests/tooling.
    uncertain_event_count: int


@dataclasses.dataclass(frozen=True, slots=True)
class _Leg:
    direction: str  # "BUY" or "SELL"
    token_mint: str
    quote_asset_mint: str
    token_qty: Decimal
    quote_qty: Decimal
    at: datetime | None
    slot: int


def _classify_leg(swap: Swap) -> _Leg | None:
    """A genuine, unambiguous BUY/SELL leg -- exactly one quote-asset
    side and one non-quote side, both amounts present. Anything else
    (both sides quote, both sides non-quote, or a missing amount)
    returns None -- excluded from quantity/cost math, never guessed."""
    if swap.classification != CLASSIFICATION_SWAP_SIMPLE:
        return None
    if swap.input_mint is None or swap.output_mint is None:
        return None
    if swap.input_amount_ui is None or swap.output_amount_ui is None:
        return None
    input_is_quote = swap.input_mint in QUOTE_ASSETS
    output_is_quote = swap.output_mint in QUOTE_ASSETS
    if input_is_quote and not output_is_quote:
        return _Leg(
            direction="BUY",
            token_mint=swap.output_mint,
            quote_asset_mint=swap.input_mint,
            token_qty=swap.output_amount_ui,
            quote_qty=swap.input_amount_ui,
            at=swap.block_time,
            slot=swap.slot,
        )
    if output_is_quote and not input_is_quote:
        return _Leg(
            direction="SELL",
            token_mint=swap.input_mint,
            quote_asset_mint=swap.output_mint,
            token_qty=swap.input_amount_ui,
            quote_qty=swap.output_amount_ui,
            at=swap.block_time,
            slot=swap.slot,
        )
    return None


def reconstruct_positions_for_wallet(swaps: list[Swap]) -> list[ReconstructedPosition]:
    """Deterministically reconstructs one position per token mint the
    wallet's ``swaps`` touch. ``swaps`` may be in any order -- this
    function sorts by ``(slot, signature not available here, so slot
    then block_time)`` internally to guarantee reproducible output
    regardless of input/query ordering (restart/replay safety)."""
    legs_by_mint: dict[str, list[_Leg]] = {}
    uncertain_by_mint: dict[str, int] = {}

    # Sort key is entirely content-derived (never event_id/first_seen_at,
    # which are randomly-assigned/ingestion-time values that would make
    # same-slot tie order non-reproducible across an independent re-parse
    # of the same raw evidence -- restart/replay determinism, section 35).
    ordered = sorted(
        swaps,
        key=lambda s: (
            s.slot,
            s.classification,
            s.input_mint or "",
            s.output_mint or "",
            s.input_amount_raw or 0,
            s.output_amount_raw or 0,
        ),
    )
    for swap in ordered:
        leg = _classify_leg(swap)
        if leg is not None:
            legs_by_mint.setdefault(leg.token_mint, []).append(leg)
            continue
        if swap.classification in _UNCERTAIN_CLASSIFICATIONS:
            for mint in (swap.input_mint, swap.output_mint):
                if mint is not None and mint not in QUOTE_ASSETS:
                    uncertain_by_mint[mint] = uncertain_by_mint.get(mint, 0) + 1
        # TOKEN_CREATE / LP_ACTION and any leg with two quote or two
        # non-quote sides: not a position-relevant directional trade,
        # deliberately excluded from both quantity math and the
        # uncertain-event confidence downgrade.

    all_mints = set(legs_by_mint) | set(uncertain_by_mint)
    results: list[ReconstructedPosition] = []
    for mint in sorted(all_mints):
        # Already in deterministic slot order from the outer sort above --
        # re-sorting here on (slot, direction) alone would discard that
        # same-slot tiebreak, so insertion order is kept as-is.
        legs = legs_by_mint.get(mint, [])
        uncertain_count = uncertain_by_mint.get(mint, 0)
        results.append(_reconstruct_one(mint, legs, uncertain_count))
    return results


def _reconstruct_one(
    token_mint: str, legs: list[_Leg], uncertain_count: int
) -> ReconstructedPosition:
    if not legs:
        # Touched only by uncertain evidence -- no unambiguous entry to
        # derive a cost basis from. Never fabricated.
        return ReconstructedPosition(
            token_mint=token_mint,
            quote_asset_mint="",
            first_entry_at=None,
            last_entry_at=None,
            final_exit_at=None,
            entry_quantity=None,
            entry_value_quote=None,
            average_cost_quote=None,
            partial_exit_count=0,
            realized_pnl_quote=None,
            unrealized_pnl_quote=None,
            holding_duration_seconds=None,
            mfe_quote=None,
            mae_quote=None,
            peak_value_quote=None,
            peak_profit_capture=None,
            confidence=CONFIDENCE_UNRESOLVED,
            status=STATUS_OPEN,
            uncertain_event_count=uncertain_count,
        )

    quote_asset_mint = legs[0].quote_asset_mint
    open_quantity = Decimal(0)
    open_cost_basis = Decimal(0)
    total_entry_quantity = Decimal(0)
    total_entry_value = Decimal(0)
    realized_pnl = Decimal(0)
    partial_exit_count = 0
    first_entry_at: datetime | None = None
    last_entry_at: datetime | None = None
    final_exit_at: datetime | None = None
    oversell_detected = False
    peak_value = Decimal(0)
    mfe = Decimal(0)
    mae = Decimal(0)
    peak_unrealized_gain = Decimal(0)

    for leg in legs:
        if leg.direction == "BUY":
            open_quantity += leg.token_qty
            open_cost_basis += leg.quote_qty
            total_entry_quantity += leg.token_qty
            total_entry_value += leg.quote_qty
            if first_entry_at is None:
                first_entry_at = leg.at
            last_entry_at = leg.at
            final_exit_at = None  # a fresh buy reopens the position
        else:  # SELL
            average_cost = open_cost_basis / open_quantity if open_quantity > 0 else Decimal(0)
            sell_qty = leg.token_qty
            if sell_qty > open_quantity:
                oversell_detected = True
            qty_realized = min(sell_qty, open_quantity)
            price_per_unit = leg.quote_qty / sell_qty if sell_qty > 0 else Decimal(0)
            if qty_realized > 0:
                leg_pnl = qty_realized * (price_per_unit - average_cost)
                realized_pnl += leg_pnl
                mfe = max(mfe, leg_pnl)
                mae = min(mae, leg_pnl)
            open_cost_basis -= qty_realized * average_cost
            open_quantity -= qty_realized
            if open_quantity <= Decimal("0.000000000000000001"):
                open_quantity = Decimal(0)
                open_cost_basis = Decimal(0)
                final_exit_at = leg.at
            else:
                partial_exit_count += 1

        # Fill-price-only mark-to-market: the value of the currently-held
        # quantity at THIS fill's own implied price, and the paper gain
        # that mark would represent over the running average cost.
        if open_quantity > 0:
            implied_price = leg.quote_qty / leg.token_qty if leg.token_qty > 0 else Decimal(0)
            mark_value = open_quantity * implied_price
            peak_value = max(peak_value, mark_value)
            avg_cost_now = open_cost_basis / open_quantity if open_quantity > 0 else Decimal(0)
            unrealized_gain = open_quantity * (implied_price - avg_cost_now)
            peak_unrealized_gain = max(peak_unrealized_gain, unrealized_gain)

    status = STATUS_CLOSED if open_quantity == 0 and final_exit_at is not None else STATUS_OPEN
    holding_duration_seconds: int | None = None
    if first_entry_at is not None:
        end_ref = final_exit_at if status == STATUS_CLOSED else last_entry_at
        if end_ref is not None:
            holding_duration_seconds = max(0, int((end_ref - first_entry_at).total_seconds()))

    # Flat average cost across every BUY fill ever made for this token
    # (paired with entry_quantity/entry_value, both lifetime totals) --
    # not the weighted-average cost basis of only the currently-open
    # remainder, which can differ after a full close and later reopen at
    # a different price. Both are legitimate; this module reports the
    # lifetime figure since that is what entry_quantity/entry_value
    # themselves already describe.
    average_cost_final = (
        total_entry_value / total_entry_quantity if total_entry_quantity > 0 else None
    )
    peak_profit_capture = (
        (realized_pnl / peak_unrealized_gain) if peak_unrealized_gain > 0 else None
    )
    # Clamp to [0, 1] -- a realized result can exceed the coarse
    # fill-price-only peak estimate (a later, larger sale at a better
    # price than any earlier held-quantity mark), which is a real
    # property of this approximation, not an error; capture is reported
    # as fully captured (1) rather than a value >1 that would misstate
    # "how much of the peak was captured."
    if peak_profit_capture is not None:
        peak_profit_capture = min(Decimal(1), max(Decimal(0), peak_profit_capture))

    if oversell_detected:
        confidence = CONFIDENCE_LOW
    elif uncertain_count > 0:
        confidence = CONFIDENCE_MEDIUM
    else:
        confidence = CONFIDENCE_HIGH

    return ReconstructedPosition(
        token_mint=token_mint,
        quote_asset_mint=quote_asset_mint,
        first_entry_at=first_entry_at,
        last_entry_at=last_entry_at,
        final_exit_at=final_exit_at,
        entry_quantity=total_entry_quantity if total_entry_quantity > 0 else None,
        entry_value_quote=total_entry_value if total_entry_quantity > 0 else None,
        average_cost_quote=average_cost_final,
        partial_exit_count=partial_exit_count,
        realized_pnl_quote=realized_pnl if legs else None,
        # Unrealized P&L for a still-open position requires a genuinely
        # current/live market price this project has no feed for --
        # never fabricated from a stale historical fill price. A fully
        # CLOSED position has no open exposure left, which is a
        # tautological (not fabricated) zero.
        unrealized_pnl_quote=Decimal(0) if status == STATUS_CLOSED else None,
        holding_duration_seconds=holding_duration_seconds,
        mfe_quote=mfe if legs else None,
        mae_quote=mae if legs else None,
        peak_value_quote=peak_value if peak_value > 0 else None,
        peak_profit_capture=peak_profit_capture,
        confidence=confidence,
        status=status,
        uncertain_event_count=uncertain_count,
    )
