"""Top-level Phase 4 monitoring pass: real, production service/CLI wiring
tying ``argus.shadow.prospective``/``argus.shadow.intents`` together
(MASTER_SPEC.md sections 44-46) -- never a test-only helper. Wired
through ``argus prospective run`` (``src/argus/cli.py``).

No network I/O happens in this module -- scanning for new tracked-wallet
swaps and creating a prospective event/shadow intent are pure DB reads/
writes, so this pass is one atomic transaction; the entry-delay probes a
qualifying intent schedules here are only DUE later and are executed by
``argus.shadow.quote_jobs.run_due_entry_probes`` (a separate, network-
calling pass -- see that module for why it needs its own claim/execute/
record shape instead).
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from argus.domain.swaps import Swap
from argus.shadow.intents import create_shadow_intent_for_event
from argus.shadow.prospective import revisit_pending_confirmations, scan_for_new_prospective_events

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from argus.config import ArgusConfig
    from argus.domain.prospective_events import ProspectiveEvent
    from argus.domain.shadow_intents import ShadowIntent


@dataclasses.dataclass(frozen=True, slots=True)
class MonitoringPassResult:
    prospective_events: tuple[ProspectiveEvent, ...]
    shadow_intents: tuple[ShadowIntent, ...]
    confirmed_event_ids: tuple[uuid.UUID, ...] = ()


async def run_prospective_monitoring_pass(
    session_factory: async_sessionmaker[_AsyncSession],
    *,
    config: ArgusConfig,
    now: datetime,
    tier_allowed: Sequence[str] | None = None,
    limit: int = 100,
) -> MonitoringPassResult:
    """One pass: first revisits already-created events still missing
    confirmation evidence (P4-R3 -- exposes a late-arriving real
    confirmation exactly once, never touching any other frozen field),
    then scans for new tracked-wallet swaps, creates their prospective
    events, and creates a shadow intent (with its scheduled entry-delay
    probes) for every one that passes the honest eligibility gate. Call
    repeatedly (a bounded loop, a cron tick, or as part of ``argus ingest
    run``'s own periodic cadence)."""
    resolved_tier_allowed = tier_allowed or config.get("thresholds.wallet_tier_allowed") or []
    async with session_factory() as session, session.begin():
        confirmed_ids = await revisit_pending_confirmations(session, limit=limit)
        new_events = await scan_for_new_prospective_events(
            session, tier_allowed=resolved_tier_allowed, now=now, limit=limit
        )
        intents_created: list[ShadowIntent] = []
        for event in new_events:
            swap = await session.get(Swap, event.swap_id)
            assert swap is not None
            intent = await create_shadow_intent_for_event(
                session, event=event, swap=swap, config=config, now=now
            )
            if intent is not None:
                intents_created.append(intent)

    return MonitoringPassResult(
        prospective_events=tuple(new_events),
        shadow_intents=tuple(intents_created),
        confirmed_event_ids=tuple(confirmed_ids),
    )
