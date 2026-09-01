"""Phase 4 remediation round 2: bind confirmation_time to its source
CommitmentObservation

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-01

Per orchestrator instruction ``argus-phase-4-remediation-002`` (P4-R3
continued): ``prospective_events.confirmation_time`` was previously a
bare cached timestamp with no reference to which real
``commitment_observations`` row justified it. This adds a nullable
``confirmation_observation_id`` FK to that table -- the same provenance-
binding pattern migration 0017 established for
``score_snapshot_id``/``tier_transition_id`` -- so a late-recorded
confirmation is independently checkable against its own cited evidence,
never just an opaque cached value. Additive only: no existing column's
meaning changes, no row is deleted or rewritten.

``argus_ingest`` (the role every production writer, including
``revisit_pending_confirmations``, actually connects as) gets ``UPDATE``
on ONLY this new column -- the same narrow, column-scoped grant pattern
migration 0018 used for ``confirmation_time`` itself, never a general
loosening of this table's otherwise-append-only write surface.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "prospective_events",
        sa.Column("confirmation_observation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_prospective_events_confirmation_observation_id",
        "prospective_events",
        "commitment_observations",
        ["confirmation_observation_id"],
        ["observation_id"],
    )
    op.execute("GRANT UPDATE (confirmation_observation_id) ON prospective_events TO argus_ingest;")


def downgrade() -> None:
    op.execute(
        "REVOKE UPDATE (confirmation_observation_id) ON prospective_events FROM argus_ingest;"
    )
    op.drop_constraint(
        "fk_prospective_events_confirmation_observation_id",
        "prospective_events",
        type_="foreignkey",
    )
    op.drop_column("prospective_events", "confirmation_observation_id")
