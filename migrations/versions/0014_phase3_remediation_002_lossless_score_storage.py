"""Phase 3 remediation round 2 (P3-R6b): lossless score storage.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-01

``wallet_score_snapshots.descriptive_score``/``qualification_score`` were
``Numeric(6, 3)`` -- three fractional digits. A real, unrounded Decimal
score computation (weighted sums of divisions) genuinely produces more
than three fractional digits; the database silently truncated it on
write, so comparing the persisted (truncated) value against the fresh
in-memory (unrounded) score on an exact replay was spuriously unequal --
defeating the very idempotency guarantee this comparison exists to
provide. Widened to ``Numeric(20, 15)``, comfortably covering the
[0, 100]-clamped score range with deep fractional precision intact.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "wallet_score_snapshots",
        "descriptive_score",
        type_=sa.Numeric(20, 15),
        existing_type=sa.Numeric(6, 3),
    )
    op.alter_column(
        "wallet_score_snapshots",
        "qualification_score",
        type_=sa.Numeric(20, 15),
        existing_type=sa.Numeric(6, 3),
    )


def downgrade() -> None:
    op.alter_column(
        "wallet_score_snapshots",
        "qualification_score",
        type_=sa.Numeric(6, 3),
        existing_type=sa.Numeric(20, 15),
    )
    op.alter_column(
        "wallet_score_snapshots",
        "descriptive_score",
        type_=sa.Numeric(6, 3),
        existing_type=sa.Numeric(20, 15),
    )
