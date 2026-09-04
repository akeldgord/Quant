"""FSR-02: execution_fills evidence-reference columns + updatable evidence

Revision ID: 0037
Revises: 0036
Create Date: 2026-09-04

ARGUS-INSTRUCTION-ID: argus-final-spec-recovery-001

Additive-only. ``execution_fills`` (migration ``0024``) already separates
quoted/simulated/actual input-output plus fees, but has no way to record
WHICH confirmed on-chain transaction the ``actual_*`` evidence came from,
nor the commitment level that evidence was observed at -- so a reviewer
could not distinguish "confirmed chain evidence" from "value present for
some other reason." Adds:

- ``transaction_signature`` (nullable, unique when present): the exact
  confirmed transaction the evidence was reconstructed from.
- ``slot``: the slot that transaction landed in.
- ``confirmation_state``: ``UNKNOWN`` | ``PROCESSED`` | ``CONFIRMED`` |
  ``FINALIZED`` | ``FAILED`` -- the commitment level (or terminal failure)
  this row's evidence currently reflects. ``NULL`` for a fill row that
  predates this migration or has no chain-confirmation evidence yet.
- ``updated_at`` (nullable): a fill row is created once at submission time
  with only quoted/simulated evidence, then updated in place as
  ``argus.executor.confirmation`` resolves ambiguous/pending chain state --
  the first genuine UPDATE path this append-mostly table has ever needed.

No existing column, row, or grant is altered. The ``argus_executor`` role
already has UPDATE on ``execution_fills`` (migration ``0024``, table-level
grant), so no new GRANT is required for the new columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "execution_fills",
        sa.Column("transaction_signature", sa.String(length=128), nullable=True),
    )
    op.add_column("execution_fills", sa.Column("slot", sa.BigInteger(), nullable=True))
    op.add_column(
        "execution_fills", sa.Column("confirmation_state", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "execution_fills", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "uq_execution_fills_transaction_signature",
        "execution_fills",
        ["transaction_signature"],
        unique=True,
        postgresql_where=sa.text("transaction_signature IS NOT NULL"),
    )
    op.create_check_constraint(
        "ck_execution_fills_confirmation_state",
        "execution_fills",
        "confirmation_state IN ('UNKNOWN', 'PROCESSED', 'CONFIRMED', 'FINALIZED', 'FAILED') "
        "OR confirmation_state IS NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_execution_fills_confirmation_state", "execution_fills", type_="check")
    op.drop_index("uq_execution_fills_transaction_signature", table_name="execution_fills")
    op.drop_column("execution_fills", "updated_at")
    op.drop_column("execution_fills", "confirmation_state")
    op.drop_column("execution_fills", "slot")
    op.drop_column("execution_fills", "transaction_signature")
