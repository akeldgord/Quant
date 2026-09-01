"""``token_market_snapshots`` — point-in-time token lifecycle + market-state
observations (MASTER_SPEC.md section 24 TOKEN LIFECYCLE MODEL, section 26
HISTORICAL MARKET-STATE RULE, Phase 2 build items 3-4).

One row per (token, source, observed_at): repeated observations from the
same source at the same observation time deduplicate (idempotent replay);
a later observation never overwrites an earlier one -- point-in-time truth
is preserved by simply accumulating rows, exactly like
``argus.domain.chain_events``. ``observed_at`` (ARGUS's own capture time)
is kept distinct from ``chain_time`` (the chain-observed time, where
available) per CORE-003.

Section 26's rule: historical market cap/supply/liquidity/FDV must never
be computed from today's values backfilled onto a historical timestamp.
When contemporaneous evidence cannot be recovered, the affected numeric
field is ``NULL`` -- preferable to false precision -- and
``market_state_confidence`` records how much to trust what *is* present
(``HIGH``/``MEDIUM``/``LOW``/``UNKNOWN``, mirroring MASTER_SPEC.md section
34's wallet-history-completeness states).
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
from argus.domain.tokens import LIFECYCLE_STAGES
from argus.domain.u64 import U64Numeric, u64_check_constraints

MARKET_STATE_CONFIDENCE_HIGH = "HIGH"
MARKET_STATE_CONFIDENCE_MEDIUM = "MEDIUM"
MARKET_STATE_CONFIDENCE_LOW = "LOW"
MARKET_STATE_CONFIDENCE_UNKNOWN = "UNKNOWN"

MARKET_STATE_CONFIDENCE_LEVELS: tuple[str, ...] = (
    MARKET_STATE_CONFIDENCE_HIGH,
    MARKET_STATE_CONFIDENCE_MEDIUM,
    MARKET_STATE_CONFIDENCE_LOW,
    MARKET_STATE_CONFIDENCE_UNKNOWN,
)

_LIFECYCLE_STAGE_LIST_SQL = ", ".join(f"'{stage}'" for stage in LIFECYCLE_STAGES)
_MARKET_STATE_CONFIDENCE_LIST_SQL = ", ".join(
    f"'{level}'" for level in MARKET_STATE_CONFIDENCE_LEVELS
)


class TokenMarketSnapshot(Base):
    """One point-in-time lifecycle + market-state observation of a token."""

    __tablename__ = "token_market_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "token_id",
            "source",
            "observed_at",
            name="uq_token_market_snapshots_token_source_observed_at",
        ),
        CheckConstraint(
            f"lifecycle_stage IN ({_LIFECYCLE_STAGE_LIST_SQL})",
            name="ck_token_market_snapshots_lifecycle_stage",
        ),
        CheckConstraint(
            f"market_state_confidence IS NULL OR "
            f"market_state_confidence IN ({_MARKET_STATE_CONFIDENCE_LIST_SQL})",
            name="ck_token_market_snapshots_market_state_confidence",
        ),
        *u64_check_constraints("token_market_snapshots", "supply_raw"),
    )

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tokens.token_id"), nullable=False, index=True
    )

    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    chain_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    lifecycle_stage: Mapped[str] = mapped_column(String(32), nullable=False)
    venue: Mapped[str | None] = mapped_column(String(64), nullable=True)
    venue_program: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pool_or_curve_address: Mapped[str | None] = mapped_column(String(64), nullable=True)

    price_usd: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    supply_raw: Mapped[int | None] = mapped_column(U64Numeric, nullable=True)
    liquidity_usd: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    fdv_usd: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    market_cap_usd: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)

    # NULL (never false precision) when contemporaneous evidence for the
    # numeric fields above cannot be recovered (MASTER_SPEC.md section 26).
    market_state_confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)

    source: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_reference: Mapped[str | None] = mapped_column(String(256), nullable=True)

    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    build_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
