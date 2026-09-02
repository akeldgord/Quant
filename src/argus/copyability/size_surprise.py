"""M4 (robust size surprise) — MASTER_SPEC.md section 52, Phase 5
(``argus-phase-5-001``).

Robust statistics (median + MAD) over a wallet's own last <=100 known
prior POSITIVE buy notionals in the SAME quote mint, strictly during the
90 days before the current signal -- the caller (``argus.copyability.
loaders``) is responsible for producing that already-filtered,
chronologically-ordered ``prior_sizes`` list (excluding the current buy,
any future-known row, duplicates, and any discovery-contaminating token
evidence per M7).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from argus.copyability.delay_curves import decimal_median
from argus.copyability.util import clamp

MAD_SCALE_CONSTANT = Decimal("1.4826")


@dataclass(frozen=True)
class SizeSurpriseInput:
    # Chronologically ascending (oldest first, most recent last), already
    # restricted to the same quote mint / 90-day window / current-buy and
    # future-knowledge exclusion / discovery-firewall exclusion, capped at
    # the most recent 100.
    prior_sizes: list[Decimal]
    current_size: Decimal
    # Actual point-in-time evidenced total portfolio value in units
    # compatible with prior_sizes/current_size -- never a sum of known
    # open positions treated as "total wealth" (this instruction's own
    # explicit rule). None when no such evidence exists.
    portfolio_value_at_signal: Decimal | None = None


@dataclass(frozen=True)
class SizeSurpriseResult:
    baseline_count: int
    median: Decimal | None = None
    mad: Decimal | None = None
    typical_absolute_size: Decimal | None = None
    recent_median: Decimal | None = None
    z: Decimal | None = None
    component: Decimal | None = None
    unavailable_reason: str | None = None
    portfolio_relative_size_fraction: Decimal | None = None
    portfolio_relative_unavailable_reason: str | None = None


def compute_size_surprise(
    data: SizeSurpriseInput, *, recent_window: int = 20
) -> SizeSurpriseResult:
    n = len(data.prior_sizes)
    if n == 0:
        return SizeSurpriseResult(
            baseline_count=0,
            unavailable_reason="no baseline prior-buy evidence",
            portfolio_relative_unavailable_reason=(
                "no point-in-time portfolio valuation evidence in compatible units"
                if data.portfolio_value_at_signal is None
                else None
            ),
        )

    median = decimal_median(data.prior_sizes)
    mad = decimal_median([abs(size - median) for size in data.prior_sizes])
    recent_slice = data.prior_sizes[-recent_window:]
    recent_median = decimal_median(recent_slice)

    z: Decimal | None = None
    component: Decimal | None = None
    reason: str | None = None
    if n < 5:
        reason = f"baseline sample too small for z-score (n={n} < 5)"
    elif median <= 0:
        reason = "baseline median size is non-positive"
    elif mad == 0:
        reason = "baseline MAD is zero (no dispersion to compare against)"
    else:
        z = (data.current_size - median) / (MAD_SCALE_CONSTANT * mad)
        component = clamp(Decimal(50) + Decimal(10) * z, Decimal(0), Decimal(100))

    portfolio_fraction: Decimal | None = None
    portfolio_reason: str | None = None
    if data.portfolio_value_at_signal is None:
        portfolio_reason = "no point-in-time portfolio valuation evidence in compatible units"
    elif data.portfolio_value_at_signal <= 0:
        portfolio_reason = "nonpositive portfolio valuation"
    else:
        portfolio_fraction = data.current_size / data.portfolio_value_at_signal

    return SizeSurpriseResult(
        baseline_count=n,
        median=median,
        mad=mad,
        typical_absolute_size=median,
        recent_median=recent_median,
        z=z,
        component=component,
        unavailable_reason=reason,
        portfolio_relative_size_fraction=portfolio_fraction,
        portfolio_relative_unavailable_reason=portfolio_reason,
    )
