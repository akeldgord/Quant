"""argus.executor.position_policy — MASTER_SPEC.md section 65 (ONE OPEN
POSITION PER MINT DEFAULT), Phase 6 (``argus-phase-6-001``).

``ALLOW_AUTOMATIC_SCALE_IN = false`` is hardcoded here, never read from
config/env -- multiple wallet signals concerning the same token may
increase confidence, but they must never automatically create
additional buys. The real, final backstop is the database's own
partial unique index on ``live_positions`` (migration ``0024``,
``WHERE status = 'OPEN'``); this module's decision function is the
application-level check that runs BEFORE ever attempting an insert.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

ALLOW_AUTOMATIC_SCALE_IN: Final[bool] = False


@dataclass(frozen=True)
class ScaleInDecision:
    allowed: bool
    reason: str


def evaluate_scale_in(*, existing_open_position_for_mint: bool) -> ScaleInDecision:
    if not existing_open_position_for_mint:
        return ScaleInDecision(allowed=True, reason="no existing open position for this mint")
    if ALLOW_AUTOMATIC_SCALE_IN:
        return ScaleInDecision(allowed=True, reason="scale-in explicitly allowed")
    return ScaleInDecision(
        allowed=False,
        reason=(
            "an open position already exists for this mint and "
            "ALLOW_AUTOMATIC_SCALE_IN=false -- additional wallet signals may "
            "increase confidence but must never automatically create another buy"
        ),
    )
