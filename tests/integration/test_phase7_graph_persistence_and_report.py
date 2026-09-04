"""Phase 7 (ALPHA ANCESTRY) DB-backed integration coverage:

- Real `prospective_events` evidence -> `argus.graph.service.
  compute_and_persist_directional_edges` -> idempotent persistence of
  `lead_follow_observations`/`directional_edges`.
- Point-in-time cutoff excludes a not-yet-known entry.
- The real `argus graph report` CLI command, run through the same Typer
  app a human operator uses.

Follows the exact `admin_engine`-gated skip pattern every other Phase
1-6 DB-backed integration test in this repo uses -- these tests SKIP
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
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.chain_events import ChainEvent
from argus.domain.directional_edges import DirectionalEdge
from argus.domain.lead_follow_observations import LeadFollowObservation
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
from argus.graph.service import GraphRunConfig, compute_and_persist_directional_edges

SOL_MINT = "So11111111111111111111111111111111111111112"
_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)

runner = CliRunner()


def _sessionmaker() -> tuple[ArgusConfig, Any, async_sessionmaker[Any]]:
    config = load_config()
    info = connection_for_role(config, DbRole.INGEST)
    engine = create_async_engine(info.as_asyncpg_url())
    return config, engine, async_sessionmaker(engine, expire_on_commit=False)


def _unique_wallet() -> str:
    return f"P7TEST{uuid.uuid4().hex[:38]}"


def _unique_mint() -> str:
    return f"P7TOK{uuid.uuid4().hex[:39]}"


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
            provider="p7-test",
            provider_received_at=entered_at,
            transaction_signature=f"p7-test-{uuid.uuid4()}",
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
            build_hash="p7-test-build",
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
            graph_state_snapshot={"available": False, "reason": "phase7-test"},
            algorithm_version="p7-test",
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
) -> uuid.UUID:
    """FSR-05: same as :func:`_seed_prospective_event`, but also seeds a
    FILLED :class:`ShadowIntent`/:class:`ShadowPosition` and a SUCCESS
    5m :class:`ShadowQuoteProbe` -- the real Phase 5 executable-return
    evidence :func:`argus.graph.loaders.load_forward_information_after_leader`
    reuses, never a fabricated return."""
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
            config_hash="p7-fsr05-test-config",
            status=STATUS_FILLED,
            algorithm_version="p7-fsr05-test",
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
            algorithm_version="p7-fsr05-test",
            created_at=entered_at,
        )
    )
    await session.flush()

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
            responded_at=entered_at + timedelta(minutes=5, milliseconds=100),
            terminal_at=entered_at + timedelta(minutes=5, milliseconds=100),
            expected_output_amount_raw=reverse_output_raw,
            route_present=True,
            outcome=OUTCOME_SUCCESS,
            algorithm_version="p7-fsr05-test",
            created_at=entered_at,
        )
    )
    await session.flush()
    return prospective_event_id


_CONFIG = GraphRunConfig(
    max_lag=timedelta(minutes=30), min_observations=1, q_value_threshold=Decimal("0.5")
)


async def test_lead_follow_observation_and_directional_edge_persisted(admin_engine) -> None:
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
            result = await compute_and_persist_directional_edges(
                session, cutoff=_NOW + timedelta(hours=1), config=_CONFIG, computed_at=_NOW
            )
        assert result.observation_count == 1
        assert len(result.edges) == 1
        edge = result.edges[0].edge
        assert edge.leader_wallet_id == wallet_a
        assert edge.follower_wallet_id == wallet_b
        assert edge.observation_count == 1

        async with sessionmaker() as session:
            obs_rows = (
                (
                    await session.execute(
                        select(LeadFollowObservation).where(
                            LeadFollowObservation.token_id == token_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(obs_rows) == 1

            edge_rows = (
                (
                    await session.execute(
                        select(DirectionalEdge).where(
                            DirectionalEdge.leader_wallet_id == wallet_a,
                            DirectionalEdge.follower_wallet_id == wallet_b,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(edge_rows) == 1
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
            await compute_and_persist_directional_edges(
                session, cutoff=cutoff, config=_CONFIG, computed_at=_NOW
            )
        async with sessionmaker() as session, session.begin():
            await compute_and_persist_directional_edges(
                session, cutoff=cutoff, config=_CONFIG, computed_at=_NOW + timedelta(seconds=1)
            )

        async with sessionmaker() as session:
            obs_rows = (
                (
                    await session.execute(
                        select(LeadFollowObservation).where(
                            LeadFollowObservation.token_id == token_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(obs_rows) == 1

            edge_rows = (
                (
                    await session.execute(
                        select(DirectionalEdge).where(
                            DirectionalEdge.leader_wallet_id == wallet_a,
                            DirectionalEdge.follower_wallet_id == wallet_b,
                            DirectionalEdge.as_of == cutoff,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(edge_rows) == 1
    finally:
        await engine.dispose()


async def test_entry_after_cutoff_is_excluded(admin_engine) -> None:
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
            # Follower's entry is AFTER the cutoff -- must be excluded.
            await _seed_prospective_event(
                session,
                wallet_id=wallet_b,
                token_id=token_id,
                output_mint=mint,
                entered_at=_NOW + timedelta(minutes=10),
            )

        cutoff = _NOW + timedelta(minutes=5)
        async with sessionmaker() as session, session.begin():
            result = await compute_and_persist_directional_edges(
                session, cutoff=cutoff, config=_CONFIG, computed_at=_NOW
            )
        assert result.observation_count == 0
    finally:
        await engine.dispose()


def test_cli_graph_report_runs_and_prints_required_fields(admin_engine) -> None:
    result = runner.invoke(app, ["graph", "report", "--as-of", _NOW.isoformat()])
    assert result.exit_code == 0, result.output
    assert "top_directional_edges" in result.output
    assert "algorithm_version" in result.output
    assert "purely observational" in result.output


async def test_fsr05_forward_information_uses_followers_own_executable_return(
    admin_engine,
) -> None:
    """FSR-05: ``forward_information_after_leader_pct`` is the follower's
    own real 5m executable return -- never the always-``None`` placeholder
    the pre-recovery build persisted."""
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
            # 100 SOL-raw in -> 200 token-raw entry, then 200 token-raw ->
            # 400 SOL-raw reverse: ends with 4x the SOL spent => +300% gross.
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

        async with sessionmaker() as session, session.begin():
            result = await compute_and_persist_directional_edges(
                session, cutoff=_NOW + timedelta(hours=1), config=_CONFIG, computed_at=_NOW
            )
        assert len(result.edges) == 1
        edge = result.edges[0]

        async with sessionmaker() as session:
            row = (
                await session.execute(
                    select(DirectionalEdge).where(
                        DirectionalEdge.leader_wallet_id == wallet_a,
                        DirectionalEdge.follower_wallet_id == wallet_b,
                    )
                )
            ).scalar_one()
            assert row.forward_information_after_leader_pct == Decimal("300")
            assert row.forward_information_sample_count == 1
            assert row.forward_information_eligible_count == 1
            assert row.forward_information_missing_reason is None
            assert edge.edge.observation_count == 1
    finally:
        await engine.dispose()


async def test_fsr05_forward_information_missing_reason_when_no_executable_evidence(
    admin_engine,
) -> None:
    """FSR-05: when the follower has no 5m reverse-executable evidence at
    all, the mean stays ``None`` with an explicit, honest reason -- never
    a silent unexplained ``NULL``."""
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
            # Follower's entry never gets a shadow fill/reverse probe at all.
            await _seed_prospective_event(
                session,
                wallet_id=wallet_b,
                token_id=token_id,
                output_mint=mint,
                entered_at=_NOW + timedelta(seconds=30),
            )

        async with sessionmaker() as session, session.begin():
            await compute_and_persist_directional_edges(
                session, cutoff=_NOW + timedelta(hours=1), config=_CONFIG, computed_at=_NOW
            )

        async with sessionmaker() as session:
            row = (
                await session.execute(
                    select(DirectionalEdge).where(
                        DirectionalEdge.leader_wallet_id == wallet_a,
                        DirectionalEdge.follower_wallet_id == wallet_b,
                    )
                )
            ).scalar_one()
            assert row.forward_information_after_leader_pct is None
            assert row.forward_information_sample_count == 0
            assert row.forward_information_eligible_count == 0
            assert row.forward_information_missing_reason == (
                "NO_5M_EXECUTABLE_PROBE_FOR_FOLLOWER_ENTRIES"
            )
    finally:
        await engine.dispose()
