"""Phase 5 remediation (F5-05): bind config_hash into snapshot identity

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-02

Per orchestrator instruction ``argus-phase-5-remediation-001`` finding
F5-05: ``wallet_copyability_snapshots``/``opportunity_readiness_snapshots``
already carry a ``config_hash`` column (``FullIdentityMixin``, added by
0022) but their unique-identity constraints omitted it -- a rerun after a
``config/signals_v1.yaml`` weight change over otherwise-identical evidence
would silently reuse the OLD row instead of producing a new one (stale-
config reuse). This migration is additive-only: it does not touch any row
or any column added by 0022, only widens each table's own unique
constraint (drop-by-name, recreate-by-name with ``config_hash`` added) so
identity is ``(... , evidence_manifest_digest, config_hash)``. No existing
grant changes.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_wallet_copyability_identity", "wallet_copyability_snapshots", type_="unique"
    )
    op.create_unique_constraint(
        "uq_wallet_copyability_identity",
        "wallet_copyability_snapshots",
        ["wallet_id", "as_of", "algorithm_version", "evidence_manifest_digest", "config_hash"],
    )

    op.drop_constraint(
        "uq_opportunity_readiness_identity", "opportunity_readiness_snapshots", type_="unique"
    )
    op.create_unique_constraint(
        "uq_opportunity_readiness_identity",
        "opportunity_readiness_snapshots",
        [
            "prospective_event_id",
            "as_of",
            "algorithm_version",
            "evidence_manifest_digest",
            "config_hash",
        ],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_opportunity_readiness_identity", "opportunity_readiness_snapshots", type_="unique"
    )
    op.create_unique_constraint(
        "uq_opportunity_readiness_identity",
        "opportunity_readiness_snapshots",
        ["prospective_event_id", "as_of", "algorithm_version", "evidence_manifest_digest"],
    )

    op.drop_constraint(
        "uq_wallet_copyability_identity", "wallet_copyability_snapshots", type_="unique"
    )
    op.create_unique_constraint(
        "uq_wallet_copyability_identity",
        "wallet_copyability_snapshots",
        ["wallet_id", "as_of", "algorithm_version", "evidence_manifest_digest"],
    )
