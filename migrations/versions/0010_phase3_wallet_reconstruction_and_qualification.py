"""Phase 3: wallet reconstruction + unbiased qualification schema

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-01

Implements MASTER_SPEC.md section 34 (HISTORICAL WALLET COMPLETENESS),
section 35 (WALLET POSITION RECONSTRUCTION), section 36 (WALLET
LIFECYCLE), section 37 (WALLET FEATURE FINGERPRINT), section 38 (WALLET
QUALIFICATION SCORE v1), section 39 (QUALIFICATION SAMPLE REQUIREMENTS
v1), section 40 (LOTTERY-DOMINANCE PROTECTION), section 41 (RECENCY AND
ALPHA DECAY), section 42 (WALLET CLUSTERING), section 43 (CONSERVATIVE
INDEPENDENCE), per orchestrator instruction ``argus-phase-3-001``
(``AUTHORIZED_ACTION:
EXECUTE_PHASE_3_WALLET_RECONSTRUCTION_AND_UNBIASED_QUALIFICATION_ONLY``).

Six new tables, in dependency order: ``wallet_history_quality``,
``wallet_positions``, ``wallet_metrics_snapshots``,
``wallet_score_snapshots``, ``wallet_tier_history``,
``wallet_cluster_links``; plus one column added to the existing Phase 2
``wallets`` table (``current_tier``, a denormalized cache of the latest
``wallet_tier_history`` row, mirroring ``tokens.current_lifecycle_stage``'s
identical precedent). No raw-position-event table is added: ``swaps``
(Phase 1) is already the immutable, append-only, re-derivable raw
evidence ledger MASTER_SPEC section 35's "store raw position events"
requirement calls for -- Phase 3 derives ``wallet_positions`` from it
directly rather than duplicating it. See the corresponding
``argus.domain.*`` model module for the rationale behind each table's
shape -- this migration mirrors those models exactly (column-for-column,
constraint-for-constraint), per the established 0002/0006/0007/0008/0009
convention of hand-written ``op.create_table`` rather than autogenerate.

``wallet_score_snapshots`` carries the full CORE-004 identity block
(``build_hash``/``config_hash``/``master_spec_hash``/``git_commit``),
matching ``token_mint_validations``/``archaeology_runs``'s precedent from
migration 0008 exactly -- it is the one audit-critical *decision* ledger
this phase adds. Every other new table uses only ``algorithm_version``
(± ``git_commit``), matching the lighter ``swaps``/``token_market_
snapshots`` precedent.

Least-privilege grants (section 72) follow the 0008 pattern exactly:
``argus_ingest`` gets ``SELECT, INSERT`` on every new append-only table,
plus an additional ``UPDATE`` grant on the pre-existing ``wallets`` table
(needed only for the new ``current_tier`` cache column -- ``wallets``
itself is not otherwise mutated); ``argus_research`` gets broad
``SELECT``; ``argus_executor`` gets nothing (Phase 3 creates no trade
intent, order, transaction, or live execution path, per this
instruction's explicit prohibition list).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COMPLETENESS_SQL = "'HIGH', 'MEDIUM', 'LOW', 'UNKNOWN'"
_POSITION_CONFIDENCE_SQL = "'HIGH', 'MEDIUM', 'LOW', 'UNRESOLVED'"
_POSITION_STATUS_SQL = "'OPEN', 'CLOSED'"
_WINDOW_SQL = "'LIFETIME', '180D', '90D', '30D', '7D'"
_TIER_SQL = "'DISCOVERED', 'WATCH', 'PROBATION', 'B', 'A', 'S', 'QUARANTINE', 'DORMANT', 'RETIRED'"
_CLUSTER_EVIDENCE_SQL = (
    "'COMMON_FUNDING_SOURCE', 'DIRECT_TRANSFER', 'SAME_INITIAL_FUNDER', "
    "'SYNCHRONIZED_ACTIVITY', 'REPEATED_SIZING', 'REPEATED_TOKEN_SEQUENCE', "
    "'SHARED_DEPLOYER_RELATION', 'SHARED_CASHOUT_DESTINATION', 'TEMPORAL_COOCCURRENCE'"
)

_APPEND_ONLY_TABLES = (
    "wallet_history_quality",
    "wallet_positions",
    "wallet_metrics_snapshots",
    "wallet_score_snapshots",
    "wallet_tier_history",
    "wallet_cluster_links",
)


def upgrade() -> None:
    # --- wallet_history_quality ---------------------------------------
    op.create_table(
        "wallet_history_quality",
        sa.Column("history_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "wallet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.wallet_id"),
            nullable=False,
        ),
        sa.Column("history_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("history_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("history_provider_set", sa.String(length=256), nullable=False),
        sa.Column("history_completeness", sa.String(length=16), nullable=False),
        sa.Column("history_completeness_reason", sa.Text(), nullable=False),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"history_completeness IN ({_COMPLETENESS_SQL})",
            name="ck_wallet_history_quality_completeness",
        ),
        sa.CheckConstraint(
            "length(history_completeness_reason) > 0",
            name="ck_wallet_history_quality_reason_nonempty",
        ),
        sa.CheckConstraint(
            "length(history_provider_set) > 0",
            name="ck_wallet_history_quality_provider_set_nonempty",
        ),
        sa.CheckConstraint(
            "history_start IS NULL OR history_end IS NULL OR history_start <= history_end",
            name="ck_wallet_history_quality_start_before_end",
        ),
    )
    op.create_index("ix_wallet_history_quality_wallet_id", "wallet_history_quality", ["wallet_id"])
    op.create_index(
        "ix_wallet_history_quality_completeness",
        "wallet_history_quality",
        ["history_completeness"],
    )
    op.create_index(
        "ix_wallet_history_quality_created_at", "wallet_history_quality", ["created_at"]
    )

    # --- wallet_positions ----------------------------------------------
    op.create_table(
        "wallet_positions",
        sa.Column("position_id", postgresql.UUID(as_uuid=True), primary_key=True),
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
            nullable=False,
        ),
        sa.Column(
            "history_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallet_history_quality.history_id"),
            nullable=False,
        ),
        sa.Column("quote_asset_mint", sa.String(length=64), nullable=False),
        sa.Column("first_entry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_entry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("final_exit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entry_quantity", sa.Numeric(38, 18), nullable=True),
        sa.Column("entry_value_quote", sa.Numeric(38, 18), nullable=True),
        sa.Column("average_cost_quote", sa.Numeric(38, 18), nullable=True),
        sa.Column("partial_exit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("realized_pnl_quote", sa.Numeric(38, 18), nullable=True),
        sa.Column("unrealized_pnl_quote", sa.Numeric(38, 18), nullable=True),
        sa.Column("holding_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("mfe_quote", sa.Numeric(38, 18), nullable=True),
        sa.Column("mae_quote", sa.Numeric(38, 18), nullable=True),
        sa.Column("peak_value_quote", sa.Numeric(38, 18), nullable=True),
        sa.Column("peak_profit_capture", sa.Numeric(6, 5), nullable=True),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column("git_commit", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"confidence IN ({_POSITION_CONFIDENCE_SQL})", name="ck_wallet_positions_confidence"
        ),
        sa.CheckConstraint(
            f"status IN ({_POSITION_STATUS_SQL})", name="ck_wallet_positions_status"
        ),
        sa.CheckConstraint(
            "length(quote_asset_mint) > 0", name="ck_wallet_positions_quote_asset_nonempty"
        ),
        sa.CheckConstraint(
            "partial_exit_count >= 0", name="ck_wallet_positions_partial_exit_count"
        ),
    )
    op.create_index("ix_wallet_positions_wallet_id", "wallet_positions", ["wallet_id"])
    op.create_index("ix_wallet_positions_token_id", "wallet_positions", ["token_id"])
    op.create_index("ix_wallet_positions_confidence", "wallet_positions", ["confidence"])
    op.create_index("ix_wallet_positions_status", "wallet_positions", ["status"])
    op.create_index("ix_wallet_positions_created_at", "wallet_positions", ["created_at"])

    # --- wallet_metrics_snapshots ----------------------------------------
    op.create_table(
        "wallet_metrics_snapshots",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "wallet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.wallet_id"),
            nullable=False,
        ),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metrics_window", sa.String(length=16), nullable=False),
        sa.Column("selection_skill", sa.Numeric(6, 3), nullable=True),
        sa.Column("early_discovery_skill", sa.Numeric(6, 3), nullable=True),
        sa.Column("entry_timing_skill", sa.Numeric(6, 3), nullable=True),
        sa.Column("exit_skill", sa.Numeric(6, 3), nullable=True),
        sa.Column("risk_control_skill", sa.Numeric(6, 3), nullable=True),
        sa.Column("consistency", sa.Numeric(6, 3), nullable=True),
        sa.Column("copyability", sa.Numeric(6, 3), nullable=True),
        sa.Column("forward_information_value", sa.Numeric(6, 3), nullable=True),
        sa.Column("recency", sa.Numeric(6, 3), nullable=True),
        sa.Column("data_confidence", sa.Numeric(6, 3), nullable=True),
        sa.Column("insider_risk", sa.Numeric(6, 3), nullable=True),
        sa.Column("cluster_risk", sa.Numeric(6, 3), nullable=True),
        sa.Column("independence_probability", sa.Numeric(6, 5), nullable=True),
        sa.Column("predation_risk", sa.Numeric(6, 3), nullable=True),
        sa.Column("automation_probability", sa.Numeric(6, 5), nullable=True),
        sa.Column("median_return", sa.Numeric(20, 6), nullable=True),
        sa.Column("trimmed_mean_return", sa.Numeric(20, 6), nullable=True),
        sa.Column("winsorized_return", sa.Numeric(20, 6), nullable=True),
        sa.Column("profit_factor", sa.Numeric(20, 6), nullable=True),
        sa.Column("hit_rate", sa.Numeric(6, 5), nullable=True),
        sa.Column("largest_trade_contribution_pct", sa.Numeric(6, 5), nullable=True),
        sa.Column("top_three_trade_contribution_pct", sa.Numeric(6, 5), nullable=True),
        sa.Column("max_drawdown", sa.Numeric(6, 5), nullable=True),
        sa.Column("distinct_profitable_token_count", sa.Integer(), nullable=True),
        sa.Column("lottery_dominated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "usable_closed_positions_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "distinct_tokens_with_usable_outcomes_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column("git_commit", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"metrics_window IN ({_WINDOW_SQL})", name="ck_wallet_metrics_window"),
        sa.CheckConstraint(
            "usable_closed_positions_count >= 0", name="ck_wallet_metrics_closed_positions_count"
        ),
        sa.CheckConstraint(
            "distinct_tokens_with_usable_outcomes_count >= 0",
            name="ck_wallet_metrics_distinct_tokens_count",
        ),
    )
    op.create_index(
        "ix_wallet_metrics_snapshots_wallet_id", "wallet_metrics_snapshots", ["wallet_id"]
    )
    op.create_index("ix_wallet_metrics_snapshots_as_of", "wallet_metrics_snapshots", ["as_of"])
    op.create_index(
        "ix_wallet_metrics_snapshots_window", "wallet_metrics_snapshots", ["metrics_window"]
    )

    # --- wallet_score_snapshots ------------------------------------------
    op.create_table(
        "wallet_score_snapshots",
        sa.Column("score_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "wallet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.wallet_id"),
            nullable=False,
        ),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("score_version", sa.String(length=32), nullable=False),
        sa.Column("descriptive_score", sa.Numeric(6, 3), nullable=True),
        sa.Column("qualification_score", sa.Numeric(6, 3), nullable=True),
        sa.Column("component_values", postgresql.JSONB(), nullable=False),
        sa.Column("penalties", postgresql.JSONB(), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=True),
        sa.Column(
            "excluded_discovery_token_ids", postgresql.JSONB(), nullable=False, server_default="[]"
        ),
        sa.Column("eligible_for_qualification", sa.Boolean(), nullable=False),
        sa.Column("sample_gate_reason", sa.Text(), nullable=False),
        sa.Column("build_hash", sa.String(length=64), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("master_spec_hash", sa.String(length=64), nullable=False),
        sa.Column("git_commit", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(score_version) > 0", name="ck_wallet_score_version_nonempty"),
        sa.CheckConstraint(
            "length(sample_gate_reason) > 0", name="ck_wallet_score_sample_gate_reason_nonempty"
        ),
        sa.CheckConstraint(
            "length(build_hash) > 0", name="ck_wallet_score_snapshots_build_hash_nonempty"
        ),
        sa.CheckConstraint(
            "length(config_hash) > 0", name="ck_wallet_score_snapshots_config_hash_nonempty"
        ),
        sa.CheckConstraint(
            "length(master_spec_hash) > 0",
            name="ck_wallet_score_snapshots_master_spec_hash_nonempty",
        ),
        sa.CheckConstraint(
            "length(git_commit) > 0", name="ck_wallet_score_snapshots_git_commit_nonempty"
        ),
    )
    op.create_index("ix_wallet_score_snapshots_wallet_id", "wallet_score_snapshots", ["wallet_id"])
    op.create_index("ix_wallet_score_snapshots_as_of", "wallet_score_snapshots", ["as_of"])
    op.create_index(
        "ix_wallet_score_snapshots_score_version", "wallet_score_snapshots", ["score_version"]
    )
    op.create_index(
        "ix_wallet_score_snapshots_created_at", "wallet_score_snapshots", ["created_at"]
    )

    # --- wallet_tier_history -----------------------------------------
    op.create_table(
        "wallet_tier_history",
        sa.Column("transition_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "wallet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.wallet_id"),
            nullable=False,
        ),
        sa.Column(
            "source_score_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallet_score_snapshots.score_id"),
            nullable=True,
        ),
        sa.Column("from_tier", sa.String(length=16), nullable=True),
        sa.Column("to_tier", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"from_tier IS NULL OR from_tier IN ({_TIER_SQL})",
            name="ck_wallet_tier_history_from_tier",
        ),
        sa.CheckConstraint(f"to_tier IN ({_TIER_SQL})", name="ck_wallet_tier_history_to_tier"),
        sa.CheckConstraint("length(reason) > 0", name="ck_wallet_tier_history_reason_nonempty"),
    )
    op.create_index("ix_wallet_tier_history_wallet_id", "wallet_tier_history", ["wallet_id"])
    op.create_index("ix_wallet_tier_history_to_tier", "wallet_tier_history", ["to_tier"])
    op.create_index(
        "ix_wallet_tier_history_transitioned_at", "wallet_tier_history", ["transitioned_at"]
    )
    op.create_index("ix_wallet_tier_history_created_at", "wallet_tier_history", ["created_at"])

    # --- wallet_cluster_links --------------------------------------------
    op.create_table(
        "wallet_cluster_links",
        sa.Column("link_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "wallet_a_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.wallet_id"),
            nullable=False,
        ),
        sa.Column(
            "wallet_b_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.wallet_id"),
            nullable=False,
        ),
        sa.Column("evidence_type", sa.String(length=32), nullable=False),
        sa.Column("evidence_reference", sa.Text(), nullable=False),
        sa.Column("probability", sa.Numeric(6, 5), nullable=False),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"evidence_type IN ({_CLUSTER_EVIDENCE_SQL})",
            name="ck_wallet_cluster_links_evidence_type",
        ),
        sa.CheckConstraint(
            "probability >= 0 AND probability <= 1", name="ck_wallet_cluster_links_probability"
        ),
        sa.CheckConstraint(
            "length(evidence_reference) > 0", name="ck_wallet_cluster_links_evidence_ref_nonempty"
        ),
        sa.CheckConstraint("wallet_a_id <> wallet_b_id", name="ck_wallet_cluster_links_distinct"),
    )
    op.create_index("ix_wallet_cluster_links_wallet_a_id", "wallet_cluster_links", ["wallet_a_id"])
    op.create_index("ix_wallet_cluster_links_wallet_b_id", "wallet_cluster_links", ["wallet_b_id"])
    op.create_index(
        "ix_wallet_cluster_links_evidence_type", "wallet_cluster_links", ["evidence_type"]
    )
    op.create_index("ix_wallet_cluster_links_as_of", "wallet_cluster_links", ["as_of"])

    # --- wallets.current_tier (denormalized tier cache) -------------------
    op.add_column("wallets", sa.Column("current_tier", sa.String(length=16), nullable=True))

    # --- least-privilege grants (section 72) --------------------------------
    for table in _APPEND_ONLY_TABLES:
        op.execute(f"GRANT SELECT, INSERT ON {table} TO argus_ingest;")
        op.execute(f"GRANT SELECT ON {table} TO argus_research;")
    # wallets itself was granted only SELECT, INSERT by migration 0008;
    # current_tier is the first mutable field it has ever had.
    op.execute("GRANT UPDATE ON wallets TO argus_ingest;")


def downgrade() -> None:
    op.execute("REVOKE UPDATE ON wallets FROM argus_ingest;")
    op.drop_column("wallets", "current_tier")

    for table in _APPEND_ONLY_TABLES:
        op.execute(f"REVOKE ALL ON {table} FROM argus_ingest;")
        op.execute(f"REVOKE ALL ON {table} FROM argus_research;")

    op.drop_index("ix_wallet_cluster_links_as_of", table_name="wallet_cluster_links")
    op.drop_index("ix_wallet_cluster_links_evidence_type", table_name="wallet_cluster_links")
    op.drop_index("ix_wallet_cluster_links_wallet_b_id", table_name="wallet_cluster_links")
    op.drop_index("ix_wallet_cluster_links_wallet_a_id", table_name="wallet_cluster_links")
    op.drop_table("wallet_cluster_links")

    op.drop_index("ix_wallet_tier_history_created_at", table_name="wallet_tier_history")
    op.drop_index("ix_wallet_tier_history_transitioned_at", table_name="wallet_tier_history")
    op.drop_index("ix_wallet_tier_history_to_tier", table_name="wallet_tier_history")
    op.drop_index("ix_wallet_tier_history_wallet_id", table_name="wallet_tier_history")
    op.drop_table("wallet_tier_history")

    op.drop_index("ix_wallet_score_snapshots_created_at", table_name="wallet_score_snapshots")
    op.drop_index("ix_wallet_score_snapshots_score_version", table_name="wallet_score_snapshots")
    op.drop_index("ix_wallet_score_snapshots_as_of", table_name="wallet_score_snapshots")
    op.drop_index("ix_wallet_score_snapshots_wallet_id", table_name="wallet_score_snapshots")
    op.drop_table("wallet_score_snapshots")

    op.drop_index("ix_wallet_metrics_snapshots_window", table_name="wallet_metrics_snapshots")
    op.drop_index("ix_wallet_metrics_snapshots_as_of", table_name="wallet_metrics_snapshots")
    op.drop_index("ix_wallet_metrics_snapshots_wallet_id", table_name="wallet_metrics_snapshots")
    op.drop_table("wallet_metrics_snapshots")

    op.drop_index("ix_wallet_positions_created_at", table_name="wallet_positions")
    op.drop_index("ix_wallet_positions_status", table_name="wallet_positions")
    op.drop_index("ix_wallet_positions_confidence", table_name="wallet_positions")
    op.drop_index("ix_wallet_positions_token_id", table_name="wallet_positions")
    op.drop_index("ix_wallet_positions_wallet_id", table_name="wallet_positions")
    op.drop_table("wallet_positions")

    op.drop_index("ix_wallet_history_quality_created_at", table_name="wallet_history_quality")
    op.drop_index("ix_wallet_history_quality_completeness", table_name="wallet_history_quality")
    op.drop_index("ix_wallet_history_quality_wallet_id", table_name="wallet_history_quality")
    op.drop_table("wallet_history_quality")
