"""argus.synthetic.service -- MASTER_SPEC.md Phase 10 (SYNTHETIC
SUPER-WALLET) orchestration: simulates all five prospective strategies
(A-E) from section 64 / PHASE 10's own build list, persisted
idempotently. "Shadow only unless later approved" -- this module has no
live-execution capability and never enables anything automatically
(MASTER_SPEC's own explicit instruction). This is the one place Phase
10's backtests are assembled -- ``argus synthetic report`` (the CLI
command) calls this.

Computes Phase 9's own full evidence cascade first (reusing
``argus.counterfactual.service.compute_and_persist_phase9`` unchanged --
itself cascading through Phase 8's convergence/confirmation evidence and
Phase 7's directional edges), since every one of the five strategies'
entry/exit triggers is read directly from that already-persisted
evidence -- no new signal-detection logic exists in this phase, only a
backtest engine that consumes it.

Strategy definitions (MASTER_SPEC.md PHASE 10's own A-E list, section
64's R/A/K/E pipeline):

- A: source entry -> source exit -- any tracked wallet's real buy, held
  until that SAME wallet's own sell.
- B: discovery specialist -> source exit -- Strategy A's population,
  restricted to wallets Phase 9 classified as discovery specialists.
- C: discovery -> confirmation -> source exit -- a discovery specialist's
  buy, but the entry fires only once a follower CONFIRMS it (Phase 8),
  at the follower's own confirmation time (never look-ahead to the
  leader's own earlier entry) -- held until the ORIGINAL leader's exit.
- D: discovery -> confirmation -> exit oracle -- the same confirmed-entry
  trigger as C, but exits on ANY qualifying exit specialist's sell of
  that token (not necessarily the original leader).
- E: high convergence -> exit convergence -- entry triggered by an
  unusually surprising Phase 8 convergence episode for that token
  (anchored at the episode's own ``window_end``, never ``window_start``
  -- the full episode is not known until its window closes); exit
  triggered by a Phase 9 exit-convergence episode for that same token.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from argus.convergence.service import ALGORITHM_VERSION as PHASE8_ALGORITHM_VERSION
from argus.convergence.service import ConvergenceRunConfig as Phase8RunConfig
from argus.counterfactual.loaders import load_nearest_token_market_snapshot
from argus.counterfactual.matching import compute_forward_return
from argus.counterfactual.service import ALGORITHM_VERSION as PHASE9_ALGORITHM_VERSION
from argus.counterfactual.service import Phase9RunConfig, compute_and_persist_phase9
from argus.domain.synthetic_strategy_trades import (
    OUTCOME_FAILURE_NO_ENTRY_PRICE,
    OUTCOME_FAILURE_NO_EXIT_PRICE,
    OUTCOME_FAILURE_NO_EXIT_TRIGGER,
    OUTCOME_RESOLVED,
)
from argus.graph.service import GraphRunConfig
from argus.synthetic.costs import apply_entry_cost, apply_exit_cost
from argus.synthetic.loaders import (
    filter_entries_by_wallet,
    filter_exits_by_wallet,
    load_confirmed_discovery_entries,
    load_discovery_specialist_wallet_ids,
    load_exit_convergence_exits,
    load_exit_specialist_wallet_ids,
    load_high_convergence_entries,
    load_source_entries,
    load_source_exits,
)
from argus.synthetic.matching import MatchedTrade, MatchResult, TriggerEvent, match_strategy_trades
from argus.synthetic.persistence import (
    get_or_create_synthetic_strategy_summary,
    get_or_create_synthetic_strategy_trade,
)
from argus.synthetic.stats import StrategySummary, TradeOutcome, compute_strategy_summary

ALGORITHM_VERSION: Final[str] = "synthetic_super_wallet_v1"

_PHASE10_ARTIFACT_FILENAMES: Final[tuple[str, ...]] = (
    "costs.py",
    "matching.py",
    "stats.py",
    "loaders.py",
    "persistence.py",
    "service.py",
)


def _compute_build_hash() -> str:
    digest = hashlib.sha256()
    module_dir = Path(__file__).parent
    for filename in _PHASE10_ARTIFACT_FILENAMES:
        digest.update((module_dir / filename).read_bytes())
    return digest.hexdigest()


BUILD_HASH: Final[str] = _compute_build_hash()

STRATEGY_A = "A"
STRATEGY_B = "B"
STRATEGY_C = "C"
STRATEGY_D = "D"
STRATEGY_E = "E"
STRATEGY_CODES: Final[tuple[str, ...]] = (
    STRATEGY_A,
    STRATEGY_B,
    STRATEGY_C,
    STRATEGY_D,
    STRATEGY_E,
)

STRATEGY_DESCRIPTIONS: Final[dict[str, str]] = {
    STRATEGY_A: "source entry -> source exit",
    STRATEGY_B: "discovery specialist -> source exit",
    STRATEGY_C: "discovery -> confirmation -> source exit",
    STRATEGY_D: "discovery -> confirmation -> exit oracle",
    STRATEGY_E: "high convergence -> exit convergence",
}


@dataclass(frozen=True)
class Phase10RunConfig:
    entry_exit_price_max_staleness: timedelta
    cost_bps: Decimal
    max_concurrent_positions: int
    high_convergence_surprisal_threshold: Decimal
    min_exit_specialist_score: Decimal
    max_hold_duration: timedelta

    def config_hash(self) -> str:
        payload = (
            f"entry_exit_price_max_staleness_seconds="
            f"{self.entry_exit_price_max_staleness.total_seconds()}|"
            f"cost_bps={self.cost_bps}|"
            f"max_concurrent_positions={self.max_concurrent_positions}|"
            f"high_convergence_surprisal_threshold={self.high_convergence_surprisal_threshold}|"
            f"min_exit_specialist_score={self.min_exit_specialist_score}|"
            f"max_hold_duration_seconds={self.max_hold_duration.total_seconds()}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Phase10ComputationResult:
    as_of: datetime
    summaries: dict[str, StrategySummary] = field(default_factory=dict)


def _same_wallet_exit(entry: TriggerEvent, exit_event: TriggerEvent) -> bool:
    return exit_event.wallet_id == entry.wallet_id


def _any_exit(_entry: TriggerEvent, _exit_event: TriggerEvent) -> bool:
    return True


async def _price_and_persist_trades(
    session: AsyncSession,
    *,
    strategy_code: str,
    match_result: MatchResult,
    config: Phase10RunConfig,
    cutoff: datetime,
    algorithm_version: str,
    config_hash: str,
    computed_at: datetime,
) -> list[TradeOutcome]:
    outcomes: list[TradeOutcome] = []
    max_staleness_seconds = config.entry_exit_price_max_staleness.total_seconds()

    for ordinal, matched in enumerate(sorted(match_result.trades, key=lambda t: t.entry.at)):
        entry_snapshot = await load_nearest_token_market_snapshot(
            session,
            token_id=matched.entry.token_id,
            target=matched.entry.at,
            max_staleness_seconds=max_staleness_seconds,
        )
        if entry_snapshot is None or entry_snapshot.price_usd is None:
            await _persist(
                session,
                strategy_code=strategy_code,
                matched=matched,
                entry_price=None,
                exit_price=None,
                gross_return=None,
                net_return=None,
                outcome=OUTCOME_FAILURE_NO_ENTRY_PRICE,
                config=config,
                cutoff=cutoff,
                algorithm_version=algorithm_version,
                config_hash=config_hash,
                computed_at=computed_at,
            )
            outcomes.append(
                TradeOutcome(
                    outcome=OUTCOME_FAILURE_NO_ENTRY_PRICE, net_return=None, exit_at_ordinal=ordinal
                )
            )
            continue

        raw_entry_price = entry_snapshot.price_usd

        if matched.exit is None:
            await _persist(
                session,
                strategy_code=strategy_code,
                matched=matched,
                entry_price=raw_entry_price,
                exit_price=None,
                gross_return=None,
                net_return=None,
                outcome=OUTCOME_FAILURE_NO_EXIT_TRIGGER,
                config=config,
                cutoff=cutoff,
                algorithm_version=algorithm_version,
                config_hash=config_hash,
                computed_at=computed_at,
            )
            outcomes.append(
                TradeOutcome(
                    outcome=OUTCOME_FAILURE_NO_EXIT_TRIGGER,
                    net_return=None,
                    exit_at_ordinal=ordinal,
                )
            )
            continue

        exit_snapshot = await load_nearest_token_market_snapshot(
            session,
            token_id=matched.entry.token_id,
            target=matched.exit.at,
            max_staleness_seconds=max_staleness_seconds,
        )
        if exit_snapshot is None or exit_snapshot.price_usd is None:
            await _persist(
                session,
                strategy_code=strategy_code,
                matched=matched,
                entry_price=raw_entry_price,
                exit_price=None,
                gross_return=None,
                net_return=None,
                outcome=OUTCOME_FAILURE_NO_EXIT_PRICE,
                config=config,
                cutoff=cutoff,
                algorithm_version=algorithm_version,
                config_hash=config_hash,
                computed_at=computed_at,
            )
            outcomes.append(
                TradeOutcome(
                    outcome=OUTCOME_FAILURE_NO_EXIT_PRICE, net_return=None, exit_at_ordinal=ordinal
                )
            )
            continue

        raw_exit_price = exit_snapshot.price_usd
        effective_entry_price = apply_entry_cost(raw_entry_price, cost_bps=config.cost_bps)
        effective_exit_price = apply_exit_cost(raw_exit_price, cost_bps=config.cost_bps)
        gross_return = compute_forward_return(raw_entry_price, raw_exit_price)
        net_return = compute_forward_return(effective_entry_price, effective_exit_price)

        await _persist(
            session,
            strategy_code=strategy_code,
            matched=matched,
            entry_price=raw_entry_price,
            exit_price=raw_exit_price,
            gross_return=gross_return,
            net_return=net_return,
            outcome=OUTCOME_RESOLVED,
            config=config,
            cutoff=cutoff,
            algorithm_version=algorithm_version,
            config_hash=config_hash,
            computed_at=computed_at,
        )
        outcomes.append(
            TradeOutcome(outcome=OUTCOME_RESOLVED, net_return=net_return, exit_at_ordinal=ordinal)
        )

    return outcomes


async def _persist(
    session: AsyncSession,
    *,
    strategy_code: str,
    matched: MatchedTrade,
    entry_price: Decimal | None,
    exit_price: Decimal | None,
    gross_return: Decimal | None,
    net_return: Decimal | None,
    outcome: str,
    config: Phase10RunConfig,
    cutoff: datetime,
    algorithm_version: str,
    config_hash: str,
    computed_at: datetime,
) -> None:
    await get_or_create_synthetic_strategy_trade(
        session,
        strategy_code=strategy_code,
        matched=matched,
        entry_price_usd=entry_price,
        exit_price_usd=exit_price,
        cost_bps_applied=config.cost_bps,
        gross_return=gross_return,
        net_return=net_return,
        outcome=outcome,
        as_of=cutoff,
        algorithm_version=algorithm_version,
        config_hash=config_hash,
        now=computed_at,
    )


async def _run_and_persist_strategy(
    session: AsyncSession,
    *,
    strategy_code: str,
    entries: list[TriggerEvent],
    exits: list[TriggerEvent],
    exit_matches: Callable[[TriggerEvent, TriggerEvent], bool],
    cutoff: datetime,
    config: Phase10RunConfig,
    computed_at: datetime,
) -> StrategySummary:
    algorithm_version = ALGORITHM_VERSION
    config_hash = config.config_hash()

    match_result = match_strategy_trades(
        entries,
        exits,
        exit_matches=exit_matches,
        max_concurrent_positions=config.max_concurrent_positions,
        max_hold_duration=config.max_hold_duration,
        cutoff=cutoff,
    )
    outcomes = await _price_and_persist_trades(
        session,
        strategy_code=strategy_code,
        match_result=match_result,
        config=config,
        cutoff=cutoff,
        algorithm_version=algorithm_version,
        config_hash=config_hash,
        computed_at=computed_at,
    )
    summary = compute_strategy_summary(
        outcomes,
        concurrency_samples=match_result.concurrency_samples,
        max_concurrent_positions=config.max_concurrent_positions,
    )
    await get_or_create_synthetic_strategy_summary(
        session,
        strategy_code=strategy_code,
        trade_count=summary.trade_count,
        resolved_count=summary.resolved_count,
        failure_count=summary.failure_count,
        failure_rate=summary.failure_rate,
        win_rate=summary.win_rate,
        profit_factor=summary.profit_factor,
        max_drawdown=summary.max_drawdown,
        capital_utilization=summary.capital_utilization,
        mean_net_return=summary.mean_net_return,
        median_net_return=summary.median_net_return,
        as_of=cutoff,
        algorithm_version=algorithm_version,
        config_hash=config_hash,
        now=computed_at,
    )
    return summary


async def compute_and_persist_phase10(
    session: AsyncSession,
    *,
    cutoff: datetime,
    graph_config: GraphRunConfig,
    phase8_config: Phase8RunConfig,
    phase9_config: Phase9RunConfig,
    config: Phase10RunConfig,
    computed_at: datetime,
) -> Phase10ComputationResult:
    await compute_and_persist_phase9(
        session,
        cutoff=cutoff,
        graph_config=graph_config,
        phase8_config=phase8_config,
        config=phase9_config,
        computed_at=computed_at,
    )

    source_entries = await load_source_entries(session, cutoff=cutoff)
    source_exits = await load_source_exits(session, cutoff=cutoff)

    discovery_wallet_ids = await load_discovery_specialist_wallet_ids(
        session,
        cutoff=cutoff,
        algorithm_version=PHASE9_ALGORITHM_VERSION,
        config_hash=phase9_config.config_hash(),
    )
    discovery_entries = filter_entries_by_wallet(source_entries, discovery_wallet_ids)

    confirmed_discovery_entries = await load_confirmed_discovery_entries(
        session,
        cutoff=cutoff,
        discovery_wallet_ids=discovery_wallet_ids,
        confirmation_algorithm_version=PHASE8_ALGORITHM_VERSION,
    )

    exit_specialist_wallet_ids = await load_exit_specialist_wallet_ids(
        session,
        cutoff=cutoff,
        algorithm_version=PHASE9_ALGORITHM_VERSION,
        config_hash=phase9_config.config_hash(),
        min_exit_specialist_score=config.min_exit_specialist_score,
    )
    exit_oracle_exits = filter_exits_by_wallet(source_exits, exit_specialist_wallet_ids)

    high_convergence_entries = await load_high_convergence_entries(
        session,
        cutoff=cutoff,
        algorithm_version=PHASE8_ALGORITHM_VERSION,
        config_hash=phase8_config.config_hash(),
        surprisal_threshold=config.high_convergence_surprisal_threshold,
    )
    exit_convergence_exits = await load_exit_convergence_exits(
        session,
        cutoff=cutoff,
        algorithm_version=PHASE9_ALGORITHM_VERSION,
        config_hash=phase9_config.config_hash(),
    )

    summaries: dict[str, StrategySummary] = {}
    summaries[STRATEGY_A] = await _run_and_persist_strategy(
        session,
        strategy_code=STRATEGY_A,
        entries=source_entries,
        exits=source_exits,
        exit_matches=_same_wallet_exit,
        cutoff=cutoff,
        config=config,
        computed_at=computed_at,
    )
    summaries[STRATEGY_B] = await _run_and_persist_strategy(
        session,
        strategy_code=STRATEGY_B,
        entries=discovery_entries,
        exits=source_exits,
        exit_matches=_same_wallet_exit,
        cutoff=cutoff,
        config=config,
        computed_at=computed_at,
    )
    summaries[STRATEGY_C] = await _run_and_persist_strategy(
        session,
        strategy_code=STRATEGY_C,
        entries=confirmed_discovery_entries,
        exits=source_exits,
        exit_matches=_same_wallet_exit,
        cutoff=cutoff,
        config=config,
        computed_at=computed_at,
    )
    summaries[STRATEGY_D] = await _run_and_persist_strategy(
        session,
        strategy_code=STRATEGY_D,
        entries=confirmed_discovery_entries,
        exits=exit_oracle_exits,
        exit_matches=_any_exit,
        cutoff=cutoff,
        config=config,
        computed_at=computed_at,
    )
    summaries[STRATEGY_E] = await _run_and_persist_strategy(
        session,
        strategy_code=STRATEGY_E,
        entries=high_convergence_entries,
        exits=exit_convergence_exits,
        exit_matches=_any_exit,
        cutoff=cutoff,
        config=config,
        computed_at=computed_at,
    )

    return Phase10ComputationResult(as_of=cutoff, summaries=summaries)
