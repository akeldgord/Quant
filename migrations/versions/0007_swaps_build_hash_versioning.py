"""phase 1 remediation round 4, finding #5: swaps versioned by parser
artifact identity (parser_version + build_hash), not parser_version alone

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-31

Round 3's finding #5 added ``parse_attempts.build_hash`` so a durable
parse attempt records the exact executable parser artifact that produced
it, not just the human-assigned ``parser_version`` label. But ``swaps``'
own dedup constraint (migration 0003) was still ``(event_id,
parser_version)`` alone -- a rebuilt parser under an unbumped version
label could append an honest new ``parse_attempts`` row while
``SqlSwapRecorder.record()`` silently treated the *derived* ``swaps`` row
as already present (the old build's classification), never appending the
new build's result. The old, potentially-incompatible derived row stayed
the only canonical answer.

Adds ``build_hash`` (NOT NULL, non-empty CHECK-constrained, matching the
``parse_attempts`` pattern from migration 0006) and replaces the dedup
unique constraint with ``(event_id, parser_version, build_hash)``. A new
build under the same version label, or a bumped version label, can now
always append an honest new derived row; the old one is never rewritten
or removed.

Every pre-existing row (recorded before this migration existed) is
backfilled with the explicit sentinel ``'NOT_CAPTURED_PRE_R4_REMEDIATION'``
rather than a fabricated hash -- ``swaps`` is derived, re-computable
evidence, but still never silently rewritten with an invented value.

Phase 1 remediation round 5, finding #8: ``downgrade()`` previously
recreated the narrower pre-0007 ``(event_id, parser_version)`` unique
constraint unconditionally. Once this revision has been live long enough
for a second parser build to append an honest new ``swaps`` row for the
same ``(event_id, parser_version)`` under a different ``build_hash`` --
exactly the case this migration exists to allow -- that recreate raises
a bare Postgres unique-violation, an opaque, undocumented failure that
never actually proved anything about what downgrading a *populated*
database does. The two honest options were a non-destructive downgrade
that somehow keeps every row anyway (impossible without silently
deleting, merging, or arbitrarily selecting one append-only row to keep
-- forbidden), or a preflight check that fails closed with a precise,
actionable reason before attempting the narrower constraint at all.
``downgrade()`` now does the latter: it queries for any ``(event_id,
parser_version)`` pair with more than one distinct ``build_hash`` and
raises :class:`Downgrade0007IncompatibleDataError` naming exactly how
many such pairs exist, refusing to touch the schema at all, before ever
reaching ``DROP CONSTRAINT``/``DROP COLUMN``. When no such pair exists
(the common case: at most one parser build has ever produced a ``swaps``
row for each event), the downgrade proceeds exactly as before and is
fully supported.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BACKFILL_SENTINEL = "NOT_CAPTURED_PRE_R4_REMEDIATION"


class Downgrade0007IncompatibleDataError(RuntimeError):
    """Raised by :func:`downgrade` when the current ``swaps`` data cannot
    be represented under the narrower pre-0007 ``(event_id,
    parser_version)`` uniqueness: at least one pair has rows from more
    than one distinct ``build_hash``. Downgrading anyway would require
    silently deleting, merging, or arbitrarily selecting one of those
    append-only rows to keep -- this project's evidence-preservation
    discipline forbids all three, so the downgrade is refused instead."""


def upgrade() -> None:
    op.add_column(
        "swaps",
        sa.Column(
            "build_hash",
            sa.String(length=64),
            nullable=False,
            server_default=_BACKFILL_SENTINEL,
        ),
    )
    op.alter_column("swaps", "build_hash", server_default=None)
    op.create_check_constraint(
        "ck_swaps_build_hash_nonempty",
        "swaps",
        "length(build_hash) > 0",
    )
    op.drop_constraint("uq_swaps_event_id_parser_version", "swaps", type_="unique")
    op.create_unique_constraint(
        "uq_swaps_event_id_parser_version_build_hash",
        "swaps",
        ["event_id", "parser_version", "build_hash"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    conflicts = bind.execute(
        sa.text(
            "SELECT event_id, parser_version, COUNT(DISTINCT build_hash) AS distinct_builds "
            "FROM swaps GROUP BY event_id, parser_version HAVING COUNT(DISTINCT build_hash) > 1"
        )
    ).fetchall()
    if conflicts:
        raise Downgrade0007IncompatibleDataError(
            f"cannot downgrade past revision 0007: {len(conflicts)} (event_id, parser_version) "
            "pair(s) in 'swaps' have rows from more than one distinct build_hash -- the "
            "narrower pre-0007 (event_id, parser_version) unique constraint cannot represent "
            "this data. Downgrading would require silently deleting, merging, or arbitrarily "
            "selecting one of these append-only rows, which is never done. Resolve by "
            "archiving/exporting the affected 'swaps' rows for the listed pairs before "
            "downgrading, or do not downgrade past this revision once more than one parser "
            "build has produced a swaps row for the same chain event."
        )
    op.drop_constraint("uq_swaps_event_id_parser_version_build_hash", "swaps", type_="unique")
    op.create_unique_constraint(
        "uq_swaps_event_id_parser_version", "swaps", ["event_id", "parser_version"]
    )
    op.drop_constraint("ck_swaps_build_hash_nonempty", "swaps", type_="check")
    op.drop_column("swaps", "build_hash")
