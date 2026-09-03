"""argus.convergence.confirmation -- MASTER_SPEC.md Phase 8 (CONVERGENCE
+ NEGATIVE EVIDENCE), section 60 (DOG-THAT-DIDN'T-BARK SIGNAL): classify
whether a follower's historically-expected confirmation of a leader's
real buy entry occurred, and how.

MASTER_SPEC's own rule: if leader R historically precedes follower A
frequently (a significant Phase 7 ``directional_edges`` row) and R buys
token X, and A does not appear within the expected window, that is
``EXPECTED_CONFIRMATION_ABSENT`` -- mandatory negative-evidence research.
Also supports ``EARLY``/``LATE`` (outside the edge's own empirical
historical lag band) and ``STRONG`` (an unusually high independent-actor
convergence coincided with the confirmation). "Test whether missing
downstream confirmation predicts poor outcomes. Do not assume it does" --
this module only produces the classification; it never assumes an
outcome relationship.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

OUTCOME_ABSENT = "ABSENT"
OUTCOME_EARLY = "EARLY"
OUTCOME_LATE = "LATE"
OUTCOME_STRONG = "STRONG"
OUTCOME_NORMAL = "NORMAL"

VALID_OUTCOMES: tuple[str, ...] = (
    OUTCOME_ABSENT,
    OUTCOME_EARLY,
    OUTCOME_LATE,
    OUTCOME_STRONG,
    OUTCOME_NORMAL,
)


def _nearest_rank_percentile(ordered: list[Decimal], p: Decimal) -> Decimal:
    n = len(ordered)
    rank = max(1, min(n, math.ceil(float(p) * n)))
    return ordered[rank - 1]


def expected_confirmation_window(historical_lag_seconds: list[Decimal]) -> tuple[Decimal, Decimal]:
    """The [p10, p90] nearest-rank percentile band of a (leader, follower)
    edge's own historical lag_seconds distribution -- the "expected
    confirmation window" MASTER_SPEC.md's PHASE 8 build list names as its
    own deliverable, independent of the classification that consumes it.
    Requires at least one historical observation; callers must exclude
    entries with no prior history (point-in-time discipline: only lags
    from leader entries strictly before the one being classified may be
    used as that entry's own baseline)."""
    if not historical_lag_seconds:
        raise ValueError("historical_lag_seconds must be non-empty")
    ordered = sorted(historical_lag_seconds)
    low = _nearest_rank_percentile(ordered, Decimal("0.10"))
    high = _nearest_rank_percentile(ordered, Decimal("0.90"))
    return low, high


@dataclass(frozen=True)
class ConfirmationClassification:
    outcome: str
    follower_entered_at: datetime | None
    lag_seconds: Decimal | None
    expected_window_low_seconds: Decimal
    expected_window_high_seconds: Decimal


def classify_confirmation(
    *,
    leader_entered_at: datetime,
    follower_entered_at: datetime | None,
    expected_window_low_seconds: Decimal,
    expected_window_high_seconds: Decimal,
    is_strong: bool,
) -> ConfirmationClassification:
    """``follower_entered_at`` must already be restricted by the caller to
    a qualifying entry within the edge's own ``max_lag`` window (the same
    window Phase 7 used to build the underlying observations) -- ``None``
    means no qualifying entry exists at all, i.e. ``ABSENT``.

    Precedence when more than one label could apply: ABSENT (no
    confirmation at all) > STRONG (an unusually high independent-actor
    convergence, a magnitude signal independent of timing) > EARLY/LATE
    (outside the edge's own empirical [p10, p90] historical lag band) >
    NORMAL (within it). MASTER_SPEC.md does not itself specify how these
    labels compose when more than one could apply -- this precedence is a
    disclosed, deterministic policy choice, not an ambiguity left
    unresolved."""
    if follower_entered_at is None:
        return ConfirmationClassification(
            outcome=OUTCOME_ABSENT,
            follower_entered_at=None,
            lag_seconds=None,
            expected_window_low_seconds=expected_window_low_seconds,
            expected_window_high_seconds=expected_window_high_seconds,
        )
    lag_seconds = Decimal(str((follower_entered_at - leader_entered_at).total_seconds()))
    if is_strong:
        outcome = OUTCOME_STRONG
    elif lag_seconds < expected_window_low_seconds:
        outcome = OUTCOME_EARLY
    elif lag_seconds > expected_window_high_seconds:
        outcome = OUTCOME_LATE
    else:
        outcome = OUTCOME_NORMAL
    return ConfirmationClassification(
        outcome=outcome,
        follower_entered_at=follower_entered_at,
        lag_seconds=lag_seconds,
        expected_window_low_seconds=expected_window_low_seconds,
        expected_window_high_seconds=expected_window_high_seconds,
    )
