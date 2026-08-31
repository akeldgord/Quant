"""``commitment_observations`` — append-only commitment-progression log.

Replaces the earlier (broken) design where ``chain_events.confirmed_at``/
``finalized_at`` were meant to be set by a later write against an
already-inserted row: because ``chain_events`` dedups on
``(transaction_signature, wallet_address, event_type)``, a truth-path
promotion attempt for an already-fast-path-recorded event always hit the
unique constraint and was silently dropped (see
``docs/DECISION_LOG.md``, Phase 1 remediation round 1, finding #3).

This table is the durable side of commitment progression instead: every
provider observation of a transaction's commitment level (``PROCESSED``/
``CONFIRMED``/``FINALIZED``) is appended here, keyed to the immutable
``chain_events`` row it describes, never overwriting a prior observation.
Current commitment state is a deterministic *derived* query over this log
(highest commitment rank, most recent ``observed_at`` on ties), not a
mutable column anywhere -- see
:mod:`argus.ingestion.commitment` for the derivation logic.

Commitment level is kept strictly separate from transaction *execution*
success/failure: a transaction can be finalized on-chain while its
instructions failed (``transaction_succeeded=False``), and a failed
transaction is still real point-in-time truth worth recording -- it is
simply mechanically excluded from live-copy eligibility (enforced by
:func:`argus.ingestion.commitment.is_execution_eligible`, not by this
table).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

COMMITMENT_PROCESSED = "PROCESSED"
COMMITMENT_CONFIRMED = "CONFIRMED"
COMMITMENT_FINALIZED = "FINALIZED"

COMMITMENT_RANK: dict[str, int] = {
    COMMITMENT_PROCESSED: 0,
    COMMITMENT_CONFIRMED: 1,
    COMMITMENT_FINALIZED: 2,
}


class CommitmentObservation(Base):
    """One append-only observation of a ``chain_events`` row's commitment
    level. Never updated or deleted by application code."""

    __tablename__ = "commitment_observations"

    observation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chain_events.event_id"), nullable=False, index=True
    )

    commitment_level: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # None = not yet knowable from this observation (e.g. a bare WebSocket
    # notification carries no execution-result field at all); True/False
    # once a provider has actually reported success/failure.
    transaction_succeeded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
