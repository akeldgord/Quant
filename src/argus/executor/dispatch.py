"""argus.executor.dispatch — sentinel-guarded submission/signing
dispatch boundary, MASTER_SPEC.md sections 70/78, Phase 6, P6-16.

The ONE seam through which a provider-submission call or a signer call
may ever be made. Every report/readiness/dry-run code path in this
project constructs a :class:`DispatchGuard` with
``argus.executor.signing.RaisingSigner`` and the default
``raising_submission`` (never a real signer/submission callable) --
proving, structurally, that those paths cannot accidentally perform
live network execution.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from argus.executor.signing import Signer


class DispatchNeverCalledError(RuntimeError):
    """Raised by the default raising submission callable -- proves a
    code path never actually submits to a provider."""


def raising_submission(*args: object, **kwargs: object) -> object:
    raise DispatchNeverCalledError("provider submission dispatched from a guarded path")


@dataclass(frozen=True)
class DispatchGuard:
    """Bundles a :class:`Signer` and a submission callable -- the ONLY
    two seams that may ever touch a real key or a real network request.
    Every non-canary/non-live-execution code path must be constructed
    with the raising defaults."""

    signer: Signer
    submit: Callable[..., object] = raising_submission
