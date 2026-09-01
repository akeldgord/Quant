"""``shadow_intents`` — MASTER_SPEC.md section 45 (SHADOW COPY EXECUTION),
Phase 4 (`argus-phase-4-001`).

One row per :class:`~argus.domain.prospective_events.ProspectiveEvent`
that passed the honest, research-only shadow-eligibility gate (never a
live-trading authorization -- ``config/signals_v1.yaml``'s existing
``wallet_tier_allowed``/``qualification_score_min`` thresholds, the same
ones already governing live eligibility elsewhere in this project,
reused rather than a manufactured, looser Phase-4-only bar). Represents
the *intent* to shadow-copy this trade with a standardized small
notional; the actual attempted entry quotes are
:class:`~argus.domain.shadow_quote_probes.ShadowQuoteProbe` rows with
``probe_kind='ENTRY_DELAY'``, and a successful one produces exactly one
:class:`~argus.domain.shadow_positions.ShadowPosition`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

STATUS_CREATED = "CREATED"
STATUS_FILLED = "FILLED"
STATUS_NO_FILL = "NO_FILL"

_VALID_STATUSES_SQL = "'CREATED', 'FILLED', 'NO_FILL'"


class ShadowIntent(Base):
    """One qualifying prospective event's intent to shadow-copy, with a
    standardized notional (section 46: "Use standardized shadow
    notionals. V1 may begin with one configurable small notional.")."""

    __tablename__ = "shadow_intents"
    __table_args__ = (
        UniqueConstraint("prospective_event_id", name="uq_shadow_intents_prospective_event_id"),
        CheckConstraint(f"status IN ({_VALID_STATUSES_SQL})", name="ck_shadow_intents_status"),
        CheckConstraint(
            "notional_input_amount_raw > 0", name="ck_shadow_intents_notional_positive"
        ),
        CheckConstraint("length(config_hash) > 0", name="ck_shadow_intents_config_hash_nonempty"),
    )

    shadow_intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    prospective_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prospective_events.prospective_event_id"),
        nullable=False,
        index=True,
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=False, index=True
    )
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tokens.token_id"), nullable=True
    )

    input_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    output_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    notional_input_amount_raw: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Binds this intent's exact notional/threshold identity to the config
    # that produced it (section 46's "retain its asset/raw units and
    # config identity") -- never merely descriptive metadata.
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_CREATED)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
