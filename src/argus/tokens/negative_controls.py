"""Negative-control archaeology schema round-trip (MASTER_SPEC.md section
31 NEGATIVE-CONTROL ARCHAEOLOGY; Phase 2 build item 13).

Schema and deterministic round-trip only -- this module never computes or
derives a score, and never marks a control token a winner or vice versa
(required test P2-T9). A later phase decides HOW to select a matching
control token and what the matching dimensions actually mean for
qualification; this module only persists and retrieves what that later
phase (or a human researcher) asserts.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from argus.domain.token_negative_controls import TokenNegativeControl

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclasses.dataclass(frozen=True, slots=True)
class NegativeControlDraft:
    winner_token_id: uuid.UUID
    control_token_id: uuid.UUID
    method_version: str
    launch_period_match: bool | None = None
    venue_match: bool | None = None
    early_liquidity_delta_pct: Decimal | None = None
    early_market_cap_delta_pct: Decimal | None = None
    early_tx_activity_delta_pct: Decimal | None = None
    evidence_reference: str | None = None


async def record_negative_control(
    session: AsyncSession, draft: NegativeControlDraft, *, now: datetime
) -> uuid.UUID:
    """Idempotent on ``(winner_token_id, control_token_id,
    method_version)`` -- a replayed match never duplicates."""
    control_id = uuid.uuid4()
    stmt = (
        pg_insert(TokenNegativeControl)
        .values(
            control_id=control_id,
            winner_token_id=draft.winner_token_id,
            control_token_id=draft.control_token_id,
            method_version=draft.method_version,
            launch_period_match=draft.launch_period_match,
            venue_match=draft.venue_match,
            early_liquidity_delta_pct=draft.early_liquidity_delta_pct,
            early_market_cap_delta_pct=draft.early_market_cap_delta_pct,
            early_tx_activity_delta_pct=draft.early_tx_activity_delta_pct,
            evidence_reference=draft.evidence_reference,
            created_at=now,
        )
        .on_conflict_do_nothing(
            index_elements=["winner_token_id", "control_token_id", "method_version"]
        )
        .returning(TokenNegativeControl.control_id)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is not None:
        await session.flush()
        return uuid.UUID(str(row))

    existing = (
        await session.execute(
            select(TokenNegativeControl.control_id).where(
                TokenNegativeControl.winner_token_id == draft.winner_token_id,
                TokenNegativeControl.control_token_id == draft.control_token_id,
                TokenNegativeControl.method_version == draft.method_version,
            )
        )
    ).scalar_one()
    return uuid.UUID(str(existing))


async def controls_for_winner(
    session: AsyncSession, *, winner_token_id: uuid.UUID
) -> list[TokenNegativeControl]:
    return list(
        (
            await session.execute(
                select(TokenNegativeControl).where(
                    TokenNegativeControl.winner_token_id == winner_token_id
                )
            )
        )
        .scalars()
        .all()
    )
