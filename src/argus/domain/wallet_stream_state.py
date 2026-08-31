"""``wallet_stream_state`` — per-wallet fast-path/truth-path watermarks.

Schema per MASTER_SPEC.md section 19 (LIVE CHAIN OBSERVATION: FAST PATH +
TRUTH PATH) and section 20 (COMMITMENT POLICY). One row per tracked wallet.
Persisted so reconciliation state survives process restart (MASTER_SPEC
requires watermarks to persist across restart, not live only in memory).

``wallet_live_state`` starts ``OK`` and moves to ``DEGRADED`` whenever
reconciliation is triggered (disconnect, reconnect, process restart,
timeout, subscription failure, clock anomaly, host resume) and remains
unresolved. A ``DEGRADED`` wallet must never be treated by callers as
eligible for a new live-entry intent -- enforced by
``WalletStreamState.is_live_entry_eligible``, not by a DB constraint, since
"eligible" also depends on confirmed-vs-processed commitment policy that
lives outside this row.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

STREAM_HEALTH_OK = "OK"
STREAM_HEALTH_DEGRADED = "DEGRADED"
STREAM_HEALTH_UNKNOWN = "UNKNOWN"

WALLET_LIVE_STATE_OK = "OK"
WALLET_LIVE_STATE_DEGRADED = "DEGRADED"


class WalletStreamState(Base):
    """Persistent per-wallet stream/reconciliation watermarks."""

    __tablename__ = "wallet_stream_state"

    wallet_address: Mapped[str] = mapped_column(String(64), primary_key=True)

    last_stream_signature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_stream_slot: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    last_reconciled_signature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_reconciled_slot: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_reconciliation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    stream_health: Mapped[str] = mapped_column(
        String(16), nullable=False, default=STREAM_HEALTH_UNKNOWN
    )
    # Phase 1 remediation round 2, finding #1: the truth path's own
    # independent last-attempt outcome -- never set by the ingestion
    # manager, only by ReconciliationEngine.reconcile(). Fail-closed
    # default: a wallet that has never had a reconciliation attempt at
    # all must never look like one succeeded.
    reconciliation_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    wallet_live_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=WALLET_LIVE_STATE_DEGRADED
    )

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def is_live_entry_eligible(self) -> bool:
        """A DEGRADED wallet must never produce a new live-entry intent
        (MASTER_SPEC.md section 19). Phase 1 never actually enters a live
        trade -- this predicate exists now so later phases inherit the
        invariant instead of re-deriving it."""
        return self.wallet_live_state == WALLET_LIVE_STATE_OK
