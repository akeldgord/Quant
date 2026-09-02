"""M3 (information retention/forward value) — MASTER_SPEC.md sections
50-51, Phase 5 (``argus-phase-5-001``).

Three pieces, all deterministic and observation-only (never fitted decay,
never forced monotonicity, never interpolated):

- :func:`decimal_median` / :func:`build_delay_curve` -- one MEDIAN
  executable-return-fraction cell per entry-delay target label, over a
  cohort of comparable events (same notional/quote-unit/horizon/evidence-
  class -- the caller is responsible for pre-filtering to one comparable
  cohort; this module trusts its input list is already that cohort).
- :func:`compute_half_life` -- section 50, comparing >=2 delay points on
  one comparable cohort.
- :func:`build_forward_information_grid` -- section 51's fixed nine-cell
  grid (5s/15s/30s/60s/5m/30m/1h/6h/24h from ``first_seen_at``), each cell
  measured-or-explicitly-unavailable. V1 benchmark is the explicit cash
  (zero-return) baseline -- "how much abnormal return remained" reduces to
  the raw return fraction itself; a market-adjusted/residual figure is
  Phase 9 (``PHASE_9_MATCHED_CONTROLS_UNAVAILABLE``), never computed here.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

FORWARD_INFO_HORIZON_LABELS = (
    "5s",
    "15s",
    "30s",
    "60s",
    "5m",
    "30m",
    "1h",
    "6h",
    "24h",
)

PHASE_9_MATCHED_CONTROLS_UNAVAILABLE = "PHASE_9_MATCHED_CONTROLS_UNAVAILABLE"


def decimal_median(values: list[Decimal]) -> Decimal:
    """Exact Decimal median -- never routed through float, so a computed
    peak/crossing comparison is always exact."""
    if not values:
        raise ValueError("decimal_median requires at least one value")
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


@dataclass(frozen=True)
class DelayObservation:
    """One event's realized return fraction at one entry-delay target,
    already restricted by the caller to one comparable cohort (same
    notional, quote mint, holding horizon, evidence class)."""

    event_id: str
    target_label: str
    target_seconds: int
    return_fraction: Decimal


@dataclass(frozen=True)
class DelayPoint:
    target_label: str
    target_seconds: int
    median_return_fraction: Decimal
    n: int
    event_ids: tuple[str, ...]


def build_delay_curve(observations: list[DelayObservation]) -> list[DelayPoint]:
    """Groups by ``target_label`` and takes the MEDIAN return fraction
    per group -- distinct-event counts, never probe/observation counts
    (six probes from one event is not six independent trades; the caller
    must have already reduced to at most one observation per
    (event_id, target_label))."""
    by_label: dict[str, list[DelayObservation]] = {}
    for obs in observations:
        by_label.setdefault(obs.target_label, []).append(obs)

    points: list[DelayPoint] = []
    for label, group in by_label.items():
        seconds = group[0].target_seconds
        distinct_events = {o.event_id: o for o in group}
        median = decimal_median([o.return_fraction for o in distinct_events.values()])
        points.append(
            DelayPoint(
                target_label=label,
                target_seconds=seconds,
                median_return_fraction=median,
                n=len(distinct_events),
                event_ids=tuple(sorted(distinct_events)),
            )
        )
    return sorted(points, key=lambda p: p.target_seconds)


HalfLifeOutcome = Literal[
    "PEAK_FOUND", "NO_POSITIVE_SIGNAL", "RIGHT_CENSORED", "INSUFFICIENT_COMPARABLE_EVIDENCE"
]


@dataclass(frozen=True)
class HalfLifeResult:
    outcome: HalfLifeOutcome
    peak_target_label: str | None = None
    peak_seconds: int | None = None
    peak_return_fraction: Decimal | None = None
    crossing_target_label: str | None = None
    crossing_seconds: int | None = None
    crossing_delay_from_first_seen_seconds: int | None = None
    half_life_seconds: Decimal | None = None
    reason: str | None = None


def compute_half_life(points: list[DelayPoint]) -> HalfLifeResult:
    """Section 50: no fitted decay curve, no forced monotonicity, no
    interpolation -- only comparisons between actually observed points.

    Algorithm (frozen, byte-exact to the sealed contract's worked
    examples): sort by delay; the "peak" is the earliest delay among
    those achieving the maximum POSITIVE median return fraction (ties
    broken by earliest delay); half-life is the elapsed time from the
    peak to the first LATER observed point whose median return fraction
    is <= half the peak's value (that crossing point's own absolute delay
    from first_seen_at is reported alongside the elapsed half-life)."""
    if len(points) < 2:
        return HalfLifeResult(
            outcome="INSUFFICIENT_COMPARABLE_EVIDENCE",
            reason="fewer than 2 comparable delay points in this cohort",
        )

    ordered = sorted(points, key=lambda p: p.target_seconds)
    positive = [p for p in ordered if p.median_return_fraction > 0]
    if not positive:
        return HalfLifeResult(
            outcome="NO_POSITIVE_SIGNAL",
            reason="no delay point in this cohort has a positive median return fraction",
        )

    max_value = max(p.median_return_fraction for p in positive)
    peak = min(
        (p for p in positive if p.median_return_fraction == max_value),
        key=lambda p: p.target_seconds,
    )
    half_value = peak.median_return_fraction / 2

    later_points = [p for p in ordered if p.target_seconds > peak.target_seconds]
    crossing = next((p for p in later_points if p.median_return_fraction <= half_value), None)
    if crossing is None:
        return HalfLifeResult(
            outcome="RIGHT_CENSORED",
            peak_target_label=peak.target_label,
            peak_seconds=peak.target_seconds,
            peak_return_fraction=peak.median_return_fraction,
            reason="no later observed point crossed half of the peak return",
        )

    elapsed = Decimal(crossing.target_seconds - peak.target_seconds)
    return HalfLifeResult(
        outcome="PEAK_FOUND",
        peak_target_label=peak.target_label,
        peak_seconds=peak.target_seconds,
        peak_return_fraction=peak.median_return_fraction,
        crossing_target_label=crossing.target_label,
        crossing_seconds=crossing.target_seconds,
        crossing_delay_from_first_seen_seconds=crossing.target_seconds,
        half_life_seconds=elapsed,
    )


@dataclass(frozen=True)
class ForwardInfoCell:
    """One section-51 grid cell. ``available=False`` means "no comparable
    observation at this exact horizon" -- never filled by interpolation or
    a neighboring horizon's value."""

    available: bool
    return_fraction: Decimal | None = None
    is_executable: bool = True
    reason: str | None = None


def build_forward_information_grid(cells: dict[str, ForwardInfoCell]) -> dict[str, dict]:
    """Always emits exactly the nine fixed ``FORWARD_INFO_HORIZON_LABELS``
    keys -- a horizon absent from ``cells`` is reported unavailable, never
    silently omitted or backfilled. The V1 benchmark is the explicit cash
    (zero-return) baseline, so a cell's own ``return_fraction`` already IS
    the forward-value proxy relative to it (never market-adjusted)."""
    grid: dict[str, dict] = {}
    for label in FORWARD_INFO_HORIZON_LABELS:
        cell = cells.get(label)
        if cell is None or not cell.available:
            grid[label] = {
                "available": False,
                "reason": (cell.reason if cell is not None else "no observation at this horizon"),
            }
            continue
        grid[label] = {
            "available": True,
            "return_fraction": str(cell.return_fraction)
            if cell.return_fraction is not None
            else None,
            "is_executable": cell.is_executable,
            "benchmark": "cash_zero_return_baseline",
            "matched_universe_abnormal_return": None,
            "matched_universe_status": PHASE_9_MATCHED_CONTROLS_UNAVAILABLE,
        }
    return grid
