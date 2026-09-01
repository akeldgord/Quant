"""``argus report daily`` (MASTER_SPEC.md section 93).

Every figure below is a real, queried count over the reporting window
(default: the 24 hours ending at ``now``) -- never a fabricated or
estimated value. A section this offline, single-process report genuinely
cannot measure (process uptime; a live error/incident log) is reported
with an explicit ``"UNAVAILABLE"`` sentinel, never a guessed number.
Sections whose feature does not exist yet (LIVE beyond its always-false
safety flags; RESEARCH's hypothesis-registry fields, Phase 6/7/8+ work)
report ``"NOT_IMPLEMENTED"`` for those fields, per this instruction's own
"Sections depending on later phases report unavailable/not implemented,
not invented activity." No causal language is used anywhere in this
module (section 93's own explicit rule) -- every sentence states a count
or a status, never an inference about why it occurred.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from argus.domain.provider_usage import ProviderUsage
from argus.domain.shadow_intents import STATUS_FILLED, ShadowIntent
from argus.domain.shadow_mark_outcomes import OUTCOME_RECORDED, ShadowMarkOutcome
from argus.domain.shadow_positions import ShadowPosition
from argus.domain.shadow_quote_probes import PROBE_KIND_REVERSE_EXECUTABLE, ShadowQuoteProbe
from argus.domain.swaps import Swap
from argus.domain.tokens import Token
from argus.domain.wallet_discovery_events import WalletDiscoveryEvent
from argus.domain.wallet_stream_state import WalletStreamState
from argus.domain.wallet_tier_history import (
    TIER_A,
    TIER_QUARANTINE,
    TIER_S,
    WalletTierTransition,
)
from argus.domain.wallets import Wallet

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

REPORT_VERSION = "daily_report_v1"


@dataclasses.dataclass(frozen=True, slots=True)
class DailyReport:
    generated_at: datetime
    window_start: datetime
    window_end: datetime
    system: dict
    discovery: dict
    tracking: dict
    signals: dict
    shadow: dict
    live: dict
    research: dict
    data_quality: dict


async def _count(session: AsyncSession, stmt) -> int:
    return (await session.execute(stmt)).scalar_one()


async def _build_system(session: AsyncSession, *, start: datetime, end: datetime) -> dict:
    usage_rows = (
        await session.execute(
            select(ProviderUsage.provider, ProviderUsage.status, func.count())
            .where(ProviderUsage.requested_at >= start, ProviderUsage.requested_at < end)
            .group_by(ProviderUsage.provider, ProviderUsage.status)
        )
    ).all()
    provider_use: dict[str, dict[str, int]] = {}
    errors_total = 0
    for provider, status, count in usage_rows:
        provider_use.setdefault(provider, {})[status] = count
        if status != "ok":
            errors_total += count
    return {
        "uptime": "UNAVAILABLE_OFFLINE_REPORT",
        "errors": errors_total,
        "provider_health": "UNAVAILABLE_OFFLINE_REPORT",
        "provider_use": provider_use,
    }


async def _build_discovery(session: AsyncSession, *, start: datetime, end: datetime) -> dict:
    new_tokens = await _count(
        session,
        select(func.count())
        .select_from(Token)
        .where(Token.first_observed_at >= start, Token.first_observed_at < end),
    )
    new_wallets = await _count(
        session,
        select(func.count())
        .select_from(WalletDiscoveryEvent)
        .where(WalletDiscoveryEvent.created_at >= start, WalletDiscoveryEvent.created_at < end),
    )
    transitions = (
        (
            await session.execute(
                select(WalletTierTransition.to_tier).where(
                    WalletTierTransition.transitioned_at >= start,
                    WalletTierTransition.transitioned_at < end,
                )
            )
        )
        .scalars()
        .all()
    )
    promotions = sum(1 for t in transitions if t in (TIER_A, TIER_S))
    quarantines = sum(1 for t in transitions if t == TIER_QUARANTINE)
    demotions = len(transitions) - promotions - quarantines
    return {
        "new_tokens": new_tokens,
        "new_wallets": new_wallets,
        "promotions": promotions,
        "demotions": demotions,
        "quarantines": quarantines,
    }


async def _build_tracking(
    session: AsyncSession, *, start: datetime, end: datetime, tier_allowed: list[str]
) -> dict:
    tracked_wallets = await _count(
        session,
        select(func.count()).select_from(Wallet).where(Wallet.current_tier.in_(tier_allowed)),
    )
    tracked_addresses = (
        (
            await session.execute(
                select(Wallet.wallet_address).where(Wallet.current_tier.in_(tier_allowed))
            )
        )
        .scalars()
        .all()
    )
    wallet_trades = 0
    if tracked_addresses:
        wallet_trades = await _count(
            session,
            select(func.count())
            .select_from(Swap)
            .where(
                Swap.wallet_address.in_(tracked_addresses),
                Swap.created_at >= start,
                Swap.created_at < end,
            ),
        )
    degraded_wallets = await _count(
        session,
        select(func.count())
        .select_from(WalletStreamState)
        .where(WalletStreamState.wallet_live_state == "DEGRADED"),
    )
    reconciled_recently = await _count(
        session,
        select(func.count())
        .select_from(WalletStreamState)
        .where(
            WalletStreamState.last_reconciliation_at >= start,
            WalletStreamState.last_reconciliation_at < end,
        ),
    )
    return {
        "tracked_wallets": tracked_wallets,
        "wallet_trades": wallet_trades,
        "stream_gaps_degraded_wallets": degraded_wallets,
        "reconciliations_in_window": reconciled_recently,
    }


async def _build_signals(session: AsyncSession, *, start: datetime, end: datetime) -> dict:
    from argus.domain.prospective_events import ProspectiveEvent

    signals = await _count(
        session,
        select(func.count())
        .select_from(ProspectiveEvent)
        .where(ProspectiveEvent.created_at >= start, ProspectiveEvent.created_at < end),
    )
    confirmed = await _count(
        session,
        select(func.count())
        .select_from(ProspectiveEvent)
        .where(
            ProspectiveEvent.created_at >= start,
            ProspectiveEvent.created_at < end,
            ProspectiveEvent.confirmation_time.is_not(None),
        ),
    )
    return {
        "signals": signals,
        "confirmations": confirmed,
        "convergence_events": "NOT_IMPLEMENTED",
    }


async def _build_shadow(session: AsyncSession, *, start: datetime, end: datetime) -> dict:
    trades = await _count(
        session,
        select(func.count())
        .select_from(ShadowIntent)
        .where(
            ShadowIntent.created_at >= start,
            ShadowIntent.created_at < end,
            ShadowIntent.status == STATUS_FILLED,
        ),
    )
    matured_executable = await _count(
        session,
        select(func.count())
        .select_from(ShadowQuoteProbe)
        .where(
            ShadowQuoteProbe.probe_kind == PROBE_KIND_REVERSE_EXECUTABLE,
            ShadowQuoteProbe.responded_at >= start,
            ShadowQuoteProbe.responded_at < end,
        ),
    )
    matured_mark = await _count(
        session,
        select(func.count())
        .select_from(ShadowMarkOutcome)
        .where(
            ShadowMarkOutcome.actual_at >= start,
            ShadowMarkOutcome.actual_at < end,
            ShadowMarkOutcome.outcome == OUTCOME_RECORDED,
        ),
    )
    open_positions = await _count(session, select(func.count()).select_from(ShadowPosition))
    return {
        "shadow_trades_opened_in_window": trades,
        "matured_executable_outcomes_in_window": matured_executable,
        "matured_mark_outcomes_in_window": matured_mark,
        "open_shadow_positions_total": open_positions,
        "mfe_mae": "NOT_IMPLEMENTED",
    }


def _build_live() -> dict:
    return {
        "ready_state": False,
        "canary_state": False,
        "armed_state": False,
        "orders": "NOT_IMPLEMENTED",
        "fills": "NOT_IMPLEMENTED",
        "pnl": "NOT_IMPLEMENTED",
        "risk_events": "NOT_IMPLEMENTED",
        "rejections": "NOT_IMPLEMENTED",
    }


def _build_research() -> dict:
    return {
        "sample_counts": "NOT_IMPLEMENTED",
        "hypothesis_changes": "NOT_IMPLEMENTED",
        "notable_anomalies": "NOT_IMPLEMENTED",
    }


async def _build_data_quality(session: AsyncSession, *, start: datetime, end: datetime) -> dict:
    ambiguous_swaps = await _count(
        session,
        select(func.count())
        .select_from(Swap)
        .where(Swap.classification == "UNKNOWN", Swap.created_at >= start, Swap.created_at < end),
    )
    missing_mark_observations = await _count(
        session,
        select(func.count())
        .select_from(ShadowMarkOutcome)
        .where(ShadowMarkOutcome.due_at < end, ShadowMarkOutcome.actual_at.is_(None)),
    )
    return {
        "ambiguous_swaps_in_window": ambiguous_swaps,
        "missing_mark_observations_overdue": missing_mark_observations,
        "low_completeness_wallets": "NOT_IMPLEMENTED",
        "provider_gaps": "NOT_IMPLEMENTED",
    }


async def build_daily_report(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime,
    tier_allowed: list[str],
    window: timedelta = timedelta(hours=24),
) -> DailyReport:
    start = now - window
    async with session_factory() as session:
        system = await _build_system(session, start=start, end=now)
        discovery = await _build_discovery(session, start=start, end=now)
        tracking = await _build_tracking(session, start=start, end=now, tier_allowed=tier_allowed)
        signals = await _build_signals(session, start=start, end=now)
        shadow = await _build_shadow(session, start=start, end=now)
        data_quality = await _build_data_quality(session, start=start, end=now)
    return DailyReport(
        generated_at=now,
        window_start=start,
        window_end=now,
        system=system,
        discovery=discovery,
        tracking=tracking,
        signals=signals,
        shadow=shadow,
        live=_build_live(),
        research=_build_research(),
        data_quality=data_quality,
    )
