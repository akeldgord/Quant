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
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from argus.convergence.service import ALGORITHM_VERSION as PHASE8_ALGORITHM_VERSION
from argus.convergence.service import ConvergenceRunConfig as Phase8RunConfig
from argus.copyability.loaders import (
    PRIMARY_EXECUTABLE_HORIZON,
    WalletOpportunity,
    load_contamination_firewall,
    load_wallet_opportunities,
)
from argus.counterfactual.loaders import load_nearest_token_market_snapshot
from argus.counterfactual.matching import compute_forward_return
from argus.counterfactual.service import ALGORITHM_VERSION as PHASE9_ALGORITHM_VERSION
from argus.counterfactual.service import Phase9RunConfig, compute_and_persist_phase9
from argus.domain.synthetic_strategy_trades import (
    OUTCOME_FAILURE_EXECUTABLE_QUOTE_FAILED,
    OUTCOME_FAILURE_NO_EXECUTABLE_EVIDENCE,
    OUTCOME_FAILURE_NO_EXIT_TRIGGER,
    OUTCOME_RESOLVED,
)
from argus.graph.service import GraphRunConfig
from argus.synthetic.costs import apply_entry_cost, apply_exit_cost
from argus.synthetic.loaders import (
    filter_entries_by_decision_time_discovery_specialist,
    filter_exits_by_decision_time_exit_specialist,
    load_confirmed_entries,
    load_exit_convergence_exits,
    load_high_convergence_entries,
    load_source_entries,
    load_source_exits,
    load_specialist_scores_as_of,
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
    # FSR-08: per-strategy "no genuine executable-return evidence at all"
    # flag -- kept alongside (not inside) ``StrategySummary`` since it is
    # Phase 10's own data-provenance disclosure, not a backtest statistic
    # (``argus.synthetic.stats`` stays generic and untouched by FSR-08).
    insufficient_executable_sample: dict[str, bool] = field(default_factory=dict)


def _same_wallet_exit(entry: TriggerEvent, exit_event: TriggerEvent) -> bool:
    return exit_event.wallet_id == entry.wallet_id


def _any_exit(_entry: TriggerEvent, _exit_event: TriggerEvent) -> bool:
    return True


async def _mark_prices_and_return(
    session: AsyncSession,
    *,
    matched: MatchedTrade,
    config: Phase10RunConfig,
    max_staleness_seconds: float,
) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None]:
    """FSR-08: the OLD fixed-cost-haircut mark-price computation,
    preserved unchanged but now purely descriptive -- returns
    (mark_entry_price, mark_exit_price, mark_gross_return,
    mark_net_return), NEVER consulted for the primary executable
    ``outcome``/``gross_return``/``net_return`` fields."""
    entry_snapshot = await load_nearest_token_market_snapshot(
        session,
        token_id=matched.entry.token_id,
        target=matched.entry.at,
        max_staleness_seconds=max_staleness_seconds,
    )
    if entry_snapshot is None or entry_snapshot.price_usd is None or matched.exit is None:
        return (
            entry_snapshot.price_usd if entry_snapshot is not None else None,
            None,
            None,
            None,
        )
    exit_snapshot = await load_nearest_token_market_snapshot(
        session,
        token_id=matched.entry.token_id,
        target=matched.exit.at,
        max_staleness_seconds=max_staleness_seconds,
    )
    if exit_snapshot is None or exit_snapshot.price_usd is None:
        return entry_snapshot.price_usd, None, None, None

    raw_entry_price = entry_snapshot.price_usd
    raw_exit_price = exit_snapshot.price_usd
    effective_entry_price = apply_entry_cost(raw_entry_price, cost_bps=config.cost_bps)
    effective_exit_price = apply_exit_cost(raw_exit_price, cost_bps=config.cost_bps)
    mark_gross_return = compute_forward_return(raw_entry_price, raw_exit_price)
    mark_net_return = compute_forward_return(effective_entry_price, effective_exit_price)
    return raw_entry_price, raw_exit_price, mark_gross_return, mark_net_return


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
    opportunities_by_wallet: dict[uuid.UUID, list[WalletOpportunity]],
) -> list[TradeOutcome]:
    """FSR-08: the PRIMARY executable-return result is the entry
    wallet's own real Phase 5 reverse-executable quote at the primary 5m
    horizon (the same evidence FSR-05/06/07 reuse), matched by
    (token_id, first_seen_at == entry.at) -- never a mark-price proxy.
    An explicit no-route/insufficient-liquidity/excessive-impact/quote-
    failure observation is recorded as ``FAILURE_EXECUTABLE_QUOTE_FAILED``
    (never dropped, never folded into RESOLVED); no matching opportunity/
    probe at all (or one still PENDING/UNAVAILABLE) is
    ``FAILURE_NO_EXECUTABLE_EVIDENCE``. Strategy E's entries have no
    single entry wallet (anchored at a convergence episode instead), so
    they are honestly always ``FAILURE_NO_EXECUTABLE_EVIDENCE`` -- there
    is no per-wallet Phase 5 shadow position for a swarm-anchored entry
    to reuse (a disclosed Phase 10 scope limitation, not a fabricated
    value)."""
    outcomes: list[TradeOutcome] = []
    max_staleness_seconds = config.entry_exit_price_max_staleness.total_seconds()

    for ordinal, matched in enumerate(sorted(match_result.trades, key=lambda t: t.entry.at)):
        (
            mark_entry_price,
            mark_exit_price,
            mark_gross_return,
            mark_net_return,
        ) = await _mark_prices_and_return(
            session, matched=matched, config=config, max_staleness_seconds=max_staleness_seconds
        )

        if matched.exit is None:
            outcome = OUTCOME_FAILURE_NO_EXIT_TRIGGER
            executable_status = None
            executable_failure_class = None
            gross_return: Decimal | None = None
            net_return: Decimal | None = None
        else:
            opportunity = (
                next(
                    (
                        opp
                        for opp in opportunities_by_wallet.get(matched.entry.wallet_id, [])
                        if opp.token_id == matched.entry.token_id
                        and opp.first_seen_at == matched.entry.at
                    ),
                    None,
                )
                if matched.entry.wallet_id is not None
                else None
            )
            reverse_outcome = (
                opportunity.reverse_outcomes.get(PRIMARY_EXECUTABLE_HORIZON)
                if opportunity is not None
                else None
            )
            if reverse_outcome is None:
                outcome = OUTCOME_FAILURE_NO_EXECUTABLE_EVIDENCE
                executable_status = None
                executable_failure_class = None
                gross_return = None
                net_return = None
            else:
                result = reverse_outcome.result
                executable_status = result.status
                executable_failure_class = result.failure_class
                if result.status == "SUCCESS" and result.gross_return_fraction is not None:
                    outcome = OUTCOME_RESOLVED
                    gross_return = result.gross_return_fraction
                    net_return = (
                        result.net_return_fraction
                        if result.net_return_fraction is not None
                        else result.gross_return_fraction
                    )
                elif result.status == "FAILED":
                    outcome = OUTCOME_FAILURE_EXECUTABLE_QUOTE_FAILED
                    gross_return = None
                    net_return = None
                else:
                    outcome = OUTCOME_FAILURE_NO_EXECUTABLE_EVIDENCE
                    gross_return = None
                    net_return = None

        await get_or_create_synthetic_strategy_trade(
            session,
            strategy_code=strategy_code,
            matched=matched,
            entry_price_usd=mark_entry_price,
            exit_price_usd=mark_exit_price,
            cost_bps_applied=config.cost_bps,
            gross_return=gross_return,
            net_return=net_return,
            executable_horizon_label=PRIMARY_EXECUTABLE_HORIZON
            if matched.exit is not None
            else None,
            executable_status=executable_status,
            executable_failure_class=executable_failure_class,
            mark_gross_return=mark_gross_return,
            mark_net_return=mark_net_return,
            outcome=outcome,
            as_of=cutoff,
            algorithm_version=algorithm_version,
            config_hash=config_hash,
            now=computed_at,
        )
        outcomes.append(
            TradeOutcome(outcome=outcome, net_return=net_return, exit_at_ordinal=ordinal)
        )

    return outcomes


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
    opportunities_by_wallet: dict[uuid.UUID, list[WalletOpportunity]],
) -> tuple[StrategySummary, bool]:
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
        opportunities_by_wallet=opportunities_by_wallet,
    )
    summary = compute_strategy_summary(
        outcomes,
        concurrency_samples=match_result.concurrency_samples,
        max_concurrent_positions=config.max_concurrent_positions,
    )
    # FSR-08: true only when NOT ONE trade ever got real executable
    # evidence (success or failure) -- "do not silently fall back to
    # mark prices" when there simply isn't enough executable evidence to
    # report a meaningful result.
    insufficient_executable_sample = not any(
        o.outcome in (OUTCOME_RESOLVED, OUTCOME_FAILURE_EXECUTABLE_QUOTE_FAILED) for o in outcomes
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
        insufficient_executable_sample=insufficient_executable_sample,
        as_of=cutoff,
        algorithm_version=algorithm_version,
        config_hash=config_hash,
        now=computed_at,
    )
    return summary, insufficient_executable_sample


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
    confirmed_entries = await load_confirmed_entries(
        session, cutoff=cutoff, confirmation_algorithm_version=PHASE8_ALGORITHM_VERSION
    )
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

    # FSR-08: Strategy B's discovery-specialist filter and Strategy D's
    # exit-specialist filter must each use the Phase 9 classification
    # exactly AS OF that individual entry/exit's own ``at`` -- never a
    # single set computed once at the final run cutoff (look-ahead bias).
    # Phase 9 only ever persists one snapshot per cutoff it is invoked
    # with, so every DISTINCT decision time actually needed here is
    # recomputed through Phase 9's own idempotent cascade (a disclosed
    # O(distinct decision times) cost) and then queried back.
    phase9_config_hash = phase9_config.config_hash()
    decision_times = (
        {e.at for e in source_entries}
        | {e.at for e in confirmed_entries}
        | {e.at for e in source_exits}
    )
    discovery_wallet_ids_by_time: dict[datetime, set[uuid.UUID]] = {}
    exit_specialist_scores_by_time: dict[datetime, dict[uuid.UUID, Decimal | None]] = {}
    for decision_time in decision_times:
        if decision_time != cutoff:
            await compute_and_persist_phase9(
                session,
                cutoff=decision_time,
                graph_config=graph_config,
                phase8_config=phase8_config,
                config=phase9_config,
                computed_at=computed_at,
            )
        scores = await load_specialist_scores_as_of(
            session,
            decision_time=decision_time,
            algorithm_version=PHASE9_ALGORITHM_VERSION,
            config_hash=phase9_config_hash,
        )
        discovery_wallet_ids_by_time[decision_time] = {
            s.wallet_id for s in scores if s.dominant_specialty == "DISCOVERY"
        }
        exit_specialist_scores_by_time[decision_time] = {
            s.wallet_id: s.exit_specialist_score for s in scores
        }

    discovery_entries = filter_entries_by_decision_time_discovery_specialist(
        source_entries, discovery_wallet_ids_by_time
    )
    confirmed_discovery_entries = filter_entries_by_decision_time_discovery_specialist(
        confirmed_entries, discovery_wallet_ids_by_time
    )
    exit_oracle_exits = filter_exits_by_decision_time_exit_specialist(
        source_exits,
        exit_specialist_scores_by_time,
        min_exit_specialist_score=config.min_exit_specialist_score,
    )

    # FSR-08: opportunities_by_wallet batched once per distinct entry
    # wallet across the whole run (established FSR-05/06/07 efficiency
    # pattern) -- every strategy's executable-return pricing draws from
    # this same map.
    all_entry_wallet_ids = {
        e.wallet_id for e in (*source_entries, *confirmed_entries) if e.wallet_id is not None
    }
    opportunities_by_wallet: dict[uuid.UUID, list[WalletOpportunity]] = {}
    for wallet_id in all_entry_wallet_ids:
        firewall = await load_contamination_firewall(session, wallet_id=wallet_id)
        result = await load_wallet_opportunities(
            session, wallet_id=wallet_id, cutoff=cutoff, firewall=firewall
        )
        opportunities_by_wallet[wallet_id] = result.opportunities

    summaries: dict[str, StrategySummary] = {}
    insufficient_executable_sample: dict[str, bool] = {}
    (
        summaries[STRATEGY_A],
        insufficient_executable_sample[STRATEGY_A],
    ) = await _run_and_persist_strategy(
        session,
        strategy_code=STRATEGY_A,
        entries=source_entries,
        exits=source_exits,
        exit_matches=_same_wallet_exit,
        cutoff=cutoff,
        config=config,
        computed_at=computed_at,
        opportunities_by_wallet=opportunities_by_wallet,
    )
    (
        summaries[STRATEGY_B],
        insufficient_executable_sample[STRATEGY_B],
    ) = await _run_and_persist_strategy(
        session,
        strategy_code=STRATEGY_B,
        entries=discovery_entries,
        exits=source_exits,
        exit_matches=_same_wallet_exit,
        cutoff=cutoff,
        config=config,
        computed_at=computed_at,
        opportunities_by_wallet=opportunities_by_wallet,
    )
    (
        summaries[STRATEGY_C],
        insufficient_executable_sample[STRATEGY_C],
    ) = await _run_and_persist_strategy(
        session,
        strategy_code=STRATEGY_C,
        entries=confirmed_discovery_entries,
        exits=source_exits,
        exit_matches=_same_wallet_exit,
        cutoff=cutoff,
        config=config,
        computed_at=computed_at,
        opportunities_by_wallet=opportunities_by_wallet,
    )
    (
        summaries[STRATEGY_D],
        insufficient_executable_sample[STRATEGY_D],
    ) = await _run_and_persist_strategy(
        session,
        strategy_code=STRATEGY_D,
        entries=confirmed_discovery_entries,
        exits=exit_oracle_exits,
        exit_matches=_any_exit,
        cutoff=cutoff,
        config=config,
        computed_at=computed_at,
        opportunities_by_wallet=opportunities_by_wallet,
    )
    (
        summaries[STRATEGY_E],
        insufficient_executable_sample[STRATEGY_E],
    ) = await _run_and_persist_strategy(
        session,
        strategy_code=STRATEGY_E,
        entries=high_convergence_entries,
        exits=exit_convergence_exits,
        exit_matches=_any_exit,
        cutoff=cutoff,
        config=config,
        computed_at=computed_at,
        opportunities_by_wallet=opportunities_by_wallet,
    )

    return Phase10ComputationResult(
        as_of=cutoff,
        summaries=summaries,
        insufficient_executable_sample=insufficient_executable_sample,
    )
