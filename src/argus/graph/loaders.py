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
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from argus.copyability.identity import known_by_cutoff
from argus.domain.prospective_events import ProspectiveEvent
from argus.graph.lead_follow import WalletTokenEntry


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
