"""``token_mint_validations`` — append-only, immutable evidence ledger for
on-chain mint validation (MASTER_SPEC.md Phase 2 build item 14, required
implementation item 2).

Address shape alone (a plausible-looking base58 string) is never proof a
mint exists on-chain -- this ledger exists to force every "is this a real
token mint" decision through committed chain/provider evidence, recording
exactly what evidence was used and when, mirroring
``argus.domain.parse_attempts``'s append-only decision-ledger pattern
(never updated or deleted by application code; a later re-validation
appends a new row rather than overwriting an earlier belief). See
``argus.tokens.mint_validation`` for the validator.

Malformed, missing, conflicting, unresolvable, wrong-owner, or non-mint
account evidence produces ``validation_status = 'INVALID'``. A provider-
capacity or environmental miss (no reachable provider, timeout, etc.)
produces ``validation_status = 'UNAVAILABLE'`` -- explicitly never silently
promoted to ``'VALID'``. Only ``'VALID'`` may ever flip
``tokens.mint_validated`` to ``True``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base
from argus.domain.identity_mixin import FullIdentityMixin, full_identity_check_constraints

VALIDATION_STATUS_VALID = "VALID"
VALIDATION_STATUS_INVALID = "INVALID"
VALIDATION_STATUS_UNAVAILABLE = "UNAVAILABLE"

VALIDATION_STATUSES: tuple[str, ...] = (
    VALIDATION_STATUS_VALID,
    VALIDATION_STATUS_INVALID,
    VALIDATION_STATUS_UNAVAILABLE,
)


class TokenMintValidation(FullIdentityMixin, Base):
    """One immutable attempt to prove (or disprove) that a candidate
    address is a genuine on-chain Solana token mint."""

    __tablename__ = "token_mint_validations"
    __table_args__ = (
        CheckConstraint(
            "validation_status IN ('VALID', 'INVALID', 'UNAVAILABLE')",
            name="ck_token_mint_validations_status",
        ),
        CheckConstraint(
            "length(evidence_reference) > 0",
            name="ck_token_mint_validations_evidence_reference_nonempty",
        ),
        *full_identity_check_constraints("token_mint_validations"),
    )

    validation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tokens.token_id"), nullable=False, index=True
    )

    validation_status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    validation_source: Mapped[str] = mapped_column(String(64), nullable=False)

    # ARGUS's own observation time vs. the chain-observed time -- kept
    # distinct per CORE-003 point-in-time truth, same as chain_events.
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    chain_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    commitment: Mapped[str | None] = mapped_column(String(16), nullable=True)

    evidence_reference: Mapped[str] = mapped_column(String(256), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)

    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
