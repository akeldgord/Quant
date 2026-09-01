"""Archaeology run orchestration (MASTER_SPEC.md Phase 2 build items 6,
7-8, 12; required-implementation items 4-5).

``run_archaeology`` is the single orchestration path for both
``HISTORICAL_WINNER`` (a human/CLI asked ARGUS to study a specific
already-known historical winner) and ``PROSPECTIVE_WINNER`` (triggered by
``argus.wallets.watcher_service`` after a milestone crossing) archaeology.
It always creates exactly one ``archaeology_runs`` row recording its own
source/time-range/gaps/completeness/algorithm identity BEFORE doing any
extraction work, and always ends that row ``COMPLETED``, ``PARTIAL``, or
``FAILED`` -- never leaves it ``RUNNING`` on a caller exception, and never
silently discards a failed/partial prior attempt (a retry always creates
a fresh run row; ``early_buyers``/``wallet_discovery_events``'s own
idempotency keys, not this table, are what prevent duplicate OUTPUTS
across retries).

Never accesses signing material, creates a trade intent, order,
transaction, or execution side effect (this instruction's explicit
invariant 12).
"""

from __future__ import annotations

import dataclasses
import hashlib
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from argus.domain.archaeology_runs import (
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_PARTIAL,
    RUN_STATUS_RUNNING,
    ArchaeologyRun,
)
from argus.domain.archaeology_triggers import (
    TRIGGER_TYPE_HISTORICAL_WINNER,
    ArchaeologyTrigger,
)
from argus.domain.early_buyers import EarlyBuyer
from argus.domain.wallet_discovery_events import (
    DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY,
    DISCOVERY_CHANNEL_PROSPECTIVE_WINNER_ARCHAEOLOGY,
    EXCLUSION_REASON_DISCOVERY_CONTAMINATION,
    WalletDiscoveryEvent,
)
from argus.domain.wallets import Wallet
from argus.wallets.early_buyer_extraction import (
    ALGORITHM_VERSION as EARLY_BUYER_ALGORITHM_VERSION,
)
from argus.wallets.early_buyer_extraction import (
    OWNERSHIP_SIGNER_WALLET,
    RawTransactionEvidence,
    extract_early_buyers,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from argus.config import ArgusConfig

ALGORITHM_VERSION: Final[str] = "archaeology_run_v2"
BUILD_HASH: Final[str] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


@dataclasses.dataclass(frozen=True, slots=True)
class ArchaeologyRunResult:
    run_id: uuid.UUID
    status: str
    early_buyers_recovered: int
    wallets_discovered: int
    unresolved_ownership_count: int


async def _get_or_create_wallet(
    session: AsyncSession, *, wallet_address: str, now: datetime
) -> Wallet:
    existing = (
        await session.execute(select(Wallet).where(Wallet.wallet_address == wallet_address))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    wallet = Wallet(
        wallet_id=uuid.uuid4(),
        wallet_address=wallet_address,
        first_discovered_at=now,
        created_at=now,
    )
    session.add(wallet)
    await session.flush()
    return wallet


async def _record_discovery_event(
    session: AsyncSession,
    *,
    wallet_id: uuid.UUID,
    discovery_channel: str,
    trigger_token_id: uuid.UUID,
    trigger_event: str | None,
    trigger_reason: str,
    algorithm_version: str,
    now: datetime,
) -> bool:
    stmt = (
        pg_insert(WalletDiscoveryEvent)
        .values(
            discovery_event_id=uuid.uuid4(),
            wallet_id=wallet_id,
            discovered_at=now,
            discovery_channel=discovery_channel,
            trigger_token_id=trigger_token_id,
            trigger_wallet_id=None,
            trigger_event=trigger_event,
            trigger_reason=trigger_reason,
            algorithm_version=algorithm_version,
            exclusion_reason=EXCLUSION_REASON_DISCOVERY_CONTAMINATION,
            created_at=now,
        )
        .on_conflict_do_nothing(
            index_elements=["wallet_id", "discovery_channel", "trigger_token_id"]
        )
        .returning(WalletDiscoveryEvent.discovery_event_id)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    await session.flush()
    return row is not None


async def _record_early_buyer(
    session: AsyncSession,
    *,
    token_id: uuid.UUID,
    wallet_id: uuid.UUID,
    run_id: uuid.UUID,
    candidate: Any,
    now: datetime,
) -> bool:
    stmt = (
        pg_insert(EarlyBuyer)
        .values(
            early_buyer_id=uuid.uuid4(),
            token_id=token_id,
            wallet_id=wallet_id,
            source_run_id=run_id,
            first_buy_slot=candidate.first_buy_slot,
            first_buy_time=candidate.first_buy_time,
            sequence_number=candidate.sequence_number,
            venue=None,
            lifecycle_stage=None,
            entry_price_estimate=None,
            entry_market_state_confidence=None,
            token_age_seconds=None,
            amount_raw=candidate.amount_raw,
            amount_decimals=candidate.amount_decimals,
            usd_estimate=None,
            possible_deployer=candidate.possible_deployer,
            possible_insider=False,
            possible_bundler=False,
            possible_funder_related=False,
            possible_bot=False,
            evidence_reference=candidate.evidence_reference,
            algorithm_version=EARLY_BUYER_ALGORITHM_VERSION,
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["token_id", "wallet_id"])
        .returning(EarlyBuyer.early_buyer_id)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    await session.flush()
    return row is not None


async def get_or_create_historical_trigger(
    session: AsyncSession, *, token_id: uuid.UUID, trigger_reason: str, now: datetime
) -> uuid.UUID:
    """At most one ``HISTORICAL_WINNER`` trigger may ever exist per token
    (the migration's partial unique index enforces this); a second call
    for the same token returns the existing trigger id rather than
    creating a duplicate."""
    trigger_id = uuid.uuid4()
    stmt = (
        pg_insert(ArchaeologyTrigger)
        .values(
            trigger_id=trigger_id,
            token_id=token_id,
            trigger_type=TRIGGER_TYPE_HISTORICAL_WINNER,
            source_milestone_id=None,
            trigger_reason=trigger_reason,
            algorithm_version=ALGORITHM_VERSION,
            created_at=now,
            consumed_at=None,
        )
        .on_conflict_do_nothing(
            index_elements=["token_id"],
            index_where=ArchaeologyTrigger.trigger_type == TRIGGER_TYPE_HISTORICAL_WINNER,
        )
        .returning(ArchaeologyTrigger.trigger_id)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is not None:
        await session.flush()
        return uuid.UUID(str(row))

    existing = (
        await session.execute(
            select(ArchaeologyTrigger.trigger_id).where(
                ArchaeologyTrigger.token_id == token_id,
                ArchaeologyTrigger.trigger_type == TRIGGER_TYPE_HISTORICAL_WINNER,
            )
        )
    ).scalar_one()
    return uuid.UUID(str(existing))


class _SimulatedWorkerCrash(RuntimeError):
    """Test-only fault injection (P2-R6): raised by :func:`run_archaeology`
    when its private ``_simulate_crash_after`` hook matches a just-
    committed phase, to deterministically prove restart-recovery behavior
    without needing to actually kill a process. The parameter defaults to
    ``None`` and no production caller (CLI or service) ever sets it."""


async def run_archaeology(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    token_id: uuid.UUID,
    mint: str,
    run_type: str,
    transactions: list[RawTransactionEvidence],
    discovery_channel: str,
    source_provider_set: str,
    input_evidence_reference: str,
    time_range_start: datetime | None,
    time_range_end: datetime | None,
    known_gaps: str | None,
    completeness_statement: str,
    config: ArgusConfig,
    git_commit: str,
    now: datetime,
    trigger_id: uuid.UUID | None = None,
    deployer_wallet: str | None = None,
    winner_definition_version: str | None = None,
    is_partial: bool = False,
    _simulate_crash_after: str | None = None,
) -> ArchaeologyRunResult:
    """Runs one archaeology job across three independently-committing
    transaction phases (P2-R6) so a worker-process crash at any point
    leaves genuine, queryable evidence rather than everything rolling
    back together (the pre-remediation design did all of "claim ->
    extract -> persist outputs -> terminalize" inside a single caller-
    supplied transaction, so a crash before that one transaction's final
    commit lost even the fact that a RUNNING attempt had ever started):

    1. **claim** -- insert the ``archaeology_runs`` row as ``RUNNING`` and
       commit it alone. A concurrent duplicate ``trigger_id`` claim fails
       here with an ``IntegrityError`` (the partial unique index is the
       real exclusivity mechanism; the caller/service layer treats that
       as a benign "someone else already claimed it," per this
       instruction's "duplicate delivery is expected and safe").
    2. **extract + persist outputs** -- pure extraction, then
       wallets/wallet_discovery_events/early_buyers, committed together
       and alone. The run row is still ``RUNNING`` when this commits --
       outputs are durable and queryable even before terminalization.
    3. **terminalize** -- flip the run to its terminal status, consume
       the trigger if any, commit alone.

    A crash between any two phases leaves the run genuinely ``RUNNING``
    with whatever the last committed phase produced -- never silently
    lost, never a phantom "as if it never started." A separate reaper
    (:func:`reap_stale_archaeology_runs`) is what a restart/operator uses
    to recognize and terminalize such a stale attempt; a fresh retry
    (new ``run_id``) is always safe regardless, since every output table's
    own idempotency key (not this function) is what prevents duplicate
    canonical output across retries."""
    run_id = uuid.uuid4()

    # Phase 1: claim -- committed alone.
    async with session_factory() as session, session.begin():
        run = ArchaeologyRun(
            run_id=run_id,
            token_id=token_id,
            trigger_id=trigger_id,
            run_type=run_type,
            source_provider_set=source_provider_set,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
            input_evidence_reference=input_evidence_reference,
            known_gaps=known_gaps,
            completeness_statement=completeness_statement,
            winner_definition_version=winner_definition_version,
            status=RUN_STATUS_RUNNING,
            started_at=now,
            completed_at=None,
            error_reason=None,
            algorithm_version=ALGORITHM_VERSION,
            build_hash=BUILD_HASH,
            config_hash=config.config_hash,
            master_spec_hash=config.spec_hash,
            git_commit=git_commit,
            created_at=now,
        )
        session.add(run)
    if _simulate_crash_after == "claim":
        raise _SimulatedWorkerCrash(f"simulated crash after claim (run_id={run_id})")

    try:
        candidates = extract_early_buyers(transactions, mint=mint, deployer_wallet=deployer_wallet)
    except Exception as exc:  # noqa: BLE001 -- deliberately terminal: record and re-raise nothing further
        async with session_factory() as session, session.begin():
            failed_run = await session.get(ArchaeologyRun, run_id)
            assert failed_run is not None
            failed_run.status = RUN_STATUS_FAILED
            failed_run.completed_at = now
            failed_run.error_reason = f"{type(exc).__name__}: {exc}"[:512]
        return ArchaeologyRunResult(
            run_id=run_id,
            status=RUN_STATUS_FAILED,
            early_buyers_recovered=0,
            wallets_discovered=0,
            unresolved_ownership_count=0,
        )

    # Phase 2: extract + persist outputs -- committed alone. The run row
    # is still RUNNING at this point; outputs are already durable.
    recovered = 0
    discovered = 0
    unresolved_ownership_count = 0
    async with session_factory() as session, session.begin():
        for candidate in candidates:
            # P2-R3: only a candidate whose owner is itself a transaction
            # signer (a genuine, evidence-grounded proxy for "authorized
            # this token receipt," which a program-derived reserve/curve/
            # pool/vault account can never be) is promoted to a wallet
            # candidate. An unresolved/non-signer observation is never
            # invented into wallets/wallet_discovery_events/early_buyers --
            # its raw evidence remains fully preserved and re-derivable
            # from the same immutable committed transaction bytes, just
            # not promoted to candidacy (MASTER_SPEC.md section 33's
            # "tag, do not delete" rule governs tagging an accepted
            # wallet, not inventing candidacy for a non-wallet account).
            if candidate.ownership_classification != OWNERSHIP_SIGNER_WALLET:
                unresolved_ownership_count += 1
                continue
            wallet = await _get_or_create_wallet(
                session, wallet_address=candidate.wallet_address, now=now
            )
            was_new_discovery = await _record_discovery_event(
                session,
                wallet_id=wallet.wallet_id,
                discovery_channel=discovery_channel,
                trigger_token_id=token_id,
                trigger_event=str(run_id),
                trigger_reason=f"early buyer of {mint} recovered by archaeology run {run_id}",
                algorithm_version=ALGORITHM_VERSION,
                now=now,
            )
            if was_new_discovery:
                discovered += 1
            was_new_buyer = await _record_early_buyer(
                session,
                token_id=token_id,
                wallet_id=wallet.wallet_id,
                run_id=run_id,
                candidate=candidate,
                now=now,
            )
            if was_new_buyer:
                recovered += 1
    if _simulate_crash_after == "outputs":
        raise _SimulatedWorkerCrash(f"simulated crash after outputs (run_id={run_id})")

    # Phase 3: terminalize -- committed alone.
    async with session_factory() as session, session.begin():
        final_run = await session.get(ArchaeologyRun, run_id)
        assert final_run is not None
        if unresolved_ownership_count:
            note = (
                f"[P2-R3] {unresolved_ownership_count} net-positive observation(s) had "
                "unresolved/non-signer ownership (e.g. a program-derived reserve/curve/pool/"
                "vault account) and were never promoted to wallet candidacy -- fully "
                "re-derivable from the same input evidence, never erased."
            )
            final_run.known_gaps = (
                f"{final_run.known_gaps}\n{note}" if final_run.known_gaps else note
            )

        if trigger_id is not None:
            trigger = (
                await session.execute(
                    select(ArchaeologyTrigger).where(ArchaeologyTrigger.trigger_id == trigger_id)
                )
            ).scalar_one_or_none()
            if trigger is not None and trigger.consumed_at is None:
                trigger.consumed_at = now

        # PARTIAL is an honest, caller-asserted disclosure (e.g. "only N
        # of a known-larger evidence set was available"), never inferred
        # from the candidate count alone -- finding zero genuine early
        # buyers in a complete evidence set is still a COMPLETED run,
        # not a failure.
        final_run.status = RUN_STATUS_PARTIAL if is_partial else RUN_STATUS_COMPLETED
        final_run.completed_at = now
        final_status = final_run.status
    # Deliberately raised AFTER the `async with` block above has already
    # committed: "crash during/after the terminal commit" is only ever
    # meaningfully distinct from "crash before it" once the commit has
    # actually landed durably -- the client dying in the narrow window
    # after a successful commit but before it observes the result is a
    # real scenario (e.g. a network partition on the ack), and proves
    # the terminal state is already durable and correct in the database
    # regardless of what happens to the caller afterward.
    if _simulate_crash_after == "terminalize":
        raise _SimulatedWorkerCrash(f"simulated crash after terminalize commit (run_id={run_id})")

    return ArchaeologyRunResult(
        run_id=run_id,
        status=final_status,
        early_buyers_recovered=recovered,
        wallets_discovered=discovered,
        unresolved_ownership_count=unresolved_ownership_count,
    )


async def reap_stale_archaeology_runs(
    session: AsyncSession, *, older_than: timedelta, now: datetime
) -> list[uuid.UUID]:
    """P2-R6 restart recovery: finds every ``archaeology_runs`` row still
    ``RUNNING`` after ``older_than`` has elapsed since ``started_at`` --
    the signature of a worker that crashed mid-run (a genuinely still-
    active run is bounded by ``older_than`` in practice; callers choose
    it generously relative to how long a real run takes) -- and marks
    each ``FAILED`` with an honest ``error_reason``, never resuming or
    guessing at partial completion. A fresh retry (a new ``run_archaeology``
    call, a new ``run_id``) is always the safe next step: every output
    table's own idempotency key means re-deriving the same evidence never
    duplicates whatever the crashed attempt already durably wrote in its
    own "extract + persist outputs" phase. Caller owns the transaction
    (a single atomic sweep, no multi-phase durability concern of its own)."""
    threshold = now - older_than
    stale = (
        (
            await session.execute(
                select(ArchaeologyRun).where(
                    ArchaeologyRun.status == RUN_STATUS_RUNNING,
                    ArchaeologyRun.started_at < threshold,
                )
            )
        )
        .scalars()
        .all()
    )
    reaped: list[uuid.UUID] = []
    for run in stale:
        run.status = RUN_STATUS_FAILED
        run.completed_at = now
        run.error_reason = (
            f"reaped as stale: status was still RUNNING more than {older_than} after "
            "started_at (worker crash or abnormal termination inferred, not directly "
            "observed) -- retry by starting a fresh archaeology run for this token"
        )[:512]
        reaped.append(run.run_id)
    await session.flush()
    return reaped


async def find_pending_archaeology_trigger(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    token_id: uuid.UUID,
    trigger_type: str | None = None,
) -> ArchaeologyTrigger | None:
    """The single oldest not-yet-consumed trigger for ``token_id`` (P2-R5:
    the piece a human previously had to find and copy a trigger ID for by
    hand). ``trigger_type=None`` matches either type, oldest first."""
    async with session_factory() as session:
        conditions = [
            ArchaeologyTrigger.token_id == token_id,
            ArchaeologyTrigger.consumed_at.is_(None),
        ]
        if trigger_type is not None:
            conditions.append(ArchaeologyTrigger.trigger_type == trigger_type)
        return (
            await session.execute(
                select(ArchaeologyTrigger)
                .where(*conditions)
                .order_by(ArchaeologyTrigger.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()


async def run_next_pending_trigger(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    token_id: uuid.UUID,
    mint: str,
    transactions: list[RawTransactionEvidence],
    source_provider_set: str,
    known_gaps: str | None,
    completeness_statement: str,
    config: ArgusConfig,
    git_commit: str,
    now: datetime,
    trigger_type: str | None = None,
    deployer_wallet: str | None = None,
    is_partial: bool = False,
) -> ArchaeologyRunResult | None:
    """P2-R5 automatic trigger execution: finds the next pending trigger
    for ``token_id`` itself (never a human-supplied trigger ID) and runs
    it through the same durable :func:`run_archaeology` path. Returns
    ``None`` (a legitimate, non-error outcome) when there is no pending
    trigger to consume -- the caller/service loop simply tries again
    later; this is the bounded per-call unit a service loop or
    ``argus discover run-pending-trigger`` composes into a longer-running
    sweep. A trigger claimed by a concurrent caller between the lookup
    above and this call's own "claim" phase surfaces as the same
    ``IntegrityError`` :func:`run_archaeology` already documents --
    duplicate delivery is expected and safe, never fatal."""
    trigger = await find_pending_archaeology_trigger(
        session_factory, token_id=token_id, trigger_type=trigger_type
    )
    if trigger is None:
        return None

    discovery_channel = (
        DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY
        if trigger.trigger_type == TRIGGER_TYPE_HISTORICAL_WINNER
        else DISCOVERY_CHANNEL_PROSPECTIVE_WINNER_ARCHAEOLOGY
    )
    return await run_archaeology(
        session_factory,
        token_id=token_id,
        mint=mint,
        run_type=trigger.trigger_type,
        transactions=transactions,
        discovery_channel=discovery_channel,
        source_provider_set=source_provider_set,
        input_evidence_reference=", ".join(tx.evidence_reference for tx in transactions) or "none",
        time_range_start=None,
        time_range_end=None,
        known_gaps=known_gaps,
        completeness_statement=completeness_statement,
        config=config,
        git_commit=git_commit,
        now=now,
        trigger_id=trigger.trigger_id,
        deployer_wallet=deployer_wallet,
        is_partial=is_partial,
    )


async def run_all_pending_triggers_for_token(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    token_id: uuid.UUID,
    mint: str,
    transactions: list[RawTransactionEvidence],
    source_provider_set: str,
    known_gaps: str | None,
    completeness_statement: str,
    config: ArgusConfig,
    git_commit: str,
    now: datetime,
    max_triggers: int = 10,
    trigger_type: str | None = None,
    deployer_wallet: str | None = None,
    is_partial: bool = False,
) -> list[ArchaeologyRunResult]:
    """Bounded (P2-R5's explicit "bounded" requirement) sweep: repeatedly
    consumes the next pending trigger for ``token_id`` until none remain
    or ``max_triggers`` runs have been produced -- never an unbounded
    loop. Each individual run is independently durable
    (:func:`run_archaeology`'s own three-phase design); a crash partway
    through the sweep simply leaves fewer runs completed than
    ``max_triggers``, safely resumable by calling this again."""
    results: list[ArchaeologyRunResult] = []
    for _ in range(max_triggers):
        result = await run_next_pending_trigger(
            session_factory,
            token_id=token_id,
            mint=mint,
            transactions=transactions,
            source_provider_set=source_provider_set,
            known_gaps=known_gaps,
            completeness_statement=completeness_statement,
            config=config,
            git_commit=git_commit,
            now=now,
            trigger_type=trigger_type,
            deployer_wallet=deployer_wallet,
            is_partial=is_partial,
        )
        if result is None:
            break
        results.append(result)
    return results
