"""phase 1 remediation round 3, finding #5: parse_attempts build/config/
MASTER_SPEC/git identity columns

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-31

Migration 0004 added ``parse_attempts`` recording ``parser_version`` and
``input_payload_hash`` but no build hash, config hash, MASTER_SPEC hash,
or git commit. MASTER_SPEC.md CORE-004 ("every meaningful decision is
reproducible") requires algorithm version, config version/hash, and git
commit -- a human-assigned ``parser_version`` label alone can be
forgotten to bump, and neither existing column says anything about the
runtime configuration or MASTER_SPEC.md contract version in force when
the attempt ran, so the immutable attempt could not be reproduced
against the exact code/configuration that produced it.

Adds four NOT NULL columns:

- ``build_hash`` -- a reproducible SHA-256 hash of the exact parsing-
  algorithm source that ran (``argus.parsing.generic_parser``), distinct
  from ``parser_version`` (a label that can be forgotten to bump) and
  from ``git_commit`` (which changes on any commit anywhere in the repo,
  not just parser changes, and does not reflect uncommitted local edits);
- ``config_hash`` -- ``ArgusConfig.config_hash()``, the effective runtime
  configuration in force at attempt time;
- ``master_spec_hash`` -- the SHA-256 of ``MASTER_SPEC.md`` itself
  (``argus.config.master_spec_hash``);
- ``git_commit`` -- ``git rev-parse HEAD`` at attempt time.

Every pre-existing row (recorded under round 2's schema, before this
migration existed) is backfilled with the explicit sentinel
``'NOT_CAPTURED_PRE_R3_REMEDIATION'`` rather than a fabricated hash --
those rows are immutable append-only evidence and are never rewritten
with invented values; the sentinel honestly records that this identity
was not captured at the time. Every row recorded from this migration
forward always carries a real, non-empty value: a ``length(...) > 0``
CHECK constraint on all four columns makes an empty string impossible at
the database layer, not merely by application-code convention.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BACKFILL_SENTINEL = "NOT_CAPTURED_PRE_R3_REMEDIATION"
_IDENTITY_COLUMNS: tuple[str, ...] = ("build_hash", "config_hash", "master_spec_hash", "git_commit")


def upgrade() -> None:
    for column in _IDENTITY_COLUMNS:
        op.add_column(
            "parse_attempts",
            sa.Column(
                column,
                sa.String(length=64),
                nullable=False,
                server_default=_BACKFILL_SENTINEL,
            ),
        )
    for column in _IDENTITY_COLUMNS:
        # Drop the server default *after* backfill so every future insert
        # must supply a real value explicitly -- an application-code bug
        # that forgets to pass the identity fails loudly (NOT NULL
        # violation), never silently falls back to the backfill sentinel.
        op.alter_column("parse_attempts", column, server_default=None)
        op.create_check_constraint(
            f"ck_parse_attempts_{column}_nonempty",
            "parse_attempts",
            f"length({column}) > 0",
        )


def downgrade() -> None:
    for column in _IDENTITY_COLUMNS:
        op.drop_constraint(f"ck_parse_attempts_{column}_nonempty", "parse_attempts", type_="check")
    for column in _IDENTITY_COLUMNS:
        op.drop_column("parse_attempts", column)
