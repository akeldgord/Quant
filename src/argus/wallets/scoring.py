"""Wallet feature fingerprint + qualification/descriptive score v1
(MASTER_SPEC.md section 30 CRITICAL ANTI-SURVIVORSHIP RULE, section 37
WALLET FEATURE FINGERPRINT, section 38 WALLET QUALIFICATION SCORE v1,
section 39 QUALIFICATION SAMPLE REQUIREMENTS v1, section 40
LOTTERY-DOMINANCE PROTECTION, section 41 RECENCY AND ALPHA DECAY; Phase 3,
`argus-phase-3-001`).

**The discovery-contamination firewall is structural, not a filter
applied after the fact**: this module's public entry point,
:func:`score_wallet`, computes ``descriptive_score`` from every position
the caller passes it, and ``qualification_score`` from a SEPARATE call
over only the subset with ``token_id not in discovery_contaminated_
token_ids`` -- the huge-winner token that discovered this wallet simply
never enters the qualification computation's inputs at all, so it cannot
leak through any secondary aggregate (sample counts, recency windows,
largest-trade contribution, tier gates) by construction, not by a
post-hoc check. ``discovery_contaminated_token_ids`` must be derived from
real, persisted ``wallet_discovery_events.trigger_token_id`` provenance
by the caller (see ``argus.wallets.orchestration``) -- never a fixture
name or a hand-maintained list.

Every V1 formula here is deliberately simple and fully transparent
(matching this project's established "no black box, no ML" ethos already
set by ``argus.parsing.generic_parser``) -- the frozen section-38 WEIGHTS
are what must not be tuned in this phase; the component formulas
themselves are explicitly first-cut V1 priors "to be evaluated
prospectively" (section 38's own words), not claimed as optimal.

**A missing component is never redistributed** (section 38's own explicit
prohibition): an unavailable component (e.g. ``forward_information`` --
always unavailable in Phase 3, since it needs Phase 4 prospective data
that does not exist yet) contributes at a neutral prior value (50/100),
never excluded and never reweighted onto the other components. Missing
components instead lower the snapshot's own ``confidence`` field, an
explicit, documented, non-fabricated effect (section 38's own "document
the resulting confidence effect" requirement).
"""

from __future__ import annotations

import dataclasses
import statistics
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

from argus.domain.wallet_positions import CONFIDENCE_HIGH, STATUS_CLOSED

# Section 41's frozen v1 recency windows -- P3-R4: all five are
# materialized as independent WalletMetricsSnapshot rows, never just
# LIFETIME. None means unbounded (LIFETIME).
WINDOW_DAYS: Final[dict[str, int | None]] = {
    "LIFETIME": None,
    "180D": 180,
    "90D": 90,
    "30D": 30,
    "7D": 7,
}

ALGORITHM_VERSION: Final[str] = "wallet_scoring_v1"
SCORE_VERSION: Final[str] = "qualification_score_v1"

CONFIDENCE_HIGH_TIER: Final[str] = "HIGH"
CONFIDENCE_MEDIUM_TIER: Final[str] = "MEDIUM"
CONFIDENCE_LOW_TIER: Final[str] = "LOW"
CONFIDENCE_UNKNOWN_TIER: Final[str] = "UNKNOWN"

# Section 38's frozen v1 weights -- never optimized/retuned in this phase.
COMPONENT_WEIGHTS: Final[dict[str, Decimal]] = {
    "selection_alpha": Decimal("0.25"),
    "consistency": Decimal("0.15"),
    "entry_timing": Decimal("0.15"),
    "forward_information": Decimal("0.15"),
    "risk_adjusted_return": Decimal("0.10"),
    "exit_capture": Decimal("0.10"),
    "recency": Decimal("0.05"),
    "data_confidence": Decimal("0.05"),
}
assert sum(COMPONENT_WEIGHTS.values()) == Decimal("1.00")  # noqa: S101 - module-load invariant

_NEUTRAL_PRIOR: Final[Decimal] = Decimal(50)
# Section 39's frozen v1 sample-size gate.
MIN_USABLE_CLOSED_POSITIONS: Final[int] = 20
MIN_DISTINCT_TOKENS: Final[int] = 10
# Section 40's frozen 70% lottery-dominance threshold.
LOTTERY_DOMINANCE_THRESHOLD: Final[Decimal] = Decimal("0.70")
# Section 40's penalty for a flagged (not automatically rejected) wallet.
LOTTERY_DOMINANCE_PENALTY: Final[Decimal] = Decimal("15")
INSIDER_PENALTY: Final[Decimal] = Decimal("20")
_MEDIUM_COMPLETENESS_DATA_QUALITY_PENALTY: Final[Decimal] = Decimal("5")

RECENCY_FULL_CREDIT_DAYS: Final[int] = 7
RECENCY_ZERO_CREDIT_DAYS: Final[int] = 365


@dataclasses.dataclass(frozen=True, slots=True)
class PositionForScoring:
    """The subset of a reconstructed position's fields scoring actually
    needs, plus the ``token_id``/``possible_deployer``/``early_buyer_
    sequence_number`` evidence scoring cross-references from Phase 2 --
    kept as a small, explicit input contract independent of the ORM
    model shape."""

    token_id: str
    confidence: str
    status: str
    realized_pnl_quote: Decimal | None
    entry_value_quote: Decimal | None
    peak_profit_capture: Decimal | None
    first_entry_at: datetime | None
    last_entry_at: datetime | None
    # P3-R5: required for realization-order drawdown and window-membership
    # filtering -- a closed round trip's own exit time, never approximated
    # by last_entry_at (an entry-side timestamp).
    final_exit_at: datetime | None = None
    # From argus.domain.early_buyers, when this wallet has a recorded
    # early-buyer row for this token -- None when no such evidence
    # exists (never guessed).
    early_buyer_sequence_number: int | None = None
    possible_deployer: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class PositionStats:
    closed_count: int
    distinct_tokens: int
    returns: tuple[Decimal, ...]  # per closed position: realized_pnl / entry_value
    hit_count: int
    median_return: Decimal | None
    mean_return: Decimal | None
    trimmed_mean_return: Decimal | None
    winsorized_return: Decimal | None
    profit_factor: Decimal | None
    hit_rate: Decimal | None
    largest_trade_contribution_pct: Decimal | None
    top_three_trade_contribution_pct: Decimal | None
    max_drawdown: Decimal | None
    distinct_profitable_token_count: int
    lottery_dominated: bool
    total_realized_pnl: Decimal


@dataclasses.dataclass(frozen=True, slots=True)
class FeatureFingerprint:
    selection_skill: Decimal | None
    early_discovery_skill: Decimal | None
    entry_timing_skill: Decimal | None
    exit_skill: Decimal | None
    risk_control_skill: Decimal | None
    consistency: Decimal | None
    copyability: Decimal | None
    forward_information_value: Decimal | None
    recency: Decimal | None
    data_confidence: Decimal | None
    insider_risk: Decimal | None


@dataclasses.dataclass(frozen=True, slots=True)
class ScoringResult:
    stats: PositionStats
    fingerprint: FeatureFingerprint
    descriptive_score: Decimal
    qualification_score: Decimal
    component_values: dict[str, Decimal | None]
    penalties: dict[str, Decimal]
    confidence: str
    eligible_for_qualification: bool
    sample_gate_reason: str


def compute_position_stats(positions: list[PositionForScoring]) -> PositionStats:
    """Section 40's lottery-dominance/return-distribution metrics, from
    only genuinely CLOSED positions -- an OPEN position has no realized
    return to include, never estimated from an unknowable current mark."""
    closed = [
        p
        for p in positions
        if p.status == STATUS_CLOSED and p.realized_pnl_quote is not None and p.entry_value_quote
    ]
    returns = tuple(
        sorted(
            p.realized_pnl_quote / p.entry_value_quote
            for p in closed
            if p.realized_pnl_quote is not None and p.entry_value_quote
        )
    )
    # P3-R5: distinct-token eligibility counts only tokens with at least
    # one usable CLOSED outcome -- an open position (however many exist)
    # contributes no usable outcome and must never inflate this count.
    distinct_tokens = len({p.token_id for p in closed})
    total_pnl = sum((p.realized_pnl_quote or Decimal(0) for p in closed), Decimal(0))

    if not returns:
        return PositionStats(
            closed_count=0,
            distinct_tokens=distinct_tokens,
            returns=(),
            hit_count=0,
            median_return=None,
            mean_return=None,
            trimmed_mean_return=None,
            winsorized_return=None,
            profit_factor=None,
            hit_rate=None,
            largest_trade_contribution_pct=None,
            top_three_trade_contribution_pct=None,
            max_drawdown=None,
            distinct_profitable_token_count=0,
            lottery_dominated=False,
            total_realized_pnl=total_pnl,
        )

    hit_count = sum(1 for r in returns if r > 0)
    hit_rate = Decimal(hit_count) / Decimal(len(returns))
    median_return = Decimal(str(statistics.median(returns)))
    mean_return = sum(returns, Decimal(0)) / Decimal(len(returns))

    # Trim/winsorize the top and bottom 10% (rounded down), a standard,
    # deterministic robust-statistics convention -- never less than
    # dropping/clamping 0 at each tail on a tiny sample.
    trim_n = len(returns) // 10
    if trim_n > 0:
        trimmed = returns[trim_n:-trim_n]
        winsorized = (
            (returns[trim_n],) * trim_n + returns[trim_n:-trim_n] + (returns[-trim_n - 1],) * trim_n
        )
    else:
        trimmed = returns
        winsorized = returns
    trimmed_mean = Decimal(sum(trimmed)) / Decimal(len(trimmed)) if trimmed else None
    winsorized_mean = Decimal(sum(winsorized)) / Decimal(len(winsorized)) if winsorized else None

    gains = [
        p.realized_pnl_quote
        for p in closed
        if p.realized_pnl_quote is not None and p.realized_pnl_quote > 0
    ]
    losses = [
        -p.realized_pnl_quote
        for p in closed
        if p.realized_pnl_quote is not None and p.realized_pnl_quote < 0
    ]
    gross_gain = sum(gains, Decimal(0))
    gross_loss = sum(losses, Decimal(0))
    profit_factor = (gross_gain / gross_loss) if gross_loss > 0 else None

    # P3-R5: the frozen lottery-dominance ratio is largest-single-
    # position-PnL divided by estimated NET lifetime P&L (total_pnl,
    # gains and losses both included) -- never divided by gross positive
    # gains alone, which understates the ratio whenever real losses
    # exist elsewhere (a wallet with +100/-90 nets only +10, so its
    # single +100 winner is actually 10x its whole net result, not 100%
    # of gross gains). Undefined (None, not zero) when net lifetime P&L
    # is not positive -- "not a positive lifetime-profit contribution"
    # cannot be described as a fraction of a non-positive total.
    pnls_sorted_desc = sorted((p.realized_pnl_quote or Decimal(0) for p in closed), reverse=True)
    if total_pnl > 0 and pnls_sorted_desc and pnls_sorted_desc[0] > 0:
        largest_trade_contribution: Decimal | None = pnls_sorted_desc[0] / total_pnl
        top_three_contribution: Decimal | None = (
            sum(p for p in pnls_sorted_desc[:3] if p > 0) / total_pnl
        )
    else:
        largest_trade_contribution = None
        top_three_contribution = None

    # Max drawdown across the closed-trade equity curve in realization
    # (exit) order -- final_exit_at, never last_entry_at (an entry-side
    # timestamp that does not reflect when a round trip's outcome was
    # actually realized).
    ordered_by_exit = [
        p.realized_pnl_quote or Decimal(0)
        for p in sorted(closed, key=lambda p: (p.final_exit_at or datetime.min, p.token_id))
    ]
    running = Decimal(0)
    peak = Decimal(0)
    max_dd = Decimal(0)
    for pnl in ordered_by_exit:
        running += pnl
        peak = max(peak, running)
        if peak > 0:
            drawdown = (peak - running) / peak
            max_dd = max(max_dd, drawdown)

    distinct_profitable_tokens = len(
        {p.token_id for p in closed if (p.realized_pnl_quote or 0) > 0}
    )
    lottery_dominated = (
        largest_trade_contribution is not None
        and largest_trade_contribution > LOTTERY_DOMINANCE_THRESHOLD
    )

    return PositionStats(
        closed_count=len(closed),
        distinct_tokens=distinct_tokens,
        returns=returns,
        hit_count=hit_count,
        median_return=median_return,
        mean_return=mean_return,
        trimmed_mean_return=trimmed_mean,
        winsorized_return=winsorized_mean,
        profit_factor=profit_factor,
        hit_rate=hit_rate,
        largest_trade_contribution_pct=largest_trade_contribution,
        top_three_trade_contribution_pct=top_three_contribution,
        max_drawdown=max_dd,
        distinct_profitable_token_count=distinct_profitable_tokens,
        lottery_dominated=lottery_dominated,
        total_realized_pnl=total_pnl,
    )


def _clamp_0_100(value: Decimal) -> Decimal:
    return max(Decimal(0), min(Decimal(100), value))


def _normalize_return_multiple(return_ratio: Decimal) -> Decimal:
    """A transparent, deterministic, documented V1 mapping: breakeven
    (0% return) -> 50, a total loss (-100%) -> 0, a +100% return -> 100,
    linear and clamped outside that range. Never claims statistical
    optimality -- a first honest prior, per section 38's own framing."""
    return _clamp_0_100(Decimal(50) + return_ratio * Decimal(50))


def compute_feature_fingerprint(
    positions: list[PositionForScoring],
    stats: PositionStats,
    *,
    as_of: datetime,
    robust: bool = True,
) -> FeatureFingerprint:
    """``robust=True`` (the qualification pass) derives ``selection_skill``
    from the outlier-resistant median return, deliberately so a single
    lottery-style winner cannot alone inflate perceived selection skill
    (section 40's own lottery-dominance concern). ``robust=False`` (the
    descriptive pass only) uses the plain arithmetic mean instead, so a
    wallet's descriptive picture genuinely reflects every position handed
    to it, discovery-trigger token included -- this is what makes the
    section-30 "TOKEN_A affects descriptive score, not qualification
    score" fixture an observable, not merely definitional, property."""
    return_summary = stats.mean_return if not robust else stats.median_return
    selection_skill = (
        _normalize_return_multiple(return_summary) if return_summary is not None else None
    )
    consistency = _clamp_0_100(stats.hit_rate * 100) if stats.hit_rate is not None else None

    timing_scores = [
        _clamp_0_100(
            Decimal(100)
            * max(Decimal(0), Decimal(1) - Decimal(p.early_buyer_sequence_number - 1) / Decimal(50))
        )
        for p in positions
        if p.early_buyer_sequence_number is not None
    ]
    entry_timing_skill = sum(timing_scores) / Decimal(len(timing_scores)) if timing_scores else None
    early_discovery_skill = entry_timing_skill  # same evidence, section 37's paired concept

    capture_scores = [p.peak_profit_capture for p in positions if p.peak_profit_capture is not None]
    exit_skill = (
        _clamp_0_100(Decimal(100) * (sum(capture_scores) / Decimal(len(capture_scores))))
        if capture_scores
        else None
    )

    risk_control_skill = (
        _clamp_0_100(Decimal(100) * (Decimal(1) - stats.max_drawdown))
        if stats.max_drawdown is not None
        else None
    )

    qualifying = [p for p in positions if p.confidence == CONFIDENCE_HIGH]
    copyability = (
        _clamp_0_100(Decimal(100) * Decimal(len(qualifying)) / Decimal(len(positions)))
        if positions
        else None
    )

    # Phase 4 (prospective monitoring) does not exist yet -- always
    # explicitly unavailable, never fabricated (this instruction's own
    # explicit requirement).
    forward_information_value = None

    last_activity = max(
        (p.last_entry_at for p in positions if p.last_entry_at is not None), default=None
    )
    recency: Decimal | None
    if last_activity is None:
        recency = None
    else:
        days_since = max(
            Decimal(0), Decimal((as_of - last_activity).total_seconds()) / Decimal(86400)
        )
        if days_since <= RECENCY_FULL_CREDIT_DAYS:
            recency = Decimal(100)
        elif days_since >= RECENCY_ZERO_CREDIT_DAYS:
            recency = Decimal(0)
        else:
            span = Decimal(RECENCY_ZERO_CREDIT_DAYS - RECENCY_FULL_CREDIT_DAYS)
            recency = _clamp_0_100(
                Decimal(100) * (Decimal(1) - (days_since - RECENCY_FULL_CREDIT_DAYS) / span)
            )

    resolved = [p for p in positions if p.confidence in (CONFIDENCE_HIGH, "MEDIUM")]
    data_confidence = (
        _clamp_0_100(Decimal(100) * Decimal(len(resolved)) / Decimal(len(positions)))
        if positions
        else None
    )

    insider_risk = Decimal(100) if any(p.possible_deployer for p in positions) else None

    return FeatureFingerprint(
        selection_skill=selection_skill,
        early_discovery_skill=early_discovery_skill,
        entry_timing_skill=entry_timing_skill,
        exit_skill=exit_skill,
        risk_control_skill=risk_control_skill,
        consistency=consistency,
        copyability=copyability,
        forward_information_value=forward_information_value,
        recency=recency,
        data_confidence=data_confidence,
        insider_risk=insider_risk,
    )


def _sample_gate(stats: PositionStats, *, history_completeness: str) -> tuple[bool, str]:
    reasons = []
    ok = True
    if stats.closed_count < MIN_USABLE_CLOSED_POSITIONS:
        ok = False
        reasons.append(
            f"only {stats.closed_count} usable closed position(s), "
            f"need >= {MIN_USABLE_CLOSED_POSITIONS}"
        )
    if stats.distinct_tokens < MIN_DISTINCT_TOKENS:
        ok = False
        reasons.append(
            f"only {stats.distinct_tokens} distinct token(s) with usable outcomes, "
            f"need >= {MIN_DISTINCT_TOKENS}"
        )
    if history_completeness in ("LOW", "UNKNOWN"):
        ok = False
        reasons.append(f"history_completeness={history_completeness!r} (must not be LOW/UNKNOWN)")
    if ok:
        return True, (
            f"eligible: {stats.closed_count} closed positions across "
            f"{stats.distinct_tokens} distinct tokens, history_completeness="
            f"{history_completeness!r}"
        )
    return False, "; ".join(reasons)


def _weighted_score(component_values: dict[str, Decimal | None]) -> Decimal:
    total = Decimal(0)
    for name, weight in COMPONENT_WEIGHTS.items():
        value = component_values.get(name)
        total += weight * (value if value is not None else _NEUTRAL_PRIOR)
    return _clamp_0_100(total)


def qualifying_positions_for(
    all_positions: list[PositionForScoring], discovery_contaminated_token_ids: frozenset[str]
) -> list[PositionForScoring]:
    """The one structural contamination-exclusion filter (section 30):
    every token this wallet was discovered through, AND every position
    below HIGH/MEDIUM confidence (section 35's own "only high/medium
    confidence positions substantially contribute to qualification"),
    is excluded before anything else ever computes from this list.
    Exposed publicly so ``score_wallet`` and the per-window metrics
    computation (P3-R4) both build from exactly the same filtered set --
    a contaminated token can never appear in any qualification window
    either."""
    return [
        p
        for p in all_positions
        if p.token_id not in discovery_contaminated_token_ids
        and p.confidence in (CONFIDENCE_HIGH, "MEDIUM")
    ]


def filter_positions_for_window(
    positions: list[PositionForScoring], *, as_of: datetime, window_days: int | None
) -> list[PositionForScoring]:
    """P3-R4: restricts ``positions`` to the ones that belong in one
    recency window. ``window_days=None`` is LIFETIME (unbounded).
    Closed-position membership uses ``final_exit_at`` (when its outcome
    was actually realized); an open position's evidence is relevant to a
    window only via its own last-known activity (``last_entry_at``) --
    never a later observation leaking into an earlier window snapshot,
    since both timestamps are themselves already bounded by ``as_of``
    upstream (P3-R1)."""
    if window_days is None:
        return positions
    cutoff = as_of - timedelta(days=window_days)
    result: list[PositionForScoring] = []
    for p in positions:
        member_at = p.final_exit_at if p.status == STATUS_CLOSED else p.last_entry_at
        if member_at is not None and cutoff <= member_at <= as_of:
            result.append(p)
    return result


def score_wallet(
    *,
    all_positions: list[PositionForScoring],
    discovery_contaminated_token_ids: frozenset[str],
    history_completeness: str,
    as_of: datetime,
) -> ScoringResult:
    """The one public entry point. ``qualification_score`` is computed
    from ``all_positions`` filtered to exclude every
    ``discovery_contaminated_token_ids`` member AND restricted to
    HIGH/MEDIUM-confidence positions only (section 35's own "only high/
    medium confidence positions substantially contribute to
    qualification"); ``descriptive_score`` uses every position, any
    confidence, contaminated tokens included."""
    qualifying_positions = qualifying_positions_for(all_positions, discovery_contaminated_token_ids)

    qual_stats = compute_position_stats(qualifying_positions)
    qual_fingerprint = compute_feature_fingerprint(qualifying_positions, qual_stats, as_of=as_of)

    descriptive_stats = compute_position_stats(all_positions)
    descriptive_fingerprint = compute_feature_fingerprint(
        all_positions, descriptive_stats, as_of=as_of, robust=False
    )

    component_values: dict[str, Decimal | None] = {
        "selection_alpha": qual_fingerprint.selection_skill,
        "consistency": qual_fingerprint.consistency,
        "entry_timing": qual_fingerprint.entry_timing_skill,
        "forward_information": qual_fingerprint.forward_information_value,
        "risk_adjusted_return": qual_fingerprint.risk_control_skill,
        "exit_capture": qual_fingerprint.exit_skill,
        "recency": qual_fingerprint.recency,
        "data_confidence": qual_fingerprint.data_confidence,
    }
    descriptive_component_values: dict[str, Decimal | None] = {
        "selection_alpha": descriptive_fingerprint.selection_skill,
        "consistency": descriptive_fingerprint.consistency,
        "entry_timing": descriptive_fingerprint.entry_timing_skill,
        "forward_information": descriptive_fingerprint.forward_information_value,
        "risk_adjusted_return": descriptive_fingerprint.risk_control_skill,
        "exit_capture": descriptive_fingerprint.exit_skill,
        "recency": descriptive_fingerprint.recency,
        "data_confidence": descriptive_fingerprint.data_confidence,
    }

    raw_qualification_score = _weighted_score(component_values)
    descriptive_score = _weighted_score(descriptive_component_values)

    penalties: dict[str, Decimal] = {
        "insider_penalty": INSIDER_PENALTY if qual_fingerprint.insider_risk else Decimal(0),
        "cluster_uncertainty_penalty": Decimal(
            0
        ),  # filled in by the caller (argus.wallets.clustering)
        "lottery_dominance_penalty": (
            LOTTERY_DOMINANCE_PENALTY if qual_stats.lottery_dominated else Decimal(0)
        ),
        "data_quality_penalty": (
            _MEDIUM_COMPLETENESS_DATA_QUALITY_PENALTY
            if history_completeness == "MEDIUM"
            else Decimal(0)
        ),
        "predation_penalty": Decimal(0),  # no Phase 3 evidence signal exists yet -- honest zero
    }
    total_penalty = sum(penalties.values())

    eligible, gate_reason = _sample_gate(qual_stats, history_completeness=history_completeness)

    if eligible:
        qualification_score = _clamp_0_100(raw_qualification_score - total_penalty)
    else:
        # Section 39: confidence-shrink toward a neutral population
        # prior in proportion to how far short of the sample AND
        # completeness thresholds this wallet falls -- deterministic,
        # never simply capped at a fixed ceiling (which would still let
        # a very high raw score sit just under the cap and misleadingly
        # imply near-elite standing on a tiny/unreliable sample). LOW/
        # UNKNOWN history completeness shrinks even a superficially
        # large, otherwise-passing sample, since the sample itself may
        # be an unrepresentative fragment of this wallet's real history.
        position_fraction = min(
            Decimal(1), Decimal(qual_stats.closed_count) / Decimal(MIN_USABLE_CLOSED_POSITIONS)
        )
        token_fraction = min(
            Decimal(1), Decimal(qual_stats.distinct_tokens) / Decimal(MIN_DISTINCT_TOKENS)
        )
        completeness_fraction = {
            "HIGH": Decimal(1),
            "MEDIUM": Decimal(1),
            "LOW": Decimal("0.5"),
            "UNKNOWN": Decimal(0),
        }.get(history_completeness, Decimal(0))
        sample_fraction = position_fraction * token_fraction * completeness_fraction
        shrunk = _NEUTRAL_PRIOR + (raw_qualification_score - _NEUTRAL_PRIOR) * sample_fraction
        qualification_score = _clamp_0_100(shrunk - total_penalty)

    # P3-R6: forward_information's known absence counts toward the
    # missing-evidence tally like every other component -- it is never
    # excluded from this count. Since forward_information is always
    # unavailable in Phase 3 (it needs Phase 4 prospective data that does
    # not exist yet), HIGH confidence is therefore structurally
    # unreachable until Phase 4 exists -- an honest, disclosed,
    # documented V1 consequence (this instruction's own "must cap/lower
    # confidence according to one documented V1 rule"), not a bug. It
    # still contributes its neutral-prior weight to the score itself
    # (section 38's "never redistributed" rule, applied in
    # ``_weighted_score`` above) -- only the *confidence* tier is capped.
    missing_required = sum(1 for name in COMPONENT_WEIGHTS if component_values.get(name) is None)
    if missing_required == 0:
        confidence = CONFIDENCE_HIGH_TIER
    elif missing_required <= 2:
        confidence = CONFIDENCE_MEDIUM_TIER
    elif qual_stats.closed_count > 0:
        confidence = CONFIDENCE_LOW_TIER
    else:
        confidence = CONFIDENCE_UNKNOWN_TIER

    return ScoringResult(
        stats=qual_stats,
        fingerprint=qual_fingerprint,
        descriptive_score=descriptive_score,
        qualification_score=qualification_score,
        component_values=component_values,
        penalties=penalties,
        confidence=confidence,
        eligible_for_qualification=eligible,
        sample_gate_reason=gate_reason,
    )
