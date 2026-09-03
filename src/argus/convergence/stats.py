"""argus.convergence.stats -- MASTER_SPEC.md Phase 8 (CONVERGENCE +
NEGATIVE EVIDENCE), section 59 (CONVERGENCE SURPRISE): non-parametric
empirical overlap probability and surprisal.

Rather than assuming a parametric distribution for how many independent
actors converge on a token by chance, this derives ``expected_overlap``
and ``empirical_probability`` directly from prior episodes' own observed
independent-actor counts -- MASTER_SPEC's own "empirical overlap
probabilities" term (plural: built from data, not assumed). Never
converts to a 0-100 score (section 59's own explicit prohibition until
calibration is defined) -- ``calibration_confidence`` is a disclosed
sample-size bucket instead.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

CALIBRATION_INSUFFICIENT_SAMPLE: Final[str] = "INSUFFICIENT_SAMPLE"
CALIBRATION_LOW: Final[str] = "LOW"
CALIBRATION_MEDIUM: Final[str] = "MEDIUM"
CALIBRATION_HIGH: Final[str] = "HIGH"

# Disclosed sample-size thresholds -- policy constants, not derived from
# any statistical optimality criterion, in the same spirit as
# argus.wallets.clustering's own named penalty constants.
_INSUFFICIENT_THRESHOLD: Final[int] = 10
_LOW_THRESHOLD: Final[int] = 30
_MEDIUM_THRESHOLD: Final[int] = 100


def calibration_confidence(sample_size: int) -> str:
    if sample_size < _INSUFFICIENT_THRESHOLD:
        return CALIBRATION_INSUFFICIENT_SAMPLE
    if sample_size < _LOW_THRESHOLD:
        return CALIBRATION_LOW
    if sample_size < _MEDIUM_THRESHOLD:
        return CALIBRATION_MEDIUM
    return CALIBRATION_HIGH


@dataclass(frozen=True)
class OverlapSurpriseResult:
    expected_overlap: Decimal
    empirical_probability: Decimal
    surprisal: Decimal
    sample_size: int
    calibration_confidence: str


def compute_overlap_surprise(
    observed_overlap: Decimal, historical_overlaps: list[Decimal]
) -> OverlapSurpriseResult:
    """``historical_overlaps`` must already be restricted to episodes
    known strictly before this one (point-in-time discipline, CORE-001)
    -- an empty list means no prior episodes exist yet for calibration,
    which ``calibration_confidence`` will honestly report as
    ``INSUFFICIENT_SAMPLE``.

    ``empirical_probability`` is a Laplace/add-one upper-tail estimate --
    ``(1 + count(historical >= observed)) / (1 + n)`` -- so a genuinely
    unprecedented observation never collapses probability to exactly 0
    (and surprisal to infinity); this is a standard, disclosed smoothing
    technique, not a fabricated number."""
    n = len(historical_overlaps)
    count_at_or_above = sum(1 for value in historical_overlaps if value >= observed_overlap)
    empirical_probability = Decimal(1 + count_at_or_above) / Decimal(1 + n)
    surprisal = Decimal(str(-math.log(float(empirical_probability))))
    expected_overlap = sum(historical_overlaps, Decimal(0)) / Decimal(n) if n > 0 else Decimal(0)
    return OverlapSurpriseResult(
        expected_overlap=expected_overlap,
        empirical_probability=empirical_probability,
        surprisal=surprisal,
        sample_size=n,
        calibration_confidence=calibration_confidence(n),
    )
