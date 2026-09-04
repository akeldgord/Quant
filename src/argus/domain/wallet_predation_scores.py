"""``wallet_predation_scores`` — MASTER_SPEC.md Phase 9 (COUNTERFACTUAL
ALPHA + SPECIALISTS), section 61 (PREDATION DETECTION).

A profitable wallet may profit partly from its followers: leader buy ->
follower influx -> follower-driven price impact -> leader distribution.
Estimates all four of section 61's required evidence families --
follower influx and leader-exit timing (reusing Phase 7 lead/follow
observations and a raw-swap-derived exit signal), repetition frequency
(``exit_after_influx_count`` itself, incorporated into the score as a
confidence factor -- FSR-07), and real contemporaneous price-impact
evidence (the followers' own Phase 5 executable-entry price impact --
FSR-07, replacing the always-``NULL`` pre-recovery placeholder).
Composes them into a disclosed V1 ``predation_score`` heuristic (never a
calibrated probability -- section 38's own "V1 priors to be evaluated
prospectively" precedent). ``price_impact_incorporated`` records
honestly whether ``price_impact_mean`` was actually available and used
for this row -- FSR-07's own explicit rule that missing price impact
must make the result explicitly partial, never silently behave as
complete.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
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


class WalletPredationScore(Base):
    __tablename__ = "wallet_predation_scores"
    __table_args__ = (
        UniqueConstraint(
            "wallet_id",
            "as_of",
            "algorithm_version",
            "config_hash",
            name="uq_wallet_predation_scores_identity",
        ),
        CheckConstraint(
            "total_entries_count >= 0", name="ck_wallet_predation_scores_total_entries_nonneg"
        ),
        CheckConstraint(
            "entries_with_influx_count >= 0 AND entries_with_influx_count <= total_entries_count",
            name="ck_wallet_predation_scores_influx_count_range",
        ),
        CheckConstraint(
            "exit_after_influx_count >= 0 AND exit_after_influx_count <= entries_with_influx_count",
            name="ck_wallet_predation_scores_exit_after_influx_range",
        ),
        CheckConstraint(
            "predation_score IS NULL OR (predation_score >= 0 AND predation_score <= 1)",
            name="ck_wallet_predation_scores_predation_score_range",
        ),
        CheckConstraint(
            "length(algorithm_version) > 0", name="ck_wallet_predation_scores_algo_version_nonempty"
        ),
        CheckConstraint(
            "length(config_hash) > 0", name="ck_wallet_predation_scores_config_hash_nonempty"
        ),
    )

    score_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=False, index=True
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    total_entries_count: Mapped[int] = mapped_column(Integer, nullable=False)
    entries_with_influx_count: Mapped[int] = mapped_column(Integer, nullable=False)
    follower_influx_mean: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    exit_after_influx_count: Mapped[int] = mapped_column(Integer, nullable=False)
    exit_after_influx_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    price_impact_mean: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    price_impact_incorporated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    predation_score: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)

    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
