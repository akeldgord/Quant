"""P5-09: append-only, idempotent persistence for Phase 5 snapshots.

A rerun over byte-identical evidence at the same ``as_of``/algorithm
version/config always reuses the existing row (never a duplicate, never an
overwrite); a changed evidence set, algorithm version, or config always
produces a new row (F5-05 remediation: ``config_hash`` is part of each
table's own unique-identity constraint -- see
``argus.domain.wallet_copyability_snapshots``/
``opportunity_readiness_snapshots``).

Concurrent inserts racing for the same identity are resolved with
``INSERT ... ON CONFLICT DO NOTHING`` (F5-05 remediation): the loser's
insert is a silent no-op and it re-selects the winner's row within the
SAME still-active transaction. The prior approach -- catching
``IntegrityError`` and calling ``session.rollback()`` -- is never safe here:
this function runs inside the caller's own still-active ``session.begin()``
block (see ``argus.copyability.service``'s ``compute_and_persist_*``
callers), and rolling back mid-transaction there raises
``InvalidRequestError`` rather than recovering.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from argus.domain.opportunity_readiness_snapshots import OpportunityReadinessSnapshot
from argus.domain.wallet_copyability_snapshots import WalletCopyabilitySnapshot


def _row_values(row: object, table) -> dict:
    return {column.name: getattr(row, column.name) for column in table.columns}


async def get_or_create_wallet_copyability_snapshot(
    session: AsyncSession,
    *,
    wallet_id: uuid.UUID,
    as_of: datetime,
    algorithm_version: str,
    evidence_manifest_digest: str,
    config_hash: str,
    build_row: Callable[[], WalletCopyabilitySnapshot],
) -> tuple[WalletCopyabilitySnapshot, bool]:
    """Returns ``(row, created)``. ``build_row`` is called only if no row
    with this exact identity already exists; it must construct (but not
    add/flush) a fresh, fully-populated :class:`WalletCopyabilitySnapshot`
    (every column set -- see ``argus.copyability.service.build_snapshot_row``)."""
    identity = (
        WalletCopyabilitySnapshot.wallet_id == wallet_id,
        WalletCopyabilitySnapshot.as_of == as_of,
        WalletCopyabilitySnapshot.algorithm_version == algorithm_version,
        WalletCopyabilitySnapshot.evidence_manifest_digest == evidence_manifest_digest,
        WalletCopyabilitySnapshot.config_hash == config_hash,
    )
    existing = (
        await session.execute(select(WalletCopyabilitySnapshot).where(*identity))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    row = build_row()
    stmt = (
        pg_insert(WalletCopyabilitySnapshot)
        .values(**_row_values(row, WalletCopyabilitySnapshot.__table__))
        .on_conflict_do_nothing(constraint="uq_wallet_copyability_identity")
        .returning(WalletCopyabilitySnapshot.snapshot_id)
    )
    inserted_id = (await session.execute(stmt)).scalar_one_or_none()
    if inserted_id is not None:
        return row, True

    # Lost the race -- another concurrent caller already committed the
    # winning row for this exact identity; re-select it within this SAME
    # still-active transaction rather than rolling back.
    existing = (
        await session.execute(select(WalletCopyabilitySnapshot).where(*identity))
    ).scalar_one()
    return existing, False


async def get_or_create_opportunity_readiness_snapshot(
    session: AsyncSession,
    *,
    prospective_event_id: uuid.UUID,
    as_of: datetime,
    algorithm_version: str,
    evidence_manifest_digest: str,
    config_hash: str,
    build_row: Callable[[], OpportunityReadinessSnapshot],
) -> tuple[OpportunityReadinessSnapshot, bool]:
    identity = (
        OpportunityReadinessSnapshot.prospective_event_id == prospective_event_id,
        OpportunityReadinessSnapshot.as_of == as_of,
        OpportunityReadinessSnapshot.algorithm_version == algorithm_version,
        OpportunityReadinessSnapshot.evidence_manifest_digest == evidence_manifest_digest,
        OpportunityReadinessSnapshot.config_hash == config_hash,
    )
    existing = (
        await session.execute(select(OpportunityReadinessSnapshot).where(*identity))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    row = build_row()
    stmt = (
        pg_insert(OpportunityReadinessSnapshot)
        .values(**_row_values(row, OpportunityReadinessSnapshot.__table__))
        .on_conflict_do_nothing(constraint="uq_opportunity_readiness_identity")
        .returning(OpportunityReadinessSnapshot.snapshot_id)
    )
    inserted_id = (await session.execute(stmt)).scalar_one_or_none()
    if inserted_id is not None:
        return row, True

    existing = (
        await session.execute(select(OpportunityReadinessSnapshot).where(*identity))
    ).scalar_one()
    return existing, False
