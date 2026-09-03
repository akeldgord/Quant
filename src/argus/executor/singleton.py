"""argus.executor.singleton — MASTER_SPEC.md section 75 (EXECUTOR
SINGLETON), Phase 6 (``argus-phase-6-001``).

Lease/fencing-token protocol: only one live executor process may hold
the singleton lease at a time. ``try_acquire`` succeeds only when no
lease is currently held or the held lease has expired -- a genuinely
concurrent acquire against the SAME still-valid lease always REFUSES
(never blocks/waits, never silently lets two owners coexist).
``try_renew`` is a compare-and-swap: it only succeeds if the caller
still holds the EXACT fencing token it was granted; otherwise ownership
has been lost (another process took over after expiry) and the caller
must DISARM rather than assume it still owns the lease.

:class:`LeaseStore` is a small protocol so the compare-and-swap DECISION
logic (this module's own responsibility) is fully unit-testable via
:class:`InMemoryLeaseStore` without any database -- two independent
callers sharing one ``InMemoryLeaseStore`` instance is a genuine,
deterministic concurrency test.
:class:`PostgresLeaseStore` is the real production adapter, backed by
``executor_leases``/``executor_lease_fencing_seq`` (migration ``0024``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

PRIMARY_LEASE_ID = "primary"


@dataclass(frozen=True)
class LeaseHandle:
    owner_id: uuid.UUID
    fencing_token: int
    expires_at: datetime


class ExecutorSingletonRefusedError(RuntimeError):
    """Raised when acquisition is refused because another owner
    currently holds an unexpired lease."""


class LeaseStore(Protocol):
    async def try_acquire(
        self, *, owner_id: uuid.UUID, ttl: timedelta, now: datetime
    ) -> LeaseHandle | None: ...

    async def try_renew(
        self, *, owner_id: uuid.UUID, fencing_token: int, ttl: timedelta, now: datetime
    ) -> LeaseHandle | None: ...


class InMemoryLeaseStore:
    """Deterministic, fully unit-testable in-memory lease store -- two
    callers sharing ONE instance simulate two executor processes
    contending for the same database row."""

    def __init__(self) -> None:
        self._row: LeaseHandle | None = None
        self._next_token = 1

    async def try_acquire(
        self, *, owner_id: uuid.UUID, ttl: timedelta, now: datetime
    ) -> LeaseHandle | None:
        if self._row is not None and self._row.expires_at >= now:
            return None
        handle = LeaseHandle(
            owner_id=owner_id, fencing_token=self._next_token, expires_at=now + ttl
        )
        self._next_token += 1
        self._row = handle
        return handle

    async def try_renew(
        self, *, owner_id: uuid.UUID, fencing_token: int, ttl: timedelta, now: datetime
    ) -> LeaseHandle | None:
        if self._row is None:
            return None
        if self._row.owner_id != owner_id or self._row.fencing_token != fencing_token:
            return None
        handle = LeaseHandle(owner_id=owner_id, fencing_token=fencing_token, expires_at=now + ttl)
        self._row = handle
        return handle


class PostgresLeaseStore:
    """Production adapter over the real ``executor_leases`` table --
    ``INSERT ... ON CONFLICT ... WHERE <expired>`` for acquire, a
    compare-and-swap ``UPDATE ... WHERE owner_id = ... AND
    fencing_token = ...`` for renew."""

    def __init__(self, session: object) -> None:
        self._session = session

    async def try_acquire(
        self, *, owner_id: uuid.UUID, ttl: timedelta, now: datetime
    ) -> LeaseHandle | None:
        from sqlalchemy import text

        expires_at = now + ttl
        result = await self._session.execute(  # type: ignore[attr-defined]
            text(
                """
                INSERT INTO executor_leases
                    (lease_id, owner_id, fencing_token, acquired_at, expires_at, updated_at)
                VALUES
                    (:lease_id, :owner_id, nextval('executor_lease_fencing_seq'), :now,
                     :expires_at, :now)
                ON CONFLICT (lease_id) DO UPDATE SET
                    owner_id = EXCLUDED.owner_id,
                    fencing_token = nextval('executor_lease_fencing_seq'),
                    acquired_at = EXCLUDED.acquired_at,
                    expires_at = EXCLUDED.expires_at,
                    updated_at = EXCLUDED.updated_at
                WHERE executor_leases.expires_at < :now
                RETURNING fencing_token
                """
            ),
            {
                "lease_id": PRIMARY_LEASE_ID,
                "owner_id": owner_id,
                "now": now,
                "expires_at": expires_at,
            },
        )
        row = result.first()
        if row is None:
            return None
        return LeaseHandle(owner_id=owner_id, fencing_token=row[0], expires_at=expires_at)

    async def try_renew(
        self, *, owner_id: uuid.UUID, fencing_token: int, ttl: timedelta, now: datetime
    ) -> LeaseHandle | None:
        from sqlalchemy import text

        expires_at = now + ttl
        result = await self._session.execute(  # type: ignore[attr-defined]
            text(
                """
                UPDATE executor_leases
                SET expires_at = :expires_at, updated_at = :now
                WHERE lease_id = :lease_id
                    AND owner_id = :owner_id
                    AND fencing_token = :fencing_token
                RETURNING fencing_token
                """
            ),
            {
                "lease_id": PRIMARY_LEASE_ID,
                "owner_id": owner_id,
                "fencing_token": fencing_token,
                "expires_at": expires_at,
                "now": now,
            },
        )
        row = result.first()
        if row is None:
            return None
        return LeaseHandle(owner_id=owner_id, fencing_token=row[0], expires_at=expires_at)


async def acquire_or_refuse(
    store: LeaseStore, *, owner_id: uuid.UUID, ttl: timedelta, now: datetime
) -> LeaseHandle:
    handle = await store.try_acquire(owner_id=owner_id, ttl=ttl, now=now)
    if handle is None:
        raise ExecutorSingletonRefusedError(
            "another owner currently holds an unexpired executor lease"
        )
    return handle


def lost_ownership(renewed: LeaseHandle | None) -> bool:
    """True means DISARM -- the caller no longer owns the lease."""
    return renewed is None
