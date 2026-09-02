"""Loads the PRECISE, existing ``copyability_weights``/``trade_readiness_
weights`` blocks from ``config/signals_v1.yaml`` as ``Decimal`` -- the
one place Phase 5 reads those weights, so no call site can accidentally
retune or approximate them with a float literal (this instruction's own
explicit "use PRECISELY the existing weights ... no retuning" rule).
"""

from __future__ import annotations

from decimal import Decimal

from argus.config import ArgusConfig
from argus.scoring.copyability import COMPONENT_KEYS as COPYABILITY_COMPONENT_KEYS
from argus.scoring.readiness import READINESS_COMPONENT_KEYS


class MissingConfigWeightError(Exception):
    """Raised when a frozen component key has no corresponding weight in
    ``config/signals_v1.yaml`` -- never silently defaulted."""


def _load_weight_block(
    config: ArgusConfig, dotted_key: str, expected_keys: tuple[str, ...]
) -> dict[str, Decimal]:
    raw = config.get(dotted_key)
    if not isinstance(raw, dict):
        raise MissingConfigWeightError(
            f"{dotted_key!r} missing or not a mapping in effective config"
        )
    weights: dict[str, Decimal] = {}
    for key in expected_keys:
        if key not in raw:
            raise MissingConfigWeightError(f"{dotted_key}.{key} missing from effective config")
        weights[key] = Decimal(str(raw[key]))
    return weights


def load_copyability_weights(config: ArgusConfig) -> dict[str, Decimal]:
    return _load_weight_block(config, "copyability_weights", COPYABILITY_COMPONENT_KEYS)


def load_trade_readiness_weights(config: ArgusConfig) -> dict[str, Decimal]:
    return _load_weight_block(config, "trade_readiness_weights", READINESS_COMPONENT_KEYS)
