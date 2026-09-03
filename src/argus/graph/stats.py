"""argus.graph.stats — MASTER_SPEC.md Phase 7 (ALPHA ANCESTRY): base-rate
correction, effect sizes, and multiple-comparison correction.

Pure statistics, no I/O. An exact binomial upper-tail p-value is used for
small samples (``math.comb`` is exact); a normal approximation with
continuity correction is used above ``_EXACT_N_LIMIT`` to avoid an
extremely large binomial-coefficient sum. Benjamini-Hochberg controls the
false-discovery rate across every candidate directional pair tested in one
run -- never a single-pair p-value used alone to claim significance
across a large search space (this is the "no unsupported causal claims"
rule's own statistical teeth: many candidate pairs are tested, so the
naive per-pair p-value understates the true false-positive rate unless
corrected).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

_EXACT_N_LIMIT = 300


def _to_float(value: Decimal) -> float:
    return float(value)


def binomial_upper_tail_p_value(*, k: int, n: int, p: Decimal) -> Decimal:
    """P(X >= k) for X ~ Binomial(n, p). Exact via ``math.comb`` for
    n <= 300; a normal approximation with continuity correction above
    that, since summing binomial coefficients for very large n is both
    slow and numerically unstable. ``p`` must be in [0, 1]; ``k`` may
    exceed ``n`` (returns 0) or be <= 0 (returns 1)."""
    if n < 0:
        raise ValueError("n must be non-negative")
    p_f = _to_float(p)
    if not (0.0 <= p_f <= 1.0):
        raise ValueError("p must be in [0, 1]")
    if k <= 0:
        return Decimal(1)
    if k > n:
        return Decimal(0)
    if n <= _EXACT_N_LIMIT:
        if p_f <= 0.0:
            return Decimal(0)
        if p_f >= 1.0:
            return Decimal(1)
        total = 0.0
        for i in range(k, n + 1):
            total += math.comb(n, i) * (p_f**i) * ((1 - p_f) ** (n - i))
        return Decimal(str(min(max(total, 0.0), 1.0)))

    mean = n * p_f
    variance = n * p_f * (1 - p_f)
    if variance <= 0.0:
        return Decimal(1) if mean >= k else Decimal(0)
    stddev = math.sqrt(variance)
    z = (k - 0.5 - mean) / stddev
    p_value = 0.5 * math.erfc(z / math.sqrt(2))
    return Decimal(str(min(max(p_value, 0.0), 1.0)))


def effect_size_z(*, observed: int, expected: Decimal, variance: Decimal) -> Decimal | None:
    """Standardized effect size (observed - expected) / sqrt(variance).
    ``None`` when variance is non-positive (zero-variance null model --
    no meaningful standardization is possible, never a fabricated
    infinite/zero result)."""
    variance_f = _to_float(variance)
    if variance_f <= 0.0:
        return None
    z = (float(observed) - _to_float(expected)) / math.sqrt(variance_f)
    return Decimal(str(z))


@dataclass(frozen=True)
class BHResult:
    """One entry's Benjamini-Hochberg-corrected q-value, alongside its
    original p-value and rank, in the CALLER's original input order."""

    p_value: Decimal
    q_value: Decimal


def benjamini_hochberg(p_values: list[Decimal]) -> list[BHResult]:
    """Benjamini-Hochberg false-discovery-rate correction. Returns one
    :class:`BHResult` per input p-value, in the SAME order as the input
    list (never resorted out from under the caller) -- q-values are
    monotonically enforced (a q-value can never be smaller than a
    higher-ranked p-value's own corrected value, the standard BH
    step-up guarantee)."""
    m = len(p_values)
    if m == 0:
        return []
    sorted_indices = sorted(range(m), key=lambda i: p_values[i])
    q_by_sorted_pos: list[Decimal] = [Decimal(0)] * m
    running_min = Decimal(1)
    for rank in range(m, 0, -1):
        sorted_pos = rank - 1
        original_index = sorted_indices[sorted_pos]
        candidate = p_values[original_index] * m / rank
        running_min = min(running_min, candidate)
        q_by_sorted_pos[sorted_pos] = min(running_min, Decimal(1))
    results: list[BHResult | None] = [None] * m
    for sorted_pos, original_index in enumerate(sorted_indices):
        results[original_index] = BHResult(
            p_value=p_values[original_index], q_value=q_by_sorted_pos[sorted_pos]
        )
    return [r for r in results if r is not None]
