"""Central request-priority scheduler (MASTER_SPEC.md section 15).

Dispatches queued provider requests strictly in priority-class order
(``P0`` first), FIFO within a class, bounded by ``max_concurrency``
simultaneous in-flight requests. Class names match
``config/providers.yaml``'s ``jupiter.priority_classes`` list exactly.

"When constrained, background research may be delayed or dropped with an
explicit missing-data reason; safety-class requests must never be silently
starved" -- enforced two ways:

1. Once a droppable class's own pending queue depth reaches
   ``max_queue_depth_per_droppable_class``, further submissions to that
   class are rejected immediately with :class:`RequestDropped` (a
   concrete, inspectable reason -- never a fabricated/empty result).
2. Phase 1 remediation round 1, finding #8: strict priority alone can
   starve a lower *safety* class (P1-P3) indefinitely under a sustained
   flood of a higher safety class (e.g. P0) -- the previous version only
   proved ordering and non-dropping, not bounded service. An accepted
   safety-class item now ages: once ``starvation_ceiling`` other
   dispatches have happened while it was still waiting, it is serviced
   next regardless of nominal priority, giving every accepted safety-class
   request a deterministic, provable upper bound on wait time (in units
   of dispatches, not wall-clock) rather than an unbounded one. This never
   changes ordering for the common case (nothing near its ceiling) --
   only kicks in once the bound would otherwise be violated.

Nothing here executes a live trade or holds any credential -- it only
governs the ORDER in which injected async callables (``coro_factory``) run.
"""

from __future__ import annotations

import asyncio
import dataclasses
import heapq
import itertools
from collections.abc import Awaitable, Callable
from typing import Any, Final, TypeVar

T = TypeVar("T")

PRIORITY_ORDER: Final[tuple[str, ...]] = (
    "P0_emergency_live_exit",
    "P1_ordinary_live_exit",
    "P2_live_entry_order",
    "P3_live_safety_check",
    "P4_prospective_copyability_quote",
    "P5_shadow_exit_quote",
    "P6_background_research",
)

# P0-P3 are safety/execution classes: never dropped, never queue-depth-limited.
SAFETY_CLASSES: Final[frozenset[str]] = frozenset(PRIORITY_ORDER[:4])
DROPPABLE_CLASSES: Final[frozenset[str]] = frozenset(PRIORITY_ORDER[4:])

DEFAULT_STARVATION_CEILING: Final[int] = 20


class UnknownPriorityClassError(ValueError):
    pass


class RequestDropped(RuntimeError):
    """Raised into the submitter's awaited result when a droppable-class
    request is rejected under capacity constraint. Carries an explicit
    reason -- callers must surface this as a missing-data condition, never
    silently substitute a fabricated observation."""

    def __init__(self, priority_class: str, reason: str) -> None:
        super().__init__(reason)
        self.priority_class = priority_class
        self.reason = reason


@dataclasses.dataclass(order=True)
class _QueueItem:
    sort_key: tuple[int, int]
    priority_class: str = dataclasses.field(compare=False)
    coro_factory: Callable[[], Awaitable[Any]] = dataclasses.field(compare=False)
    future: asyncio.Future[Any] = dataclasses.field(compare=False)
    enqueued_at_dispatch_count: int = dataclasses.field(compare=False, default=0)


class PriorityScheduler:
    def __init__(
        self,
        *,
        priority_order: tuple[str, ...] = PRIORITY_ORDER,
        safety_classes: frozenset[str] = SAFETY_CLASSES,
        max_concurrency: int = 1,
        max_queue_depth_per_droppable_class: int = 50,
        starvation_ceiling: int = DEFAULT_STARVATION_CEILING,
    ) -> None:
        if max_concurrency <= 0:
            raise ValueError(f"max_concurrency must be positive, got {max_concurrency}")
        if max_queue_depth_per_droppable_class < 0:
            raise ValueError(
                "max_queue_depth_per_droppable_class must be nonnegative, got "
                f"{max_queue_depth_per_droppable_class}"
            )
        if starvation_ceiling <= 0:
            raise ValueError(f"starvation_ceiling must be positive, got {starvation_ceiling}")
        self._rank = {cls: i for i, cls in enumerate(priority_order)}
        self._safety_classes = frozenset(priority_order) & safety_classes
        self._droppable_classes = frozenset(priority_order) - safety_classes
        self._max_queue_depth = max_queue_depth_per_droppable_class
        self._starvation_ceiling = starvation_ceiling
        self._queue: list[_QueueItem] = []
        self._seq = itertools.count()
        self._lock = asyncio.Lock()
        self._capacity = asyncio.Semaphore(max_concurrency)
        self._pending_by_class: dict[str, int] = dict.fromkeys(priority_order, 0)
        self._dispatch_count = 0

    async def submit(self, priority_class: str, coro_factory: Callable[[], Awaitable[T]]) -> T:
        if priority_class not in self._rank:
            raise UnknownPriorityClassError(priority_class)

        loop = asyncio.get_running_loop()
        future: asyncio.Future[T] = loop.create_future()

        async with self._lock:
            if (
                priority_class in self._droppable_classes
                and self._pending_by_class[priority_class] >= self._max_queue_depth
            ):
                reason = (
                    f"scheduler at capacity for droppable class {priority_class!r} "
                    f"({self._pending_by_class[priority_class]} already queued); "
                    "dropped rather than fabricated or queued indefinitely"
                )
                future.set_exception(RequestDropped(priority_class, reason))
                return await future

            item = _QueueItem(
                sort_key=(self._rank[priority_class], next(self._seq)),
                priority_class=priority_class,
                coro_factory=coro_factory,
                future=future,
                enqueued_at_dispatch_count=self._dispatch_count,
            )
            heapq.heappush(self._queue, item)
            self._pending_by_class[priority_class] += 1

        asyncio.ensure_future(self._dispatch_next())
        return await future

    def _select_next_locked(self) -> _QueueItem:
        """Must be called with ``self._lock`` held and ``self._queue``
        non-empty. Picks the item to dispatch: normally the strict
        highest-priority item (heap top), but a safety-class item that has
        aged past ``starvation_ceiling`` dispatches is force-selected
        instead, guaranteeing bounded service (finding #8). Removing an
        arbitrary (non-top) heap element cheaply isn't possible with a
        plain binary heap, so the aged case rebuilds the heap after
        removing it -- O(n), acceptable at this queue's expected scale and
        far simpler/safer than reaching into ``heapq``'s private
        sift helpers."""
        aged_item: _QueueItem | None = None
        for candidate in self._queue:
            if candidate.priority_class not in self._safety_classes:
                continue
            age = self._dispatch_count - candidate.enqueued_at_dispatch_count
            if age >= self._starvation_ceiling and (
                aged_item is None or candidate.sort_key < aged_item.sort_key
            ):
                aged_item = candidate
        if aged_item is not None:
            self._queue.remove(aged_item)
            heapq.heapify(self._queue)
            return aged_item
        return heapq.heappop(self._queue)

    async def _dispatch_next(self) -> None:
        await self._capacity.acquire()
        item: _QueueItem | None = None
        try:
            async with self._lock:
                if not self._queue:
                    return
                item = self._select_next_locked()
                self._pending_by_class[item.priority_class] -= 1
                self._dispatch_count += 1

            try:
                result = await item.coro_factory()
            except asyncio.CancelledError:
                # This dispatch task itself was cancelled mid-flight (e.g.
                # scheduler shutdown) -- never leave the submitter's future
                # permanently wedged waiting for a resolution that will
                # never come.
                if not item.future.done():
                    item.future.cancel()
                raise
            except Exception as exc:  # noqa: BLE001 - propagate to the submitter, never swallow
                if not item.future.done():
                    item.future.set_exception(exc)
            else:
                if not item.future.done():
                    item.future.set_result(result)
        finally:
            # Always releases -- including when cancelled before an item
            # was even popped (capacity was still acquired above) -- so a
            # cancellation can never permanently leak a concurrency slot.
            self._capacity.release()

    def pending_count(self, priority_class: str | None = None) -> int:
        if priority_class is not None:
            return self._pending_by_class[priority_class]
        return sum(self._pending_by_class.values())
