"""Regression test for `argus.db.errors.constraint_name` -- Phase 1
remediation round 2, finding #9 uncovered (via a real-Postgres
integration test, not a unit test) that SQLAlchemy's asyncpg dialect
wraps the constraint-carrying exception two levels deep
(`IntegrityError.orig.__cause__`, not `.orig` itself), so a naive
`getattr(exc.orig, "constraint_name", None)` always returned `None` and
every dedup collision was wrongly re-raised as an unrecognized failure.
These fakes reproduce that exact wrapper shape without needing a real
database.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from argus.db.errors import constraint_name


class _RealAsyncpgError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__("duplicate key")
        self.constraint_name = name


class _SqlAlchemyDbapiWrapper(Exception):
    """Mimics `AsyncAdapt_asyncpg_dbapi.IntegrityError` -- carries no
    `constraint_name` of its own, only a `__cause__` chain to the real
    asyncpg exception."""


def _wrapped_integrity_error(name: str) -> IntegrityError:
    dbapi_wrapper = _SqlAlchemyDbapiWrapper()
    dbapi_wrapper.__cause__ = _RealAsyncpgError(name)
    return IntegrityError("statement", {}, dbapi_wrapper)


def test_constraint_name_found_via_orig_cause_not_orig_directly() -> None:
    exc = _wrapped_integrity_error("uq_chain_events_signature_wallet_type")
    assert constraint_name(exc) == "uq_chain_events_signature_wallet_type"


def test_constraint_name_prefers_orig_itself_when_present() -> None:
    """If a future SQLAlchemy/driver version exposes it directly on
    `.orig`, that should be used without needing `__cause__` at all."""
    direct = _RealAsyncpgError("uq_swaps_event_id_parser_version")
    exc = IntegrityError("statement", {}, direct)
    assert constraint_name(exc) == "uq_swaps_event_id_parser_version"


def test_constraint_name_returns_none_when_unavailable() -> None:
    exc = IntegrityError("statement", {}, _SqlAlchemyDbapiWrapper())
    assert constraint_name(exc) is None
