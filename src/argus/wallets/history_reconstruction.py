"""Honest wallet history-completeness assessment (MASTER_SPEC.md section
34 HISTORICAL WALLET COMPLETENESS; Phase 3, `argus-phase-3-001`,
remediated by `argus-phase-3-remediation-001` finding P3-R2).

``getSignaturesForAddress(wallet)`` alone is never assumed to represent
complete wallet activity (section 34's own explicit warning) -- this
module derives an honest ``HIGH``/``MEDIUM``/``LOW``/``UNKNOWN``
completeness judgment from a REAL, structured, evidence-grounded
:class:`AcquisitionManifest`, never from a bare caller-typed status
string. The P3-R2 defect this replaces: a caller could previously pass
``--acquisition-status COMPLETE`` as free text with no manifest at all
and manufacture ``HIGH`` completeness for any wallet with even one
``swaps`` row -- that path no longer exists.

- ``EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK`` -- requires a real
  :class:`AcquisitionManifest`, produced by actually executing the typed
  acquisition path (:func:`argus.tokens.historical_acquisition.
  acquire_historical_transactions`, the same real, bounded,
  fault-detecting, P2-R2-remediated pagination service Phase 2 already
  built and proved -- it is address-generic, so Phase 3 reuses it
  unmodified for wallet addresses too) and, where available, an
  associated token-account enumeration/coverage walk. ``HIGH`` requires
  BOTH the wallet-address walk to have genuinely completed AND every
  known associated token account to have been enumerated and completed
  -- a wallet-address-only ``COMPLETE`` is capped at ``MEDIUM``, never
  ``HIGH``, since section 34 explicitly warns that address-only history
  is not necessarily complete wallet activity.
- ``EVIDENCE_SOURCE_STREAM_FORWARD_ONLY`` -- the wallet's ``swaps`` rows
  came only from Phase 1's live-streaming ingestion
  (``argus ingest run``), which is forward-only from whenever tracking
  began -- no attempt was made to acquire history from before that point.
  Always ``LOW``: genuine data exists, but it provably cannot represent
  the wallet's full lifetime activity.
- No ``swaps`` evidence at all for the wallet -- ``UNKNOWN``, never
  fabricated as "the wallet has no activity."

Low/unknown completeness must reduce score confidence and may prevent
live eligibility (section 34) -- enforced downstream by
``argus.wallets.scoring``, not by this module (which only records the
honest completeness judgment itself).
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from argus.domain.swaps import Swap

from argus.domain.wallet_history_quality import (
    COMPLETENESS_HIGH,
    COMPLETENESS_LOW,
    COMPLETENESS_MEDIUM,
    COMPLETENESS_UNKNOWN,
)
from argus.tokens.historical_acquisition import STATUS_COMPLETE, STATUS_FAILED, STATUS_PARTIAL

ALGORITHM_VERSION: Final[str] = "history_reconstruction_v2"

EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK: Final[str] = "LIVE_ACQUISITION_WALK"
EVIDENCE_SOURCE_STREAM_FORWARD_ONLY: Final[str] = "STREAM_FORWARD_ONLY"

EvidenceSource = Literal["LIVE_ACQUISITION_WALK", "STREAM_FORWARD_ONLY"]

_VALID_WALK_STATUSES: Final[frozenset[str]] = frozenset(
    {STATUS_COMPLETE, STATUS_PARTIAL, STATUS_FAILED}
)

# P3-R2 remediation round 3 (`argus-phase-3-remediation-003`): the exact
# fate of one acquired-or-already-known transaction, per signature --
# never inferred from "a chain_events row with this signature exists,"
# which the round-2 audit proved lets a successful address walk bless an
# unrelated/incomplete swaps fragment. Only PARSED/ALREADY_KNOWN_VERIFIED
# entries count as genuine usable evidence; any other outcome is an
# explicit, honestly-named gap that caps completeness below HIGH.
EVIDENCE_OUTCOME_PARSED: Final[str] = "PARSED"
EVIDENCE_OUTCOME_PARSE_FAILED: Final[str] = "PARSE_FAILED"
EVIDENCE_OUTCOME_ALREADY_KNOWN_VERIFIED: Final[str] = "ALREADY_KNOWN_VERIFIED"
EVIDENCE_OUTCOME_PAYLOAD_HASH_MISMATCH: Final[str] = "PAYLOAD_HASH_MISMATCH"

_VALID_EVIDENCE_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        EVIDENCE_OUTCOME_PARSED,
        EVIDENCE_OUTCOME_PARSE_FAILED,
        EVIDENCE_OUTCOME_ALREADY_KNOWN_VERIFIED,
        EVIDENCE_OUTCOME_PAYLOAD_HASH_MISMATCH,
    }
)

_GENUINE_EVIDENCE_OUTCOMES: Final[frozenset[str]] = frozenset(
    {EVIDENCE_OUTCOME_PARSED, EVIDENCE_OUTCOME_ALREADY_KNOWN_VERIFIED}
)


class ManifestDecodeError(ValueError):
    """A persisted acquisition-run manifest failed strict, fail-closed
    decoding (P3-R2 remediation round 3) -- a non-boolean
    ``token_accounts_enumerated`` (the round-2-audit-reproduced
    ``bool("false") is True`` defect), an unrecognized status/outcome
    literal, or a duplicate account/evidence identity within one
    manifest. Never silently coerced or dropped -- a malformed manifest
    can never be used as scoring evidence at all."""


@dataclasses.dataclass(frozen=True, slots=True)
class WalkStats:
    """The real, machine-checkable outcome of one paginated address walk
    (the wallet address itself, or one associated token account) --
    P3-R2 remediation round 3's own explicit requirement: "pages fetched,
    signatures seen and transaction-fetch failures," plus the optional
    caller-supplied boundary and whether it was actually satisfied,
    exactly as :func:`argus.tokens.historical_acquisition.
    acquire_historical_transactions` itself observed -- never re-derived
    from prose in ``known_gaps``."""

    status: str  # STATUS_COMPLETE / STATUS_PARTIAL / STATUS_FAILED
    known_gaps: str | None
    pages_fetched: int
    signatures_seen: int
    transaction_fetch_failures: int
    expected_oldest_slot: int | None
    boundary_satisfied: bool | None  # None only when no boundary was supplied


@dataclasses.dataclass(frozen=True, slots=True)
class TokenAccountCoverage:
    """One associated token account's own walk status -- part of a real
    :class:`AcquisitionManifest`, never hand-typed by a caller.

    ``pubkey``/``owner`` (P3-R2 remediation round 2,
    `argus-phase-3-remediation-002`): the mint alone is not an account
    identity -- a wallet can hold multiple distinct token accounts for
    the same mint, and ``owner`` is the on-chain proof this account
    genuinely belongs to the wallet being assessed, not merely
    coincidentally sharing a mint. ``walk`` (round 3) carries this
    account's own page/signature/failure counts, never merely a terminal
    status string."""

    pubkey: str
    mint: str
    owner: str
    status: str  # STATUS_COMPLETE / STATUS_PARTIAL / STATUS_FAILED -- mirrors walk.status
    walk: WalkStats


@dataclasses.dataclass(frozen=True, slots=True)
class AcquiredEvidenceRecord:
    """One signature's exact, machine-resolvable fate within an
    acquisition run (P3-R2 remediation round 3) -- the precise "raw/
    parser input set used for reconstruction" the round-2 audit found
    entirely unrepresented. ``chain_event_id``/``payload_hash`` are
    verified against the real ``chain_events`` row on load (see
    ``argus.wallets.acquisition.load_verified_acquisition_manifest``),
    never trusted from the JSONB alone; ``derived_swap_id`` is likewise
    verified to be a real ``swaps`` row for that exact event when
    ``parser_outcome`` claims genuine evidence
    (``PARSED``/``ALREADY_KNOWN_VERIFIED``)."""

    address: str  # which walk this signature was observed under
    signature: str
    slot: int
    chain_event_id: str
    payload_hash: str
    parser_outcome: str  # one of the EVIDENCE_OUTCOME_* constants
    parser_version: str | None
    build_hash: str | None
    derived_swap_id: str | None


@dataclasses.dataclass(frozen=True, slots=True)
class AcquisitionManifest:
    """The real, structured, immutable result of actually executing a
    typed acquisition walk -- never a bare caller-supplied status
    string. ``token_accounts_enumerated`` distinguishes "a real
    enumeration call was made and found this exact set of accounts"
    (even if that set is empty) from "no enumeration was ever
    attempted" -- the latter can never support ``HIGH``, no matter how
    complete the wallet-address walk itself was.

    P3-R2 remediation round 3 (`argus-phase-3-remediation-002`'s own
    round-2 audit): a manifest is no longer a trusted summary assertion.
    ``run_id``/``wallet_id``/``wallet_address``/``observation_cutoff``
    bind this manifest's own identity (never merely the row it happens
    to be stored in); ``wallet_walk`` carries the wallet-address walk's
    real page/signature/failure/boundary evidence; and
    ``acquired_evidence`` names the EXACT raw/parser input set this run
    is built from, each entry independently verified against real
    ``chain_events``/``swaps`` rows on load."""

    run_id: uuid.UUID
    wallet_id: uuid.UUID
    wallet_address: str
    observation_cutoff: datetime
    algorithm_version: str
    wallet_walk_status: str  # STATUS_COMPLETE / STATUS_PARTIAL / STATUS_FAILED
    wallet_walk: WalkStats
    token_accounts_enumerated: bool
    associated_token_accounts: tuple[TokenAccountCoverage, ...]
    acquired_evidence: tuple[AcquiredEvidenceRecord, ...]
    provider_set: str
    known_gaps: str | None
    evidence_reference: str


class HistoryAssessment:
    """The fields this module computes, ready to persist as a
    ``WalletHistoryQuality`` row -- kept as a plain typed container
    rather than importing the ORM model here (this module is pure/
    session-free, matching ``position_reconstruction``'s own shape)."""

    __slots__ = (
        "history_start",
        "history_end",
        "history_provider_set",
        "history_completeness",
        "history_completeness_reason",
        "acquisition_manifest",
    )

    def __init__(
        self,
        *,
        history_start: datetime | None,
        history_end: datetime | None,
        history_provider_set: str,
        history_completeness: str,
        history_completeness_reason: str,
        acquisition_manifest: AcquisitionManifest | None = None,
    ) -> None:
        self.history_start = history_start
        self.history_end = history_end
        self.history_provider_set = history_provider_set
        self.history_completeness = history_completeness
        self.history_completeness_reason = history_completeness_reason
        self.acquisition_manifest = acquisition_manifest


def _walk_stats_as_dict(walk: WalkStats) -> dict:
    return {
        "status": walk.status,
        "known_gaps": walk.known_gaps,
        "pages_fetched": walk.pages_fetched,
        "signatures_seen": walk.signatures_seen,
        "transaction_fetch_failures": walk.transaction_fetch_failures,
        "expected_oldest_slot": walk.expected_oldest_slot,
        "boundary_satisfied": walk.boundary_satisfied,
    }


def _walk_stats_from_dict(data: dict, *, context: str) -> WalkStats:
    status = data.get("status")
    if status not in _VALID_WALK_STATUSES:
        raise ManifestDecodeError(f"{context}: status {status!r} is not a recognized walk status")
    boundary_satisfied = data.get("boundary_satisfied")
    if boundary_satisfied is not None and not isinstance(boundary_satisfied, bool):
        raise ManifestDecodeError(
            f"{context}: boundary_satisfied must be a real JSON boolean or null, got "
            f"{boundary_satisfied!r}"
        )
    for int_field in ("pages_fetched", "signatures_seen", "transaction_fetch_failures"):
        value = data.get(int_field)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ManifestDecodeError(f"{context}: {int_field} must be an integer, got {value!r}")
    expected_oldest_slot = data.get("expected_oldest_slot")
    if expected_oldest_slot is not None and (
        not isinstance(expected_oldest_slot, int) or isinstance(expected_oldest_slot, bool)
    ):
        raise ManifestDecodeError(
            f"{context}: expected_oldest_slot must be an integer or null, got "
            f"{expected_oldest_slot!r}"
        )
    return WalkStats(
        status=status,
        known_gaps=data.get("known_gaps"),
        pages_fetched=data["pages_fetched"],
        signatures_seen=data["signatures_seen"],
        transaction_fetch_failures=data["transaction_fetch_failures"],
        expected_oldest_slot=expected_oldest_slot,
        boundary_satisfied=boundary_satisfied,
    )


def _check_walk_internal_consistency(walk: WalkStats, *, context: str) -> None:
    """P3-R2 remediation round 4 (`argus-phase-3-remediation-004`,
    adversarial probe 3): the real producer
    (``argus.tokens.historical_acquisition.acquire_historical_transactions``)
    can never itself report ``STATUS_COMPLETE`` while also recording a
    per-transaction fetch failure or an unsatisfied caller-supplied
    boundary -- either one downgrades its own ``status`` to
    ``STATUS_PARTIAL`` before returning. A persisted walk claiming
    ``COMPLETE`` alongside either of those is therefore never genuine
    producer output; it is conflicting/tampered data and must fail
    closed rather than silently justify trust in a COMPLETE walk."""
    if walk.status != STATUS_COMPLETE:
        return
    if walk.transaction_fetch_failures != 0:
        raise ManifestDecodeError(
            f"{context}: status is {STATUS_COMPLETE!r} but transaction_fetch_failures="
            f"{walk.transaction_fetch_failures} -- a genuinely complete walk can never record "
            "a per-transaction fetch failure"
        )
    if walk.boundary_satisfied is False:
        raise ManifestDecodeError(
            f"{context}: status is {STATUS_COMPLETE!r} but boundary_satisfied is False -- a "
            "genuinely complete walk can never leave a supplied boundary unsatisfied"
        )


def manifest_as_dict(manifest: AcquisitionManifest) -> dict:
    return {
        "run_id": str(manifest.run_id),
        "wallet_id": str(manifest.wallet_id),
        "wallet_address": manifest.wallet_address,
        "observation_cutoff": manifest.observation_cutoff.isoformat(),
        "algorithm_version": manifest.algorithm_version,
        "wallet_walk_status": manifest.wallet_walk_status,
        "wallet_walk": _walk_stats_as_dict(manifest.wallet_walk),
        "token_accounts_enumerated": manifest.token_accounts_enumerated,
        "associated_token_accounts": [
            {
                "pubkey": tac.pubkey,
                "mint": tac.mint,
                "owner": tac.owner,
                "status": tac.status,
                "walk": _walk_stats_as_dict(tac.walk),
            }
            for tac in manifest.associated_token_accounts
        ],
        "acquired_evidence": [
            {
                "address": ev.address,
                "signature": ev.signature,
                "slot": ev.slot,
                "chain_event_id": ev.chain_event_id,
                "payload_hash": ev.payload_hash,
                "parser_outcome": ev.parser_outcome,
                "parser_version": ev.parser_version,
                "build_hash": ev.build_hash,
                "derived_swap_id": ev.derived_swap_id,
            }
            for ev in manifest.acquired_evidence
        ],
        "provider_set": manifest.provider_set,
        "known_gaps": manifest.known_gaps,
        "evidence_reference": manifest.evidence_reference,
    }


def manifest_from_dict(data: dict) -> AcquisitionManifest:
    """Reconstructs an :class:`AcquisitionManifest` from its persisted
    JSONB form (the exact inverse of :func:`manifest_as_dict`) -- used to
    load a verified, immutable acquisition-run record back into the same
    typed shape :func:`assess_wallet_history` requires, never to accept
    an arbitrary caller-supplied shape (see
    ``argus.wallets.acquisition.load_verified_acquisition_manifest``).

    P3-R2 remediation round 3: fails closed (raises
    :class:`ManifestDecodeError`) on anything malformed rather than
    coercing it -- ``token_accounts_enumerated`` must be a genuine JSON
    boolean (``bool("false")`` evaluating to ``True`` in Python is the
    exact reproduced round-2-audit defect this replaces), every status/
    outcome literal must be one of the recognized constants, and no
    account pubkey or evidence signature may repeat within one manifest
    (a duplicate is itself malformed/conflicting data, never silently
    deduplicated here).

    P3-R2 remediation round 4 (`argus-phase-3-remediation-004`, closing
    audit `argus-phase-3-remediation-audit-003`'s P3-R2b): ``acquired_
    evidence`` and ``associated_token_accounts`` must be explicitly
    present arrays -- a genuinely empty array (a real enumeration/walk
    that found nothing) remains legitimate, but a MISSING key (adversarial
    probe 2: deleting the key entirely) is fatal, never silently defaulted
    to ``[]``. ``PARSED``/``ALREADY_KNOWN_VERIFIED`` evidence must name a
    non-null, resolving ``derived_swap_id`` plus its real ``parser_version``/
    ``build_hash`` (adversarial probe 4: a null derived reference can no
    longer decode successfully at all). ``wallet_walk_status`` must agree
    with ``wallet_walk.status`` (and each account's own top-level
    ``status`` with its own ``walk.status``) -- the real producer never
    disagrees with itself, so any manifest that does is conflicting data
    (adversarial probe 3). A walk cannot claim ``COMPLETE`` while also
    recording a transaction-fetch failure or an unsatisfied supplied
    boundary -- see :func:`_check_walk_internal_consistency`."""
    if "associated_token_accounts" not in data:
        raise ManifestDecodeError(
            "associated_token_accounts is a required array (an explicit empty list is "
            "legitimate; the key itself must always be present)"
        )
    if "acquired_evidence" not in data:
        raise ManifestDecodeError(
            "acquired_evidence is a required array (an explicit empty list is legitimate; "
            "the key itself must always be present)"
        )

    enumerated = data.get("token_accounts_enumerated")
    if not isinstance(enumerated, bool):
        raise ManifestDecodeError(
            f"token_accounts_enumerated must be a real JSON boolean, got {enumerated!r} "
            f"(type {type(enumerated).__name__}) -- never coerced via bool(...)"
        )
    wallet_walk_status = data.get("wallet_walk_status")
    if wallet_walk_status not in _VALID_WALK_STATUSES:
        raise ManifestDecodeError(
            f"wallet_walk_status {wallet_walk_status!r} is not a recognized walk status"
        )
    wallet_walk = _walk_stats_from_dict(data["wallet_walk"], context="wallet walk")
    if wallet_walk_status != wallet_walk.status:
        raise ManifestDecodeError(
            f"wallet_walk_status {wallet_walk_status!r} disagrees with wallet_walk.status "
            f"{wallet_walk.status!r} -- the real producer never reports these two fields "
            "differently; this is conflicting data"
        )
    _check_walk_internal_consistency(wallet_walk, context="wallet walk")

    seen_pubkeys: set[str] = set()
    accounts: list[TokenAccountCoverage] = []
    for tac in data["associated_token_accounts"]:
        pubkey = tac.get("pubkey")
        if not pubkey or not isinstance(pubkey, str):
            raise ManifestDecodeError(f"associated token account missing a valid pubkey: {tac!r}")
        if pubkey in seen_pubkeys:
            raise ManifestDecodeError(
                f"duplicate associated_token_accounts pubkey {pubkey!r} within one manifest -- "
                "conflicting evidence, never silently deduplicated"
            )
        seen_pubkeys.add(pubkey)
        status = tac.get("status")
        if status not in _VALID_WALK_STATUSES:
            raise ManifestDecodeError(
                f"associated token account {pubkey!r}: status {status!r} is not recognized"
            )
        account_walk = _walk_stats_from_dict(tac["walk"], context=f"account {pubkey!r}")
        if status != account_walk.status:
            raise ManifestDecodeError(
                f"associated token account {pubkey!r}: status {status!r} disagrees with its "
                f"own walk.status {account_walk.status!r} -- conflicting data"
            )
        _check_walk_internal_consistency(account_walk, context=f"account {pubkey!r}")
        accounts.append(
            TokenAccountCoverage(
                pubkey=pubkey,
                mint=tac["mint"],
                owner=tac["owner"],
                status=status,
                walk=account_walk,
            )
        )

    seen_signatures: set[str] = set()
    evidence: list[AcquiredEvidenceRecord] = []
    for ev in data["acquired_evidence"]:
        signature = ev.get("signature")
        if not signature or not isinstance(signature, str):
            raise ManifestDecodeError(f"acquired evidence entry missing a valid signature: {ev!r}")
        if signature in seen_signatures:
            raise ManifestDecodeError(
                f"duplicate acquired_evidence signature {signature!r} within one manifest -- "
                "conflicting evidence, never silently deduplicated"
            )
        seen_signatures.add(signature)
        outcome = ev.get("parser_outcome")
        if outcome not in _VALID_EVIDENCE_OUTCOMES:
            raise ManifestDecodeError(
                f"acquired evidence {signature!r}: parser_outcome {outcome!r} is not recognized"
            )
        chain_event_id = ev.get("chain_event_id")
        if not chain_event_id or not isinstance(chain_event_id, str):
            raise ManifestDecodeError(
                f"acquired evidence {signature!r}: missing a resolvable chain_event_id"
            )
        payload_hash_value = ev.get("payload_hash")
        if not payload_hash_value or not isinstance(payload_hash_value, str):
            raise ManifestDecodeError(f"acquired evidence {signature!r}: missing a payload_hash")
        parser_version = ev.get("parser_version")
        build_hash_value = ev.get("build_hash")
        derived_swap_id = ev.get("derived_swap_id")
        if outcome in _GENUINE_EVIDENCE_OUTCOMES:
            if not derived_swap_id or not isinstance(derived_swap_id, str):
                raise ManifestDecodeError(
                    f"acquired evidence {signature!r}: parser_outcome {outcome!r} claims "
                    "genuine usable evidence but names no non-null, resolving derived_swap_id"
                )
            if not parser_version or not isinstance(parser_version, str):
                raise ManifestDecodeError(
                    f"acquired evidence {signature!r}: parser_outcome {outcome!r} requires a "
                    "real, non-null parser_version"
                )
            if not build_hash_value or not isinstance(build_hash_value, str):
                raise ManifestDecodeError(
                    f"acquired evidence {signature!r}: parser_outcome {outcome!r} requires a "
                    "real, non-null build_hash"
                )
        evidence.append(
            AcquiredEvidenceRecord(
                address=ev["address"],
                signature=signature,
                slot=ev["slot"],
                chain_event_id=chain_event_id,
                payload_hash=payload_hash_value,
                parser_outcome=outcome,
                parser_version=parser_version,
                build_hash=build_hash_value,
                derived_swap_id=derived_swap_id,
            )
        )

    return AcquisitionManifest(
        run_id=uuid.UUID(data["run_id"]),
        wallet_id=uuid.UUID(data["wallet_id"]),
        wallet_address=data["wallet_address"],
        observation_cutoff=datetime.fromisoformat(data["observation_cutoff"]),
        algorithm_version=data["algorithm_version"],
        wallet_walk_status=wallet_walk_status,
        wallet_walk=wallet_walk,
        token_accounts_enumerated=enumerated,
        associated_token_accounts=tuple(accounts),
        acquired_evidence=tuple(evidence),
        provider_set=data["provider_set"],
        known_gaps=data.get("known_gaps"),
        evidence_reference=data["evidence_reference"],
    )


def assess_wallet_history(
    swaps: list[Swap],
    *,
    wallet_address: str,
    evidence_source: EvidenceSource,
    acquisition_manifest: AcquisitionManifest | None = None,
) -> HistoryAssessment:
    """Derives an honest history-completeness assessment.

    ``acquisition_manifest`` is required when ``evidence_source ==
    EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK`` -- a real, structured
    :class:`AcquisitionManifest`, never a bare caller-supplied status
    string (this is the P3-R2 fix: the exact caller-forged-completeness
    path is no longer expressible in this function's own signature).
    """
    if not swaps:
        return HistoryAssessment(
            history_start=None,
            history_end=None,
            history_provider_set=f"no evidence found for wallet {wallet_address!r}",
            history_completeness=COMPLETENESS_UNKNOWN,
            history_completeness_reason=(
                "zero swaps rows found for this wallet -- genuinely missing evidence, "
                "never assumed to mean zero on-chain activity"
            ),
        )

    times = [s.block_time for s in swaps if s.block_time is not None]
    history_start = min(times) if times else None
    history_end = max(times) if times else None

    if evidence_source == EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK:
        if acquisition_manifest is None:
            raise ValueError(
                "acquisition_manifest is required when evidence_source is "
                "LIVE_ACQUISITION_WALK -- a real, structured AcquisitionManifest "
                "produced by actually executing the typed acquisition path, never a "
                "bare caller-supplied status string"
            )
        provider_set = (
            f"argus.tokens.historical_acquisition.acquire_historical_transactions "
            f"(live pagination walk of wallet {wallet_address!r}); "
            f"{acquisition_manifest.provider_set}"
        )
        wallet_walk_complete = acquisition_manifest.wallet_walk_status == STATUS_COMPLETE

        if not wallet_walk_complete:
            reason = (
                f"wallet-address walk did not complete "
                f"(status={acquisition_manifest.wallet_walk_status!r})"
            )
            if acquisition_manifest.known_gaps:
                reason += f": {acquisition_manifest.known_gaps}"
            completeness = (
                COMPLETENESS_MEDIUM
                if acquisition_manifest.wallet_walk_status == STATUS_PARTIAL
                else COMPLETENESS_LOW
            )
        elif not acquisition_manifest.token_accounts_enumerated:
            completeness = COMPLETENESS_MEDIUM
            reason = (
                "wallet-address walk complete, but associated token-account "
                "enumeration was never performed -- section 34 explicitly warns "
                "wallet-address history alone is not necessarily complete wallet "
                "activity, so this cannot exceed MEDIUM"
            )
        else:
            incomplete = [
                tac.mint
                for tac in acquisition_manifest.associated_token_accounts
                if tac.status != STATUS_COMPLETE
            ]
            if incomplete:
                completeness = COMPLETENESS_MEDIUM
                reason = (
                    f"wallet-address walk complete and token accounts enumerated, but "
                    f"{len(incomplete)} associated account(s) have incomplete history: "
                    f"{incomplete}"
                )
            else:
                # P3-R2 remediation round 3: a COMPLETE walk status alone
                # never proves every acquired signature actually supplied
                # usable, verified parser evidence -- a parse exception,
                # a payload-hash mismatch against a pre-existing event, or
                # any other non-genuine acquired_evidence outcome is an
                # explicit gap that caps this below HIGH, exactly the
                # "successful walk blessing an unrelated/incomplete swaps
                # fragment" scenario the round-2 audit named.
                gap_evidence = [
                    ev
                    for ev in acquisition_manifest.acquired_evidence
                    if ev.parser_outcome not in _GENUINE_EVIDENCE_OUTCOMES
                ]
                if gap_evidence:
                    completeness = COMPLETENESS_MEDIUM
                    outcomes = sorted({ev.parser_outcome for ev in gap_evidence})
                    reason = (
                        f"wallet-address walk complete and token accounts enumerated, but "
                        f"{len(gap_evidence)} acquired signature(s) never became verified "
                        f"usable evidence ({', '.join(outcomes)}) -- a successful address "
                        "walk alone never blesses an unparsed/mismatched fragment"
                    )
                else:
                    completeness = COMPLETENESS_HIGH
                    reason = (
                        "wallet-address walk complete, every known associated "
                        "token-account history is complete through the stated boundary, "
                        "and every acquired signature resolved to verified parser evidence"
                    )

        return HistoryAssessment(
            history_start=history_start,
            history_end=history_end,
            history_provider_set=provider_set,
            history_completeness=completeness,
            history_completeness_reason=reason,
            acquisition_manifest=acquisition_manifest,
        )

    # EVIDENCE_SOURCE_STREAM_FORWARD_ONLY
    return HistoryAssessment(
        history_start=history_start,
        history_end=history_end,
        history_provider_set=(
            f"Phase 1 live-streaming ingestion (argus ingest run), forward-only from "
            f"whenever tracking of {wallet_address!r} began -- no backward historical "
            f"walk attempted"
        ),
        history_completeness=COMPLETENESS_LOW,
        history_completeness_reason=(
            "evidence exists only from whenever live tracking began; no attempt was "
            "made to acquire this wallet's pre-tracking history, so completeness "
            "cannot honestly be assessed higher than LOW regardless of how much "
            "post-tracking evidence exists"
        ),
    )
