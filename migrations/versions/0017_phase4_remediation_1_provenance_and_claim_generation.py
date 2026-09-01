"""Phase 4 remediation round 1: additive provenance/dedup/claim-generation
columns

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-01

Per orchestrator instruction ``argus-phase-4-remediation-001``
(``AUTHORIZED_ACTION: CLOSE_CONSOLIDATED_FROZEN_PHASE_4_FINDINGS``),
addressing three of the seven frozen findings with additive, non-
destructive schema changes -- no existing row is deleted, no existing
column's meaning changes, per the instruction's own "Additive schema
changes are authorized when needed for these existing obligations; no
rewriting/deleting past evidence or changes to frozen scores/thresholds."

- **P4-R1** ("preserve selected source identities so the snapshot can be
  checked"): ``prospective_events`` gains nullable ``score_snapshot_id``/
  ``tier_transition_id`` columns naming the exact
  ``wallet_score_snapshots``/``wallet_tier_history`` row (if any) that was
  actually available at ``first_seen_at`` and used to populate this
  event's frozen snapshot -- auditable provenance, not just an opaque
  value.
- **P4-R3** ("identify one prospective economic event per canonical
  wallet transaction; reparse must not silently create a second shadow
  trade"): ``prospective_events`` gains a NOT NULL ``event_id`` column
  (denormalized from ``swaps.event_id``, backfilled from the existing
  ``swap_id`` join before the NOT NULL constraint is applied) with its
  own unique constraint -- the true identity boundary is the canonical
  on-chain transaction (``chain_events.event_id``), not one specific
  parser artifact's ``swap_id``; two different parser-artifact rows for
  the SAME raw transaction can no longer both become prospective events.
  The existing ``swap_id`` unique constraint is intentionally retained
  (a defense-in-depth backstop, still correct on its own terms).
- **P4-R5** ("an ownership/attempt generation tied to each claim and
  verify it atomically at terminal write"): ``shadow_quote_probes``/
  ``shadow_mark_outcomes`` gain a ``claim_generation`` integer column,
  incremented on every claim; the terminal-write step now verifies the
  generation it read still matches before publishing, so a stale
  worker whose claim was superseded by a fresh reclaim can never
  overwrite the new attempt's result.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "prospective_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        "UPDATE prospective_events pe SET event_id = s.event_id "
        "FROM swaps s WHERE s.swap_id = pe.swap_id"
    )
    op.alter_column("prospective_events", "event_id", nullable=False)
    op.create_foreign_key(
        "fk_prospective_events_event_id",
        "prospective_events",
        "chain_events",
        ["event_id"],
        ["event_id"],
    )
    op.create_unique_constraint(
        "uq_prospective_events_event_id", "prospective_events", ["event_id"]
    )

    op.add_column(
        "prospective_events",
        sa.Column("score_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_prospective_events_score_snapshot_id",
        "prospective_events",
        "wallet_score_snapshots",
        ["score_snapshot_id"],
        ["score_id"],
    )
    op.add_column(
        "prospective_events",
        sa.Column("tier_transition_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_prospective_events_tier_transition_id",
        "prospective_events",
        "wallet_tier_history",
        ["tier_transition_id"],
        ["transition_id"],
    )

    op.add_column(
        "shadow_quote_probes",
        sa.Column("claim_generation", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "shadow_mark_outcomes",
        sa.Column("claim_generation", sa.Integer(), nullable=False, server_default="0"),
    )
    # No new GRANT statements needed: migration 0016's table-level
    # SELECT/INSERT/UPDATE grants on these three tables already cover
    # every column added here automatically.


def downgrade() -> None:
    op.drop_column("shadow_mark_outcomes", "claim_generation")
    op.drop_column("shadow_quote_probes", "claim_generation")

    op.drop_constraint(
        "fk_prospective_events_tier_transition_id", "prospective_events", type_="foreignkey"
    )
    op.drop_column("prospective_events", "tier_transition_id")
    op.drop_constraint(
        "fk_prospective_events_score_snapshot_id", "prospective_events", type_="foreignkey"
    )
    op.drop_column("prospective_events", "score_snapshot_id")

    op.drop_constraint("uq_prospective_events_event_id", "prospective_events", type_="unique")
    op.drop_constraint("fk_prospective_events_event_id", "prospective_events", type_="foreignkey")
    op.drop_column("prospective_events", "event_id")
