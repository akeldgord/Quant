"""Honest wallet history-completeness assessment (MASTER_SPEC.md section
34 HISTORICAL WALLET COMPLETENESS; Phase 3, `argus-phase-3-001`).

``getSignaturesForAddress(wallet)`` alone is never assumed to represent
complete wallet activity (section 34's own explicit warning) -- this
module derives an honest ``HIGH``/``MEDIUM``/``LOW``/``UNKNOWN``
completeness judgment from the REAL, evidence-grounded acquisition method
that actually produced the wallet's ``swaps`` rows, never from a bare
caller-supplied claim:

- ``EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK`` -- the wallet's transaction
  history was walked by
  :func:`argus.tokens.historical_acquisition.acquire_historical_transactions`
  (the same real, bounded, fault-detecting, P2-R2-remediated pagination
  service Phase 2 already built and proved for token addresses -- it is
  address-generic, so Phase 3 reuses it unmodified for wallet addresses
  too). Its own honest terminal ``status`` maps directly:
  ``STATUS_COMPLETE`` -> ``HIGH`` (the walk genuinely reached the start
  of this address's history), ``STATUS_PARTIAL`` -> ``MEDIUM`` (a real
  backward walk occurred but stopped short, with the exact reason in
  ``known_gaps``).
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

ALGORITHM_VERSION: Final[str] = "history_reconstruction_v1"

EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK: Final[str] = "LIVE_ACQUISITION_WALK"
EVIDENCE_SOURCE_STREAM_FORWARD_ONLY: Final[str] = "STREAM_FORWARD_ONLY"

EvidenceSource = Literal["LIVE_ACQUISITION_WALK", "STREAM_FORWARD_ONLY"]


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
    )

    def __init__(
        self,
        *,
        history_start: datetime | None,
        history_end: datetime | None,
        history_provider_set: str,
        history_completeness: str,
        history_completeness_reason: str,
    ) -> None:
        self.history_start = history_start
        self.history_end = history_end
        self.history_provider_set = history_provider_set
        self.history_completeness = history_completeness
        self.history_completeness_reason = history_completeness_reason


def assess_wallet_history(
    swaps: list[Swap],
    *,
    wallet_address: str,
    evidence_source: EvidenceSource,
    acquisition_status: str | None = None,
    acquisition_known_gaps: str | None = None,
) -> HistoryAssessment:
    """Derives an honest history-completeness assessment.

    ``acquisition_status``/``acquisition_known_gaps`` are required when
    ``evidence_source == EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK`` -- the
    real terminal status from
    :class:`argus.tokens.historical_acquisition.AcquisitionResult`, not a
    caller assertion. A ``STATUS_FAILED`` (or any other non-COMPLETE/
    non-PARTIAL) acquisition status is treated the same as PARTIAL here:
    real evidence may still exist even though the walk itself failed
    closed, so it is never silently promoted to "no evidence" (UNKNOWN)
    if ``swaps`` rows are actually present.
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
        if acquisition_status is None:
            raise ValueError(
                "acquisition_status is required when evidence_source is "
                "LIVE_ACQUISITION_WALK -- the real terminal AcquisitionResult.status, "
                "never omitted or assumed"
            )
        provider_set = (
            f"argus.tokens.historical_acquisition.acquire_historical_transactions "
            f"(live pagination walk of wallet {wallet_address!r})"
        )
        if acquisition_status == STATUS_COMPLETE:
            return HistoryAssessment(
                history_start=history_start,
                history_end=history_end,
                history_provider_set=provider_set,
                history_completeness=COMPLETENESS_HIGH,
                history_completeness_reason=(
                    "live acquisition walk reached the genuine start of this address's "
                    "signature history with no unresolved fault (STATUS_COMPLETE)"
                ),
            )
        reason = (
            f"live acquisition walk did not reach the genuine start of this address's "
            f"history (status={acquisition_status!r})"
        )
        if acquisition_known_gaps:
            reason += f": {acquisition_known_gaps}"
        return HistoryAssessment(
            history_start=history_start,
            history_end=history_end,
            history_provider_set=provider_set,
            history_completeness=COMPLETENESS_MEDIUM
            if acquisition_status == STATUS_PARTIAL
            else COMPLETENESS_LOW,
            history_completeness_reason=reason,
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
