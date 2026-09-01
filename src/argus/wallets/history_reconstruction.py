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
from argus.tokens.historical_acquisition import STATUS_COMPLETE, STATUS_PARTIAL

ALGORITHM_VERSION: Final[str] = "history_reconstruction_v2"

EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK: Final[str] = "LIVE_ACQUISITION_WALK"
EVIDENCE_SOURCE_STREAM_FORWARD_ONLY: Final[str] = "STREAM_FORWARD_ONLY"

EvidenceSource = Literal["LIVE_ACQUISITION_WALK", "STREAM_FORWARD_ONLY"]


@dataclasses.dataclass(frozen=True, slots=True)
class TokenAccountCoverage:
    """One associated token account's own walk status -- part of a real
    :class:`AcquisitionManifest`, never hand-typed by a caller.

    ``pubkey``/``owner`` (P3-R2 remediation round 2,
    `argus-phase-3-remediation-002`): the mint alone is not an account
    identity -- a wallet can hold multiple distinct token accounts for
    the same mint, and ``owner`` is the on-chain proof this account
    genuinely belongs to the wallet being assessed, not merely
    coincidentally sharing a mint."""

    pubkey: str
    mint: str
    owner: str
    status: str  # STATUS_COMPLETE / STATUS_PARTIAL / STATUS_FAILED


@dataclasses.dataclass(frozen=True, slots=True)
class AcquisitionManifest:
    """The real, structured, immutable result of actually executing a
    typed acquisition walk -- never a bare caller-supplied status
    string. ``token_accounts_enumerated`` distinguishes "a real
    enumeration call was made and found this exact set of accounts"
    (even if that set is empty) from "no enumeration was ever
    attempted" -- the latter can never support ``HIGH``, no matter how
    complete the wallet-address walk itself was."""

    wallet_walk_status: str  # STATUS_COMPLETE / STATUS_PARTIAL / STATUS_FAILED
    token_accounts_enumerated: bool
    associated_token_accounts: tuple[TokenAccountCoverage, ...]
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


def manifest_as_dict(manifest: AcquisitionManifest) -> dict:
    return {
        "wallet_walk_status": manifest.wallet_walk_status,
        "token_accounts_enumerated": manifest.token_accounts_enumerated,
        "associated_token_accounts": [
            {"pubkey": tac.pubkey, "mint": tac.mint, "owner": tac.owner, "status": tac.status}
            for tac in manifest.associated_token_accounts
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
    ``argus.wallets.acquisition.load_verified_acquisition_manifest``)."""
    return AcquisitionManifest(
        wallet_walk_status=data["wallet_walk_status"],
        token_accounts_enumerated=bool(data["token_accounts_enumerated"]),
        associated_token_accounts=tuple(
            TokenAccountCoverage(
                pubkey=tac["pubkey"], mint=tac["mint"], owner=tac["owner"], status=tac["status"]
            )
            for tac in data.get("associated_token_accounts", [])
        ),
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
                completeness = COMPLETENESS_HIGH
                reason = (
                    "wallet-address walk complete and every known associated "
                    "token-account history is complete through the stated boundary"
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
