"""argus.synthetic.costs -- MASTER_SPEC.md Phase 10 (SYNTHETIC
SUPER-WALLET): a disclosed V1 realistic-cost haircut, applied
symmetrically to both sides of a simulated trade (a buy pays slightly
above the observed price, a sell receives slightly below it) -- no
disclosed default cost assumption exists anywhere else in this project
(Phase 5's own executable-return machinery takes an ``AdditionalCost``
input but never asserts a default value), so this is a new, explicit V1
prior for this phase, in the same spirit as section 38's own "V1 priors
to be evaluated prospectively."
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

# 100 bps (1%) round-trip, split evenly across entry and exit -- a
# disclosed, deliberately conservative placeholder, not a modeled
# estimate of any specific token's real liquidity/slippage.
DEFAULT_COST_BPS: Final[Decimal] = Decimal(100)

_BPS_DIVISOR: Final[Decimal] = Decimal(10_000)


def apply_entry_cost(raw_price: Decimal, *, cost_bps: Decimal) -> Decimal:
    """A buy pays slightly ABOVE the observed price."""
    half_cost_fraction = cost_bps / Decimal(2) / _BPS_DIVISOR
    return raw_price * (Decimal(1) + half_cost_fraction)


def apply_exit_cost(raw_price: Decimal, *, cost_bps: Decimal) -> Decimal:
    """A sell receives slightly BELOW the observed price."""
    half_cost_fraction = cost_bps / Decimal(2) / _BPS_DIVISOR
    return raw_price * (Decimal(1) - half_cost_fraction)
