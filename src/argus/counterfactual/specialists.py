"""argus.counterfactual.specialists -- MASTER_SPEC.md Phase 9, section 62
(ENTRY AND EXIT SPECIALISTS): non-parametric percentile ranking (the
same empirical philosophy Phase 8 used for convergence surprisal, applied
here so four incommensurable score types -- a return percentage, a graph
effect size, a confirmation rate, a 0-100 skill score -- become
comparable) and dominant-specialty classification.
"""

from __future__ import annotations

from decimal import Decimal

ENTRY = "ENTRY"
DISCOVERY = "DISCOVERY"
VALIDATION = "VALIDATION"
EXIT = "EXIT"

# Alphabetical -- the disclosed, deterministic tie-break order when two or
# more specialties are equally dominant.
_SPECIALTY_ORDER: tuple[str, ...] = (DISCOVERY, ENTRY, EXIT, VALIDATION)


def percentile_rank(value: Decimal, population: list[Decimal]) -> Decimal:
    """Fraction of ``population`` (which should include ``value`` itself)
    at or below ``value`` -- higher is always better for every score type
    this module ranks. A population of one wallet ranks itself at 1.0
    (not a fabricated "beats everyone," simply -- with a sample of one,
    the wallet's own score is trivially the maximum observed)."""
    if not population:
        raise ValueError("population must be non-empty")
    at_or_below = sum(1 for v in population if v <= value)
    return Decimal(at_or_below) / Decimal(len(population))


def dominant_specialty(percentiles: dict[str, Decimal | None]) -> str | None:
    """The specialty with the highest percentile rank among those that
    are non-null; ``None`` if fewer than two specialties have a score
    (a single data point cannot meaningfully claim "dominance" over
    nothing to compare against)."""
    available = {name: value for name, value in percentiles.items() if value is not None}
    if len(available) < 2:
        return None
    best_value = max(available.values())
    best_names = [name for name in _SPECIALTY_ORDER if available.get(name) == best_value]
    return best_names[0] if best_names else None
