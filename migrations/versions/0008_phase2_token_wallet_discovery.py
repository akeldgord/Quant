"""Phase 2: token + wallet discovery schema

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-01

Implements MASTER_SPEC.md section 24 (TOKEN LIFECYCLE MODEL), section 25
(REFERENCE PRICE LEDGER), section 26 (HISTORICAL MARKET-STATE RULE),
section 27 (CORE DATA ENTITIES -- Token/Wallet domain, Phase 2 subset),
section 28 (WALLET DISCOVERY CHANNELS), section 29 (WALLET DISCOVERY
PROVENANCE), section 30 (CRITICAL ANTI-SURVIVORSHIP RULE), section 31
(NEGATIVE-CONTROL ARCHAEOLOGY, schema-only per this instruction's explicit
scope limit), section 32 (WINNER DEFINITIONS), and section 33
(EARLY-BUYER EXTRACTION), per orchestrator instruction ``argus-phase-2-001``
(``AUTHORIZED_ACTION: EXECUTE_PHASE_2_TOKEN_AND_WALLET_DISCOVERY_ONLY``).

Eleven new tables, in dependency order: ``tokens``,
``token_mint_validations``, ``reference_asset_prices``,
``token_market_snapshots``, ``token_winner_milestones``,
``archaeology_triggers``, ``archaeology_runs``, ``wallets``,
``wallet_discovery_events``, ``early_buyers``, ``token_negative_controls``.
See the corresponding ``argus.domain.*`` model module for the rationale
behind each table's shape -- this migration mirrors those models exactly
(column-for-column, constraint-for-constraint), per the established
0002/0006/0007 convention of hand-written ``op.create_table`` rather than
autogenerate.

Two decision-ledger tables (``token_mint_validations``, ``archaeology_runs``)
carry the full CORE-004 identity block (``build_hash``/``config_hash``/
``master_spec_hash``/``git_commit``), matching ``parse_attempts``'s
precedent from migration 0006 exactly. Every other new table uses only
``algorithm_version`` (± ``build_hash``), matching the lighter
``swaps``/``chain_events`` precedent -- this Phase 2 build follows the
same "full identity block reserved for audit-critical decision ledgers"
distinction Phase 1 already established, not a new convention.

Least-privilege grants (section 72) follow the 0002/0004 pattern exactly:
``argus_ingest`` gets ``SELECT, INSERT`` on every append-only ledger table
and additionally ``UPDATE`` only on the three tables with a genuine mutable
field (``tokens.mint_validated``/``current_lifecycle_stage``,
``archaeology_triggers.consumed_at``,
``archaeology_runs.status``/``completed_at``/``error_reason``);
``argus_research`` gets broad ``SELECT``; ``argus_executor`` gets nothing
(Phase 2 creates no trade intent, order, transaction, or live execution
path, per this instruction's explicit invariant 12).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LIFECYCLE_STAGES_SQL = (
    "'TOKEN_CREATION', 'BONDING_CURVE', 'LAUNCHPAD_TRADING', 'MIGRATION', "
    "'AMM_POOL', 'MULTIPLE_POOLS'"
)
_MARKET_STATE_CONFIDENCE_SQL = "'HIGH', 'MEDIUM', 'LOW', 'UNKNOWN'"
_DISCOVERY_CHANNELS_SQL = (
    "'HISTORICAL_WINNER_ARCHAEOLOGY', 'PROSPECTIVE_WINNER_ARCHAEOLOGY', "
    "'ALPHA_ANCESTRY_UPSTREAM', 'PEER_NETWORK'"
)

_APPEND_ONLY_TABLES = (
    "token_mint_validations",
    "reference_asset_prices",
    "token_market_snapshots",
    "token_winner_milestones",
    "wallets",
    "wallet_discovery_events",
    "early_buyers",
    "token_negative_controls",
)
_MUTABLE_TABLES = ("tokens", "archaeology_triggers", "archaeology_runs")
_ALL_TABLES = (*_APPEND_ONLY_TABLES, *_MUTABLE_TABLES)


def upgrade() -> None:
    # --- tokens ------------------------------------------------------
    op.create_table(
        "tokens",
        sa.Column("token_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("mint", sa.String(length=64), nullable=False),
        sa.Column("chain", sa.String(length=32), nullable=False, server_default="solana"),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mint_validated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("current_lifecycle_stage", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("mint", name="uq_tokens_mint"),
    )
    op.create_index("ix_tokens_mint", "tokens", ["mint"])
    op.create_index("ix_tokens_created_at", "tokens", ["created_at"])

    # --- token_mint_validations ----------------------------------------
    op.create_table(
        "token_mint_validations",
        sa.Column("validation_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tokens.token_id"),
            nullable=False,
        ),
        sa.Column("validation_status", sa.String(length=16), nullable=False),
        sa.Column("validation_source", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("chain_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("commitment", sa.String(length=16), nullable=True),
        sa.Column("evidence_reference", sa.String(length=256), nullable=False),
        sa.Column("reason", sa.String(length=512), nullable=True),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column("build_hash", sa.String(length=64), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("master_spec_hash", sa.String(length=64), nullable=False),
        sa.Column("git_commit", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "validation_status IN ('VALID', 'INVALID', 'UNAVAILABLE')",
            name="ck_token_mint_validations_status",
        ),
        sa.CheckConstraint(
            "length(evidence_reference) > 0",
            name="ck_token_mint_validations_evidence_reference_nonempty",
        ),
        sa.CheckConstraint(
            "length(build_hash) > 0", name="ck_token_mint_validations_build_hash_nonempty"
        ),
        sa.CheckConstraint(
            "length(config_hash) > 0", name="ck_token_mint_validations_config_hash_nonempty"
        ),
        sa.CheckConstraint(
            "length(master_spec_hash) > 0",
            name="ck_token_mint_validations_master_spec_hash_nonempty",
        ),
        sa.CheckConstraint(
            "length(git_commit) > 0", name="ck_token_mint_validations_git_commit_nonempty"
        ),
    )
    op.create_index("ix_token_mint_validations_token_id", "token_mint_validations", ["token_id"])
    op.create_index(
        "ix_token_mint_validations_validation_status",
        "token_mint_validations",
        ["validation_status"],
    )
    op.create_index(
        "ix_token_mint_validations_created_at", "token_mint_validations", ["created_at"]
    )

    # --- reference_asset_prices -----------------------------------------
    op.create_table(
        "reference_asset_prices",
        sa.Column("price_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("asset", sa.String(length=16), nullable=False),
        sa.Column("price_usd", sa.Numeric(38, 18), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "asset",
            "source",
            "observed_at",
            name="uq_reference_asset_prices_asset_source_observed_at",
        ),
        sa.CheckConstraint("price_usd > 0", name="ck_reference_asset_prices_price_positive"),
    )
    op.create_index("ix_reference_asset_prices_asset", "reference_asset_prices", ["asset"])
    op.create_index(
        "ix_reference_asset_prices_observed_at", "reference_asset_prices", ["observed_at"]
    )
    op.create_index(
        "ix_reference_asset_prices_created_at", "reference_asset_prices", ["created_at"]
    )

    # --- token_market_snapshots ------------------------------------------
    op.create_table(
        "token_market_snapshots",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tokens.token_id"),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("chain_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lifecycle_stage", sa.String(length=32), nullable=False),
        sa.Column("venue", sa.String(length=64), nullable=True),
        sa.Column("venue_program", sa.String(length=64), nullable=True),
        sa.Column("pool_or_curve_address", sa.String(length=64), nullable=True),
        sa.Column("price_usd", sa.Numeric(38, 18), nullable=True),
        sa.Column("supply_raw", sa.BigInteger(), nullable=True),
        sa.Column("liquidity_usd", sa.Numeric(38, 18), nullable=True),
        sa.Column("fdv_usd", sa.Numeric(38, 18), nullable=True),
        sa.Column("market_cap_usd", sa.Numeric(38, 18), nullable=True),
        sa.Column("market_state_confidence", sa.String(length=16), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("evidence_reference", sa.String(length=256), nullable=True),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column("build_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "token_id",
            "source",
            "observed_at",
            name="uq_token_market_snapshots_token_source_observed_at",
        ),
        sa.CheckConstraint(
            f"lifecycle_stage IN ({_LIFECYCLE_STAGES_SQL})",
            name="ck_token_market_snapshots_lifecycle_stage",
        ),
        sa.CheckConstraint(
            f"market_state_confidence IS NULL OR "
            f"market_state_confidence IN ({_MARKET_STATE_CONFIDENCE_SQL})",
            name="ck_token_market_snapshots_market_state_confidence",
        ),
    )
    op.create_index("ix_token_market_snapshots_token_id", "token_market_snapshots", ["token_id"])
    op.create_index(
        "ix_token_market_snapshots_observed_at", "token_market_snapshots", ["observed_at"]
    )
    op.create_index(
        "ix_token_market_snapshots_created_at", "token_market_snapshots", ["created_at"]
    )

    # --- token_winner_milestones -----------------------------------------
    op.create_table(
        "token_winner_milestones",
        sa.Column("milestone_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tokens.token_id"),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("winner_definition_version", sa.String(length=32), nullable=False),
        sa.Column("baseline_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("baseline_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("baseline_liquidity", sa.Numeric(38, 18), nullable=True),
        sa.Column(
            "baseline_snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("token_market_snapshots.snapshot_id"),
            nullable=False,
        ),
        sa.Column("peak_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("peak_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "peak_snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("token_market_snapshots.snapshot_id"),
            nullable=False,
        ),
        sa.Column("multiple_x", sa.Numeric(20, 6), nullable=False),
        sa.Column("crossed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason_codes", sa.String(length=256), nullable=True),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column("build_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "token_id",
            "category",
            "winner_definition_version",
            name="uq_token_winner_milestones_token_category_version",
        ),
        sa.CheckConstraint(
            "category IN ('MAJOR_WINNER', 'MONSTER', 'EXTREME')",
            name="ck_token_winner_milestones_category",
        ),
        sa.CheckConstraint(
            "baseline_price > 0", name="ck_token_winner_milestones_baseline_price_positive"
        ),
        sa.CheckConstraint("peak_price > 0", name="ck_token_winner_milestones_peak_price_positive"),
    )
    op.create_index("ix_token_winner_milestones_token_id", "token_winner_milestones", ["token_id"])
    op.create_index("ix_token_winner_milestones_category", "token_winner_milestones", ["category"])
    op.create_index(
        "ix_token_winner_milestones_created_at", "token_winner_milestones", ["created_at"]
    )

    # --- archaeology_triggers --------------------------------------------
    op.create_table(
        "archaeology_triggers",
        sa.Column("trigger_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tokens.token_id"),
            nullable=False,
        ),
        sa.Column("trigger_type", sa.String(length=24), nullable=False),
        sa.Column(
            "source_milestone_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("token_winner_milestones.milestone_id"),
            nullable=True,
        ),
        sa.Column("trigger_reason", sa.String(length=256), nullable=False),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "trigger_type IN ('HISTORICAL_WINNER', 'PROSPECTIVE_WINNER')",
            name="ck_archaeology_triggers_trigger_type",
        ),
        sa.CheckConstraint(
            "(trigger_type = 'PROSPECTIVE_WINNER') = (source_milestone_id IS NOT NULL)",
            name="ck_archaeology_triggers_prospective_has_milestone",
        ),
    )
    op.create_index("ix_archaeology_triggers_token_id", "archaeology_triggers", ["token_id"])
    op.create_index(
        "ix_archaeology_triggers_trigger_type", "archaeology_triggers", ["trigger_type"]
    )
    op.create_index("ix_archaeology_triggers_created_at", "archaeology_triggers", ["created_at"])
    # At most one HISTORICAL_WINNER trigger per token, ever.
    op.create_index(
        "uq_archaeology_triggers_historical_per_token",
        "archaeology_triggers",
        ["token_id"],
        unique=True,
        postgresql_where=sa.text("trigger_type = 'HISTORICAL_WINNER'"),
    )
    # At most one PROSPECTIVE_WINNER trigger per (token, milestone) --
    # replaying the same milestone-crossing observation must not create a
    # second trigger; a different milestone legitimately creates a new one.
    op.create_index(
        "uq_archaeology_triggers_prospective_per_milestone",
        "archaeology_triggers",
        ["token_id", "source_milestone_id"],
        unique=True,
        postgresql_where=sa.text("trigger_type = 'PROSPECTIVE_WINNER'"),
    )

    # --- archaeology_runs -------------------------------------------------
    op.create_table(
        "archaeology_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tokens.token_id"),
            nullable=False,
        ),
        sa.Column(
            "trigger_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("archaeology_triggers.trigger_id"),
            nullable=True,
        ),
        sa.Column("run_type", sa.String(length=24), nullable=False),
        sa.Column("source_provider_set", sa.String(length=256), nullable=False),
        sa.Column("time_range_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_range_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_evidence_reference", sa.String(length=256), nullable=False),
        sa.Column("known_gaps", sa.Text(), nullable=True),
        sa.Column("completeness_statement", sa.Text(), nullable=False),
        sa.Column("winner_definition_version", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_reason", sa.String(length=512), nullable=True),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column("build_hash", sa.String(length=64), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("master_spec_hash", sa.String(length=64), nullable=False),
        sa.Column("git_commit", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "run_type IN ('HISTORICAL_WINNER', 'PROSPECTIVE_WINNER')",
            name="ck_archaeology_runs_type",
        ),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'COMPLETED', 'FAILED', 'PARTIAL')",
            name="ck_archaeology_runs_status",
        ),
        sa.CheckConstraint(
            "length(input_evidence_reference) > 0",
            name="ck_archaeology_runs_input_evidence_reference_nonempty",
        ),
        sa.CheckConstraint(
            "length(completeness_statement) > 0",
            name="ck_archaeology_runs_completeness_statement_nonempty",
        ),
        sa.CheckConstraint(
            "length(build_hash) > 0", name="ck_archaeology_runs_build_hash_nonempty"
        ),
        sa.CheckConstraint(
            "length(config_hash) > 0", name="ck_archaeology_runs_config_hash_nonempty"
        ),
        sa.CheckConstraint(
            "length(master_spec_hash) > 0", name="ck_archaeology_runs_master_spec_hash_nonempty"
        ),
        sa.CheckConstraint(
            "length(git_commit) > 0", name="ck_archaeology_runs_git_commit_nonempty"
        ),
    )
    op.create_index("ix_archaeology_runs_token_id", "archaeology_runs", ["token_id"])
    op.create_index("ix_archaeology_runs_run_type", "archaeology_runs", ["run_type"])
    op.create_index("ix_archaeology_runs_status", "archaeology_runs", ["status"])
    op.create_index("ix_archaeology_runs_created_at", "archaeology_runs", ["created_at"])
    # A trigger may be consumed into at most one run -- prevents duplicate
    # concurrent trigger delivery (P2-T10). NULL trigger_id (a directly
    # CLI-invoked historical run) is unconstrained.
    op.create_index(
        "uq_archaeology_runs_trigger_id",
        "archaeology_runs",
        ["trigger_id"],
        unique=True,
        postgresql_where=sa.text("trigger_id IS NOT NULL"),
    )

    # --- wallets -----------------------------------------------------------
    op.create_table(
        "wallets",
        sa.Column("wallet_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("wallet_address", sa.String(length=64), nullable=False),
        sa.Column("first_discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("wallet_address", name="uq_wallets_wallet_address"),
    )
    op.create_index("ix_wallets_wallet_address", "wallets", ["wallet_address"])
    op.create_index("ix_wallets_created_at", "wallets", ["created_at"])

    # --- wallet_discovery_events --------------------------------------------
    op.create_table(
        "wallet_discovery_events",
        sa.Column("discovery_event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "wallet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.wallet_id"),
            nullable=False,
        ),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("discovery_channel", sa.String(length=40), nullable=False),
        sa.Column(
            "trigger_token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tokens.token_id"),
            nullable=True,
        ),
        sa.Column(
            "trigger_wallet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.wallet_id"),
            nullable=True,
        ),
        sa.Column("trigger_event", sa.String(length=128), nullable=True),
        sa.Column("trigger_reason", sa.String(length=256), nullable=False),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column(
            "exclusion_reason",
            sa.String(length=32),
            nullable=False,
            server_default="DISCOVERY_CONTAMINATION",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "wallet_id",
            "discovery_channel",
            "trigger_token_id",
            name="uq_wallet_discovery_events_wallet_channel_token",
        ),
        sa.CheckConstraint(
            f"discovery_channel IN ({_DISCOVERY_CHANNELS_SQL})",
            name="ck_wallet_discovery_events_channel",
        ),
        sa.CheckConstraint(
            "exclusion_reason = 'DISCOVERY_CONTAMINATION'",
            name="ck_wallet_discovery_events_exclusion_reason",
        ),
    )
    op.create_index(
        "ix_wallet_discovery_events_wallet_id", "wallet_discovery_events", ["wallet_id"]
    )
    op.create_index(
        "ix_wallet_discovery_events_discovery_channel",
        "wallet_discovery_events",
        ["discovery_channel"],
    )
    op.create_index(
        "ix_wallet_discovery_events_trigger_token_id",
        "wallet_discovery_events",
        ["trigger_token_id"],
    )
    op.create_index(
        "ix_wallet_discovery_events_created_at", "wallet_discovery_events", ["created_at"]
    )

    # --- early_buyers --------------------------------------------------------
    op.create_table(
        "early_buyers",
        sa.Column("early_buyer_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tokens.token_id"),
            nullable=False,
        ),
        sa.Column(
            "wallet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.wallet_id"),
            nullable=False,
        ),
        sa.Column(
            "source_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("archaeology_runs.run_id"),
            nullable=False,
        ),
        sa.Column("first_buy_slot", sa.BigInteger(), nullable=False),
        sa.Column("first_buy_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("venue", sa.String(length=64), nullable=True),
        sa.Column("lifecycle_stage", sa.String(length=32), nullable=True),
        sa.Column("entry_price_estimate", sa.Numeric(38, 18), nullable=True),
        sa.Column("entry_market_state_confidence", sa.String(length=16), nullable=True),
        sa.Column("token_age_seconds", sa.BigInteger(), nullable=True),
        sa.Column("amount_raw", sa.BigInteger(), nullable=False),
        sa.Column("amount_decimals", sa.Integer(), nullable=False),
        sa.Column("usd_estimate", sa.Numeric(38, 18), nullable=True),
        sa.Column("possible_deployer", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("possible_insider", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("possible_bundler", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "possible_funder_related", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("possible_bot", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evidence_reference", sa.String(length=256), nullable=False),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_id", "wallet_id", name="uq_early_buyers_token_wallet"),
        sa.CheckConstraint(
            f"entry_market_state_confidence IS NULL OR "
            f"entry_market_state_confidence IN ({_MARKET_STATE_CONFIDENCE_SQL})",
            name="ck_early_buyers_entry_market_state_confidence",
        ),
        sa.CheckConstraint("amount_raw > 0", name="ck_early_buyers_amount_positive"),
        sa.CheckConstraint("sequence_number >= 1", name="ck_early_buyers_sequence_positive"),
    )
    op.create_index("ix_early_buyers_token_id", "early_buyers", ["token_id"])
    op.create_index("ix_early_buyers_wallet_id", "early_buyers", ["wallet_id"])
    op.create_index("ix_early_buyers_source_run_id", "early_buyers", ["source_run_id"])
    op.create_index("ix_early_buyers_sequence_number", "early_buyers", ["sequence_number"])
    op.create_index("ix_early_buyers_created_at", "early_buyers", ["created_at"])

    # --- token_negative_controls -----------------------------------------------
    op.create_table(
        "token_negative_controls",
        sa.Column("control_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "winner_token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tokens.token_id"),
            nullable=False,
        ),
        sa.Column(
            "control_token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tokens.token_id"),
            nullable=False,
        ),
        sa.Column("method_version", sa.String(length=32), nullable=False),
        sa.Column("launch_period_match", sa.Boolean(), nullable=True),
        sa.Column("venue_match", sa.Boolean(), nullable=True),
        sa.Column("early_liquidity_delta_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("early_market_cap_delta_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("early_tx_activity_delta_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("evidence_reference", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "winner_token_id",
            "control_token_id",
            "method_version",
            name="uq_token_negative_controls_winner_control_method",
        ),
        sa.CheckConstraint(
            "winner_token_id <> control_token_id",
            name="ck_token_negative_controls_distinct_tokens",
        ),
    )
    op.create_index(
        "ix_token_negative_controls_winner_token_id",
        "token_negative_controls",
        ["winner_token_id"],
    )
    op.create_index(
        "ix_token_negative_controls_control_token_id",
        "token_negative_controls",
        ["control_token_id"],
    )
    op.create_index(
        "ix_token_negative_controls_created_at", "token_negative_controls", ["created_at"]
    )

    # --- least-privilege grants (section 72) --------------------------------
    for table in _APPEND_ONLY_TABLES:
        op.execute(f"GRANT SELECT, INSERT ON {table} TO argus_ingest;")
        op.execute(f"GRANT SELECT ON {table} TO argus_research;")
    for table in _MUTABLE_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO argus_ingest;")
        op.execute(f"GRANT SELECT ON {table} TO argus_research;")


def downgrade() -> None:
    for table in _ALL_TABLES:
        op.execute(f"REVOKE ALL ON {table} FROM argus_ingest;")
        op.execute(f"REVOKE ALL ON {table} FROM argus_research;")

    op.drop_table("token_negative_controls")

    op.drop_index("ix_early_buyers_created_at", table_name="early_buyers")
    op.drop_index("ix_early_buyers_sequence_number", table_name="early_buyers")
    op.drop_index("ix_early_buyers_source_run_id", table_name="early_buyers")
    op.drop_index("ix_early_buyers_wallet_id", table_name="early_buyers")
    op.drop_index("ix_early_buyers_token_id", table_name="early_buyers")
    op.drop_table("early_buyers")

    op.drop_index("ix_wallet_discovery_events_created_at", table_name="wallet_discovery_events")
    op.drop_index(
        "ix_wallet_discovery_events_trigger_token_id", table_name="wallet_discovery_events"
    )
    op.drop_index(
        "ix_wallet_discovery_events_discovery_channel", table_name="wallet_discovery_events"
    )
    op.drop_index("ix_wallet_discovery_events_wallet_id", table_name="wallet_discovery_events")
    op.drop_table("wallet_discovery_events")

    op.drop_index("ix_wallets_created_at", table_name="wallets")
    op.drop_index("ix_wallets_wallet_address", table_name="wallets")
    op.drop_table("wallets")

    op.drop_index("uq_archaeology_runs_trigger_id", table_name="archaeology_runs")
    op.drop_index("ix_archaeology_runs_created_at", table_name="archaeology_runs")
    op.drop_index("ix_archaeology_runs_status", table_name="archaeology_runs")
    op.drop_index("ix_archaeology_runs_run_type", table_name="archaeology_runs")
    op.drop_index("ix_archaeology_runs_token_id", table_name="archaeology_runs")
    op.drop_table("archaeology_runs")

    op.drop_index(
        "uq_archaeology_triggers_prospective_per_milestone", table_name="archaeology_triggers"
    )
    op.drop_index("uq_archaeology_triggers_historical_per_token", table_name="archaeology_triggers")
    op.drop_index("ix_archaeology_triggers_created_at", table_name="archaeology_triggers")
    op.drop_index("ix_archaeology_triggers_trigger_type", table_name="archaeology_triggers")
    op.drop_index("ix_archaeology_triggers_token_id", table_name="archaeology_triggers")
    op.drop_table("archaeology_triggers")

    op.drop_index("ix_token_winner_milestones_created_at", table_name="token_winner_milestones")
    op.drop_index("ix_token_winner_milestones_category", table_name="token_winner_milestones")
    op.drop_index("ix_token_winner_milestones_token_id", table_name="token_winner_milestones")
    op.drop_table("token_winner_milestones")

    op.drop_index("ix_token_market_snapshots_created_at", table_name="token_market_snapshots")
    op.drop_index("ix_token_market_snapshots_observed_at", table_name="token_market_snapshots")
    op.drop_index("ix_token_market_snapshots_token_id", table_name="token_market_snapshots")
    op.drop_table("token_market_snapshots")

    op.drop_index("ix_reference_asset_prices_created_at", table_name="reference_asset_prices")
    op.drop_index("ix_reference_asset_prices_observed_at", table_name="reference_asset_prices")
    op.drop_index("ix_reference_asset_prices_asset", table_name="reference_asset_prices")
    op.drop_table("reference_asset_prices")

    op.drop_index("ix_token_mint_validations_created_at", table_name="token_mint_validations")
    op.drop_index(
        "ix_token_mint_validations_validation_status", table_name="token_mint_validations"
    )
    op.drop_index("ix_token_mint_validations_token_id", table_name="token_mint_validations")
    op.drop_table("token_mint_validations")

    op.drop_index("ix_tokens_created_at", table_name="tokens")
    op.drop_index("ix_tokens_mint", table_name="tokens")
    op.drop_table("tokens")
