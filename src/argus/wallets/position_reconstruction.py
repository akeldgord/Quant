"""Deterministic V1 weighted-average-cost position reconstruction
(MASTER_SPEC.md section 35 WALLET POSITION RECONSTRUCTION; Phase 3,
`argus-phase-3-001`, remediated by `argus-phase-3-remediation-001`
findings P3-R1 and P3-R3).

Consumes the existing, immutable, append-only ``swaps`` ledger (Phase 1)
directly -- this module never introduces a new raw-event table; ``swaps``
itself already IS "raw position events... so alternative accounting
remains recomputable" (section 35's own persistence requirement),
re-derivable at any time from ``chain_events.raw_payload`` under a new
``parser_version``/``ALGORITHM_VERSION`` without losing anything.

**Round trips, not one row per token lifetime** (P3-R3): a wallet that
fully closes a token position and later reopens it produces two
independently identified :class:`ReconstructedPosition` results for that
mint (``round_trip_index`` 0 and 1), each with its own entry/exit
totals, cost basis, and realized P&L -- never one merged aggregate that
conflates two economically distinct holding periods. A still-open
round trip's ``average_cost_quote`` is always the CURRENT weighted-average
cost of the remaining open inventory (``open_cost_basis /
open_quantity``), never a lifetime-flat average across every buy the
token has ever seen.

**Quote-asset safety** (P3-R3): a round trip is opened and tracked in
exactly one quote asset (whichever the opening BUY used). A later leg
denominated in a different quote asset (e.g. the position was opened in
SOL and a later leg is priced in USDC) is never summed into that
quantity/cost math -- it is excluded from the ledger arithmetic,
preserved as a raw reference, and forces this round trip's confidence to
``LOW`` (excluded from qualification via the existing HIGH/MEDIUM-only
filter) rather than inventing a conversion rate this project has no
authoritative source for.

**Point-in-time cutoff** (P3-R1): callers must supply the same ``as_of``
knowledge-time boundary used for the rest of the scoring pipeline. Any
leg whose own chain timestamp (``block_time``) is later than ``as_of`` --
a malformed/future-dated economic timestamp, since a chain event cannot
be genuinely known to have happened before it happens -- is excluded
entirely from reconstruction (never processed, never contributing
recency credit or quantity/cost math), while the underlying ``swaps`` row
itself is never deleted or mutated. This is independent of, and in
addition to, the caller's own responsibility to first restrict the
``swaps`` list to ``first_seen_at <= as_of`` (this module's own
``as_of`` guard only catches the narrower "corrupted/future chain time"
case that a pure ingestion-time filter cannot).

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
import hashlib
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

ALGORITHM_VERSION: Final[str] = "position_reconstruction_v2"

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

_DUST_EPSILON: Final[Decimal] = Decimal("0.000000000000000001")


@dataclasses.dataclass(frozen=True, slots=True)
class ReconstructedPosition:
    """One derived weighted-average-cost round trip, not yet persisted."""

    token_mint: str
    round_trip_index: int
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
    # Every raw swaps.swap_id (as str) that fed this specific round trip's
    # ledger math (buy/sell legs, including any mixed-quote-excluded leg
    # preserved for traceability) -- never the mint-level uncertain
    # (transfer/unknown/complex) evidence, which cannot be structurally
    # attributed to one round trip.
    contributing_swap_ids: tuple[str, ...]
    # Stable SHA-256 hex digest of contributing_swap_ids -- see module
    # docstring and wallet_positions.WalletPosition.input_manifest_digest.
    input_manifest_digest: str
    # Diagnostic-only, never persisted: how many uncertain (transfer/
    # unknown/complex) events touched this mint, for tests/tooling.
    uncertain_event_count: int
    # Diagnostic-only: legs excluded from this round trip's own ledger
    # math because their quote asset didn't match the round trip's own
    # locked quote asset (P3-R3) -- never summed, never converted.
    mixed_quote_leg_count: int


@dataclasses.dataclass(frozen=True, slots=True)
class _Leg:
    direction: str  # "BUY" or "SELL"
    token_mint: str
    quote_asset_mint: str
    token_qty: Decimal
    quote_qty: Decimal
    at: datetime | None
    slot: int
    swap_id: str


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
            swap_id=str(swap.swap_id),
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
            swap_id=str(swap.swap_id),
        )
    return None


def _digest(swap_ids: tuple[str, ...]) -> str:
    return hashlib.sha256(",".join(sorted(swap_ids)).encode("utf-8")).hexdigest()


def reconstruct_positions_for_wallet(
    swaps: list[Swap], *, as_of: datetime
) -> list[ReconstructedPosition]:
    """Deterministically reconstructs the round trips a wallet's
    ``swaps`` support, per token mint. ``swaps`` may be in any order --
    this function sorts by a fully content-derived key internally to
    guarantee reproducible output regardless of input/query ordering
    (restart/replay safety). Any swap whose ``block_time`` is later than
    ``as_of`` is excluded entirely (see module docstring, P3-R1) -- the
    caller is separately responsible for having already restricted
    ``swaps`` to ``first_seen_at <= as_of`` at the query layer."""
    known_swaps = [s for s in swaps if s.block_time is None or s.block_time <= as_of]

    legs_by_mint: dict[str, list[_Leg]] = {}
    uncertain_by_mint: dict[str, int] = {}
    uncertain_swap_ids_by_mint: dict[str, list[str]] = {}

    # Sort key is entirely content-derived (never event_id/first_seen_at,
    # which are randomly-assigned/ingestion-time values that would make
    # same-slot tie order non-reproducible across an independent re-parse
    # of the same raw evidence -- restart/replay determinism, section 35).
    ordered = sorted(
        known_swaps,
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
                    uncertain_swap_ids_by_mint.setdefault(mint, []).append(str(swap.swap_id))
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
        uncertain_ids = tuple(uncertain_swap_ids_by_mint.get(mint, ()))
        results.extend(_reconstruct_round_trips(mint, legs, uncertain_count, uncertain_ids))
    return results


@dataclasses.dataclass(slots=True)
class _RoundTripState:
    quote_asset_mint: str | None = None
    open_quantity: Decimal = Decimal(0)
    open_cost_basis: Decimal = Decimal(0)
    total_entry_quantity: Decimal = Decimal(0)
    total_entry_value: Decimal = Decimal(0)
    realized_pnl: Decimal = Decimal(0)
    partial_exit_count: int = 0
    first_entry_at: datetime | None = None
    last_entry_at: datetime | None = None
    final_exit_at: datetime | None = None
    oversell_detected: bool = False
    mixed_quote_leg_count: int = 0
    peak_value: Decimal = Decimal(0)
    mfe: Decimal = Decimal(0)
    mae: Decimal = Decimal(0)
    peak_unrealized_gain: Decimal = Decimal(0)
    contributing_swap_ids: list[str] = dataclasses.field(default_factory=list)
    # Authoritative "this round trip has genuine ledger activity" flag --
    # deliberately independent of first_entry_at/final_exit_at, both of
    # which are nullable (a real swap's block_time can itself be
    # unknown/None) and must never double as control-flow sentinels for
    # "has this round trip started/closed."
    has_activity: bool = False


def _reconstruct_round_trips(
    token_mint: str,
    legs: list[_Leg],
    uncertain_count: int,
    uncertain_swap_ids: tuple[str, ...],
) -> list[ReconstructedPosition]:
    if not legs:
        # Touched only by uncertain evidence -- no unambiguous entry to
        # derive a cost basis from. Never fabricated.
        return [
            ReconstructedPosition(
                token_mint=token_mint,
                round_trip_index=0,
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
                contributing_swap_ids=uncertain_swap_ids,
                input_manifest_digest=_digest(uncertain_swap_ids),
                uncertain_event_count=uncertain_count,
                mixed_quote_leg_count=0,
            )
        ]

    round_trips: list[_RoundTripState] = []
    current = _RoundTripState()

    for leg in legs:
        if current.quote_asset_mint is None:
            current.quote_asset_mint = leg.quote_asset_mint
        if leg.quote_asset_mint != current.quote_asset_mint:
            # Never sum two incompatible quote units (P3-R3) -- exclude
            # from ledger math, preserve the reference, downgrade below.
            current.mixed_quote_leg_count += 1
            current.contributing_swap_ids.append(leg.swap_id)
            continue

        current.contributing_swap_ids.append(leg.swap_id)
        current.has_activity = True
        if leg.direction == "BUY":
            current.open_quantity += leg.token_qty
            current.open_cost_basis += leg.quote_qty
            current.total_entry_quantity += leg.token_qty
            current.total_entry_value += leg.quote_qty
            if current.first_entry_at is None:
                current.first_entry_at = leg.at
            current.last_entry_at = leg.at
        else:  # SELL
            average_cost = (
                current.open_cost_basis / current.open_quantity
                if current.open_quantity > 0
                else Decimal(0)
            )
            sell_qty = leg.token_qty
            if sell_qty > current.open_quantity:
                current.oversell_detected = True
            qty_realized = min(sell_qty, current.open_quantity)
            price_per_unit = leg.quote_qty / sell_qty if sell_qty > 0 else Decimal(0)
            if qty_realized > 0:
                leg_pnl = qty_realized * (price_per_unit - average_cost)
                current.realized_pnl += leg_pnl
                current.mfe = max(current.mfe, leg_pnl)
                current.mae = min(current.mae, leg_pnl)
            current.open_cost_basis -= qty_realized * average_cost
            current.open_quantity -= qty_realized
            if current.open_quantity <= _DUST_EPSILON:
                current.open_quantity = Decimal(0)
                current.open_cost_basis = Decimal(0)
                current.final_exit_at = leg.at
            else:
                current.partial_exit_count += 1

        # Fill-price-only mark-to-market: the value of the currently-held
        # quantity at THIS fill's own implied price, and the paper gain
        # that mark would represent over the running average cost.
        if current.open_quantity > 0:
            implied_price = leg.quote_qty / leg.token_qty if leg.token_qty > 0 else Decimal(0)
            mark_value = current.open_quantity * implied_price
            current.peak_value = max(current.peak_value, mark_value)
            avg_cost_now = (
                current.open_cost_basis / current.open_quantity
                if current.open_quantity > 0
                else Decimal(0)
            )
            unrealized_gain = current.open_quantity * (implied_price - avg_cost_now)
            current.peak_unrealized_gain = max(current.peak_unrealized_gain, unrealized_gain)

        if current.has_activity and current.open_quantity == 0:
            # This round trip just closed -- flush it and start a fresh,
            # independently identified round trip for any later legs.
            # Gated on has_activity (never on final_exit_at, which is
            # nullable and must never double as a control-flow sentinel)
            # so a genuine close is detected even when the closing leg's
            # own block_time happens to be unknown.
            round_trips.append(current)
            current = _RoundTripState()

    if current.has_activity:
        # A trailing still-open round trip.
        round_trips.append(current)

    return [
        _finalize_round_trip(token_mint, index, state, uncertain_count)
        for index, state in enumerate(round_trips)
    ]


def _finalize_round_trip(
    token_mint: str, round_trip_index: int, state: _RoundTripState, uncertain_count: int
) -> ReconstructedPosition:
    # Every state reaching this function has has_activity=True (see
    # _reconstruct_round_trips) and, if flushed via the mid-loop closing
    # branch, open_quantity==0 confirmed at that moment -- open_quantity
    # alone is the reliable signal, never final_exit_at (nullable; a
    # real closing leg's own block_time can itself be unknown).
    status = STATUS_CLOSED if state.open_quantity == 0 else STATUS_OPEN
    holding_duration_seconds: int | None = None
    if state.first_entry_at is not None:
        end_ref = state.final_exit_at if status == STATUS_CLOSED else state.last_entry_at
        if end_ref is not None:
            holding_duration_seconds = max(0, int((end_ref - state.first_entry_at).total_seconds()))

    # This round trip's OWN weighted-average cost: for a still-open round
    # trip, the current remaining open inventory's basis (never a
    # lifetime-flat average across other, unrelated round trips); for a
    # closed round trip, its own entry-weighted average -- both are
    # exactly "this round trip's own economics," never contaminated by
    # any other round trip for the same token (P3-R3).
    if status == STATUS_OPEN:
        average_cost_quote = (
            state.open_cost_basis / state.open_quantity if state.open_quantity > 0 else None
        )
    else:
        average_cost_quote = (
            state.total_entry_value / state.total_entry_quantity
            if state.total_entry_quantity > 0
            else None
        )

    peak_profit_capture = (
        (state.realized_pnl / state.peak_unrealized_gain)
        if state.peak_unrealized_gain > 0
        else None
    )
    # Clamp to [0, 1] -- a realized result can exceed the coarse
    # fill-price-only peak estimate (a later, larger sale at a better
    # price than any earlier held-quantity mark), which is a real
    # property of this approximation, not an error; capture is reported
    # as fully captured (1) rather than a value >1 that would misstate
    # "how much of the peak was captured."
    if peak_profit_capture is not None:
        peak_profit_capture = min(Decimal(1), max(Decimal(0), peak_profit_capture))

    if state.mixed_quote_leg_count > 0 or state.oversell_detected:
        confidence = CONFIDENCE_LOW
    elif uncertain_count > 0:
        confidence = CONFIDENCE_MEDIUM
    else:
        confidence = CONFIDENCE_HIGH

    contributing = tuple(state.contributing_swap_ids)
    return ReconstructedPosition(
        token_mint=token_mint,
        round_trip_index=round_trip_index,
        quote_asset_mint=state.quote_asset_mint or "",
        first_entry_at=state.first_entry_at,
        last_entry_at=state.last_entry_at,
        final_exit_at=state.final_exit_at,
        entry_quantity=state.total_entry_quantity if state.total_entry_quantity > 0 else None,
        entry_value_quote=state.total_entry_value if state.total_entry_quantity > 0 else None,
        average_cost_quote=average_cost_quote,
        partial_exit_count=state.partial_exit_count,
        realized_pnl_quote=state.realized_pnl,
        # Unrealized P&L for a still-open round trip requires a genuinely
        # current/live market price this project has no feed for --
        # never fabricated from a stale historical fill price. A fully
        # CLOSED round trip has no open exposure left, which is a
        # tautological (not fabricated) zero.
        unrealized_pnl_quote=Decimal(0) if status == STATUS_CLOSED else None,
        holding_duration_seconds=holding_duration_seconds,
        mfe_quote=state.mfe,
        mae_quote=state.mae,
        peak_value_quote=state.peak_value if state.peak_value > 0 else None,
        peak_profit_capture=peak_profit_capture,
        confidence=confidence,
        status=status,
        contributing_swap_ids=contributing,
        input_manifest_digest=_digest(contributing),
        uncertain_event_count=uncertain_count,
        mixed_quote_leg_count=state.mixed_quote_leg_count,
    )
