"""R2-03: Phase 10 strategy-time executable matching, v2->v3 invalidation

Revision ID: 0039
Revises: 0038
Create Date: 2026-09-04

ARGUS-INSTRUCTION-ID: argus-final-spec-recovery-002

Additive-only, CORE-002-compliant. Seeds exactly ONE new
``contaminated_run_invalidations`` row naming
``synthetic_super_wallet_v2`` invalid and superseded by
``synthetic_super_wallet_v3`` -- the fix in
``argus.synthetic.service._price_and_persist_trades``, which now (a)
matches each trade's exit pricing against whichever REAL reverse-quote
probe's observed elapsed time is actually contemporaneous with that
trade's own hold duration (``_select_contemporaneous_reverse_outcome``),
replacing the fixed ``PRIMARY_EXECUTABLE_HORIZON`` ("5m") used for every
trade regardless of how long it was actually held, and (b) looks up
Strategy C/D's confirmed-entry executable-return opportunity by the
LEADER's own real entry time (not the follower's confirmation time),
fixing a silent near-total FAILURE_NO_EXECUTABLE_EVIDENCE forcing on
those two strategies.

``TARGET_COMMIT`` (``7cca4094d7672759b1023733a810f552f1109040``) is the
exact audited-contaminated commit this recovery round
(``argus-final-spec-recovery-002``) responds to.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TARGET_COMMIT = "7cca4094d7672759b1023733a810f552f1109040"

_REASON = (
    "R2-03: executable-return exit pricing used a fixed "
    "PRIMARY_EXECUTABLE_HORIZON (5m) reverse-quote for every trade "
    "regardless of that trade's own actual hold duration (e.g. a 1-hour "
    "hold priced off a 5-minute-later quote), and Strategy C/D's "
    "confirmed-entry opportunity lookup used the follower's own "
    "confirmation time instead of the leader's real entry time, silently "
    "forcing those two strategies to FAILURE_NO_EXECUTABLE_EVIDENCE "
    "almost always."
)


def upgrade() -> None:
    table = sa.table(
        "contaminated_run_invalidations",
        sa.column("invalidation_id", postgresql.UUID(as_uuid=True)),
        sa.column("phase_name", sa.String),
        sa.column("invalidated_algorithm_version", sa.String),
        sa.column("superseded_by_algorithm_version", sa.String),
        sa.column("status", sa.String),
        sa.column("reason", sa.Text),
        sa.column("target_commit", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    seeded_at = datetime(2026, 9, 4, tzinfo=UTC)
    op.bulk_insert(
        table,
        [
            {
                "invalidation_id": uuid.uuid4(),
                "phase_name": "PHASE_10_SYNTHETIC",
                "invalidated_algorithm_version": "synthetic_super_wallet_v2",
                "superseded_by_algorithm_version": "synthetic_super_wallet_v3",
                "status": "INVALID_FOR_EVALUATION",
                "reason": _REASON,
                "target_commit": _TARGET_COMMIT,
                "created_at": seeded_at,
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM contaminated_run_invalidations "
        "WHERE phase_name = 'PHASE_10_SYNTHETIC' "
        "AND invalidated_algorithm_version = 'synthetic_super_wallet_v2' "
        "AND superseded_by_algorithm_version = 'synthetic_super_wallet_v3'"
    )
