"""Phase 10 (SYNTHETIC SUPER-WALLET) DB-backed integration coverage:

- Real ``prospective_events``/``swaps``/``token_market_snapshots``
  evidence -> ``argus.synthetic.service.compute_and_persist_phase10`` ->
  idempotent persistence of ``synthetic_strategy_trades``/
  ``synthetic_strategy_summaries`` for all five strategies (A-E), even
  when a given strategy has zero qualifying triggers in this minimal
  fixture (an honest zero-trade summary, not a missing row).
- FSR-08: the PRIMARY executable-return result (``gross_return``/
  ``net_return``/``outcome``) comes from the entry wallet's own real
  Phase 5 reverse-executable quote -- never the old fixed-cost-haircut
  mark price (preserved only as the separate, descriptive-only
  ``mark_gross_return``/``mark_net_return`` columns).
- FSR-08: Strategy B's discovery-specialist filter uses each entry's own
  decision-time Phase 9 classification, never a single set computed once
  at the final run cutoff (look-ahead bias).
- The real ``argus synthetic report`` CLI command, run through the same
  Typer app a human operator uses -- confirms the report is explicitly
  labeled shadow-only.

Follows the exact ``admin_engine``-gated skip pattern every other Phase
1-9 DB-backed integration test in this repo uses -- these tests SKIP
(never fail) when Postgres is unreachable in this sandbox.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from typer.testing import CliRunner

from argus.cli import app
from argus.config import ArgusConfig, load_config
from argus.convergence.service import ConvergenceRunConfig as Phase8RunConfig
from argus.counterfactual.service import ALGORITHM_VERSION as PHASE9_ALGORITHM_VERSION
from argus.counterfactual.service import Phase9RunConfig
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.chain_events import ChainEvent
from argus.domain.prospective_events import ProspectiveEvent
from argus.domain.shadow_intents import STATUS_FILLED, ShadowIntent
from argus.domain.shadow_positions import ShadowPosition
from argus.domain.shadow_quote_probes import (
    OUTCOME_NO_ROUTE,
    OUTCOME_SUCCESS,
    PROBE_KIND_REVERSE_EXECUTABLE,
    ShadowQuoteProbe,
)
from argus.domain.swaps import Swap
from argus.domain.synthetic_strategy_summaries import SyntheticStrategySummary
from argus.domain.synthetic_strategy_trades import SyntheticStrategyTrade
from argus.domain.token_market_snapshots import TokenMarketSnapshot
from argus.domain.tokens import Token
from argus.domain.wallet_specialist_scores import WalletSpecialistScore
from argus.domain.wallets import Wallet
from argus.graph.service import GraphRunConfig
from argus.synthetic.service import STRATEGY_CODES, Phase10RunConfig, compute_and_persist_phase10

pytestmark = pytest.mark.usefixtures("isolated_database")
# R2-04 (``argus-final-spec-recovery-002``): see
# ``tests/integration/conftest.py``'s ``isolated_database`` fixture --
# this module's own production queries scan ALL matching rows, so each
# TEST FUNCTION here gets its own real, independent database.

_PRIMARY_HORIZON = "5m"

SOL_MINT = "So11111111111111111111111111111111111111112"
_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)

runner = CliRunner()


def _sessionmaker() -> tuple[ArgusConfig, Any, async_sessionmaker[Any]]:
    config = load_config()
    info = connection_for_role(config, DbRole.INGEST)
    engine = create_async_engine(info.as_asyncpg_url())
    return config, engine, async_sessionmaker(engine, expire_on_commit=False)


def _unique_wallet() -> str:
    return f"P10TEST{uuid.uuid4().hex[:37]}"


def _unique_mint() -> str:
    return f"P10TOK{uuid.uuid4().hex[:38]}"


async def _seed_wallet(session, *, address: str, at: datetime) -> uuid.UUID:
    wallet_id = uuid.uuid4()
    session.add(
        Wallet(
            wallet_id=wallet_id,
            wallet_address=address,
            first_discovered_at=at,
            current_tier="A",
            created_at=at,
        )
    )
    await session.flush()
    return wallet_id


async def _seed_token(session, *, mint: str, at: datetime) -> uuid.UUID:
    token_id = uuid.uuid4()
    session.add(Token(token_id=token_id, mint=mint, first_observed_at=at, created_at=at))
    await session.flush()
    return token_id


async def _seed_snapshot(session, *, token_id: uuid.UUID, at: datetime, price_usd: Decimal) -> None:
    session.add(
        TokenMarketSnapshot(
            snapshot_id=uuid.uuid4(),
            token_id=token_id,
            observed_at=at,
            lifecycle_stage="AMM_POOL",
            venue="pump.fun",
            price_usd=price_usd,
            liquidity_usd=Decimal(5_000),
            market_cap_usd=Decimal(10_000),
            source="p10-test",
            algorithm_version="p10-test",
            build_hash="p10-test-build",
            created_at=at,
        )
    )
    await session.flush()


async def _seed_buy(
    session,
    *,
    wallet_address: str,
    wallet_id: uuid.UUID,
    token_id: uuid.UUID,
    mint: str,
    at: datetime,
) -> uuid.UUID:
    event_id = uuid.uuid4()
    session.add(
        ChainEvent(
            event_id=event_id,
            chain="solana",
            slot=1,
            block_time=at,
            first_seen_at=at,
            provider="p10-test",
            provider_received_at=at,
            transaction_signature=f"p10-buy-{uuid.uuid4()}",
            event_type="TRANSACTION_OBSERVED",
            wallet_address=wallet_address,
            raw_payload={},
            payload_hash="h",
            parser_version="v1",
            created_at=at,
        )
    )
    swap_id = uuid.uuid4()
    session.add(
        Swap(
            swap_id=swap_id,
            event_id=event_id,
            wallet_address=wallet_address,
            classification="SWAP_SIMPLE",
            input_mint=SOL_MINT,
            input_amount_raw=100_000_000,
            input_amount_ui=Decimal("0.1"),
            output_mint=mint,
            output_amount_raw=200_000_000,
            output_amount_ui=Decimal(200),
            network_fee_raw=5000,
            slot=1,
            block_time=at,
            first_seen_at=at,
            confidence=Decimal("1.000"),
            parser_version="v1",
            build_hash="p10-test-build",
            created_at=at,
        )
    )
    await session.flush()
    prospective_event_id = uuid.uuid4()
    session.add(
        ProspectiveEvent(
            prospective_event_id=prospective_event_id,
            wallet_id=wallet_id,
            swap_id=swap_id,
            event_id=event_id,
            token_id=token_id,
            leader_transaction_time=at,
            first_seen_at=at,
            wallet_tier_snapshot="A",
            token_state_snapshot={},
            position_size_context={},
            cluster_state_snapshot={},
            graph_state_snapshot={"available": False, "reason": "phase10-test"},
            algorithm_version="p10-test",
            created_at=at,
        )
    )
    await session.flush()
    return prospective_event_id


async def _seed_shadow_fill_and_quote(
    session,
    *,
    prospective_event_id: uuid.UUID,
    wallet_id: uuid.UUID,
    token_id: uuid.UUID,
    output_mint: str,
    entered_at: datetime,
    entry_input_amount_raw: int,
    entry_output_amount_raw: int,
    reverse_outcome: str = OUTCOME_SUCCESS,
    reverse_output_amount_raw: int | None = None,
) -> None:
    """FSR-08: real Phase 5 executable-return evidence for a wallet's own
    entry -- a FILLED :class:`ShadowIntent`/:class:`ShadowPosition` plus a
    :class:`ShadowQuoteProbe` at the primary 5m horizon. This, not any
    mark-price snapshot, is what ``argus.synthetic.service`` now reads for
    a trade's primary ``gross_return``/``net_return``/``outcome``."""
    intent_id = uuid.uuid4()
    session.add(
        ShadowIntent(
            shadow_intent_id=intent_id,
            prospective_event_id=prospective_event_id,
            wallet_id=wallet_id,
            token_id=token_id,
            input_mint=SOL_MINT,
            output_mint=output_mint,
            notional_input_amount_raw=entry_input_amount_raw,
            config_hash="p10-fsr08-test-config",
            status=STATUS_FILLED,
            algorithm_version="p10-fsr08-test",
            created_at=entered_at,
        )
    )
    await session.flush()

    position_id = uuid.uuid4()
    session.add(
        ShadowPosition(
            shadow_position_id=position_id,
            shadow_intent_id=intent_id,
            wallet_id=wallet_id,
            token_id=token_id,
            input_mint=SOL_MINT,
            output_mint=output_mint,
            entry_input_amount_raw=entry_input_amount_raw,
            entry_output_amount_raw=entry_output_amount_raw,
            entry_price_impact_pct=Decimal("0.5"),
            entry_route_present=True,
            entry_probe_target_label="0s",
            entry_requested_at=entered_at,
            entry_responded_at=entered_at,
            opened_at=entered_at,
            algorithm_version="p10-fsr08-test",
            created_at=entered_at,
        )
    )
    await session.flush()

    session.add(
        ShadowQuoteProbe(
            probe_id=uuid.uuid4(),
            probe_kind=PROBE_KIND_REVERSE_EXECUTABLE,
            target_label=_PRIMARY_HORIZON,
            shadow_position_id=position_id,
            input_mint=output_mint,
            output_mint=SOL_MINT,
            notional_input_amount_raw=entry_output_amount_raw,
            target_due_at=entered_at + timedelta(minutes=5),
            requested_at=entered_at + timedelta(minutes=5),
            responded_at=entered_at + timedelta(minutes=5, milliseconds=100),
            terminal_at=entered_at + timedelta(minutes=5, milliseconds=100),
            expected_output_amount_raw=reverse_output_amount_raw,
            route_present=reverse_outcome == OUTCOME_SUCCESS,
            outcome=reverse_outcome,
            algorithm_version="p10-fsr08-test",
            created_at=entered_at,
        )
    )
    await session.flush()


async def _seed_sell(session, *, wallet_address: str, mint: str, at: datetime) -> None:
    event_id = uuid.uuid4()
    session.add(
        ChainEvent(
            event_id=event_id,
            chain="solana",
            slot=2,
            block_time=at,
            first_seen_at=at,
            provider="p10-test",
            provider_received_at=at,
            transaction_signature=f"p10-sell-{uuid.uuid4()}",
            event_type="TRANSACTION_OBSERVED",
            wallet_address=wallet_address,
            raw_payload={},
            payload_hash="h",
            parser_version="v1",
            created_at=at,
        )
    )
    session.add(
        Swap(
            swap_id=uuid.uuid4(),
            event_id=event_id,
            wallet_address=wallet_address,
            classification="SWAP_SIMPLE",
            input_mint=mint,
            input_amount_raw=200_000_000,
            input_amount_ui=Decimal(200),
            output_mint=SOL_MINT,
            output_amount_raw=120_000_000,
            output_amount_ui=Decimal("0.12"),
            network_fee_raw=5000,
            slot=2,
            block_time=at,
            first_seen_at=at,
            confidence=Decimal("1.000"),
            parser_version="v1",
            build_hash="p10-test-build",
            created_at=at,
        )
    )
    await session.flush()


_GRAPH_CONFIG = GraphRunConfig(
    max_lag=timedelta(minutes=30), min_observations=1, q_value_threshold=Decimal("0.99")
)
_PHASE8_CONFIG = Phase8RunConfig(
    window=timedelta(minutes=30),
    unknown_independence_weight=Decimal("0.75"),
    q_value_threshold=Decimal("0.99"),
    min_observations=1,
    strong_surprisal_threshold=Decimal("3.0"),
)
_PHASE9_CONFIG = Phase9RunConfig(
    horizons=(timedelta(minutes=5),),
    max_price_staleness=timedelta(minutes=30),
    max_control_tokens=10,
    entry_specialist_horizon=timedelta(minutes=5),
    discovery_min_observations=1,
    discovery_q_value_threshold=Decimal("0.99"),
    follower_influx_window=timedelta(minutes=30),
    exit_after_influx_window=timedelta(minutes=30),
    predation_influx_normalization_cap=Decimal(10),
    exit_convergence_window=timedelta(minutes=30),
    exit_convergence_unknown_independence_weight=Decimal("0.75"),
    min_exit_specialist_score=Decimal(70),
)
_CONFIG = Phase10RunConfig(
    entry_exit_price_max_staleness=timedelta(minutes=30),
    cost_bps=Decimal(100),
    max_concurrent_positions=10,
    high_convergence_surprisal_threshold=Decimal("3.0"),
    min_exit_specialist_score=Decimal(70),
    max_hold_duration=timedelta(hours=6),
)


async def _seed_trade_fixture(
    session,
    *,
    wallet_address: str,
    wallet_id: uuid.UUID,
    token_id: uuid.UUID,
    mint: str,
    entered_at: datetime,
    exit_at: datetime,
) -> uuid.UUID:
    """The shared A/B/C/D/E entry+exit+mark-price fixture every FSR-08
    pricing test starts from: a real buy at ``entered_at`` (mark price
    $100), a real sell at ``exit_at`` (mark price $110, i.e. the OLD
    mark-price computation would show a +10% gain) -- callers separately
    seed (or omit) real Phase 5 executable-return evidence to prove the
    PRIMARY result no longer comes from these mark-price snapshots."""
    await _seed_snapshot(session, token_id=token_id, at=entered_at, price_usd=Decimal(100))
    await _seed_snapshot(session, token_id=token_id, at=exit_at, price_usd=Decimal(110))
    prospective_event_id = await _seed_buy(
        session,
        wallet_address=wallet_address,
        wallet_id=wallet_id,
        token_id=token_id,
        mint=mint,
        at=entered_at,
    )
    await _seed_sell(session, wallet_address=wallet_address, mint=mint, at=exit_at)
    return prospective_event_id


async def test_strategy_a_uses_real_executable_return_not_mark_price(admin_engine) -> None:
    """FSR-08: the entry wallet's own real Phase 5 reverse-executable
    quote sells 200_000_000 raw token back for only 90_000_000 raw SOL
    (a real -10% loss) -- the OLD mark-price computation over the SAME
    fixture ($100 -> $110 snapshots) would show a +10% gain. The
    persisted primary ``gross_return``/``net_return`` must reflect the
    real quote, never the mark price -- proving the executable result,
    not a mark-price proxy, is used. Exit fires 5 minutes after entry --
    contemporaneous with the ONE reverse-quote probe this fixture seeds
    (R2-03: exit pricing is only ever matched to a REAL, contemporaneous
    probe, never a fixed horizon regardless of the trade's own actual
    hold duration -- see ``test_r203_phase10_executable_matching.py`` for
    the dedicated one-hour-exit-trap coverage of that fix)."""
    config, engine, sessionmaker = _sessionmaker()
    try:
        wallet_address = _unique_wallet()
        async with sessionmaker() as session, session.begin():
            wallet_id = await _seed_wallet(session, address=wallet_address, at=_NOW)
            mint = _unique_mint()
            token_id = await _seed_token(session, mint=mint, at=_NOW)
            exit_at = _NOW + timedelta(minutes=5)
            prospective_event_id = await _seed_trade_fixture(
                session,
                wallet_address=wallet_address,
                wallet_id=wallet_id,
                token_id=token_id,
                mint=mint,
                entered_at=_NOW,
                exit_at=exit_at,
            )
            await _seed_shadow_fill_and_quote(
                session,
                prospective_event_id=prospective_event_id,
                wallet_id=wallet_id,
                token_id=token_id,
                output_mint=mint,
                entered_at=_NOW,
                entry_input_amount_raw=100_000_000,
                entry_output_amount_raw=200_000_000,
                reverse_outcome=OUTCOME_SUCCESS,
                reverse_output_amount_raw=90_000_000,
            )

        cutoff = _NOW + timedelta(hours=2)
        async with sessionmaker() as session, session.begin():
            result = await compute_and_persist_phase10(
                session,
                cutoff=cutoff,
                graph_config=_GRAPH_CONFIG,
                phase8_config=_PHASE8_CONFIG,
                phase9_config=_PHASE9_CONFIG,
                config=_CONFIG,
                computed_at=_NOW,
            )
        assert set(result.summaries.keys()) == set(STRATEGY_CODES)
        assert result.summaries["A"].trade_count >= 1
        assert result.insufficient_executable_sample["A"] is False

        async with sessionmaker() as session:
            trades = (
                (
                    await session.execute(
                        select(SyntheticStrategyTrade).where(
                            SyntheticStrategyTrade.strategy_code == "A",
                            SyntheticStrategyTrade.token_id == token_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(trades) == 1
            trade = trades[0]
            assert trade.outcome == "RESOLVED"
            assert trade.executable_status == "SUCCESS"
            assert trade.executable_horizon_label == "5m"
            # The real Phase 5 quote result: 90_000_000 / 100_000_000 - 1.
            assert trade.gross_return == Decimal("-0.1")
            assert trade.net_return == Decimal("-0.1")
            # The OLD mark-price computation, preserved only as a
            # separate descriptive column -- opposite sign, never the
            # primary result.
            assert trade.entry_price_usd == Decimal(100)
            assert trade.exit_price_usd == Decimal(110)
            assert trade.mark_gross_return == Decimal("0.1")
            assert trade.mark_net_return < trade.mark_gross_return
            assert trade.gross_return != trade.mark_gross_return

            summaries = (
                (
                    await session.execute(
                        select(SyntheticStrategySummary).where(
                            SyntheticStrategySummary.as_of == cutoff
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert {s.strategy_code for s in summaries} == set(STRATEGY_CODES)
    finally:
        await engine.dispose()


async def test_unsellable_reverse_quote_is_a_failed_executable_outcome(admin_engine) -> None:
    """FSR-08: an explicit no-route/insufficient-liquidity/excessive-
    impact/quote-failure observation is recorded as a genuine failure
    outcome (``FAILURE_EXECUTABLE_QUOTE_FAILED``), never dropped and
    never folded into ``RESOLVED`` with a fabricated return. Exit fires 5
    minutes after entry -- contemporaneous with the ONE reverse-quote
    probe this fixture seeds (R2-03)."""
    config, engine, sessionmaker = _sessionmaker()
    try:
        wallet_address = _unique_wallet()
        async with sessionmaker() as session, session.begin():
            wallet_id = await _seed_wallet(session, address=wallet_address, at=_NOW)
            mint = _unique_mint()
            token_id = await _seed_token(session, mint=mint, at=_NOW)
            exit_at = _NOW + timedelta(minutes=5)
            prospective_event_id = await _seed_trade_fixture(
                session,
                wallet_address=wallet_address,
                wallet_id=wallet_id,
                token_id=token_id,
                mint=mint,
                entered_at=_NOW,
                exit_at=exit_at,
            )
            await _seed_shadow_fill_and_quote(
                session,
                prospective_event_id=prospective_event_id,
                wallet_id=wallet_id,
                token_id=token_id,
                output_mint=mint,
                entered_at=_NOW,
                entry_input_amount_raw=100_000_000,
                entry_output_amount_raw=200_000_000,
                reverse_outcome=OUTCOME_NO_ROUTE,
                reverse_output_amount_raw=None,
            )

        cutoff = _NOW + timedelta(hours=2)
        async with sessionmaker() as session, session.begin():
            await compute_and_persist_phase10(
                session,
                cutoff=cutoff,
                graph_config=_GRAPH_CONFIG,
                phase8_config=_PHASE8_CONFIG,
                phase9_config=_PHASE9_CONFIG,
                config=_CONFIG,
                computed_at=_NOW,
            )

        async with sessionmaker() as session:
            trade = (
                await session.execute(
                    select(SyntheticStrategyTrade).where(
                        SyntheticStrategyTrade.strategy_code == "A",
                        SyntheticStrategyTrade.token_id == token_id,
                    )
                )
            ).scalar_one()
            assert trade.outcome == "FAILURE_EXECUTABLE_QUOTE_FAILED"
            assert trade.executable_status == "FAILED"
            assert trade.executable_failure_class == "NO_ROUTE"
            assert trade.gross_return is None
            assert trade.net_return is None
            # Mark price still computed descriptively, but never
            # substituted in for the missing primary result.
            assert trade.mark_gross_return == Decimal("0.1")
    finally:
        await engine.dispose()


async def test_no_phase5_evidence_never_falls_back_to_mark_price(admin_engine) -> None:
    """FSR-08: with no matching Phase 5 shadow position/quote at all, the
    trade is an honest ``FAILURE_NO_EXECUTABLE_EVIDENCE`` -- the fixed-
    haircut mark-price proxy is computed (``mark_gross_return``) but can
    never enter the primary ``gross_return``/``net_return`` fields, and
    the strategy-level summary discloses it has no real executable
    sample."""
    config, engine, sessionmaker = _sessionmaker()
    try:
        wallet_address = _unique_wallet()
        async with sessionmaker() as session, session.begin():
            wallet_id = await _seed_wallet(session, address=wallet_address, at=_NOW)
            mint = _unique_mint()
            token_id = await _seed_token(session, mint=mint, at=_NOW)
            exit_at = _NOW + timedelta(hours=1)
            await _seed_trade_fixture(
                session,
                wallet_address=wallet_address,
                wallet_id=wallet_id,
                token_id=token_id,
                mint=mint,
                entered_at=_NOW,
                exit_at=exit_at,
            )
            # Deliberately no _seed_shadow_fill_and_quote call.

        cutoff = _NOW + timedelta(hours=2)
        async with sessionmaker() as session, session.begin():
            result = await compute_and_persist_phase10(
                session,
                cutoff=cutoff,
                graph_config=_GRAPH_CONFIG,
                phase8_config=_PHASE8_CONFIG,
                phase9_config=_PHASE9_CONFIG,
                config=_CONFIG,
                computed_at=_NOW,
            )
        assert result.insufficient_executable_sample["A"] is True

        async with sessionmaker() as session:
            trade = (
                await session.execute(
                    select(SyntheticStrategyTrade).where(
                        SyntheticStrategyTrade.strategy_code == "A",
                        SyntheticStrategyTrade.token_id == token_id,
                    )
                )
            ).scalar_one()
            assert trade.outcome == "FAILURE_NO_EXECUTABLE_EVIDENCE"
            assert trade.executable_status is None
            assert trade.gross_return is None
            assert trade.net_return is None
            assert trade.mark_gross_return == Decimal("0.1")

            summary = (
                await session.execute(
                    select(SyntheticStrategySummary).where(
                        SyntheticStrategySummary.strategy_code == "A",
                        SyntheticStrategySummary.as_of == cutoff,
                    )
                )
            ).scalar_one()
            assert summary.insufficient_executable_sample is True
    finally:
        await engine.dispose()


async def test_strategy_b_discovery_filter_uses_entrys_own_decision_time(admin_engine) -> None:
    """FSR-08: Strategy B's discovery-specialist filter must use each
    entry's OWN decision-time Phase 9 classification, never a single
    set computed once at the final run cutoff. Wallet ``W`` is made a
    DISCOVERY specialist as of the FINAL cutoff (a shortcut direct
    insert, the same "shortcut what the query sees" pattern already used
    for ``LeadFollowObservation`` in the Phase 9 integration suite) but
    has NO real signal at all as of its own earlier entry time -- under
    the old "one set at the final cutoff" bug this earlier entry would
    be wrongly admitted into Strategy B; under the fix it must not be."""
    config, engine, sessionmaker = _sessionmaker()
    try:
        wallet_address = _unique_wallet()
        entered_at = _NOW
        cutoff = _NOW + timedelta(hours=2)
        async with sessionmaker() as session, session.begin():
            wallet_id = await _seed_wallet(session, address=wallet_address, at=_NOW)
            mint = _unique_mint()
            token_id = await _seed_token(session, mint=mint, at=_NOW)
            await _seed_snapshot(session, token_id=token_id, at=entered_at, price_usd=Decimal(100))
            await _seed_buy(
                session,
                wallet_address=wallet_address,
                wallet_id=wallet_id,
                token_id=token_id,
                mint=mint,
                at=entered_at,
            )
            # Shortcut: pre-insert wallet W's DISCOVERY classification
            # AS OF THE FINAL CUTOFF ONLY -- Phase 9's own real
            # computation at any EARLIER decision time (including this
            # entry's own ``entered_at``) sees zero underlying signal for
            # a freshly-seeded wallet, so it independently classifies W
            # as NOT a discovery specialist at that earlier time.
            session.add(
                WalletSpecialistScore(
                    score_id=uuid.uuid4(),
                    wallet_id=wallet_id,
                    as_of=cutoff,
                    entry_specialist_score=None,
                    entry_specialist_sample_size=0,
                    discovery_specialist_score=Decimal("5.0"),
                    discovery_specialist_sample_size=1,
                    validation_specialist_score=None,
                    validation_specialist_sample_size=0,
                    exit_specialist_score=None,
                    entry_percentile=None,
                    discovery_percentile=Decimal("1.0"),
                    validation_percentile=None,
                    exit_percentile=None,
                    dominant_specialty="DISCOVERY",
                    algorithm_version=PHASE9_ALGORITHM_VERSION,
                    config_hash=_PHASE9_CONFIG.config_hash(),
                    created_at=_NOW,
                )
            )

        async with sessionmaker() as session, session.begin():
            await compute_and_persist_phase10(
                session,
                cutoff=cutoff,
                graph_config=_GRAPH_CONFIG,
                phase8_config=_PHASE8_CONFIG,
                phase9_config=_PHASE9_CONFIG,
                config=_CONFIG,
                computed_at=_NOW,
            )

        async with sessionmaker() as session:
            # Sanity: the shortcut row really is visible as DISCOVERY at
            # the final cutoff.
            final_score = (
                await session.execute(
                    select(WalletSpecialistScore).where(
                        WalletSpecialistScore.wallet_id == wallet_id,
                        WalletSpecialistScore.as_of == cutoff,
                    )
                )
            ).scalar_one()
            assert final_score.dominant_specialty == "DISCOVERY"

            # Strategy A (unfiltered) sees the entry.
            strategy_a_trades = (
                (
                    await session.execute(
                        select(SyntheticStrategyTrade).where(
                            SyntheticStrategyTrade.strategy_code == "A",
                            SyntheticStrategyTrade.token_id == token_id,
                            SyntheticStrategyTrade.entry_at == entered_at,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(strategy_a_trades) == 1

            # Strategy B, filtered by discovery-specialist status AS OF
            # the entry's OWN time, must NOT admit it -- W had no real
            # discovery signal yet at ``entered_at``.
            strategy_b_trades = (
                (
                    await session.execute(
                        select(SyntheticStrategyTrade).where(
                            SyntheticStrategyTrade.strategy_code == "B",
                            SyntheticStrategyTrade.token_id == token_id,
                            SyntheticStrategyTrade.entry_at == entered_at,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(strategy_b_trades) == 0
    finally:
        await engine.dispose()


async def test_rerun_over_identical_evidence_is_idempotent(admin_engine) -> None:
    config, engine, sessionmaker = _sessionmaker()
    try:
        wallet_address = _unique_wallet()
        async with sessionmaker() as session, session.begin():
            wallet_id = await _seed_wallet(session, address=wallet_address, at=_NOW)
            mint = _unique_mint()
            token_id = await _seed_token(session, mint=mint, at=_NOW)
            await _seed_snapshot(session, token_id=token_id, at=_NOW, price_usd=Decimal(100))
            await _seed_buy(
                session,
                wallet_address=wallet_address,
                wallet_id=wallet_id,
                token_id=token_id,
                mint=mint,
                at=_NOW,
            )

        cutoff = _NOW + timedelta(hours=2)
        async with sessionmaker() as session, session.begin():
            await compute_and_persist_phase10(
                session,
                cutoff=cutoff,
                graph_config=_GRAPH_CONFIG,
                phase8_config=_PHASE8_CONFIG,
                phase9_config=_PHASE9_CONFIG,
                config=_CONFIG,
                computed_at=_NOW,
            )
        async with sessionmaker() as session, session.begin():
            await compute_and_persist_phase10(
                session,
                cutoff=cutoff,
                graph_config=_GRAPH_CONFIG,
                phase8_config=_PHASE8_CONFIG,
                phase9_config=_PHASE9_CONFIG,
                config=_CONFIG,
                computed_at=_NOW + timedelta(seconds=1),
            )

        async with sessionmaker() as session:
            summaries = (
                (
                    await session.execute(
                        select(SyntheticStrategySummary).where(
                            SyntheticStrategySummary.strategy_code == "A",
                            SyntheticStrategySummary.as_of == cutoff,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(summaries) == 1
    finally:
        await engine.dispose()


def test_cli_synthetic_report_runs_and_is_labeled_shadow_only(admin_engine) -> None:
    result = runner.invoke(app, ["synthetic", "report", "--as-of", _NOW.isoformat()])
    assert result.exit_code == 0, result.output
    assert "strategies" in result.output
    assert '"shadow_only": true' in result.output
    assert "SHADOW ONLY" in result.output
