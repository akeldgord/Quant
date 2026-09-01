"""Deterministic prospective (and historical) winner-milestone detection
(MASTER_SPEC.md section 32 WINNER DEFINITIONS; Phase 2 build items 9-10;
required-implementation item 6).

A token crossing a versioned winner-category multiple creates exactly one
idempotent :class:`MilestoneCrossing` per category, ever -- replaying the
same (or a superset of the same) snapshot history must never produce a
second crossing for a category already found, and an out-of-order,
duplicate, or lower-confidence later snapshot must never revise an
already-recorded baseline/peak. The pure function here
(:func:`compute_new_milestone_crossings`) takes plain, already-fetched
snapshot data and the set of categories already recorded, and returns
only genuinely NEW crossings -- callers (``argus.wallets.watcher_service``)
own turning those into persisted, idempotent DB rows via the
``ON CONFLICT DO NOTHING`` pattern the rest of Phase 2 uses, so a race
between two workers evaluating the same token can never double-insert
(the DB's own unique constraint is the final authority, not this
function).

Winner categories are research labels only -- nothing in this module may
create a trade intent, order, quote, or execution side effect (this
instruction's explicit prohibition).
"""

from __future__ import annotations

import dataclasses
import hashlib
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Final

from argus.domain.token_market_snapshots import (
    MARKET_STATE_CONFIDENCE_HIGH,
    MARKET_STATE_CONFIDENCE_MEDIUM,
)
from argus.domain.token_winner_milestones import WINNER_CATEGORIES, WINNER_CATEGORY_THRESHOLDS

ALGORITHM_VERSION: Final[str] = "winner_watcher_v2"
BUILD_HASH: Final[str] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

WINNER_DEFINITION_VERSION: Final[str] = "winner_definition_v2"

# P2-R4: a winner-milestone decision may only rest on an observation this
# project itself has already rated reliably tradable. LOW, UNKNOWN, and
# NULL confidence are all excluded from baseline/peak selection -- an
# uncertain or unrated observation must never be treated as evidence a
# token genuinely reached (or started from) a given price, however large
# the resulting multiple would look.
_RELIABLY_TRADABLE_CONFIDENCE_LEVELS: Final[frozenset[str]] = frozenset(
    {MARKET_STATE_CONFIDENCE_HIGH, MARKET_STATE_CONFIDENCE_MEDIUM}
)


@dataclasses.dataclass(frozen=True, slots=True)
class SnapshotView:
    """The minimal, DB-agnostic view of one ``token_market_snapshots`` row
    this module needs -- kept separate from the ORM model so the pure
    detection logic below never needs a database to be unit tested."""

    snapshot_id: uuid.UUID
    observed_at: datetime
    price_usd: Decimal | None
    liquidity_usd: Decimal | None
    market_state_confidence: str | None


@dataclasses.dataclass(frozen=True, slots=True)
class MilestoneCrossing:
    token_id: uuid.UUID
    category: str
    winner_definition_version: str
    baseline_timestamp: datetime
    baseline_price: Decimal
    baseline_liquidity: Decimal | None
    baseline_snapshot_id: uuid.UUID
    peak_price: Decimal
    peak_timestamp: datetime
    peak_snapshot_id: uuid.UUID
    multiple_x: Decimal
    reason_codes: str | None


def _is_reliably_tradable(snapshot: SnapshotView) -> bool:
    """P2-R4: LOW/UNKNOWN/NULL-confidence, missing-price, missing-
    liquidity, and zero-liquidity observations are never reliably
    tradable market state, regardless of what multiple they would imply
    -- excluded from both baseline and peak selection uniformly."""
    return (
        snapshot.market_state_confidence in _RELIABLY_TRADABLE_CONFIDENCE_LEVELS
        and snapshot.price_usd is not None
        and snapshot.price_usd > 0
        and snapshot.liquidity_usd is not None
        and snapshot.liquidity_usd > 0
    )


def select_baseline(snapshots: list[SnapshotView]) -> SnapshotView | None:
    """The earliest reliably tradable market state: the first
    chronological snapshot with a real, positive price AND positive
    liquidity AND HIGH/MEDIUM confidence. An untradeable zero-liquidity
    launch-instant snapshot, and any LOW/UNKNOWN/NULL-confidence
    observation, are both deliberately skipped -- never used merely to
    inflate the multiple (MASTER_SPEC.md section 32's explicit rule;
    P2-R4 extends it from "tradable" to "tradable AND reliably
    observed")."""
    ordered = sorted(snapshots, key=lambda s: s.observed_at)
    for snapshot in ordered:
        if _is_reliably_tradable(snapshot):
            return snapshot
    return None


def select_peak(snapshots: list[SnapshotView], *, at_or_after: datetime) -> SnapshotView | None:
    """The highest-price snapshot at or after the baseline, restricted to
    the same reliably-tradable observations the baseline itself requires
    (P2-R4) -- a LOW/UNKNOWN/NULL-confidence spike must never be reported
    as the peak. Ties broken by earliest ``observed_at`` (stable,
    deterministic: the peak is "first time this price was reached," not
    an arbitrary later repeat)."""
    candidates = [s for s in snapshots if s.observed_at >= at_or_after and _is_reliably_tradable(s)]
    if not candidates:
        return None
    return max(candidates, key=lambda s: (s.price_usd, -s.observed_at.timestamp()))


def compute_new_milestone_crossings(
    *,
    token_id: uuid.UUID,
    snapshots: list[SnapshotView],
    already_recorded_categories: frozenset[str],
    winner_definition_version: str = WINNER_DEFINITION_VERSION,
) -> list[MilestoneCrossing]:
    """Every category from :data:`argus.domain.token_winner_milestones.
    WINNER_CATEGORIES` genuinely crossed by this snapshot history that is
    NOT already in ``already_recorded_categories`` -- deterministic,
    order-independent (the caller may pass snapshots in any order; this
    function sorts internally), and safe to call repeatedly as new
    snapshots arrive (idempotent: a category once returned and persisted
    is simply skipped on every future call via
    ``already_recorded_categories``)."""
    baseline = select_baseline(snapshots)
    if baseline is None:
        return []
    peak = select_peak(snapshots, at_or_after=baseline.observed_at)
    if peak is None or peak.price_usd is None or baseline.price_usd is None:
        return []
    baseline_price = baseline.price_usd
    peak_price = peak.price_usd

    multiple_x = (peak_price / baseline_price).quantize(Decimal("0.000001"))

    crossings: list[MilestoneCrossing] = []
    for category in WINNER_CATEGORIES:
        if category in already_recorded_categories:
            continue
        threshold = WINNER_CATEGORY_THRESHOLDS[category]
        if multiple_x < threshold:
            continue
        crossings.append(
            MilestoneCrossing(
                token_id=token_id,
                category=category,
                winner_definition_version=winner_definition_version,
                baseline_timestamp=baseline.observed_at,
                baseline_price=baseline_price,
                baseline_liquidity=baseline.liquidity_usd,
                baseline_snapshot_id=baseline.snapshot_id,
                peak_price=peak_price,
                peak_timestamp=peak.observed_at,
                peak_snapshot_id=peak.snapshot_id,
                multiple_x=multiple_x,
                reason_codes=(
                    ",".join(
                        code
                        for code, present in (
                            (
                                "ZERO_LIQUIDITY_SNAPSHOTS_EXCLUDED_FROM_BASELINE",
                                any(
                                    s.observed_at < baseline.observed_at
                                    and (s.liquidity_usd is None or s.liquidity_usd == 0)
                                    for s in snapshots
                                ),
                            ),
                            (
                                "LOW_CONFIDENCE_SNAPSHOTS_EXCLUDED",
                                any(
                                    s.market_state_confidence
                                    not in _RELIABLY_TRADABLE_CONFIDENCE_LEVELS
                                    for s in snapshots
                                ),
                            ),
                        )
                        if present
                    )
                    or None
                ),
            )
        )
    return crossings
