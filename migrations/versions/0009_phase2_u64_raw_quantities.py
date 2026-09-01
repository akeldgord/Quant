"""Phase 2 remediation: exact unsigned-64-bit raw quantity columns

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-01

Orchestrator instruction ``argus-phase-2-remediation-001``, finding
P2-R7 (``SPEC_BLOCKING``): the Phase 2 schema's ``token_market_
snapshots.supply_raw`` and ``early_buyers.amount_raw`` columns used
signed PostgreSQL ``BIGINT`` (max ``2**63 - 1``), which cannot represent
the full unsigned 64-bit domain Solana/SPL raw token quantities actually
use (max ``2**64 - 1``). This migration widens both columns to
``NUMERIC(39, 10)`` (see ``argus.domain.u64`` for why a nonzero scale is
required for the integrality CHECK to ever see a fractional remainder to
reject -- PostgreSQL silently rounds at coercion time on a scale-0
column, confirmed empirically against this project's own PostgreSQL 16
instance) and adds two CHECK constraints per column: an inclusive
``[0, 2**64 - 1]`` range guard, and an integrality guard
(``value = trunc(value)``). ``argus.domain.u64.U64Numeric`` is the
matching SQLAlchemy column type -- it always presents a plain Python
``int`` at the ORM boundary (never ``Decimal``/``float``) and fails fast
in Python before ever reaching the database on a non-int, negative, or
out-of-range value.

No other Phase 2 (or earlier-phase) column is touched: this instruction
is explicitly scoped to "New Phase 2 supply_raw and amount_raw columns"
-- Phase 1's own pre-existing ``swaps.input_amount_raw``/
``output_amount_raw``/``network_fee_raw`` (also ``BigInteger``) are
already-approved history, out of this remediation's scope, and
unmodified here.

Downgrade fails closed (mirroring migration 0007's ``Downgrade0007
IncompatibleDataError`` precedent): if any currently-stored value in
either column exceeds ``BIGINT``'s signed 64-bit ceiling
(``2**63 - 1``), it cannot be represented after downgrading back to
``BIGINT`` without silent truncation/corruption, so the downgrade is
refused with a clear, actionable error instead.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_U64_MAX = 2**64 - 1
_BIGINT_MAX = 2**63 - 1
_STORAGE_TYPE = sa.Numeric(39, 10)

# (table, column) pairs this migration widens -- kept as one list so
# upgrade/downgrade apply the identical operation set in mirrored order.
_COLUMNS: tuple[tuple[str, str], ...] = (
    ("token_market_snapshots", "supply_raw"),
    ("early_buyers", "amount_raw"),
)


class Downgrade0009IncompatibleDataError(RuntimeError):
    """Raised by :func:`downgrade` when a currently-stored raw quantity
    exceeds signed ``BIGINT``'s range and therefore cannot be represented
    after downgrading -- silently truncating/corrupting an append-only
    raw on-chain quantity is never done."""


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            type_=_STORAGE_TYPE,
            postgresql_using=f"{column}::numeric(39,10)",
        )
        op.create_check_constraint(
            f"ck_{table}_{column}_u64_range",
            table,
            f"{column} IS NULL OR {column} BETWEEN 0 AND {_U64_MAX}",
        )
        op.create_check_constraint(
            f"ck_{table}_{column}_u64_integral",
            table,
            f"{column} IS NULL OR {column} = trunc({column})",
        )


def downgrade() -> None:
    bind = op.get_bind()
    for table, column in _COLUMNS:
        overflow = bind.execute(
            sa.text(f"SELECT COUNT(*) FROM {table} WHERE {column} > :bigint_max"),  # noqa: S608
            {"bigint_max": _BIGINT_MAX},
        ).scalar_one()
        if overflow:
            raise Downgrade0009IncompatibleDataError(
                f"cannot downgrade past revision 0009: {overflow} row(s) in '{table}.{column}' "
                f"exceed signed BIGINT's range (2**63 - 1 = {_BIGINT_MAX}) -- the pre-0009 "
                "BIGINT column cannot represent this data without silent truncation. "
                "Downgrading is refused; archive/export the affected rows first, or do not "
                "downgrade past this revision once a raw quantity this large has been recorded."
            )

    for table, column in _COLUMNS:
        op.drop_constraint(f"ck_{table}_{column}_u64_integral", table, type_="check")
        op.drop_constraint(f"ck_{table}_{column}_u64_range", table, type_="check")
        op.alter_column(
            table,
            column,
            type_=sa.BigInteger(),
            postgresql_using=f"{column}::bigint",
        )
