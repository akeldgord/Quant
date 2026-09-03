"""argus.synthetic.matching -- MASTER_SPEC.md Phase 10 (SYNTHETIC
SUPER-WALLET): pure entry/exit trigger matching engine, shared by all
five strategies (A-E). Strategy-specific behavior is expressed entirely
through the ``exit_matches`` predicate the caller supplies -- the
matching/concurrency mechanics themselves never change per strategy.

Enforces section 65's ONE OPEN POSITION PER MINT rule (reusing
``argus.executor.position_policy.evaluate_scale_in`` unchanged -- the
same pure policy function Phase 6's live executor uses, applied here to
a historical simulation instead of a live position table) and a global
concurrent-position cap (this run's own capital-utilization ceiling).

Known scale limitation (disclosed): the per-entry open-position purge is
O(open positions) per entry, so this is not optimized for very large
trigger volumes -- acceptable for a research backtest, not a claim of
production-scale performance.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from argus.executor.position_policy import evaluate_scale_in


@dataclass(frozen=True)
class TriggerEvent:
    token_id: uuid.UUID
    wallet_id: uuid.UUID | None
    at: datetime
    reference: dict


@dataclass(frozen=True)
class MatchedTrade:
    entry: TriggerEvent
    exit: TriggerEvent | None


@dataclass(frozen=True)
class MatchResult:
    trades: list[MatchedTrade]
    # Concurrent open-position count sampled immediately after each
    # successful entry -- the raw series ``capital_utilization`` (see
    # argus.synthetic.stats) is computed from.
    concurrency_samples: list[int]


def match_strategy_trades(
    entries: list[TriggerEvent],
    exits: list[TriggerEvent],
    *,
    exit_matches: Callable[[TriggerEvent, TriggerEvent], bool],
    max_concurrent_positions: int,
    max_hold_duration: timedelta,
    cutoff: datetime,
) -> MatchResult:
    exits_by_token: dict[uuid.UUID, list[TriggerEvent]] = {}
    for exit_event in exits:
        exits_by_token.setdefault(exit_event.token_id, []).append(exit_event)
    for candidates in exits_by_token.values():
        candidates.sort(key=lambda e: e.at)

    open_positions: dict[uuid.UUID, MatchedTrade] = {}
    trades: list[MatchedTrade] = []
    concurrency_samples: list[int] = []

    for entry in sorted(entries, key=lambda e: e.at):
        for token_id in [
            t
            for t, trade in open_positions.items()
            if trade.exit is not None and trade.exit.at <= entry.at
        ]:
            del open_positions[token_id]

        decision = evaluate_scale_in(
            existing_open_position_for_mint=entry.token_id in open_positions
        )
        if not decision.allowed:
            continue
        if len(open_positions) >= max_concurrent_positions:
            continue

        exit_deadline = min(cutoff, entry.at + max_hold_duration)
        candidate_exits = exits_by_token.get(entry.token_id, [])
        matched_exit = next(
            (
                candidate
                for candidate in candidate_exits
                if entry.at < candidate.at <= exit_deadline and exit_matches(entry, candidate)
            ),
            None,
        )

        trade = MatchedTrade(entry=entry, exit=matched_exit)
        open_positions[entry.token_id] = trade
        trades.append(trade)
        concurrency_samples.append(len(open_positions))

    return MatchResult(trades=trades, concurrency_samples=concurrency_samples)
