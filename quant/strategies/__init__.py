from .orb import opening_range_breakout
from .vwap_reversion import vwap_reversion
from .momentum import trend_pullback

STRATEGIES = {
    "orb": opening_range_breakout,
    "vwap_reversion": vwap_reversion,
    "trend_pullback": trend_pullback,
}

__all__ = ["opening_range_breakout", "vwap_reversion", "trend_pullback", "STRATEGIES"]
