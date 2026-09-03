"""Phase 6: hardened isolated executor schema (software-only)

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-03

Per orchestrator instruction ``argus-phase-6-001`` (frozen contract
``phase-6-v1``, P6-01 through P6-18): additive-only tables implementing
MASTER_SPEC.md sections 65-84's live-execution safety machinery --
executor singleton/fencing (``executor_leases``, section 75), the
persisted execution-intent state machine and its audit trail
(``execution_intents``/``execution_intent_transitions``, section 76),
transaction attestation records (``execution_attestations``, section 78),
actual-fill accounting (``execution_fills``, section 79), one-open-
position-per-mint live position tracking (``live_positions``, section
65), independent risk-exit audit (``risk_exit_events``, section 67), and
token-safety-gate evidence storage (``token_safety_assessments``,
section 68). No existing table, column, or grant is altered; migration
``0023`` (and everything before it) is unmodified.

Least-privilege grants (MASTER_SPEC.md section 72, P6-03): the
``argus_executor`` role (already created by migration ``0001``, unused
until now) gets SELECT/INSERT/UPDATE on the new execution tables only --
it explicitly does NOT gain any privilege on ``wallet_score_snapshots``,
``wallet_copyability_snapshots``, or any other historical research
table. ``argus_research``/``argus_ingest`` get SELECT-only on the new
tables (for reporting/reconciliation) and explicitly no INSERT/UPDATE/
DELETE -- research/ingestion must never be able to rewrite confirmed
execution history.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_TABLES = (
    "executor_leases",
    "execution_intents",
    "execution_intent_transitions",
    "execution_attestations",
    "execution_fills",
    "live_positions",
    "risk_exit_events",
    "token_safety_assessments",
)

_EXECUTION_STATES_SQL = (
    "'CREATED', 'VALIDATING', 'REJECTED', 'ORDER_REQUESTED', 'ORDER_READY', "
    "'ATTESTING', 'SIGNED', 'SUBMITTED', 'CONFIRMED', 'FAILED', 'UNKNOWN'"
)


def upgrade() -> None:
    # ---- section 75: executor singleton lease/fencing-token table ----
    op.create_table(
        "executor_leases",
        sa.Column("lease_id", sa.String(32), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("lease_id = 'primary'", name="ck_executor_leases_lease_id_singleton"),
        sa.CheckConstraint("fencing_token > 0", name="ck_executor_leases_fencing_token_positive"),
    )
    op.execute("CREATE SEQUENCE executor_lease_fencing_seq START WITH 1 INCREMENT BY 1;")

    # ---- section 76/77: execution-intent state machine ----
    op.create_table(
        "execution_intents",
        sa.Column("intent_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "prospective_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prospective_events.prospective_event_id"),
            nullable=True,
        ),
        sa.Column("strategy_version", sa.String(32), nullable=False),
        sa.Column(
            "token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tokens.token_id"),
            nullable=False,
        ),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("quote_mint", sa.String(64), nullable=False),
        sa.Column("notional_input_raw", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("idempotency_fingerprint", sa.String(64), nullable=False),
        sa.Column("build_hash", sa.String(64), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("master_spec_hash", sa.String(64), nullable=False),
        sa.Column("git_commit", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "idempotency_fingerprint", name="uq_execution_intents_idempotency_fingerprint"
        ),
        sa.CheckConstraint("side IN ('BUY', 'SELL')", name="ck_execution_intents_side"),
        sa.CheckConstraint(
            f"state IN ({_EXECUTION_STATES_SQL})", name="ck_execution_intents_state"
        ),
        sa.CheckConstraint("notional_input_raw > 0", name="ck_execution_intents_notional_positive"),
        sa.CheckConstraint(
            "length(idempotency_fingerprint) > 0",
            name="ck_execution_intents_fingerprint_nonempty",
        ),
        sa.CheckConstraint(
            "length(build_hash) > 0", name="ck_execution_intents_build_hash_nonempty"
        ),
        sa.CheckConstraint(
            "length(config_hash) > 0", name="ck_execution_intents_config_hash_nonempty"
        ),
        sa.CheckConstraint(
            "length(master_spec_hash) > 0",
            name="ck_execution_intents_master_spec_hash_nonempty",
        ),
        sa.CheckConstraint(
            "length(git_commit) > 0", name="ck_execution_intents_git_commit_nonempty"
        ),
    )
    op.create_index("ix_execution_intents_token_id", "execution_intents", ["token_id"])
    op.create_index("ix_execution_intents_state", "execution_intents", ["state"])
    op.create_index("ix_execution_intents_created_at", "execution_intents", ["created_at"])

    op.create_table(
        "execution_intent_transitions",
        sa.Column("transition_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "intent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("execution_intents.intent_id"),
            nullable=False,
        ),
        sa.Column("from_state", sa.String(24), nullable=True),
        sa.Column("to_state", sa.String(24), nullable=False),
        sa.Column("reason", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"to_state IN ({_EXECUTION_STATES_SQL})",
            name="ck_execution_intent_transitions_to_state",
        ),
        sa.CheckConstraint(
            "length(reason) > 0", name="ck_execution_intent_transitions_reason_nonempty"
        ),
    )
    op.create_index(
        "ix_execution_intent_transitions_intent_id",
        "execution_intent_transitions",
        ["intent_id"],
    )

    # ---- section 78: transaction attestation ----
    op.create_table(
        "execution_attestations",
        sa.Column("attestation_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "intent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("execution_intents.intent_id"),
            nullable=False,
        ),
        sa.Column("dimension", sa.String(64), nullable=False),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("detail", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("result IN ('PASS', 'FAIL')", name="ck_execution_attestations_result"),
        sa.CheckConstraint(
            "length(dimension) > 0", name="ck_execution_attestations_dimension_nonempty"
        ),
    )
    op.create_index("ix_execution_attestations_intent_id", "execution_attestations", ["intent_id"])

    # ---- section 79: actual fill accounting ----
    op.create_table(
        "execution_fills",
        sa.Column("fill_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "intent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("execution_intents.intent_id"),
            nullable=False,
        ),
        sa.Column("quoted_input_raw", sa.BigInteger(), nullable=True),
        sa.Column("quoted_output_raw", sa.BigInteger(), nullable=True),
        sa.Column("simulated_input_raw", sa.BigInteger(), nullable=True),
        sa.Column("simulated_output_raw", sa.BigInteger(), nullable=True),
        sa.Column("actual_input_raw", sa.BigInteger(), nullable=True),
        sa.Column("actual_output_raw", sa.BigInteger(), nullable=True),
        sa.Column("network_fee_raw", sa.BigInteger(), nullable=True),
        sa.Column("priority_fee_raw", sa.BigInteger(), nullable=True),
        sa.Column("tip_raw", sa.BigInteger(), nullable=True),
        sa.Column("rent_raw", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("intent_id", name="uq_execution_fills_intent_id"),
    )

    # ---- section 65: one-open-live-position-per-mint ----
    op.create_table(
        "live_positions",
        sa.Column("position_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tokens.token_id"),
            nullable=False,
        ),
        sa.Column(
            "opening_intent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("execution_intents.intent_id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("opening_intent_id", name="uq_live_positions_opening_intent_id"),
        sa.CheckConstraint("status IN ('OPEN', 'CLOSED')", name="ck_live_positions_status"),
        sa.CheckConstraint(
            "(status = 'OPEN' AND closed_at IS NULL) OR "
            "(status = 'CLOSED' AND closed_at IS NOT NULL)",
            name="ck_live_positions_closed_at_matches_status",
        ),
    )
    # The actual DB-level enforcement mechanism for MASTER_SPEC.md section
    # 65 / P6-11 (ALLOW_AUTOMATIC_SCALE_IN=false): at most one OPEN live
    # position per token, enforced by the database itself, not merely by
    # application logic that a bug could bypass.
    op.create_index(
        "uq_live_positions_one_open_per_token",
        "live_positions",
        ["token_id"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
    )

    # ---- section 67: independent risk exits ----
    op.create_table(
        "risk_exit_events",
        sa.Column("risk_exit_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "position_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("live_positions.position_id"),
            nullable=False,
        ),
        sa.Column("trigger_type", sa.String(32), nullable=False),
        sa.Column("detail", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "trigger_type IN ('MAX_POSITION_LOSS', 'LIQUIDITY_COLLAPSE', "
            "'TOKEN_RISK_STATE_CHANGE', 'MAX_DAILY_LOSS', 'MAX_AGGREGATE_EXPOSURE', "
            "'OPERATOR_EMERGENCY_EXIT')",
            name="ck_risk_exit_events_trigger_type",
        ),
    )
    op.create_index("ix_risk_exit_events_position_id", "risk_exit_events", ["position_id"])

    # ---- section 68: token safety gate evidence ----
    op.create_table(
        "token_safety_assessments",
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tokens.token_id"),
            nullable=False,
        ),
        sa.Column(
            "token_risk_flags",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("token_risk_version", sa.String(32), nullable=False),
        sa.Column("overall_status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "overall_status IN ('SAFE', 'UNSAFE', 'UNKNOWN')",
            name="ck_token_safety_assessments_overall_status",
        ),
        sa.CheckConstraint(
            "length(token_risk_version) > 0",
            name="ck_token_safety_assessments_version_nonempty",
        ),
    )
    op.create_index(
        "ix_token_safety_assessments_token_id", "token_safety_assessments", ["token_id"]
    )
    op.create_index(
        "ix_token_safety_assessments_created_at", "token_safety_assessments", ["created_at"]
    )

    # ---- section 72 / P6-03: least-privilege grants ----
    for table in _NEW_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO argus_executor;")
        op.execute(f"GRANT SELECT ON {table} TO argus_research;")
        op.execute(f"GRANT SELECT ON {table} TO argus_ingest;")
    op.execute("GRANT USAGE ON SEQUENCE executor_lease_fencing_seq TO argus_executor;")


def downgrade() -> None:
    op.execute("REVOKE USAGE ON SEQUENCE executor_lease_fencing_seq FROM argus_executor;")
    for table in _NEW_TABLES:
        op.execute(f"REVOKE ALL ON {table} FROM argus_executor;")
        op.execute(f"REVOKE ALL ON {table} FROM argus_research;")
        op.execute(f"REVOKE ALL ON {table} FROM argus_ingest;")

    op.drop_index("ix_token_safety_assessments_created_at", table_name="token_safety_assessments")
    op.drop_index("ix_token_safety_assessments_token_id", table_name="token_safety_assessments")
    op.drop_table("token_safety_assessments")

    op.drop_index("ix_risk_exit_events_position_id", table_name="risk_exit_events")
    op.drop_table("risk_exit_events")

    op.drop_index("uq_live_positions_one_open_per_token", table_name="live_positions")
    op.drop_table("live_positions")

    op.drop_table("execution_fills")

    op.drop_index("ix_execution_attestations_intent_id", table_name="execution_attestations")
    op.drop_table("execution_attestations")

    op.drop_index(
        "ix_execution_intent_transitions_intent_id", table_name="execution_intent_transitions"
    )
    op.drop_table("execution_intent_transitions")

    op.drop_index("ix_execution_intents_created_at", table_name="execution_intents")
    op.drop_index("ix_execution_intents_state", table_name="execution_intents")
    op.drop_index("ix_execution_intents_token_id", table_name="execution_intents")
    op.drop_table("execution_intents")

    op.execute("DROP SEQUENCE executor_lease_fencing_seq;")
    op.drop_table("executor_leases")
