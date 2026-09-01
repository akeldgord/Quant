"""Phase 3 (WALLET RECONSTRUCTION + UNBIASED QUALIFICATION) pure-function
tests -- the DB-persistence halves of the same required scenarios live in
``tests/integration/test_phase3_wallet_qualification.py``. Covers the
original `argus-phase-3-001` required categories (updated for the
`argus-phase-3-remediation-001` API changes) plus the new P3-R1/P3-R2/
P3-R3/P3-R5/P3-R6 pure-function prospective acceptance tests. Per both
instructions' own "cover the financial/data invariants deeply, not dozens
of superficial tests" guidance.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from argus.tokens.historical_acquisition import STATUS_COMPLETE, STATUS_PARTIAL
from argus.wallets.history_reconstruction import (
    EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK,
    EVIDENCE_SOURCE_STREAM_FORWARD_ONLY,
    AcquiredEvidenceRecord,
    AcquisitionManifest,
    TokenAccountCoverage,
    WalkStats,
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
TOKEN_MINT = "TOKENmint1111111111111111111111111111111"


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
    swap_id: str = "swap-0"


def _buy(slot: int, *, token_qty: str, sol_qty: str, at: datetime, swap_id: str = "") -> _FakeSwap:
    return _FakeSwap(
        classification="SWAP_SIMPLE",
        input_mint=SOL,
        input_amount_ui=Decimal(sol_qty),
        output_mint=TOKEN_MINT,
        output_amount_ui=Decimal(token_qty),
        slot=slot,
        block_time=at,
        swap_id=swap_id or f"buy-{slot}",
    )


def _sell(slot: int, *, token_qty: str, sol_qty: str, at: datetime, swap_id: str = "") -> _FakeSwap:
    return _FakeSwap(
        classification="SWAP_SIMPLE",
        input_mint=TOKEN_MINT,
        input_amount_ui=Decimal(token_qty),
        output_mint=SOL,
        output_amount_ui=Decimal(sol_qty),
        slot=slot,
        block_time=at,
        swap_id=swap_id or f"sell-{slot}",
    )


def _buy_usdc(
    slot: int, *, token_qty: str, usdc_qty: str, at: datetime, swap_id: str = ""
) -> _FakeSwap:
    return _FakeSwap(
        classification="SWAP_SIMPLE",
        input_mint=USDC,
        input_amount_ui=Decimal(usdc_qty),
        output_mint=TOKEN_MINT,
        output_amount_ui=Decimal(token_qty),
        slot=slot,
        block_time=at,
        swap_id=swap_id or f"buy-usdc-{slot}",
    )


def _transfer_in(slot: int, *, token_qty: str, at: datetime) -> _FakeSwap:
    return _FakeSwap(
        classification="TRANSFER_IN",
        input_mint=None,
        input_amount_ui=None,
        output_mint=TOKEN_MINT,
        output_amount_ui=Decimal(token_qty),
        slot=slot,
        block_time=at,
        swap_id=f"transfer-{slot}",
    )


_FAR_FUTURE_AS_OF = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=3650)


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

    positions = reconstruct_positions_for_wallet(swaps, as_of=_FAR_FUTURE_AS_OF)  # type: ignore[arg-type]
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
    assert pos.round_trip_index == 0


# ---------------------------------------------------------------------
# Required test 3: transfer uncertainty.
# ---------------------------------------------------------------------


def test_p3_unresolved_transfer_never_becomes_a_fabricated_buy() -> None:
    """A token touched ONLY by a TRANSFER_IN (no SWAP_SIMPLE evidence at
    all) must never be treated as a purchase -- confidence UNRESOLVED,
    every quantity/value field left None, never fabricated."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    swaps = [_transfer_in(1, token_qty="500", at=t0)]

    positions = reconstruct_positions_for_wallet(swaps, as_of=_FAR_FUTURE_AS_OF)  # type: ignore[arg-type]
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
    positions = reconstruct_positions_for_wallet(swaps, as_of=_FAR_FUTURE_AS_OF)  # type: ignore[arg-type]
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
    positions = reconstruct_positions_for_wallet(swaps, as_of=_FAR_FUTURE_AS_OF)  # type: ignore[arg-type]
    pos = positions[0]
    assert pos.confidence == CONFIDENCE_LOW


# ---------------------------------------------------------------------
# Required test 1: discovery contamination (phase-blocking).
# ---------------------------------------------------------------------


def _closed_position(
    token_id: str, *, pnl: str, value: str = "10", final_exit_at: datetime | None = None
) -> PositionForScoring:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    exit_at = final_exit_at if final_exit_at is not None else now - timedelta(days=10)
    return PositionForScoring(
        token_id=token_id,
        confidence=CONFIDENCE_HIGH,
        status=STATUS_CLOSED,
        realized_pnl_quote=Decimal(pnl),
        entry_value_quote=Decimal(value),
        peak_profit_capture=Decimal("0.5"),
        first_entry_at=now - timedelta(days=20),
        last_entry_at=now - timedelta(days=10),
        final_exit_at=exit_at,
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
        final_exit_at=now,
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


# ---------------------------------------------------------------------
# P3-R2: history completeness is evidence-bound, never caller-asserted.
# ---------------------------------------------------------------------


def _walk(status: str, *, known_gaps: str | None = None) -> WalkStats:
    return WalkStats(
        status=status,
        known_gaps=known_gaps,
        pages_fetched=1,
        signatures_seen=1,
        transaction_fetch_failures=0,
        expected_oldest_slot=None,
        boundary_satisfied=None,
    )


def _tac(*, pubkey: str, mint: str, owner: str, status: str) -> TokenAccountCoverage:
    return TokenAccountCoverage(
        pubkey=pubkey, mint=mint, owner=owner, status=status, walk=_walk(status)
    )


def _manifest(
    *,
    wallet_walk_status: str,
    token_accounts_enumerated: bool = False,
    associated_token_accounts: tuple[TokenAccountCoverage, ...] = (),
    acquired_evidence: tuple[AcquiredEvidenceRecord, ...] = (),
    known_gaps: str | None = None,
) -> AcquisitionManifest:
    return AcquisitionManifest(
        run_id=uuid.uuid4(),
        wallet_id=uuid.uuid4(),
        wallet_address=WALLET,
        observation_cutoff=datetime(2026, 1, 1, tzinfo=UTC),
        algorithm_version="test-acquisition-v1",
        wallet_walk_status=wallet_walk_status,
        wallet_walk=_walk(wallet_walk_status, known_gaps=known_gaps),
        token_accounts_enumerated=token_accounts_enumerated,
        associated_token_accounts=associated_token_accounts,
        acquired_evidence=acquired_evidence,
        provider_set="test-fake-provider",
        known_gaps=known_gaps,
        evidence_reference="test-evidence",
    )


def test_p3_history_assessment_derives_from_real_acquisition_manifest_not_a_claim() -> None:
    """The completeness tier is derived from a REAL, structured
    AcquisitionManifest, never a bare caller-typed status string (P3-R2:
    the ``--acquisition-status COMPLETE`` free-text path no longer
    exists in this function's signature at all)."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    swaps = [_buy(1, token_qty="10", sol_qty="10", at=t0)]

    # A complete wallet-address walk with NO token-account enumeration
    # at all: required test 3, "a complete wallet-address walk with
    # missing token-account enumeration is not HIGH."
    wallet_only_complete = assess_wallet_history(
        swaps,  # type: ignore[arg-type]
        wallet_address=WALLET,
        evidence_source=EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK,
        acquisition_manifest=_manifest(wallet_walk_status=STATUS_COMPLETE),
    )
    assert wallet_only_complete.history_completeness == "MEDIUM"

    # A complete wallet walk PLUS complete enumeration and complete
    # histories for every known associated token account: required test
    # 3's HIGH case.
    fully_covered = assess_wallet_history(
        swaps,  # type: ignore[arg-type]
        wallet_address=WALLET,
        evidence_source=EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK,
        acquisition_manifest=_manifest(
            wallet_walk_status=STATUS_COMPLETE,
            token_accounts_enumerated=True,
            associated_token_accounts=(
                _tac(pubkey="pubkey-acct-1", mint="acct-1", owner=WALLET, status=STATUS_COMPLETE),
                _tac(pubkey="pubkey-acct-2", mint="acct-2", owner=WALLET, status=STATUS_COMPLETE),
            ),
        ),
    )
    assert fully_covered.history_completeness == "HIGH"

    # One partial/failed account walk lowers completeness with the exact
    # gap recorded: required test 3's 4th assertion.
    one_incomplete_account = assess_wallet_history(
        swaps,  # type: ignore[arg-type]
        wallet_address=WALLET,
        evidence_source=EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK,
        acquisition_manifest=_manifest(
            wallet_walk_status=STATUS_COMPLETE,
            token_accounts_enumerated=True,
            associated_token_accounts=(
                _tac(pubkey="pubkey-acct-1", mint="acct-1", owner=WALLET, status=STATUS_COMPLETE),
                _tac(pubkey="pubkey-acct-2", mint="acct-2", owner=WALLET, status=STATUS_PARTIAL),
            ),
        ),
    )
    assert one_incomplete_account.history_completeness == "MEDIUM"
    assert "acct-2" in one_incomplete_account.history_completeness_reason

    partial_walk = assess_wallet_history(
        swaps,  # type: ignore[arg-type]
        wallet_address=WALLET,
        evidence_source=EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK,
        acquisition_manifest=_manifest(
            wallet_walk_status=STATUS_PARTIAL, known_gaps="safety ceiling reached"
        ),
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

    # The exact P3-R2 defect: no manifest at all under LIVE_ACQUISITION_
    # WALK must fail closed -- there is no way to pass a bare status
    # string to manufacture completeness any more.
    with pytest.raises(ValueError, match="acquisition_manifest is required"):
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
# Required test 6 / P3-R5: lottery dominance, corrected metrics.
# ---------------------------------------------------------------------


def test_p3_lottery_dominance_flag_and_boundary_are_deterministic() -> None:
    """One position contributing more than 70% of NET lifetime P&L is
    flagged LOTTERY_DOMINATED and penalized -- never automatically
    rejected (a flag/penalty, per section 40's own explicit rule)."""
    now = datetime(2026, 6, 1, tzinfo=UTC)
    # 24 small wins (pnl=1 each -> total small gains = 24) + one position
    # contributing far more than 70% of net lifetime P&L.
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


def test_p3_lottery_dominance_uses_net_pnl_not_gross_gains_with_boundary() -> None:
    """P3-R5: a +100 winner against a -90 loser nets only +10 -- the
    ratio is 100/10 = 10.0 (1000%), not 100/100 = 1.0 against gross
    gains alone. The exact 0.70 boundary is not flagged; just above it
    is."""
    winner = _closed_position("winner", pnl="100", value="10")
    loser = _closed_position("loser", pnl="-90", value="10")
    stats = compute_position_stats([winner, loser])
    assert stats.total_realized_pnl == Decimal("10")
    assert stats.largest_trade_contribution_pct == Decimal("100") / Decimal("10")
    assert stats.lottery_dominated is True

    # Net lifetime P&L <= 0: contribution is null/not-applicable, never
    # a fabricated fraction of a non-positive total.
    two_losers = [
        _closed_position("l1", pnl="-10", value="10"),
        _closed_position("l2", pnl="-5", value="10"),
    ]
    non_positive_net = compute_position_stats(two_losers)
    assert non_positive_net.largest_trade_contribution_pct is None
    assert non_positive_net.lottery_dominated is False

    # Exact boundary: a largest-trade-contribution ratio of exactly
    # 0.70 net is not flagged; a hair above 0.70 is.
    at_boundary = [
        _closed_position("big", pnl="70", value="10"),
        _closed_position("rest", pnl="30", value="10"),
    ]
    at = compute_position_stats(at_boundary)
    assert at.largest_trade_contribution_pct == Decimal("0.70")
    assert at.lottery_dominated is False

    above_boundary = [
        _closed_position("big", pnl="71", value="10"),
        _closed_position("rest", pnl="29", value="10"),
    ]
    above = compute_position_stats(above_boundary)
    assert above.largest_trade_contribution_pct > Decimal("0.70")
    assert above.lottery_dominated is True


def test_p3_drawdown_uses_final_exit_at_order_not_last_entry_at() -> None:
    """P3-R5: the realization-order equity curve is ordered by
    ``final_exit_at`` (when an outcome was actually realized), never
    ``last_entry_at`` (an entry-side timestamp) -- a big loss that
    exits LAST must actually appear last in the drawdown curve even if
    its entry-side timestamp sorts earlier."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    # entered first (so last_entry_at sorts it first) but exits LAST.
    late_exit_loss = PositionForScoring(
        token_id="late-exit",
        confidence=CONFIDENCE_HIGH,
        status=STATUS_CLOSED,
        realized_pnl_quote=Decimal("-50"),
        entry_value_quote=Decimal("10"),
        peak_profit_capture=Decimal("0"),
        first_entry_at=base,
        last_entry_at=base,  # earliest entry
        final_exit_at=base + timedelta(days=10),  # latest exit
    )
    early_exit_win = PositionForScoring(
        token_id="early-exit",
        confidence=CONFIDENCE_HIGH,
        status=STATUS_CLOSED,
        realized_pnl_quote=Decimal("100"),
        entry_value_quote=Decimal("10"),
        peak_profit_capture=Decimal("1"),
        first_entry_at=base + timedelta(days=5),
        last_entry_at=base + timedelta(days=5),  # later entry
        final_exit_at=base + timedelta(days=6),  # earlier exit
    )
    stats = compute_position_stats([late_exit_loss, early_exit_win])
    # Exit order: win (+100, peak=100, dd=0) then loss (-50, running=50,
    # dd=(100-50)/100=0.5). If last_entry_at were used instead, the loss
    # would be ordered first (peak stays 0, no drawdown at all).
    assert stats.max_drawdown == Decimal("0.5")


def test_p3_distinct_tokens_counts_only_closed_usable_outcomes() -> None:
    """P3-R5: an open position (however many exist) contributes no
    usable outcome and must never inflate distinct-token eligibility."""
    open_position = PositionForScoring(
        token_id="open-tok",
        confidence=CONFIDENCE_HIGH,
        status=STATUS_OPEN,
        realized_pnl_quote=None,
        entry_value_quote=Decimal("10"),
        peak_profit_capture=None,
        first_entry_at=datetime(2026, 1, 1, tzinfo=UTC),
        last_entry_at=datetime(2026, 1, 1, tzinfo=UTC),
        final_exit_at=None,
    )
    closed_position = _closed_position("closed-tok", pnl="5")
    stats = compute_position_stats([open_position, closed_position])
    assert stats.distinct_tokens == 1


# ---------------------------------------------------------------------
# Required test 7 / P3-R6: recency/versioning, missing-evidence rule.
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
            final_exit_at=entry_time,
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


def test_p3_missing_forward_information_counts_toward_missing_evidence_and_caps_confidence() -> (
    None
):
    """P3-R6: forward_information's known absence counts toward the
    missing-evidence tally like every other component -- HIGH confidence
    is therefore structurally unreachable in Phase 3 (an honest,
    documented consequence, not excluded from the count as the
    pre-remediation code did). It still contributes its neutral-prior
    weight to the score itself -- never redistributed."""
    now = datetime(2026, 6, 1, tzinfo=UTC)
    positions = [_closed_position(f"tok-{i}", pnl="5") for i in range(25)]
    result = score_wallet(
        all_positions=positions,
        discovery_contaminated_token_ids=frozenset(),
        history_completeness="HIGH",
        as_of=now,
    )
    assert result.component_values["forward_information"] is None
    assert result.confidence != "HIGH"


# ---------------------------------------------------------------------
# P3-R1: point-in-time firewall -- future-dated evidence fails closed.
# ---------------------------------------------------------------------


def test_p3_future_dated_swap_excluded_from_reconstruction_evidence_preserved() -> None:
    """A swap whose own chain timestamp is later than ``as_of`` (a
    malformed/future-dated economic timestamp) is excluded entirely from
    reconstruction -- it contributes no recency credit and cannot enter
    qualification -- while the underlying evidence itself is never lost
    to the caller (the swap object is simply not selected, never
    mutated or deleted)."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    as_of = t0 + timedelta(days=1)
    future = t0 + timedelta(days=400)  # far beyond as_of

    buy_swap = _buy(1, token_qty="100", sol_qty="100", at=t0)
    future_sell = _sell(2, token_qty="100", sol_qty="500", at=future)

    positions = reconstruct_positions_for_wallet([buy_swap, future_sell], as_of=as_of)  # type: ignore[arg-type]
    assert len(positions) == 1
    pos = positions[0]
    # The future sell never executed from this snapshot's perspective --
    # the position remains OPEN with only the real, past buy counted.
    assert pos.status == STATUS_OPEN
    assert pos.entry_quantity == Decimal("100")
    assert pos.last_entry_at == t0
    assert pos.realized_pnl_quote == Decimal(0)

    # Both raw swaps are still there for the caller to inspect --
    # nothing was deleted or mutated by reconstruction.
    assert buy_swap.swap_id == "buy-1"
    assert future_sell.swap_id == "sell-2"


def test_p3_future_dated_only_evidence_excludes_the_token_entirely() -> None:
    """A token touched ONLY by future-dated evidence produces no
    position at all as of an earlier as_of -- it genuinely was not yet
    known to exist."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    as_of = t0 - timedelta(days=1)  # before the swap even happened
    swaps = [_buy(1, token_qty="100", sol_qty="100", at=t0)]
    positions = reconstruct_positions_for_wallet(swaps, as_of=as_of)  # type: ignore[arg-type]
    assert positions == []


# ---------------------------------------------------------------------
# P3-R3: round-trip-safe, quote-safe weighted-average ledger.
# ---------------------------------------------------------------------


def test_p3_full_close_then_reopen_produces_two_independent_round_trips() -> None:
    """Buy, full close, reopen, full close -- two separately identified
    closed round trips with independently hand-calculated PnL and
    holding times, never one merged lifetime aggregate."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    swaps = [
        _buy(1, token_qty="100", sol_qty="100", at=t0),
        _sell(2, token_qty="100", sol_qty="150", at=t0 + timedelta(hours=1)),  # closes: +50
        _buy(3, token_qty="50", sol_qty="60", at=t0 + timedelta(hours=2)),
        _sell(4, token_qty="50", sol_qty="40", at=t0 + timedelta(hours=3)),  # closes: -20
    ]
    positions = reconstruct_positions_for_wallet(swaps, as_of=_FAR_FUTURE_AS_OF)  # type: ignore[arg-type]
    assert len(positions) == 2
    first, second = positions
    assert first.round_trip_index == 0
    assert first.realized_pnl_quote == Decimal("50")
    assert first.entry_quantity == Decimal("100")
    assert first.status == STATUS_CLOSED
    assert first.holding_duration_seconds == 3600  # 1 hour

    assert second.round_trip_index == 1
    assert second.realized_pnl_quote == Decimal("-20")
    assert second.entry_quantity == Decimal("50")
    assert second.status == STATUS_CLOSED
    assert second.holding_duration_seconds == 3600  # 1 hour

    # Disjoint raw-evidence references -- never conflated.
    assert set(first.contributing_swap_ids) == {"buy-1", "sell-2"}
    assert set(second.contributing_swap_ids) == {"buy-3", "sell-4"}
    assert first.input_manifest_digest != second.input_manifest_digest


def test_p3_partial_sell_then_later_buy_uses_current_open_inventory_basis() -> None:
    """A still-open round trip's ``average_cost_quote`` is the CURRENT
    weighted-average cost of the remaining open inventory after a
    partial sell and a later buy -- never a lifetime-flat average
    across all buys."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    swaps = [
        _buy(1, token_qty="100", sol_qty="100", at=t0),  # cost basis 100, qty 100
        _sell(2, token_qty="40", sol_qty="80", at=t0 + timedelta(hours=1)),
        # open_qty 60, open_cost_basis 60 (100 - 40*1.0)
        _buy(3, token_qty="50", sol_qty="150", at=t0 + timedelta(hours=2)),
        # open_qty 110, open_cost_basis 210
    ]
    positions = reconstruct_positions_for_wallet(swaps, as_of=_FAR_FUTURE_AS_OF)  # type: ignore[arg-type]
    assert len(positions) == 1
    pos = positions[0]
    assert pos.status == STATUS_OPEN
    assert pos.average_cost_quote == Decimal("210") / Decimal("110")
    assert pos.unrealized_pnl_quote is None  # never fabricated from a stale fill price


def test_p3_mixed_quote_asset_never_summed_excluded_as_unresolved() -> None:
    """Opening in SOL then a later leg denominated in USDC is never
    summed into the same quantity/cost math -- excluded, preserved as a
    raw reference, and the round trip's confidence is degraded to LOW
    (excluded from qualification via the existing HIGH/MEDIUM filter),
    never a fabricated conversion."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    swaps = [
        _buy(1, token_qty="100", sol_qty="100", at=t0),
        _buy_usdc(2, token_qty="50", usdc_qty="75", at=t0 + timedelta(hours=1)),
    ]
    positions = reconstruct_positions_for_wallet(swaps, as_of=_FAR_FUTURE_AS_OF)  # type: ignore[arg-type]
    assert len(positions) == 1
    pos = positions[0]
    assert pos.mixed_quote_leg_count == 1
    assert pos.confidence == CONFIDENCE_LOW
    # Only the SOL-denominated buy entered quantity/cost math.
    assert pos.entry_quantity == Decimal("100")
    assert pos.quote_asset_mint == SOL
    # The USDC leg's raw reference is preserved, not lost.
    assert "buy-usdc-2" in pos.contributing_swap_ids


def test_p3_input_permutations_and_same_slot_ties_are_byte_identical() -> None:
    """Input-order permutations of the same underlying evidence, and
    same-slot ties, must yield byte-identical reconstructed output."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    buy_a = _buy(1, token_qty="100", sol_qty="100", at=t0, swap_id="a")
    sell_a = _sell(2, token_qty="100", sol_qty="200", at=t0 + timedelta(hours=1), swap_id="b")

    forward = reconstruct_positions_for_wallet([buy_a, sell_a], as_of=_FAR_FUTURE_AS_OF)  # type: ignore[arg-type]
    reversed_order = reconstruct_positions_for_wallet([sell_a, buy_a], as_of=_FAR_FUTURE_AS_OF)  # type: ignore[arg-type]
    assert forward == reversed_order


def test_p3_decimal_boundary_values_prove_no_float_conversion() -> None:
    """A quantity with far more precision than any binary float can
    represent exactly round-trips through reconstruction unchanged."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    precise_qty = "0.123456789012345678"
    swaps = [_buy(1, token_qty=precise_qty, sol_qty="1", at=t0)]
    positions = reconstruct_positions_for_wallet(swaps, as_of=_FAR_FUTURE_AS_OF)  # type: ignore[arg-type]
    assert positions[0].entry_quantity == Decimal(precise_qty)
    assert isinstance(positions[0].entry_quantity, Decimal)


# ---------------------------------------------------------------------
# P3-R3 remediation round 2 (`argus-phase-3-remediation-002`): a total,
# fully immutable event-ordering tie-break, and quote-unit-safe
# cross-round-trip scoring aggregates.
# ---------------------------------------------------------------------


def test_p3_exact_same_slot_type_mints_raw_amounts_tie_break_by_immutable_swap_id() -> None:
    """Two genuinely distinct buys sharing the exact same (slot,
    classification, input_mint, output_mint, raw amounts) sort-key tuple
    -- a real possibility the prior test (slots 1 and 2, never colliding)
    never exercised -- must still order deterministically by their own
    immutable swap_id, regardless of input list order. Before the P3-R3
    remediation-002 fix, the original input list's own order silently
    decided ties, so first_entry_at would differ between permutations of
    the identical evidence set."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    later = t0 + timedelta(hours=1)
    # Both legs: slot=1, SWAP_SIMPLE, SOL->TOKEN_MINT, and (since this
    # fixture never sets input_amount_raw/output_amount_raw) both raw
    # amounts default to the same 0 -- genuinely identical on every
    # pre-swap_id sort-key component despite different UI quantities and
    # different block_times.
    buy_high_id = _buy(1, token_qty="50", sol_qty="50", at=t0, swap_id="zzz-higher")
    buy_low_id = _buy(1, token_qty="30", sol_qty="30", at=later, swap_id="aaa-lower")

    forward = reconstruct_positions_for_wallet(  # type: ignore[arg-type]
        [buy_high_id, buy_low_id], as_of=_FAR_FUTURE_AS_OF
    )
    reversed_order = reconstruct_positions_for_wallet(  # type: ignore[arg-type]
        [buy_low_id, buy_high_id], as_of=_FAR_FUTURE_AS_OF
    )
    assert forward == reversed_order
    # The lower swap_id ("aaa-lower", the `later`-timed leg) is processed
    # first regardless of input order -- so first_entry_at is always
    # `later`, never t0, in both permutations.
    assert forward[0].first_entry_at == later
    assert forward[0].entry_quantity == Decimal("80")  # 30 + 50, order-independent total


def test_p3_mixed_currency_closed_trips_never_sum_incompatible_units() -> None:
    """Two independently closed round trips -- one realizing +1 SOL, one
    realizing +1000 USDC -- must never be summed into a single cash PnL
    of 1001. Covers both a same-token-reopened case and a different-token
    case: total_realized_pnl/profit_factor/largest_trade_contribution_pct/
    max_drawdown all become explicitly unavailable (None), never a
    fabricated cross-currency total. lottery_dominated is False (never
    determinable as True without a real ratio)."""
    now = datetime(2026, 6, 1, tzinfo=UTC)
    sol_trip = PositionForScoring(
        token_id="token-a",
        confidence=CONFIDENCE_HIGH,
        status=STATUS_CLOSED,
        realized_pnl_quote=Decimal(1),
        entry_value_quote=Decimal(10),
        peak_profit_capture=Decimal("0.5"),
        first_entry_at=now - timedelta(days=20),
        last_entry_at=now - timedelta(days=10),
        final_exit_at=now - timedelta(days=10),
        quote_asset_mint="SOL",
        round_trip_index=0,
    )
    usdc_trip = PositionForScoring(
        token_id="token-b",
        confidence=CONFIDENCE_HIGH,
        status=STATUS_CLOSED,
        realized_pnl_quote=Decimal(1000),
        entry_value_quote=Decimal(10),
        peak_profit_capture=Decimal("0.5"),
        first_entry_at=now - timedelta(days=15),
        last_entry_at=now - timedelta(days=5),
        final_exit_at=now - timedelta(days=5),
        quote_asset_mint=USDC,
        round_trip_index=0,
    )
    stats = compute_position_stats([sol_trip, usdc_trip])
    assert stats.closed_count == 2
    assert stats.total_realized_pnl is None
    assert stats.profit_factor is None
    assert stats.largest_trade_contribution_pct is None
    assert stats.top_three_trade_contribution_pct is None
    assert stats.max_drawdown is None
    assert stats.lottery_dominated is False
    # Per-position dimensionless returns remain fully computable --
    # currency-agnostic ratios, never a cross-currency sum.
    assert stats.median_return is not None

    # Same-token-reopened case: two round trips of the SAME token_id, one
    # opened/closed in SOL, later reopened and closed in USDC.
    sol_reopen = dataclasses.replace(sol_trip, token_id="token-c", round_trip_index=0)
    usdc_reopen = dataclasses.replace(usdc_trip, token_id="token-c", round_trip_index=1)
    reopened_stats = compute_position_stats([sol_reopen, usdc_reopen])
    assert reopened_stats.total_realized_pnl is None
    assert reopened_stats.max_drawdown is None
    # Still exactly one distinct token -- two round trips of it.
    assert reopened_stats.distinct_tokens == 1


def test_p3_none_and_aware_exit_times_never_crash_drawdown_reported_unavailable() -> None:
    """A closed position with a genuinely unknown final_exit_at mixed
    with ordinary timezone-aware ones must never raise a naive/aware
    datetime TypeError -- the whole drawdown metric is reported
    unavailable (None) rather than fabricating a sentinel ordering, while
    order-independent metrics (returns, profit_factor within one
    currency) are entirely unaffected."""
    now = datetime(2026, 6, 1, tzinfo=UTC)
    known = PositionForScoring(
        token_id="token-a",
        confidence=CONFIDENCE_HIGH,
        status=STATUS_CLOSED,
        realized_pnl_quote=Decimal(5),
        entry_value_quote=Decimal(10),
        peak_profit_capture=Decimal("0.5"),
        first_entry_at=now - timedelta(days=20),
        last_entry_at=now - timedelta(days=10),
        final_exit_at=now - timedelta(days=10),
        quote_asset_mint="SOL",
    )
    unknown_exit = PositionForScoring(
        token_id="token-b",
        confidence=CONFIDENCE_HIGH,
        status=STATUS_CLOSED,
        realized_pnl_quote=Decimal(3),
        entry_value_quote=Decimal(10),
        peak_profit_capture=Decimal("0.5"),
        first_entry_at=now - timedelta(days=15),
        last_entry_at=now - timedelta(days=5),
        final_exit_at=None,  # genuinely unknown, never fabricated
        quote_asset_mint="SOL",
    )
    # Must not raise -- this is the exact scenario that previously
    # compared a naive datetime.min sentinel against real aware datetimes.
    stats = compute_position_stats([known, unknown_exit])
    assert stats.max_drawdown is None
    assert stats.closed_count == 2
    assert stats.total_realized_pnl == Decimal(8)  # order-independent, unaffected
    assert stats.profit_factor is None  # no losses at all, gross_loss == 0


def test_p3_drawdown_tie_break_uses_immutable_round_trip_identity_not_just_token_id() -> None:
    """Distinct round trips sharing BOTH token_id and final_exit_at (a
    real possibility once P3-R3 allows more than one round trip per
    token) must produce an identical drawdown across input-order
    permutations using their own immutable round_trip_index, not merely
    token_id (which cannot disambiguate them at all) -- compared against
    a fixed, hand-calculated expected order, not a value the
    implementation itself generated."""
    now = datetime(2026, 6, 1, tzinfo=UTC)
    exit_at = now - timedelta(days=10)
    # Two round trips of the SAME token, same exit instant: a loss then a
    # gain, identified only by round_trip_index (0 then 1).
    loss_first = PositionForScoring(
        token_id="token-a",
        confidence=CONFIDENCE_HIGH,
        status=STATUS_CLOSED,
        realized_pnl_quote=Decimal(-40),
        entry_value_quote=Decimal(100),
        peak_profit_capture=Decimal("0"),
        first_entry_at=now - timedelta(days=30),
        last_entry_at=now - timedelta(days=20),
        final_exit_at=exit_at,
        quote_asset_mint="SOL",
        round_trip_index=0,
    )
    gain_second = PositionForScoring(
        token_id="token-a",
        confidence=CONFIDENCE_HIGH,
        status=STATUS_CLOSED,
        realized_pnl_quote=Decimal(100),
        entry_value_quote=Decimal(100),
        peak_profit_capture=Decimal("1"),
        first_entry_at=now - timedelta(days=20),
        last_entry_at=now - timedelta(days=15),
        final_exit_at=exit_at,
        quote_asset_mint="SOL",
        round_trip_index=1,
    )
    # Hand-calculated expected order (loss then gain, by round_trip_index
    # 0 then 1): running -40 (peak 0, drawdown undefined since peak<=0),
    # then running +60 (peak 60, drawdown 0) -- max_dd = 0. This fixed
    # expectation is independent of the implementation's own output.
    forward = compute_position_stats([loss_first, gain_second])
    reversed_order = compute_position_stats([gain_second, loss_first])
    assert forward.max_drawdown == reversed_order.max_drawdown == Decimal(0)
