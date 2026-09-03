"""``lead_follow_observations`` — MASTER_SPEC.md Phase 7 (ALPHA ANCESTRY).

One append-only row per (token, leader wallet, follower wallet): the
follower entered this token strictly after the leader, within the
computing algorithm's own configured lag window
(``argus.graph.lead_follow.build_lead_follow_observations``). Purely
observational -- see that module's own docstring for why this table
never implies causation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base


class LeadFollowObservation(Base):
    __tablename__ = "lead_follow_observations"
    __table_args__ = (
        UniqueConstraint(
            "token_id",
            "leader_wallet_id",
            "follower_wallet_id",
            "algorithm_version",
            name="uq_lead_follow_observations_identity",
        ),
        CheckConstraint("lag_seconds > 0", name="ck_lead_follow_observations_lag_positive"),
        CheckConstraint(
            "leader_wallet_id != follower_wallet_id",
            name="ck_lead_follow_observations_distinct_wallets",
        ),
        CheckConstraint(
            "follower_entered_at > leader_entered_at",
            name="ck_lead_follow_observations_follower_after_leader",
        ),
        CheckConstraint(
            "length(algorithm_version) > 0",
            name="ck_lead_follow_observations_algo_version_nonempty",
        ),
    )

    observation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tokens.token_id"), nullable=False, index=True
    )
    leader_wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=False, index=True
    )
    follower_wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=False, index=True
    )
    leader_prospective_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prospective_events.prospective_event_id"), nullable=False
    )
    follower_prospective_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prospective_events.prospective_event_id"), nullable=False
    )
    leader_entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    follower_entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lag_seconds: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
