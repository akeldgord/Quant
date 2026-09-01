"""``wallet_history_quality`` — MASTER_SPEC.md section 34 (HISTORICAL
WALLET COMPLETENESS), Phase 3 (`argus-phase-3-001`).

``getSignaturesForAddress(wallet)`` alone is never assumed to represent
complete wallet activity (section 34's own explicit warning). Every
reconstruction attempt records what evidence it actually had --
``history_start``/``history_end``/``history_provider_set`` -- and an
honest qualitative ``history_completeness`` judgment
(``HIGH``/``MEDIUM``/``LOW``/``UNKNOWN``) with its reason, never silently
assumed complete. Missing/unrecoverable history is explicit missing
evidence, never zero activity -- a wallet with no evidence at all still
gets a row here, with ``history_completeness = 'UNKNOWN'`` and an honest
reason, not a fabricated "no activity" claim.

Append-only and versioned like every other Phase 1/2 decision ledger: a
later reconstruction attempt (more evidence, a new provider, a bug fix)
adds a new row rather than overwriting a prior point-in-time judgment.
Downstream code always reads the latest row per wallet.

``acquisition_manifest`` (Phase 3 remediation, `argus-phase-3-remediation-001`,
finding P3-R2): when ``history_completeness`` was derived from a real
``LIVE_ACQUISITION_WALK``, this stores the verified, immutable
``argus.wallets.history_reconstruction.AcquisitionManifest`` that
justified it -- the wallet-address walk's own real terminal status plus
associated token-account enumeration/coverage -- so a HIGH/MEDIUM
completeness judgment is always traceable to real, structured acquisition
evidence, never a bare caller-typed status string. NULL for
``STREAM_FORWARD_ONLY``/no-evidence assessments, which never claim a
verified acquisition walk occurred.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

COMPLETENESS_HIGH = "HIGH"
COMPLETENESS_MEDIUM = "MEDIUM"
COMPLETENESS_LOW = "LOW"
COMPLETENESS_UNKNOWN = "UNKNOWN"

HISTORY_COMPLETENESS_LEVELS: tuple[str, ...] = (
    COMPLETENESS_HIGH,
    COMPLETENESS_MEDIUM,
    COMPLETENESS_LOW,
    COMPLETENESS_UNKNOWN,
)

_COMPLETENESS_LIST_SQL = ", ".join(f"'{c}'" for c in HISTORY_COMPLETENESS_LEVELS)


class WalletHistoryQuality(Base):
    """One point-in-time honest assessment of how complete ARGUS's
    evidence for one wallet's trading history actually is."""

    __tablename__ = "wallet_history_quality"
    __table_args__ = (
        CheckConstraint(
            f"history_completeness IN ({_COMPLETENESS_LIST_SQL})",
            name="ck_wallet_history_quality_completeness",
        ),
        CheckConstraint(
            "length(history_completeness_reason) > 0",
            name="ck_wallet_history_quality_reason_nonempty",
        ),
        CheckConstraint(
            "length(history_provider_set) > 0",
            name="ck_wallet_history_quality_provider_set_nonempty",
        ),
        CheckConstraint(
            "history_start IS NULL OR history_end IS NULL OR history_start <= history_end",
            name="ck_wallet_history_quality_start_before_end",
        ),
    )

    history_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=False, index=True
    )

    # NULL/NULL is a genuine, honest state: no usable evidence was found at
    # all (never fabricated as "the wallet has no history").
    history_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    history_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    history_provider_set: Mapped[str] = mapped_column(String(256), nullable=False)
    history_completeness: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    history_completeness_reason: Mapped[str] = mapped_column(Text, nullable=False)

    # See module docstring. NULL unless evidence_source was
    # LIVE_ACQUISITION_WALK with a real, structured AcquisitionManifest.
    acquisition_manifest: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # P3-R1 remediation round 2 (`argus-phase-3-remediation-002`): every
    # swap excluded from this assessment's own usable-evidence set because
    # its economic timestamp (block_time) is later than the score's as_of
    # -- a list of {"swap_id": ..., "reason": "FUTURE_ECONOMIC_TIMESTAMP"}
    # entries. Never empty-vs-populated by omission: always `[]` when
    # nothing was excluded, never NULL. The raw swap row itself is never
    # deleted or mutated -- this is a record of what was excluded and why,
    # not a deletion log.
    excluded_evidence: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
