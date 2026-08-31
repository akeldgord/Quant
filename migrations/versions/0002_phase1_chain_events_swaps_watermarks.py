"""phase 1: chain_events, swaps, wallet_stream_state, clock_health_events

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-31

Implements MASTER_SPEC.md section 18 (canonical event ledger), section 21
(generic swap parser output), section 19 (per-wallet fast-path/truth-path
watermarks), and section 17 (durable clock health/anomaly log). Adds
least-privilege grants per section 72, matching the per-role pattern
established in 0001_baseline_roles_and_provider_usage.py: ``argus_ingest``
writes raw/derived data it produces; ``argus_research`` reads broadly;
``argus_executor`` gets nothing here (Phase 1 does not execute).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chain_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("chain", sa.String(length=32), nullable=False, server_default="solana"),
        sa.Column("slot", sa.BigInteger(), nullable=False),
        sa.Column("block_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("transaction_signature", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("wallet_address", sa.String(length=64), nullable=True),
        sa.Column("mint", sa.String(length=64), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "transaction_signature",
            "wallet_address",
            "event_type",
            name="uq_chain_events_signature_wallet_type",
        ),
    )
    op.create_index("ix_chain_events_slot", "chain_events", ["slot"])
    op.create_index("ix_chain_events_first_seen_at", "chain_events", ["first_seen_at"])
    op.create_index("ix_chain_events_provider", "chain_events", ["provider"])
    op.create_index(
        "ix_chain_events_transaction_signature", "chain_events", ["transaction_signature"]
    )
    op.create_index("ix_chain_events_wallet_address", "chain_events", ["wallet_address"])
    op.create_index("ix_chain_events_created_at", "chain_events", ["created_at"])

    op.create_table(
        "swaps",
        sa.Column("swap_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chain_events.event_id"),
            nullable=False,
        ),
        sa.Column("wallet_address", sa.String(length=64), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("input_mint", sa.String(length=64), nullable=True),
        sa.Column("input_amount_raw", sa.BigInteger(), nullable=True),
        sa.Column("input_amount_ui", sa.Numeric(38, 18), nullable=True),
        sa.Column("output_mint", sa.String(length=64), nullable=True),
        sa.Column("output_amount_raw", sa.BigInteger(), nullable=True),
        sa.Column("output_amount_ui", sa.Numeric(38, 18), nullable=True),
        sa.Column("network_fee_raw", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("slot", sa.BigInteger(), nullable=False),
        sa.Column("block_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("parser_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_swaps_event_id", "swaps", ["event_id"])
    op.create_index("ix_swaps_wallet_address", "swaps", ["wallet_address"])
    op.create_index("ix_swaps_classification", "swaps", ["classification"])
    op.create_index("ix_swaps_created_at", "swaps", ["created_at"])

    op.create_table(
        "wallet_stream_state",
        sa.Column("wallet_address", sa.String(length=64), primary_key=True),
        sa.Column("last_stream_signature", sa.String(length=128), nullable=True),
        sa.Column("last_stream_slot", sa.BigInteger(), nullable=True),
        sa.Column("last_reconciled_signature", sa.String(length=128), nullable=True),
        sa.Column("last_reconciled_slot", sa.BigInteger(), nullable=True),
        sa.Column("last_reconciliation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stream_health", sa.String(length=16), nullable=False, server_default="UNKNOWN"),
        sa.Column("wallet_live_state", sa.String(length=16), nullable=False, server_default="OK"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "clock_health_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("sampled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("monotonic_seconds", sa.Float(), nullable=False),
        sa.Column("wall_delta_seconds", sa.Float(), nullable=False),
        sa.Column("monotonic_delta_seconds", sa.Float(), nullable=False),
        sa.Column("drift_seconds", sa.Float(), nullable=False),
        sa.Column("healthy", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_clock_health_events_sampled_at", "clock_health_events", ["sampled_at"])
    op.create_index("ix_clock_health_events_healthy", "clock_health_events", ["healthy"])

    # Least-privilege grants (section 72): ingest produces this data,
    # research reads it broadly for later phases' scoring/analysis. The
    # executor role gets nothing here -- Phase 1 never executes.
    for table in ("chain_events", "swaps", "wallet_stream_state", "clock_health_events"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO argus_ingest;")
        op.execute(f"GRANT SELECT ON {table} TO argus_research;")


def downgrade() -> None:
    for table in ("chain_events", "swaps", "wallet_stream_state", "clock_health_events"):
        op.execute(f"REVOKE ALL ON {table} FROM argus_ingest;")
        op.execute(f"REVOKE ALL ON {table} FROM argus_research;")

    op.drop_index("ix_clock_health_events_healthy", table_name="clock_health_events")
    op.drop_index("ix_clock_health_events_sampled_at", table_name="clock_health_events")
    op.drop_table("clock_health_events")

    op.drop_table("wallet_stream_state")

    op.drop_index("ix_swaps_created_at", table_name="swaps")
    op.drop_index("ix_swaps_classification", table_name="swaps")
    op.drop_index("ix_swaps_wallet_address", table_name="swaps")
    op.drop_index("ix_swaps_event_id", table_name="swaps")
    op.drop_table("swaps")

    op.drop_index("ix_chain_events_created_at", table_name="chain_events")
    op.drop_index("ix_chain_events_wallet_address", table_name="chain_events")
    op.drop_index("ix_chain_events_transaction_signature", table_name="chain_events")
    op.drop_index("ix_chain_events_provider", table_name="chain_events")
    op.drop_index("ix_chain_events_first_seen_at", table_name="chain_events")
    op.drop_index("ix_chain_events_slot", table_name="chain_events")
    op.drop_table("chain_events")
