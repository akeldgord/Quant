"""R2-02: Phase 11 specialist-input propagation, v2->v3 invalidation

Revision ID: 0040
Revises: 0039
Create Date: 2026-09-04

ARGUS-INSTRUCTION-ID: argus-final-spec-recovery-002

Additive-only, CORE-002-compliant. Seeds exactly ONE new
``contaminated_run_invalidations`` row naming
``order_flow_prediction_v2`` invalid and superseded by
``order_flow_prediction_v3``. No code in ``argus.prediction`` itself
changed; its own ``wallet_discovery_effect_size`` feature is read
straight from Phase 9's ``WalletSpecialistScore.discovery_specialist_
score`` (R2-02's own fix, migration ``0038``), so every historical
feature value computed against the OLD, leaky Phase 9 output is
contaminated by propagation and must never be silently presented as a
current result alongside a value computed after the fix.

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

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TARGET_COMMIT = "7cca4094d7672759b1023733a810f552f1109040"

_REASON = (
    "R2-02 propagation: Phase 11's wallet_discovery_effect_size feature "
    "is read directly from Phase 9's WalletSpecialistScore.discovery_"
    "specialist_score, which was itself corrected by the R2-02 "
    "known_by_cutoff fix (migration 0038, counterfactual_alpha_v3). No "
    "code in argus.prediction changed, but every historical feature "
    "value computed against the OLD, leaky Phase 9 output is "
    "contaminated by propagation."
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
                "phase_name": "PHASE_11_PREDICTION",
                "invalidated_algorithm_version": "order_flow_prediction_v2",
                "superseded_by_algorithm_version": "order_flow_prediction_v3",
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
        "WHERE phase_name = 'PHASE_11_PREDICTION' "
        "AND invalidated_algorithm_version = 'order_flow_prediction_v2' "
        "AND superseded_by_algorithm_version = 'order_flow_prediction_v3'"
    )
