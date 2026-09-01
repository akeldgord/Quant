"""Real acquisition-run execution + verified load-by-ID (P3-R1/P3-R2
remediation round 2, `argus-phase-3-remediation-002`).

:func:`run_wallet_acquisition` composes the existing Phase 2
``acquire_historical_transactions`` (wallet-address walk) with
``ChainProvider.get_token_accounts`` (associated-account enumeration)
plus a per-account walk for each returned account, feeds every uniquely-
signed transaction through the existing raw-preservation/parser
machinery (``ChainEvent`` + ``parse_transaction`` + ``SqlSwapRecorder`` --
never a new provider/parsing framework), and persists one immutable
``WalletAcquisitionRun`` manifest record with an explicit wallet binding.

:func:`load_verified_acquisition_manifest` is the ONLY way a score
computation may obtain an :class:`~argus.wallets.history_reconstruction.
AcquisitionManifest` for ``LIVE_ACQUISITION_WALK`` evidence: it loads a
persisted run by ``run_id``, verifies the run genuinely belongs to the
wallet being scored and was not observed after the score's own ``as_of``
("a run from another wallet or learned after T cannot justify history at
T" -- this instruction's own explicit requirement), and only then
reconstructs the typed manifest from the verified row. There is no path
from an arbitrary caller-supplied file/JSON to a manifest any more (the
P3-R2 defect this replaces).
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from argus.domain.chain_events import ChainEvent
from argus.domain.wallet_acquisition_runs import WalletAcquisitionRun
from argus.ingestion.parse_ledger import payload_hash
from argus.ingestion.swap_repository import SqlSwapRecorder
from argus.parsing.generic_parser import PARSER_BUILD_HASH, PARSER_VERSION, parse_transaction
from argus.tokens.historical_acquisition import AcquisitionResult, acquire_historical_transactions
from argus.wallets.history_reconstruction import (
    AcquisitionManifest,
    TokenAccountCoverage,
    manifest_as_dict,
    manifest_from_dict,
)

if TYPE_CHECKING:
    from argus.providers import ChainProvider

ALGORITHM_VERSION: Final[str] = "wallet_acquisition_v1"
EVENT_TYPE_TRANSACTION_OBSERVED: Final[str] = "TRANSACTION_OBSERVED"


@dataclasses.dataclass(frozen=True, slots=True)
class AcquisitionRunOutcome:
    run_id: uuid.UUID
    manifest: AcquisitionManifest
    transactions_persisted: int
    transactions_already_known: int


async def run_wallet_acquisition(
    provider: ChainProvider,
    session: AsyncSession,
    *,
    wallet_id: uuid.UUID,
    wallet_address: str,
    provider_name: str,
    max_pages: int = 50,
    page_size: int = 1000,
    now: datetime,
) -> AcquisitionRunOutcome:
    """Actually executes the wallet-address walk plus every associated
    token-account walk, persists every newly-seen transaction as real
    ``chain_events``/``swaps`` rows (never merely blessing an unrelated
    pre-existing fragment), and persists one immutable
    ``WalletAcquisitionRun`` manifest row. Never invokes a live/paid
    provider itself -- ``provider`` is supplied by the caller, which
    remains responsible for fail-closed credential handling exactly as
    every other live Phase 1/2 command already does."""
    wallet_result = await acquire_historical_transactions(
        provider, address=wallet_address, max_pages=max_pages, page_size=page_size
    )

    token_accounts_enumerated = False
    enumeration_error: str | None = None
    account_coverage: list[TokenAccountCoverage] = []
    account_results: list[AcquisitionResult] = []
    try:
        accounts = await provider.get_token_accounts(wallet_address)
        token_accounts_enumerated = True
    except Exception as exc:  # noqa: BLE001 -- provider-boundary fault, recorded not re-raised
        accounts = []
        enumeration_error = f"token-account enumeration failed: {type(exc).__name__}: {exc}"

    for account in accounts:
        result = await acquire_historical_transactions(
            provider, address=account.pubkey, max_pages=max_pages, page_size=page_size
        )
        account_results.append(result)
        account_coverage.append(
            TokenAccountCoverage(
                pubkey=account.pubkey,
                mint=account.mint,
                owner=account.owner,
                status=result.status,
            )
        )

    # Feed every uniquely-signed transaction (wallet walk + every account
    # walk) through the real raw-preservation/parser machinery.
    seen_signatures: set[str] = set()
    persisted = 0
    already_known = 0
    all_evidence = [
        *wallet_result.transactions,
        *(t for r in account_results for t in r.transactions),
    ]
    for evidence in all_evidence:
        if evidence.signature in seen_signatures:
            continue
        seen_signatures.add(evidence.signature)
        existing_event_id = (
            await session.execute(
                select(ChainEvent.event_id).where(
                    ChainEvent.transaction_signature == evidence.signature,
                    ChainEvent.wallet_address == wallet_address,
                    ChainEvent.event_type == EVENT_TYPE_TRANSACTION_OBSERVED,
                )
            )
        ).scalar_one_or_none()
        if existing_event_id is not None:
            already_known += 1
            continue
        event_id = uuid.uuid4()
        session.add(
            ChainEvent(
                event_id=event_id,
                chain="solana",
                slot=evidence.slot,
                block_time=evidence.block_time,
                first_seen_at=now,
                provider=provider_name,
                provider_received_at=now,
                transaction_signature=evidence.signature,
                event_type=EVENT_TYPE_TRANSACTION_OBSERVED,
                wallet_address=wallet_address,
                raw_payload=evidence.raw,
                payload_hash=payload_hash(evidence.raw),
                parser_version=PARSER_VERSION,
                created_at=now,
            )
        )
        await session.flush()
        try:
            parsed = parse_transaction(
                evidence.raw,
                wallet_address=wallet_address,
                slot=evidence.slot,
                block_time=evidence.block_time,
            )
        except Exception:  # noqa: BLE001 -- unparseable evidence is not fatal to the whole run
            continue
        await SqlSwapRecorder(session).record(
            event_id=event_id,
            wallet_address=wallet_address,
            parsed=parsed,
            build_hash=PARSER_BUILD_HASH,
            created_at=now,
        )
        persisted += 1

    manifest = AcquisitionManifest(
        wallet_walk_status=wallet_result.status,
        token_accounts_enumerated=token_accounts_enumerated,
        associated_token_accounts=tuple(account_coverage),
        provider_set=provider_name,
        known_gaps=(
            "; ".join(
                part
                for part in (
                    wallet_result.known_gaps,
                    enumeration_error,
                    *(r.known_gaps for r in account_results if r.known_gaps),
                )
                if part
            )
            or None
        ),
        evidence_reference=f"wallet_acquisition:{wallet_address}:{now.isoformat()}",
    )

    run = WalletAcquisitionRun(
        run_id=uuid.uuid4(),
        wallet_id=wallet_id,
        observation_cutoff=now,
        manifest=manifest_as_dict(manifest),
        algorithm_version=ALGORITHM_VERSION,
        created_at=now,
    )
    session.add(run)
    await session.flush()

    return AcquisitionRunOutcome(
        run_id=run.run_id,
        manifest=manifest,
        transactions_persisted=persisted,
        transactions_already_known=already_known,
    )


class AcquisitionRunVerificationError(ValueError):
    """Raised by :func:`load_verified_acquisition_manifest` when the
    requested run does not exist, belongs to a different wallet, or was
    observed after the score's own ``as_of`` -- never silently ignored or
    downgraded to a weaker completeness instead."""


async def load_verified_acquisition_manifest(
    session: AsyncSession, *, run_id: uuid.UUID, wallet_id: uuid.UUID, as_of: datetime
) -> AcquisitionManifest:
    """The only path from a persisted acquisition run to a usable
    :class:`AcquisitionManifest`: loads the run, verifies it genuinely
    belongs to ``wallet_id`` and was not observed after ``as_of``, then
    reconstructs the manifest from the verified row's own JSONB -- never
    from caller-supplied JSON."""
    run = (
        await session.execute(
            select(WalletAcquisitionRun).where(WalletAcquisitionRun.run_id == run_id)
        )
    ).scalar_one_or_none()
    if run is None:
        raise AcquisitionRunVerificationError(
            f"no wallet_acquisition_runs row for run_id={run_id} -- an acquisition run must "
            "actually be executed and persisted (see 'argus wallets acquire-history') before "
            "it can be used as LIVE_ACQUISITION_WALK evidence"
        )
    if run.wallet_id != wallet_id:
        raise AcquisitionRunVerificationError(
            f"acquisition run {run_id} belongs to wallet_id={run.wallet_id}, not the wallet "
            f"being scored (wallet_id={wallet_id}) -- a run from another wallet can never "
            "justify this wallet's history"
        )
    if run.observation_cutoff > as_of:
        raise AcquisitionRunVerificationError(
            f"acquisition run {run_id} was observed at {run.observation_cutoff.isoformat()}, "
            f"after this score's own as_of ({as_of.isoformat()}) -- evidence learned after T "
            "can never justify history known at T"
        )
    return manifest_from_dict(run.manifest)
