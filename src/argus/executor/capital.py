"""argus.executor.capital — MASTER_SPEC.md section 74 (DEFAULT CAPITAL
CONFIGURATION), Phase 6 (``argus-phase-6-001``).

Repository defaults are exactly zero and hardcoded here -- never read
from config/env/database -- so no live trade can occur from default
configuration regardless of what any config file says. Only an
explicitly validated external arm file (``argus.executor.arm``) can
ever raise these for one decision; this module itself never changes.
"""

from __future__ import annotations

import enum
from decimal import Decimal
from typing import Final

LIVE_MAX_SINGLE_TRADE_SOL: Final[Decimal] = Decimal(0)
LIVE_MAX_TOTAL_EXPOSURE_SOL: Final[Decimal] = Decimal(0)
LIVE_MAX_DAILY_LOSS_SOL: Final[Decimal] = Decimal(0)


class RiskMultiplier(enum.Enum):
    """MASTER_SPEC.md section 74's staged risk multipliers. The
    underlying NORMAL notional remains operator-defined -- this module
    never invents one."""

    MICRO = Decimal("0.10")
    QUARTER = Decimal("0.25")
    HALF = Decimal("0.50")
    NORMAL = Decimal("1.00")


def scaled_notional(normal_notional: Decimal, multiplier: RiskMultiplier) -> Decimal:
    return normal_notional * multiplier.value
