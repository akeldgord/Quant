"""argus.convergence.outcome_comparison -- FSR-06 (final spec recovery):
Phase 8's missing required outcome-comparison layer (MASTER_SPEC.md
section 59/60's own required report unit list: "outcome comparisons for
ordinary overlap, high-surprisal overlap, rapid confirmation and failed
confirmation"). Pure statistics only -- see ``argus.convergence.loaders``
for the async evidence loader that builds this module's inputs from real
persisted Phase 5 executable-return and mark-return evidence.

Never collapses these four classes into a single 0-100 score (FSR-06's
own explicit prohibition, echoing section 59's "no 0-100 score" rule for
convergence surprise itself): each class keeps its own sample/eligible
counts, mean/median executable return, win rate, and no-route/unsellable/
missing-outcome rate, with the mark-return summary reported separately
and only for descriptive use (section 47/48's own "mark return is
descriptive, never a substitute for an executable outcome" rule).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from argus.copyability.executable_returns import ExecutableReturnResult

CLASS_ORDINARY_OVERLAP: Final[str] = "ORDINARY_OVERLAP"
CLASS_HIGH_SURPRISAL_OVERLAP: Final[str] = "HIGH_SURPRISAL_OVERLAP"
CLASS_RAPID_CONFIRMATION: Final[str] = "RAPID_CONFIRMATION"
CLASS_FAILED_CONFIRMATION: Final[str] = "FAILED_CONFIRMATION"

OUTCOME_COMPARISON_CLASSES: Final[tuple[str, ...]] = (
    CLASS_ORDINARY_OVERLAP,
    CLASS_HIGH_SURPRISAL_OVERLAP,
    CLASS_RAPID_CONFIRMATION,
    CLASS_FAILED_CONFIRMATION,
)


@dataclass(frozen=True)
class ExecutableOutcomeStats:
    """One class's aggregate executable-outcome evidence, at minimum the
    fields FSR-06 itself requires. ``eligible_count`` is every member
    with a known-by-cutoff 5m reverse-executable probe result, whatever
    its status; ``sample_count`` is the subset that actually resolved to
    a usable SUCCESS return (the only rows the mean/median/win rate are
    computed from). When ``insufficient_executable_sample`` is True every
    other numeric field is ``None`` -- never a mark-return substitute."""

    member_count: int
    eligible_count: int
    sample_count: int
    mean_return_pct: Decimal | None
    median_return_pct: Decimal | None
    win_rate: Decimal | None
    no_route_unsellable_missing_rate: Decimal | None
    insufficient_executable_sample: bool


@dataclass(frozen=True)
class MarkReturnSummary:
    """Descriptive-only mark-return evidence (section 47/48) -- never
    substituted for ``ExecutableOutcomeStats`` and never used to decide
    ``insufficient_executable_sample``."""

    sample_count: int
    mean_return_pct: Decimal | None


@dataclass(frozen=True)
class OutcomeComparisonResult:
    class_name: str
    executable: ExecutableOutcomeStats
    mark: MarkReturnSummary


def compute_executable_outcome_stats(
    outcomes: list[ExecutableReturnResult | None],
) -> ExecutableOutcomeStats:
    """``outcomes`` has one entry per class member, in any order -- ``None``
    means no matching opportunity or no 5m reverse-executable probe at
    all for that member (never dropped from ``member_count``, since a
    member without evidence is still real, honestly-uncovered evidence
    about this class)."""
    member_count = len(outcomes)
    eligible = [o for o in outcomes if o is not None]
    eligible_count = len(eligible)
    if eligible_count == 0:
        return ExecutableOutcomeStats(
            member_count=member_count,
            eligible_count=0,
            sample_count=0,
            mean_return_pct=None,
            median_return_pct=None,
            win_rate=None,
            no_route_unsellable_missing_rate=None,
            insufficient_executable_sample=True,
        )

    successful_returns = sorted(
        o.gross_return_pct
        for o in eligible
        if o.status == "SUCCESS" and o.gross_return_pct is not None
    )
    sample_count = len(successful_returns)
    no_route_rate = Decimal(eligible_count - sample_count) / Decimal(eligible_count)
    if sample_count == 0:
        return ExecutableOutcomeStats(
            member_count=member_count,
            eligible_count=eligible_count,
            sample_count=0,
            mean_return_pct=None,
            median_return_pct=None,
            win_rate=None,
            no_route_unsellable_missing_rate=no_route_rate,
            insufficient_executable_sample=False,
        )

    mean_return = sum(successful_returns, Decimal(0)) / Decimal(sample_count)
    median_return = statistics.median(successful_returns)
    win_rate = Decimal(sum(1 for r in successful_returns if r > 0)) / Decimal(sample_count)
    return ExecutableOutcomeStats(
        member_count=member_count,
        eligible_count=eligible_count,
        sample_count=sample_count,
        mean_return_pct=mean_return,
        median_return_pct=median_return,
        win_rate=win_rate,
        no_route_unsellable_missing_rate=no_route_rate,
        insufficient_executable_sample=False,
    )


def compute_mark_return_summary(mark_returns: list[Decimal | None]) -> MarkReturnSummary:
    """``mark_returns`` has one entry per class member (``None`` = no
    RECORDED mark outcome known by cutoff for that member)."""
    values = [v for v in mark_returns if v is not None]
    if not values:
        return MarkReturnSummary(sample_count=0, mean_return_pct=None)
    mean_return = sum(values, Decimal(0)) / Decimal(len(values))
    return MarkReturnSummary(sample_count=len(values), mean_return_pct=mean_return)
