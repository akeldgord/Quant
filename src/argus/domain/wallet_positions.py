"""``wallet_positions`` — MASTER_SPEC.md section 35 (WALLET POSITION
RECONSTRUCTION), Phase 3 (`argus-phase-3-001`).

One derived, versioned per-(wallet, token) position summary, computed
with V1 weighted-average-cost inventory accounting directly from the
existing immutable ``swaps`` ledger (Phase 1) -- never a new raw-event
table duplicating what ``swaps`` already preserves verbatim. Section 35's
own "store raw position events so alternative accounting can later be
recomputed" is satisfied by ``swaps`` itself already being append-only,
immutable, and re-derivable from ``chain_events.raw_payload`` under a
different parser/accounting version without losing anything -- see
``argus.wallets.position_reconstruction`` for the derivation.

A row is never updated in place: a later reconstruction (more evidence, a
fixed accounting bug, a new ``algorithm_version``) appends a new row for
the same ``(wallet_id, token_id, round_trip_index)`` rather than mutating
history, matching the "derived score/position artifacts must be
versioned/reproducible" persistence rule. Downstream scoring always reads
the latest row per ``(wallet_id, token_id, round_trip_index)``.

``round_trip_index`` (Phase 3 remediation, `argus-phase-3-remediation-001`,
finding P3-R3): one wallet can genuinely buy, fully close, and later
reopen the same token -- each such closed-then-reopened cycle is a
separate, independently identified round trip (0-indexed per token, in
deterministic evidence order), not merged into one lifetime aggregate. A
still-open round trip is always the highest index for that
``(wallet_id, token_id)``. ``input_manifest_digest`` is a stable SHA-256
hex digest of the exact, ordered raw ``swaps.swap_id`` references that
fed this specific round trip -- "preserve every raw swap reference that
fed each round trip... via a stable input-manifest digest" (this
instruction's own requirement), independent of the derived numbers
themselves so a changed evidence set is always detectable even when it
happens to produce the same totals.

Amounts are denominated in whatever asset was actually exchanged on-chain
(``quote_asset_mint`` -- typically native SOL, sometimes a stablecoin),
never converted to a fabricated USD figure from missing/sparse price
data: this project never invents precision it does not have (the same
principle ``token_market_snapshots``/``reference_asset_prices`` already
established in Phase 2). All quantities are ``Decimal`` UI-adjusted
amounts (never raw u64, never binary float), taken directly from
``swaps.input_amount_ui``/``output_amount_ui`` -- Phase 1's own parser
already performed the raw-to-UI conversion correctly once; this module
never re-derives it independently.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"
CONFIDENCE_UNRESOLVED = "UNRESOLVED"

POSITION_CONFIDENCE_LEVELS: tuple[str, ...] = (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_LOW,
    CONFIDENCE_UNRESOLVED,
)

# Only HIGH/MEDIUM-confidence positions may materially contribute to
# qualification metrics (MASTER_SPEC.md section 35's own explicit rule).
RELIABLY_QUALIFYING_POSITION_CONFIDENCE: frozenset[str] = frozenset(
    {CONFIDENCE_HIGH, CONFIDENCE_MEDIUM}
)

STATUS_OPEN = "OPEN"
STATUS_CLOSED = "CLOSED"

POSITION_STATUSES: tuple[str, ...] = (STATUS_OPEN, STATUS_CLOSED)

_CONFIDENCE_LIST_SQL = ", ".join(f"'{c}'" for c in POSITION_CONFIDENCE_LEVELS)
_STATUS_LIST_SQL = ", ".join(f"'{s}'" for s in POSITION_STATUSES)


class WalletPosition(Base):
    """One derived weighted-average-cost position summary for one wallet
    in one token, as of one reconstruction run."""

    __tablename__ = "wallet_positions"
    __table_args__ = (
        CheckConstraint(
            f"confidence IN ({_CONFIDENCE_LIST_SQL})", name="ck_wallet_positions_confidence"
        ),
        CheckConstraint(f"status IN ({_STATUS_LIST_SQL})", name="ck_wallet_positions_status"),
        CheckConstraint(
            "length(quote_asset_mint) > 0", name="ck_wallet_positions_quote_asset_nonempty"
        ),
        CheckConstraint("partial_exit_count >= 0", name="ck_wallet_positions_partial_exit_count"),
        CheckConstraint("round_trip_index >= 0", name="ck_wallet_positions_round_trip_index"),
        CheckConstraint(
            "length(input_manifest_digest) > 0",
            name="ck_wallet_positions_input_manifest_digest_nonempty",
        ),
    )

    position_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=False, index=True
    )
    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tokens.token_id"), nullable=False, index=True
    )
    history_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallet_history_quality.history_id"), nullable=False
    )

    quote_asset_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    round_trip_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_manifest_digest: Mapped[str] = mapped_column(String(64), nullable=False)

    first_entry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_entry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    final_exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    entry_quantity: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    entry_value_quote: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    average_cost_quote: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)

    partial_exit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    realized_pnl_quote: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    unrealized_pnl_quote: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    holding_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    mfe_quote: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    mae_quote: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    peak_value_quote: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    # 0-1: realized exit value captured relative to the peak mark-to-market
    # value reached while the position was open. NULL when no exit
    # occurred yet or no peak could be established.
    peak_profit_capture: Mapped[Decimal | None] = mapped_column(Numeric(6, 5), nullable=True)

    confidence: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    git_commit: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
