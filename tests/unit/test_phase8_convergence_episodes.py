"""Unit tests for argus.convergence.episodes (MASTER_SPEC.md Phase 8,
section 59 CONVERGENCE SURPRISE): grouping same-token wallet entries into
convergence episodes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from argus.convergence.episodes import build_convergence_episodes
from argus.graph.lead_follow import WalletTokenEntry

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)


def _entry(*, wallet: uuid.UUID, token: uuid.UUID, offset_seconds: int) -> WalletTokenEntry:
    return WalletTokenEntry(
        wallet_id=wallet,
        token_id=token,
        entered_at=_NOW + timedelta(seconds=offset_seconds),
        source_id=uuid.uuid4(),
    )


def test_single_token_single_wallet_forms_one_member_episode() -> None:
    token = uuid.uuid4()
    wallet = uuid.uuid4()
    episodes = build_convergence_episodes(
        [_entry(wallet=wallet, token=token, offset_seconds=0)], window=timedelta(minutes=30)
    )
    assert len(episodes) == 1
    assert episodes[0].token_id == token
    assert episodes[0].raw_wallet_count == 1
    assert episodes[0].window_start == _NOW
    assert episodes[0].window_end == _NOW + timedelta(minutes=30)


def test_entries_within_window_join_same_episode() -> None:
    token = uuid.uuid4()
    wallets = [uuid.uuid4() for _ in range(3)]
    entries = [
        _entry(wallet=wallets[0], token=token, offset_seconds=0),
        _entry(wallet=wallets[1], token=token, offset_seconds=60),
        _entry(wallet=wallets[2], token=token, offset_seconds=120),
    ]
    episodes = build_convergence_episodes(entries, window=timedelta(minutes=30))
    assert len(episodes) == 1
    assert episodes[0].raw_wallet_count == 3


def test_entry_after_window_excluded_from_episode() -> None:
    token = uuid.uuid4()
    wallets = [uuid.uuid4() for _ in range(2)]
    entries = [
        _entry(wallet=wallets[0], token=token, offset_seconds=0),
        _entry(wallet=wallets[1], token=token, offset_seconds=3600),
    ]
    episodes = build_convergence_episodes(entries, window=timedelta(minutes=30))
    assert len(episodes) == 1
    assert episodes[0].raw_wallet_count == 1


def test_repeat_entry_by_same_wallet_deduped_to_earliest() -> None:
    token = uuid.uuid4()
    wallet = uuid.uuid4()
    entries = [
        _entry(wallet=wallet, token=token, offset_seconds=600),
        _entry(wallet=wallet, token=token, offset_seconds=0),
        _entry(wallet=wallet, token=token, offset_seconds=1200),
    ]
    episodes = build_convergence_episodes(entries, window=timedelta(minutes=30))
    assert len(episodes) == 1
    assert episodes[0].raw_wallet_count == 1
    assert episodes[0].window_start == _NOW


def test_distinct_tokens_produce_distinct_episodes() -> None:
    token_a, token_b = uuid.uuid4(), uuid.uuid4()
    wallet = uuid.uuid4()
    entries = [
        _entry(wallet=wallet, token=token_a, offset_seconds=0),
        _entry(wallet=wallet, token=token_b, offset_seconds=0),
    ]
    episodes = build_convergence_episodes(entries, window=timedelta(minutes=30))
    assert {e.token_id for e in episodes} == {token_a, token_b}


def test_empty_entries_yields_no_episodes() -> None:
    assert build_convergence_episodes([], window=timedelta(minutes=30)) == []
