"""``wallet_specialist_scores`` — MASTER_SPEC.md Phase 9 (COUNTERFACTUAL
ALPHA + SPECIALISTS), section 62 (ENTRY AND EXIT SPECIALISTS).

Entry/discovery/validation/exit ability scored independently per wallet
(never reduced to one score, section 62's own explicit instruction), plus
a percentile-rank-based ``dominant_specialty`` classification -- a wallet
can have ``entry_specialist_score`` low and ``exit_specialist_score`` high
and remain strategically useful (section 62's own worked example).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

DOMINANT_SPECIALTY_ENTRY = "ENTRY"
DOMINANT_SPECIALTY_DISCOVERY = "DISCOVERY"
DOMINANT_SPECIALTY_VALIDATION = "VALIDATION"
DOMINANT_SPECIALTY_EXIT = "EXIT"

DOMINANT_SPECIALTIES: tuple[str, ...] = (
    DOMINANT_SPECIALTY_ENTRY,
    DOMINANT_SPECIALTY_DISCOVERY,
    DOMINANT_SPECIALTY_VALIDATION,
    DOMINANT_SPECIALTY_EXIT,
)


class WalletSpecialistScore(Base):
    __tablename__ = "wallet_specialist_scores"
    __table_args__ = (
        UniqueConstraint(
            "wallet_id",
            "as_of",
            "algorithm_version",
            "config_hash",
            name="uq_wallet_specialist_scores_identity",
        ),
        CheckConstraint(
            "dominant_specialty IS NULL OR "
            "dominant_specialty IN ('ENTRY', 'DISCOVERY', 'VALIDATION', 'EXIT')",
            name="ck_wallet_specialist_scores_dominant_specialty",
        ),
        CheckConstraint(
            "entry_percentile IS NULL OR (entry_percentile >= 0 AND entry_percentile <= 1)",
            name="ck_wallet_specialist_scores_entry_percentile_range",
        ),
        CheckConstraint(
            "discovery_percentile IS NULL OR (discovery_percentile >= 0 AND discovery_percentile <= 1)",
            name="ck_wallet_specialist_scores_discovery_percentile_range",
        ),
        CheckConstraint(
            "validation_percentile IS NULL OR (validation_percentile >= 0 AND validation_percentile <= 1)",
            name="ck_wallet_specialist_scores_validation_percentile_range",
        ),
        CheckConstraint(
            "exit_percentile IS NULL OR (exit_percentile >= 0 AND exit_percentile <= 1)",
            name="ck_wallet_specialist_scores_exit_percentile_range",
        ),
        CheckConstraint(
            "length(algorithm_version) > 0",
            name="ck_wallet_specialist_scores_algo_version_nonempty",
        ),
        CheckConstraint(
            "length(config_hash) > 0", name="ck_wallet_specialist_scores_config_hash_nonempty"
        ),
        CheckConstraint(
            "source_knowledge_max_at <= as_of",
            name="ck_wallet_specialist_scores_source_knowledge_not_after_as_of",
        ),
    )

    score_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=False, index=True
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    # entry: this wallet's own mean residual_selection_alpha (section 55)
    # at the configured entry horizon.
    entry_specialist_score: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    entry_specialist_sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    # discovery: mean effect_size of this wallet's own significant
    # OUTGOING Phase 7 directional edges (as leader).
    discovery_specialist_score: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 15), nullable=True
    )
    discovery_specialist_sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    # validation: fraction of this wallet's own Phase 8 confirmation
    # events (as follower) that were NOT ABSENT.
    validation_specialist_score: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 15), nullable=True
    )
    validation_specialist_sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    # exit: this wallet's own latest Phase 3 exit_skill component
    # (wallet_score_snapshots.component_values["exit_capture"]) known by
    # as_of -- reused, not recomputed.
    exit_specialist_score: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)

    entry_percentile: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    discovery_percentile: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    validation_percentile: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    exit_percentile: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    dominant_specialty: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # R2-02 (argus-final-spec-recovery-002-clarification-001): machine-
    # checkable source-knowledge provenance -- the MAX created_at/
    # knowledge-time among every source row that actually contributed to
    # this score (across all four specialist dimensions), never merely
    # this row's OWN created_at (which only reflects when this
    # computation ran, not when its source evidence became knowable). A
    # loader consuming this row at decision time T must verify
    # source_knowledge_max_at <= T in addition to as_of == T -- as_of
    # alone is not sufficient proof of knowledge-time eligibility.
    source_knowledge_max_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
