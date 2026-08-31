"""phase 1 remediation round 2: commitment observation sequence + CHECK
constraints, commitment_observation_rejections audit table,
parse_attempts durable ledger, immutability grants

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-31

Phase 1 remediation round 2 (argus-phase-1-remediation-002):

Finding #5 -- ``commitment_observations`` ordered only by ``created_at``,
which Postgres gives no guaranteed stable order to among rows sharing a
timestamp, so ``derive_current_state``'s tie-break (Python list position)
varied between independent queries. Adds ``sequence``, a database-generated
``IDENTITY`` column giving a durable, globally monotonic total order.
Also adds a ``CHECK`` constraint on ``commitment_level`` and a new
append-only ``commitment_observation_rejections`` table -- the durable
audit trail for a regression/conflict the tracker refused to append.

Finding #9 -- adds ``parse_attempts``, a durable, versioned ledger of
every attempt to parse a canonical event (success, ambiguous ``UNKNOWN``,
or failure), so a parser failure is no longer just an in-memory counter
lost on restart.

Finding #6 -- ``argus_ingest`` previously held ``UPDATE`` on
``chain_events`` and ``commitment_observations`` despite both being
stated append-only raw-evidence tables. Revokes ``UPDATE``/``DELETE`` on
both (``DELETE`` was never granted, so only ``UPDATE`` needs revoking),
and grants the new tables ``SELECT, INSERT`` only -- application code has
no legitimate reason to ever update or delete a row in any of these four
tables, so the database itself now refuses it regardless of what
application code attempts.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- finding #5: durable monotonic total order + level CHECK -------
    op.add_column(
        "commitment_observations",
        sa.Column(
            "sequence",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_commitment_observations_sequence", "commitment_observations", ["sequence"]
    )
    op.create_index("ix_commitment_observations_sequence", "commitment_observations", ["sequence"])
    op.create_check_constraint(
        "ck_commitment_observations_level",
        "commitment_observations",
        "commitment_level IN ('PROCESSED', 'CONFIRMED', 'FINALIZED')",
    )

    # --- finding #5: rejection/audit table ------------------------------
    op.create_table(
        "commitment_observation_rejections",
        sa.Column("rejection_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chain_events.event_id"),
            nullable=False,
        ),
        sa.Column("attempted_commitment_level", sa.String(length=16), nullable=False),
        sa.Column("attempted_transaction_succeeded", sa.Boolean(), nullable=True),
        sa.Column("attempted_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempted_provider", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_commitment_observation_rejections_event_id",
        "commitment_observation_rejections",
        ["event_id"],
    )
    op.create_index(
        "ix_commitment_observation_rejections_created_at",
        "commitment_observation_rejections",
        ["created_at"],
    )

    # --- finding #9: durable parse-attempt ledger -----------------------
    op.create_table(
        "parse_attempts",
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chain_events.event_id"),
            nullable=False,
        ),
        sa.Column("parser_version", sa.String(length=32), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("error_class", sa.String(length=128), nullable=True),
        sa.Column("error_reason", sa.String(length=512), nullable=True),
        sa.Column("input_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("retry_disposition", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_parse_attempts_event_id", "parse_attempts", ["event_id"])
    op.create_index("ix_parse_attempts_parser_version", "parse_attempts", ["parser_version"])
    op.create_index("ix_parse_attempts_outcome", "parse_attempts", ["outcome"])
    op.create_index("ix_parse_attempts_created_at", "parse_attempts", ["created_at"])
    op.create_check_constraint(
        "ck_parse_attempts_outcome",
        "parse_attempts",
        "outcome IN ('SUCCESS', 'UNKNOWN', 'FAILURE')",
    )
    op.create_check_constraint(
        "ck_parse_attempts_retry_disposition",
        "parse_attempts",
        "retry_disposition IN ('NOT_APPLICABLE', 'RETRYABLE')",
    )

    # --- finding #6: immutability at the role layer ---------------------
    op.execute("REVOKE UPDATE ON chain_events FROM argus_ingest;")
    op.execute("REVOKE UPDATE ON commitment_observations FROM argus_ingest;")

    for table in ("commitment_observation_rejections", "parse_attempts"):
        op.execute(f"GRANT SELECT, INSERT ON {table} TO argus_ingest;")
        op.execute(f"GRANT SELECT ON {table} TO argus_research;")


def downgrade() -> None:
    for table in ("commitment_observation_rejections", "parse_attempts"):
        op.execute(f"REVOKE ALL ON {table} FROM argus_ingest;")
        op.execute(f"REVOKE ALL ON {table} FROM argus_research;")

    op.execute("GRANT UPDATE ON commitment_observations TO argus_ingest;")
    op.execute("GRANT UPDATE ON chain_events TO argus_ingest;")

    op.drop_constraint("ck_parse_attempts_retry_disposition", "parse_attempts", type_="check")
    op.drop_constraint("ck_parse_attempts_outcome", "parse_attempts", type_="check")
    op.drop_index("ix_parse_attempts_created_at", table_name="parse_attempts")
    op.drop_index("ix_parse_attempts_outcome", table_name="parse_attempts")
    op.drop_index("ix_parse_attempts_parser_version", table_name="parse_attempts")
    op.drop_index("ix_parse_attempts_event_id", table_name="parse_attempts")
    op.drop_table("parse_attempts")

    op.drop_index(
        "ix_commitment_observation_rejections_created_at",
        table_name="commitment_observation_rejections",
    )
    op.drop_index(
        "ix_commitment_observation_rejections_event_id",
        table_name="commitment_observation_rejections",
    )
    op.drop_table("commitment_observation_rejections")

    op.drop_constraint("ck_commitment_observations_level", "commitment_observations", type_="check")
    op.drop_index("ix_commitment_observations_sequence", table_name="commitment_observations")
    op.drop_constraint(
        "uq_commitment_observations_sequence", "commitment_observations", type_="unique"
    )
    op.drop_column("commitment_observations", "sequence")
