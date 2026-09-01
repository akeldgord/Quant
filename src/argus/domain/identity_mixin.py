"""Shared columns for the CORE-004 "full identity block" (MASTER_SPEC.md:
every meaningful decision records algorithm version, config version/hash,
and git commit). ``src/argus/domain/parse_attempts.py`` established this
exact 4-column shape (``build_hash``/``config_hash``/``master_spec_hash``/
``git_commit``, each required and non-empty) for Phase 1's one audit-
critical decision ledger; Phase 2 adds two more audit-critical decision
ledgers (on-chain mint validation, historical/prospective archaeology
runs) that need the identical shape, so it is factored out here rather
than copy-pasted a second and third time.

Not applied to every Phase 2 table -- only to the tables recording a
genuinely audit-critical algorithmic decision, matching the precedent set
by Phase 1 (``chain_events``/``swaps`` carry only ``parser_version`` +
``build_hash``; the full block is reserved for ``parse_attempts``).
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column


class FullIdentityMixin:
    """Mix into a declarative model to add ``build_hash``/``config_hash``/
    ``master_spec_hash``/``git_commit``. The including model's
    ``__table_args__`` must still add the four non-empty ``CheckConstraint``
    entries returned by :func:`full_identity_check_constraints` (SQLAlchemy
    does not merge ``__table_args__`` across mixins automatically)."""

    build_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    master_spec_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    git_commit: Mapped[str] = mapped_column(String(64), nullable=False)


def full_identity_check_constraints(table_name: str) -> tuple[CheckConstraint, ...]:
    """The four non-empty ``CheckConstraint`` entries a table using
    :class:`FullIdentityMixin` must append to its own ``__table_args__``,
    named consistently with the table (matches ``parse_attempts``'s own
    ``ck_parse_attempts_build_hash_nonempty`` naming convention)."""
    return (
        CheckConstraint("length(build_hash) > 0", name=f"ck_{table_name}_build_hash_nonempty"),
        CheckConstraint("length(config_hash) > 0", name=f"ck_{table_name}_config_hash_nonempty"),
        CheckConstraint(
            "length(master_spec_hash) > 0", name=f"ck_{table_name}_master_spec_hash_nonempty"
        ),
        CheckConstraint("length(git_commit) > 0", name=f"ck_{table_name}_git_commit_nonempty"),
    )
