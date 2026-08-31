"""Tests for argus.providers.scheduler.PriorityScheduler:
MASTER_SPEC.md section 15 -- strict priority ordering, and safety-class
requests are never starved or dropped while droppable (research) requests
may be delayed/dropped with an explicit reason under capacity constraint.
"""

from __future__ import annotations

import asyncio

import pytest

from argus.providers.scheduler import PriorityScheduler, RequestDropped, UnknownPriorityClassError


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


# --- Finding #8: bounded service, constructor validation, cancellation --


def test_constructor_rejects_invalid_limits() -> None:
    with pytest.raises(ValueError, match="max_concurrency"):
        PriorityScheduler(max_concurrency=0)
    with pytest.raises(ValueError, match="max_concurrency"):
        PriorityScheduler(max_concurrency=-1)
    with pytest.raises(ValueError, match="max_queue_depth"):
        PriorityScheduler(max_queue_depth_per_droppable_class=-1)
    with pytest.raises(ValueError, match="starvation_ceiling"):
        PriorityScheduler(starvation_ceiling=0)


async def test_starvation_ceiling_forces_aged_safety_item_ahead_of_fresh_higher_priority_arrivals() -> (
    None
):
    """Direct test of the aging algorithm's bound (finding #8): proves
    that under a continuous stream of *freshly arriving* higher-priority
    (P0) items -- the realistic "sustained flood" scenario, where each new
    arrival has a low age relative to the current dispatch count -- an
    older, already-waiting P3 item is never delayed past
    `starvation_ceiling` dispatches, even though strict priority alone
    would always favor the newer P0 arrivals indefinitely. Drives
    `_select_next_locked()` directly rather than racing real asyncio task
    scheduling, since the guarantee is a property of this pure selection
    algorithm, not of wall-clock timing."""
    from argus.providers.scheduler import _QueueItem

    scheduler = PriorityScheduler(max_concurrency=1, starvation_ceiling=3)

    async def noop() -> None:
        return None

    p3_future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    p3_item = _QueueItem(
        sort_key=(scheduler._rank["P3_live_safety_check"], 0),
        priority_class="P3_live_safety_check",
        coro_factory=noop,
        future=p3_future,
        enqueued_at_dispatch_count=0,
    )
    scheduler._queue.append(p3_item)

    selected_classes: list[str] = []
    for i in range(5):
        p0_future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        p0_item = _QueueItem(
            sort_key=(scheduler._rank["P0_emergency_live_exit"], 100 + i),
            priority_class="P0_emergency_live_exit",
            coro_factory=noop,
            future=p0_future,
            enqueued_at_dispatch_count=scheduler._dispatch_count,  # freshly arrived: age 0 now
        )
        scheduler._queue.append(p0_item)
        chosen = scheduler._select_next_locked()
        selected_classes.append(chosen.priority_class)
        scheduler._dispatch_count += 1
        if chosen is p3_item:
            break

    assert "P3_live_safety_check" in selected_classes
    bound_index = selected_classes.index("P3_live_safety_check")
    assert bound_index <= 3  # bounded by starvation_ceiling, not left to strict priority forever
    assert selected_classes[:bound_index] == ["P0_emergency_live_exit"] * bound_index


async def test_dispatch_cancellation_releases_capacity_and_does_not_wedge_future() -> None:
    """Finding #8: a dispatch task cancelled mid-flight (e.g. scheduler
    shutdown) must never permanently hold the concurrency slot, and must
    never leave the submitter's future pending forever."""
    from argus.providers.scheduler import _QueueItem

    scheduler = PriorityScheduler(max_concurrency=1)
    started = asyncio.Event()

    async def slow() -> None:
        started.set()
        await asyncio.sleep(10)

    future_result: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    item = _QueueItem(
        sort_key=(0, 0),
        priority_class="P0_emergency_live_exit",
        coro_factory=slow,
        future=future_result,
        enqueued_at_dispatch_count=0,
    )
    scheduler._queue.append(item)
    dispatch_task = asyncio.ensure_future(scheduler._dispatch_next())
    await started.wait()  # the factory is genuinely running, holding the capacity slot

    dispatch_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await dispatch_task

    assert future_result.cancelled()  # never left wedged

    # Capacity was released -- a fresh submission must proceed immediately,
    # not hang behind a leaked slot.
    ran = asyncio.Event()

    async def quick() -> None:
        ran.set()

    result = asyncio.ensure_future(scheduler.submit("P0_emergency_live_exit", quick))
    await asyncio.wait_for(result, timeout=1.0)
    assert ran.is_set()


async def test_dispatch_cancelled_before_item_popped_still_releases_capacity() -> None:
    """Cancellation while waiting on the lock (before any item is even
    selected) must still release the semaphore -- otherwise a slot leaks
    with nothing to show for it."""
    scheduler = PriorityScheduler(max_concurrency=1)

    async def held_lock() -> None:
        await asyncio.sleep(10)

    async with scheduler._lock:
        dispatch_task = asyncio.ensure_future(scheduler._dispatch_next())
        await asyncio.sleep(0)  # dispatch_next has acquired capacity, now blocked on the lock
        dispatch_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await dispatch_task

    ran = asyncio.Event()

    async def quick() -> None:
        ran.set()

    result = asyncio.ensure_future(scheduler.submit("P0_emergency_live_exit", quick))
    await asyncio.wait_for(result, timeout=1.0)
    assert ran.is_set()
