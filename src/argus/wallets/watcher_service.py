"""Persistence orchestration for the prospective winner watcher
(MASTER_SPEC.md Phase 2 build items 9-11; required-implementation item 6).

``evaluate_token`` is the single entry point: load a token's current
``token_market_snapshots`` history, compute any genuinely new milestone
crossings (``argus.wallets.winner_watcher``), and persist each as one
idempotent ``token_winner_milestones`` row plus one idempotent
``archaeology_triggers`` row (``PROSPECTIVE_WINNER``). Both inserts use
``ON CONFLICT DO NOTHING`` against the tables' own unique constraints, so
calling this repeatedly -- replayed observations, duplicate deliveries,
concurrent workers evaluating the same token -- can never create a
duplicate milestone or a duplicate trigger (required test P2-T7).

This module creates no trade intent, order, quote, or execution side
effect. "Automatic archaeology trigger" here means only: a row is
inserted recording that ARGUS should run (or queue) archaeology research
for this token -- turning that row into an actual
``argus.wallets.archaeology`` run is a separate, explicit step (the CLI's
``argus discover run-triggers`` command, or a future scheduler), never
performed implicitly by this function.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from argus.domain.archaeology_triggers import TRIGGER_TYPE_PROSPECTIVE_WINNER, ArchaeologyTrigger
from argus.domain.token_market_snapshots import TokenMarketSnapshot
from argus.domain.token_winner_milestones import TokenWinnerMilestone
from argus.wallets.winner_watcher import (
    ALGORITHM_VERSION,
    BUILD_HASH,
    WINNER_DEFINITION_VERSION,
    MilestoneCrossing,
    SnapshotView,
    compute_new_milestone_crossings,
)


@dataclasses.dataclass(frozen=True, slots=True)
class WatcherEvaluation:
    crossing: MilestoneCrossing
    milestone_id: uuid.UUID
    trigger_id: uuid.UUID
    milestone_newly_recorded: bool
    trigger_newly_recorded: bool


async def evaluate_token(
    session: AsyncSession,
    *,
    token_id: uuid.UUID,
    now: datetime,
    winner_definition_version: str = WINNER_DEFINITION_VERSION,
) -> list[WatcherEvaluation]:
    already_recorded = frozenset(
        (
            await session.execute(
                select(TokenWinnerMilestone.category).where(
                    TokenWinnerMilestone.token_id == token_id,
                    TokenWinnerMilestone.winner_definition_version == winner_definition_version,
                )
            )
        )
        .scalars()
        .all()
    )

    rows = (
        (
            await session.execute(
                select(TokenMarketSnapshot).where(TokenMarketSnapshot.token_id == token_id)
            )
        )
        .scalars()
        .all()
    )
    snapshots = [
        SnapshotView(
            snapshot_id=row.snapshot_id,
            observed_at=row.observed_at,
            price_usd=row.price_usd,
            liquidity_usd=row.liquidity_usd,
            market_state_confidence=row.market_state_confidence,
        )
        for row in rows
    ]

    crossings = compute_new_milestone_crossings(
        token_id=token_id,
        snapshots=snapshots,
        already_recorded_categories=already_recorded,
        winner_definition_version=winner_definition_version,
    )

    results: list[WatcherEvaluation] = []
    for crossing in crossings:
        milestone_id, milestone_new = await _insert_milestone(session, crossing, now=now)
        trigger_id, trigger_new = await _insert_prospective_trigger(
            session, token_id=token_id, milestone_id=milestone_id, crossing=crossing, now=now
        )
        results.append(
            WatcherEvaluation(
                crossing=crossing,
                milestone_id=milestone_id,
                trigger_id=trigger_id,
                milestone_newly_recorded=milestone_new,
                trigger_newly_recorded=trigger_new,
            )
        )
    return results


async def _insert_milestone(
    session: AsyncSession, crossing: MilestoneCrossing, *, now: datetime
) -> tuple[uuid.UUID, bool]:
    milestone_id = uuid.uuid4()
    stmt = (
        pg_insert(TokenWinnerMilestone)
        .values(
            milestone_id=milestone_id,
            token_id=crossing.token_id,
            category=crossing.category,
            winner_definition_version=crossing.winner_definition_version,
            baseline_timestamp=crossing.baseline_timestamp,
            baseline_price=crossing.baseline_price,
            baseline_liquidity=crossing.baseline_liquidity,
            baseline_snapshot_id=crossing.baseline_snapshot_id,
            peak_price=crossing.peak_price,
            peak_timestamp=crossing.peak_timestamp,
            peak_snapshot_id=crossing.peak_snapshot_id,
            multiple_x=crossing.multiple_x,
            crossed_at=now,
            reason_codes=crossing.reason_codes,
            algorithm_version=ALGORITHM_VERSION,
            build_hash=BUILD_HASH,
            created_at=now,
        )
        .on_conflict_do_nothing(
            index_elements=["token_id", "category", "winner_definition_version"]
        )
        .returning(TokenWinnerMilestone.milestone_id)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is not None:
        await session.flush()
        return uuid.UUID(str(row)), True

    existing = (
        await session.execute(
            select(TokenWinnerMilestone.milestone_id).where(
                TokenWinnerMilestone.token_id == crossing.token_id,
                TokenWinnerMilestone.category == crossing.category,
                TokenWinnerMilestone.winner_definition_version
                == crossing.winner_definition_version,
            )
        )
    ).scalar_one()
    return uuid.UUID(str(existing)), False


async def _insert_prospective_trigger(
    session: AsyncSession,
    *,
    token_id: uuid.UUID,
    milestone_id: uuid.UUID,
    crossing: MilestoneCrossing,
    now: datetime,
) -> tuple[uuid.UUID, bool]:
    trigger_id = uuid.uuid4()
    stmt = (
        pg_insert(ArchaeologyTrigger)
        .values(
            trigger_id=trigger_id,
            token_id=token_id,
            trigger_type=TRIGGER_TYPE_PROSPECTIVE_WINNER,
            source_milestone_id=milestone_id,
            trigger_reason=(
                f"token crossed {crossing.category} "
                f"({crossing.multiple_x}x under {crossing.winner_definition_version})"
            ),
            algorithm_version=ALGORITHM_VERSION,
            created_at=now,
            consumed_at=None,
        )
        .on_conflict_do_nothing(
            index_elements=["token_id", "source_milestone_id"],
            index_where=ArchaeologyTrigger.trigger_type == TRIGGER_TYPE_PROSPECTIVE_WINNER,
        )
        .returning(ArchaeologyTrigger.trigger_id)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is not None:
        await session.flush()
        return uuid.UUID(str(row)), True

    existing = (
        await session.execute(
            select(ArchaeologyTrigger.trigger_id).where(
                ArchaeologyTrigger.token_id == token_id,
                ArchaeologyTrigger.source_milestone_id == milestone_id,
                ArchaeologyTrigger.trigger_type == TRIGGER_TYPE_PROSPECTIVE_WINNER,
            )
        )
    ).scalar_one()
    return uuid.UUID(str(existing)), False
