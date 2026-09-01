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
from datetime import datetime
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
from argus.domain.archaeology_triggers import TRIGGER_TYPE_HISTORICAL_WINNER, ArchaeologyTrigger
from argus.domain.early_buyers import EarlyBuyer
from argus.domain.wallet_discovery_events import (
    EXCLUSION_REASON_DISCOVERY_CONTAMINATION,
    WalletDiscoveryEvent,
)
from argus.domain.wallets import Wallet
from argus.wallets.early_buyer_extraction import (
    ALGORITHM_VERSION as EARLY_BUYER_ALGORITHM_VERSION,
)
from argus.wallets.early_buyer_extraction import (
    RawTransactionEvidence,
    extract_early_buyers,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from argus.config import ArgusConfig

ALGORITHM_VERSION: Final[str] = "archaeology_run_v1"
BUILD_HASH: Final[str] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


@dataclasses.dataclass(frozen=True, slots=True)
class ArchaeologyRunResult:
    run_id: uuid.UUID
    status: str
    early_buyers_recovered: int
    wallets_discovered: int


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


async def run_archaeology(
    session: AsyncSession,
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
) -> ArchaeologyRunResult:
    run_id = uuid.uuid4()
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
    await session.flush()

    try:
        candidates = extract_early_buyers(transactions, mint=mint, deployer_wallet=deployer_wallet)
    except Exception as exc:  # noqa: BLE001 -- deliberately terminal: record and re-raise nothing further
        run.status = RUN_STATUS_FAILED
        run.completed_at = now
        run.error_reason = f"{type(exc).__name__}: {exc}"[:512]
        await session.flush()
        return ArchaeologyRunResult(
            run_id=run_id, status=RUN_STATUS_FAILED, early_buyers_recovered=0, wallets_discovered=0
        )

    recovered = 0
    discovered = 0
    for candidate in candidates:
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

    if trigger_id is not None:
        trigger = (
            await session.execute(
                select(ArchaeologyTrigger).where(ArchaeologyTrigger.trigger_id == trigger_id)
            )
        ).scalar_one_or_none()
        if trigger is not None and trigger.consumed_at is None:
            trigger.consumed_at = now

    # PARTIAL is an honest, caller-asserted disclosure (e.g. "only N of a
    # known-larger evidence set was available"), never inferred from the
    # candidate count alone -- finding zero genuine early buyers in a
    # complete evidence set is still a COMPLETED run, not a failure.
    run.status = RUN_STATUS_PARTIAL if is_partial else RUN_STATUS_COMPLETED
    run.completed_at = now
    await session.flush()

    return ArchaeologyRunResult(
        run_id=run_id,
        status=run.status,
        early_buyers_recovered=recovered,
        wallets_discovered=discovered,
    )
