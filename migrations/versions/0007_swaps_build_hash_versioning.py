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
    op.drop_constraint("uq_swaps_event_id_parser_version_build_hash", "swaps", type_="unique")
    op.create_unique_constraint(
        "uq_swaps_event_id_parser_version", "swaps", ["event_id", "parser_version"]
    )
    op.drop_constraint("ck_swaps_build_hash_nonempty", "swaps", type_="check")
    op.drop_column("swaps", "build_hash")
