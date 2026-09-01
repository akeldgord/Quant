"""``shadow_positions`` — MASTER_SPEC.md section 45 (SHADOW COPY
EXECUTION: "shadow fill recorded"), Phase 4 (`argus-phase-4-001`).

Created exactly once, the moment the FIRST entry-delay probe
(:class:`~argus.domain.shadow_quote_probes.ShadowQuoteProbe`,
``probe_kind='ENTRY_DELAY'``) for a
:class:`~argus.domain.shadow_intents.ShadowIntent` actually resolves a
usable route -- never from a later price chart ("Never create an
imaginary historical fill from a later price chart," section 45's own
explicit rule). ``entry_probe_target_label`` names WHICH delay probe
produced this fill (e.g. ``"5s"``) as a plain label, not a foreign key --
avoiding a circular reference back to ``shadow_quote_probes`` (whose own
``REVERSE_EXECUTABLE``/``MARK`` rows reference this table's
``shadow_position_id`` instead).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
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


class ShadowPosition(Base):
    """One real, honestly-timestamped simulated entry fill and the
    resulting held shadow position, awaiting mark/executable outcomes."""

    __tablename__ = "shadow_positions"
    __table_args__ = (
        UniqueConstraint("shadow_intent_id", name="uq_shadow_positions_shadow_intent_id"),
        CheckConstraint(
            "entry_input_amount_raw > 0", name="ck_shadow_positions_input_amount_positive"
        ),
        CheckConstraint(
            "entry_output_amount_raw > 0", name="ck_shadow_positions_output_amount_positive"
        ),
        CheckConstraint(
            "length(entry_probe_target_label) > 0",
            name="ck_shadow_positions_entry_probe_label_nonempty",
        ),
    )

    shadow_position_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    shadow_intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shadow_intents.shadow_intent_id"), nullable=False
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=False, index=True
    )
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tokens.token_id"), nullable=True
    )

    input_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    output_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_input_amount_raw: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entry_output_amount_raw: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entry_price_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    entry_route_present: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    entry_fee_estimate_raw: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Best-effort market price (USD) for the output token at fill time --
    # the baseline ``shadow_mark_outcomes.mark_return_pct`` is computed
    # against. NULL (never a fabricated value) when no market-data
    # provider snapshot was available at fill time; mark outcomes remain
    # descriptive-only either way (section 47).
    entry_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)

    # Which entry-delay probe (by its label, e.g. "5s") actually produced
    # this fill -- a plain label, not an FK (see module docstring).
    entry_probe_target_label: Mapped[str] = mapped_column(String(16), nullable=False)
    entry_requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_responded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
