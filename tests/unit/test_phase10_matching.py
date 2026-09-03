"""Unit tests for argus.synthetic.matching (MASTER_SPEC.md Phase 10,
SYNTHETIC SUPER-WALLET): pure entry/exit trigger matching engine shared
by all five strategies.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from argus.synthetic.matching import TriggerEvent, match_strategy_trades

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
_CUTOFF = _NOW + timedelta(days=1)
_MAX_HOLD = timedelta(hours=6)


def _same_wallet(entry: TriggerEvent, exit_event: TriggerEvent) -> bool:
    return exit_event.wallet_id == entry.wallet_id


def _any_exit(_entry: TriggerEvent, _exit_event: TriggerEvent) -> bool:
    return True


def _entry(*, token, wallet, at, ref="e") -> TriggerEvent:
    return TriggerEvent(token_id=token, wallet_id=wallet, at=at, reference={"type": ref})


def test_simple_entry_exit_pair_matches() -> None:
    token, wallet = uuid.uuid4(), uuid.uuid4()
    entry = _entry(token=token, wallet=wallet, at=_NOW)
    exit_event = _entry(token=token, wallet=wallet, at=_NOW + timedelta(hours=1))
    result = match_strategy_trades(
        [entry],
        [exit_event],
        exit_matches=_same_wallet,
        max_concurrent_positions=10,
        max_hold_duration=_MAX_HOLD,
        cutoff=_CUTOFF,
    )
    assert len(result.trades) == 1
    assert result.trades[0].entry == entry
    assert result.trades[0].exit == exit_event


def test_no_exit_trigger_leaves_trade_unresolved() -> None:
    token, wallet = uuid.uuid4(), uuid.uuid4()
    entry = _entry(token=token, wallet=wallet, at=_NOW)
    result = match_strategy_trades(
        [entry],
        [],
        exit_matches=_same_wallet,
        max_concurrent_positions=10,
        max_hold_duration=_MAX_HOLD,
        cutoff=_CUTOFF,
    )
    assert len(result.trades) == 1
    assert result.trades[0].exit is None


def test_exit_beyond_max_hold_duration_not_matched() -> None:
    token, wallet = uuid.uuid4(), uuid.uuid4()
    entry = _entry(token=token, wallet=wallet, at=_NOW)
    late_exit = _entry(token=token, wallet=wallet, at=_NOW + timedelta(hours=12))
    result = match_strategy_trades(
        [entry],
        [late_exit],
        exit_matches=_same_wallet,
        max_concurrent_positions=10,
        max_hold_duration=_MAX_HOLD,
        cutoff=_CUTOFF,
    )
    assert result.trades[0].exit is None


def test_second_entry_on_same_token_blocked_while_open() -> None:
    token = uuid.uuid4()
    wallet_a, wallet_b = uuid.uuid4(), uuid.uuid4()
    entry_a = _entry(token=token, wallet=wallet_a, at=_NOW)
    entry_b = _entry(token=token, wallet=wallet_b, at=_NOW + timedelta(minutes=10))
    result = match_strategy_trades(
        [entry_a, entry_b],
        [],
        exit_matches=_same_wallet,
        max_concurrent_positions=10,
        max_hold_duration=_MAX_HOLD,
        cutoff=_CUTOFF,
    )
    # Only entry_a opens -- entry_b is scale-in blocked (position still open).
    assert len(result.trades) == 1
    assert result.trades[0].entry == entry_a


def test_reentry_allowed_after_position_closes() -> None:
    token, wallet = uuid.uuid4(), uuid.uuid4()
    entry_1 = _entry(token=token, wallet=wallet, at=_NOW)
    exit_1 = _entry(token=token, wallet=wallet, at=_NOW + timedelta(hours=1))
    entry_2 = _entry(token=token, wallet=wallet, at=_NOW + timedelta(hours=2))
    result = match_strategy_trades(
        [entry_1, entry_2],
        [exit_1],
        exit_matches=_same_wallet,
        max_concurrent_positions=10,
        max_hold_duration=_MAX_HOLD,
        cutoff=_CUTOFF,
    )
    assert len(result.trades) == 2
    assert result.trades[0].exit == exit_1
    assert result.trades[1].exit is None


def test_global_concurrency_cap_blocks_new_entries() -> None:
    tokens = [uuid.uuid4() for _ in range(3)]
    wallet = uuid.uuid4()
    entries = [
        _entry(token=t, wallet=wallet, at=_NOW + timedelta(minutes=i)) for i, t in enumerate(tokens)
    ]
    result = match_strategy_trades(
        entries,
        [],
        exit_matches=_same_wallet,
        max_concurrent_positions=2,
        max_hold_duration=_MAX_HOLD,
        cutoff=_CUTOFF,
    )
    assert len(result.trades) == 2


def test_any_exit_matcher_ignores_wallet_identity() -> None:
    token = uuid.uuid4()
    leader, other_wallet = uuid.uuid4(), uuid.uuid4()
    entry = _entry(token=token, wallet=leader, at=_NOW)
    exit_event = _entry(token=token, wallet=other_wallet, at=_NOW + timedelta(hours=1))
    result = match_strategy_trades(
        [entry],
        [exit_event],
        exit_matches=_any_exit,
        max_concurrent_positions=10,
        max_hold_duration=_MAX_HOLD,
        cutoff=_CUTOFF,
    )
    assert result.trades[0].exit == exit_event


def test_exit_before_entry_never_matched() -> None:
    token, wallet = uuid.uuid4(), uuid.uuid4()
    entry = _entry(token=token, wallet=wallet, at=_NOW)
    earlier_exit = _entry(token=token, wallet=wallet, at=_NOW - timedelta(minutes=5))
    result = match_strategy_trades(
        [entry],
        [earlier_exit],
        exit_matches=_same_wallet,
        max_concurrent_positions=10,
        max_hold_duration=_MAX_HOLD,
        cutoff=_CUTOFF,
    )
    assert result.trades[0].exit is None
