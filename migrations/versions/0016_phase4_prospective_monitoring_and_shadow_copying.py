"""Phase 4: prospective monitoring + shadow copying schema

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-01

Implements MASTER_SPEC.md section 44 (PROSPECTIVE SHADOW MONITORING),
section 45 (SHADOW COPY EXECUTION), section 46 (COPYABILITY DELAY
PROBES), section 47 (EXECUTABLE RETURNS), section 48 (UNSELLABLE IS A
REAL OUTCOME), per orchestrator instruction ``argus-phase-4-001``
(``AUTHORIZED_ACTION:
IMPLEMENT_COMPLETE_PHASE_4_PROSPECTIVE_MONITORING_AND_SHADOW_COPYING``).

Five new tables, in dependency order: ``prospective_events``,
``shadow_intents``, ``shadow_positions``, ``shadow_quote_probes``,
``shadow_mark_outcomes``. No raw-observation table duplicates Phase 1's
``chain_events``/``swaps`` -- ``prospective_events.swap_id`` references
the real, already-ingested ``swaps`` row directly. See the corresponding
``argus.domain.*`` model module for the rationale behind each table's
shape -- this migration mirrors those models exactly (column-for-column,
constraint-for-constraint), per the established 0002/0008/0010 convention
of hand-written ``op.create_table`` rather than autogenerate.

No Phase 6 execution/signing table, column, or role grant is added --
Phase 4 remains fully disarmed (this instruction's explicit absolute
prohibitions). ``shadow_quote_probes``/``shadow_mark_outcomes`` use
partial unique indexes (``postgresql_where``) rather than a plain
``UniqueConstraint`` since each row's "one per (parent, label)" identity
depends on which of two mutually-exclusive parent columns is set.

Least-privilege grants (section 72) follow the 0008/0010 pattern exactly:
``argus_ingest`` gets ``SELECT, INSERT`` on every new table, plus
``UPDATE`` on ``shadow_intents``/``shadow_quote_probes``/
``shadow_mark_outcomes`` (status transitions and claim/response writes --
the only three tables any Phase 4 writer ever mutates in place;
``prospective_events``/``shadow_positions`` are pure append, exactly like
``wallet_positions``); ``argus_research`` gets broad ``SELECT``;
``argus_executor`` gets nothing (Phase 4 creates no live order, signing,
or broadcast path).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APPEND_ONLY_TABLES = ("prospective_events", "shadow_positions")
_MUTABLE_TABLES = ("shadow_intents", "shadow_quote_probes", "shadow_mark_outcomes")

_INTENT_STATUS_SQL = "'CREATED', 'FILLED', 'NO_FILL'"
_PROBE_KIND_SQL = "'ENTRY_DELAY', 'REVERSE_EXECUTABLE'"
_PROBE_OUTCOME_SQL = (
    "'PENDING', 'SUCCESS', 'NO_ROUTE', 'INSUFFICIENT_LIQUIDITY', "
    "'PRICE_IMPACT_EXCESSIVE', 'QUOTE_FAILED', 'TOKEN_RESTRICTED', "
    "'PROVIDER_CAPACITY_MISS'"
)
_MARK_HORIZON_SQL = "'5m', '30m', '1h', '6h', '24h', '3d', '7d'"
_MARK_OUTCOME_SQL = "'PENDING', 'RECORDED', 'PRICE_UNAVAILABLE'"


def upgrade() -> None:
    # --- prospective_events ---------------------------------------------
    op.create_table(
        "prospective_events",
        sa.Column("prospective_event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "wallet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.wallet_id"),
            nullable=False,
        ),
        sa.Column(
            "swap_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("swaps.swap_id"),
            nullable=False,
        ),
        sa.Column(
            "token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tokens.token_id"),
            nullable=True,
        ),
        sa.Column("leader_transaction_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmation_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("wallet_score_snapshot", sa.Numeric(6, 3), nullable=True),
        sa.Column("wallet_tier_snapshot", sa.String(length=16), nullable=False),
        sa.Column("token_state_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("position_size_context", postgresql.JSONB(), nullable=False),
        sa.Column("cluster_state_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("graph_state_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("swap_id", name="uq_prospective_events_swap_id"),
        sa.CheckConstraint(
            "length(wallet_tier_snapshot) > 0",
            name="ck_prospective_events_tier_snapshot_nonempty",
        ),
        sa.CheckConstraint(
            "length(algorithm_version) > 0", name="ck_prospective_events_algo_nonempty"
        ),
    )
    op.create_index("ix_prospective_events_wallet_id", "prospective_events", ["wallet_id"])
    op.create_index("ix_prospective_events_swap_id", "prospective_events", ["swap_id"])
    op.create_index("ix_prospective_events_token_id", "prospective_events", ["token_id"])
    op.create_index("ix_prospective_events_created_at", "prospective_events", ["created_at"])

    # --- shadow_intents ---------------------------------------------------
    op.create_table(
        "shadow_intents",
        sa.Column("shadow_intent_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "prospective_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prospective_events.prospective_event_id"),
            nullable=False,
        ),
        sa.Column(
            "wallet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.wallet_id"),
            nullable=False,
        ),
        sa.Column(
            "token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tokens.token_id"),
            nullable=True,
        ),
        sa.Column("input_mint", sa.String(length=64), nullable=False),
        sa.Column("output_mint", sa.String(length=64), nullable=False),
        sa.Column("notional_input_amount_raw", sa.BigInteger(), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="CREATED"),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("prospective_event_id", name="uq_shadow_intents_prospective_event_id"),
        sa.CheckConstraint(f"status IN ({_INTENT_STATUS_SQL})", name="ck_shadow_intents_status"),
        sa.CheckConstraint(
            "notional_input_amount_raw > 0", name="ck_shadow_intents_notional_positive"
        ),
        sa.CheckConstraint(
            "length(config_hash) > 0", name="ck_shadow_intents_config_hash_nonempty"
        ),
    )
    op.create_index("ix_shadow_intents_wallet_id", "shadow_intents", ["wallet_id"])
    op.create_index("ix_shadow_intents_created_at", "shadow_intents", ["created_at"])

    # --- shadow_positions ---------------------------------------------------
    op.create_table(
        "shadow_positions",
        sa.Column("shadow_position_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "shadow_intent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_intents.shadow_intent_id"),
            nullable=False,
        ),
        sa.Column(
            "wallet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.wallet_id"),
            nullable=False,
        ),
        sa.Column(
            "token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tokens.token_id"),
            nullable=True,
        ),
        sa.Column("input_mint", sa.String(length=64), nullable=False),
        sa.Column("output_mint", sa.String(length=64), nullable=False),
        sa.Column("entry_input_amount_raw", sa.BigInteger(), nullable=False),
        sa.Column("entry_output_amount_raw", sa.BigInteger(), nullable=False),
        sa.Column("entry_price_impact_pct", sa.Numeric(10, 6), nullable=True),
        sa.Column("entry_route_present", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("entry_fee_estimate_raw", sa.BigInteger(), nullable=True),
        sa.Column("entry_price_usd", sa.Numeric(38, 18), nullable=True),
        sa.Column("entry_probe_target_label", sa.String(length=16), nullable=False),
        sa.Column("entry_requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_responded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("shadow_intent_id", name="uq_shadow_positions_shadow_intent_id"),
        sa.CheckConstraint(
            "entry_input_amount_raw > 0", name="ck_shadow_positions_input_amount_positive"
        ),
        sa.CheckConstraint(
            "entry_output_amount_raw > 0", name="ck_shadow_positions_output_amount_positive"
        ),
        sa.CheckConstraint(
            "length(entry_probe_target_label) > 0",
            name="ck_shadow_positions_entry_probe_label_nonempty",
        ),
    )
    op.create_index("ix_shadow_positions_wallet_id", "shadow_positions", ["wallet_id"])
    op.create_index("ix_shadow_positions_created_at", "shadow_positions", ["created_at"])

    # --- shadow_quote_probes -------------------------------------------
    op.create_table(
        "shadow_quote_probes",
        sa.Column("probe_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("probe_kind", sa.String(length=24), nullable=False),
        sa.Column("target_label", sa.String(length=16), nullable=False),
        sa.Column("target_seconds_from_observation", sa.Integer(), nullable=True),
        sa.Column(
            "shadow_intent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_intents.shadow_intent_id"),
            nullable=True,
        ),
        sa.Column(
            "shadow_position_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_positions.shadow_position_id"),
            nullable=True,
        ),
        sa.Column("input_mint", sa.String(length=64), nullable=False),
        sa.Column("output_mint", sa.String(length=64), nullable=False),
        sa.Column("notional_input_amount_raw", sa.BigInteger(), nullable=False),
        sa.Column("target_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by", sa.String(length=64), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduling_delay_seconds", sa.Numeric(12, 3), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("expected_output_amount_raw", sa.BigInteger(), nullable=True),
        sa.Column("price_impact_pct", sa.Numeric(10, 6), nullable=True),
        sa.Column("route_present", sa.Boolean(), nullable=True),
        sa.Column("fee_estimate_raw", sa.BigInteger(), nullable=True),
        sa.Column("outcome", sa.String(length=24), nullable=False, server_default="PENDING"),
        sa.Column("raw_quote", postgresql.JSONB(), nullable=True),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"probe_kind IN ({_PROBE_KIND_SQL})", name="ck_shadow_probes_kind"),
        sa.CheckConstraint(f"outcome IN ({_PROBE_OUTCOME_SQL})", name="ck_shadow_probes_outcome"),
        sa.CheckConstraint(
            "length(target_label) > 0", name="ck_shadow_probes_target_label_nonempty"
        ),
        sa.CheckConstraint(
            "(probe_kind = 'ENTRY_DELAY' AND shadow_intent_id IS NOT NULL "
            "AND shadow_position_id IS NULL) OR "
            "(probe_kind = 'REVERSE_EXECUTABLE' AND shadow_position_id IS NOT NULL "
            "AND shadow_intent_id IS NULL)",
            name="ck_shadow_probes_kind_matches_parent",
        ),
        sa.CheckConstraint(
            "responded_at IS NULL OR requested_at IS NOT NULL",
            name="ck_shadow_probes_responded_requires_requested",
        ),
        sa.CheckConstraint(
            "notional_input_amount_raw > 0", name="ck_shadow_probes_notional_positive"
        ),
    )
    op.create_index("ix_shadow_probes_kind", "shadow_quote_probes", ["probe_kind"])
    op.create_index("ix_shadow_probes_target_due_at", "shadow_quote_probes", ["target_due_at"])
    op.create_index("ix_shadow_probes_created_at", "shadow_quote_probes", ["created_at"])
    op.create_index(
        "uq_shadow_probes_entry_intent_label",
        "shadow_quote_probes",
        ["shadow_intent_id", "target_label"],
        unique=True,
        postgresql_where=sa.text("probe_kind = 'ENTRY_DELAY'"),
    )
    op.create_index(
        "uq_shadow_probes_reverse_position_label",
        "shadow_quote_probes",
        ["shadow_position_id", "target_label"],
        unique=True,
        postgresql_where=sa.text("probe_kind = 'REVERSE_EXECUTABLE'"),
    )

    # --- shadow_mark_outcomes -----------------------------------------
    op.create_table(
        "shadow_mark_outcomes",
        sa.Column("shadow_mark_outcome_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "shadow_position_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shadow_positions.shadow_position_id"),
            nullable=False,
        ),
        sa.Column("horizon_label", sa.String(length=8), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by", sa.String(length=64), nullable=True),
        sa.Column("actual_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mark_price_usd", sa.Numeric(38, 18), nullable=True),
        sa.Column("mark_return_pct", sa.Numeric(20, 6), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("outcome", sa.String(length=24), nullable=False, server_default="PENDING"),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "shadow_position_id", "horizon_label", name="uq_shadow_mark_position_horizon"
        ),
        sa.CheckConstraint(
            f"horizon_label IN ({_MARK_HORIZON_SQL})", name="ck_shadow_mark_horizon"
        ),
        sa.CheckConstraint(f"outcome IN ({_MARK_OUTCOME_SQL})", name="ck_shadow_mark_outcome"),
    )
    op.create_index("ix_shadow_mark_position_id", "shadow_mark_outcomes", ["shadow_position_id"])
    op.create_index("ix_shadow_mark_due_at", "shadow_mark_outcomes", ["due_at"])
    op.create_index("ix_shadow_mark_created_at", "shadow_mark_outcomes", ["created_at"])

    # --- least-privilege grants (section 72) --------------------------------
    for table in (*_APPEND_ONLY_TABLES, *_MUTABLE_TABLES):
        op.execute(f"GRANT SELECT, INSERT ON {table} TO argus_ingest;")
        op.execute(f"GRANT SELECT ON {table} TO argus_research;")
    for table in _MUTABLE_TABLES:
        op.execute(f"GRANT UPDATE ON {table} TO argus_ingest;")


def downgrade() -> None:
    for table in _MUTABLE_TABLES:
        op.execute(f"REVOKE UPDATE ON {table} FROM argus_ingest;")
    for table in (*_APPEND_ONLY_TABLES, *_MUTABLE_TABLES):
        op.execute(f"REVOKE ALL ON {table} FROM argus_ingest;")
        op.execute(f"REVOKE ALL ON {table} FROM argus_research;")

    op.drop_index("ix_shadow_mark_created_at", table_name="shadow_mark_outcomes")
    op.drop_index("ix_shadow_mark_due_at", table_name="shadow_mark_outcomes")
    op.drop_index("ix_shadow_mark_position_id", table_name="shadow_mark_outcomes")
    op.drop_table("shadow_mark_outcomes")

    op.drop_index("uq_shadow_probes_reverse_position_label", table_name="shadow_quote_probes")
    op.drop_index("uq_shadow_probes_entry_intent_label", table_name="shadow_quote_probes")
    op.drop_index("ix_shadow_probes_created_at", table_name="shadow_quote_probes")
    op.drop_index("ix_shadow_probes_target_due_at", table_name="shadow_quote_probes")
    op.drop_index("ix_shadow_probes_kind", table_name="shadow_quote_probes")
    op.drop_table("shadow_quote_probes")

    op.drop_index("ix_shadow_positions_created_at", table_name="shadow_positions")
    op.drop_index("ix_shadow_positions_wallet_id", table_name="shadow_positions")
    op.drop_table("shadow_positions")

    op.drop_index("ix_shadow_intents_created_at", table_name="shadow_intents")
    op.drop_index("ix_shadow_intents_wallet_id", table_name="shadow_intents")
    op.drop_table("shadow_intents")

    op.drop_index("ix_prospective_events_created_at", table_name="prospective_events")
    op.drop_index("ix_prospective_events_token_id", table_name="prospective_events")
    op.drop_index("ix_prospective_events_swap_id", table_name="prospective_events")
    op.drop_index("ix_prospective_events_wallet_id", table_name="prospective_events")
    op.drop_table("prospective_events")
