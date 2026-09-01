"""``tokens`` — the canonical token-mint identity registry (MASTER_SPEC.md
section 27, "Token domain").

Phase 2 (TOKEN + WALLET DISCOVERY). A row is created by the bootstrap
importer the moment a candidate mint address is submitted -- BEFORE any
on-chain validation runs -- so a malformed or not-yet-validated mint is
still a real, queryable row (never silently dropped), but ``mint_validated``
starts ``False`` and only ever flips to ``True`` in response to a genuine
``token_mint_validations`` row with ``validation_status = 'VALID'``
(``argus.domain.token_mint_validations``). Address shape alone (a
plausible-looking base58 string) is never sufficient to set it -- see
``argus.tokens.mint_validation``. The full validation evidence trail is
queried from ``token_mint_validations`` by ``token_id`` (deliberately no
``tokens.mint_validation_id`` back-pointer -- that would create a circular
foreign key between the two tables for no benefit over an ordinary
``WHERE token_id = ... ORDER BY created_at DESC`` query).

``current_lifecycle_stage`` is a denormalized cache of the most recent
``token_market_snapshots`` row's ``lifecycle_stage`` for cheap reads; the
full point-in-time history (never overwritten) lives in
``token_market_snapshots`` itself (MASTER_SPEC.md section 24).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

LIFECYCLE_TOKEN_CREATION = "TOKEN_CREATION"
LIFECYCLE_BONDING_CURVE = "BONDING_CURVE"
LIFECYCLE_LAUNCHPAD_TRADING = "LAUNCHPAD_TRADING"
LIFECYCLE_MIGRATION = "MIGRATION"
LIFECYCLE_AMM_POOL = "AMM_POOL"
LIFECYCLE_MULTIPLE_POOLS = "MULTIPLE_POOLS"

LIFECYCLE_STAGES: tuple[str, ...] = (
    LIFECYCLE_TOKEN_CREATION,
    LIFECYCLE_BONDING_CURVE,
    LIFECYCLE_LAUNCHPAD_TRADING,
    LIFECYCLE_MIGRATION,
    LIFECYCLE_AMM_POOL,
    LIFECYCLE_MULTIPLE_POOLS,
)


class Token(Base):
    """One candidate Solana token mint ARGUS has been asked to track."""

    __tablename__ = "tokens"
    __table_args__ = (UniqueConstraint("mint", name="uq_tokens_mint"),)

    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    mint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    chain: Mapped[str] = mapped_column(String(32), nullable=False, default="solana")

    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Denormalized cache -- always derived from a real token_mint_validations
    # row, never set from address shape alone (argus.tokens.mint_validation).
    mint_validated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Denormalized cache of the latest token_market_snapshots row; the full
    # point-in-time history is never overwritten (see that table).
    current_lifecycle_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
