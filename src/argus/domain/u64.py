"""Exact unsigned-64-bit raw on-chain quantity column type (P2-R7).

The pre-remediation Phase 2 schema stored ``supply_raw``/``amount_raw``
as signed PostgreSQL ``BIGINT`` (max ``2**63 - 1``), which cannot
represent the full unsigned 64-bit domain Solana/SPL raw token amounts
actually use (max ``2**64 - 1``, roughly double ``BIGINT``'s ceiling) --
a genuine silent-overflow risk for any token with a large enough raw
supply or balance.

:class:`U64Numeric` stores the value as ``NUMERIC(39, 10)`` (39 digits of
precision comfortably exceeds the 20 digits ``2**64 - 1`` needs, and a
non-zero scale is required -- see the module-level note below -- for the
integrality CHECK constraint to ever actually see a fractional remainder
to reject), while always presenting a plain Python ``int`` at the ORM
boundary (never ``Decimal`` or ``float``, per this instruction's explicit
"keep Python values as int" requirement) via ``process_bind_param``/
``process_result_value``. Both directions also fail fast in Python before
ever reaching the database on a non-``int``, negative, or out-of-range
value -- the paired ``CheckConstraint``\\s (:func:`u64_check_constraints`)
are a second, independent line of defense against any write that bypasses
the ORM (e.g. a future raw-SQL migration or admin-role fixup script).

Why ``NUMERIC(39, 10)`` and not ``NUMERIC(20, 0)`` for the integrality
check: PostgreSQL silently ROUNDS a value to a column's declared scale at
storage/coercion time rather than rejecting it (empirically confirmed
against this project's own PostgreSQL 16 instance: inserting ``1.5`` into
a bare ``NUMERIC(20,0)`` column stores ``2``, no error). A
``CHECK (value = trunc(value))`` constraint evaluates against the
already-coerced stored value, so on a scale-0 column it is always
trivially true and never actually catches anything. Declaring the column
with a nonzero scale (10, arbitrarily generous) lets a genuine fractional
input survive coercion long enough for the CHECK to see and reject it --
confirmed empirically the same way (a ``NUMERIC(39,10)`` column with this
same CHECK genuinely raises on ``1.5``, and genuinely accepts
``2**64 - 1``)."""

from __future__ import annotations

from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.types import TypeDecorator

U64_MAX: Final[int] = 2**64 - 1
_STORAGE_PRECISION: Final[int] = 39
_STORAGE_SCALE: Final[int] = 10


class U64Numeric(TypeDecorator[int]):
    """A PostgreSQL-backed column type for an exact, unsigned 64-bit raw
    on-chain quantity, always presented as a plain Python ``int``."""

    impl = sa.Numeric(_STORAGE_PRECISION, _STORAGE_SCALE)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> int | None:
        if value is None:
            return None
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(
                f"u64 raw on-chain quantity must be a plain int, got {value!r} "
                f"({type(value).__name__})"
            )
        if not (0 <= value <= U64_MAX):
            raise ValueError(
                f"u64 raw on-chain quantity {value} is outside the unsigned 64-bit "
                f"domain [0, {U64_MAX}]"
            )
        return value

    def process_result_value(self, value: Any, dialect: Any) -> int | None:
        if value is None:
            return None
        return int(value)


def u64_check_constraints(table_name: str, column_name: str) -> tuple[sa.CheckConstraint, ...]:
    """The two independent database-level guards backing :class:`U64Numeric`
    -- a defense-in-depth counterpart to the Python-level checks above,
    covering any write that bypasses the ORM entirely."""
    return (
        sa.CheckConstraint(
            f"{column_name} IS NULL OR {column_name} BETWEEN 0 AND {U64_MAX}",
            name=f"ck_{table_name}_{column_name}_u64_range",
        ),
        sa.CheckConstraint(
            f"{column_name} IS NULL OR {column_name} = trunc({column_name})",
            name=f"ck_{table_name}_{column_name}_u64_integral",
        ),
    )
