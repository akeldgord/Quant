"""argus.graph.loaders — MASTER_SPEC.md Phase 7 (ALPHA ANCESTRY) production
data loader: turns already-persisted Phase 4 ``prospective_events`` rows
(one per tracked wallet's real buy entry into a token) into the typed
``WalletTokenEntry`` inputs ``argus.graph.lead_follow`` consumes.

Applies the SAME point-in-time discipline M1 established for Phase 5
(``argus.copyability.identity.known_by_cutoff``): an entry is only
"known" as of a cutoff if it was both recorded (``created_at``) and
effective (``first_seen_at``) by that cutoff -- an entry recorded early
but describing a still-future event is never used.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from argus.copyability.identity import known_by_cutoff
from argus.copyability.loaders import (
    PRIMARY_EXECUTABLE_HORIZON,
    WalletOpportunity,
    load_contamination_firewall,
    load_wallet_opportunities,
)
from argus.domain.prospective_events import ProspectiveEvent
from argus.graph.lead_follow import LeadFollowObservation, WalletTokenEntry


async def load_wallet_token_entries(
    session: AsyncSession, *, cutoff: datetime
) -> list[WalletTokenEntry]:
    """Every tracked-wallet token entry known by ``cutoff``, across all
    tokens -- the base population :func:`argus.graph.lead_follow.
    build_lead_follow_observations` and the base-rate computation both
    draw from. A ``prospective_event`` with a ``NULL`` ``token_id`` (mint
    validation not yet resolved -- see ``argus.domain.prospective_events``)
    is excluded: an entry cannot be a token-graph observation without a
    known token."""
    rows = (
        (
            await session.execute(
                select(ProspectiveEvent).where(ProspectiveEvent.token_id.is_not(None))
            )
        )
        .scalars()
        .all()
    )
    entries: list[WalletTokenEntry] = []
    for row in rows:
        if not known_by_cutoff(
            created_at=row.created_at, effective_at=row.first_seen_at, cutoff=cutoff
        ):
            continue
        assert row.token_id is not None  # excluded by the query above
        entries.append(
            WalletTokenEntry(
                wallet_id=row.wallet_id,
                token_id=row.token_id,
                entered_at=row.first_seen_at,
                source_id=row.prospective_event_id,
            )
        )
    return entries


def compute_follower_base_rates(
    entries: list[WalletTokenEntry],
) -> dict[uuid.UUID, tuple[int, int]]:
    """For every wallet appearing in ``entries``, the (distinct tokens
    that wallet entered, distinct tokens ANY wallet entered) pair --
    the exact numerator/denominator a caller uses to compute that
    wallet's own unconditional base rate of entering a token drawn from
    this same universe. Returned as counts, never a lossy pre-divided
    float, so callers can build an exact ``Decimal`` ratio."""
    tokens_by_wallet: dict[uuid.UUID, set[uuid.UUID]] = {}
    universe: set[uuid.UUID] = set()
    for entry in entries:
        tokens_by_wallet.setdefault(entry.wallet_id, set()).add(entry.token_id)
        universe.add(entry.token_id)
    universe_size = len(universe)
    return {
        wallet_id: (len(tokens), universe_size) for wallet_id, tokens in tokens_by_wallet.items()
    }


_MISSING_NO_MATCH = "NO_5M_EXECUTABLE_PROBE_FOR_FOLLOWER_ENTRIES"
_MISSING_NO_SUCCESS = "NO_SUCCESSFUL_EXECUTABLE_RETURN_AT_5M"


@dataclass(frozen=True)
class ForwardInformationResult:
    """FSR-05: the follower's own real forward executable-return evidence
    for one (leader, follower) edge's observations -- never a fabricated
    or re-derived price series, and never silently ``None`` without a
    stated reason."""

    mean_pct: Decimal | None
    sample_count: int
    eligible_count: int
    missing_reason: str | None


async def load_forward_information_after_leader(
    session: AsyncSession,
    *,
    observations_by_pair: dict[tuple[uuid.UUID, uuid.UUID], list[LeadFollowObservation]],
    cutoff: datetime,
) -> dict[tuple[uuid.UUID, uuid.UUID], ForwardInformationResult]:
    """For every (leader, follower) pair, reuses the follower's OWN
    already-computed Phase 5 executable-return evidence
    (:func:`argus.copyability.loaders.load_wallet_opportunities`) at the
    primary 5m horizon, matched to each observation by the follower's
    real entry (``token_id``, ``first_seen_at`` == ``follower_entered_at``)
    -- the same point-in-time-safe, contamination-firewalled evidence
    Phase 5 itself reports, never a re-derived or approximated return.
    Loads each distinct follower wallet's opportunity population exactly
    once, regardless of how many leader edges reference it."""
    follower_wallet_ids = {follower for (_, follower) in observations_by_pair}
    opportunities_by_follower: dict[uuid.UUID, list[WalletOpportunity]] = {}
    for follower_wallet_id in follower_wallet_ids:
        firewall = await load_contamination_firewall(session, wallet_id=follower_wallet_id)
        loaded = await load_wallet_opportunities(
            session, wallet_id=follower_wallet_id, cutoff=cutoff, firewall=firewall
        )
        opportunities_by_follower[follower_wallet_id] = loaded.opportunities

    results: dict[tuple[uuid.UUID, uuid.UUID], ForwardInformationResult] = {}
    for (leader_wallet_id, follower_wallet_id), pair_observations in observations_by_pair.items():
        opportunity_by_key = {
            (opp.token_id, opp.first_seen_at): opp
            for opp in opportunities_by_follower[follower_wallet_id]
            if opp.token_id is not None
        }

        eligible_count = 0
        successful_returns: list[Decimal] = []
        for observation in pair_observations:
            opportunity = opportunity_by_key.get(
                (observation.token_id, observation.follower_entered_at)
            )
            if opportunity is None:
                continue
            outcome = opportunity.reverse_outcomes.get(PRIMARY_EXECUTABLE_HORIZON)
            if outcome is None:
                continue
            eligible_count += 1
            if outcome.result.status == "SUCCESS" and outcome.result.gross_return_pct is not None:
                successful_returns.append(outcome.result.gross_return_pct)

        if eligible_count == 0:
            results[(leader_wallet_id, follower_wallet_id)] = ForwardInformationResult(
                mean_pct=None,
                sample_count=0,
                eligible_count=0,
                missing_reason=_MISSING_NO_MATCH,
            )
        elif not successful_returns:
            results[(leader_wallet_id, follower_wallet_id)] = ForwardInformationResult(
                mean_pct=None,
                sample_count=0,
                eligible_count=eligible_count,
                missing_reason=_MISSING_NO_SUCCESS,
            )
        else:
            mean_pct = sum(successful_returns, start=Decimal(0)) / Decimal(len(successful_returns))
            results[(leader_wallet_id, follower_wallet_id)] = ForwardInformationResult(
                mean_pct=mean_pct,
                sample_count=len(successful_returns),
                eligible_count=eligible_count,
                missing_reason=None,
            )
    return results
