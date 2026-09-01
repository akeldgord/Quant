"""Phase 3 remediation round 2 (P3-R6a): widen provenance columns nullable
for databases already stamped 0011 under its original destructive form.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-01

Migration 0011 was UNAPPROVED (Phase 3 has never been orchestrator-
approved) when an independent audit (``argus-phase-3-remediation-audit-
001``) found its original ``upgrade()`` destructive: it made
``wallet_positions.round_trip_index``/``input_manifest_digest`` and
``wallet_score_snapshots.input_manifest_digest`` ``NOT NULL`` and paired
that with ``DELETE``/``UPDATE`` statements clearing all existing Phase 3
decision rows so the new columns could be backfilled with a placeholder.
Per orchestrator instruction ``argus-phase-3-remediation-002``, migration
0011's own file was amended in place (permitted narrow change-control on
a still-unapproved migration) to make these three columns nullable from
the start and remove the ``DELETE``/``UPDATE`` statements entirely --
never migration 0010 or any orchestrator-approved migration.

That amendment is sufficient for any database that has not yet run
migration 0011 at all: a fresh ``zero -> head`` upgrade picks up the
amended, non-destructive 0011 directly. It is NOT sufficient for a
database whose ``alembic_version`` already reads ``0011`` from running
the migration's ORIGINAL (destructive, ``NOT NULL``) form before this
amendment landed -- Alembic never re-runs an already-applied revision's
``upgrade()``, so such a database's columns are still physically
``NOT NULL`` at the DB level and its Phase 3 decision tables were already
cleared by the original 0011's now-removed ``DELETE`` statements. This
migration performs the same nullable-widening as a pure schema fix for
that case; for a database that already ran the amended 0011, every
operation below is an idempotent no-op (the columns are already nullable
and the constraints already match).

This migration performs NO data changes and deletes nothing. It cannot
restore rows already lost to the original 0011's ``DELETE`` statements in
a database that ran that original form before this amendment -- that
loss, where it already occurred (this project's own disposable local
development database, no other environment), is disclosed in the
remediation-002 checkpoint rather than claimed as recovered; no
recomputation is asserted to "restore" the original historical beliefs.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


class Downgrade0012IncompatibleDataError(RuntimeError):
    """Raised by :func:`downgrade` when a NULL provenance value exists
    that the narrower pre-0012 (post-original-0011) ``NOT NULL``
    constraint cannot represent. Downgrading anyway would require either
    deleting those legacy rows or fabricating a digest/index value for
    them, neither of which this project ever does silently."""


def upgrade() -> None:
    # Idempotent-safe for both a fresh install (already nullable, via the
    # amended migration 0011 above) and a database that ran 0011's
    # original destructive/NOT-NULL form before that amendment.
    op.alter_column("wallet_positions", "round_trip_index", nullable=True)
    op.alter_column("wallet_positions", "input_manifest_digest", nullable=True)
    op.alter_column("wallet_score_snapshots", "input_manifest_digest", nullable=True)

    op.drop_constraint("ck_wallet_positions_round_trip_index", "wallet_positions", type_="check")
    op.create_check_constraint(
        "ck_wallet_positions_round_trip_index",
        "wallet_positions",
        "round_trip_index IS NULL OR round_trip_index >= 0",
    )
    op.drop_constraint(
        "ck_wallet_positions_input_manifest_digest_nonempty", "wallet_positions", type_="check"
    )
    op.create_check_constraint(
        "ck_wallet_positions_input_manifest_digest_nonempty",
        "wallet_positions",
        "input_manifest_digest IS NULL OR length(input_manifest_digest) > 0",
    )
    op.drop_constraint(
        "ck_wallet_score_input_manifest_digest_nonempty", "wallet_score_snapshots", type_="check"
    )
    op.create_check_constraint(
        "ck_wallet_score_input_manifest_digest_nonempty",
        "wallet_score_snapshots",
        "input_manifest_digest IS NULL OR length(input_manifest_digest) > 0",
    )


def downgrade() -> None:
    bind = op.get_bind()
    null_positions = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM wallet_positions "
            "WHERE round_trip_index IS NULL OR input_manifest_digest IS NULL"
        )
    ).scalar_one()
    null_scores = bind.execute(
        sa.text("SELECT COUNT(*) FROM wallet_score_snapshots WHERE input_manifest_digest IS NULL")
    ).scalar_one()
    if null_positions or null_scores:
        raise Downgrade0012IncompatibleDataError(
            f"cannot downgrade past revision 0012: {null_positions} wallet_positions row(s) "
            f"with a NULL round_trip_index/input_manifest_digest and {null_scores} "
            "wallet_score_snapshots row(s) with a NULL input_manifest_digest cannot be "
            "represented under the narrower pre-0012 NOT NULL constraint. Downgrading would "
            "require deleting these legacy rows or fabricating a digest/index value for them, "
            "which is never done. Resolve by archiving/exporting the affected legacy rows "
            "before downgrading, or do not downgrade past this revision once a legacy "
            "(pre-provenance-tracking) decision row exists."
        )

    op.drop_constraint(
        "ck_wallet_score_input_manifest_digest_nonempty", "wallet_score_snapshots", type_="check"
    )
    op.create_check_constraint(
        "ck_wallet_score_input_manifest_digest_nonempty",
        "wallet_score_snapshots",
        "length(input_manifest_digest) > 0",
    )
    op.drop_constraint(
        "ck_wallet_positions_input_manifest_digest_nonempty", "wallet_positions", type_="check"
    )
    op.create_check_constraint(
        "ck_wallet_positions_input_manifest_digest_nonempty",
        "wallet_positions",
        "length(input_manifest_digest) > 0",
    )
    op.drop_constraint("ck_wallet_positions_round_trip_index", "wallet_positions", type_="check")
    op.create_check_constraint(
        "ck_wallet_positions_round_trip_index", "wallet_positions", "round_trip_index >= 0"
    )

    op.alter_column("wallet_score_snapshots", "input_manifest_digest", nullable=False)
    op.alter_column("wallet_positions", "input_manifest_digest", nullable=False)
    op.alter_column("wallet_positions", "round_trip_index", nullable=False)
