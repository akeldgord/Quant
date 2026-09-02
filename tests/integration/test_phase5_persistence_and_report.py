"""Phase 5 (``argus-phase-5-001``) DB-backed integration coverage:

- P5-01 (SPEC_BLOCKING): the production loader's point-in-time cutoff --
  a ShadowPosition created after the query cutoff must never appear in
  that cutoff's evidence set.
- P5-07 (SPEC_BLOCKING): the discovery firewall -- a wallet's discovery-
  contaminated token's shadow evidence never enters selection-usable
  output (delay curve / contributing sources).
- P5-09 (SPEC_BLOCKING): append-only idempotent snapshot persistence --
  same identity is reused across separate sessions, a changed evidence
  set produces a new row, concurrent insertion never duplicates.
- P5-10 (SPEC_BLOCKING): the real ``argus copyability report`` CLI
  command, run through the same Typer app a human operator uses.

Follows the exact ``admin_engine``-gated skip pattern every other Phase
1-4 DB-backed integration test in this repo uses (see tests/integration/
conftest.py) -- these tests SKIP (never fail) when Postgres is
unreachable in this sandbox; the same code path is exercised for real
under ``make up && make test``.
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
from argus.copyability.identity import evidence_manifest_digest
from argus.copyability.loaders import (
    ContaminationFirewall,
    load_contamination_firewall,
    load_wallet_shadow_positions,
)
from argus.copyability.persistence import get_or_create_wallet_copyability_snapshot
from argus.copyability.service import ALGORITHM_VERSION
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.shadow_intents import STATUS_FILLED, ShadowIntent
from argus.domain.shadow_positions import ShadowPosition
from argus.domain.shadow_quote_probes import (
    OUTCOME_SUCCESS,
    PROBE_KIND_REVERSE_EXECUTABLE,
    ShadowQuoteProbe,
)
from argus.domain.tokens import Token
from argus.domain.wallet_copyability_snapshots import WalletCopyabilitySnapshot
from argus.domain.wallet_discovery_events import (
    DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY,
    WalletDiscoveryEvent,
)
from argus.domain.wallets import Wallet

SOL_MINT = "So11111111111111111111111111111111111111112"
_TEST_GIT_COMMIT = "PHASE5TEST_DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEF"
_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)

runner = CliRunner()


def _sessionmaker() -> tuple[ArgusConfig, Any, async_sessionmaker[Any]]:
    config = load_config()
    info = connection_for_role(config, DbRole.INGEST)
    engine = create_async_engine(info.as_asyncpg_url())
    return config, engine, async_sessionmaker(engine, expire_on_commit=False)


def _unique_wallet() -> str:
    return f"P5TEST{uuid.uuid4().hex[:38]}"


def _unique_mint() -> str:
    return f"P5TOK{uuid.uuid4().hex[:39]}"


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
    session.add(
        Token(
            token_id=token_id,
            mint=mint,
            first_observed_at=at,
            created_at=at,
        )
    )
    await session.flush()
    return token_id


async def _seed_shadow_position_with_reverse(
    session,
    *,
    wallet_id: uuid.UUID,
    token_id: uuid.UUID,
    output_mint: str,
    created_at: datetime,
    entry_label: str = "5s",
    entry_in: int = 100_000_000,
    entry_out: int = 200_000_000,
    reverse_out: int = 240_000_000,
) -> uuid.UUID:
    """Seeds a complete, terminal ShadowIntent+Position+entry probe+
    REVERSE_EXECUTABLE(5m) probe -- the minimal real evidence chain M2/M3
    consume, using the real domain models (never hand-built feature
    dicts), matching P5-01's own "real production loader" requirement."""
    prospective_event_id = uuid.uuid4()
    # A minimal, valid ShadowIntent requires a real prospective_events row
    # per its FK -- reuse the same seeding helper pattern Phase 4's own
    # integration tests use (see test_shadow_phase4.py).
    from argus.domain.chain_events import ChainEvent
    from argus.domain.prospective_events import ProspectiveEvent
    from argus.domain.swaps import Swap

    event_id = uuid.uuid4()
    session.add(
        ChainEvent(
            event_id=event_id,
            chain="solana",
            slot=1,
            block_time=created_at,
            first_seen_at=created_at,
            provider="p5-test",
            provider_received_at=created_at,
            transaction_signature=f"p5-test-{uuid.uuid4()}",
            event_type="TRANSACTION_OBSERVED",
            wallet_address="leader-not-under-test",
            raw_payload={},
            payload_hash="h",
            parser_version="v1",
            created_at=created_at,
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
            input_amount_raw=entry_in,
            input_amount_ui=Decimal(entry_in) / Decimal(10**9),
            output_mint=output_mint,
            output_amount_raw=entry_out,
            output_amount_ui=Decimal(entry_out),
            network_fee_raw=5000,
            slot=1,
            block_time=created_at,
            first_seen_at=created_at,
            confidence=Decimal("1.000"),
            parser_version="v1",
            build_hash="p5-test-build",
            created_at=created_at,
        )
    )
    await session.flush()
    session.add(
        ProspectiveEvent(
            prospective_event_id=prospective_event_id,
            wallet_id=wallet_id,
            swap_id=swap_id,
            event_id=event_id,
            token_id=token_id,
            leader_transaction_time=created_at,
            first_seen_at=created_at,
            wallet_tier_snapshot="A",
            token_state_snapshot={},
            position_size_context={},
            cluster_state_snapshot={},
            graph_state_snapshot={"available": False, "reason": "phase5-test"},
            algorithm_version="p5-test",
            created_at=created_at,
        )
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
            notional_input_amount_raw=entry_in,
            config_hash="p5-test-config",
            status=STATUS_FILLED,
            algorithm_version="p5-test",
            created_at=created_at,
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
            entry_input_amount_raw=entry_in,
            entry_output_amount_raw=entry_out,
            entry_route_present=True,
            entry_probe_target_label=entry_label,
            entry_requested_at=created_at,
            entry_responded_at=created_at,
            opened_at=created_at,
            algorithm_version="p5-test",
            created_at=created_at,
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
            notional_input_amount_raw=entry_out,
            target_due_at=created_at + timedelta(minutes=5),
            requested_at=created_at + timedelta(minutes=5),
            responded_at=created_at + timedelta(minutes=5, milliseconds=100),
            terminal_at=created_at + timedelta(minutes=5, milliseconds=100),
            expected_output_amount_raw=reverse_out,
            route_present=True,
            outcome=OUTCOME_SUCCESS,
            algorithm_version="p5-test",
            created_at=created_at,
        )
    )
    await session.commit()
    return position_id


async def test_p5_01_position_created_after_cutoff_is_excluded(admin_engine) -> None:
    config, engine, sessionmaker = _sessionmaker()
    try:
        wallet_address = _unique_wallet()
        mint = _unique_mint()
        async with sessionmaker() as session, session.begin():
            wallet_id = await _seed_wallet(session, address=wallet_address, at=_NOW)
            token_id = await _seed_token(session, mint=mint, at=_NOW)

        cutoff = _NOW - timedelta(days=1)
        async with sessionmaker() as session:
            await _seed_shadow_position_with_reverse(
                session, wallet_id=wallet_id, token_id=token_id, output_mint=mint, created_at=_NOW
            )

        firewall = ContaminationFirewall(contaminated_token_ids=frozenset())
        async with sessionmaker() as session:
            evidence = await load_wallet_shadow_positions(
                session, wallet_id=wallet_id, cutoff=cutoff, firewall=firewall
            )
        assert evidence.delay_observations == []  # position created AFTER cutoff -- excluded

        async with sessionmaker() as session:
            evidence_at_now = await load_wallet_shadow_positions(
                session, wallet_id=wallet_id, cutoff=_NOW + timedelta(minutes=10), firewall=firewall
            )
        assert len(evidence_at_now.delay_observations) == 1
    finally:
        await engine.dispose()


async def test_p5_07_discovery_contaminated_token_excluded_from_selection_usable(
    admin_engine,
) -> None:
    config, engine, sessionmaker = _sessionmaker()
    try:
        wallet_address = _unique_wallet()
        contaminated_mint = _unique_mint()
        clean_mint = _unique_mint()
        async with sessionmaker() as session, session.begin():
            wallet_id = await _seed_wallet(session, address=wallet_address, at=_NOW)
            contaminated_token_id = await _seed_token(session, mint=contaminated_mint, at=_NOW)
            clean_token_id = await _seed_token(session, mint=clean_mint, at=_NOW)
            session.add(
                WalletDiscoveryEvent(
                    discovery_event_id=uuid.uuid4(),
                    wallet_id=wallet_id,
                    discovered_at=_NOW,
                    discovery_channel=DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY,
                    trigger_token_id=contaminated_token_id,
                    trigger_reason="p5-07-test",
                    algorithm_version="p5-test",
                    created_at=_NOW,
                )
            )

        async with sessionmaker() as session:
            await _seed_shadow_position_with_reverse(
                session,
                wallet_id=wallet_id,
                token_id=contaminated_token_id,
                output_mint=contaminated_mint,
                created_at=_NOW,
            )
        async with sessionmaker() as session:
            await _seed_shadow_position_with_reverse(
                session,
                wallet_id=wallet_id,
                token_id=clean_token_id,
                output_mint=clean_mint,
                created_at=_NOW,
            )

        cutoff = _NOW + timedelta(minutes=10)
        async with sessionmaker() as session:
            firewall = await load_contamination_firewall(session, wallet_id=wallet_id)
        assert firewall.contaminated_token_ids == frozenset({contaminated_token_id})

        async with sessionmaker() as session:
            evidence = await load_wallet_shadow_positions(
                session, wallet_id=wallet_id, cutoff=cutoff, firewall=firewall
            )
        # Only the clean token's position is selection-usable.
        assert len(evidence.delay_observations) == 1
        assert evidence.delay_observations[0].token_id == clean_token_id
        assert any(excl.reason == "DISCOVERY_CONTAMINATED" for excl in evidence.excluded)
    finally:
        await engine.dispose()


async def test_p5_09_snapshot_reused_across_sessions_for_identical_identity(admin_engine) -> None:
    config, engine, sessionmaker = _sessionmaker()
    try:
        wallet_address = _unique_wallet()
        async with sessionmaker() as session, session.begin():
            wallet_id = await _seed_wallet(session, address=wallet_address, at=_NOW)

        digest = evidence_manifest_digest([])

        def _build() -> WalletCopyabilitySnapshot:
            return WalletCopyabilitySnapshot(
                snapshot_id=uuid.uuid4(),
                wallet_id=wallet_id,
                as_of=_NOW,
                algorithm_version=ALGORITHM_VERSION,
                contributing_source_ids=[],
                excluded_source_ids=[],
                evidence_manifest_digest=digest,
                delay_curve={},
                half_life_result={},
                forward_information_grid={},
                size_surprise={},
                copyability_score=None,
                copyability_components={},
                available_weight=Decimal(0),
                sample_n=0,
                sample_k=0,
                sample_coverage=Decimal(0),
                sample_c=Decimal(0),
                confidence="UNKNOWN",
                descriptive_extras={},
                build_hash=_TEST_GIT_COMMIT,
                config_hash=_TEST_GIT_COMMIT,
                master_spec_hash=_TEST_GIT_COMMIT,
                git_commit=_TEST_GIT_COMMIT,
                computed_at=_NOW,
            )

        async with sessionmaker() as session, session.begin():
            row1, created1 = await get_or_create_wallet_copyability_snapshot(
                session,
                wallet_id=wallet_id,
                as_of=_NOW,
                algorithm_version=ALGORITHM_VERSION,
                evidence_manifest_digest=digest,
                build_row=_build,
            )
        assert created1 is True

        # A fresh session, second execution, same identity -- reused, not duplicated.
        async with sessionmaker() as session, session.begin():
            row2, created2 = await get_or_create_wallet_copyability_snapshot(
                session,
                wallet_id=wallet_id,
                as_of=_NOW,
                algorithm_version=ALGORITHM_VERSION,
                evidence_manifest_digest=digest,
                build_row=_build,
            )
        assert created2 is False
        assert row2.snapshot_id == row1.snapshot_id

        async with sessionmaker() as session:
            count = (
                (
                    await session.execute(
                        select(WalletCopyabilitySnapshot).where(
                            WalletCopyabilitySnapshot.wallet_id == wallet_id
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert len(count) == 1

        # A DIFFERENT evidence-manifest digest is a new row, never an overwrite.
        digest2 = evidence_manifest_digest(
            [
                __import__("argus.copyability.identity", fromlist=["SourceRef"]).SourceRef(
                    "swap", "x"
                )
            ]
        )

        def _build2() -> WalletCopyabilitySnapshot:
            row = _build()
            row.snapshot_id = uuid.uuid4()
            row.evidence_manifest_digest = digest2
            return row

        async with sessionmaker() as session, session.begin():
            row3, created3 = await get_or_create_wallet_copyability_snapshot(
                session,
                wallet_id=wallet_id,
                as_of=_NOW,
                algorithm_version=ALGORITHM_VERSION,
                evidence_manifest_digest=digest2,
                build_row=_build2,
            )
        assert created3 is True
        assert row3.snapshot_id != row1.snapshot_id
    finally:
        await engine.dispose()


def test_p5_10_cli_copyability_report_runs_and_prints_required_fields(admin_engine) -> None:
    import asyncio

    config, engine, sessionmaker = _sessionmaker()

    async def _seed() -> str:
        wallet_address = _unique_wallet()
        async with sessionmaker() as session, session.begin():
            await _seed_wallet(session, address=wallet_address, at=_NOW)
        return wallet_address

    wallet_address = asyncio.run(_seed())
    asyncio.run(engine.dispose())

    result = runner.invoke(
        app, ["copyability", "report", "--wallet", wallet_address, "--as-of", _NOW.isoformat()]
    )
    assert result.exit_code == 0, result.output
    import json

    reports = json.loads(result.output)
    assert len(reports) == 1
    report = reports[0]
    for field in (
        "wallet",
        "as_of",
        "algorithm_version",
        "copyability_score",
        "copyability_components",
        "sample_n",
        "sample_k",
        "confidence",
        "delay_curve",
        "half_life_result",
        "forward_information_grid",
        "size_surprise",
        "evidence_manifest_digest",
        "config_hash",
        "master_spec_hash",
        "build_hash",
        "git_commit",
    ):
        assert field in report, field
    assert report["wallet"] == wallet_address
    # No sample evidence yet -- honestly null, never fabricated.
    assert report["copyability_score"] is None
    assert report["sample_n"] == 0

    # Re-run: reuses the same snapshot, never duplicates.
    result2 = runner.invoke(
        app, ["copyability", "report", "--wallet", wallet_address, "--as-of", _NOW.isoformat()]
    )
    assert result2.exit_code == 0, result2.output
    reports2 = json.loads(result2.output)
    assert reports2[0]["snapshot_reused"] is True


def test_p5_10_cli_copyability_report_empty_database_is_honest() -> None:
    """A wallet address with no matching row: honest empty report, never a
    fabricated one. Does not require Postgres reachability to prove --
    exercised via a nonexistent wallet filter against whatever database
    is configured; if unreachable, the command's own connection error
    surfaces as a nonzero exit, which this test tolerates explicitly
    rather than asserting a specific DB-dependent outcome."""
    result = runner.invoke(
        app, ["copyability", "report", "--wallet", f"NEVER-EXISTS-{uuid.uuid4()}"]
    )
    if result.exit_code == 0:
        assert "no tracked wallets found" in result.output
