"""R2-02 clarification-001: persisted source-knowledge provenance on wallet_specialist_scores

Revision ID: 0041
Revises: 0040
Create Date: 2026-09-04

ARGUS-INSTRUCTION-ID: argus-final-spec-recovery-002-clarification-001

Adds ``wallet_specialist_scores.source_knowledge_max_at`` -- the MAX
``created_at``/knowledge-time among every source row that actually
contributed to a given specialist score (across entry/discovery/
validation/exit), computed in
``argus.counterfactual.service._compute_and_persist_specialist_scores``.
This is machine-checkable proof that every source item was known by the
row's own ``as_of`` cutoff, independent of when the score row ITSELF was
physically persisted -- ``as_of`` alone (checked against a query's own
``decision_time``) was not sufficient, per the independent audit's own
clarification of the already-frozen R2-02 requirement.

No existing row is deleted or rewritten (CORE-002 additive-only): this
migration adds the column as NULLABLE, backfills every pre-existing row
with its own ``as_of`` (the only value guaranteed to satisfy the new
``source_knowledge_max_at <= as_of`` invariant for historical rows with
no reconstructable per-source provenance -- ``created_at`` is typically
>= ``as_of`` for a legitimate historical reconstruction and would
usually VIOLATE that invariant if used instead), then sets the column
NOT NULL. This backfill makes no stronger claim than "assume this
pre-existing row's sources were known by its own as_of" -- exactly the
pre-fix behavior every such row was already computed under; it does not
retroactively grant these rows better provenance than they actually
have. Every pre-existing row also carries an OLD ``algorithm_version``
string that a current loader's version filter already excludes
regardless of this backfilled value. No durable (non-disposable-test-
database) row was ever computed under the OLD (missing-provenance)
semantics against a real database in this recovery round, so no
``contaminated_run_invalidations`` entry is seeded here -- this is a
genuine schema/algorithm evolution (``counterfactual_alpha_v3`` ->
``v4``, ``order_flow_prediction_v3`` -> ``v4``), not a
contaminated-result correction.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "wallet_specialist_scores",
        sa.Column("source_knowledge_max_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE wallet_specialist_scores SET source_knowledge_max_at = as_of "
        "WHERE source_knowledge_max_at IS NULL"
    )
    op.alter_column("wallet_specialist_scores", "source_knowledge_max_at", nullable=False)
    op.create_check_constraint(
        "ck_wallet_specialist_scores_source_knowledge_not_after_as_of",
        "wallet_specialist_scores",
        "source_knowledge_max_at <= as_of",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_wallet_specialist_scores_source_knowledge_not_after_as_of",
        "wallet_specialist_scores",
        type_="check",
    )
    op.drop_column("wallet_specialist_scores", "source_knowledge_max_at")
