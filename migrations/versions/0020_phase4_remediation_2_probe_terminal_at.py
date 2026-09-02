"""Phase 4 remediation round 2: shadow_quote_probes.terminal_at

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-01

Per orchestrator instruction ``argus-phase-4-remediation-002`` (P4-R4
continued): "A scheduler drop before dispatch has no request/response
timestamps or call latency. Persist its terminal decision time/reason
separately... use explicit terminal state/time for claim, no-op,
intent-finalization and report logic instead of assuming responded_at
non-null is the only completion proof."

Adds a nullable ``terminal_at`` column to ``shadow_quote_probes``, set on
EVERY terminal write regardless of whether a real provider dispatch ever
happened -- ``requested_at``/``responded_at``/``latency_ms``/
``scheduling_delay_seconds`` now stay honestly ``NULL`` for a genuine
scheduler-level capacity drop (no request/response ever occurred), while
``terminal_at`` still records exactly when that drop was decided and
recorded. Additive only; no existing row's meaning changes; no new grant
needed (migration 0016's table-level UPDATE grant on ``shadow_quote_
probes`` for ``argus_ingest`` already covers this new column).

P4-REC-04 (``argus-phase-4-recovery-001``, frozen finding R4-M from
``argus-phase-4-failure-review-001``): the CHECK constraint below --
``responded_at IS NULL OR terminal_at IS NOT NULL`` -- is validated
against EVERY existing row the moment it is created. A pre-existing row
whose real provider response already happened (``responded_at IS NOT
NULL``) has no ``terminal_at`` value yet, because that column did not
exist before this migration -- on a real populated database this
constraint would fail the migration outright. Every prior version of this
project's code performed its terminal write in the SAME atomic
transaction immediately after computing ``responded_at`` (see
``argus.shadow.quote_jobs._execute_and_record_probe``'s own recording
step), so ``responded_at`` IS ITSELF the truthful, deterministically-
derivable terminal moment for these legacy rows -- never a fabricated or
current-wall-clock value, never a deleted/replaced row. The backfill
below sets ``terminal_at = responded_at`` for exactly those rows, BEFORE
the CHECK constraint is created. A row whose ``responded_at IS NULL``
(a still-pending probe, or a genuine scheduler-level capacity drop that
never dispatched) already satisfies the constraint via its own left-hand
side and is left untouched -- never backdated into a false "already
terminal" state, so a genuinely pending row stays claimable/runnable.
Idempotent: re-running only ever touches rows the previous run's own
``WHERE`` clause would still match (none, once backfilled).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shadow_quote_probes",
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
    )
    # P4-REC-04: backfill BEFORE the CHECK constraint below is validated --
    # see the module docstring for why responded_at is itself the
    # truthful, deterministically-derived terminal moment for these
    # legacy rows.
    op.execute(
        "UPDATE shadow_quote_probes SET terminal_at = responded_at "
        "WHERE responded_at IS NOT NULL AND terminal_at IS NULL"
    )
    op.create_check_constraint(
        "ck_shadow_probes_responded_requires_terminal",
        "shadow_quote_probes",
        "responded_at IS NULL OR terminal_at IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_shadow_probes_responded_requires_terminal", "shadow_quote_probes", type_="check"
    )
    op.drop_column("shadow_quote_probes", "terminal_at")
