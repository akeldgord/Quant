"""Helpers for identifying exactly which database constraint caused an
``IntegrityError``, so a duplicate-key collision can be told apart from
every other integrity failure precisely (Phase 1 remediation round 2,
finding #9).

SQLAlchemy's asyncpg dialect wraps the *real* ``asyncpg.exceptions.*``
error two levels deep: ``IntegrityError.orig`` is SQLAlchemy's own DBAPI
adapter exception (``AsyncAdapt_asyncpg_dbapi.IntegrityError``), which
does **not** carry ``constraint_name`` -- that attribute lives on the
underlying real asyncpg exception, reachable as ``orig.__cause__``. Using
``orig`` directly (a mistake this module exists to prevent) silently
returns ``None`` for every constraint, which would make every collision
look unidentifiable and fall through to "re-raise as an unrecognized
failure" instead of the intended dedup/idempotency path.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError


def constraint_name(exc: IntegrityError) -> str | None:
    """The Postgres constraint name that caused ``exc``, or ``None`` if
    it cannot be determined (an unexpected driver/exception shape --
    callers must treat that as "not the constraint I'm checking for",
    never assume a match)."""
    for candidate in (
        getattr(exc, "orig", None),
        getattr(getattr(exc, "orig", None), "__cause__", None),
    ):
        name = getattr(candidate, "constraint_name", None)
        if name is not None:
            return str(name)
    return None
