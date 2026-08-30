"""``provider_usage`` — canonical record of every outbound provider request.

Schema per MASTER_SPEC.md section 14 (PROVIDER COST GUARD) and section 27
(CORE DATA ENTITIES / Operations). Populated starting Phase 1 once real
provider adapters exist; the table itself is part of the Phase 0 foundation
so cost-guard accounting has somewhere to write from day one of Phase 1.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base


class ProviderUsage(Base):
    """One row per outbound HTTP/RPC request or streaming accounting tick."""

    __tablename__ = "provider_usage"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(String(256), nullable=False)
    request_class: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    estimated_credits: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    bytes_received: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Streaming-specific accounting (section 14, "Streaming accounting must
    # additionally record ..."). Null for ordinary request/response rows.
    connection_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subscription_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reconnect_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_streaming_credits: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 6), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
