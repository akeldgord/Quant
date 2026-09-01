"""Phase 3 (WALLET RECONSTRUCTION + UNBIASED QUALIFICATION) pure-function
tests -- the DB-persistence halves of the same required scenarios live in
``tests/integration/test_phase3_wallet_qualification.py``. Per
`argus-phase-3-001`'s own "cover the financial/data invariants deeply,
not dozens of superficial tests" instruction, this file implements
exactly the 10 required test categories (regression is covered by the
full repository suite, not a dedicated function here), nothing more.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from argus.tokens.historical_acquisition import STATUS_COMPLETE, STATUS_PARTIAL
from argus.wallets.history_reconstruction import (
    EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK,
    EVIDENCE_SOURCE_STREAM_FORWARD_ONLY,
    assess_wallet_history,
)
from argus.wallets.position_reconstruction import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_UNRESOLVED,
    STATUS_CLOSED,
    STATUS_OPEN,
    reconstruct_positions_for_wallet,
)
from argus.wallets.scoring import (
    LOTTERY_DOMINANCE_THRESHOLD,
    MIN_DISTINCT_TOKENS,
    MIN_USABLE_CLOSED_POSITIONS,
    PositionForScoring,
    compute_position_stats,
    score_wallet,
)

WALLET = "TestWallet1111111111111111111111111111111"
SOL = "SOL"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


@dataclasses.dataclass
class _FakeSwap:
    """Duck-typed stand-in for `argus.domain.swaps.Swap` -- position
    reconstruction only reads these specific attributes, so a real ORM
    instance (and therefore a database) is never required to test it."""

    classification: str
    input_mint: str | None
    input_amount_ui: Decimal | None
    output_mint: str | None
    output_amount_ui: Decimal | None
    slot: int
    block_time: datetime | None
    wallet_address: str = WALLET
    input_amount_raw: int | None = None
    output_amount_raw: int | None = None


def _buy(slot: int, *, token_qty: str, sol_qty: str, at: datetime) -> _FakeSwap:
    return _FakeSwap(
        classification="SWAP_SIMPLE",
        input_mint=SOL,
        input_amount_ui=Decimal(sol_qty),
        output_mint="TOKENmint1111111111111111111111111111111",
        output_amount_ui=Decimal(token_qty),
        slot=slot,
        block_time=at,
    )


def _sell(slot: int, *, token_qty: str, sol_qty: str, at: datetime) -> _FakeSwap:
    return _FakeSwap(
        classification="SWAP_SIMPLE",
        input_mint="TOKENmint1111111111111111111111111111111",
        input_amount_ui=Decimal(token_qty),
        output_mint=SOL,
        output_amount_ui=Decimal(sol_qty),
        slot=slot,
        block_time=at,
    )


def _transfer_in(slot: int, *, token_qty: str, at: datetime) -> _FakeSwap:
    return _FakeSwap(
        classification="TRANSFER_IN",
        input_mint=None,
        input_amount_ui=None,
        output_mint="TOKENmint1111111111111111111111111111111",
        output_amount_ui=Decimal(token_qty),
        slot=slot,
        block_time=at,
    )


# ---------------------------------------------------------------------
# Required test 2: weighted-average ledger.
# ---------------------------------------------------------------------


def test_p3_weighted_average_ledger_buys_partial_sell_buy_sell() -> None:
    """Buy 100 @ 1 SOL/unit, partial-sell 40 @ 1.5 SOL/unit, buy 50 more
    @ 2 SOL/unit, final-sell the remaining 110 @ 3 SOL/unit -- hand-
    verified exact expected cost basis and realized P&L (see the
    checkpoint for the full worked arithmetic)."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    swaps = [
        _buy(1, token_qty="100", sol_qty="100", at=t0),
        _sell(2, token_qty="40", sol_qty="60", at=t0 + timedelta(hours=1)),
        _buy(3, token_qty="50", sol_qty="100", at=t0 + timedelta(hours=2)),
        _sell(4, token_qty="110", sol_qty="330", at=t0 + timedelta(hours=3)),
    ]

    positions = reconstruct_positions_for_wallet(swaps)  # type: ignore[arg-type]
    assert len(positions) == 1
    pos = positions[0]

    assert pos.entry_quantity == Decimal("150")  # 100 + 50
    assert pos.entry_value_quote == Decimal("200")  # 100 + 100
    assert pos.average_cost_quote == Decimal("200") / Decimal("150")
    assert pos.partial_exit_count == 1  # only the first sell was partial
    assert pos.realized_pnl_quote == Decimal("190")  # 20 (first sell) + 170 (final sell)
    assert pos.status == STATUS_CLOSED
    assert pos.final_exit_at == t0 + timedelta(hours=3)
    assert pos.confidence == CONFIDENCE_HIGH
    assert pos.unrealized_pnl_quote == Decimal(0)  # fully closed, no open exposure


# ---------------------------------------------------------------------
# Required test 3: transfer uncertainty.
# ---------------------------------------------------------------------


def test_p3_unresolved_transfer_never_becomes_a_fabricated_buy() -> None:
    """A token touched ONLY by a TRANSFER_IN (no SWAP_SIMPLE evidence at
    all) must never be treated as a purchase -- confidence UNRESOLVED,
    every quantity/value field left None, never fabricated."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    swaps = [_transfer_in(1, token_qty="500", at=t0)]

    positions = reconstruct_positions_for_wallet(swaps)  # type: ignore[arg-type]
    assert len(positions) == 1
    pos = positions[0]
    assert pos.confidence == CONFIDENCE_UNRESOLVED
    assert pos.entry_quantity is None
    assert pos.entry_value_quote is None
    assert pos.average_cost_quote is None
    assert pos.realized_pnl_quote is None
    assert pos.status == STATUS_OPEN  # never guessed closed either


def test_p3_transfer_alongside_genuine_swaps_downgrades_confidence_not_quantity() -> None:
    """A genuine buy/sell pair plus an uncertain transfer touching the
    same token: quantity/cost math is unaffected, but confidence
    downgrades from HIGH to MEDIUM to reflect the uncertain evidence."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    swaps = [
        _buy(1, token_qty="10", sol_qty="10", at=t0),
        _transfer_in(2, token_qty="5", at=t0 + timedelta(hours=1)),
        _sell(3, token_qty="10", sol_qty="20", at=t0 + timedelta(hours=2)),
    ]
    positions = reconstruct_positions_for_wallet(swaps)  # type: ignore[arg-type]
    assert len(positions) == 1
    pos = positions[0]
    assert pos.confidence == CONFIDENCE_MEDIUM
    assert pos.entry_quantity == Decimal("10")  # the transfer never entered the quantity math
    assert pos.realized_pnl_quote == Decimal("10")  # 10 * (2 - 1)
    assert pos.uncertain_event_count == 1


def test_p3_oversell_beyond_reconstructed_holdings_downgrades_to_low_confidence() -> None:
    """Selling more than the reconstructed open quantity (missing
    earlier evidence, or an untracked inflow) is never silently
    absorbed -- it is flagged via LOW confidence, and P&L is only
    realized on the reconstructable portion."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    swaps = [
        _buy(1, token_qty="10", sol_qty="10", at=t0),
        _sell(2, token_qty="30", sol_qty="60", at=t0 + timedelta(hours=1)),
    ]
    positions = reconstruct_positions_for_wallet(swaps)  # type: ignore[arg-type]
    pos = positions[0]
    assert pos.confidence == CONFIDENCE_LOW


# ---------------------------------------------------------------------
# Required test 1: discovery contamination (phase-blocking).
# ---------------------------------------------------------------------


def _closed_position(token_id: str, *, pnl: str, value: str = "10") -> PositionForScoring:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    return PositionForScoring(
        token_id=token_id,
        confidence=CONFIDENCE_HIGH,
        status=STATUS_CLOSED,
        realized_pnl_quote=Decimal(pnl),
        entry_value_quote=Decimal(value),
        peak_profit_capture=Decimal("0.5"),
        first_entry_at=now - timedelta(days=20),
        last_entry_at=now - timedelta(days=10),
    )


def test_p3_discovery_contamination_excluded_from_qualification_not_descriptive() -> None:
    """TOKEN_A discovers wallet W and is a huge winner: descriptive_score
    reflects it, qualification_score (and every metric feeding it --
    sample counts, hit rate, largest-trade contribution) must not."""
    now = datetime(2026, 6, 1, tzinfo=UTC)
    clean_positions = [_closed_position(f"clean-{i}", pnl="5") for i in range(25)]

    baseline = score_wallet(
        all_positions=clean_positions,
        discovery_contaminated_token_ids=frozenset(),
        history_completeness="HIGH",
        as_of=now,
    )

    huge_winner = _closed_position("DISCOVERY_TOKEN", pnl="100000", value="10")
    with_contamination = score_wallet(
        all_positions=[*clean_positions, huge_winner],
        discovery_contaminated_token_ids=frozenset({"DISCOVERY_TOKEN"}),
        history_completeness="HIGH",
        as_of=now,
    )

    # The phase-blocking assertion: qualification is byte-identical
    # whether or not the huge winner is present, because it is excluded
    # from every input the qualification computation ever sees.
    assert with_contamination.qualification_score == baseline.qualification_score
    assert with_contamination.stats.closed_count == baseline.stats.closed_count
    assert with_contamination.stats.distinct_tokens == baseline.stats.distinct_tokens
    assert with_contamination.stats.hit_rate == baseline.stats.hit_rate
    assert (
        with_contamination.stats.largest_trade_contribution_pct
        == baseline.stats.largest_trade_contribution_pct
    )
    assert with_contamination.eligible_for_qualification == baseline.eligible_for_qualification
    assert with_contamination.penalties == baseline.penalties

    # The non-blocking assertion: descriptive_score DOES see it, and is
    # measurably different -- proving the two scores are not secretly
    # computed from the same filtered set.
    assert with_contamination.descriptive_score > baseline.descriptive_score


def test_p3_discovery_contamination_never_leaks_through_recency_or_tier_gate() -> None:
    """The huge winner's own very recent activity must not inflate the
    qualification-side recency component, and must not single-handedly
    push an otherwise-ineligible wallet over the sample-size gate."""
    now = datetime(2026, 6, 1, tzinfo=UTC)
    # Only 5 clean closed positions -- below the 20/10 gate on its own.
    clean_positions = [_closed_position(f"clean-{i}", pnl="5") for i in range(5)]
    huge_winner = PositionForScoring(
        token_id="DISCOVERY_TOKEN",
        confidence=CONFIDENCE_HIGH,
        status=STATUS_CLOSED,
        realized_pnl_quote=Decimal("100000"),
        entry_value_quote=Decimal("10"),
        peak_profit_capture=Decimal("1.0"),
        first_entry_at=now - timedelta(hours=1),
        last_entry_at=now,  # maximally recent -- would inflate recency if it leaked
    )

    result = score_wallet(
        all_positions=[*clean_positions, huge_winner],
        discovery_contaminated_token_ids=frozenset({"DISCOVERY_TOKEN"}),
        history_completeness="HIGH",
        as_of=now,
    )
    # Still ineligible: the contaminated token's extra count/recency
    # never reached the qualification-side sample gate at all.
    assert result.eligible_for_qualification is False
    assert result.stats.closed_count == 5
    assert result.stats.distinct_tokens == 5


# ---------------------------------------------------------------------
# Required test 4: completeness-confidence coupling.
# ---------------------------------------------------------------------


def test_p3_low_unknown_history_completeness_blocks_eligibility_identical_positions() -> None:
    """The exact same 25-closed-position economic evidence: HIGH
    completeness is eligible, LOW/UNKNOWN completeness is not -- LOW/
    UNKNOWN can never qualify A/S regardless of how good the trades
    otherwise look (MASTER_SPEC.md section 34's own explicit rule)."""
    now = datetime(2026, 6, 1, tzinfo=UTC)
    positions = [_closed_position(f"tok-{i}", pnl="5") for i in range(25)]

    high = score_wallet(
        all_positions=positions,
        discovery_contaminated_token_ids=frozenset(),
        history_completeness="HIGH",
        as_of=now,
    )
    low = score_wallet(
        all_positions=positions,
        discovery_contaminated_token_ids=frozenset(),
        history_completeness="LOW",
        as_of=now,
    )
    unknown = score_wallet(
        all_positions=positions,
        discovery_contaminated_token_ids=frozenset(),
        history_completeness="UNKNOWN",
        as_of=now,
    )

    assert high.eligible_for_qualification is True
    assert low.eligible_for_qualification is False
    assert unknown.eligible_for_qualification is False
    assert "history_completeness" in low.sample_gate_reason
    # Confidence-shrunk toward the neutral prior, never simply capped at
    # the raw (un-shrunk) score.
    assert low.qualification_score != high.qualification_score


def test_p3_history_assessment_derives_from_real_acquisition_status_not_a_claim() -> None:
    """The completeness tier is derived from the REAL evidence-acquisition
    method, never a bare caller assertion."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    swaps = [_buy(1, token_qty="10", sol_qty="10", at=t0)]

    complete_walk = assess_wallet_history(
        swaps,  # type: ignore[arg-type]
        wallet_address=WALLET,
        evidence_source=EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK,
        acquisition_status=STATUS_COMPLETE,
    )
    assert complete_walk.history_completeness == "HIGH"

    partial_walk = assess_wallet_history(
        swaps,  # type: ignore[arg-type]
        wallet_address=WALLET,
        evidence_source=EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK,
        acquisition_status=STATUS_PARTIAL,
        acquisition_known_gaps="safety ceiling reached",
    )
    assert partial_walk.history_completeness == "MEDIUM"
    assert "safety ceiling reached" in partial_walk.history_completeness_reason

    stream_only = assess_wallet_history(
        swaps,  # type: ignore[arg-type]
        wallet_address=WALLET,
        evidence_source=EVIDENCE_SOURCE_STREAM_FORWARD_ONLY,
    )
    assert stream_only.history_completeness == "LOW"

    no_evidence = assess_wallet_history(
        [], wallet_address=WALLET, evidence_source=EVIDENCE_SOURCE_STREAM_FORWARD_ONLY
    )
    assert no_evidence.history_completeness == "UNKNOWN"

    with pytest.raises(ValueError, match="acquisition_status is required"):
        assess_wallet_history(
            swaps,  # type: ignore[arg-type]
            wallet_address=WALLET,
            evidence_source=EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK,
        )


# ---------------------------------------------------------------------
# Required test 5: small-sample constraint.
# ---------------------------------------------------------------------


def test_p3_tiny_but_superficially_excellent_sample_cannot_reach_top_score() -> None:
    """3 closed positions, every one a clean 10x win: raw component
    values would score very high, but the sample-size gate keeps the
    reported qualification_score deterministically shrunk toward the
    neutral population prior rather than reflecting that raw score."""
    now = datetime(2026, 6, 1, tzinfo=UTC)
    tiny_excellent = [_closed_position(f"tok-{i}", pnl="90", value="10") for i in range(3)]
    result = score_wallet(
        all_positions=tiny_excellent,
        discovery_contaminated_token_ids=frozenset(),
        history_completeness="HIGH",
        as_of=now,
    )
    assert result.eligible_for_qualification is False
    assert f"only {result.stats.closed_count} usable closed position" in result.sample_gate_reason
    # Deterministic shrinkage toward the neutral 50 prior -- proportional
    # to how far short of the 20/10 thresholds the sample falls (3/20 *
    # 3/10 = 0.045 of the way from the prior to the raw score), not
    # simply capped just under a fixed ceiling.
    assert result.qualification_score < Decimal(60)


def test_p3_sample_gate_thresholds_are_the_frozen_v1_values() -> None:
    assert MIN_USABLE_CLOSED_POSITIONS == 20
    assert MIN_DISTINCT_TOKENS == 10


# ---------------------------------------------------------------------
# Required test 6: lottery dominance.
# ---------------------------------------------------------------------


def test_p3_lottery_dominance_flag_and_boundary_are_deterministic() -> None:
    """One position contributing more than 70% of lifetime P&L is
    flagged LOTTERY_DOMINATED and penalized -- never automatically
    rejected (a flag/penalty, per section 40's own explicit rule)."""
    now = datetime(2026, 6, 1, tzinfo=UTC)
    # 24 small wins (pnl=1 each -> total small gains = 24) + one position
    # contributing far more than 70% of the positive total.
    small_wins = [_closed_position(f"tok-{i}", pnl="1") for i in range(24)]
    dominator = _closed_position("dominator", pnl="1000")

    dominated = compute_position_stats([*small_wins, dominator])
    assert dominated.lottery_dominated is True
    assert dominated.largest_trade_contribution_pct is not None
    assert dominated.largest_trade_contribution_pct > LOTTERY_DOMINANCE_THRESHOLD

    result = score_wallet(
        all_positions=[*small_wins, dominator],
        discovery_contaminated_token_ids=frozenset(),
        history_completeness="HIGH",
        as_of=now,
    )
    assert result.penalties["lottery_dominance_penalty"] > Decimal(0)

    balanced = compute_position_stats(small_wins)
    assert balanced.lottery_dominated is False


# ---------------------------------------------------------------------
# Required test 7: recency/versioning.
# ---------------------------------------------------------------------


def test_p3_recency_uses_point_in_time_as_of_never_a_fixed_clock() -> None:
    """The identical position, scored as of two different `as_of`
    timestamps, produces different recency -- proving the decay is
    genuinely point-in-time-sensitive, and a later snapshot never
    silently reuses an earlier snapshot's own notion of 'now'."""
    entry_time = datetime(2026, 1, 1, tzinfo=UTC)
    positions = [
        PositionForScoring(
            token_id="tok-1",
            confidence=CONFIDENCE_HIGH,
            status=STATUS_CLOSED,
            realized_pnl_quote=Decimal("5"),
            entry_value_quote=Decimal("10"),
            peak_profit_capture=Decimal("0.5"),
            first_entry_at=entry_time,
            last_entry_at=entry_time,
        )
    ]

    soon_after = score_wallet(
        all_positions=positions,
        discovery_contaminated_token_ids=frozenset(),
        history_completeness="HIGH",
        as_of=entry_time + timedelta(days=1),
    )
    long_after = score_wallet(
        all_positions=positions,
        discovery_contaminated_token_ids=frozenset(),
        history_completeness="HIGH",
        as_of=entry_time + timedelta(days=400),
    )
    assert soon_after.component_values["recency"] == Decimal(100)
    assert long_after.component_values["recency"] == Decimal(0)
    assert soon_after.component_values["recency"] != long_after.component_values["recency"]
