"""Tests for argus.providers.scheduler.PriorityScheduler:
MASTER_SPEC.md section 15 -- strict priority ordering, and safety-class
requests are never starved or dropped while droppable (research) requests
may be delayed/dropped with an explicit reason under capacity constraint.
"""

from __future__ import annotations

import asyncio

import pytest

from argus.providers.scheduler import PriorityScheduler, RequestDropped, UnknownPriorityClassError

pytestmark = pytest.mark.asyncio


async def test_unknown_priority_class_rejected() -> None:
    scheduler = PriorityScheduler(max_concurrency=1)
    with pytest.raises(UnknownPriorityClassError):
        await scheduler.submit("NOT_A_REAL_CLASS", lambda: asyncio.sleep(0))


async def test_strict_priority_ordering_under_single_concurrency() -> None:
    """With max_concurrency=1, items submitted concurrently but out of
    priority order must still execute in strict priority order (P0
    first), because the scheduler always pops the globally
    highest-priority pending item, not merely FIFO submission order."""
    scheduler = PriorityScheduler(max_concurrency=1)
    completion_order: list[str] = []

    async def make_task(name: str, priority_class: str, hold: asyncio.Event | None = None):
        async def _run() -> None:
            if hold is not None:
                await hold.wait()
            completion_order.append(name)

        return await scheduler.submit(priority_class, _run)

    # Submit a long-running low-priority task first to occupy the single
    # concurrency slot, so the rest genuinely queue up behind it.
    blocker_hold = asyncio.Event()
    blocker = asyncio.ensure_future(make_task("blocker", "P6_background_research", blocker_hold))
    await asyncio.sleep(0)  # let the blocker actually start and take the capacity slot

    tasks = [
        asyncio.ensure_future(make_task("research-1", "P6_background_research")),
        asyncio.ensure_future(make_task("shadow-quote", "P5_shadow_exit_quote")),
        asyncio.ensure_future(make_task("copyability", "P4_prospective_copyability_quote")),
        asyncio.ensure_future(make_task("safety-check", "P3_live_safety_check")),
        asyncio.ensure_future(make_task("entry-order", "P2_live_entry_order")),
        asyncio.ensure_future(make_task("ordinary-exit", "P1_ordinary_live_exit")),
        asyncio.ensure_future(make_task("emergency-exit", "P0_emergency_live_exit")),
    ]
    await asyncio.sleep(0)  # let all six queue up behind the blocker

    blocker_hold.set()  # release the blocker; the rest should now drain in priority order
    await asyncio.gather(blocker, *tasks)

    assert completion_order == [
        "blocker",
        "emergency-exit",
        "ordinary-exit",
        "entry-order",
        "safety-check",
        "copyability",
        "shadow-quote",
        "research-1",
    ]


async def test_droppable_class_dropped_with_explicit_reason_when_queue_full() -> None:
    scheduler = PriorityScheduler(max_concurrency=1, max_queue_depth_per_droppable_class=2)
    blocker_hold = asyncio.Event()

    async def blocker_run() -> None:
        await blocker_hold.wait()

    blocker = asyncio.ensure_future(scheduler.submit("P6_background_research", blocker_run))
    await asyncio.sleep(0)  # blocker now holds the single concurrency slot

    async def noop() -> None:
        return None

    queued_1 = asyncio.ensure_future(scheduler.submit("P6_background_research", noop))
    queued_2 = asyncio.ensure_future(scheduler.submit("P6_background_research", noop))
    await asyncio.sleep(0)  # both now genuinely queued (pending depth == 2)

    with pytest.raises(RequestDropped) as exc_info:
        await scheduler.submit("P6_background_research", noop)
    assert exc_info.value.priority_class == "P6_background_research"
    assert "dropped" in str(exc_info.value)

    blocker_hold.set()
    await asyncio.gather(blocker, queued_1, queued_2)


async def test_safety_class_never_dropped_even_when_droppable_queue_is_full() -> None:
    scheduler = PriorityScheduler(max_concurrency=1, max_queue_depth_per_droppable_class=1)
    blocker_hold = asyncio.Event()
    completion_order: list[str] = []

    async def blocker_run() -> None:
        await blocker_hold.wait()
        completion_order.append("blocker")

    blocker = asyncio.ensure_future(scheduler.submit("P6_background_research", blocker_run))
    await asyncio.sleep(0)

    async def research_run() -> None:
        completion_order.append("research-queued")

    queued_research = asyncio.ensure_future(
        scheduler.submit("P6_background_research", research_run)
    )
    await asyncio.sleep(0)  # droppable queue now at its configured depth of 1

    async def safety_run() -> None:
        completion_order.append("safety")

    # A safety-class submission must be accepted (not dropped) despite the
    # droppable class being completely full, and must be dispatched ahead
    # of the already-queued research item.
    safety = asyncio.ensure_future(scheduler.submit("P0_emergency_live_exit", safety_run))
    await asyncio.sleep(0)

    blocker_hold.set()
    await asyncio.gather(blocker, queued_research, safety)

    assert completion_order == ["blocker", "safety", "research-queued"]


async def test_same_class_requests_are_fifo() -> None:
    scheduler = PriorityScheduler(max_concurrency=1)
    blocker_hold = asyncio.Event()
    order: list[int] = []

    async def blocker_run() -> None:
        await blocker_hold.wait()

    blocker = asyncio.ensure_future(scheduler.submit("P6_background_research", blocker_run))
    await asyncio.sleep(0)

    async def make(n: int):
        async def _run() -> None:
            order.append(n)

        return await scheduler.submit("P6_background_research", _run)

    tasks = [asyncio.ensure_future(make(n)) for n in range(5)]
    await asyncio.sleep(0)

    blocker_hold.set()
    await asyncio.gather(blocker, *tasks)

    assert order == [0, 1, 2, 3, 4]


async def test_exception_in_task_propagates_to_submitter_not_swallowed() -> None:
    scheduler = PriorityScheduler(max_concurrency=1)

    async def failing() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await scheduler.submit("P0_emergency_live_exit", failing)
