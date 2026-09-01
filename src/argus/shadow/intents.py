"""Shadow intent creation + entry-delay probe scheduling (MASTER_SPEC.md
section 45 SHADOW COPY EXECUTION, section 46 COPYABILITY DELAY PROBES).

The eligibility gate reuses ``config/signals_v1.yaml``'s existing
``thresholds.wallet_tier_allowed``/``thresholds.qualification_score_min``
-- the SAME thresholds already governing live eligibility elsewhere in
this project -- never a manufactured, looser Phase-4-only bar (this
instruction's own explicit "preserve existing live thresholds rather than
manufacturing qualified wallets"). This is research/shadow eligibility
only: it authorizes nothing about real trading, and every live safety
flag remains unaffected by anything in this module.

P4-R2 remediation (argus-phase-4-remediation-001): each entry-delay
probe's ``target_due_at`` is now anchored to ``event.first_seen_at`` --
the moment ARGUS actually first observed the leader's transaction --
never to whatever wall-clock time the monitoring pass happened to reach
this event at. A confirmation delay, a queue backlog, or simply calling
``argus prospective run`` less often than every second must never push a
probe's nominal target later; a probe found overdue when it is finally
scheduled is honestly late (``scheduling_delay_seconds`` reflects the
real gap from ``event.first_seen_at + target_seconds``), never silently
re-based to look on-time. ``ShadowIntent.created_at``/each probe's own
``created_at`` still honestly record the real row-creation instant
(``now``) -- a distinct concept from the due-time origin, never
backdated.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from argus.domain.shadow_intents import STATUS_CREATED, ShadowIntent
from argus.domain.shadow_quote_probes import (
    OUTCOME_PENDING,
    PROBE_KIND_ENTRY_DELAY,
    ShadowQuoteProbe,
)
from argus.shadow.prospective import is_buy

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from argus.config import ArgusConfig
    from argus.domain.prospective_events import ProspectiveEvent
    from argus.domain.swaps import Swap

ALGORITHM_VERSION: Final[str] = "shadow_intent_v1"


def entry_probe_label(seconds: int) -> str:
    return f"{seconds}s"


async def _schedule_entry_delay_probes(
    session: AsyncSession,
    *,
    intent: ShadowIntent,
    due_origin: datetime,
    created_at: datetime,
    delays_seconds: Sequence[int],
) -> list[ShadowQuoteProbe]:
    """``due_origin`` is ``event.first_seen_at`` (P4-R2: the immutable
    knowledge cutoff every target due time is anchored to) --
    ``created_at`` is the real, honest instant these rows are actually
    being created (``now``), never backdated to ``due_origin``."""
    probes: list[ShadowQuoteProbe] = []
    for seconds in delays_seconds:
        probe = ShadowQuoteProbe(
            probe_id=uuid.uuid4(),
            probe_kind=PROBE_KIND_ENTRY_DELAY,
            target_label=entry_probe_label(seconds),
            target_seconds_from_observation=seconds,
            shadow_intent_id=intent.shadow_intent_id,
            shadow_position_id=None,
            input_mint=intent.input_mint,
            output_mint=intent.output_mint,
            notional_input_amount_raw=intent.notional_input_amount_raw,
            target_due_at=due_origin + timedelta(seconds=seconds),
            outcome=OUTCOME_PENDING,
            algorithm_version=ALGORITHM_VERSION,
            created_at=created_at,
        )
        session.add(probe)
        probes.append(probe)
    await session.flush()
    return probes


def _is_eligible(event: ProspectiveEvent, swap: Swap, *, config: ArgusConfig) -> bool:
    tier_allowed = config.get("thresholds.wallet_tier_allowed") or []
    if event.wallet_tier_snapshot not in tier_allowed:
        return False
    score_min = config.get("thresholds.qualification_score_min")
    if event.wallet_score_snapshot is None:
        return False
    if score_min is not None and event.wallet_score_snapshot < Decimal(str(score_min)):
        return False
    return is_buy(swap)


async def create_shadow_intent_for_event(
    session: AsyncSession,
    *,
    event: ProspectiveEvent,
    swap: Swap,
    config: ArgusConfig,
    now: datetime,
) -> ShadowIntent | None:
    """Creates exactly one :class:`ShadowIntent` (with its full set of
    scheduled entry-delay probes) for a qualifying prospective event, or
    returns ``None`` without creating anything for a non-qualifying one
    -- eligibility is never manufactured to force a shadow trade to
    exist."""
    if not _is_eligible(event, swap, config=config):
        return None

    notional_mint = config.get("shadow_copy.notional_input_mint")
    notional_raw = config.get("shadow_copy.notional_input_amount_raw")
    if not notional_mint or not notional_raw:
        raise ValueError(
            "config/signals_v1.yaml is missing shadow_copy.notional_input_mint/"
            "notional_input_amount_raw -- required for shadow intent creation"
        )

    intent = ShadowIntent(
        shadow_intent_id=uuid.uuid4(),
        prospective_event_id=event.prospective_event_id,
        wallet_id=event.wallet_id,
        token_id=event.token_id,
        input_mint=notional_mint,
        output_mint=swap.output_mint,
        notional_input_amount_raw=int(notional_raw),
        config_hash=config.config_hash,
        status=STATUS_CREATED,
        algorithm_version=ALGORITHM_VERSION,
        created_at=now,
    )
    session.add(intent)
    await session.flush()

    delays_seconds = config.get("copyability_delay_probes_seconds") or [1, 5, 15, 30, 60, 300]
    await _schedule_entry_delay_probes(
        session,
        intent=intent,
        due_origin=event.first_seen_at,
        created_at=now,
        delays_seconds=delays_seconds,
    )
    return intent
