"""Scheduled quote-probe execution -- entry-delay (section 46) and
reverse-executable (section 47) -- with claim-based restart safety
(section 84: "kill shadow worker mid-job -> restart -> no duplicate
shadow trade").

Every probe follows the SAME three-step, independently-committing shape
``argus.wallets.archaeology.run_archaeology`` already established for
crash safety:

1. **claim** -- an atomic ``UPDATE ... WHERE claimed_at IS NULL OR
   claimed_at < staleness cutoff`` (``FOR UPDATE SKIP LOCKED``), committed
   alone. A worker that dies here leaves the row claimable again once its
   claim goes stale -- never silently lost, never double-claimed by a
   live concurrent worker.
2. **call the provider** -- deliberately OUTSIDE any open transaction
   (a real network round trip must never hold a DB transaction/lock
   open). ``requested_at``/``responded_at`` come from the injected
   :class:`~argus.clock.Clock`, taken immediately before/after the call,
   so actual latency is always the real measured gap -- never asserted
   ("Never claim a +1s quote if the call occurred +2.7s later," section
   46's own explicit rule).
3. **record** -- one atomic transaction that writes the terminal
   ``responded_at``/``outcome``/... fields and, for an ``ENTRY_DELAY``
   probe whose outcome is ``SUCCESS``, creates the ``ShadowPosition``
   (guarded by the position's own unique ``shadow_intent_id`` constraint,
   so even a genuine double-execution of this step can never create two
   positions for the same intent) and schedules its reverse-executable/
   mark probes, all together. A worker that dies after step 2 but before
   this commits simply leaves the probe claimed-but-unresponded; the next
   claim pass (after the staleness window) reclaims and re-attempts it --
   never resuming mid-write, since nothing was ever partially written.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from sqlalchemy import or_, select

from argus.domain.shadow_intents import STATUS_FILLED, STATUS_NO_FILL, ShadowIntent
from argus.domain.shadow_mark_outcomes import OUTCOME_PENDING as MARK_OUTCOME_PENDING
from argus.domain.shadow_mark_outcomes import ShadowMarkOutcome
from argus.domain.shadow_positions import ShadowPosition
from argus.domain.shadow_quote_probes import (
    OUTCOME_INSUFFICIENT_LIQUIDITY,
    OUTCOME_NO_ROUTE,
    OUTCOME_PENDING,
    OUTCOME_PRICE_IMPACT_EXCESSIVE,
    OUTCOME_PROVIDER_CAPACITY_MISS,
    OUTCOME_QUOTE_FAILED,
    OUTCOME_SUCCESS,
    OUTCOME_TOKEN_RESTRICTED,
    PROBE_KIND_ENTRY_DELAY,
    PROBE_KIND_REVERSE_EXECUTABLE,
    ShadowQuoteProbe,
)
from argus.shadow.errors import (
    InsufficientLiquidityError,
    NoRouteError,
    ProviderCapacityMissError,
    TokenRestrictedError,
)
from argus.shadow.errors import ShadowQuoteError as _ShadowQuoteError
from argus.shadow.horizons import horizon_to_timedelta

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from argus.clock import Clock
    from argus.config import ArgusConfig
    from argus.providers import ExecutionProvider, MarketDataProvider

ALGORITHM_VERSION: Final[str] = "shadow_quote_jobs_v1"

_ERROR_OUTCOME_MAP: Final[dict[type[Exception], str]] = {
    NoRouteError: OUTCOME_NO_ROUTE,
    InsufficientLiquidityError: OUTCOME_INSUFFICIENT_LIQUIDITY,
    TokenRestrictedError: OUTCOME_TOKEN_RESTRICTED,
    ProviderCapacityMissError: OUTCOME_PROVIDER_CAPACITY_MISS,
}

_DEFAULT_MAX_PRICE_IMPACT_PCT: Final[Decimal] = Decimal("0.10")


class SimulatedWorkerCrash(RuntimeError):
    """Raised only when a caller explicitly requests a crash-injection
    point for a restart/idempotency test (section 84's own required
    test) -- never raised in normal operation."""


async def _claim_due_probes(
    session: AsyncSession,
    *,
    probe_kind: str,
    now: datetime,
    worker_id: str,
    stale_after: timedelta,
    limit: int,
) -> list[uuid.UUID]:
    stale_cutoff = now - stale_after
    candidates = (
        (
            await session.execute(
                select(ShadowQuoteProbe)
                .where(
                    ShadowQuoteProbe.probe_kind == probe_kind,
                    ShadowQuoteProbe.target_due_at <= now,
                    ShadowQuoteProbe.responded_at.is_(None),
                    or_(
                        ShadowQuoteProbe.claimed_at.is_(None),
                        ShadowQuoteProbe.claimed_at < stale_cutoff,
                    ),
                )
                .order_by(ShadowQuoteProbe.target_due_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    claimed_ids: list[uuid.UUID] = []
    for probe in candidates:
        probe.claimed_at = now
        probe.claimed_by = worker_id
        claimed_ids.append(probe.probe_id)
    await session.flush()
    return claimed_ids


def _classify_quote(
    quote_raw: dict, *, out_amount_raw: int, config: ArgusConfig
) -> tuple[str, Decimal | None, bool]:
    """Real Jupiter quotes always carry ``priceImpactPct``; this project
    decides whether that impact is excessive (section 48), never Jupiter
    itself. Missing/unparseable impact data is treated leniently
    (``None``, not excessive) -- an honestly-unknown impact is not the
    same claim as a known-excessive one."""
    raw_impact = quote_raw.get("priceImpactPct")
    price_impact: Decimal | None
    try:
        price_impact = Decimal(str(raw_impact)) if raw_impact is not None else None
    except (ValueError, ArithmeticError):
        price_impact = None
    threshold = config.get("thresholds.max_price_impact_pct")
    max_impact = Decimal(str(threshold)) if threshold is not None else _DEFAULT_MAX_PRICE_IMPACT_PCT
    if price_impact is not None and price_impact > max_impact:
        return OUTCOME_PRICE_IMPACT_EXCESSIVE, price_impact, True
    if out_amount_raw <= 0:
        return OUTCOME_NO_ROUTE, price_impact, False
    return OUTCOME_SUCCESS, price_impact, True


async def _maybe_finalize_intent_no_fill(
    session: AsyncSession, *, shadow_intent_id: uuid.UUID
) -> None:
    entry_probes = (
        (
            await session.execute(
                select(ShadowQuoteProbe).where(
                    ShadowQuoteProbe.shadow_intent_id == shadow_intent_id,
                    ShadowQuoteProbe.probe_kind == PROBE_KIND_ENTRY_DELAY,
                )
            )
        )
        .scalars()
        .all()
    )
    if not entry_probes or any(p.responded_at is None for p in entry_probes):
        return
    if any(p.outcome == OUTCOME_SUCCESS for p in entry_probes):
        return
    existing_position = (
        await session.execute(
            select(ShadowPosition.shadow_position_id).where(
                ShadowPosition.shadow_intent_id == shadow_intent_id
            )
        )
    ).scalar_one_or_none()
    if existing_position is not None:
        return
    intent = await session.get(ShadowIntent, shadow_intent_id)
    if intent is not None and intent.status != STATUS_NO_FILL:
        intent.status = STATUS_NO_FILL


async def schedule_reverse_probes_for_position(
    session: AsyncSession, *, position: ShadowPosition, config: ArgusConfig, opened_at: datetime
) -> list[ShadowQuoteProbe]:
    """Schedules the reverse-executable probes for a just-opened shadow
    position (section 47's own 5m/30m/1h/6h/24h horizons) plus its mark
    outcomes (section 47's descriptive-only mark family, 5m/30m/1h/6h/
    24h/3d/7d) -- called from the SAME atomic transaction that created
    ``position``, so a position is never left without its own scheduled
    follow-up probes."""
    reverse_horizons: Sequence[str] = config.get("executable_outcome_horizons") or [
        "5m",
        "30m",
        "1h",
        "6h",
        "24h",
    ]
    mark_horizons: Sequence[str] = config.get("mark_outcome_horizons") or [
        "5m",
        "30m",
        "1h",
        "6h",
        "24h",
        "3d",
        "7d",
    ]
    probes: list[ShadowQuoteProbe] = []
    for label in reverse_horizons:
        probe = ShadowQuoteProbe(
            probe_id=uuid.uuid4(),
            probe_kind=PROBE_KIND_REVERSE_EXECUTABLE,
            target_label=label,
            target_seconds_from_observation=None,
            shadow_intent_id=None,
            shadow_position_id=position.shadow_position_id,
            input_mint=position.output_mint,
            output_mint=position.input_mint,
            notional_input_amount_raw=position.entry_output_amount_raw,
            target_due_at=opened_at + horizon_to_timedelta(label),
            outcome=OUTCOME_PENDING,
            algorithm_version=ALGORITHM_VERSION,
            created_at=opened_at,
        )
        session.add(probe)
        probes.append(probe)
    for label in mark_horizons:
        mark = ShadowMarkOutcome(
            shadow_mark_outcome_id=uuid.uuid4(),
            shadow_position_id=position.shadow_position_id,
            horizon_label=label,
            due_at=opened_at + horizon_to_timedelta(label),
            outcome=MARK_OUTCOME_PENDING,
            algorithm_version=ALGORITHM_VERSION,
            created_at=opened_at,
        )
        session.add(mark)
    await session.flush()
    return probes


async def _execute_and_record_probe(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    probe_id: uuid.UUID,
    provider: ExecutionProvider,
    config: ArgusConfig,
    clock: Clock,
    market_provider: MarketDataProvider | None = None,
    _simulate_crash_after: str | None = None,
) -> ShadowQuoteProbe:
    async with session_factory() as session:
        probe = await session.get(ShadowQuoteProbe, probe_id)
        assert probe is not None
        input_mint = probe.input_mint
        output_mint = probe.output_mint
        notional = probe.notional_input_amount_raw
        target_due_at = probe.target_due_at
        probe_kind = probe.probe_kind
        shadow_intent_id = probe.shadow_intent_id
        shadow_position_id = probe.shadow_position_id
        target_label = probe.target_label

    requested_at = clock.utc_now()
    outcome = OUTCOME_QUOTE_FAILED
    expected_output: int | None = None
    price_impact: Decimal | None = None
    route_present = False
    fee_estimate: int | None = None
    raw_quote: dict | None = None
    try:
        quote = await provider.get_quote(
            input_mint=input_mint, output_mint=output_mint, amount_raw=notional
        )
    except _ShadowQuoteError as exc:
        outcome = _ERROR_OUTCOME_MAP.get(type(exc), OUTCOME_QUOTE_FAILED)
    except Exception:  # noqa: BLE001 -- an unclassified provider failure is a real, honest QUOTE_FAILED
        outcome = OUTCOME_QUOTE_FAILED
    else:
        outcome, price_impact, route_present = _classify_quote(
            dict(quote.raw), out_amount_raw=quote.out_amount_raw, config=config
        )
        expected_output = quote.out_amount_raw if outcome != OUTCOME_NO_ROUTE else None
        fee_estimate = None
        raw_quote = dict(quote.raw)
    responded_at = clock.utc_now()

    entry_price_usd: Decimal | None = None
    if (
        probe_kind == PROBE_KIND_ENTRY_DELAY
        and outcome == OUTCOME_SUCCESS
        and market_provider is not None
    ):
        try:
            snapshot = await market_provider.token_snapshot(output_mint)
            entry_price_usd = snapshot.price_usd
        except Exception:  # noqa: BLE001 -- best-effort only; mark outcomes stay descriptive either way
            entry_price_usd = None

    if _simulate_crash_after == "quote":
        raise SimulatedWorkerCrash(f"simulated crash after quote call (probe_id={probe_id})")

    async with session_factory() as session, session.begin():
        probe = await session.get(ShadowQuoteProbe, probe_id)
        assert probe is not None
        if probe.responded_at is not None:
            # Already recorded by another worker/attempt -- idempotent
            # no-op, never a second write (section 84).
            return probe

        probe.requested_at = requested_at
        probe.responded_at = responded_at
        probe.scheduling_delay_seconds = Decimal(
            str((requested_at - target_due_at).total_seconds())
        )
        probe.latency_ms = int((responded_at - requested_at).total_seconds() * 1000)
        probe.expected_output_amount_raw = expected_output
        probe.price_impact_pct = price_impact
        probe.route_present = route_present
        probe.fee_estimate_raw = fee_estimate
        probe.outcome = outcome
        probe.raw_quote = raw_quote

        if probe_kind == PROBE_KIND_ENTRY_DELAY:
            assert shadow_intent_id is not None
            if outcome == OUTCOME_SUCCESS:
                existing_position = (
                    await session.execute(
                        select(ShadowPosition).where(
                            ShadowPosition.shadow_intent_id == shadow_intent_id
                        )
                    )
                ).scalar_one_or_none()
                if existing_position is None:
                    intent = await session.get(ShadowIntent, shadow_intent_id)
                    assert intent is not None
                    position = ShadowPosition(
                        shadow_position_id=uuid.uuid4(),
                        shadow_intent_id=shadow_intent_id,
                        wallet_id=intent.wallet_id,
                        token_id=intent.token_id,
                        input_mint=input_mint,
                        output_mint=output_mint,
                        entry_input_amount_raw=notional,
                        entry_output_amount_raw=expected_output or 0,
                        entry_price_impact_pct=price_impact,
                        entry_route_present=route_present,
                        entry_fee_estimate_raw=fee_estimate,
                        entry_price_usd=entry_price_usd,
                        entry_probe_target_label=target_label,
                        entry_requested_at=requested_at,
                        entry_responded_at=responded_at,
                        opened_at=responded_at,
                        algorithm_version=ALGORITHM_VERSION,
                        created_at=responded_at,
                    )
                    session.add(position)
                    intent.status = STATUS_FILLED
                    await session.flush()
                    await schedule_reverse_probes_for_position(
                        session, position=position, config=config, opened_at=responded_at
                    )
            else:
                await _maybe_finalize_intent_no_fill(session, shadow_intent_id=shadow_intent_id)
        else:
            assert shadow_position_id is not None

        await session.flush()
        return probe


async def run_due_entry_probes(
    session_factory: async_sessionmaker[AsyncSession],
    provider: ExecutionProvider,
    *,
    config: ArgusConfig,
    clock: Clock,
    now: datetime,
    market_provider: MarketDataProvider | None = None,
    worker_id: str = "entry-delay-worker",
    stale_after: timedelta = timedelta(seconds=30),
    limit: int = 50,
    _simulate_crash_after: str | None = None,
) -> list[ShadowQuoteProbe]:
    """Claims and executes every currently-due ``ENTRY_DELAY`` probe.
    Call repeatedly (a bounded loop, a cron tick, or a REPLAY step
    advancing a controlled clock) -- this function itself never sleeps
    or blocks waiting for a future due time. ``market_provider`` is
    optional and best-effort -- only used to capture a fill's entry
    market price for later mark-outcome computation (section 47); its
    absence or failure never blocks a shadow fill."""
    async with session_factory() as session, session.begin():
        claimed_ids = await _claim_due_probes(
            session,
            probe_kind=PROBE_KIND_ENTRY_DELAY,
            now=now,
            worker_id=worker_id,
            stale_after=stale_after,
            limit=limit,
        )
    if _simulate_crash_after == "claim":
        raise SimulatedWorkerCrash("simulated crash after claim")

    results = []
    for probe_id in claimed_ids:
        results.append(
            await _execute_and_record_probe(
                session_factory,
                probe_id=probe_id,
                provider=provider,
                config=config,
                clock=clock,
                market_provider=market_provider,
                _simulate_crash_after=_simulate_crash_after,
            )
        )
    return results


async def run_due_reverse_probes(
    session_factory: async_sessionmaker[AsyncSession],
    provider: ExecutionProvider,
    *,
    config: ArgusConfig,
    clock: Clock,
    now: datetime,
    worker_id: str = "reverse-executable-worker",
    stale_after: timedelta = timedelta(seconds=30),
    limit: int = 50,
    _simulate_crash_after: str | None = None,
) -> list[ShadowQuoteProbe]:
    """Claims and executes every currently-due ``REVERSE_EXECUTABLE``
    probe -- same claim/execute/record shape as
    :func:`run_due_entry_probes`."""
    async with session_factory() as session, session.begin():
        claimed_ids = await _claim_due_probes(
            session,
            probe_kind=PROBE_KIND_REVERSE_EXECUTABLE,
            now=now,
            worker_id=worker_id,
            stale_after=stale_after,
            limit=limit,
        )
    if _simulate_crash_after == "claim":
        raise SimulatedWorkerCrash("simulated crash after claim")

    results = []
    for probe_id in claimed_ids:
        results.append(
            await _execute_and_record_probe(
                session_factory,
                probe_id=probe_id,
                provider=provider,
                config=config,
                clock=clock,
                _simulate_crash_after=_simulate_crash_after,
            )
        )
    return results
