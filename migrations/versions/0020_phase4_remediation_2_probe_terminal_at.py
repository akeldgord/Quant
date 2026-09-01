"""Phase 4 remediation round 2: shadow_quote_probes.terminal_at

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-01

Per orchestrator instruction ``argus-phase-4-remediation-002`` (P4-R4
continued): "A scheduler drop before dispatch has no request/response
timestamps or call latency. Persist its terminal decision time/reason
separately... use explicit terminal state/time for claim, no-op,
intent-finalization and report logic instead of assuming responded_at
non-null is the only completion proof."

Adds a nullable ``terminal_at`` column to ``shadow_quote_probes``, set on
EVERY terminal write regardless of whether a real provider dispatch ever
happened -- ``requested_at``/``responded_at``/``latency_ms``/
``scheduling_delay_seconds`` now stay honestly ``NULL`` for a genuine
scheduler-level capacity drop (no request/response ever occurred), while
``terminal_at`` still records exactly when that drop was decided and
recorded. Additive only; no existing row's meaning changes; no new grant
needed (migration 0016's table-level UPDATE grant on ``shadow_quote_
probes`` for ``argus_ingest`` already covers this new column).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shadow_quote_probes",
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_shadow_probes_responded_requires_terminal",
        "shadow_quote_probes",
        "responded_at IS NULL OR terminal_at IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_shadow_probes_responded_requires_terminal", "shadow_quote_probes", type_="check"
    )
    op.drop_column("shadow_quote_probes", "terminal_at")
