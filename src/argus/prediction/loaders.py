"""argus.prediction.loaders -- MASTER_SPEC.md Phase 11 (PREDICT INFORMED
ORDER FLOW) production data loaders: turns Phase 7's own tracked-wallet
entry population, Phase 3's wallet-tier history, wallet qualification
score snapshots, and Phase 9's discovery-specialist scores into the typed
inputs ``argus.prediction.labels``/``features`` consume.

Extends the point-in-time discipline every phase since Phase 5 applies
(``argus.copyability.identity.known_by_cutoff``) to wallet-tier
transitions and wallet-score snapshots: a row is only "known" at a given
moment if it was both effective and recorded by then -- a transition or
score recorded after the fact but describing an earlier moment must never
leak into a label or feature computed as of that earlier moment. This is
what makes ``tier_at_entry`` genuinely the wallet's tier AT ITS OWN ENTRY
TIME, never its later (or current) tier.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from argus.copyability.identity import known_by_cutoff
from argus.counterfactual.buckets import liquidity_bucket, market_cap_bucket, token_age_bucket
from argus.counterfactual.loaders import load_token_market_snapshot_at_or_before
from argus.counterfactual.matching import compute_forward_return
from argus.domain.tokens import Token
from argus.domain.wallet_score_snapshots import WalletScoreSnapshot
from argus.domain.wallet_specialist_scores import WalletSpecialistScore
from argus.domain.wallet_tier_history import WalletTierTransition
from argus.graph.loaders import load_wallet_token_entries
from argus.prediction.features import RawFeatures
from argus.prediction.labels import TieredEntry


async def load_wallet_tier_transitions(
    session: AsyncSession, *, wallet_ids: set[uuid.UUID]
) -> dict[uuid.UUID, list[WalletTierTransition]]:
    if not wallet_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(WalletTierTransition).where(WalletTierTransition.wallet_id.in_(wallet_ids))
            )
        )
        .scalars()
        .all()
    )
    by_wallet: dict[uuid.UUID, list[WalletTierTransition]] = {}
    for row in rows:
        by_wallet.setdefault(row.wallet_id, []).append(row)
    for transitions in by_wallet.values():
        transitions.sort(key=lambda t: t.transitioned_at)
    return by_wallet


def tier_at(transitions: list[WalletTierTransition], *, at: datetime) -> str | None:
    """The tier a wallet held at moment ``at``, from an already-loaded,
    ``transitioned_at``-sorted transition list -- the latest transition
    both effective and recorded by ``at``, or ``None`` if none yet."""
    known: str | None = None
    known_transitioned_at: datetime | None = None
    for transition in transitions:
        if not known_by_cutoff(
            created_at=transition.created_at, effective_at=transition.transitioned_at, cutoff=at
        ):
            continue
        if known_transitioned_at is None or transition.transitioned_at >= known_transitioned_at:
            known = transition.to_tier
            known_transitioned_at = transition.transitioned_at
    return known


async def load_tiered_entries(session: AsyncSession, *, cutoff: datetime) -> list[TieredEntry]:
    """Every tracked-wallet token entry known by ``cutoff`` (Phase 7's own
    population), each annotated with the wallet's own tier AT ITS OWN
    ENTRY TIME -- never the wallet's current/latest tier, which would leak
    a wallet's LATER promotion into an earlier observation's label."""
    entries = await load_wallet_token_entries(session, cutoff=cutoff)
    wallet_ids = {e.wallet_id for e in entries}
    transitions_by_wallet = await load_wallet_tier_transitions(session, wallet_ids=wallet_ids)
    return [
        TieredEntry(
            wallet_id=e.wallet_id,
            token_id=e.token_id,
            entered_at=e.entered_at,
            source_id=e.source_id,
            tier_at_entry=tier_at(transitions_by_wallet.get(e.wallet_id, []), at=e.entered_at),
        )
        for e in entries
    ]


async def load_wallet_fingerprints(
    session: AsyncSession, *, wallet_ids: set[uuid.UUID]
) -> dict[uuid.UUID, list[WalletScoreSnapshot]]:
    if not wallet_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(WalletScoreSnapshot).where(WalletScoreSnapshot.wallet_id.in_(wallet_ids))
            )
        )
        .scalars()
        .all()
    )
    by_wallet: dict[uuid.UUID, list[WalletScoreSnapshot]] = {}
    for row in rows:
        by_wallet.setdefault(row.wallet_id, []).append(row)
    for snapshots in by_wallet.values():
        snapshots.sort(key=lambda s: s.as_of)
    return by_wallet


def wallet_fingerprint_at(
    snapshots: list[WalletScoreSnapshot], *, at: datetime
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """(selection_alpha, consistency, forward_information) from this
    wallet's own latest Phase 3 ``component_values`` known by ``at`` --
    the same ``known_by_cutoff(as_of, created_at)`` pattern
    ``argus.counterfactual.loaders.load_latest_exit_skill`` applies to the
    same table."""
    latest: WalletScoreSnapshot | None = None
    for snapshot in snapshots:
        if not known_by_cutoff(
            created_at=snapshot.created_at, effective_at=snapshot.as_of, cutoff=at
        ):
            continue
        if latest is None or snapshot.as_of >= latest.as_of:
            latest = snapshot
    if latest is None:
        return None, None, None

    def _get(key: str) -> Decimal | None:
        value = latest.component_values.get(key)
        return Decimal(str(value)) if value is not None else None

    return _get("selection_alpha"), _get("consistency"), _get("forward_information")


async def load_discovery_effect_size_by_wallet(
    session: AsyncSession, *, cutoff: datetime, algorithm_version: str, config_hash: str
) -> dict[uuid.UUID, Decimal]:
    """Phase 9's own already-computed ``discovery_specialist_score`` per
    wallet, AS OF ``cutoff`` -- reused unchanged, never recomputed. FSR-09:
    callers must invoke this once per DISTINCT observation decision time
    actually needed (never once at the final run cutoff, reused backward
    for every observation) -- the same per-decision-time pattern FSR-08
    established for ``argus.synthetic.service``."""
    rows = (
        (
            await session.execute(
                select(WalletSpecialistScore).where(
                    WalletSpecialistScore.as_of == cutoff,
                    WalletSpecialistScore.algorithm_version == algorithm_version,
                    WalletSpecialistScore.config_hash == config_hash,
                )
            )
        )
        .scalars()
        .all()
    )
    return {
        row.wallet_id: row.discovery_specialist_score
        for row in rows
        if row.discovery_specialist_score is not None
    }


def _snapshot_price_at_or_before(
    snapshot, *, target: datetime, max_staleness_seconds: float
) -> Decimal | None:
    """FSR-09: honors the same ``max_staleness_seconds`` freshness bound
    the market_cap/liquidity buckets already apply, but NEVER looks past
    ``target`` -- a nearest-snapshot lookup (before OR after) is forbidden
    here since a closer post-observation price would leak a future price
    as though it were known at ``target``."""
    if snapshot is None or snapshot.price_usd is None:
        return None
    if (target - snapshot.observed_at).total_seconds() > max_staleness_seconds:
        return None
    return snapshot.price_usd


async def compute_raw_features(
    session: AsyncSession,
    *,
    wallet_id: uuid.UUID,
    token_id: uuid.UUID,
    entered_at: datetime,
    token_by_id: dict[uuid.UUID, Token],
    fingerprints_by_wallet: dict[uuid.UUID, list[WalletScoreSnapshot]],
    discovery_effect_size_by_wallet: dict[uuid.UUID, Decimal],
    max_staleness_seconds: float,
    momentum_window: timedelta,
) -> RawFeatures:
    """``discovery_effect_size_by_wallet`` must already be the map for
    THIS OBSERVATION's own ``entered_at`` decision time (FSR-09) -- the
    caller (``argus.prediction.service``) is responsible for selecting the
    correct per-decision-time slice, never a single map reused across
    every observation's own entry time."""
    token = token_by_id.get(token_id)
    market_cap_b: str | None = None
    liquidity_b: str | None = None
    age_b: str | None = None
    momentum_pct: Decimal | None = None

    if token is not None:
        snapshot = await load_token_market_snapshot_at_or_before(
            session, token_id=token_id, at=entered_at
        )
        if (
            snapshot is not None
            and (entered_at - snapshot.observed_at).total_seconds() <= max_staleness_seconds
        ):
            if snapshot.market_cap_usd is not None:
                market_cap_b = market_cap_bucket(snapshot.market_cap_usd)
            if snapshot.liquidity_usd is not None:
                liquidity_b = liquidity_bucket(snapshot.liquidity_usd)

        age = entered_at - token.first_observed_at
        if age >= timedelta(0):
            age_b = token_age_bucket(age)

        # FSR-09: both price points are the latest snapshot AT OR BEFORE
        # their own respective target time -- never the "nearest" snapshot
        # (which could be strictly after ``entered_at`` itself).
        entry_price_snapshot = await load_token_market_snapshot_at_or_before(
            session, token_id=token_id, at=entered_at
        )
        entry_price = _snapshot_price_at_or_before(
            entry_price_snapshot, target=entered_at, max_staleness_seconds=max_staleness_seconds
        )
        prior_target = entered_at - momentum_window
        prior_price_snapshot = await load_token_market_snapshot_at_or_before(
            session, token_id=token_id, at=prior_target
        )
        prior_price = _snapshot_price_at_or_before(
            prior_price_snapshot, target=prior_target, max_staleness_seconds=max_staleness_seconds
        )
        if entry_price is not None and prior_price is not None:
            momentum_pct = compute_forward_return(prior_price, entry_price)

    selection_alpha, consistency, forward_information = wallet_fingerprint_at(
        fingerprints_by_wallet.get(wallet_id, []), at=entered_at
    )

    return RawFeatures(
        token_market_cap_bucket=market_cap_b,
        token_liquidity_bucket=liquidity_b,
        token_age_bucket=age_b,
        token_momentum_pct=momentum_pct,
        wallet_selection_alpha=selection_alpha,
        wallet_consistency=consistency,
        wallet_forward_information=forward_information,
        wallet_discovery_effect_size=discovery_effect_size_by_wallet.get(wallet_id),
    )
