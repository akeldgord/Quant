"""Phase 5 orchestration: ties the M1-M7 pure mechanics and the production
loaders together into wallet-level copyability and per-opportunity
readiness computations, and persists both idempotently (P5-09). This is
the one place all of Phase 5's analytics are assembled -- ``argus
copyability report`` (the CLI command required by P5-10) calls this for
each tracked wallet/opportunity.

Remediated per ``argus-phase-5-remediation-001`` (F5-01 through F5-06):
wallet-level analytics are now built from
:func:`argus.copyability.loaders.load_wallet_opportunities`'s real event
population (never a position-only, entry-failure-dropping approximation);
the forward-information grid only fills a cell when a REAL observation's
actual elapsed time from ``first_seen_at`` exactly matches that cell's
nominal horizon (F5-02 -- an entry delayed 5s with a 5m holding exit is
never relabeled as the "5m" cell); M5's coverage/n/k/stability/holding-
duration/impact inputs are wired from that same real population (F5-03);
and a real per-opportunity readiness entry point now exists
(:func:`compute_opportunity_readiness`, F5-04), evaluating all six master
hard gates from actual evidence before any eligible score.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from argus.copyability.delay_curves import (
    DelayPoint,
    ForwardInfoCell,
    HalfLifeResult,
    build_forward_information_grid,
    compute_half_life,
    decimal_median,
)
from argus.copyability.delay_curves import (
    build_delay_curve as _build_delay_curve,
)
from argus.copyability.identity import SourceRef, evidence_manifest_digest
from argus.copyability.loaders import (
    PRIMARY_EXECUTABLE_HORIZON,
    WalletOpportunity,
    build_delay_observations_for_curve,
    build_forward_information_observations,
    load_contamination_firewall,
    load_prior_buy_sizes,
    load_wallet_opportunities,
)
from argus.copyability.persistence import (
    get_or_create_opportunity_readiness_snapshot,
    get_or_create_wallet_copyability_snapshot,
)
from argus.copyability.size_surprise import (
    SizeSurpriseInput,
    SizeSurpriseResult,
    compute_size_surprise,
)
from argus.domain.opportunity_readiness_snapshots import (
    ALL_GATE_KEYS,
    GATE_FAIL,
    GATE_PASS,
    GATE_UNKNOWN,
    OpportunityReadinessSnapshot,
)
from argus.domain.prospective_events import ProspectiveEvent
from argus.domain.shadow_intents import STATUS_FILLED, ShadowIntent
from argus.domain.shadow_positions import ShadowPosition
from argus.domain.tokens import Token
from argus.domain.wallet_copyability_snapshots import WalletCopyabilitySnapshot
from argus.domain.wallet_history_quality import WalletHistoryQuality
from argus.domain.wallet_score_snapshots import WalletScoreSnapshot
from argus.domain.wallets import Wallet
from argus.scoring.copyability import CopyabilityInputs, CopyabilityResult, compute_copyability
from argus.scoring.readiness import (
    ReadinessGates,
    ReadinessInputs,
    ReadinessResult,
    compute_readiness,
    gate,
)

ALGORITHM_VERSION = "copyability_v1"
READINESS_ALGORITHM_VERSION = "trade_readiness_v1"

# Same "hash every artifact whose code can change the decision" pattern
# Phase 3's qualification_service.BUILD_HASH established -- covers every
# Phase 5 module able to change a copyability/readiness output.
_PHASE5_ARTIFACT_RELATIVE_PATHS: Final[tuple[str, ...]] = (
    "identity.py",
    "executable_returns.py",
    "delay_curves.py",
    "size_surprise.py",
    "util.py",
    "loaders.py",
    "persistence.py",
    "service.py",
)
_SCORING_ARTIFACT_FILENAMES: Final[tuple[str, ...]] = (
    "copyability.py",
    "readiness.py",
    "config_weights.py",
)


def _compute_build_hash() -> str:
    digest = hashlib.sha256()
    module_dir = Path(__file__).parent
    scoring_dir = module_dir.parent / "scoring"
    for filename in _PHASE5_ARTIFACT_RELATIVE_PATHS:
        digest.update((module_dir / filename).read_bytes())
    for filename in _SCORING_ARTIFACT_FILENAMES:
        digest.update((scoring_dir / filename).read_bytes())
    return digest.hexdigest()


BUILD_HASH: Final[str] = _compute_build_hash()

SOL_MINT: Final[str] = "So11111111111111111111111111111111111111112"
_LONG_HORIZON_GRID_LABELS = ("30m", "1h", "6h", "24h")


@dataclass(frozen=True)
class WalletCopyabilityComputation:
    delay_points: list[DelayPoint]
    forward_information_grid: dict
    half_life: HalfLifeResult
    size_surprise: SizeSurpriseResult
    copyability: CopyabilityResult
    contributing_source_ids: list
    excluded_source_ids: list
    evidence_manifest_digest: str


async def compute_wallet_copyability(
    session: AsyncSession,
    *,
    wallet: Wallet,
    as_of: datetime,
    weights: dict[str, Decimal],
    quote_mint: str = SOL_MINT,
    exclude_shadow_intent_id: uuid.UUID | None = None,
) -> WalletCopyabilityComputation:
    firewall = await load_contamination_firewall(session, wallet_id=wallet.wallet_id)
    opp_result = await load_wallet_opportunities(
        session,
        wallet_id=wallet.wallet_id,
        cutoff=as_of,
        firewall=firewall,
        exclude_shadow_intent_id=exclude_shadow_intent_id,
    )
    opportunities = opp_result.opportunities

    curve_observations = build_delay_observations_for_curve(
        opportunities, horizon_label=PRIMARY_EXECUTABLE_HORIZON, quote_mint=quote_mint
    )
    delay_points = _build_delay_curve(curve_observations)
    half_life = compute_half_life(delay_points)

    # Forward-information grid: F5-02 -- only a REAL exact-elapsed-time
    # match fills a cell; nothing is relabeled or interpolated.
    horizon_observations = build_forward_information_observations(opportunities)
    grid_cells: dict[str, ForwardInfoCell] = {}
    for label, fractions in horizon_observations.items():
        if fractions:
            grid_cells[label] = ForwardInfoCell(
                available=True, return_fraction=decimal_median(fractions), is_executable=True
            )
    forward_information_grid = build_forward_information_grid(grid_cells)

    prior_buys = await load_prior_buy_sizes(
        session,
        wallet_address=wallet.wallet_address,
        quote_mint=quote_mint,
        signal_at=as_of,
        cutoff=as_of,
        firewall=firewall,
    )
    # Wallet-level report has no single "current" opportunity -- size
    # surprise stays descriptive-only here (F5-01: never substitute zero).
    size_surprise = compute_size_surprise(
        SizeSurpriseInput(prior_sizes=prior_buys.sizes, current_size=None)
    )

    copyability_inputs = _build_copyability_inputs(
        opportunities=opportunities,
        delay_points=delay_points,
        half_life=half_life,
        history_completeness=await _load_history_completeness(
            session, wallet_id=wallet.wallet_id, cutoff=as_of
        ),
    )
    copyability = compute_copyability(copyability_inputs, weights=weights)

    all_contributing = list(opp_result.contributing) + list(prior_buys.contributing)
    all_excluded = list(opp_result.excluded) + list(prior_buys.excluded)
    digest = evidence_manifest_digest(all_contributing)

    return WalletCopyabilityComputation(
        delay_points=delay_points,
        forward_information_grid=forward_information_grid,
        half_life=half_life,
        size_surprise=size_surprise,
        copyability=copyability,
        contributing_source_ids=[ref.as_dict() for ref in all_contributing],
        excluded_source_ids=[ref.as_dict() for ref in all_excluded],
        evidence_manifest_digest=digest,
    )


def _build_copyability_inputs(
    *,
    opportunities: list[WalletOpportunity],
    delay_points: list[DelayPoint],
    half_life: HalfLifeResult,
    history_completeness: str,
) -> CopyabilityInputs:
    """F5-03: wires every M5 component from the REAL opportunity
    population -- entry failures/missing reverses count in coverage;
    n/k/stability/holding-pairs/impact are all derived from actual
    per-event evidence, never hardcoded placeholders."""
    primary_successes = [
        opp
        for opp in opportunities
        if PRIMARY_EXECUTABLE_HORIZON in opp.reverse_outcomes
        and opp.reverse_outcomes[PRIMARY_EXECUTABLE_HORIZON].result.status == "SUCCESS"
        and opp.reverse_outcomes[PRIMARY_EXECUTABLE_HORIZON].result.gross_return_fraction
        is not None
    ]
    primary_terminal = [
        opp for opp in opportunities if PRIMARY_EXECUTABLE_HORIZON in opp.reverse_outcomes
    ]

    primary_success_fractions = [
        fraction
        for opp in primary_successes
        if (
            fraction := opp.reverse_outcomes[
                PRIMARY_EXECUTABLE_HORIZON
            ].result.gross_return_fraction
        )
        is not None
    ]
    follower_alpha_median = (
        decimal_median(primary_success_fractions) if primary_success_fractions else None
    )

    n = len(primary_successes)
    k = len({opp.token_id for opp in primary_successes if opp.token_id is not None})
    coverage_denominator = len(opportunities)
    coverage_numerator = n

    per_event_stability: list[Decimal] = []
    for opp in opportunities:
        if opp.shadow_position_id is None:
            continue
        success_fractions = [
            outcome.result.gross_return_fraction
            for outcome in opp.reverse_outcomes.values()
            if outcome.result.status == "SUCCESS"
            and outcome.result.gross_return_fraction is not None
        ]
        if not success_fractions:
            continue
        nonneg = sum(1 for fraction in success_fractions if fraction >= 0)
        per_event_stability.append(Decimal(nonneg) / Decimal(len(success_fractions)))

    holding_pairs_total = 0
    holding_pairs_5m_le_30m = 0
    for opp in opportunities:
        five_m = opp.reverse_outcomes.get("5m")
        thirty_m = opp.reverse_outcomes.get("30m")
        if (
            five_m is not None
            and thirty_m is not None
            and five_m.result.status == "SUCCESS"
            and thirty_m.result.status == "SUCCESS"
            and five_m.result.gross_return_fraction is not None
            and thirty_m.result.gross_return_fraction is not None
        ):
            holding_pairs_total += 1
            if thirty_m.result.gross_return_fraction >= five_m.result.gross_return_fraction:
                holding_pairs_5m_le_30m += 1

    positive_peak = (
        half_life.peak_return_fraction
        if half_life.outcome in ("PEAK_FOUND", "RIGHT_CENSORED")
        else None
    )
    latest_point = max(delay_points, key=lambda p: p.target_seconds) if delay_points else None
    latest_return = latest_point.median_return_fraction if latest_point else None

    entry_impact_fractions: list[Decimal] = [
        opp.entry_price_impact_pct
        for opp in opportunities
        if opp.entry_price_impact_pct is not None
    ]
    mean_impact = (
        sum(entry_impact_fractions, Decimal(0)) / Decimal(len(entry_impact_fractions))
        if entry_impact_fractions
        else None
    )

    return CopyabilityInputs(
        follower_alpha_median_return_fraction=follower_alpha_median,
        follower_alpha_reason=None
        if follower_alpha_median is not None
        else "no comparable primary-horizon executable returns",
        successful_qty_matched_reverse_count=len(
            [
                o
                for o in primary_terminal
                if o.reverse_outcomes[PRIMARY_EXECUTABLE_HORIZON].result.status == "SUCCESS"
            ]
        ),
        all_terminal_reverse_count=len(primary_terminal),
        per_event_stability_fractions=tuple(per_event_stability),
        comparable_pairs_5m_le_30m_count=holding_pairs_5m_le_30m,
        comparable_pairs_total=holding_pairs_total,
        positive_peak_return_fraction=positive_peak,
        latest_comparable_delay_return_fraction=latest_return,
        adequate_comparable_evidence=len(delay_points) >= 2,
        mean_abs_price_impact_fraction=mean_impact,
        slippage_unavailable_reason=None
        if mean_impact is not None
        else "no evidenced entry price-impact for any opportunity",
        n_events=n,
        k_distinct_tokens=k,
        coverage_numerator=coverage_numerator,
        coverage_denominator=coverage_denominator,
        history_completeness=history_completeness,
    )


async def _load_history_completeness(
    session: AsyncSession, *, wallet_id: uuid.UUID, cutoff: datetime
) -> str:
    row = (
        await session.execute(
            select(WalletHistoryQuality)
            .where(
                WalletHistoryQuality.wallet_id == wallet_id,
                WalletHistoryQuality.created_at <= cutoff,
            )
            .order_by(WalletHistoryQuality.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row.history_completeness if row is not None else "UNKNOWN"


def build_snapshot_row(
    *,
    wallet: Wallet,
    as_of: datetime,
    computation: WalletCopyabilityComputation,
    weights: dict[str, Decimal],
    build_hash: str,
    config_hash: str,
    master_spec_hash: str,
    git_commit: str,
    computed_at: datetime,
) -> WalletCopyabilitySnapshot:
    cop = computation.copyability
    return WalletCopyabilitySnapshot(
        snapshot_id=uuid.uuid4(),
        wallet_id=wallet.wallet_id,
        as_of=as_of,
        algorithm_version=ALGORITHM_VERSION,
        contributing_source_ids=computation.contributing_source_ids,
        excluded_source_ids=computation.excluded_source_ids,
        evidence_manifest_digest=computation.evidence_manifest_digest,
        delay_curve={
            p.target_label: {
                "target_seconds": p.target_seconds,
                "median_return_fraction": str(p.median_return_fraction),
                "n": p.n,
                "event_ids": list(p.event_ids),
            }
            for p in computation.delay_points
        },
        half_life_result={
            "outcome": computation.half_life.outcome,
            "peak_target_label": computation.half_life.peak_target_label,
            "peak_seconds": computation.half_life.peak_seconds,
            "peak_return_fraction": (
                str(computation.half_life.peak_return_fraction)
                if computation.half_life.peak_return_fraction is not None
                else None
            ),
            "crossing_target_label": computation.half_life.crossing_target_label,
            "crossing_seconds": computation.half_life.crossing_seconds,
            "half_life_seconds": (
                str(computation.half_life.half_life_seconds)
                if computation.half_life.half_life_seconds is not None
                else None
            ),
            "reason": computation.half_life.reason,
        },
        forward_information_grid=computation.forward_information_grid,
        size_surprise={
            "baseline_count": computation.size_surprise.baseline_count,
            "median": str(computation.size_surprise.median)
            if computation.size_surprise.median is not None
            else None,
            "mad": str(computation.size_surprise.mad)
            if computation.size_surprise.mad is not None
            else None,
            "z": str(computation.size_surprise.z)
            if computation.size_surprise.z is not None
            else None,
            "component": str(computation.size_surprise.component)
            if computation.size_surprise.component is not None
            else None,
            "unavailable_reason": computation.size_surprise.unavailable_reason,
        },
        copyability_score=cop.score,
        copyability_components={
            key: comp.as_dict(weight=weights.get(key, Decimal(0)))
            for key, comp in cop.components.items()
        },
        available_weight=cop.available_weight,
        sample_n=cop.sample_n,
        sample_k=cop.sample_k,
        sample_coverage=cop.sample_coverage,
        sample_c=cop.sample_c,
        confidence=cop.confidence,
        descriptive_extras={},
        build_hash=build_hash,
        config_hash=config_hash,
        master_spec_hash=master_spec_hash,
        git_commit=git_commit,
        computed_at=computed_at,
    )


async def compute_and_persist_wallet_copyability(
    session: AsyncSession,
    *,
    wallet: Wallet,
    as_of: datetime,
    weights: dict[str, Decimal],
    build_hash: str,
    config_hash: str,
    master_spec_hash: str,
    git_commit: str,
    computed_at: datetime,
) -> tuple[WalletCopyabilitySnapshot, bool]:
    computation = await compute_wallet_copyability(
        session, wallet=wallet, as_of=as_of, weights=weights
    )

    def _build() -> WalletCopyabilitySnapshot:
        return build_snapshot_row(
            wallet=wallet,
            as_of=as_of,
            computation=computation,
            weights=weights,
            build_hash=build_hash,
            config_hash=config_hash,
            master_spec_hash=master_spec_hash,
            git_commit=git_commit,
            computed_at=computed_at,
        )

    return await get_or_create_wallet_copyability_snapshot(
        session,
        wallet_id=wallet.wallet_id,
        as_of=as_of,
        algorithm_version=ALGORITHM_VERSION,
        config_hash=config_hash,
        evidence_manifest_digest=computation.evidence_manifest_digest,
        build_row=_build,
    )


# --------------------------------------------------------------------
# F5-04: real per-opportunity readiness entry point (M6).
# --------------------------------------------------------------------

_ELIGIBLE_TIERS = ("A", "S")


async def _evaluate_gates(
    session: AsyncSession,
    *,
    prospective_event: ProspectiveEvent,
    token: Token | None,
    history_completeness: str,
    entry_route_present: bool | None,
) -> ReadinessGates:
    if token is None:
        token_safety = gate(GATE_UNKNOWN, "no persisted token record for this opportunity's mint")
    elif token.mint_validated:
        token_safety = gate(GATE_PASS, "token mint validated on-chain (token_mint_validations)")
    else:
        token_safety = gate(GATE_FAIL, "token mint not validated")

    if prospective_event.confirmation_time is not None:
        chain_freshness = gate(GATE_PASS, "leader transaction confirmed on-chain")
    else:
        chain_freshness = gate(GATE_UNKNOWN, "no confirmed commitment observation yet")

    if prospective_event.wallet_tier_snapshot in _ELIGIBLE_TIERS:
        wallet_eligibility = gate(
            GATE_PASS,
            f"frozen wallet tier snapshot {prospective_event.wallet_tier_snapshot!r} eligible",
        )
    else:
        wallet_eligibility = gate(
            GATE_FAIL,
            f"frozen wallet tier snapshot {prospective_event.wallet_tier_snapshot!r} not A/S",
        )

    if history_completeness in ("HIGH", "MEDIUM"):
        history_quality = gate(GATE_PASS, f"history completeness {history_completeness}")
    elif history_completeness == "LOW":
        history_quality = gate(GATE_FAIL, "history completeness LOW")
    else:
        history_quality = gate(GATE_UNKNOWN, "history completeness UNKNOWN")

    if entry_route_present is True:
        quote_validity = gate(GATE_PASS, "entry probe evidenced a present route")
    elif entry_route_present is False:
        quote_validity = gate(GATE_FAIL, "entry probe evidenced no route")
    else:
        quote_validity = gate(GATE_UNKNOWN, "no entry quote evidence for this opportunity")

    # No real risk-allowance/authority system exists yet in this phase
    # (Phase 6 territory) -- honestly UNKNOWN, never a fabricated PASS
    # (this instruction's own explicit rule).
    risk_caps = gate(GATE_UNKNOWN, "no configured live risk-allowance system exists in this phase")

    return ReadinessGates(
        token_safety=token_safety,
        chain_freshness=chain_freshness,
        wallet_eligibility=wallet_eligibility,
        history_quality=history_quality,
        quote_validity=quote_validity,
        risk_caps=risk_caps,
    )


@dataclass(frozen=True)
class OpportunityReadinessComputation:
    readiness: ReadinessResult
    contributing_source_ids: list
    excluded_source_ids: list
    evidence_manifest_digest: str


async def compute_opportunity_readiness(
    session: AsyncSession,
    *,
    prospective_event: ProspectiveEvent,
    as_of: datetime,
    copyability_weights: dict[str, Decimal],
    readiness_weights: dict[str, Decimal],
) -> OpportunityReadinessComputation:
    """F5-04: the real production readiness entry point -- evaluates all
    six master hard gates from actual evidence, computes an eligible
    as-of copyability snapshot EXCLUDING this opportunity's own event,
    and only then produces the (research-only) actionable/diagnostic
    scores via M6."""
    wallet = await session.get(Wallet, prospective_event.wallet_id)
    assert wallet is not None

    intent_row = (
        await session.execute(
            select(ShadowIntent).where(
                ShadowIntent.prospective_event_id == prospective_event.prospective_event_id
            )
        )
    ).scalar_one_or_none()

    entry_route_present: bool | None = None
    position: ShadowPosition | None = None
    if intent_row is not None and intent_row.status == STATUS_FILLED:
        position = (
            await session.execute(
                select(ShadowPosition).where(
                    ShadowPosition.shadow_intent_id == intent_row.shadow_intent_id
                )
            )
        ).scalar_one_or_none()
        if position is not None:
            entry_route_present = position.entry_route_present

    token = (
        await session.get(Token, prospective_event.token_id)
        if prospective_event.token_id is not None
        else None
    )
    history_completeness = await _load_history_completeness(
        session, wallet_id=wallet.wallet_id, cutoff=as_of
    )
    gates = await _evaluate_gates(
        session,
        prospective_event=prospective_event,
        token=token,
        history_completeness=history_completeness,
        entry_route_present=entry_route_present,
    )

    qualification_score = None
    if prospective_event.score_snapshot_id is not None:
        score_row = await session.get(WalletScoreSnapshot, prospective_event.score_snapshot_id)
        if score_row is not None:
            qualification_score = score_row.qualification_score

    copyability_computation = await compute_wallet_copyability(
        session,
        wallet=wallet,
        as_of=as_of,
        weights=copyability_weights,
        exclude_shadow_intent_id=intent_row.shadow_intent_id if intent_row else None,
    )
    copyability_score = copyability_computation.copyability.score

    size_component = copyability_computation.size_surprise.component

    readiness_inputs = ReadinessInputs(
        gates=gates,
        qualification_score=qualification_score,
        copyability_score=copyability_score,
        remaining_information_return_fraction=None,
        current_quote_price_impact_fraction=(
            position.entry_price_impact_pct if position is not None else None
        ),
        current_quote_impact_unavailable_reason=(
            "no current entry quote evidenced" if position is None else None
        ),
        current_price=None,
        leader_price=None,
        size_surprise_component=size_component,
        size_surprise_unavailable_reason=copyability_computation.size_surprise.unavailable_reason,
        independent_confirmation_value=None,
    )
    readiness = compute_readiness(readiness_inputs, weights=readiness_weights)

    prospective_event_ref = SourceRef(
        "prospective_event", str(prospective_event.prospective_event_id)
    )
    contributing = [
        prospective_event_ref.as_dict()
    ] + copyability_computation.contributing_source_ids
    digest = evidence_manifest_digest(
        [prospective_event_ref]
        + [
            SourceRef(ref["type"], ref["id"])
            for ref in copyability_computation.contributing_source_ids
        ]
    )

    return OpportunityReadinessComputation(
        readiness=readiness,
        contributing_source_ids=contributing,
        excluded_source_ids=copyability_computation.excluded_source_ids,
        evidence_manifest_digest=digest,
    )


def build_readiness_snapshot_row(
    *,
    prospective_event: ProspectiveEvent,
    as_of: datetime,
    computation: OpportunityReadinessComputation,
    build_hash: str,
    config_hash: str,
    master_spec_hash: str,
    git_commit: str,
    computed_at: datetime,
) -> OpportunityReadinessSnapshot:
    readiness = computation.readiness
    return OpportunityReadinessSnapshot(
        snapshot_id=uuid.uuid4(),
        prospective_event_id=prospective_event.prospective_event_id,
        wallet_id=prospective_event.wallet_id,
        as_of=as_of,
        algorithm_version=READINESS_ALGORITHM_VERSION,
        contributing_source_ids=computation.contributing_source_ids,
        excluded_source_ids=computation.excluded_source_ids,
        evidence_manifest_digest=computation.evidence_manifest_digest,
        gates={key: getattr(readiness.gates, key).as_dict() for key in ALL_GATE_KEYS},
        eligible=readiness.eligible,
        actionable_score=readiness.actionable_score,
        diagnostic_score=readiness.diagnostic_score,
        components={
            key: comp.as_dict(weight=Decimal(0)) for key, comp in readiness.components.items()
        },
        build_hash=build_hash,
        config_hash=config_hash,
        master_spec_hash=master_spec_hash,
        git_commit=git_commit,
        computed_at=computed_at,
    )


async def compute_and_persist_opportunity_readiness(
    session: AsyncSession,
    *,
    prospective_event: ProspectiveEvent,
    as_of: datetime,
    copyability_weights: dict[str, Decimal],
    readiness_weights: dict[str, Decimal],
    build_hash: str,
    config_hash: str,
    master_spec_hash: str,
    git_commit: str,
    computed_at: datetime,
) -> tuple[OpportunityReadinessSnapshot, bool]:
    computation = await compute_opportunity_readiness(
        session,
        prospective_event=prospective_event,
        as_of=as_of,
        copyability_weights=copyability_weights,
        readiness_weights=readiness_weights,
    )

    def _build() -> OpportunityReadinessSnapshot:
        return build_readiness_snapshot_row(
            prospective_event=prospective_event,
            as_of=as_of,
            computation=computation,
            build_hash=build_hash,
            config_hash=config_hash,
            master_spec_hash=master_spec_hash,
            git_commit=git_commit,
            computed_at=computed_at,
        )

    return await get_or_create_opportunity_readiness_snapshot(
        session,
        prospective_event_id=prospective_event.prospective_event_id,
        as_of=as_of,
        algorithm_version=READINESS_ALGORITHM_VERSION,
        config_hash=config_hash,
        evidence_manifest_digest=computation.evidence_manifest_digest,
        build_row=_build,
    )
