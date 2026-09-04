"""argus.convergence.persistence -- MASTER_SPEC.md Phase 8 (CONVERGENCE +
NEGATIVE EVIDENCE): append-only, idempotent persistence for convergence
events and expected confirmation events. Follows the SAME
``INSERT ... ON CONFLICT DO NOTHING`` + re-select-within-transaction
pattern F5-05 established for Phase 5 snapshots and Phase 7's own graph
persistence -- a rerun over identical evidence always reuses the existing
row; a genuinely new episode/classification or a changed ``config_hash``
always produces a new row.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from argus.convergence.confirmation import ConfirmationClassification
from argus.convergence.episodes import ConvergenceEpisode
from argus.convergence.outcome_comparison import OutcomeComparisonResult
from argus.convergence.stats import OverlapSurpriseResult
from argus.domain.convergence_events import ConvergenceEvent
from argus.domain.convergence_outcome_comparisons import ConvergenceOutcomeComparison
from argus.domain.expected_confirmation_events import ExpectedConfirmationEvent


def _row_values(row: object, table) -> dict:
    return {column.name: getattr(row, column.name) for column in table.columns}


async def get_or_create_convergence_event(
    session: AsyncSession,
    *,
    episode: ConvergenceEpisode,
    estimated_independent_actors: Decimal,
    surprise: OverlapSurpriseResult,
    as_of: datetime,
    algorithm_version: str,
    config_hash: str,
    now: datetime,
) -> tuple[ConvergenceEvent, bool]:
    identity = (
        ConvergenceEvent.token_id == episode.token_id,
        ConvergenceEvent.window_start == episode.window_start,
        ConvergenceEvent.as_of == as_of,
        ConvergenceEvent.algorithm_version == algorithm_version,
        ConvergenceEvent.config_hash == config_hash,
    )
    existing = (
        await session.execute(select(ConvergenceEvent).where(*identity))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    row = ConvergenceEvent(
        convergence_event_id=uuid.uuid4(),
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
        pg_insert(ConvergenceEvent)
        .values(**_row_values(row, ConvergenceEvent.__table__))
        .on_conflict_do_nothing(constraint="uq_convergence_events_identity")
        .returning(ConvergenceEvent.convergence_event_id)
    )
    inserted_id = (await session.execute(stmt)).scalar_one_or_none()
    if inserted_id is not None:
        return row, True
    return (await session.execute(select(ConvergenceEvent).where(*identity))).scalar_one(), False


async def get_or_create_expected_confirmation_event(
    session: AsyncSession,
    *,
    directional_edge_id: uuid.UUID,
    leader_prospective_event_id: uuid.UUID,
    token_id: uuid.UUID,
    leader_wallet_id: uuid.UUID,
    follower_wallet_id: uuid.UUID,
    classification: ConfirmationClassification,
    convergence_event_id: uuid.UUID | None,
    as_of: datetime,
    algorithm_version: str,
    config_hash: str,
    now: datetime,
) -> tuple[ExpectedConfirmationEvent, bool]:
    identity = (
        ExpectedConfirmationEvent.directional_edge_id == directional_edge_id,
        ExpectedConfirmationEvent.leader_prospective_event_id == leader_prospective_event_id,
        ExpectedConfirmationEvent.as_of == as_of,
        ExpectedConfirmationEvent.algorithm_version == algorithm_version,
        ExpectedConfirmationEvent.config_hash == config_hash,
    )
    existing = (
        await session.execute(select(ExpectedConfirmationEvent).where(*identity))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    row = ExpectedConfirmationEvent(
        expected_confirmation_event_id=uuid.uuid4(),
        directional_edge_id=directional_edge_id,
        leader_prospective_event_id=leader_prospective_event_id,
        token_id=token_id,
        leader_wallet_id=leader_wallet_id,
        follower_wallet_id=follower_wallet_id,
        outcome=classification.outcome,
        follower_entered_at=classification.follower_entered_at,
        lag_seconds=classification.lag_seconds,
        expected_window_low_seconds=classification.expected_window_low_seconds,
        expected_window_high_seconds=classification.expected_window_high_seconds,
        convergence_event_id=convergence_event_id,
        as_of=as_of,
        algorithm_version=algorithm_version,
        config_hash=config_hash,
        created_at=now,
    )
    stmt = (
        pg_insert(ExpectedConfirmationEvent)
        .values(**_row_values(row, ExpectedConfirmationEvent.__table__))
        .on_conflict_do_nothing(constraint="uq_expected_confirmation_events_identity")
        .returning(ExpectedConfirmationEvent.expected_confirmation_event_id)
    )
    inserted_id = (await session.execute(stmt)).scalar_one_or_none()
    if inserted_id is not None:
        return row, True
    return (
        await session.execute(select(ExpectedConfirmationEvent).where(*identity))
    ).scalar_one(), False


async def get_or_create_convergence_outcome_comparison(
    session: AsyncSession,
    *,
    class_name: str,
    result: OutcomeComparisonResult,
    as_of: datetime,
    algorithm_version: str,
    config_hash: str,
    now: datetime,
) -> tuple[ConvergenceOutcomeComparison, bool]:
    identity = (
        ConvergenceOutcomeComparison.class_name == class_name,
        ConvergenceOutcomeComparison.as_of == as_of,
        ConvergenceOutcomeComparison.algorithm_version == algorithm_version,
        ConvergenceOutcomeComparison.config_hash == config_hash,
    )
    existing = (
        await session.execute(select(ConvergenceOutcomeComparison).where(*identity))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    executable = result.executable
    mark = result.mark
    row = ConvergenceOutcomeComparison(
        comparison_id=uuid.uuid4(),
        class_name=class_name,
        as_of=as_of,
        algorithm_version=algorithm_version,
        config_hash=config_hash,
        member_count=executable.member_count,
        eligible_count=executable.eligible_count,
        sample_count=executable.sample_count,
        mean_return_pct=executable.mean_return_pct,
        median_return_pct=executable.median_return_pct,
        win_rate=executable.win_rate,
        no_route_unsellable_missing_rate=executable.no_route_unsellable_missing_rate,
        insufficient_executable_sample=executable.insufficient_executable_sample,
        mark_sample_count=mark.sample_count,
        mark_mean_return_pct=mark.mean_return_pct,
        created_at=now,
    )
    stmt = (
        pg_insert(ConvergenceOutcomeComparison)
        .values(**_row_values(row, ConvergenceOutcomeComparison.__table__))
        .on_conflict_do_nothing(constraint="uq_convergence_outcome_comparisons_identity")
        .returning(ConvergenceOutcomeComparison.comparison_id)
    )
    inserted_id = (await session.execute(stmt)).scalar_one_or_none()
    if inserted_id is not None:
        return row, True
    return (
        await session.execute(select(ConvergenceOutcomeComparison).where(*identity))
    ).scalar_one(), False
