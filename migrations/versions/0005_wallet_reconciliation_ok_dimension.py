"""phase 1 remediation round 2, finding #1: independent reconciliation_ok
dimension on wallet_stream_state

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-31

The prior schema had exactly one combined ``wallet_live_state`` column
and a ``stream_health`` column that both ``ReconciliationEngine.reconcile()``
and the ingestion manager wrote to -- a successful truth-path
reconciliation could set ``stream_health = OK`` and therefore
``wallet_live_state = OK`` even when no WebSocket connection had ever
been genuinely opened, subscribed, and acknowledged (the manager
constructed an async generator but never awaited its first iteration
before calling ``reconcile()``).

``reconciliation_ok`` makes the truth path's own last-attempt outcome an
explicit, independent column, owned exclusively by ``reconcile()`` --
``stream_health`` is now owned exclusively by the ingestion manager (via
``ReconciliationEngine.mark_stream_ready``/``mark_degraded``), and
``wallet_live_state`` is always derived from both plus a live clock-
health check, never set by one dimension alone.

Backfills existing rows' ``reconciliation_ok`` from whether they already
have a ``last_reconciliation_at`` timestamp -- a wallet that has already
completed at least one reconciliation is not worse off than before this
migration; a wallet that never has had one correctly starts ``false``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "wallet_stream_state",
        sa.Column("reconciliation_ok", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        "UPDATE wallet_stream_state SET reconciliation_ok = true "
        "WHERE last_reconciliation_at IS NOT NULL"
    )
    op.alter_column("wallet_stream_state", "reconciliation_ok", server_default=None)


def downgrade() -> None:
    op.drop_column("wallet_stream_state", "reconciliation_ok")
