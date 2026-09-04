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
from argus.domain.prospective_events import ProspectiveEvent
from argus.domain.wallet_specialist_scores import WalletSpecialistScore
from argus.graph.loaders import load_wallet_token_entries
from argus.synthetic.matching import TriggerEvent

LEADER_ENTRY_AT_REFERENCE_KEY = "leader_entry_at"
"""R2-03: the key a confirmed-entry ``TriggerEvent.reference`` carries the
LEADER's own real entry time under -- distinct from ``TriggerEvent.at``
(the follower's confirmation time, correct for trade SEQUENCING) because
the leader's own Phase 5 executable-return evidence
(``WalletOpportunity.first_seen_at``) is keyed to when the LEADER's own
buy was first seen, never to when a follower later confirmed it."""


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


def filter_entries_by_decision_time_discovery_specialist(
    entries: list[TriggerEvent], discovery_wallet_ids_by_time: dict[datetime, set[uuid.UUID]]
) -> list[TriggerEvent]:
    """Strategy B's own entries: Strategy A's population, restricted to
    wallets that were discovery specialists AS OF that entry's own
    ``at`` (FSR-08) -- never a single set computed once at the final
    run cutoff."""
    return [
        e
        for e in entries
        if e.wallet_id is not None and e.wallet_id in discovery_wallet_ids_by_time.get(e.at, set())
    ]


def filter_exits_by_decision_time_exit_specialist(
    exits: list[TriggerEvent],
    exit_specialist_scores_by_time: dict[datetime, dict[uuid.UUID, Decimal | None]],
    *,
    min_exit_specialist_score: Decimal,
) -> list[TriggerEvent]:
    """Strategy D's own exits: any qualifying exit-specialist's own sell,
    not tied to the original leader, qualified using that EXIT's own
    ``at`` (FSR-08) -- never the final run cutoff."""
    result: list[TriggerEvent] = []
    for e in exits:
        if e.wallet_id is None:
            continue
        score = exit_specialist_scores_by_time.get(e.at, {}).get(e.wallet_id)
        if score is not None and score >= min_exit_specialist_score:
            result.append(e)
    return result


async def load_specialist_scores_as_of(
    session: AsyncSession, *, decision_time: datetime, algorithm_version: str, config_hash: str
) -> list[WalletSpecialistScore]:
    """FSR-08: every wallet's Phase 9 specialist classification exactly
    AS OF ``decision_time`` -- callers use this per DISTINCT decision
    time actually needed (never the final run cutoff applied uniformly),
    after ensuring Phase 9 has itself been computed at that same cutoff
    (see ``argus.synthetic.service``'s own per-decision-time cascade)."""
    rows = (
        (
            await session.execute(
                select(WalletSpecialistScore).where(
                    WalletSpecialistScore.as_of == decision_time,
                    WalletSpecialistScore.algorithm_version == algorithm_version,
                    WalletSpecialistScore.config_hash == config_hash,
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def load_confirmed_entries(
    session: AsyncSession, *, cutoff: datetime, confirmation_algorithm_version: str
) -> list[TriggerEvent]:
    """Strategies C/D's own RAW candidate entries (every leader's buy that
    was independently CONFIRMED by a follower, Phase 8's own
    ``follower_entered_at``), before discovery-specialist filtering --
    FSR-08 requires that filtering use each entry's own decision-time
    state, so it is applied by the caller (``argus.synthetic.service``),
    never pre-filtered here by a single run-wide specialist set."""
    rows = (
        await session.execute(
            select(
                ExpectedConfirmationEvent,
                DirectionalEdge.leader_wallet_id,
                ProspectiveEvent.first_seen_at,
            )
            .join(
                DirectionalEdge,
                ExpectedConfirmationEvent.directional_edge_id == DirectionalEdge.edge_id,
            )
            .join(
                ProspectiveEvent,
                ExpectedConfirmationEvent.leader_prospective_event_id
                == ProspectiveEvent.prospective_event_id,
            )
            .where(
                ExpectedConfirmationEvent.as_of == cutoff,
                ExpectedConfirmationEvent.algorithm_version == confirmation_algorithm_version,
                ExpectedConfirmationEvent.outcome != "ABSENT",
            )
        )
    ).all()
    entries: list[TriggerEvent] = []
    for confirmation, leader_wallet_id, leader_first_seen_at in rows:
        if confirmation.follower_entered_at is None:
            continue
        entries.append(
            TriggerEvent(
                token_id=confirmation.token_id,
                wallet_id=leader_wallet_id,
                # Trade SEQUENCING uses the follower's own confirmation
                # time -- Strategy C/D's trade is not "entered" until a
                # follower independently confirms it.
                at=confirmation.follower_entered_at,
                reference={
                    "type": "confirmation_event",
                    "id": str(confirmation.expected_confirmation_event_id),
                    # R2-03: the LEADER's own real entry time, for
                    # executable-return opportunity lookup -- see
                    # LEADER_ENTRY_AT_REFERENCE_KEY's own docstring. Using
                    # ``at`` (the follower's confirmation time) for that
                    # lookup instead is the "confirmation-entry trap":
                    # it almost never matches any real WalletOpportunity,
                    # silently forcing Strategy C/D to FAILURE_NO_
                    # EXECUTABLE_EVIDENCE regardless of real evidence.
                    LEADER_ENTRY_AT_REFERENCE_KEY: leader_first_seen_at.isoformat(),
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
