"""P6-04 (SAFETY_OR_INTEGRITY_BLOCKING): singleton/fencing protection --
MASTER_SPEC.md section 75 (EXECUTOR SINGLETON), orchestrator instruction
``argus-phase-6-001``.

Two independent simulated executor instances share ONE
``InMemoryLeaseStore`` -- a genuine, deterministic concurrency test
without any database. Exactly one owner ever holds the lease; a second
concurrent acquire is refused, never silently allowed to coexist; losing
ownership (fencing-token mismatch on renew) always signals DISARM.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from argus.executor.singleton import (
    ExecutorSingletonRefusedError,
    InMemoryLeaseStore,
    acquire_or_refuse,
    lost_ownership,
)

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
_TTL = timedelta(seconds=30)


@pytest.mark.asyncio
async def test_second_concurrent_owner_is_refused_never_coexists() -> None:
    store = InMemoryLeaseStore()
    owner_a = uuid.uuid4()
    owner_b = uuid.uuid4()

    handle_a = await acquire_or_refuse(store, owner_id=owner_a, ttl=_TTL, now=_NOW)
    assert handle_a.owner_id == owner_a

    with pytest.raises(ExecutorSingletonRefusedError):
        await acquire_or_refuse(store, owner_id=owner_b, ttl=_TTL, now=_NOW + timedelta(seconds=1))


@pytest.mark.asyncio
async def test_owner_can_renew_its_own_lease_before_expiry() -> None:
    store = InMemoryLeaseStore()
    owner_a = uuid.uuid4()
    handle_a = await acquire_or_refuse(store, owner_id=owner_a, ttl=_TTL, now=_NOW)

    renewed = await store.try_renew(
        owner_id=owner_a,
        fencing_token=handle_a.fencing_token,
        ttl=_TTL,
        now=_NOW + timedelta(seconds=5),
    )
    assert renewed is not None
    assert lost_ownership(renewed) is False


@pytest.mark.asyncio
async def test_new_owner_after_expiry_gets_a_new_fencing_token() -> None:
    store = InMemoryLeaseStore()
    owner_a = uuid.uuid4()
    owner_b = uuid.uuid4()
    handle_a = await acquire_or_refuse(store, owner_id=owner_a, ttl=_TTL, now=_NOW)

    handle_b = await acquire_or_refuse(
        store, owner_id=owner_b, ttl=_TTL, now=_NOW + _TTL + timedelta(seconds=1)
    )
    assert handle_b.owner_id == owner_b
    assert handle_b.fencing_token != handle_a.fencing_token


@pytest.mark.asyncio
async def test_stale_owner_renew_after_takeover_signals_lost_ownership() -> None:
    """The classic split-brain scenario: owner A's lease expires, owner B
    takes over, and owner A -- unaware -- tries to renew with its now-
    stale fencing token. This must always signal DISARM, never a silent
    success that would let two owners both believe they hold the lease."""
    store = InMemoryLeaseStore()
    owner_a = uuid.uuid4()
    owner_b = uuid.uuid4()
    handle_a = await acquire_or_refuse(store, owner_id=owner_a, ttl=_TTL, now=_NOW)

    expiry_time = _NOW + _TTL + timedelta(seconds=1)
    await acquire_or_refuse(store, owner_id=owner_b, ttl=_TTL, now=expiry_time)

    stale_renew = await store.try_renew(
        owner_id=owner_a,
        fencing_token=handle_a.fencing_token,
        ttl=_TTL,
        now=expiry_time + timedelta(seconds=1),
    )
    assert lost_ownership(stale_renew) is True


@pytest.mark.asyncio
async def test_renew_with_wrong_fencing_token_signals_lost_ownership() -> None:
    store = InMemoryLeaseStore()
    owner_a = uuid.uuid4()
    handle_a = await acquire_or_refuse(store, owner_id=owner_a, ttl=_TTL, now=_NOW)

    result = await store.try_renew(
        owner_id=owner_a,
        fencing_token=handle_a.fencing_token + 999,
        ttl=_TTL,
        now=_NOW + timedelta(seconds=1),
    )
    assert lost_ownership(result) is True


@pytest.mark.asyncio
async def test_renew_with_no_lease_ever_acquired_signals_lost_ownership() -> None:
    store = InMemoryLeaseStore()
    result = await store.try_renew(owner_id=uuid.uuid4(), fencing_token=1, ttl=_TTL, now=_NOW)
    assert lost_ownership(result) is True
