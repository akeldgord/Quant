"""Shared horizon-label <-> duration mapping for reverse-executable and
mark-outcome probes (MASTER_SPEC.md section 47)."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

_HORIZON_SECONDS: Final[dict[str, int]] = {
    "5m": 300,
    "30m": 1_800,
    "1h": 3_600,
    "6h": 21_600,
    "24h": 86_400,
    "3d": 259_200,
    "7d": 604_800,
}


def horizon_to_timedelta(label: str) -> timedelta:
    try:
        return timedelta(seconds=_HORIZON_SECONDS[label])
    except KeyError as exc:
        raise ValueError(f"unrecognized horizon label {label!r}") from exc
