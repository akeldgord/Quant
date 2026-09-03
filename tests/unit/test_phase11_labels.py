"""Unit tests for argus.prediction.labels (MASTER_SPEC.md Phase 11,
PREDICT INFORMED ORDER FLOW): labeled-observation-population construction.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from argus.prediction.labels import TieredEntry, build_labeled_observations

_ELITE = frozenset({"A", "S"})
_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
_TOKEN = uuid.uuid4()
_SOURCE = uuid.uuid4()


def _entry(*, wallet_id: uuid.UUID, at: datetime, tier: str | None) -> TieredEntry:
    return TieredEntry(
        wallet_id=wallet_id, token_id=_TOKEN, entered_at=at, source_id=_SOURCE, tier_at_entry=tier
    )


def test_wallet_elite_at_own_entry_is_excluded_from_observations() -> None:
    elite_wallet = uuid.uuid4()
    entries = [_entry(wallet_id=elite_wallet, at=_NOW, tier="A")]
    observations = build_labeled_observations(
        entries, horizons=(timedelta(minutes=5),), elite_tiers=_ELITE
    )
    assert observations == []


def test_followed_within_horizon_is_labeled_true() -> None:
    follower_wallet = uuid.uuid4()
    elite_wallet = uuid.uuid4()
    entries = [
        _entry(wallet_id=follower_wallet, at=_NOW, tier=None),
        _entry(wallet_id=elite_wallet, at=_NOW + timedelta(minutes=2), tier="A"),
    ]
    observations = build_labeled_observations(
        entries, horizons=(timedelta(minutes=5),), elite_tiers=_ELITE
    )
    assert len(observations) == 1
    assert observations[0].wallet_id == follower_wallet
    assert observations[0].labels[300] is True


def test_followed_after_horizon_is_labeled_false() -> None:
    follower_wallet = uuid.uuid4()
    elite_wallet = uuid.uuid4()
    entries = [
        _entry(wallet_id=follower_wallet, at=_NOW, tier=None),
        _entry(wallet_id=elite_wallet, at=_NOW + timedelta(minutes=10), tier="A"),
    ]
    observations = build_labeled_observations(
        entries, horizons=(timedelta(minutes=5),), elite_tiers=_ELITE
    )
    assert len(observations) == 1
    assert observations[0].labels[300] is False


def test_non_elite_follower_never_produces_true_label() -> None:
    follower_wallet = uuid.uuid4()
    other_wallet = uuid.uuid4()
    entries = [
        _entry(wallet_id=follower_wallet, at=_NOW, tier=None),
        _entry(wallet_id=other_wallet, at=_NOW + timedelta(minutes=1), tier="WATCH"),
    ]
    observations = build_labeled_observations(
        entries, horizons=(timedelta(minutes=5),), elite_tiers=_ELITE
    )
    # Neither entry is excluded (WATCH is not an elite tier), so both
    # become observations -- but neither is ever followed by an ELITE
    # wallet, so both labels are honestly False.
    assert len(observations) == 2
    assert {o.labels[300] for o in observations} == {False}


def test_wallet_own_later_entry_does_not_count_as_following_itself() -> None:
    wallet_id = uuid.uuid4()
    entries = [
        _entry(wallet_id=wallet_id, at=_NOW, tier=None),
        _entry(wallet_id=wallet_id, at=_NOW + timedelta(minutes=1), tier="A"),
    ]
    observations = build_labeled_observations(
        entries, horizons=(timedelta(minutes=5),), elite_tiers=_ELITE
    )
    assert len(observations) == 1
    assert observations[0].labels[300] is False


def test_labels_computed_independently_per_horizon() -> None:
    follower_wallet = uuid.uuid4()
    elite_wallet = uuid.uuid4()
    entries = [
        _entry(wallet_id=follower_wallet, at=_NOW, tier=None),
        _entry(wallet_id=elite_wallet, at=_NOW + timedelta(minutes=10), tier="S"),
    ]
    observations = build_labeled_observations(
        entries,
        horizons=(timedelta(minutes=5), timedelta(minutes=15)),
        elite_tiers=_ELITE,
    )
    assert observations[0].labels[300] is False
    assert observations[0].labels[900] is True


def test_entry_exactly_at_horizon_boundary_counts_as_followed() -> None:
    follower_wallet = uuid.uuid4()
    elite_wallet = uuid.uuid4()
    entries = [
        _entry(wallet_id=follower_wallet, at=_NOW, tier=None),
        _entry(wallet_id=elite_wallet, at=_NOW + timedelta(minutes=5), tier="A"),
    ]
    observations = build_labeled_observations(
        entries, horizons=(timedelta(minutes=5),), elite_tiers=_ELITE
    )
    assert observations[0].labels[300] is True


def test_entry_at_same_instant_as_own_entry_does_not_count() -> None:
    follower_wallet = uuid.uuid4()
    elite_wallet = uuid.uuid4()
    entries = [
        _entry(wallet_id=follower_wallet, at=_NOW, tier=None),
        _entry(wallet_id=elite_wallet, at=_NOW, tier="A"),
    ]
    observations = build_labeled_observations(
        entries, horizons=(timedelta(minutes=5),), elite_tiers=_ELITE
    )
    assert observations[0].labels[300] is False
