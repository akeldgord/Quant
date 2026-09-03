"""``executor_leases`` — MASTER_SPEC.md section 75 (EXECUTOR SINGLETON),
Phase 6 (``argus-phase-6-001``).

A single-row (``lease_id = 'primary'``) compare-and-swap lease/fencing-
token table: only one live executor process may hold the lease at a
time. ``acquire_lease``/``renew_lease`` (``argus.executor.singleton``)
are the only code paths that ever write this table -- see that module's
own docstring for the exact fencing-token protocol.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

PRIMARY_LEASE_ID = "primary"


class ExecutorLease(Base):
    """The single active-executor lease row. Never more than one row
    exists (``lease_id`` is a fixed singleton value, enforced by a CHECK
    constraint as well as the primary key)."""

    __tablename__ = "executor_leases"
    __table_args__ = (
        CheckConstraint("lease_id = 'primary'", name="ck_executor_leases_lease_id_singleton"),
        CheckConstraint("fencing_token > 0", name="ck_executor_leases_fencing_token_positive"),
    )

    lease_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=PRIMARY_LEASE_ID)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    fencing_token: Mapped[int] = mapped_column(BigInteger, nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
