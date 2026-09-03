"""Phase 7 (ALPHA ANCESTRY): argus.graph.lead_follow -- lead/follow
observation construction, directional-edge statistics, and upstream
candidate generation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from argus.graph.lead_follow import (
    DirectionalEdgeResult,
    WalletTokenEntry,
    apply_multiple_comparison_correction,
    build_lead_follow_observations,
    compute_directional_edge,
    generate_upstream_candidates,
)

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)


def _entry(wallet: uuid.UUID, token: uuid.UUID, offset_seconds: int) -> WalletTokenEntry:
    return WalletTokenEntry(
        wallet_id=wallet,
        token_id=token,
        entered_at=_NOW + timedelta(seconds=offset_seconds),
        source_id=uuid.uuid4(),
    )


def test_two_wallets_one_token_produces_one_observation() -> None:
    wallet_a, wallet_b = uuid.uuid4(), uuid.uuid4()
    token = uuid.uuid4()
    entries = [_entry(wallet_a, token, 0), _entry(wallet_b, token, 30)]
    observations = build_lead_follow_observations(entries, max_lag=timedelta(minutes=5))
    assert len(observations) == 1
    obs = observations[0]
    assert obs.leader_wallet_id == wallet_a
    assert obs.follower_wallet_id == wallet_b
    assert obs.lag_seconds == Decimal(30)


def test_lag_beyond_max_lag_produces_no_observation() -> None:
    wallet_a, wallet_b = uuid.uuid4(), uuid.uuid4()
    token = uuid.uuid4()
    entries = [_entry(wallet_a, token, 0), _entry(wallet_b, token, 600)]
    observations = build_lead_follow_observations(entries, max_lag=timedelta(minutes=5))
    assert observations == []


def test_three_wallets_same_token_produces_three_ordered_pairs() -> None:
    wallet_a, wallet_b, wallet_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    token = uuid.uuid4()
    entries = [_entry(wallet_a, token, 0), _entry(wallet_b, token, 10), _entry(wallet_c, token, 20)]
    observations = build_lead_follow_observations(entries, max_lag=timedelta(minutes=5))
    pairs = {(o.leader_wallet_id, o.follower_wallet_id) for o in observations}
    assert pairs == {(wallet_a, wallet_b), (wallet_a, wallet_c), (wallet_b, wallet_c)}


def test_duplicate_entries_for_same_wallet_token_use_earliest_only() -> None:
    wallet_a, wallet_b = uuid.uuid4(), uuid.uuid4()
    token = uuid.uuid4()
    entries = [
        _entry(wallet_a, token, 100),  # later duplicate, should be ignored
        _entry(wallet_a, token, 0),  # earliest -- this one wins
        _entry(wallet_b, token, 50),
    ]
    observations = build_lead_follow_observations(entries, max_lag=timedelta(minutes=5))
    assert len(observations) == 1
    assert observations[0].lag_seconds == Decimal(50)


def test_different_tokens_do_not_produce_cross_token_observations() -> None:
    wallet_a, wallet_b = uuid.uuid4(), uuid.uuid4()
    token_1, token_2 = uuid.uuid4(), uuid.uuid4()
    entries = [_entry(wallet_a, token_1, 0), _entry(wallet_b, token_2, 10)]
    observations = build_lead_follow_observations(entries, max_lag=timedelta(minutes=5))
    assert observations == []


def test_single_wallet_no_pairs() -> None:
    wallet_a = uuid.uuid4()
    token = uuid.uuid4()
    entries = [_entry(wallet_a, token, 0)]
    assert build_lead_follow_observations(entries, max_lag=timedelta(minutes=5)) == []


def test_compute_directional_edge_lift_and_p_value() -> None:
    leader, follower = uuid.uuid4(), uuid.uuid4()
    token = uuid.uuid4()
    observations = [
        build_lead_follow_observations(
            [_entry(leader, token, 0), _entry(follower, token, 10)], max_lag=timedelta(minutes=5)
        )[0]
    ]
    result = compute_directional_edge(
        leader_wallet_id=leader,
        follower_wallet_id=follower,
        observations=observations,
        tokens_leader_entered=10,
        follower_base_rate=Decimal("0.05"),
    )
    assert result.observation_count == 1
    assert result.expected_follows == Decimal("0.5")
    assert result.lift == Decimal(2)
    assert result.median_lag_seconds == Decimal(10)
    assert Decimal(0) <= result.p_value <= Decimal(1)


def test_compute_directional_edge_zero_expected_gives_none_lift() -> None:
    leader, follower = uuid.uuid4(), uuid.uuid4()
    result = compute_directional_edge(
        leader_wallet_id=leader,
        follower_wallet_id=follower,
        observations=[],
        tokens_leader_entered=0,
        follower_base_rate=Decimal("0.05"),
    )
    assert result.lift is None
    assert result.expected_follows == Decimal(0)


def _edge(
    leader: uuid.UUID,
    follower: uuid.UUID,
    *,
    observation_count: int,
    lift: Decimal | None,
    p_value: Decimal,
    effect_size: Decimal | None = Decimal(1),
) -> DirectionalEdgeResult:
    return DirectionalEdgeResult(
        leader_wallet_id=leader,
        follower_wallet_id=follower,
        observation_count=observation_count,
        tokens_leader_entered=10,
        follower_base_rate=Decimal("0.1"),
        median_lag_seconds=Decimal(30),
        expected_follows=Decimal(1),
        lift=lift,
        effect_size=effect_size,
        p_value=p_value,
    )


def test_apply_multiple_comparison_correction_preserves_edge_order() -> None:
    leader, follower = uuid.uuid4(), uuid.uuid4()
    edges = [
        _edge(leader, follower, observation_count=5, lift=Decimal(2), p_value=Decimal("0.01")),
        _edge(leader, follower, observation_count=1, lift=Decimal(1), p_value=Decimal("0.5")),
    ]
    results = apply_multiple_comparison_correction(edges)
    assert [r.edge for r in results] == edges
    assert results[0].q_value <= results[1].q_value


def test_generate_upstream_candidates_filters_by_threshold_and_lift() -> None:
    follower = uuid.uuid4()
    strong_leader = uuid.uuid4()
    weak_leader = uuid.uuid4()
    negative_leader = uuid.uuid4()
    other_follower_edge = uuid.uuid4()

    edges = apply_multiple_comparison_correction(
        [
            _edge(
                strong_leader,
                follower,
                observation_count=8,
                lift=Decimal(3),
                p_value=Decimal("0.001"),
                effect_size=Decimal(5),
            ),
            _edge(
                weak_leader,
                follower,
                observation_count=8,
                lift=Decimal("1.01"),
                p_value=Decimal("0.6"),
                effect_size=Decimal("0.1"),
            ),
            _edge(
                negative_leader,
                follower,
                observation_count=8,
                lift=Decimal("0.5"),
                p_value=Decimal("0.9"),
                effect_size=Decimal(-1),
            ),
            _edge(
                strong_leader,
                other_follower_edge,
                observation_count=8,
                lift=Decimal(3),
                p_value=Decimal("0.001"),
                effect_size=Decimal(5),
            ),
        ]
    )
    candidates = generate_upstream_candidates(
        edges,
        follower_wallet_id=follower,
        q_value_threshold=Decimal("0.05"),
        min_observations=5,
    )
    assert len(candidates) == 1
    assert candidates[0].edge.leader_wallet_id == strong_leader


def test_generate_upstream_candidates_sorted_by_effect_size_descending() -> None:
    follower = uuid.uuid4()
    leader_high = uuid.uuid4()
    leader_low = uuid.uuid4()
    edges = apply_multiple_comparison_correction(
        [
            _edge(
                leader_low,
                follower,
                observation_count=6,
                lift=Decimal(2),
                p_value=Decimal("0.01"),
                effect_size=Decimal(2),
            ),
            _edge(
                leader_high,
                follower,
                observation_count=6,
                lift=Decimal(2),
                p_value=Decimal("0.001"),
                effect_size=Decimal(9),
            ),
        ]
    )
    candidates = generate_upstream_candidates(
        edges, follower_wallet_id=follower, q_value_threshold=Decimal("0.1"), min_observations=5
    )
    assert [c.edge.leader_wallet_id for c in candidates] == [leader_high, leader_low]


def test_generate_upstream_candidates_respects_min_observations() -> None:
    follower = uuid.uuid4()
    leader = uuid.uuid4()
    edges = apply_multiple_comparison_correction(
        [
            _edge(
                leader,
                follower,
                observation_count=2,
                lift=Decimal(5),
                p_value=Decimal("0.001"),
                effect_size=Decimal(9),
            )
        ]
    )
    candidates = generate_upstream_candidates(
        edges, follower_wallet_id=follower, q_value_threshold=Decimal("0.1"), min_observations=5
    )
    assert candidates == []
