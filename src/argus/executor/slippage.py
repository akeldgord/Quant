"""argus.executor.slippage — MASTER_SPEC.md section 80 (NO AUTOMATIC
SLIPPAGE ESCALATION), Phase 6 (``argus-phase-6-001``).

If a trade fails because the approved slippage ceiling was
insufficient, the executor never repeatedly raises the ceiling. Any
retry stays within the SAME operator-approved risk ceiling AND never
exceeds an earlier attempt's own slippage value (monotonic non-
increase, so escalation is structurally impossible, not merely
avoided by convention); if execution cannot occur safely, the intent
is abandoned, never retried with a higher ceiling.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetryDecision:
    allowed: bool
    reason: str
    slippage_bps_to_use: int | None = None


def evaluate_retry(
    *,
    approved_ceiling_bps: int,
    requested_slippage_bps: int,
    previous_attempt_bps: int | None,
) -> RetryDecision:
    if requested_slippage_bps > approved_ceiling_bps:
        return RetryDecision(
            allowed=False,
            reason=(
                f"requested {requested_slippage_bps}bps exceeds approved ceiling "
                f"{approved_ceiling_bps}bps"
            ),
        )
    if previous_attempt_bps is not None and requested_slippage_bps > previous_attempt_bps:
        return RetryDecision(
            allowed=False,
            reason=(
                f"requested {requested_slippage_bps}bps exceeds previous attempt "
                f"{previous_attempt_bps}bps -- automatic escalation is never permitted"
            ),
        )
    return RetryDecision(
        allowed=True,
        reason="within approved ceiling, no escalation",
        slippage_bps_to_use=requested_slippage_bps,
    )


def should_abandon(*, approved_ceiling_bps: int, minimum_viable_slippage_bps: int | None) -> bool:
    """True means ABANDON -- no slippage value within the approved
    ceiling can safely execute."""
    if minimum_viable_slippage_bps is None:
        return True
    return minimum_viable_slippage_bps > approved_ceiling_bps
