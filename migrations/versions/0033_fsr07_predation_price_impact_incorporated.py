"""FSR-07: wallet_predation_scores.price_impact_incorporated

Revision ID: 0033
Revises: 0032
Create Date: 2026-09-04

ARGUS-INSTRUCTION-ID: argus-final-spec-recovery-001

Additive-only: no existing table, column, or grant is altered; migration
`0032` (and everything before it) is unmodified.

FSR-07 replaces the always-``NULL`` ``price_impact_mean`` with real
followers'-own Phase 5 executable-entry price-impact evidence where
available, and incorporates it (plus repetition frequency, via the
already-existing ``exit_after_influx_count``) into ``predation_score``.
``price_impact_incorporated`` records honestly whether price-impact
evidence was actually available and used for a given row -- FSR-07's own
explicit rule that missing price impact must make the result explicitly
partial, never silently behave as complete. ``server_default='false'``
keeps this additive for any already-persisted row (which, under the
pre-recovery build, always had ``price_impact_mean IS NULL`` and so was
never price-impact-complete either).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "wallet_predation_scores",
        sa.Column(
            "price_impact_incorporated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column("wallet_predation_scores", "price_impact_incorporated", server_default=None)


def downgrade() -> None:
    op.drop_column("wallet_predation_scores", "price_impact_incorporated")
