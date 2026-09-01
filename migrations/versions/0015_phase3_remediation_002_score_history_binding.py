"""Phase 3 remediation round 2 (P3-R6b): bind score identity to history.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-01

Adds ``wallet_score_snapshots.history_id`` (nullable, FK to
``wallet_history_quality.history_id``) so a score's own semantic
identity is bound to the exact, append-only history-quality row (and
therefore acquisition manifest/reason/provider/boundary/coverage) that
justified it -- a changed history reason or manifest with an otherwise
equal final score is now always a different decision, never mistaken for
the same one. Nullable for the same reason as P3-R6a's other new
provenance columns: a legacy row computed before this binding existed
has no honest value to backfill.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "wallet_score_snapshots",
        sa.Column(
            "history_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallet_history_quality.history_id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_wallet_score_snapshots_history_id", "wallet_score_snapshots", ["history_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_wallet_score_snapshots_history_id", table_name="wallet_score_snapshots")
    op.drop_column("wallet_score_snapshots", "history_id")
