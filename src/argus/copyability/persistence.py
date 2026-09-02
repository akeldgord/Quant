"""P5-09: append-only, idempotent persistence for Phase 5 snapshots.

A rerun over byte-identical evidence at the same ``as_of``/algorithm
version always reuses the existing row (never a duplicate, never an
overwrite); a changed evidence set or algorithm/config version always
produces a new row. Concurrent inserts racing for the same identity are
resolved by the database's own unique constraint -- the loser re-selects
the winner's row rather than raising, so two callers computing the same
snapshot at once never both succeed with two different rows.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from argus.domain.opportunity_readiness_snapshots import OpportunityReadinessSnapshot
from argus.domain.wallet_copyability_snapshots import WalletCopyabilitySnapshot


async def get_or_create_wallet_copyability_snapshot(
    session: AsyncSession,
    *,
    wallet_id: uuid.UUID,
    as_of: datetime,
    algorithm_version: str,
    evidence_manifest_digest: str,
    build_row: Callable[[], WalletCopyabilitySnapshot],
) -> tuple[WalletCopyabilitySnapshot, bool]:
    """Returns ``(row, created)``. ``build_row`` is called only if no row
    with this exact identity already exists; it must construct (but not
    add/flush) a fresh :class:`WalletCopyabilitySnapshot`."""
    existing = (
        await session.execute(
            select(WalletCopyabilitySnapshot).where(
                WalletCopyabilitySnapshot.wallet_id == wallet_id,
                WalletCopyabilitySnapshot.as_of == as_of,
                WalletCopyabilitySnapshot.algorithm_version == algorithm_version,
                WalletCopyabilitySnapshot.evidence_manifest_digest == evidence_manifest_digest,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    row = build_row()
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing = (
            await session.execute(
                select(WalletCopyabilitySnapshot).where(
                    WalletCopyabilitySnapshot.wallet_id == wallet_id,
                    WalletCopyabilitySnapshot.as_of == as_of,
                    WalletCopyabilitySnapshot.algorithm_version == algorithm_version,
                    WalletCopyabilitySnapshot.evidence_manifest_digest == evidence_manifest_digest,
                )
            )
        ).scalar_one()
        return existing, False
    return row, True


async def get_or_create_opportunity_readiness_snapshot(
    session: AsyncSession,
    *,
    prospective_event_id: uuid.UUID,
    as_of: datetime,
    algorithm_version: str,
    evidence_manifest_digest: str,
    build_row: Callable[[], OpportunityReadinessSnapshot],
) -> tuple[OpportunityReadinessSnapshot, bool]:
    existing = (
        await session.execute(
            select(OpportunityReadinessSnapshot).where(
                OpportunityReadinessSnapshot.prospective_event_id == prospective_event_id,
                OpportunityReadinessSnapshot.as_of == as_of,
                OpportunityReadinessSnapshot.algorithm_version == algorithm_version,
                OpportunityReadinessSnapshot.evidence_manifest_digest == evidence_manifest_digest,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    row = build_row()
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing = (
            await session.execute(
                select(OpportunityReadinessSnapshot).where(
                    OpportunityReadinessSnapshot.prospective_event_id == prospective_event_id,
                    OpportunityReadinessSnapshot.as_of == as_of,
                    OpportunityReadinessSnapshot.algorithm_version == algorithm_version,
                    OpportunityReadinessSnapshot.evidence_manifest_digest
                    == evidence_manifest_digest,
                )
            )
        ).scalar_one()
        return existing, False
    return row, True
