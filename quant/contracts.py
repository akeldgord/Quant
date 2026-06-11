"""Contract specifications and session definitions for the trading universe.

All session times are US/Eastern. "RTH" here means the liquid window we
allow strategies to trade, not necessarily the exchange's official pit
session. Equity indices use the cash-market RTH; GC uses the COMEX pit
window; FX futures use the London/NY overlap into the NY afternoon, which
is where 6E/6J volume concentrates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time


@dataclass(frozen=True)
class ContractSpec:
    symbol: str
    name: str
    exchange: str
    tick_size: float          # minimum price increment
    tick_value: float         # $ per tick per contract
    point_value: float        # $ per 1.0 price point per contract
    rth_start: time           # liquid session start (ET)
    rth_end: time             # liquid session end (ET)
    commission_rt: float      # round-turn commission + fees, $ per contract
    slippage_ticks: float     # assumed slippage per side, in ticks

    @property
    def slippage_cost_rt(self) -> float:
        """Round-turn slippage in dollars per contract."""
        return 2.0 * self.slippage_ticks * self.tick_value

    @property
    def cost_rt(self) -> float:
        """Total round-turn friction in dollars per contract."""
        return self.commission_rt + self.slippage_cost_rt


# Conservative cost assumptions: retail-ish commissions, 1 tick slippage per
# side on everything except thick ES (0.75) and thin RTY/6J (1.25).
SPECS: dict[str, ContractSpec] = {
    "ES": ContractSpec("ES", "E-mini S&P 500", "CME", 0.25, 12.50, 50.0,
                       time(9, 30), time(16, 0), 4.0, 0.75),
    "NQ": ContractSpec("NQ", "E-mini Nasdaq-100", "CME", 0.25, 5.00, 20.0,
                       time(9, 30), time(16, 0), 4.0, 1.0),
    "RTY": ContractSpec("RTY", "E-mini Russell 2000", "CME", 0.10, 5.00, 50.0,
                        time(9, 30), time(16, 0), 4.0, 1.25),
    "GC": ContractSpec("GC", "Gold", "COMEX", 0.10, 10.00, 100.0,
                       time(8, 20), time(13, 30), 4.5, 1.0),
    "6E": ContractSpec("6E", "Euro FX", "CME", 0.00005, 6.25, 125_000.0,
                       time(8, 0), time(15, 0), 4.0, 1.0),
    "6J": ContractSpec("6J", "Japanese Yen", "CME", 0.0000005, 6.25, 12_500_000.0,
                       time(8, 0), time(15, 0), 4.0, 1.25),
}

UNIVERSE = list(SPECS)


def get_spec(symbol: str) -> ContractSpec:
    try:
        return SPECS[symbol.upper()]
    except KeyError:
        raise KeyError(f"Unknown symbol {symbol!r}; universe is {UNIVERSE}") from None
