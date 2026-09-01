"""Real acquisition-run execution + verified load-by-ID (P3-R1/P3-R2,
`argus-phase-3-remediation-002`, deepened by `argus-phase-3-remediation-003`).

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
T"), decodes the manifest fail-closed (see ``history_reconstruction.
manifest_from_dict``), and then independently re-verifies every
``acquired_evidence`` entry against the REAL ``chain_events``/``swaps``
rows it claims to reference -- never trusting the persisted JSONB summary
alone (round-2 audit `argus-phase-3-remediation-audit-002`'s own named
defect: "a successful address walk can therefore be marked COMPLETE/HIGH
even when an acquired transaction raised in parsing, or when an
already-known chain event was skipped without proving it supplies the
required parsed input").
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from argus.domain.chain_events import ChainEvent
from argus.domain.swaps import Swap
from argus.domain.wallet_acquisition_runs import WalletAcquisitionRun
from argus.ingestion.parse_ledger import payload_hash
from argus.ingestion.swap_repository import SqlSwapRecorder
from argus.parsing.generic_parser import PARSER_BUILD_HASH, PARSER_VERSION, parse_transaction
from argus.tokens.historical_acquisition import (
    STATUS_FAILED,
    AcquisitionResult,
    acquire_historical_transactions,
)
from argus.wallets.history_reconstruction import (
    EVIDENCE_OUTCOME_ALREADY_KNOWN_VERIFIED,
    EVIDENCE_OUTCOME_PARSE_FAILED,
    EVIDENCE_OUTCOME_PARSED,
    EVIDENCE_OUTCOME_PAYLOAD_HASH_MISMATCH,
    AcquiredEvidenceRecord,
    AcquisitionManifest,
    ManifestDecodeError,
    TokenAccountCoverage,
    WalkStats,
    manifest_as_dict,
    manifest_from_dict,
)

if TYPE_CHECKING:
    from argus.providers import ChainProvider
    from argus.wallets.early_buyer_extraction import RawTransactionEvidence

ALGORITHM_VERSION: Final[str] = "wallet_acquisition_v2"
EVENT_TYPE_TRANSACTION_OBSERVED: Final[str] = "TRANSACTION_OBSERVED"


@dataclasses.dataclass(frozen=True, slots=True)
class AcquisitionRunOutcome:
    run_id: uuid.UUID
    manifest: AcquisitionManifest
    transactions_persisted: int
    transactions_already_known: int


def _walk_stats(result: AcquisitionResult) -> WalkStats:
    return WalkStats(
        status=result.status,
        known_gaps=result.known_gaps,
        pages_fetched=result.pages_fetched,
        signatures_seen=result.signatures_seen,
        transaction_fetch_failures=result.transaction_fetch_failures,
        expected_oldest_slot=result.expected_oldest_slot,
        boundary_satisfied=result.boundary_satisfied,
    )


async def _persisted_swap_id(
    session: AsyncSession, *, event_id: uuid.UUID, parser_version: str, build_hash: str
) -> uuid.UUID | None:
    """The real ``swaps.swap_id`` for this exact ``(event_id,
    parser_version, build_hash)`` artifact identity, however it got
    there -- ``SqlSwapRecorder.record`` itself only returns whether ITS
    OWN insert was new or a duplicate, never the row id either way, so
    this is the one place both cases resolve to the same real,
    machine-resolvable reference this manifest commits to."""
    return (
        await session.execute(
            select(Swap.swap_id).where(
                Swap.event_id == event_id,
                Swap.parser_version == parser_version,
                Swap.build_hash == build_hash,
            )
        )
    ).scalar_one_or_none()


async def run_wallet_acquisition(
    provider: ChainProvider,
    session: AsyncSession,
    *,
    wallet_id: uuid.UUID,
    wallet_address: str,
    provider_name: str,
    max_pages: int = 50,
    page_size: int = 1000,
    expected_oldest_slot: int | None = None,
    now: datetime,
) -> AcquisitionRunOutcome:
    """Actually executes the wallet-address walk plus every associated
    token-account walk, persists every newly-seen transaction as real
    ``chain_events``/``swaps`` rows (never merely blessing an unrelated
    pre-existing fragment), and persists one immutable
    ``WalletAcquisitionRun`` manifest row naming the run's own exact
    evidence set. Never invokes a live/paid provider itself --
    ``provider`` is supplied by the caller, which remains responsible for
    fail-closed credential handling exactly as every other live Phase 1/2
    command already does.

    ``expected_oldest_slot`` (P3-R2 remediation round 3): an optional,
    caller-supplied, machine-checkable boundary for the wallet-address
    walk only (mirroring Phase 2's own `--expected-oldest-slot`) -- when
    omitted, the exact prior no-boundary semantics are unchanged.
    """
    # Generated FIRST (P3-R2 remediation round 3, required implementation
    # item 3) so history/score provenance can identify this exact run
    # from the moment its own evidence starts being gathered, not merely
    # once persistence succeeds at the end.
    run_id = uuid.uuid4()

    wallet_result = await acquire_historical_transactions(
        provider,
        address=wallet_address,
        max_pages=max_pages,
        page_size=page_size,
        expected_oldest_slot=expected_oldest_slot,
    )

    token_accounts_enumerated = False
    enumeration_error: str | None = None
    account_coverage: list[TokenAccountCoverage] = []
    # (source_address, transaction) pairs feeding the shared evidence
    # loop below -- keeps each acquired signature attributable to
    # exactly the walk (wallet address or one token account) it came
    # from, per required implementation item 2's own "address" field.
    account_transactions: list[tuple[str, RawTransactionEvidence]] = []
    try:
        accounts = await provider.get_token_accounts(wallet_address)
        token_accounts_enumerated = True
    except Exception as exc:  # noqa: BLE001 -- provider-boundary fault, recorded not re-raised
        accounts = []
        enumeration_error = f"token-account enumeration failed: {type(exc).__name__}: {exc}"

    for account in accounts:
        if account.owner != wallet_address:
            # P3-R2 remediation round 3, required implementation item 5:
            # never trust an account the provider claims to enumerate
            # for this wallet without an exact on-chain owner match --
            # excluded from usable coverage, never silently folded in.
            account_coverage.append(
                TokenAccountCoverage(
                    pubkey=account.pubkey,
                    mint=account.mint,
                    owner=account.owner,
                    status=STATUS_FAILED,
                    walk=WalkStats(
                        status=STATUS_FAILED,
                        known_gaps=(
                            f"account owner {account.owner!r} does not match the wallet "
                            f"being acquired ({wallet_address!r}) -- excluded from coverage"
                        ),
                        pages_fetched=0,
                        signatures_seen=0,
                        transaction_fetch_failures=0,
                        expected_oldest_slot=None,
                        boundary_satisfied=None,
                    ),
                )
            )
            continue
        result = await acquire_historical_transactions(
            provider, address=account.pubkey, max_pages=max_pages, page_size=page_size
        )
        account_transactions.extend((account.pubkey, t) for t in result.transactions)
        account_coverage.append(
            TokenAccountCoverage(
                pubkey=account.pubkey,
                mint=account.mint,
                owner=account.owner,
                status=result.status,
                walk=_walk_stats(result),
            )
        )

    # Feed every uniquely-signed transaction (wallet walk + every account
    # walk) through the real raw-preservation/parser machinery, and
    # record the EXACT fate of each one -- required implementation item
    # 2's own "raw/parser input set used for reconstruction."
    seen_signatures: set[str] = set()
    persisted = 0
    already_known = 0
    acquired_evidence: list[AcquiredEvidenceRecord] = []
    all_evidence: list[tuple[str, RawTransactionEvidence]] = [
        *((wallet_address, t) for t in wallet_result.transactions),
        *account_transactions,
    ]
    for source_address, evidence in all_evidence:
        if evidence.signature in seen_signatures:
            continue
        seen_signatures.add(evidence.signature)
        computed_hash = payload_hash(evidence.raw)

        existing_event = (
            await session.execute(
                select(ChainEvent).where(
                    ChainEvent.transaction_signature == evidence.signature,
                    ChainEvent.wallet_address == wallet_address,
                    ChainEvent.event_type == EVENT_TYPE_TRANSACTION_OBSERVED,
                )
            )
        ).scalar_one_or_none()

        if existing_event is not None:
            already_known += 1
            # P3-R2 remediation round 3, required implementation item 4:
            # never use event existence alone as proof -- verify the
            # existing raw payload genuinely matches what this walk just
            # re-observed for the same signature.
            if existing_event.payload_hash != computed_hash:
                acquired_evidence.append(
                    AcquiredEvidenceRecord(
                        address=source_address,
                        signature=evidence.signature,
                        slot=evidence.slot,
                        chain_event_id=str(existing_event.event_id),
                        payload_hash=existing_event.payload_hash,
                        parser_outcome=EVIDENCE_OUTCOME_PAYLOAD_HASH_MISMATCH,
                        parser_version=None,
                        build_hash=None,
                        derived_swap_id=None,
                    )
                )
                continue
            existing_swap_row = (
                await session.execute(
                    select(Swap.swap_id, Swap.parser_version, Swap.build_hash)
                    .where(Swap.event_id == existing_event.event_id)
                    .limit(1)
                )
            ).one_or_none()
            if existing_swap_row is not None:
                # P3-R2 remediation round 4 (required implementation item
                # 1, "record the selected swap's actual parser version and
                # build hash, rather than null metadata"): this manifest
                # commits to the REAL historical artifact identity that
                # produced the already-persisted swap -- never today's
                # PARSER_VERSION/PARSER_BUILD_HASH, and never null.
                existing_swap_id, existing_parser_version, existing_build_hash = existing_swap_row
                acquired_evidence.append(
                    AcquiredEvidenceRecord(
                        address=source_address,
                        signature=evidence.signature,
                        slot=evidence.slot,
                        chain_event_id=str(existing_event.event_id),
                        payload_hash=existing_event.payload_hash,
                        parser_outcome=EVIDENCE_OUTCOME_ALREADY_KNOWN_VERIFIED,
                        parser_version=existing_parser_version,
                        build_hash=existing_build_hash,
                        derived_swap_id=str(existing_swap_id),
                    )
                )
                continue
            # A pre-existing event with no parser-derived evidence yet
            # (e.g. observed by an earlier, unrelated ingestion path
            # that never ran it through this parser artifact) -- parse
            # it now through the normal path rather than skip it.
            event_id = existing_event.event_id
        else:
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
                    payload_hash=computed_hash,
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
        except Exception:  # noqa: BLE001 -- unparseable evidence is a named gap, not a fatal error
            acquired_evidence.append(
                AcquiredEvidenceRecord(
                    address=source_address,
                    signature=evidence.signature,
                    slot=evidence.slot,
                    chain_event_id=str(event_id),
                    payload_hash=computed_hash,
                    parser_outcome=EVIDENCE_OUTCOME_PARSE_FAILED,
                    parser_version=None,
                    build_hash=None,
                    derived_swap_id=None,
                )
            )
            continue

        await SqlSwapRecorder(session).record(
            event_id=event_id,
            wallet_address=wallet_address,
            parsed=parsed,
            build_hash=PARSER_BUILD_HASH,
            created_at=now,
        )
        swap_id = await _persisted_swap_id(
            session,
            event_id=event_id,
            parser_version=parsed.parser_version,
            build_hash=PARSER_BUILD_HASH,
        )
        persisted += 1
        acquired_evidence.append(
            AcquiredEvidenceRecord(
                address=source_address,
                signature=evidence.signature,
                slot=evidence.slot,
                chain_event_id=str(event_id),
                payload_hash=computed_hash,
                parser_outcome=EVIDENCE_OUTCOME_PARSED,
                parser_version=parsed.parser_version,
                build_hash=PARSER_BUILD_HASH,
                derived_swap_id=(str(swap_id) if swap_id is not None else None),
            )
        )

    manifest = AcquisitionManifest(
        run_id=run_id,
        wallet_id=wallet_id,
        wallet_address=wallet_address,
        observation_cutoff=now,
        algorithm_version=ALGORITHM_VERSION,
        wallet_walk_status=wallet_result.status,
        wallet_walk=_walk_stats(wallet_result),
        token_accounts_enumerated=token_accounts_enumerated,
        associated_token_accounts=tuple(account_coverage),
        acquired_evidence=tuple(acquired_evidence),
        provider_set=provider_name,
        known_gaps=(
            "; ".join(part for part in (wallet_result.known_gaps, enumeration_error) if part)
            or None
        ),
        evidence_reference=f"wallet_acquisition_run:{run_id}",
    )

    run = WalletAcquisitionRun(
        run_id=run_id,
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
    requested run does not exist, belongs to a different wallet, was
    observed after the score's own ``as_of``, fails fail-closed manifest
    decoding, or names evidence that does not actually resolve to the
    real ``chain_events``/``swaps`` rows it claims -- never silently
    ignored or downgraded to a weaker completeness instead."""


async def load_verified_acquisition_manifest(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    wallet_id: uuid.UUID,
    wallet_address: str,
    as_of: datetime,
) -> AcquisitionManifest:
    """The only path from a persisted acquisition run to a usable
    :class:`AcquisitionManifest`: loads the run, verifies it genuinely
    belongs to ``wallet_id`` and was not observed after ``as_of``,
    decodes the manifest fail-closed (see ``history_reconstruction.
    manifest_from_dict``), and then independently re-verifies every
    ``acquired_evidence`` entry claiming genuine usable evidence
    (``PARSED``/``ALREADY_KNOWN_VERIFIED``) against the real, current
    ``chain_events``/``swaps`` rows -- a manifest is never trusted as a
    summary assertion (P3-R2 remediation round 3).

    ``wallet_address`` (P3-R2 remediation round 4, required implementation
    item 1, "validate manifest/run wallet ... identity against their
    authoritative rows"): the manifest's own ``wallet_address`` must match
    the CALLER's authoritative wallet row for ``wallet_id`` -- ``wallet_id``
    alone binds the run's row, but never previously proved the manifest's
    own embedded address is genuinely this same wallet's real address."""
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

    try:
        manifest = manifest_from_dict(run.manifest)
    except ManifestDecodeError as exc:
        raise AcquisitionRunVerificationError(
            f"acquisition run {run_id} has a malformed manifest: {exc}"
        ) from exc

    if manifest.run_id != run_id or manifest.wallet_id != wallet_id:
        raise AcquisitionRunVerificationError(
            f"acquisition run {run_id}: the manifest's own run_id ({manifest.run_id}) or "
            f"wallet_id ({manifest.wallet_id}) does not match the row it was persisted under "
            f"(run_id={run_id}, wallet_id={wallet_id}) -- conflicting identity, never trusted"
        )
    if manifest.wallet_address != wallet_address:
        raise AcquisitionRunVerificationError(
            f"acquisition run {run_id}: the manifest's own wallet_address "
            f"({manifest.wallet_address!r}) does not match the authoritative wallet_address "
            f"for wallet_id={wallet_id} ({wallet_address!r}) -- conflicting identity, never "
            "trusted"
        )

    for tac in manifest.associated_token_accounts:
        if tac.status != STATUS_FAILED and tac.owner != manifest.wallet_address:
            raise AcquisitionRunVerificationError(
                f"acquisition run {run_id}: associated token account {tac.pubkey!r} claims "
                f"owner {tac.owner!r}, which does not match this run's own wallet_address "
                f"{manifest.wallet_address!r}"
            )

    for ev in manifest.acquired_evidence:
        if ev.parser_outcome not in (
            EVIDENCE_OUTCOME_PARSED,
            EVIDENCE_OUTCOME_ALREADY_KNOWN_VERIFIED,
        ):
            continue
        try:
            event_id = uuid.UUID(ev.chain_event_id)
        except ValueError as exc:
            raise AcquisitionRunVerificationError(
                f"acquisition run {run_id}: evidence for signature {ev.signature!r} names an "
                f"unresolvable chain_event_id {ev.chain_event_id!r}"
            ) from exc
        event_row = (
            await session.execute(select(ChainEvent).where(ChainEvent.event_id == event_id))
        ).scalar_one_or_none()
        if (
            event_row is None
            or event_row.transaction_signature != ev.signature
            or event_row.wallet_address != manifest.wallet_address
            or event_row.payload_hash != ev.payload_hash
        ):
            raise AcquisitionRunVerificationError(
                f"acquisition run {run_id}: evidence for signature {ev.signature!r} does not "
                "resolve to a matching real chain_events row -- never trusted from the "
                "persisted manifest summary alone"
            )
        if ev.derived_swap_id is not None:
            try:
                swap_id = uuid.UUID(ev.derived_swap_id)
            except ValueError as exc:
                raise AcquisitionRunVerificationError(
                    f"acquisition run {run_id}: evidence for signature {ev.signature!r} names "
                    f"an unresolvable derived_swap_id {ev.derived_swap_id!r}"
                ) from exc
            swap_row = (
                await session.execute(
                    select(Swap.parser_version, Swap.build_hash).where(
                        Swap.swap_id == swap_id, Swap.event_id == event_id
                    )
                )
            ).one_or_none()
            if swap_row is None:
                raise AcquisitionRunVerificationError(
                    f"acquisition run {run_id}: evidence for signature {ev.signature!r} names "
                    f"a derived_swap_id {ev.derived_swap_id!r} that does not resolve to a real "
                    "swaps row for the same chain event"
                )
            # P3-R2 remediation round 4 (required implementation item 1,
            # "validate that named swap's ... parser artifact matches the
            # evidence"): the manifest's own recorded parser_version/
            # build_hash must be the SAME artifact identity that actually
            # produced the referenced swap -- never merely "a swap for
            # this event exists," which would let a manifest name one
            # parser artifact while a different one is the row actually
            # used for reconstruction.
            actual_parser_version, actual_build_hash = swap_row
            if actual_parser_version != ev.parser_version or actual_build_hash != ev.build_hash:
                raise AcquisitionRunVerificationError(
                    f"acquisition run {run_id}: evidence for signature {ev.signature!r} claims "
                    f"parser_version={ev.parser_version!r}/build_hash={ev.build_hash!r}, but the "
                    f"referenced swap {ev.derived_swap_id!r} was actually produced by "
                    f"parser_version={actual_parser_version!r}/build_hash={actual_build_hash!r} "
                    "-- conflicting artifact identity, never trusted"
                )

    return manifest
