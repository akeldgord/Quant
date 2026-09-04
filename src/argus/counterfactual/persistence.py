"""argus.counterfactual.persistence -- MASTER_SPEC.md Phase 9: append-only,
idempotent persistence for all four Phase 9 tables. Follows the SAME
``INSERT ... ON CONFLICT DO NOTHING`` + re-select-within-transaction
pattern F5-05 established for Phase 5 snapshots and reused by Phases 7/8.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from argus.convergence.episodes import ConvergenceEpisode
from argus.convergence.stats import OverlapSurpriseResult
from argus.domain.counterfactual_alpha_estimates import CounterfactualAlphaEstimate
from argus.domain.exit_convergence_events import ExitConvergenceEvent
from argus.domain.wallet_predation_scores import WalletPredationScore
from argus.domain.wallet_specialist_scores import WalletSpecialistScore


def _row_values(row: object, table) -> dict:
    return {column.name: getattr(row, column.name) for column in table.columns}


async def get_or_create_counterfactual_alpha_estimate(
    session: AsyncSession,
    *,
    prospective_event_id: uuid.UUID,
    wallet_id: uuid.UUID,
    token_id: uuid.UUID,
    entered_at: datetime,
    horizon_seconds: int,
    wallet_token_forward_return: Decimal | None,
    matched_universe_forward_return: Decimal | None,
    residual_selection_alpha: Decimal | None,
    matched_control_count: int,
    matching_snapshot: dict,
    as_of: datetime,
    algorithm_version: str,
    config_hash: str,
    now: datetime,
) -> tuple[CounterfactualAlphaEstimate, bool]:
    identity = (
        CounterfactualAlphaEstimate.prospective_event_id == prospective_event_id,
        CounterfactualAlphaEstimate.horizon_seconds == horizon_seconds,
        CounterfactualAlphaEstimate.as_of == as_of,
        CounterfactualAlphaEstimate.algorithm_version == algorithm_version,
        CounterfactualAlphaEstimate.config_hash == config_hash,
    )
    existing = (
        await session.execute(select(CounterfactualAlphaEstimate).where(*identity))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    row = CounterfactualAlphaEstimate(
        estimate_id=uuid.uuid4(),
        prospective_event_id=prospective_event_id,
        wallet_id=wallet_id,
        token_id=token_id,
        entered_at=entered_at,
        horizon_seconds=horizon_seconds,
        wallet_token_forward_return=wallet_token_forward_return,
        matched_universe_forward_return=matched_universe_forward_return,
        residual_selection_alpha=residual_selection_alpha,
        matched_control_count=matched_control_count,
        matching_snapshot=matching_snapshot,
        as_of=as_of,
        algorithm_version=algorithm_version,
        config_hash=config_hash,
        created_at=now,
    )
    stmt = (
        pg_insert(CounterfactualAlphaEstimate)
        .values(**_row_values(row, CounterfactualAlphaEstimate.__table__))
        .on_conflict_do_nothing(constraint="uq_counterfactual_alpha_estimates_identity")
        .returning(CounterfactualAlphaEstimate.estimate_id)
    )
    inserted_id = (await session.execute(stmt)).scalar_one_or_none()
    if inserted_id is not None:
        return row, True
    return (
        await session.execute(select(CounterfactualAlphaEstimate).where(*identity))
    ).scalar_one(), False


async def get_or_create_wallet_specialist_score(
    session: AsyncSession,
    *,
    wallet_id: uuid.UUID,
    as_of: datetime,
    entry_specialist_score: Decimal | None,
    entry_specialist_sample_size: int,
    discovery_specialist_score: Decimal | None,
    discovery_specialist_sample_size: int,
    validation_specialist_score: Decimal | None,
    validation_specialist_sample_size: int,
    exit_specialist_score: Decimal | None,
    entry_percentile: Decimal | None,
    discovery_percentile: Decimal | None,
    validation_percentile: Decimal | None,
    exit_percentile: Decimal | None,
    dominant_specialty: str | None,
    algorithm_version: str,
    config_hash: str,
    now: datetime,
) -> tuple[WalletSpecialistScore, bool]:
    identity = (
        WalletSpecialistScore.wallet_id == wallet_id,
        WalletSpecialistScore.as_of == as_of,
        WalletSpecialistScore.algorithm_version == algorithm_version,
        WalletSpecialistScore.config_hash == config_hash,
    )
    existing = (
        await session.execute(select(WalletSpecialistScore).where(*identity))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    row = WalletSpecialistScore(
        score_id=uuid.uuid4(),
        wallet_id=wallet_id,
        as_of=as_of,
        entry_specialist_score=entry_specialist_score,
        entry_specialist_sample_size=entry_specialist_sample_size,
        discovery_specialist_score=discovery_specialist_score,
        discovery_specialist_sample_size=discovery_specialist_sample_size,
        validation_specialist_score=validation_specialist_score,
        validation_specialist_sample_size=validation_specialist_sample_size,
        exit_specialist_score=exit_specialist_score,
        entry_percentile=entry_percentile,
        discovery_percentile=discovery_percentile,
        validation_percentile=validation_percentile,
        exit_percentile=exit_percentile,
        dominant_specialty=dominant_specialty,
        algorithm_version=algorithm_version,
        config_hash=config_hash,
        created_at=now,
    )
    stmt = (
        pg_insert(WalletSpecialistScore)
        .values(**_row_values(row, WalletSpecialistScore.__table__))
        .on_conflict_do_nothing(constraint="uq_wallet_specialist_scores_identity")
        .returning(WalletSpecialistScore.score_id)
    )
    inserted_id = (await session.execute(stmt)).scalar_one_or_none()
    if inserted_id is not None:
        return row, True
    return (
        await session.execute(select(WalletSpecialistScore).where(*identity))
    ).scalar_one(), False


async def get_or_create_wallet_predation_score(
    session: AsyncSession,
    *,
    wallet_id: uuid.UUID,
    as_of: datetime,
    total_entries_count: int,
    entries_with_influx_count: int,
    follower_influx_mean: Decimal | None,
    exit_after_influx_count: int,
    exit_after_influx_rate: Decimal | None,
    price_impact_mean: Decimal | None,
    price_impact_incorporated: bool,
    predation_score: Decimal | None,
    algorithm_version: str,
    config_hash: str,
    now: datetime,
) -> tuple[WalletPredationScore, bool]:
    identity = (
        WalletPredationScore.wallet_id == wallet_id,
        WalletPredationScore.as_of == as_of,
        WalletPredationScore.algorithm_version == algorithm_version,
        WalletPredationScore.config_hash == config_hash,
    )
    existing = (
        await session.execute(select(WalletPredationScore).where(*identity))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    row = WalletPredationScore(
        score_id=uuid.uuid4(),
        wallet_id=wallet_id,
        as_of=as_of,
        total_entries_count=total_entries_count,
        entries_with_influx_count=entries_with_influx_count,
        follower_influx_mean=follower_influx_mean,
        exit_after_influx_count=exit_after_influx_count,
        exit_after_influx_rate=exit_after_influx_rate,
        price_impact_mean=price_impact_mean,
        price_impact_incorporated=price_impact_incorporated,
        predation_score=predation_score,
        algorithm_version=algorithm_version,
        config_hash=config_hash,
        created_at=now,
    )
    stmt = (
        pg_insert(WalletPredationScore)
        .values(**_row_values(row, WalletPredationScore.__table__))
        .on_conflict_do_nothing(constraint="uq_wallet_predation_scores_identity")
        .returning(WalletPredationScore.score_id)
    )
    inserted_id = (await session.execute(stmt)).scalar_one_or_none()
    if inserted_id is not None:
        return row, True
    return (
        await session.execute(select(WalletPredationScore).where(*identity))
    ).scalar_one(), False


async def get_or_create_exit_convergence_event(
    session: AsyncSession,
    *,
    episode: ConvergenceEpisode,
    estimated_independent_actors: Decimal,
    surprise: OverlapSurpriseResult,
    as_of: datetime,
    algorithm_version: str,
    config_hash: str,
    now: datetime,
) -> tuple[ExitConvergenceEvent, bool]:
    identity = (
        ExitConvergenceEvent.token_id == episode.token_id,
        ExitConvergenceEvent.window_start == episode.window_start,
        ExitConvergenceEvent.as_of == as_of,
        ExitConvergenceEvent.algorithm_version == algorithm_version,
        ExitConvergenceEvent.config_hash == config_hash,
    )
    existing = (
        await session.execute(select(ExitConvergenceEvent).where(*identity))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    row = ExitConvergenceEvent(
        exit_convergence_event_id=uuid.uuid4(),
        token_id=episode.token_id,
        window_start=episode.window_start,
        window_end=episode.window_end,
        as_of=as_of,
        raw_wallet_count=episode.raw_wallet_count,
        estimated_independent_actors=estimated_independent_actors,
        expected_overlap=surprise.expected_overlap,
        observed_overlap=estimated_independent_actors,
        empirical_probability=surprise.empirical_probability,
        surprisal=surprise.surprisal,
        sample_size=surprise.sample_size,
        calibration_confidence=surprise.calibration_confidence,
        algorithm_version=algorithm_version,
        config_hash=config_hash,
        created_at=now,
    )
    stmt = (
        pg_insert(ExitConvergenceEvent)
        .values(**_row_values(row, ExitConvergenceEvent.__table__))
        .on_conflict_do_nothing(constraint="uq_exit_convergence_events_identity")
        .returning(ExitConvergenceEvent.exit_convergence_event_id)
    )
    inserted_id = (await session.execute(stmt)).scalar_one_or_none()
    if inserted_id is not None:
        return row, True
    return (
        await session.execute(select(ExitConvergenceEvent).where(*identity))
    ).scalar_one(), False
