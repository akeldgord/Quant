"""FSR-05 recovery finding: fix Phase 7-11 write-role grants

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-04

ARGUS-INSTRUCTION-ID: argus-final-spec-recovery-001

Additive/corrective grant-only migration: no table, column, or index is
altered; migration `0030` (and everything before it) is unmodified.

Real defect found while validating FSR-05 against a role-enforced
Postgres: every Phase 7-11 analytics table (migrations `0025`-`0029`)
granted ``INSERT`` to ``argus_research`` and only ``SELECT`` to
``argus_ingest``. But every one of these tables is actually written by
the production CLI commands (``argus graph report``, ``argus convergence
report``, ``argus counterfactual report``, ``argus synthetic report``,
``argus predict report`` -- see ``argus.cli``'s own
``_phase2_engine_and_sessionmaker``, which connects as ``DbRole.INGEST``
for every one of these commands, the same role Phase 0-5's own
``argus_ingest``-writes-``argus_research``-reads convention already
established for ``wallet_copyability_snapshots``/
``opportunity_readiness_snapshots`` in migration `0022`). Under real
least-privilege role enforcement this made every one of these report
commands structurally unable to persist its own computed results --
masked in prior validation because the DB-backed integration tests for
these phases inherited the same (incorrect) ``DbRole.INGEST``-writes
assumption as the production code, so both were consistently wrong
together rather than caught against each other. This migration corrects
the grant direction to match actual usage: ``argus_ingest`` gets
``SELECT, INSERT``; ``argus_research`` keeps read access
(``SELECT`` only, unchanged from what it already had for these tables
minus the ``INSERT`` it should never have held); ``argus_executor``'s
existing read-only grant is untouched.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AFFECTED_TABLES: tuple[str, ...] = (
    "lead_follow_observations",
    "directional_edges",
    "convergence_events",
    "expected_confirmation_events",
    "counterfactual_alpha_estimates",
    "wallet_specialist_scores",
    "wallet_predation_scores",
    "exit_convergence_events",
    "synthetic_strategy_trades",
    "synthetic_strategy_summaries",
    "order_flow_prediction_runs",
)


def upgrade() -> None:
    for table in _AFFECTED_TABLES:
        op.execute(f"GRANT SELECT, INSERT ON {table} TO argus_ingest;")
        op.execute(f"REVOKE INSERT ON {table} FROM argus_research;")


def downgrade() -> None:
    for table in _AFFECTED_TABLES:
        op.execute(f"REVOKE INSERT ON {table} FROM argus_ingest;")
        op.execute(f"GRANT SELECT, INSERT ON {table} TO argus_research;")
