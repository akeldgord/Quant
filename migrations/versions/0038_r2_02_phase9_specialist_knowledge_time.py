"""R2-02: Phase 9 specialist-score knowledge-time fix, v2->v3 invalidation

Revision ID: 0038
Revises: 0037
Create Date: 2026-09-04

ARGUS-INSTRUCTION-ID: argus-final-spec-recovery-002

Additive-only, CORE-002-compliant: no existing
``contaminated_run_invalidations`` row (or any Phase 9 derived row) is
deleted, rewritten, or relabeled. This migration seeds exactly ONE new
row naming ``counterfactual_alpha_v2`` invalid and superseded by
``counterfactual_alpha_v3`` -- the fix in
``argus.counterfactual.service._compute_and_persist_specialist_scores``,
which now bounds its discovery/validation source-evidence queries by
``created_at <= cutoff`` in addition to ``as_of == cutoff`` (the
``known_by_cutoff`` / M1 invariant already established by FSR-04, applied
here where it was previously missing).

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

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TARGET_COMMIT = "7cca4094d7672759b1023733a810f552f1109040"

_REASON = (
    "R2-02: the discovery- and validation-specialist queries in "
    "_compute_and_persist_specialist_scores filtered contributing "
    "DirectionalEdge/ExpectedConfirmationEvent rows by as_of == cutoff "
    "alone -- known_by_cutoff (M1) also requires created_at <= cutoff, "
    "which was missing, letting a specialist score labeled as_of=T be "
    "silently built from source evidence only recorded (i.e. only "
    "knowable) after T."
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
                "phase_name": "PHASE_9_COUNTERFACTUAL",
                "invalidated_algorithm_version": "counterfactual_alpha_v2",
                "superseded_by_algorithm_version": "counterfactual_alpha_v3",
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
        "WHERE phase_name = 'PHASE_9_COUNTERFACTUAL' "
        "AND invalidated_algorithm_version = 'counterfactual_alpha_v2' "
        "AND superseded_by_algorithm_version = 'counterfactual_alpha_v3'"
    )
