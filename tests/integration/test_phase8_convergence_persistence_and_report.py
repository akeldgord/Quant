"""Phase 8 (CONVERGENCE + NEGATIVE EVIDENCE) DB-backed integration
coverage:

- Real ``prospective_events`` evidence -> ``argus.convergence.service.
  compute_and_persist_phase8`` -> idempotent persistence of
  ``convergence_events``/``expected_confirmation_events``.
- Point-in-time cutoff excludes a not-yet-known entry from a convergence
  episode.
- A leader's real buy entry into a token the historically-confirming
  follower never enters within the lag window produces an
  ``EXPECTED_CONFIRMATION_ABSENT`` row.
- The real ``argus convergence report`` CLI command, run through the
  same Typer app a human operator uses.

Follows the exact ``admin_engine``-gated skip pattern every other Phase
1-7 DB-backed integration test in this repo uses -- these tests SKIP
(never fail) when Postgres is unreachable in this sandbox.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from typer.testing import CliRunner

from argus.cli import app
from argus.config import ArgusConfig, load_config
from argus.convergence.outcome_comparison import (
    CLASS_FAILED_CONFIRMATION,
    CLASS_HIGH_SURPRISAL_OVERLAP,
    CLASS_ORDINARY_OVERLAP,
    CLASS_RAPID_CONFIRMATION,
)
from argus.convergence.service import ConvergenceRunConfig, compute_and_persist_phase8
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.chain_events import ChainEvent
from argus.domain.convergence_events import ConvergenceEvent
from argus.domain.convergence_outcome_comparisons import ConvergenceOutcomeComparison
from argus.domain.expected_confirmation_events import ExpectedConfirmationEvent
from argus.domain.prospective_events import ProspectiveEvent
from argus.domain.shadow_intents import STATUS_FILLED, ShadowIntent
from argus.domain.shadow_positions import ShadowPosition
from argus.domain.shadow_quote_probes import (
    OUTCOME_SUCCESS,
    PROBE_KIND_REVERSE_EXECUTABLE,
    ShadowQuoteProbe,
)
from argus.domain.swaps import Swap
from argus.domain.tokens import Token
from argus.domain.wallets import Wallet
from argus.graph.service import GraphRunConfig

SOL_MINT = "So11111111111111111111111111111111111111112"
_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)

runner = CliRunner()


def _sessionmaker() -> tuple[ArgusConfig, Any, async_sessionmaker[Any]]:
    config = load_config()
    info = connection_for_role(config, DbRole.INGEST)
    engine = create_async_engine(info.as_asyncpg_url())
    return config, engine, async_sessionmaker(engine, expire_on_commit=False)


def _unique_wallet() -> str:
    return f"P8TEST{uuid.uuid4().hex[:38]}"


def _unique_mint() -> str:
    return f"P8TOK{uuid.uuid4().hex[:39]}"


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


async def _seed_prospective_event(
    session, *, wallet_id: uuid.UUID, token_id: uuid.UUID, output_mint: str, entered_at: datetime
) -> uuid.UUID:
    event_id = uuid.uuid4()
    session.add(
        ChainEvent(
            event_id=event_id,
            chain="solana",
            slot=1,
            block_time=entered_at,
            first_seen_at=entered_at,
            provider="p8-test",
            provider_received_at=entered_at,
            transaction_signature=f"p8-test-{uuid.uuid4()}",
            event_type="TRANSACTION_OBSERVED",
            wallet_address="leader-not-under-test",
            raw_payload={},
            payload_hash="h",
            parser_version="v1",
            created_at=entered_at,
        )
    )
    swap_id = uuid.uuid4()
    session.add(
        Swap(
            swap_id=swap_id,
            event_id=event_id,
            wallet_address="leader-not-under-test",
            classification="SWAP_SIMPLE",
            input_mint=SOL_MINT,
            input_amount_raw=100_000_000,
            input_amount_ui=Decimal("0.1"),
            output_mint=output_mint,
            output_amount_raw=200_000_000,
            output_amount_ui=Decimal(200),
            network_fee_raw=5000,
            slot=1,
            block_time=entered_at,
            first_seen_at=entered_at,
            confidence=Decimal("1.000"),
            parser_version="v1",
            build_hash="p8-test-build",
            created_at=entered_at,
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
            leader_transaction_time=entered_at,
            first_seen_at=entered_at,
            wallet_tier_snapshot="A",
            token_state_snapshot={},
            position_size_context={},
            cluster_state_snapshot={},
            graph_state_snapshot={"available": False, "reason": "phase8-test"},
            algorithm_version="p8-test",
            created_at=entered_at,
        )
    )
    await session.flush()
    return prospective_event_id


async def _seed_prospective_event_with_shadow_fill(
    session,
    *,
    wallet_id: uuid.UUID,
    token_id: uuid.UUID,
    output_mint: str,
    entered_at: datetime,
    entry_input_raw: int,
    entry_output_raw: int,
    reverse_output_raw: int,
    reverse_terminal_at: datetime | None = None,
) -> uuid.UUID:
    """FSR-06: same as :func:`_seed_prospective_event`, but also seeds a
    FILLED :class:`ShadowIntent`/:class:`ShadowPosition` and a SUCCESS 5m
    :class:`ShadowQuoteProbe` -- the real Phase 5 executable-return
    evidence the outcome-comparison layer reuses."""
    prospective_event_id = await _seed_prospective_event(
        session,
        wallet_id=wallet_id,
        token_id=token_id,
        output_mint=output_mint,
        entered_at=entered_at,
    )
    intent_id = uuid.uuid4()
    session.add(
        ShadowIntent(
            shadow_intent_id=intent_id,
            prospective_event_id=prospective_event_id,
            wallet_id=wallet_id,
            token_id=token_id,
            input_mint=SOL_MINT,
            output_mint=output_mint,
            notional_input_amount_raw=entry_input_raw,
            config_hash="p8-fsr06-test-config",
            status=STATUS_FILLED,
            algorithm_version="p8-fsr06-test",
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
            entry_input_amount_raw=entry_input_raw,
            entry_output_amount_raw=entry_output_raw,
            entry_route_present=True,
            entry_probe_target_label="0s",
            entry_requested_at=entered_at,
            entry_responded_at=entered_at,
            opened_at=entered_at,
            algorithm_version="p8-fsr06-test",
            created_at=entered_at,
        )
    )
    await session.flush()

    terminal_at = reverse_terminal_at or (entered_at + timedelta(minutes=5, milliseconds=100))
    session.add(
        ShadowQuoteProbe(
            probe_id=uuid.uuid4(),
            probe_kind=PROBE_KIND_REVERSE_EXECUTABLE,
            target_label="5m",
            shadow_position_id=position_id,
            input_mint=output_mint,
            output_mint=SOL_MINT,
            notional_input_amount_raw=entry_output_raw,
            target_due_at=entered_at + timedelta(minutes=5),
            requested_at=entered_at + timedelta(minutes=5),
            responded_at=terminal_at,
            terminal_at=terminal_at,
            expected_output_amount_raw=reverse_output_raw,
            route_present=True,
            outcome=OUTCOME_SUCCESS,
            algorithm_version="p8-fsr06-test",
            created_at=entered_at,
        )
    )
    await session.flush()
    return prospective_event_id


_GRAPH_CONFIG = GraphRunConfig(
    max_lag=timedelta(minutes=30), min_observations=1, q_value_threshold=Decimal("0.99")
)
_CONVERGENCE_CONFIG = ConvergenceRunConfig(
    window=timedelta(minutes=30),
    unknown_independence_weight=Decimal("0.75"),
    q_value_threshold=Decimal("0.99"),
    min_observations=1,
    strong_surprisal_threshold=Decimal("3.0"),
)


async def test_convergence_event_persisted_for_multi_wallet_episode(admin_engine) -> None:
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            wallet_a = await _seed_wallet(session, address=_unique_wallet(), at=_NOW)
            wallet_b = await _seed_wallet(session, address=_unique_wallet(), at=_NOW)
            mint = _unique_mint()
            token_id = await _seed_token(session, mint=mint, at=_NOW)
            await _seed_prospective_event(
                session, wallet_id=wallet_a, token_id=token_id, output_mint=mint, entered_at=_NOW
            )
            await _seed_prospective_event(
                session,
                wallet_id=wallet_b,
                token_id=token_id,
                output_mint=mint,
                entered_at=_NOW + timedelta(seconds=30),
            )

        async with sessionmaker() as session, session.begin():
            result = await compute_and_persist_phase8(
                session,
                cutoff=_NOW + timedelta(hours=1),
                graph_config=_GRAPH_CONFIG,
                config=_CONVERGENCE_CONFIG,
                computed_at=_NOW,
            )
        assert len(result.convergence_events) == 1
        computed = result.convergence_events[0]
        assert computed.episode.token_id == token_id
        assert computed.episode.raw_wallet_count == 2
        assert computed.estimated_independent_actors > 0
        assert computed.estimated_independent_actors <= Decimal(2)

        async with sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        select(ConvergenceEvent).where(ConvergenceEvent.token_id == token_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert rows[0].raw_wallet_count == 2
            assert rows[0].sample_size == 0
            assert rows[0].calibration_confidence == "INSUFFICIENT_SAMPLE"
    finally:
        await engine.dispose()


async def test_rerun_over_identical_evidence_is_idempotent(admin_engine) -> None:
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            wallet_a = await _seed_wallet(session, address=_unique_wallet(), at=_NOW)
            wallet_b = await _seed_wallet(session, address=_unique_wallet(), at=_NOW)
            mint = _unique_mint()
            token_id = await _seed_token(session, mint=mint, at=_NOW)
            await _seed_prospective_event(
                session, wallet_id=wallet_a, token_id=token_id, output_mint=mint, entered_at=_NOW
            )
            await _seed_prospective_event(
                session,
                wallet_id=wallet_b,
                token_id=token_id,
                output_mint=mint,
                entered_at=_NOW + timedelta(seconds=30),
            )

        cutoff = _NOW + timedelta(hours=1)
        async with sessionmaker() as session, session.begin():
            await compute_and_persist_phase8(
                session,
                cutoff=cutoff,
                graph_config=_GRAPH_CONFIG,
                config=_CONVERGENCE_CONFIG,
                computed_at=_NOW,
            )
        async with sessionmaker() as session, session.begin():
            await compute_and_persist_phase8(
                session,
                cutoff=cutoff,
                graph_config=_GRAPH_CONFIG,
                config=_CONVERGENCE_CONFIG,
                computed_at=_NOW + timedelta(seconds=1),
            )

        async with sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        select(ConvergenceEvent).where(
                            ConvergenceEvent.token_id == token_id, ConvergenceEvent.as_of == cutoff
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
    finally:
        await engine.dispose()


async def test_entry_after_cutoff_excluded_from_episode(admin_engine) -> None:
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            wallet_a = await _seed_wallet(session, address=_unique_wallet(), at=_NOW)
            wallet_b = await _seed_wallet(session, address=_unique_wallet(), at=_NOW)
            mint = _unique_mint()
            token_id = await _seed_token(session, mint=mint, at=_NOW)
            await _seed_prospective_event(
                session, wallet_id=wallet_a, token_id=token_id, output_mint=mint, entered_at=_NOW
            )
            # Second wallet's entry is AFTER the cutoff -- must be excluded
            # from this episode's raw_wallet_count.
            await _seed_prospective_event(
                session,
                wallet_id=wallet_b,
                token_id=token_id,
                output_mint=mint,
                entered_at=_NOW + timedelta(minutes=10),
            )

        cutoff = _NOW + timedelta(minutes=5)
        async with sessionmaker() as session, session.begin():
            result = await compute_and_persist_phase8(
                session,
                cutoff=cutoff,
                graph_config=_GRAPH_CONFIG,
                config=_CONVERGENCE_CONFIG,
                computed_at=_NOW,
            )
        assert len(result.convergence_events) == 1
        assert result.convergence_events[0].episode.raw_wallet_count == 1
    finally:
        await engine.dispose()


async def test_leader_entry_without_follower_confirmation_is_absent(admin_engine) -> None:
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            leader = await _seed_wallet(session, address=_unique_wallet(), at=_NOW)
            follower = await _seed_wallet(session, address=_unique_wallet(), at=_NOW)

            mint_1 = _unique_mint()
            token_1 = await _seed_token(session, mint=mint_1, at=_NOW)
            await _seed_prospective_event(
                session, wallet_id=leader, token_id=token_1, output_mint=mint_1, entered_at=_NOW
            )
            await _seed_prospective_event(
                session,
                wallet_id=follower,
                token_id=token_1,
                output_mint=mint_1,
                entered_at=_NOW + timedelta(seconds=30),
            )

            mint_2 = _unique_mint()
            token_2 = await _seed_token(session, mint=mint_2, at=_NOW)
            leader_second_entry_at = _NOW + timedelta(hours=1)
            await _seed_prospective_event(
                session,
                wallet_id=leader,
                token_id=token_2,
                output_mint=mint_2,
                entered_at=leader_second_entry_at,
            )
            # follower never buys token_2 within the lag window.

        cutoff = _NOW + timedelta(hours=2)
        async with sessionmaker() as session, session.begin():
            result = await compute_and_persist_phase8(
                session,
                cutoff=cutoff,
                graph_config=_GRAPH_CONFIG,
                config=_CONVERGENCE_CONFIG,
                computed_at=_NOW,
            )
        # token_1's entry is the first-ever observation for this edge (no
        # prior history) -- skipped. token_2's leader entry has token_1's
        # observation as its own prior history -- classified ABSENT.
        assert result.expected_confirmation_outcome_counts.get("ABSENT") == 1

        async with sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        select(ExpectedConfirmationEvent).where(
                            ExpectedConfirmationEvent.token_id == token_2,
                            ExpectedConfirmationEvent.leader_wallet_id == leader,
                            ExpectedConfirmationEvent.follower_wallet_id == follower,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert rows[0].outcome == "ABSENT"
            assert rows[0].follower_entered_at is None
            assert rows[0].lag_seconds is None
    finally:
        await engine.dispose()


def test_cli_convergence_report_runs_and_prints_required_fields(admin_engine) -> None:
    result = runner.invoke(app, ["convergence", "report", "--as-of", _NOW.isoformat()])
    assert result.exit_code == 0, result.output
    assert "top_convergence_events" in result.output
    assert "expected_confirmation_outcome_counts" in result.output
    assert "algorithm_version" in result.output
    assert "purely observational" in result.output


async def test_fsr06_outcome_comparisons_all_four_classes_persisted(admin_engine) -> None:
    """FSR-06: every run persists exactly one row per required class
    (ORDINARY_OVERLAP/HIGH_SURPRISAL_OVERLAP/RAPID_CONFIRMATION/
    FAILED_CONFIRMATION); an ordinary-overlap entrant with real Phase 5
    executable-return evidence produces the exact known mean/win rate,
    while the other three classes (no members in this fixture) are
    honestly INSUFFICIENT_EXECUTABLE_SAMPLE -- never a fabricated 0-100
    score or a mark-return substitute."""
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            wallet_a = await _seed_wallet(session, address=_unique_wallet(), at=_NOW)
            wallet_b = await _seed_wallet(session, address=_unique_wallet(), at=_NOW)
            mint = _unique_mint()
            token_id = await _seed_token(session, mint=mint, at=_NOW)
            await _seed_prospective_event(
                session, wallet_id=wallet_a, token_id=token_id, output_mint=mint, entered_at=_NOW
            )
            # wallet_b: 100 SOL-raw in -> 200 token-raw entry, then 200
            # token-raw -> 400 SOL-raw reverse = +300% gross SUCCESS return.
            await _seed_prospective_event_with_shadow_fill(
                session,
                wallet_id=wallet_b,
                token_id=token_id,
                output_mint=mint,
                entered_at=_NOW + timedelta(seconds=30),
                entry_input_raw=100_000_000,
                entry_output_raw=200_000_000,
                reverse_output_raw=400_000_000,
            )

        cutoff = _NOW + timedelta(hours=1)
        async with sessionmaker() as session, session.begin():
            result = await compute_and_persist_phase8(
                session,
                cutoff=cutoff,
                graph_config=_GRAPH_CONFIG,
                config=_CONVERGENCE_CONFIG,
                computed_at=_NOW,
            )

        assert set(result.outcome_comparisons.keys()) == {
            CLASS_ORDINARY_OVERLAP,
            CLASS_HIGH_SURPRISAL_OVERLAP,
            CLASS_RAPID_CONFIRMATION,
            CLASS_FAILED_CONFIRMATION,
        }

        ordinary = result.outcome_comparisons[CLASS_ORDINARY_OVERLAP]
        assert ordinary.member_count == 2
        assert ordinary.eligible_count == 1
        assert ordinary.sample_count == 1
        assert ordinary.mean_return_pct == Decimal("300")
        assert ordinary.median_return_pct == Decimal("300")
        assert ordinary.win_rate == Decimal("1")
        assert ordinary.insufficient_executable_sample is False

        for class_name in (
            CLASS_HIGH_SURPRISAL_OVERLAP,
            CLASS_RAPID_CONFIRMATION,
            CLASS_FAILED_CONFIRMATION,
        ):
            comparison = result.outcome_comparisons[class_name]
            assert comparison.member_count == 0
            assert comparison.insufficient_executable_sample is True
            assert comparison.mean_return_pct is None

        async with sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        select(ConvergenceOutcomeComparison).where(
                            ConvergenceOutcomeComparison.as_of == cutoff
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 4
    finally:
        await engine.dispose()


async def test_fsr06_future_executable_evidence_beyond_cutoff_is_excluded(admin_engine) -> None:
    """FSR-06 required test: a reverse-executable outcome that only
    becomes terminal AFTER the research cutoff must not be usable early
    -- the member is counted but honestly has no eligible evidence."""
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            wallet_a = await _seed_wallet(session, address=_unique_wallet(), at=_NOW)
            wallet_b = await _seed_wallet(session, address=_unique_wallet(), at=_NOW)
            mint = _unique_mint()
            token_id = await _seed_token(session, mint=mint, at=_NOW)
            await _seed_prospective_event(
                session, wallet_id=wallet_a, token_id=token_id, output_mint=mint, entered_at=_NOW
            )
            entered_at = _NOW + timedelta(seconds=30)
            await _seed_prospective_event_with_shadow_fill(
                session,
                wallet_id=wallet_b,
                token_id=token_id,
                output_mint=mint,
                entered_at=entered_at,
                entry_input_raw=100_000_000,
                entry_output_raw=200_000_000,
                reverse_output_raw=400_000_000,
                # Terminal well AFTER the cutoff used below.
                reverse_terminal_at=entered_at + timedelta(days=1),
            )

        cutoff = _NOW + timedelta(hours=1)
        async with sessionmaker() as session, session.begin():
            result = await compute_and_persist_phase8(
                session,
                cutoff=cutoff,
                graph_config=_GRAPH_CONFIG,
                config=_CONVERGENCE_CONFIG,
                computed_at=_NOW,
            )

        ordinary = result.outcome_comparisons[CLASS_ORDINARY_OVERLAP]
        assert ordinary.member_count == 2
        assert ordinary.eligible_count == 0
        assert ordinary.insufficient_executable_sample is True
        assert ordinary.mean_return_pct is None
    finally:
        await engine.dispose()
