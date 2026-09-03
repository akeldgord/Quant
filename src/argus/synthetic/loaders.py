"""argus.synthetic.loaders -- MASTER_SPEC.md Phase 10 (SYNTHETIC
SUPER-WALLET) production data loaders: turns already-persisted Phase 4/
7/8/9 evidence into the typed ``TriggerEvent`` entry/exit populations
each of the five strategies (A-E) is built from. No new signal-detection
logic lives here -- every trigger is a direct read of evidence a prior
phase already computed and persisted.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from argus.counterfactual.loaders import load_wallet_token_exits
from argus.domain.convergence_events import ConvergenceEvent
from argus.domain.directional_edges import DirectionalEdge
from argus.domain.exit_convergence_events import ExitConvergenceEvent
from argus.domain.expected_confirmation_events import ExpectedConfirmationEvent
from argus.domain.wallet_specialist_scores import WalletSpecialistScore
from argus.graph.loaders import load_wallet_token_entries
from argus.synthetic.matching import TriggerEvent


async def load_source_entries(session: AsyncSession, *, cutoff: datetime) -> list[TriggerEvent]:
    """Strategy A's own entries: any tracked wallet's real buy."""
    entries = await load_wallet_token_entries(session, cutoff=cutoff)
    return [
        TriggerEvent(
            token_id=e.token_id,
            wallet_id=e.wallet_id,
            at=e.entered_at,
            reference={"type": "prospective_event", "id": str(e.source_id)},
        )
        for e in entries
    ]


async def load_source_exits(session: AsyncSession, *, cutoff: datetime) -> list[TriggerEvent]:
    """Strategies A/B/C's own "source exit": any tracked wallet's own sell."""
    exits = await load_wallet_token_exits(session, cutoff=cutoff)
    return [
        TriggerEvent(
            token_id=e.token_id,
            wallet_id=e.wallet_id,
            at=e.entered_at,
            reference={"type": "swap", "id": str(e.source_id)},
        )
        for e in exits
    ]


async def load_discovery_specialist_wallet_ids(
    session: AsyncSession, *, cutoff: datetime, algorithm_version: str, config_hash: str
) -> set[uuid.UUID]:
    rows = (
        (
            await session.execute(
                select(WalletSpecialistScore.wallet_id).where(
                    WalletSpecialistScore.as_of == cutoff,
                    WalletSpecialistScore.algorithm_version == algorithm_version,
                    WalletSpecialistScore.config_hash == config_hash,
                    WalletSpecialistScore.dominant_specialty == "DISCOVERY",
                )
            )
        )
        .scalars()
        .all()
    )
    return set(rows)


async def load_exit_specialist_wallet_ids(
    session: AsyncSession,
    *,
    cutoff: datetime,
    algorithm_version: str,
    config_hash: str,
    min_exit_specialist_score: Decimal,
) -> set[uuid.UUID]:
    rows = (
        (
            await session.execute(
                select(WalletSpecialistScore.wallet_id).where(
                    WalletSpecialistScore.as_of == cutoff,
                    WalletSpecialistScore.algorithm_version == algorithm_version,
                    WalletSpecialistScore.config_hash == config_hash,
                    WalletSpecialistScore.exit_specialist_score.is_not(None),
                    WalletSpecialistScore.exit_specialist_score >= min_exit_specialist_score,
                )
            )
        )
        .scalars()
        .all()
    )
    return set(rows)


def filter_entries_by_wallet(
    entries: list[TriggerEvent], wallet_ids: set[uuid.UUID]
) -> list[TriggerEvent]:
    """Strategy B's own entries: Strategy A's population, restricted to
    discovery-specialist wallets."""
    return [e for e in entries if e.wallet_id is not None and e.wallet_id in wallet_ids]


def filter_exits_by_wallet(
    exits: list[TriggerEvent], wallet_ids: set[uuid.UUID]
) -> list[TriggerEvent]:
    """Strategy D's own exits: any qualifying exit-specialist's own sell,
    not tied to the original leader."""
    return [e for e in exits if e.wallet_id is not None and e.wallet_id in wallet_ids]


async def load_confirmed_discovery_entries(
    session: AsyncSession,
    *,
    cutoff: datetime,
    discovery_wallet_ids: set[uuid.UUID],
    confirmation_algorithm_version: str,
) -> list[TriggerEvent]:
    """Strategies C/D's own entries: a discovery specialist's buy, but the
    ENTRY fires at the moment a follower CONFIRMED it (Phase 8's own
    ``follower_entered_at``), not at the original leader's own entry
    time -- entering only once independent confirmation exists is the
    entire point of these two strategies (section 64's own R -> A ->
    "increase exposure if validated" pipeline)."""
    if not discovery_wallet_ids:
        return []
    rows = (
        await session.execute(
            select(ExpectedConfirmationEvent, DirectionalEdge.leader_wallet_id)
            .join(
                DirectionalEdge,
                ExpectedConfirmationEvent.directional_edge_id == DirectionalEdge.edge_id,
            )
            .where(
                ExpectedConfirmationEvent.as_of == cutoff,
                ExpectedConfirmationEvent.algorithm_version == confirmation_algorithm_version,
                ExpectedConfirmationEvent.outcome != "ABSENT",
                DirectionalEdge.leader_wallet_id.in_(discovery_wallet_ids),
            )
        )
    ).all()
    entries: list[TriggerEvent] = []
    for confirmation, leader_wallet_id in rows:
        if confirmation.follower_entered_at is None:
            continue
        entries.append(
            TriggerEvent(
                token_id=confirmation.token_id,
                wallet_id=leader_wallet_id,
                at=confirmation.follower_entered_at,
                reference={
                    "type": "confirmation_event",
                    "id": str(confirmation.expected_confirmation_event_id),
                },
            )
        )
    return entries


async def load_high_convergence_entries(
    session: AsyncSession,
    *,
    cutoff: datetime,
    algorithm_version: str,
    config_hash: str,
    surprisal_threshold: Decimal,
) -> list[TriggerEvent]:
    """Strategy E's own entries: a token whose convergence episode was
    unusually surprising. Anchored at ``window_end`` (not ``window_start``)
    -- the episode's full evidence, and therefore its surprisal, is not
    actually known until the window closes; anchoring at ``window_start``
    would be look-ahead bias."""
    rows = (
        (
            await session.execute(
                select(ConvergenceEvent).where(
                    ConvergenceEvent.as_of == cutoff,
                    ConvergenceEvent.algorithm_version == algorithm_version,
                    ConvergenceEvent.config_hash == config_hash,
                    ConvergenceEvent.surprisal >= surprisal_threshold,
                    ConvergenceEvent.calibration_confidence != "INSUFFICIENT_SAMPLE",
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        TriggerEvent(
            token_id=r.token_id,
            wallet_id=None,
            at=r.window_end,
            reference={"type": "convergence_event", "id": str(r.convergence_event_id)},
        )
        for r in rows
    ]


async def load_exit_convergence_exits(
    session: AsyncSession, *, cutoff: datetime, algorithm_version: str, config_hash: str
) -> list[TriggerEvent]:
    """Strategy E's own exits: an exit-convergence episode for that same
    token (section 63's own EXIT_CONVERGENCE). Anchored at ``window_end``
    for the same point-in-time reason as the entry side."""
    rows = (
        (
            await session.execute(
                select(ExitConvergenceEvent).where(
                    ExitConvergenceEvent.as_of == cutoff,
                    ExitConvergenceEvent.algorithm_version == algorithm_version,
                    ExitConvergenceEvent.config_hash == config_hash,
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        TriggerEvent(
            token_id=r.token_id,
            wallet_id=None,
            at=r.window_end,
            reference={"type": "exit_convergence_event", "id": str(r.exit_convergence_event_id)},
        )
        for r in rows
    ]
