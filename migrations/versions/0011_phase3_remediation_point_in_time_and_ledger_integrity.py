"""Phase 3 remediation: point-in-time cutoff, round-trip ledger integrity

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-01

Per orchestrator instruction ``argus-phase-3-remediation-001``
(``AUTHORIZED_ACTION: REMEDIATE_ALL_FROZEN_PHASE_3_BLOCKERS_ONLY``),
findings P3-R1, P3-R2, and P3-R3. Migration 0010 itself is never rewritten
(the instruction's own explicit "do not rewrite migration 0010" -- this
adds the minimal additional columns those three findings require:

- ``wallet_positions.round_trip_index`` (int, >= 0, nullable) and
  ``input_manifest_digest`` (SHA-256 hex, non-empty when present,
  nullable): P3-R3's stable round-trip identity and raw-evidence-reference
  digest, so a full close then reopen of the same token is two separately
  identified rows, not one merged lifetime aggregate.
- ``wallet_score_snapshots.input_manifest_digest`` (SHA-256 hex,
  non-empty when present, nullable): P3-R1/P3-R6's stable input-manifest
  digest binding a score to the exact, sorted, point-in-time-bounded
  evidence set that produced it -- part of the replay-idempotency
  identity, not just metadata.
- ``wallet_history_quality.acquisition_manifest`` (JSONB, nullable):
  P3-R2's verified, structured acquisition-run manifest a HIGH/MEDIUM
  completeness judgment must now be traceable to, never a bare caller-
  typed status string.
- ``wallet_metrics_snapshots.largest_trade_contribution_pct``/
  ``top_three_trade_contribution_pct`` widened from ``Numeric(6, 5)`` to
  ``Numeric(20, 6)`` (P3-R5): the corrected ratio (largest closed
  round-trip PnL over estimated NET lifetime P&L, not gross positive
  gains) is no longer bounded to ``[0, 1]``.

REMEDIATION-002 AMENDMENT (P3-R6a): the original version of this
UNAPPROVED migration made ``round_trip_index``/``input_manifest_digest``
``NOT NULL`` and paired that with ``DELETE FROM wallet_tier_history``,
``DELETE FROM wallet_score_snapshots``, ``DELETE FROM
wallet_metrics_snapshots``, ``DELETE FROM wallet_positions``, and
``UPDATE wallets SET current_tier = NULL`` in ``upgrade()`` -- an
independent audit (``argus-phase-3-remediation-audit-001``) correctly
found this an irreversible loss of historical decision rows, a direct
integrity regression against MASTER_SPEC's own append-only-history
requirement (never merely an environmental/disclosed-but-acceptable
tradeoff). Per orchestrator instruction ``argus-phase-3-remediation-002``
(``AUTHORIZED_ACTION:
CLOSE_REMAINING_FROZEN_PHASE_3_DEFECTS_AND_MIGRATION_REGRESSION``,
explicit narrow change-control authorization to amend this still-
UNAPPROVED migration in place -- never migration 0010, never any
orchestrator-approved migration), the DELETE/UPDATE statements are
removed and the three new columns are now nullable: a legacy row
computed under pre-remediation code simply carries ``NULL`` for these
new provenance fields rather than being destroyed or having a fabricated
value invented for it. The production write path (``qualification_
service.py``) still always populates real values for every newly
computed row -- nullability is a schema-level allowance for honestly
un-recomputable legacy history, never a relaxation of what new writes
must provide. See migration 0012 for the companion fix required for a
database that already applied this migration's original (destructive,
NOT-NULL) form before this amendment landed -- such a database's
``alembic_version`` is already stamped ``0011`` and will never re-run
this file's ``upgrade()``, so its columns are still physically
``NOT NULL`` at the DB level and must be separately widened.
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
    # P3-R6a: no data is deleted or reset here. Every existing
    # wallet_positions/wallet_score_snapshots/wallet_metrics_snapshots/
    # wallet_tier_history row and wallets.current_tier value is preserved
    # byte-for-byte; the new columns below are added nullable so a legacy
    # row simply has no value for them.
    op.add_column(
        "wallet_positions",
        sa.Column("round_trip_index", sa.Integer(), nullable=True),
    )
    op.add_column(
        "wallet_positions",
        sa.Column("input_manifest_digest", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        "ck_wallet_positions_round_trip_index",
        "wallet_positions",
        "round_trip_index IS NULL OR round_trip_index >= 0",
    )
    op.create_check_constraint(
        "ck_wallet_positions_input_manifest_digest_nonempty",
        "wallet_positions",
        "input_manifest_digest IS NULL OR length(input_manifest_digest) > 0",
    )

    op.add_column(
        "wallet_score_snapshots",
        sa.Column("input_manifest_digest", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        "ck_wallet_score_input_manifest_digest_nonempty",
        "wallet_score_snapshots",
        "input_manifest_digest IS NULL OR length(input_manifest_digest) > 0",
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

    # No data was deleted in upgrade() (P3-R6a) -- this downgrade only
    # reverses the schema (drops the new nullable columns/constraints and
    # narrows the two Numeric columns back), never touches row data.
