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

P4-R6 remediation (argus-phase-4-remediation-001): tier-transition
direction (promotion/demotion/quarantine/exit) is now computed from
``from_tier``/``to_tier`` together against the real ``WALLET_TIERS`` rank
order, never from ``to_tier`` alone (the previous version could not
distinguish an actual promotion like DISCOVERED->WATCH from an actual
demotion like S->A, since both merely land on a tier that isn't
QUARANTINE). ``new_wallets`` now counts distinct wallet IDENTITIES whose
``wallets.first_discovered_at`` falls in the window, never repeated
``wallet_discovery_events`` rows for the same already-known wallet.
Previously-``NOT_IMPLEMENTED`` fields this offline report CAN genuinely
answer from already-persisted evidence (``low_completeness_wallets``,
``provider_gaps``, descriptive ``mfe_mae``, research ``sample_counts``)
are now populated; features that genuinely do not exist yet (Phase 5+
hypothesis/graph/live work) remain honestly ``NOT_IMPLEMENTED``. An
optional injectable ``notifier`` sends one ``DAILY_SUMMARY`` notification
after the report is fully built, using only its own already-committed
figures -- disabled/no-op by default, ``FakeTelegramTransport`` in tests/
the REPLAY demo, and a notification failure never affects the returned
report.
"""

from __future__ import annotations

import contextlib
import dataclasses
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from argus.domain.provider_usage import ProviderUsage
from argus.domain.shadow_intents import STATUS_FILLED, ShadowIntent
from argus.domain.shadow_mark_outcomes import OUTCOME_RECORDED, ShadowMarkOutcome
from argus.domain.shadow_positions import ShadowPosition
from argus.domain.shadow_quote_probes import (
    OUTCOME_PROVIDER_CAPACITY_MISS,
    PROBE_KIND_REVERSE_EXECUTABLE,
    ShadowQuoteProbe,
)
from argus.domain.swaps import Swap
from argus.domain.tokens import Token
from argus.domain.wallet_history_quality import (
    COMPLETENESS_LOW,
    COMPLETENESS_UNKNOWN,
    WalletHistoryQuality,
)
from argus.domain.wallet_positions import WalletPosition
from argus.domain.wallet_stream_state import WalletStreamState
from argus.domain.wallet_tier_history import TIER_QUARANTINE, WALLET_TIERS, WalletTierTransition
from argus.domain.wallets import Wallet

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from argus.telegram.notifier import TelegramNotifier

REPORT_VERSION = "daily_report_v2"

# Only the "normal progression" tiers rank-compare for promotion/demotion
# purposes -- QUARANTINE/DORMANT/RETIRED are exits/holds, never scored as
# a promotion merely because their tuple position happens to sit later.
_PROGRESSION_TIERS = WALLET_TIERS[:6]  # DISCOVERED..S
_TIER_RANK = {tier: rank for rank, tier in enumerate(_PROGRESSION_TIERS)}
_EXIT_TIERS = frozenset(WALLET_TIERS[6:])  # QUARANTINE, DORMANT, RETIRED


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
        .select_from(Wallet)
        .where(Wallet.first_discovered_at >= start, Wallet.first_discovered_at < end),
    )
    transitions = (
        await session.execute(
            select(WalletTierTransition.from_tier, WalletTierTransition.to_tier).where(
                WalletTierTransition.transitioned_at >= start,
                WalletTierTransition.transitioned_at < end,
            )
        )
    ).all()
    promotions = 0
    demotions = 0
    quarantines = 0
    for from_tier, to_tier in transitions:
        if to_tier == TIER_QUARANTINE:
            quarantines += 1
            continue
        if to_tier in _EXIT_TIERS or from_tier in _EXIT_TIERS:
            # A DORMANT/RETIRED exit or a recovery FROM one of those
            # states is neither a promotion nor a demotion in the normal
            # progression sense.
            continue
        to_rank = _TIER_RANK.get(to_tier)
        if to_rank is None:
            continue
        from_rank = _TIER_RANK[from_tier] if from_tier is not None else -1
        if to_rank > from_rank:
            promotions += 1
        elif to_rank < from_rank:
            demotions += 1
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

    mfe_mae_rows = (
        await session.execute(
            select(WalletPosition.mfe_quote, WalletPosition.mae_quote).where(
                WalletPosition.mfe_quote.is_not(None), WalletPosition.mae_quote.is_not(None)
            )
        )
    ).all()
    if mfe_mae_rows:
        sample_count = len(mfe_mae_rows)
        avg_mfe = sum((r[0] for r in mfe_mae_rows), start=Decimal(0)) / sample_count
        avg_mae = sum((r[1] for r in mfe_mae_rows), start=Decimal(0)) / sample_count
        mfe_mae: dict | str = {
            "sample_count": sample_count,
            "avg_mfe_quote": str(avg_mfe),
            "avg_mae_quote": str(avg_mae),
            "note": "descriptive, sampled Phase 3 position evidence -- not continuous market coverage",
        }
    else:
        mfe_mae = "INSUFFICIENT_SAMPLE"

    return {
        "shadow_trades_opened_in_window": trades,
        "matured_executable_outcomes_in_window": matured_executable,
        "matured_mark_outcomes_in_window": matured_mark,
        "open_shadow_positions_total": open_positions,
        "mfe_mae": mfe_mae,
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


async def _build_research(session: AsyncSession) -> dict:
    closed_positions_with_mfe_mae = await _count(
        session,
        select(func.count())
        .select_from(WalletPosition)
        .where(WalletPosition.mfe_quote.is_not(None), WalletPosition.mae_quote.is_not(None)),
    )
    wallet_history_rows = await _count(
        session, select(func.count()).select_from(WalletHistoryQuality)
    )
    return {
        "sample_counts": {
            "closed_positions_with_mfe_mae": closed_positions_with_mfe_mae,
            "wallet_history_rows": wallet_history_rows,
        },
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
    low_completeness_wallets = await _count(
        session,
        select(func.count())
        .select_from(WalletHistoryQuality)
        .where(
            WalletHistoryQuality.history_completeness.in_((COMPLETENESS_LOW, COMPLETENESS_UNKNOWN))
        ),
    )
    provider_gaps = await _count(
        session,
        select(func.count())
        .select_from(ShadowQuoteProbe)
        .where(
            ShadowQuoteProbe.outcome == OUTCOME_PROVIDER_CAPACITY_MISS,
            ShadowQuoteProbe.responded_at >= start,
            ShadowQuoteProbe.responded_at < end,
        ),
    )
    return {
        "ambiguous_swaps_in_window": ambiguous_swaps,
        "missing_mark_observations_overdue": missing_mark_observations,
        "low_completeness_wallets": low_completeness_wallets,
        "provider_gaps": provider_gaps,
    }


async def _notify_daily_summary(notifier: TelegramNotifier | None, *, report: DailyReport) -> None:
    if notifier is None:
        return
    with contextlib.suppress(Exception):  # notification is never allowed to affect the record
        await notifier.notify(
            event_type="DAILY_SUMMARY",
            text=(
                f"Daily report {report.window_start.isoformat()}..{report.window_end.isoformat()}: "
                f"{report.discovery['new_wallets']} new wallets, "
                f"{report.signals['signals']} signals, "
                f"{report.shadow['shadow_trades_opened_in_window']} shadow trades opened"
            ),
        )


async def build_daily_report(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime,
    tier_allowed: list[str],
    window: timedelta = timedelta(hours=24),
    notifier: TelegramNotifier | None = None,
) -> DailyReport:
    start = now - window
    async with session_factory() as session:
        system = await _build_system(session, start=start, end=now)
        discovery = await _build_discovery(session, start=start, end=now)
        tracking = await _build_tracking(session, start=start, end=now, tier_allowed=tier_allowed)
        signals = await _build_signals(session, start=start, end=now)
        shadow = await _build_shadow(session, start=start, end=now)
        research = await _build_research(session)
        data_quality = await _build_data_quality(session, start=start, end=now)
    report = DailyReport(
        generated_at=now,
        window_start=start,
        window_end=now,
        system=system,
        discovery=discovery,
        tracking=tracking,
        signals=signals,
        shadow=shadow,
        live=_build_live(),
        research=research,
        data_quality=data_quality,
    )
    await _notify_daily_summary(notifier, report=report)
    return report
