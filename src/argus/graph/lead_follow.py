"""argus.graph.lead_follow — MASTER_SPEC.md Phase 7 (ALPHA ANCESTRY).

Pure functions over already-known wallet-token entry timestamps: builds
lead/follow observations (which tracked wallet entered a token before
which other tracked wallet, within a bounded lag window), then aggregates
those into directional-edge statistics against a base-rate null model.

Every statistic here is purely OBSERVATIONAL/correlational -- an
"upstream candidate" is a wallet whose entries are followed by another
wallet's entries more often than base-rate chance would predict, with
that excess quantified and multiple-comparison-corrected (``argus.graph.
stats``). This module never claims or implies that a leader wallet
CAUSES a follower wallet's trade (MASTER_SPEC's own explicit "no
unsupported causal claims" rule for this phase) -- it is entirely
possible, and common, for two wallets to independently react to the same
public information with one merely acting sooner.
"""

from __future__ import annotations

import statistics
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from argus.graph.stats import (
    BHResult,
    benjamini_hochberg,
    binomial_upper_tail_p_value,
    effect_size_z,
)


@dataclass(frozen=True)
class WalletTokenEntry:
    """One tracked wallet's earliest known entry into one token --
    callers are responsible for already having deduplicated to one row
    per (wallet, token) before calling :func:`build_lead_follow_observations`
    (see that function's own docstring)."""

    wallet_id: uuid.UUID
    token_id: uuid.UUID
    entered_at: datetime
    source_id: uuid.UUID


@dataclass(frozen=True)
class LeadFollowObservation:
    token_id: uuid.UUID
    leader_wallet_id: uuid.UUID
    follower_wallet_id: uuid.UUID
    leader_entered_at: datetime
    follower_entered_at: datetime
    lag_seconds: Decimal
    leader_source_id: uuid.UUID
    follower_source_id: uuid.UUID


def build_lead_follow_observations(
    entries: list[WalletTokenEntry], *, max_lag: timedelta
) -> list[LeadFollowObservation]:
    """For every token, for every ordered pair of DISTINCT tracked
    wallets where one entered strictly before the other within
    ``max_lag``, emits one observation. If ``entries`` contains more than
    one row for the same (wallet_id, token_id), only the EARLIEST is
    used -- a wallet's own later re-entry into a token it already holds
    never creates an additional lead/follow pair for that token."""
    earliest_by_token: dict[uuid.UUID, dict[uuid.UUID, WalletTokenEntry]] = defaultdict(dict)
    for entry in entries:
        by_wallet = earliest_by_token[entry.token_id]
        existing = by_wallet.get(entry.wallet_id)
        if existing is None or entry.entered_at < existing.entered_at:
            by_wallet[entry.wallet_id] = entry

    observations: list[LeadFollowObservation] = []
    for token_id, by_wallet in earliest_by_token.items():
        wallet_entries = sorted(by_wallet.values(), key=lambda e: e.entered_at)
        for i, leader in enumerate(wallet_entries):
            for follower in wallet_entries[i + 1 :]:
                lag = follower.entered_at - leader.entered_at
                if lag > max_lag:
                    break
                observations.append(
                    LeadFollowObservation(
                        token_id=token_id,
                        leader_wallet_id=leader.wallet_id,
                        follower_wallet_id=follower.wallet_id,
                        leader_entered_at=leader.entered_at,
                        follower_entered_at=follower.entered_at,
                        lag_seconds=Decimal(str(lag.total_seconds())),
                        leader_source_id=leader.source_id,
                        follower_source_id=follower.source_id,
                    )
                )
    return observations


@dataclass(frozen=True)
class DirectionalEdgeResult:
    leader_wallet_id: uuid.UUID
    follower_wallet_id: uuid.UUID
    observation_count: int
    tokens_leader_entered: int
    follower_base_rate: Decimal
    median_lag_seconds: Decimal
    expected_follows: Decimal
    lift: Decimal | None
    effect_size: Decimal | None
    p_value: Decimal


def compute_directional_edge(
    *,
    leader_wallet_id: uuid.UUID,
    follower_wallet_id: uuid.UUID,
    observations: list[LeadFollowObservation],
    tokens_leader_entered: int,
    follower_base_rate: Decimal,
) -> DirectionalEdgeResult:
    """``follower_base_rate`` is the follower's own unconditional
    probability of entering a token drawn from the same universe the
    leader's tokens were drawn from (the null model this edge's
    excess-frequency claim is measured against) -- callers compute this
    from the follower's OWN total distinct-token entry count over the
    same universe/window, never guessed."""
    observation_count = len(observations)
    expected_follows = Decimal(tokens_leader_entered) * follower_base_rate
    variance = Decimal(tokens_leader_entered) * follower_base_rate * (1 - follower_base_rate)
    lift = Decimal(observation_count) / expected_follows if expected_follows > 0 else None
    effect_size = effect_size_z(
        observed=observation_count, expected=expected_follows, variance=variance
    )
    p_value = binomial_upper_tail_p_value(
        k=observation_count, n=tokens_leader_entered, p=follower_base_rate
    )
    median_lag = (
        Decimal(str(statistics.median(float(o.lag_seconds) for o in observations)))
        if observations
        else Decimal(0)
    )
    return DirectionalEdgeResult(
        leader_wallet_id=leader_wallet_id,
        follower_wallet_id=follower_wallet_id,
        observation_count=observation_count,
        tokens_leader_entered=tokens_leader_entered,
        follower_base_rate=follower_base_rate,
        median_lag_seconds=median_lag,
        expected_follows=expected_follows,
        lift=lift,
        effect_size=effect_size,
        p_value=p_value,
    )


@dataclass(frozen=True)
class DirectionalEdgeWithSignificance:
    edge: DirectionalEdgeResult
    q_value: Decimal


def apply_multiple_comparison_correction(
    edges: list[DirectionalEdgeResult],
) -> list[DirectionalEdgeWithSignificance]:
    """Benjamini-Hochberg FDR correction across EVERY candidate edge
    tested in one run -- never a bare per-edge p-value used alone to
    claim significance (see this module's own docstring)."""
    bh_results: list[BHResult] = benjamini_hochberg([e.p_value for e in edges])
    return [
        DirectionalEdgeWithSignificance(edge=edge, q_value=bh.q_value)
        for edge, bh in zip(edges, bh_results, strict=True)
    ]


def generate_upstream_candidates(
    edges: list[DirectionalEdgeWithSignificance],
    *,
    follower_wallet_id: uuid.UUID,
    q_value_threshold: Decimal,
    min_observations: int,
) -> list[DirectionalEdgeWithSignificance]:
    """Wallets that lead ``follower_wallet_id`` more often than base-rate
    chance would predict, at the given FDR-controlled significance
    threshold -- sorted by effect size descending (strongest excess
    frequency first). An observational ranking, never a causal claim."""
    candidates = [
        e
        for e in edges
        if e.edge.follower_wallet_id == follower_wallet_id
        and e.q_value <= q_value_threshold
        and e.edge.observation_count >= min_observations
        and e.edge.lift is not None
        and e.edge.lift > 1
    ]
    return sorted(
        candidates,
        key=lambda e: (
            e.edge.effect_size if e.edge.effect_size is not None else Decimal("-Infinity")
        ),
        reverse=True,
    )
