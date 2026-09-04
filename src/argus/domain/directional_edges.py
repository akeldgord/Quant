"""``directional_edges`` — MASTER_SPEC.md Phase 7 (ALPHA ANCESTRY).

One row per (leader wallet, follower wallet) pair per computation run:
the base-rate-corrected, multiple-comparison-corrected aggregate
statistics MASTER_SPEC's own required report fields list (observation
counts, lift, median lag, effect size, p-value, q-value, forward
information after leader). ``config_hash`` is part of this table's own
unique identity (the same F5-05 pattern Phase 5 established) so a
changed lag window/base-rate universe/algorithm always produces a new
row, never a silent overwrite of a prior run's results.
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


class DirectionalEdge(Base):
    __tablename__ = "directional_edges"
    __table_args__ = (
        UniqueConstraint(
            "leader_wallet_id",
            "follower_wallet_id",
            "as_of",
            "algorithm_version",
            "config_hash",
            name="uq_directional_edges_identity",
        ),
        CheckConstraint(
            "leader_wallet_id != follower_wallet_id", name="ck_directional_edges_distinct_wallets"
        ),
        CheckConstraint("observation_count >= 0", name="ck_directional_edges_obs_nonneg"),
        CheckConstraint("tokens_leader_entered >= 0", name="ck_directional_edges_tokens_nonneg"),
        CheckConstraint("p_value >= 0 AND p_value <= 1", name="ck_directional_edges_p_value_range"),
        CheckConstraint("q_value >= 0 AND q_value <= 1", name="ck_directional_edges_q_value_range"),
        CheckConstraint(
            "length(algorithm_version) > 0", name="ck_directional_edges_algo_version_nonempty"
        ),
        CheckConstraint(
            "length(config_hash) > 0", name="ck_directional_edges_config_hash_nonempty"
        ),
        CheckConstraint(
            "forward_information_sample_count IS NULL OR forward_information_sample_count >= 0",
            name="ck_directional_edges_forward_info_sample_nonneg",
        ),
        CheckConstraint(
            "forward_information_eligible_count IS NULL OR forward_information_eligible_count >= 0",
            name="ck_directional_edges_forward_info_eligible_nonneg",
        ),
        CheckConstraint(
            "forward_information_sample_count IS NULL "
            "OR forward_information_eligible_count IS NULL "
            "OR forward_information_sample_count <= forward_information_eligible_count",
            name="ck_directional_edges_forward_info_sample_le_eligible",
        ),
    )

    edge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    leader_wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=False, index=True
    )
    follower_wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=False, index=True
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    observation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_leader_entered: Mapped[int] = mapped_column(Integer, nullable=False)
    follower_base_rate: Mapped[Decimal] = mapped_column(Numeric(20, 15), nullable=False)
    median_lag_seconds: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    expected_follows: Mapped[Decimal] = mapped_column(Numeric(20, 15), nullable=False)
    lift: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    effect_size: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    p_value: Mapped[Decimal] = mapped_column(Numeric(20, 15), nullable=False)
    q_value: Mapped[Decimal] = mapped_column(Numeric(20, 15), nullable=False)
    # Reuses the follower's own already-computed Phase 5 executable-return
    # evidence (never a fabricated/re-derived price series) at the
    # follower's real entry delay after this leader -- None when no such
    # evidence exists yet for this specific observation set. FSR-05: the
    # mean of every SUCCESS 5m executable return matched to this pair's
    # observations by (token_id, follower_entered_at); the two count
    # columns and the missing-reason column make the evidence population
    # behind that mean (or its absence) visible rather than a bare NULL.
    forward_information_after_leader_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 15), nullable=True
    )
    forward_information_sample_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forward_information_eligible_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forward_information_missing_reason: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
