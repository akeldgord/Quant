"""``exit_convergence_events`` — MASTER_SPEC.md Phase 9 (COUNTERFACTUAL
ALPHA + SPECIALISTS), section 63 (EXIT ORACLES): ``EXIT_CONVERGENCE``
among independent exit specialists.

The exact same convergence-episode shape Phase 8's ``convergence_events``
built for entries, reused unchanged (same fields, same
``argus.convergence.episodes``/``stats``/``independence`` pure logic)
against an exit-event population restricted to wallets classified as
exit specialists (``wallet_specialist_scores.exit_specialist_score``
above a disclosed threshold) -- MASTER_SPEC's own "do not require that
the wallet originally sourced the position" (section 63).
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


class ExitConvergenceEvent(Base):
    __tablename__ = "exit_convergence_events"
    __table_args__ = (
        UniqueConstraint(
            "token_id",
            "window_start",
            "as_of",
            "algorithm_version",
            "config_hash",
            name="uq_exit_convergence_events_identity",
        ),
        CheckConstraint(
            "raw_wallet_count >= 1", name="ck_exit_convergence_events_raw_count_positive"
        ),
        CheckConstraint(
            "estimated_independent_actors > 0 AND estimated_independent_actors <= raw_wallet_count",
            name="ck_exit_convergence_events_independent_actors_range",
        ),
        CheckConstraint("expected_overlap >= 0", name="ck_exit_convergence_events_expected_nonneg"),
        CheckConstraint(
            "empirical_probability > 0 AND empirical_probability <= 1",
            name="ck_exit_convergence_events_probability_range",
        ),
        CheckConstraint("surprisal >= 0", name="ck_exit_convergence_events_surprisal_nonneg"),
        CheckConstraint("sample_size >= 0", name="ck_exit_convergence_events_sample_size_nonneg"),
        CheckConstraint(
            "window_end >= window_start", name="ck_exit_convergence_events_window_order"
        ),
        CheckConstraint(
            "calibration_confidence IN ('INSUFFICIENT_SAMPLE', 'LOW', 'MEDIUM', 'HIGH')",
            name="ck_exit_convergence_events_calibration_confidence",
        ),
        CheckConstraint(
            "length(algorithm_version) > 0", name="ck_exit_convergence_events_algo_version_nonempty"
        ),
        CheckConstraint(
            "length(config_hash) > 0", name="ck_exit_convergence_events_config_hash_nonempty"
        ),
    )

    exit_convergence_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tokens.token_id"), nullable=False, index=True
    )
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    raw_wallet_count: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_independent_actors: Mapped[Decimal] = mapped_column(Numeric(20, 15), nullable=False)
    expected_overlap: Mapped[Decimal] = mapped_column(Numeric(20, 15), nullable=False)
    observed_overlap: Mapped[Decimal] = mapped_column(Numeric(20, 15), nullable=False)
    empirical_probability: Mapped[Decimal] = mapped_column(Numeric(20, 15), nullable=False)
    surprisal: Mapped[Decimal] = mapped_column(Numeric(20, 15), nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    calibration_confidence: Mapped[str] = mapped_column(String(32), nullable=False)

    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
