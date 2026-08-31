"""Central request-priority scheduler (MASTER_SPEC.md section 15).

Dispatches queued provider requests strictly in priority-class order
(``P0`` first), FIFO within a class, bounded by ``max_concurrency``
simultaneous in-flight requests. Class names match
``config/providers.yaml``'s ``jupiter.priority_classes`` list exactly.

"When constrained, background research may be delayed or dropped with an
explicit missing-data reason; safety-class requests must never be silently
starved" -- enforced here as: once a droppable class's own pending queue
depth reaches ``max_queue_depth_per_droppable_class``, further submissions
to that class are rejected immediately with :class:`RequestDropped` (a
concrete, inspectable reason -- never a fabricated/empty result). Safety
classes (``P0``-``P3``) are never subject to that limit and are always
dispatched ahead of any droppable-class item already queued, since the
scheduler always pops the globally highest-priority pending item, not
merely the head of whichever queue triggered a dispatch.

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


class PriorityScheduler:
    def __init__(
        self,
        *,
        priority_order: tuple[str, ...] = PRIORITY_ORDER,
        safety_classes: frozenset[str] = SAFETY_CLASSES,
        max_concurrency: int = 1,
        max_queue_depth_per_droppable_class: int = 50,
    ) -> None:
        self._rank = {cls: i for i, cls in enumerate(priority_order)}
        self._droppable_classes = frozenset(priority_order) - safety_classes
        self._max_queue_depth = max_queue_depth_per_droppable_class
        self._queue: list[_QueueItem] = []
        self._seq = itertools.count()
        self._lock = asyncio.Lock()
        self._capacity = asyncio.Semaphore(max_concurrency)
        self._pending_by_class: dict[str, int] = dict.fromkeys(priority_order, 0)

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
            )
            heapq.heappush(self._queue, item)
            self._pending_by_class[priority_class] += 1

        asyncio.ensure_future(self._dispatch_next())
        return await future

    async def _dispatch_next(self) -> None:
        await self._capacity.acquire()
        async with self._lock:
            if not self._queue:
                self._capacity.release()
                return
            item = heapq.heappop(self._queue)
            self._pending_by_class[item.priority_class] -= 1

        try:
            result = await item.coro_factory()
        except Exception as exc:  # noqa: BLE001 - propagate to the submitter, never swallow
            if not item.future.done():
                item.future.set_exception(exc)
        else:
            if not item.future.done():
                item.future.set_result(result)
        finally:
            self._capacity.release()

    def pending_count(self, priority_class: str | None = None) -> int:
        if priority_class is not None:
            return self._pending_by_class[priority_class]
        return sum(self._pending_by_class.values())
