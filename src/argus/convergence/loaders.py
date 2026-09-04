"""argus.convergence.loaders -- MASTER_SPEC.md Phase 8 (CONVERGENCE +
NEGATIVE EVIDENCE) production data loaders: Phase 3 wallet-cluster-link
evidence restricted to a specific group of wallets, and the significant
(FDR-surviving) Phase 7 directional edges and their own underlying
lead/follow observations that seed dog-that-didn't-bark checks.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from argus.convergence.outcome_comparison import (
    OutcomeComparisonResult,
    compute_executable_outcome_stats,
    compute_mark_return_summary,
)
from argus.copyability.executable_returns import ExecutableReturnResult
from argus.copyability.identity import known_by_cutoff
from argus.copyability.loaders import (
    PRIMARY_EXECUTABLE_HORIZON,
    WalletOpportunity,
    load_contamination_firewall,
    load_wallet_opportunities,
)
from argus.domain.directional_edges import DirectionalEdge
from argus.domain.lead_follow_observations import LeadFollowObservation
from argus.domain.shadow_mark_outcomes import OUTCOME_RECORDED, ShadowMarkOutcome
from argus.domain.wallet_cluster_links import WalletClusterLink
from argus.wallets.clustering import ClusterLinkEvidence

MemberRef = tuple[uuid.UUID, uuid.UUID, datetime]
"""(wallet_id, token_id, entered_at) -- one outcome-comparison class
member's identity, enough to look up its own real Phase 5 executable-
return and mark-return evidence."""


async def load_cluster_links_within_group(
    session: AsyncSession, wallet_ids: set[uuid.UUID]
) -> dict[uuid.UUID, list[ClusterLinkEvidence]]:
    """Every ``wallet_cluster_links`` row where BOTH endpoints are members
    of ``wallet_ids`` -- a link to a wallet outside this universe carries
    no information about any group formed from within it. Safe to call
    once with the full universe of entrant wallets across many episodes;
    ``argus.convergence.independence.compute_independence_weights`` does
    its own further per-group restriction. FSR-04: deliberately NOT
    filtered by any single cutoff here -- each episode has its own
    ``window_end`` decision time, so ``compute_independence_weights``
    applies the M1 point-in-time filter per-episode using each link's own
    ``as_of``/``created_at``, never a single run-wide cutoff that would
    leak a later episode's cluster evidence into an earlier one."""
    if not wallet_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(WalletClusterLink).where(
                    WalletClusterLink.wallet_a_id.in_(wallet_ids),
                    WalletClusterLink.wallet_b_id.in_(wallet_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    links_by_wallet: dict[uuid.UUID, list[ClusterLinkEvidence]] = {w: [] for w in wallet_ids}
    for row in rows:
        links_by_wallet[row.wallet_a_id].append(
            ClusterLinkEvidence(
                other_wallet_id=str(row.wallet_b_id),
                evidence_type=row.evidence_type,
                probability=row.probability,
                as_of=row.as_of,
                created_at=row.created_at,
            )
        )
        links_by_wallet[row.wallet_b_id].append(
            ClusterLinkEvidence(
                other_wallet_id=str(row.wallet_a_id),
                evidence_type=row.evidence_type,
                probability=row.probability,
                as_of=row.as_of,
                created_at=row.created_at,
            )
        )
    return links_by_wallet


async def load_significant_directional_edges(
    session: AsyncSession,
    *,
    algorithm_version: str,
    config_hash: str,
    as_of: datetime,
    q_value_threshold: Decimal,
    min_observations: int,
) -> list[DirectionalEdge]:
    """The Phase 7 edges from one specific prior run (identified by its
    own ``algorithm_version``/``config_hash``/``as_of``) that clear
    THIS Phase 8 run's own significance bar -- independent of whatever
    threshold that Phase 7 run itself used for candidate generation
    (``compute_and_persist_directional_edges`` persists every observed
    pair, regardless of significance)."""
    rows = (
        (
            await session.execute(
                select(DirectionalEdge).where(
                    DirectionalEdge.algorithm_version == algorithm_version,
                    DirectionalEdge.config_hash == config_hash,
                    DirectionalEdge.as_of == as_of,
                    DirectionalEdge.q_value <= q_value_threshold,
                    DirectionalEdge.observation_count >= min_observations,
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def load_observations_for_edge(
    session: AsyncSession,
    *,
    leader_wallet_id: uuid.UUID,
    follower_wallet_id: uuid.UUID,
    algorithm_version: str,
) -> list[LeadFollowObservation]:
    """Every persisted Phase 7 lead/follow observation for one specific
    (leader, follower) pair -- the raw evidence both the expected
    confirmation window (its ``lag_seconds`` distribution) and the
    per-token confirmation lookup (its ``token_id``/``follower_entered_at``)
    are built from."""
    rows = (
        (
            await session.execute(
                select(LeadFollowObservation).where(
                    LeadFollowObservation.leader_wallet_id == leader_wallet_id,
                    LeadFollowObservation.follower_wallet_id == follower_wallet_id,
                    LeadFollowObservation.algorithm_version == algorithm_version,
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _load_mark_returns_for_positions(
    session: AsyncSession,
    *,
    shadow_position_ids: set[uuid.UUID],
    horizon_label: str,
    cutoff: datetime,
) -> dict[uuid.UUID, Decimal]:
    """FSR-06: real ``shadow_mark_outcomes`` evidence at ``horizon_label``,
    known by ``cutoff`` and actually ``RECORDED`` -- descriptive-only
    (section 47/48), never a substitute for executable-outcome evidence."""
    if not shadow_position_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(ShadowMarkOutcome).where(
                    ShadowMarkOutcome.shadow_position_id.in_(shadow_position_ids),
                    ShadowMarkOutcome.horizon_label == horizon_label,
                )
            )
        )
        .scalars()
        .all()
    )
    result: dict[uuid.UUID, Decimal] = {}
    for row in rows:
        if not known_by_cutoff(
            created_at=row.created_at, effective_at=row.actual_at, cutoff=cutoff
        ):
            continue
        if row.outcome == OUTCOME_RECORDED and row.mark_return_pct is not None:
            result[row.shadow_position_id] = row.mark_return_pct
    return result


async def load_outcome_comparisons(
    session: AsyncSession,
    *,
    members_by_class: dict[str, list[MemberRef]],
    cutoff: datetime,
) -> dict[str, OutcomeComparisonResult]:
    """FSR-06: the required Phase 8 outcome-comparison layer -- for each
    class in ``members_by_class``, matches every member's own known-by-
    cutoff Phase 5 executable-return evidence at the primary 5m horizon
    (:func:`argus.copyability.loaders.load_wallet_opportunities`, the SAME
    real evidence FSR-05 reuses for Phase 7) plus its descriptive-only
    mark-return evidence, and reduces both to
    :class:`~argus.convergence.outcome_comparison.OutcomeComparisonResult`.
    Every distinct wallet's opportunity population and every matched
    shadow position's mark outcomes are loaded exactly once, shared
    across all classes that reference them."""
    distinct_wallet_ids = {
        wallet_id for members in members_by_class.values() for wallet_id, _, _ in members
    }
    opportunities_by_wallet: dict[uuid.UUID, list[WalletOpportunity]] = {}
    for wallet_id in distinct_wallet_ids:
        firewall = await load_contamination_firewall(session, wallet_id=wallet_id)
        loaded = await load_wallet_opportunities(
            session, wallet_id=wallet_id, cutoff=cutoff, firewall=firewall
        )
        opportunities_by_wallet[wallet_id] = loaded.opportunities

    matched_by_class: dict[str, list[WalletOpportunity | None]] = {}
    all_shadow_position_ids: set[uuid.UUID] = set()
    for class_name, members in members_by_class.items():
        matched: list[WalletOpportunity | None] = []
        for wallet_id, token_id, entered_at in members:
            opportunity = next(
                (
                    opp
                    for opp in opportunities_by_wallet.get(wallet_id, [])
                    if opp.token_id == token_id and opp.first_seen_at == entered_at
                ),
                None,
            )
            matched.append(opportunity)
            if opportunity is not None and opportunity.shadow_position_id is not None:
                all_shadow_position_ids.add(opportunity.shadow_position_id)
        matched_by_class[class_name] = matched

    mark_by_position = await _load_mark_returns_for_positions(
        session,
        shadow_position_ids=all_shadow_position_ids,
        horizon_label=PRIMARY_EXECUTABLE_HORIZON,
        cutoff=cutoff,
    )

    results: dict[str, OutcomeComparisonResult] = {}
    for class_name, matched in matched_by_class.items():
        executable_results: list[ExecutableReturnResult | None] = []
        mark_returns: list[Decimal | None] = []
        for opportunity in matched:
            if opportunity is None:
                executable_results.append(None)
                mark_returns.append(None)
                continue
            outcome = opportunity.reverse_outcomes.get(PRIMARY_EXECUTABLE_HORIZON)
            executable_results.append(outcome.result if outcome is not None else None)
            mark_returns.append(
                mark_by_position.get(opportunity.shadow_position_id)
                if opportunity.shadow_position_id is not None
                else None
            )
        results[class_name] = OutcomeComparisonResult(
            class_name=class_name,
            executable=compute_executable_outcome_stats(executable_results),
            mark=compute_mark_return_summary(mark_returns),
        )
    return results
