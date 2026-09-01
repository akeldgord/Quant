"""Phase 4 remediation round 1: grant argus_ingest UPDATE on
prospective_events.confirmation_time

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-01

Per orchestrator instruction ``argus-phase-4-remediation-001``, closing a
real gap discovered while writing P4-R3's focused tests: migration 0016
deliberately classified ``prospective_events`` as pure-append (only
``SELECT, INSERT`` granted to ``argus_ingest``) since a prospective
event's frozen snapshot must never be rewritten. But P4-R3 requires
``argus.shadow.prospective.revisit_pending_confirmations`` to record a
genuinely late-arriving real confirmation by setting exactly ONE column,
``confirmation_time`` -- and the ``argus_ingest`` role (the role every
production writer including ``argus prospective run`` actually connects
as) has no ``UPDATE`` privilege on this table at all, so that write fails
with ``InsufficientPrivilegeError`` against real Postgres the moment a
pending confirmation genuinely needs to be exposed. Existing tests never
caught this because they always seeded the ``CONFIRMED`` observation
*before* scanning, so ``confirmation_time`` was already set at row
creation and the ``UPDATE`` path in ``revisit_pending_confirmations``
never actually executed.

This grants ``UPDATE`` on ONLY the ``confirmation_time`` column (Postgres
column-level privileges), not the whole row -- every other column
(``first_seen_at``, the frozen score/tier/context snapshot fields, etc.)
stays exactly as append-only as migration 0016 intended. This is the
single narrow exception the instruction's own P4-R3 section explicitly
authorizes ("Record later confirmation evidence via an immutable linked
observation/update history... Do not invent confirmation success or
promote failed source transactions"), not a general loosening of this
table's write surface.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("GRANT UPDATE (confirmation_time) ON prospective_events TO argus_ingest;")


def downgrade() -> None:
    op.execute("REVOKE UPDATE (confirmation_time) ON prospective_events FROM argus_ingest;")
