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

P4-remediation-002 R4: ``matured_executable_outcomes_in_window`` and
``provider_gaps`` now window on ``ShadowQuoteProbe.terminal_at``, never
``responded_at`` -- a genuine scheduler-level ``PROVIDER_CAPACITY_MISS``
drop never sets ``responded_at`` at all (no real dispatch ever happened),
so windowing on ``responded_at`` alone silently excluded every such row
from both counts, permanently undercounting exactly the outcome
``provider_gaps`` exists to surface.

P4-remediation-002 R6: SHADOW's descriptive ``mfe_mae`` is now computed
from this window's own real ``ShadowMarkOutcome`` returns (fixed-horizon
point samples, reported as a sampled max/min with a count and an explicit
sampled-not-continuous caveat), never the historical Phase 3
``WalletPosition`` figures a prior round substituted in their place. Those
historical figures, when retained, now live in RESEARCH's own separately
labeled ``historical_backtest`` section, grouped by ``quote_asset_mint``
(never averaged across e.g. SOL and USDC) and restricted to each wallet's
CURRENT chosen history reconstruction, so a superseded/replayed
reconstruction's positions never inflate the sample.
``data_quality["low_completeness_wallets"]`` now counts distinct wallets
by their CURRENT (latest) ``WalletHistoryQuality`` assessment only -- a
wallet reassessed LOW -> LOW -> HIGH now counts 0, never every historical
LOW row. The former single ``matured_executable_outcomes_in_window``
count -- which mixed successful, unsellable, and missing-capacity
REVERSE_EXECUTABLE outcomes together and invited being read as a usable
executable sample size -- is replaced by
``reverse_executable_outcomes_in_window``'s explicit successful/
unsellable/missing_capacity breakdown, with ``usable_sample`` excluding
missing-capacity terminal no-send records (R4's own outcome) and
``reverse_executable_overdue_unattempted`` naming probes that are past due
but have not yet reached ANY terminal decision at all, kept distinguishable
from a terminal no-send capacity miss.
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
    OUTCOME_SUCCESS,
    PROBE_KIND_REVERSE_EXECUTABLE,
    UNSELLABLE_OUTCOMES,
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

    # P4-remediation-002 R6: a single "matured" count mixed SUCCESS,
    # every unsellable/error outcome, and PROVIDER_CAPACITY_MISS
    # together, then invited being read as a usable executable sample
    # size. Break it into its real classes instead -- successful,
    # unsellable (a real MASTER_SPEC section 48 outcome, never dropped),
    # and missing_capacity (R4's own terminal no-send state: a genuine
    # decision was recorded, but no request ever occurred). usable_sample
    # excludes missing_capacity; total_attempts names it explicitly
    # rather than silently folding it into the usable figure.
    outcome_rows = (
        await session.execute(
            select(ShadowQuoteProbe.outcome, func.count())
            .select_from(ShadowQuoteProbe)
            .where(
                ShadowQuoteProbe.probe_kind == PROBE_KIND_REVERSE_EXECUTABLE,
                ShadowQuoteProbe.terminal_at >= start,
                ShadowQuoteProbe.terminal_at < end,
            )
            .group_by(ShadowQuoteProbe.outcome)
        )
    ).all()
    successful = 0
    unsellable = 0
    missing_capacity = 0
    for outcome, count in outcome_rows:
        if outcome == OUTCOME_SUCCESS:
            successful = count
        elif outcome == OUTCOME_PROVIDER_CAPACITY_MISS:
            missing_capacity = count
        elif outcome in UNSELLABLE_OUTCOMES:
            unsellable += count
    usable_sample = successful + unsellable

    # Overdue-but-not-yet-terminal is a real, distinct state from a
    # terminal no-send capacity miss -- this probe was due but never
    # reached ANY terminal decision at all, never conflated with R4's
    # honest "decided not to send" outcome above.
    overdue_unattempted = await _count(
        session,
        select(func.count())
        .select_from(ShadowQuoteProbe)
        .where(
            ShadowQuoteProbe.probe_kind == PROBE_KIND_REVERSE_EXECUTABLE,
            ShadowQuoteProbe.target_due_at < end,
            ShadowQuoteProbe.terminal_at.is_(None),
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

    # P4-remediation-002 R6: descriptive SHADOW mfe/mae now comes from
    # this window's own real ShadowMarkOutcome returns -- fixed-horizon
    # (5m/30m/1h/6h/24h/3d/7d) point samples, never the historical Phase
    # 3 WalletPosition figures (moved to research's own separately
    # labeled historical section below). A late/out-of-window mark
    # (`actual_at` outside [start, end)) never changes an earlier
    # report's already-generated scope. No marks in-window is an honest
    # insufficient sample, never a fabricated zero.
    sampled_returns = (
        (
            await session.execute(
                select(ShadowMarkOutcome.mark_return_pct).where(
                    ShadowMarkOutcome.outcome == OUTCOME_RECORDED,
                    ShadowMarkOutcome.actual_at >= start,
                    ShadowMarkOutcome.actual_at < end,
                    ShadowMarkOutcome.mark_return_pct.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    non_null_returns = [r for r in sampled_returns if r is not None]
    if non_null_returns:
        mfe_mae: dict | str = {
            "sample_count": len(non_null_returns),
            "sampled_max_return_pct": str(max(non_null_returns)),
            "sampled_min_return_pct": str(min(non_null_returns)),
            "note": (
                "descriptive, sampled mark-price returns at fixed horizons within "
                "this report's window -- not a continuous MFE/MAE price path"
            ),
        }
    else:
        mfe_mae = "INSUFFICIENT_SAMPLE"

    return {
        "shadow_trades_opened_in_window": trades,
        "reverse_executable_outcomes_in_window": {
            "successful": successful,
            "unsellable": unsellable,
            "missing_capacity": missing_capacity,
            "usable_sample": usable_sample,
            "total_attempts_including_missing_capacity": usable_sample + missing_capacity,
        },
        "reverse_executable_overdue_unattempted": overdue_unattempted,
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


def _latest_history_id_per_wallet_subquery(cutoff: datetime | None = None):
    """WalletHistoryQuality is append-only and versioned (a later
    reconstruction adds a new row rather than overwriting a prior
    judgment) -- downstream code always reads the latest row per wallet.
    Returns the ``history_id`` DISTINCT ON each wallet's own most recent
    ``created_at``, so a repeated reconstruction never multiplies a
    distinct-wallet or chosen-position sample (P4-remediation-002 R6).

    P4-REC-05: ``cutoff``, when supplied, bounds the selection to history
    rows genuinely KNOWN as of that instant (``created_at <= cutoff``)
    before the DISTINCT ON picks each wallet's latest eligible row -- a
    history record created AFTER an earlier report's own ``end`` must
    never count as "current" in that earlier report just because it is
    the globally-latest row by the time the report happens to run. The
    per-wallet deduplication itself is unchanged; only which rows are
    eligible candidates is bounded. ``cutoff=None`` preserves the
    original globally-latest-ever selection (``_build_research``'s own
    unbounded historical-backtest use, out of this recovery's frozen
    scope)."""
    query = select(WalletHistoryQuality.history_id, WalletHistoryQuality.history_completeness)
    if cutoff is not None:
        query = query.where(WalletHistoryQuality.created_at <= cutoff)
    return (
        query.distinct(WalletHistoryQuality.wallet_id)
        .order_by(WalletHistoryQuality.wallet_id, WalletHistoryQuality.created_at.desc())
        .subquery()
    )


async def _build_research(session: AsyncSession) -> dict:
    latest_history = _latest_history_id_per_wallet_subquery()
    wallet_history_rows = await _count(
        session, select(func.count()).select_from(WalletHistoryQuality)
    )

    # P4-remediation-002 R6: historical Phase 3 WalletPosition mfe/mae,
    # if retained, is a genuinely separate (backtest, not live-shadow)
    # sample -- reported here, distinctly labeled, never folded into
    # shadow["mfe_mae"]. Grouped by quote_asset_mint (never averaged
    # across e.g. SOL and USDC -- an unlabeled cross-unit average is
    # meaningless), and restricted to positions belonging to each
    # wallet's CURRENT chosen (latest) history reconstruction, so a
    # superseded/replayed reconstruction's positions never inflate the
    # sample.
    historical_rows = (
        await session.execute(
            select(
                WalletPosition.quote_asset_mint, WalletPosition.mfe_quote, WalletPosition.mae_quote
            ).where(
                WalletPosition.history_id.in_(select(latest_history.c.history_id)),
                WalletPosition.mfe_quote.is_not(None),
                WalletPosition.mae_quote.is_not(None),
            )
        )
    ).all()
    by_quote_asset: dict[str, list[tuple[Decimal, Decimal]]] = {}
    for quote_asset_mint, mfe, mae in historical_rows:
        by_quote_asset.setdefault(quote_asset_mint, []).append((mfe, mae))
    historical_mfe_mae: dict | str
    if by_quote_asset:
        historical_mfe_mae = {
            quote_asset_mint: {
                "sample_count": len(pairs),
                "avg_mfe_quote": str(sum((p[0] for p in pairs), start=Decimal(0)) / len(pairs)),
                "avg_mae_quote": str(sum((p[1] for p in pairs), start=Decimal(0)) / len(pairs)),
            }
            for quote_asset_mint, pairs in by_quote_asset.items()
        }
    else:
        historical_mfe_mae = "INSUFFICIENT_SAMPLE"

    return {
        "sample_counts": {
            "wallet_history_rows": wallet_history_rows,
        },
        "historical_backtest": {
            "note": (
                "Phase 3 reconstructed-position backtest evidence, never live shadow "
                "trading -- grouped by quote asset, never averaged across assets; only "
                "each wallet's current chosen history reconstruction is included"
            ),
            "mfe_mae_by_quote_asset": historical_mfe_mae,
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
    # P4-remediation-002 R6: counts distinct WALLETS whose current
    # (latest) history assessment is LOW/UNKNOWN -- a wallet reassessed
    # LOW -> LOW -> HIGH now counts 0, never 2; every prior point-in-time
    # row stays preserved, only the report's own current-state count
    # reads just the latest one per wallet.
    # P4-REC-05: bounded to history rows known as of this report's own
    # `end` -- a history row created AFTER `end` must never count as
    # "current" in this report just because it is the globally-latest row
    # by the time this query happens to run.
    latest_history = _latest_history_id_per_wallet_subquery(cutoff=end)
    low_completeness_wallets = await _count(
        session,
        select(func.count())
        .select_from(latest_history)
        .where(latest_history.c.history_completeness.in_((COMPLETENESS_LOW, COMPLETENESS_UNKNOWN))),
    )
    provider_gaps = await _count(
        session,
        select(func.count())
        .select_from(ShadowQuoteProbe)
        .where(
            ShadowQuoteProbe.outcome == OUTCOME_PROVIDER_CAPACITY_MISS,
            ShadowQuoteProbe.terminal_at >= start,
            ShadowQuoteProbe.terminal_at < end,
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
