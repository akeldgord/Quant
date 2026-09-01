"""Phase 3 remediation: point-in-time cutoff, round-trip ledger integrity

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-01

Per orchestrator instruction ``argus-phase-3-remediation-001``
(``AUTHORIZED_ACTION: REMEDIATE_ALL_FROZEN_PHASE_3_BLOCKERS_ONLY``),
findings P3-R1, P3-R2, and P3-R3. Migration 0010 itself is never rewritten
(the instruction's own explicit "do not rewrite migration 0010" -- this
adds the minimal additional columns those three findings require:

- ``wallet_positions.round_trip_index`` (int, >= 0) and
  ``input_manifest_digest`` (SHA-256 hex, non-empty): P3-R3's stable
  round-trip identity and raw-evidence-reference digest, so a full close
  then reopen of the same token is two separately identified rows, not
  one merged lifetime aggregate.
- ``wallet_score_snapshots.input_manifest_digest`` (SHA-256 hex,
  non-empty): P3-R1/P3-R6's stable input-manifest digest binding a score
  to the exact, sorted, point-in-time-bounded evidence set that produced
  it -- part of the replay-idempotency identity, not just metadata.
- ``wallet_history_quality.acquisition_manifest`` (JSONB, nullable):
  P3-R2's verified, structured acquisition-run manifest a HIGH/MEDIUM
  completeness judgment must now be traceable to, never a bare caller-
  typed status string.
- ``wallet_metrics_snapshots.largest_trade_contribution_pct``/
  ``top_three_trade_contribution_pct`` widened from ``Numeric(6, 5)`` to
  ``Numeric(20, 6)`` (P3-R5): the corrected ratio (largest closed
  round-trip PnL over estimated NET lifetime P&L, not gross positive
  gains) is no longer bounded to ``[0, 1]``.

The three new NOT NULL columns cannot be backfilled honestly (no
retroactive round_trip_index/input_manifest_digest can be derived for a
position/score row computed under the pre-remediation code, since that
code did not track per-round-trip evidence at all). Per this
instruction's own explicit "do not rewrite migration 0010" combined with
"correct ... quote-safe weighted-average inventory," the only honest
choice is to clear the derived, always-recomputable Phase 3 decision
tables this remediation directly changes the shape of
(``wallet_positions``, ``wallet_score_snapshots``, ``wallet_metrics_
snapshots``, ``wallet_tier_history``) and their denormalized
``wallets.current_tier`` cache -- every one of these is a derived
artifact `argus wallets reconstruct-and-score` fully regenerates from the
still-untouched raw evidence (``swaps``, ``wallets`` identity rows,
``wallet_discovery_events``, ``early_buyers``, ``wallet_cluster_links``),
never itself raw evidence. This is disclosed explicitly in the
remediation checkpoint, not silently done.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Derived-artifact tables this remediation reshapes -- cleared, never
    # raw evidence. FK-safe order: tier history references score
    # snapshots via a nullable source_score_id.
    op.execute("DELETE FROM wallet_tier_history")
    op.execute("DELETE FROM wallet_score_snapshots")
    op.execute("DELETE FROM wallet_metrics_snapshots")
    op.execute("DELETE FROM wallet_positions")
    op.execute("UPDATE wallets SET current_tier = NULL")

    op.add_column(
        "wallet_positions",
        sa.Column("round_trip_index", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("wallet_positions", "round_trip_index", server_default=None)
    op.add_column(
        "wallet_positions",
        sa.Column("input_manifest_digest", sa.String(length=64), nullable=False),
    )
    op.create_check_constraint(
        "ck_wallet_positions_round_trip_index", "wallet_positions", "round_trip_index >= 0"
    )
    op.create_check_constraint(
        "ck_wallet_positions_input_manifest_digest_nonempty",
        "wallet_positions",
        "length(input_manifest_digest) > 0",
    )

    op.add_column(
        "wallet_score_snapshots",
        sa.Column("input_manifest_digest", sa.String(length=64), nullable=False),
    )
    op.create_check_constraint(
        "ck_wallet_score_input_manifest_digest_nonempty",
        "wallet_score_snapshots",
        "length(input_manifest_digest) > 0",
    )

    op.add_column(
        "wallet_history_quality",
        sa.Column("acquisition_manifest", postgresql.JSONB(), nullable=True),
    )

    op.alter_column(
        "wallet_metrics_snapshots",
        "largest_trade_contribution_pct",
        type_=sa.Numeric(20, 6),
        existing_type=sa.Numeric(6, 5),
    )
    op.alter_column(
        "wallet_metrics_snapshots",
        "top_three_trade_contribution_pct",
        type_=sa.Numeric(20, 6),
        existing_type=sa.Numeric(6, 5),
    )


def downgrade() -> None:
    op.alter_column(
        "wallet_metrics_snapshots",
        "top_three_trade_contribution_pct",
        type_=sa.Numeric(6, 5),
        existing_type=sa.Numeric(20, 6),
    )
    op.alter_column(
        "wallet_metrics_snapshots",
        "largest_trade_contribution_pct",
        type_=sa.Numeric(6, 5),
        existing_type=sa.Numeric(20, 6),
    )

    op.drop_column("wallet_history_quality", "acquisition_manifest")

    op.drop_constraint(
        "ck_wallet_score_input_manifest_digest_nonempty",
        "wallet_score_snapshots",
        type_="check",
    )
    op.drop_column("wallet_score_snapshots", "input_manifest_digest")

    op.drop_constraint(
        "ck_wallet_positions_input_manifest_digest_nonempty", "wallet_positions", type_="check"
    )
    op.drop_constraint("ck_wallet_positions_round_trip_index", "wallet_positions", type_="check")
    op.drop_column("wallet_positions", "input_manifest_digest")
    op.drop_column("wallet_positions", "round_trip_index")

    # The DELETE/UPDATE data changes made in upgrade() are not reversible
    # (derived data, not schema) -- downgrade only reverses the schema.
