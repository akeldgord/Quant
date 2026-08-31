"""phase 1 remediation: commitment_observations, drop dead commitment
columns from chain_events, swap re-parse dedup constraint

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-31

Phase 1 remediation round 1 (argus-phase-1-remediation-001), finding #3:
``chain_events.confirmed_at``/``finalized_at`` were never actually
populated by any working code path -- a truth-path promotion attempt for
an already-fast-path-recorded event always collided with the table's own
dedup unique constraint and was silently dropped. Replaced with an
append-only ``commitment_observations`` log (see
``argus.ingestion.commitment``); current commitment state is always a
derived query over that log, never a mutable column.

Finding #4 prep: ``swaps`` gets a uniqueness constraint on
``(event_id, parser_version)`` so re-running the *same* parser version
against the same event is idempotent (no duplicate row), while a *new*
parser version may still add an additional row without disturbing the
prior point-in-time result.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("chain_events", "confirmed_at")
    op.drop_column("chain_events", "finalized_at")

    op.create_table(
        "commitment_observations",
        sa.Column("observation_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chain_events.event_id"),
            nullable=False,
        ),
        sa.Column("commitment_level", sa.String(length=16), nullable=False),
        sa.Column("transaction_succeeded", sa.Boolean(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_commitment_observations_event_id", "commitment_observations", ["event_id"])
    op.create_index(
        "ix_commitment_observations_commitment_level",
        "commitment_observations",
        ["commitment_level"],
    )
    op.create_index(
        "ix_commitment_observations_created_at", "commitment_observations", ["created_at"]
    )

    op.create_unique_constraint(
        "uq_swaps_event_id_parser_version", "swaps", ["event_id", "parser_version"]
    )

    for table in ("commitment_observations",):
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO argus_ingest;")
        op.execute(f"GRANT SELECT ON {table} TO argus_research;")


def downgrade() -> None:
    op.execute("REVOKE ALL ON commitment_observations FROM argus_ingest;")
    op.execute("REVOKE ALL ON commitment_observations FROM argus_research;")

    op.drop_constraint("uq_swaps_event_id_parser_version", "swaps", type_="unique")

    op.drop_index("ix_commitment_observations_created_at", table_name="commitment_observations")
    op.drop_index(
        "ix_commitment_observations_commitment_level", table_name="commitment_observations"
    )
    op.drop_index("ix_commitment_observations_event_id", table_name="commitment_observations")
    op.drop_table("commitment_observations")

    op.add_column(
        "chain_events", sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "chain_events", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True)
    )
