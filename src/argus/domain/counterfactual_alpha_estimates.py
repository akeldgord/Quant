"""``counterfactual_alpha_estimates`` — MASTER_SPEC.md Phase 9
(COUNTERFACTUAL ALPHA + SPECIALISTS), section 55 (COUNTERFACTUAL ALPHA).

For each real wallet entry, at each configured horizon: the wallet's own
forward return on that token minus the mean forward return of a
point-in-time matched control-token set -- ``residual_selection_alpha``.
Both components (and therefore the residual) are ``NULL`` when
contemporaneous price evidence is unavailable -- never fabricated.
``config_hash`` is part of this table's own unique identity (the same
F5-05 pattern Phase 5 established) so a changed matching/horizon policy
always produces a new row, never a silent overwrite of a prior run.
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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base


class CounterfactualAlphaEstimate(Base):
    __tablename__ = "counterfactual_alpha_estimates"
    __table_args__ = (
        UniqueConstraint(
            "prospective_event_id",
            "horizon_seconds",
            "as_of",
            "algorithm_version",
            "config_hash",
            name="uq_counterfactual_alpha_estimates_identity",
        ),
        CheckConstraint(
            "horizon_seconds > 0", name="ck_counterfactual_alpha_estimates_horizon_positive"
        ),
        CheckConstraint(
            "matched_control_count >= 0",
            name="ck_counterfactual_alpha_estimates_control_count_nonneg",
        ),
        CheckConstraint(
            "(wallet_token_forward_return IS NOT NULL AND matched_universe_forward_return IS NOT NULL) "
            "OR residual_selection_alpha IS NULL",
            name="ck_counterfactual_alpha_estimates_residual_consistency",
        ),
        CheckConstraint(
            "length(algorithm_version) > 0",
            name="ck_counterfactual_alpha_estimates_algo_version_nonempty",
        ),
        CheckConstraint(
            "length(config_hash) > 0", name="ck_counterfactual_alpha_estimates_config_hash_nonempty"
        ),
    )

    estimate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    prospective_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prospective_events.prospective_event_id"), nullable=False
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=False, index=True
    )
    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tokens.token_id"), nullable=False, index=True
    )
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    horizon_seconds: Mapped[int] = mapped_column(Integer, nullable=False)

    wallet_token_forward_return: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 15), nullable=True
    )
    matched_universe_forward_return: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 15), nullable=True
    )
    residual_selection_alpha: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    matched_control_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # {"market_cap_bucket": ..., "liquidity_bucket": ..., "token_age_bucket": ...,
    #  "launch_venue": ..., "control_token_ids": [...]} -- reproducibility
    # evidence for exactly which control tokens and matching criteria
    # produced this estimate (CORE-004).
    matching_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)

    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
