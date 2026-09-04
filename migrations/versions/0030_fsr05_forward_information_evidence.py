"""FSR-05: real forward-information-after-leader evidence columns

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-04

ARGUS-INSTRUCTION-ID: argus-final-spec-recovery-001

Additive-only: no existing table, column, or grant is altered; migration
`0029` (and everything before it) is unmodified.

FSR-05 replaces Phase 7's always-``NULL`` ``forward_information_after_leader_pct``
with a genuinely computed value (the follower's own known-by-cutoff Phase 5
executable-return evidence at the primary 5m horizon for the follower's real
entries that followed this leader). Two new columns record the evidence
population size honestly rather than leaving a bare mean with no visible
denominator: ``forward_information_sample_count`` (observations that
contributed a SUCCESS executable return to the mean) and
``forward_information_eligible_count`` (observations that had a matching
5m reverse-executable probe at all, whether SUCCESS or not). When no mean
could be computed, ``forward_information_missing_reason`` records why,
instead of leaving a silent unexplained ``NULL``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "directional_edges",
        sa.Column("forward_information_sample_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "directional_edges",
        sa.Column("forward_information_eligible_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "directional_edges",
        sa.Column("forward_information_missing_reason", sa.String(64), nullable=True),
    )
    op.create_check_constraint(
        "ck_directional_edges_forward_info_sample_nonneg",
        "directional_edges",
        "forward_information_sample_count IS NULL OR forward_information_sample_count >= 0",
    )
    op.create_check_constraint(
        "ck_directional_edges_forward_info_eligible_nonneg",
        "directional_edges",
        "forward_information_eligible_count IS NULL OR forward_information_eligible_count >= 0",
    )
    op.create_check_constraint(
        "ck_directional_edges_forward_info_sample_le_eligible",
        "directional_edges",
        "forward_information_sample_count IS NULL "
        "OR forward_information_eligible_count IS NULL "
        "OR forward_information_sample_count <= forward_information_eligible_count",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_directional_edges_forward_info_sample_le_eligible",
        "directional_edges",
        type_="check",
    )
    op.drop_constraint(
        "ck_directional_edges_forward_info_eligible_nonneg", "directional_edges", type_="check"
    )
    op.drop_constraint(
        "ck_directional_edges_forward_info_sample_nonneg", "directional_edges", type_="check"
    )
    op.drop_column("directional_edges", "forward_information_missing_reason")
    op.drop_column("directional_edges", "forward_information_eligible_count")
    op.drop_column("directional_edges", "forward_information_sample_count")
