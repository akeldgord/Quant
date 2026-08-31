"""``chain_events`` — immutable, append-only canonical event ledger.

Schema per MASTER_SPEC.md section 18 (CANONICAL EVENT LEDGER) and CORE-002
(section 5: raw observations are immutable/append-only) and CORE-003
(section 5: point-in-time truth — ``block_time`` and ``first_seen_at`` are
kept distinct from commitment progression; a WebSocket receipt alone is
never proof of complete/confirmed observation).

Commitment progression (processed/confirmed/finalized, and transaction
execution success/failure) is deliberately NOT a column on this table --
see ``argus.domain.commitment.CommitmentObservation`` and
``argus.ingestion.commitment``. An earlier design tried
``confirmed_at``/``finalized_at`` columns here, but because this table
dedups on ``(transaction_signature, wallet_address, event_type)``, a
truth-path promotion attempt for an already-fast-path-recorded event
always collided with that unique constraint and was silently dropped
(Phase 1 remediation round 1, finding #3; see
``migrations/versions/0003_commitment_observations_and_swap_dedup.py``).

Rows are never updated or deleted by application code (append-only). Derived
data (e.g. ``swaps``, ``commitment_observations``) may be recomputed/appended
from raw evidence without rewriting this table. ``payload_hash`` lets any
consumer verify ``raw_payload`` was not altered after ingestion, and the raw
payload itself remains available for replay/re-parsing under a new
``parser_version`` without a second network fetch.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base


class ChainEvent(Base):
    """One immutable observation of a transaction touching a tracked wallet.

    Deduplicated on ``(transaction_signature, wallet_address, event_type)``:
    the same on-chain transaction observed twice (e.g. once via the
    WebSocket fast path, once via truth-path reconciliation) must canonicalize
    to exactly one row, per the mandatory disconnect/reconnect/duplicate-
    delivery scenario in MASTER_SPEC.md section 19.
    """

    __tablename__ = "chain_events"
    __table_args__ = (
        UniqueConstraint(
            "transaction_signature",
            "wallet_address",
            "event_type",
            name="uq_chain_events_signature_wallet_type",
        ),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    chain: Mapped[str] = mapped_column(String(32), nullable=False, default="solana")
    slot: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    block_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Point-in-time truth (CORE-003): first observation only. Commitment
    # progression lives in commitment_observations, not here (see module
    # docstring).
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    transaction_signature: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    wallet_address: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    mint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Raw provider evidence, preserved verbatim for replay. Never mutated.
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
