"""``expected_confirmation_events`` — MASTER_SPEC.md Phase 8 (CONVERGENCE
+ NEGATIVE EVIDENCE), section 60 (DOG-THAT-DIDN'T-BARK SIGNAL).

One row per (significant Phase 7 directional edge, leader's own real buy
entry): a classification of whether the historically-expected follower
confirmation occurred, and how -- ``ABSENT`` (section 60's own mandatory
negative-evidence signal), ``EARLY``/``LATE`` (outside the edge's own
empirical historical lag band), ``STRONG`` (coincided with an unusually
high independent-actor convergence), or ``NORMAL``. ``config_hash`` is
part of this table's own unique identity (the same F5-05 pattern Phase 5
established) so a changed policy/algorithm always produces a new row,
never a silent overwrite of a prior run's classification.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base


class ExpectedConfirmationEvent(Base):
    __tablename__ = "expected_confirmation_events"
    __table_args__ = (
        UniqueConstraint(
            "directional_edge_id",
            "leader_prospective_event_id",
            "as_of",
            "algorithm_version",
            "config_hash",
            name="uq_expected_confirmation_events_identity",
        ),
        CheckConstraint(
            "outcome IN ('ABSENT', 'EARLY', 'LATE', 'STRONG', 'NORMAL')",
            name="ck_expected_confirmation_events_outcome",
        ),
        CheckConstraint(
            "(outcome = 'ABSENT' AND follower_entered_at IS NULL AND lag_seconds IS NULL) OR "
            "(outcome != 'ABSENT' AND follower_entered_at IS NOT NULL AND lag_seconds IS NOT NULL)",
            name="ck_expected_confirmation_events_absent_consistency",
        ),
        CheckConstraint(
            "lag_seconds IS NULL OR lag_seconds > 0",
            name="ck_expected_confirmation_events_lag_positive",
        ),
        CheckConstraint(
            "expected_window_low_seconds >= 0",
            name="ck_expected_confirmation_events_window_low_nonneg",
        ),
        CheckConstraint(
            "expected_window_high_seconds >= expected_window_low_seconds",
            name="ck_expected_confirmation_events_window_order",
        ),
        CheckConstraint(
            "leader_wallet_id != follower_wallet_id",
            name="ck_expected_confirmation_events_distinct_wallets",
        ),
        CheckConstraint(
            "length(algorithm_version) > 0",
            name="ck_expected_confirmation_events_algo_version_nonempty",
        ),
        CheckConstraint(
            "length(config_hash) > 0", name="ck_expected_confirmation_events_config_hash_nonempty"
        ),
    )

    expected_confirmation_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    directional_edge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("directional_edges.edge_id"), nullable=False, index=True
    )
    leader_prospective_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prospective_events.prospective_event_id"), nullable=False
    )
    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tokens.token_id"), nullable=False, index=True
    )
    leader_wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=False
    )
    follower_wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=False
    )

    outcome: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    follower_entered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lag_seconds: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    expected_window_low_seconds: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    expected_window_high_seconds: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    # Set only for an outcome of STRONG -- the convergence episode whose
    # unusually high independent-actor surprisal justified that
    # classification (MASTER_SPEC.md section 60's own "also support
    # EXPECTED_CONFIRMATION_STRONG").
    convergence_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("convergence_events.convergence_event_id"), nullable=True
    )

    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
