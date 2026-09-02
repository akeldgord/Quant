"""P4-R7 remediation coverage (argus-phase-4-remediation-001): proves the
isolation fix for ``scripts/argus_phase4_replay_demo.py`` actually holds.

The pre-remediation script ran the REPLAY demo against the shared
configured (dev) database and cleaned up in its ``finally`` block by
looking up its own fixture wallet's *address* and deleting every row
found under it -- so a wallet-insert failure against a pre-existing,
unrelated row at that same address would delete that row and its entire
history. The remediated script instead creates a brand-new, uniquely
named disposable Postgres database (prefix
``argus_phase4_replay_demo_``), points ``ARGUS_DB_NAME`` at it for the
run's duration, runs migrations and the full demo lifecycle against it,
and unconditionally ``DROP DATABASE``s it afterward -- never touching the
shared database at all.

This module never modifies ``scripts/argus_phase4_replay_demo.py``; it
invokes the real ``if __name__ == "__main__":`` entry point as a
subprocess (exactly as a human operator would run it) and asserts, from
outside, that pre-existing shared-database state is untouched -- both on
a clean run and with a fault injected at each of the script's 4 named
injection points.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from argus.config import ArgusConfig, load_config
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.chain_events import ChainEvent
from argus.domain.commitment import COMMITMENT_CONFIRMED, CommitmentObservation
from argus.domain.swaps import Swap
from argus.domain.wallet_score_snapshots import WalletScoreSnapshot
from argus.domain.wallet_tier_history import WalletTierTransition
from argus.domain.wallets import Wallet
from argus.providers.models import TokenSnapshot
from argus.shadow.monitor import run_prospective_monitoring_pass
from argus.shadow.quote_jobs import run_due_entry_probes

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "argus_phase4_replay_demo.py"

# Loaded the same way tests/phase_1_5/test_historical_feasibility.py loads
# scripts/phase_1_5_feasibility.py -- scripts/ is not a package. Only
# defines names at module scope (no main()/asyncio.run side effects), so
# importing it is safe at collection time.
_spec = importlib.util.spec_from_file_location("argus_phase4_replay_demo", SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
replay_demo = importlib.util.module_from_spec(_spec)
sys.modules["argus_phase4_replay_demo"] = replay_demo
_spec.loader.exec_module(replay_demo)

_SEED_NOW = datetime(2025, 1, 1, tzinfo=UTC)
SOL_MINT = "So11111111111111111111111111111111111111112"
_TEST_GIT_COMMIT = "P4R7ISOTEST_DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFAB"

FAULT_POINTS = [
    "before_create_database",
    "before_migration",
    "after_migration",
    "before_lifecycle",
]

# Every table a pre-existing shared-database wallet's identifying state
# (and its unrelated queued shadow work) lives in, keyed by wallet_id
# except where the table only has wallet_address.
_WALLET_ID_TABLES = (
    "wallets",
    "wallet_score_snapshots",
    "wallet_tier_history",
    "shadow_intents",
    "shadow_positions",
)
_WALLET_ADDRESS_TABLES = ("swaps", "chain_events")


def _unique_wallet() -> str:
    return f"P4ISO{uuid.uuid4().hex[:37]}"


def _sessionmaker() -> tuple[ArgusConfig, Any, async_sessionmaker[Any]]:
    config = load_config()
    info = connection_for_role(config, DbRole.INGEST)
    engine = create_async_engine(info.as_asyncpg_url())
    return config, engine, async_sessionmaker(engine, expire_on_commit=False)


def _run_script(
    output_dir: Path, env_overrides: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """F5-07 remediation: every invocation in this suite passes an explicit
    ``--output-dir`` (the caller's own pytest ``tmp_path``) rather than
    relying on the script's internal ``default_output_dir()`` tempdir --
    proving the P5-11 CLI flag itself works under test, with pytest owning
    the directory's lifecycle instead of an unmanaged OS tempdir."""
    env = {**os.environ}
    env.pop("_ARGUS_REPLAY_DEMO_FAULT_INJECT", None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--output-dir", str(output_dir)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


# ---------------------------------------------------------------------
# F5-07: prove the existing tracked historical replay-evidence artifacts
# are byte-for-byte unchanged before and after this entire integration
# suite runs -- this suite's own subprocess invocations of the replay
# script must never touch tracked orchestration/ evidence paths.
# ---------------------------------------------------------------------

_TRACKED_HISTORICAL_REPLAY_ARTIFACTS: tuple[Path, ...] = tuple(
    sorted((REPO_ROOT / "orchestration").glob("*/evidence/replay_*demo*.json"))
)


def _hash_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(autouse=True, scope="module")
def _tracked_historical_replay_artifacts_unchanged() -> Any:
    before = {path: _hash_file(path) for path in _TRACKED_HISTORICAL_REPLAY_ARTIFACTS}
    assert before, "expected at least one tracked historical replay-evidence artifact to exist"
    yield
    after = {path: _hash_file(path) for path in _TRACKED_HISTORICAL_REPLAY_ARTIFACTS}
    assert after == before, (
        "this integration suite must never modify tracked historical replay-"
        "evidence artifacts -- every subprocess invocation here uses an "
        "explicit tmp_path --output-dir"
    )


def _extract_json(stdout: str) -> dict[str, Any]:
    """The script's own stdout is ``json.dumps(events, indent=2)``
    followed by two plain-text summary lines -- pull out just the JSON
    object, tolerant of anything (e.g. alembic logging) printed first."""
    start = stdout.index("{")
    obj, _ = json.JSONDecoder().raw_decode(stdout[start:])
    return obj


async def _seed_wallet_with_buy_swap(
    session: Any, *, wallet_address: str, mint: str, at: datetime
) -> tuple[uuid.UUID, uuid.UUID]:
    """Real wallets/wallet_score_snapshots/wallet_tier_history/
    chain_events/commitment_observations/swaps rows for one tracked
    (tier A, qualifying score) wallet -- style mirrors
    tests/integration/test_shadow_phase4.py's
    ``_seed_tracked_wallet_with_buy_swap``."""
    wallet_id = uuid.uuid4()
    session.add(
        Wallet(
            wallet_id=wallet_id,
            wallet_address=wallet_address,
            first_discovered_at=at,
            current_tier="A",
            created_at=at,
        )
    )
    await session.flush()
    score_id = uuid.uuid4()
    session.add(
        WalletScoreSnapshot(
            score_id=score_id,
            wallet_id=wallet_id,
            as_of=at,
            score_version="p4r7-isolation-test-v1",
            descriptive_score=Decimal("90.000"),
            qualification_score=Decimal("90.000"),
            component_values={},
            penalties={},
            confidence="HIGH",
            excluded_discovery_token_ids=[],
            eligible_for_qualification=True,
            sample_gate_reason="p4r7_isolation_test",
            build_hash="p4r7-isolation-test-build",
            config_hash="p4r7-isolation-test-config",
            master_spec_hash="p4r7-isolation-test-spec",
            git_commit=_TEST_GIT_COMMIT,
            created_at=at,
        )
    )
    session.add(
        WalletTierTransition(
            transition_id=uuid.uuid4(),
            wallet_id=wallet_id,
            source_score_id=score_id,
            from_tier=None,
            to_tier="A",
            reason="p4r7-isolation-test",
            transitioned_at=at,
            created_at=at,
        )
    )
    event_id = uuid.uuid4()
    session.add(
        ChainEvent(
            event_id=event_id,
            chain="solana",
            slot=1,
            block_time=at,
            first_seen_at=at,
            provider="helius",
            provider_received_at=at,
            transaction_signature=f"p4r7-iso-buy-{uuid.uuid4()}",
            event_type="TRANSACTION_OBSERVED",
            wallet_address=wallet_address,
            raw_payload={},
            payload_hash="h",
            parser_version="v1",
            created_at=at,
        )
    )
    await session.flush()
    session.add(
        CommitmentObservation(
            observation_id=uuid.uuid4(),
            event_id=event_id,
            commitment_level=COMMITMENT_CONFIRMED,
            transaction_succeeded=True,
            observed_at=at,
            provider="helius",
            provider_received_at=at,
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
            output_amount_raw=1_000_000,
            output_amount_ui=Decimal("1"),
            network_fee_raw=5000,
            slot=1,
            block_time=at,
            first_seen_at=at,
            confidence=Decimal("1.000"),
            parser_version="v1",
            build_hash="p4r7-isolation-test-build",
            created_at=at,
        )
    )
    await session.flush()
    return wallet_id, swap_id


async def _seed_unrelated_wallet_with_due_queue(
    config: ArgusConfig, sessionmaker: async_sessionmaker[Any]
) -> dict[str, Any]:
    """Seeds one pre-existing tracked wallet in the SHARED database with
    a full history (wallet/score/tier/swap) plus real, currently-due,
    unclaimed queued work: 5 still-pending ENTRY_DELAY probes, 1 filled
    (SUCCESS) entry probe whose fill created a ShadowPosition, and that
    position's 5 due-but-unclaimed REVERSE_EXECUTABLE probes and 7 (one
    per mark horizon: 5m/30m/1h/6h/24h/3d/7d) due-but-unclaimed
    shadow_mark_outcomes rows -- all unrelated to anything the REPLAY
    demo script itself creates."""
    wallet_address = _unique_wallet()
    mint = f"P4ISOMint{uuid.uuid4().hex[:32]}"
    async with sessionmaker() as session, session.begin():
        wallet_id, swap_id = await _seed_wallet_with_buy_swap(
            session, wallet_address=wallet_address, mint=mint, at=_SEED_NOW
        )

    pass_result = await run_prospective_monitoring_pass(
        sessionmaker, config=config, now=_SEED_NOW + timedelta(seconds=1)
    )
    assert len(pass_result.shadow_intents) == 1
    intent = pass_result.shadow_intents[0]

    entry_due_at = _SEED_NOW + timedelta(seconds=1)  # the "1s" probe's due time
    actual_requested_at = entry_due_at + timedelta(seconds=2, milliseconds=700)
    actual_responded_at = actual_requested_at + timedelta(milliseconds=100)
    clock = replay_demo._ScriptedClock(
        [actual_requested_at, actual_responded_at, actual_responded_at + timedelta(milliseconds=5)]
    )
    provider = replay_demo.QueuedExecutionProvider(
        queue=[
            replay_demo._quote(
                input_mint=intent.input_mint,
                output_mint=intent.output_mint,
                in_amount=intent.notional_input_amount_raw,
                out_amount=500_000,
            )
        ]
    )
    market = replay_demo.QueuedMarketDataProvider(
        queue=[
            TokenSnapshot(
                provider="dexscreener-fake-p4r7-iso",
                mint=intent.output_mint,
                price_usd=Decimal("1.00"),
                pairs_found=1,
                raw={},
            )
        ]
    )
    filled = await run_due_entry_probes(
        sessionmaker,
        provider,
        config=config,
        clock=clock,
        now=actual_requested_at + timedelta(seconds=10),
        market_provider=market,
        limit=1,
    )
    assert len(filled) == 1
    assert filled[0].outcome == "SUCCESS"

    return {"wallet_id": wallet_id, "wallet_address": wallet_address, "swap_id": swap_id}


async def _cleanup_wallet(admin_engine: AsyncEngine, wallet_address: str) -> None:
    async with admin_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT wallet_id FROM wallets WHERE wallet_address = :w"),
                {"w": wallet_address},
            )
        ).fetchone()
        if row is not None:
            wid = row[0]
            await conn.execute(
                text(
                    "DELETE FROM shadow_mark_outcomes WHERE shadow_position_id IN "
                    "(SELECT shadow_position_id FROM shadow_positions WHERE wallet_id = :w)"
                ),
                {"w": wid},
            )
            await conn.execute(
                text(
                    "DELETE FROM shadow_quote_probes WHERE shadow_position_id IN "
                    "(SELECT shadow_position_id FROM shadow_positions WHERE wallet_id = :w) "
                    "OR shadow_intent_id IN "
                    "(SELECT shadow_intent_id FROM shadow_intents WHERE wallet_id = :w)"
                ),
                {"w": wid},
            )
            await conn.execute(
                text("DELETE FROM shadow_positions WHERE wallet_id = :w"), {"w": wid}
            )
            await conn.execute(text("DELETE FROM shadow_intents WHERE wallet_id = :w"), {"w": wid})
            await conn.execute(
                text("DELETE FROM prospective_events WHERE wallet_id = :w"), {"w": wid}
            )
            await conn.execute(
                text("DELETE FROM wallet_tier_history WHERE wallet_id = :w"), {"w": wid}
            )
            await conn.execute(
                text("DELETE FROM wallet_score_snapshots WHERE wallet_id = :w"), {"w": wid}
            )
            await conn.execute(
                text("DELETE FROM swaps WHERE wallet_address = :addr"), {"addr": wallet_address}
            )
            await conn.execute(
                text(
                    "DELETE FROM commitment_observations WHERE event_id IN "
                    "(SELECT event_id FROM chain_events WHERE wallet_address = :addr)"
                ),
                {"addr": wallet_address},
            )
            await conn.execute(
                text("DELETE FROM chain_events WHERE wallet_address = :addr"),
                {"addr": wallet_address},
            )
            await conn.execute(text("DELETE FROM wallets WHERE wallet_id = :w"), {"w": wid})
        await conn.commit()


def _row_key(row: dict[str, Any]) -> str:
    return json.dumps(row, default=str, sort_keys=True)


async def _fetch_rows(conn: Any, table: str, column: str, value: Any) -> list[dict[str, Any]]:
    result = await conn.execute(text(f"SELECT * FROM {table} WHERE {column} = :v"), {"v": value})
    rows: list[Row[Any]] = result.mappings().all()
    return sorted((dict(r) for r in rows), key=_row_key)


async def _snapshot(
    admin_engine: AsyncEngine, *, wallet_id: uuid.UUID, wallet_address: str
) -> dict[str, list[dict[str, Any]]]:
    """A byte-for-byte snapshot of every row this wallet's tracked
    history and queued shadow work lives in: the wallet itself, its
    score/tier/swap rows, and (via its shadow_intents/shadow_positions)
    every shadow_quote_probes/shadow_mark_outcomes row -- the exact
    "pre-existing wallets/history/jobs" P4-R7 promises stay byte-for-byte
    unchanged."""
    snap: dict[str, list[dict[str, Any]]] = {}
    async with admin_engine.connect() as conn:
        for table in _WALLET_ID_TABLES:
            snap[table] = await _fetch_rows(conn, table, "wallet_id", wallet_id)
        for table in _WALLET_ADDRESS_TABLES:
            snap[table] = await _fetch_rows(conn, table, "wallet_address", wallet_address)

        intent_ids = [r["shadow_intent_id"] for r in snap["shadow_intents"]]
        position_ids = [r["shadow_position_id"] for r in snap["shadow_positions"]]

        probe_rows: list[dict[str, Any]] = []
        if intent_ids:
            probe_rows += await _fetch_rows(
                conn, "shadow_quote_probes", "shadow_intent_id", intent_ids[0]
            )
        for pid in position_ids:
            probe_rows += await _fetch_rows(conn, "shadow_quote_probes", "shadow_position_id", pid)
        snap["shadow_quote_probes"] = sorted(probe_rows, key=_row_key)

        mark_rows: list[dict[str, Any]] = []
        for pid in position_ids:
            mark_rows += await _fetch_rows(conn, "shadow_mark_outcomes", "shadow_position_id", pid)
        snap["shadow_mark_outcomes"] = sorted(mark_rows, key=_row_key)
    return snap


def _assert_seed_present(snapshot: dict[str, list[dict[str, Any]]]) -> None:
    assert len(snapshot["wallets"]) == 1
    assert len(snapshot["wallet_score_snapshots"]) == 1
    assert len(snapshot["wallet_tier_history"]) == 1
    assert len(snapshot["swaps"]) == 1
    assert len(snapshot["shadow_intents"]) == 1
    assert len(snapshot["shadow_positions"]) == 1
    # 6 ENTRY_DELAY (1 filled/SUCCESS, 5 still-pending) + 5 REVERSE_EXECUTABLE
    # (scheduled by the fill), all real due-or-pending queued work.
    assert len(snapshot["shadow_quote_probes"]) == 11
    pending_probes = [p for p in snapshot["shadow_quote_probes"] if p["outcome"] == "PENDING"]
    assert len(pending_probes) == 10
    assert len(snapshot["shadow_mark_outcomes"]) == 7
    assert all(m["outcome"] == "PENDING" for m in snapshot["shadow_mark_outcomes"])
    assert all(m["claimed_at"] is None for m in snapshot["shadow_mark_outcomes"])


# ---------------------------------------------------------------------
# 1. A successful run leaves pre-existing shared-database state
#    byte-for-byte unchanged.
# ---------------------------------------------------------------------


async def test_successful_run_leaves_shared_wallet_and_queue_untouched(
    admin_engine, tmp_path: Path
) -> None:
    config, engine, sessionmaker = _sessionmaker()
    seeded: dict[str, Any] | None = None
    try:
        seeded = await _seed_unrelated_wallet_with_due_queue(config, sessionmaker)
        before = await _snapshot(
            admin_engine, wallet_id=seeded["wallet_id"], wallet_address=seeded["wallet_address"]
        )
        _assert_seed_present(before)

        result = _run_script(tmp_path)
        assert result.returncode == 0, (
            f"successful run expected, got exit {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

        after = await _snapshot(
            admin_engine, wallet_id=seeded["wallet_id"], wallet_address=seeded["wallet_address"]
        )
        assert after == before
    finally:
        if seeded is not None:
            await _cleanup_wallet(admin_engine, seeded["wallet_address"])
        await engine.dispose()


# ---------------------------------------------------------------------
# 2. A fault injected at each of the 4 named points still leaves
#    pre-existing shared-database state byte-for-byte unchanged.
# ---------------------------------------------------------------------


@pytest.mark.parametrize("fault_point", FAULT_POINTS)
async def test_fault_injection_leaves_shared_wallet_and_queue_untouched(
    admin_engine, fault_point: str, tmp_path: Path
) -> None:
    config, engine, sessionmaker = _sessionmaker()
    seeded: dict[str, Any] | None = None
    try:
        seeded = await _seed_unrelated_wallet_with_due_queue(config, sessionmaker)
        before = await _snapshot(
            admin_engine, wallet_id=seeded["wallet_id"], wallet_address=seeded["wallet_address"]
        )
        _assert_seed_present(before)

        result = _run_script(tmp_path, {"_ARGUS_REPLAY_DEMO_FAULT_INJECT": fault_point})
        assert result.returncode != 0, (
            f"fault injection at {fault_point!r} was expected to fail the run\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

        after = await _snapshot(
            admin_engine, wallet_id=seeded["wallet_id"], wallet_address=seeded["wallet_address"]
        )
        assert after == before, f"fault_point={fault_point}"
    finally:
        if seeded is not None:
            await _cleanup_wallet(admin_engine, seeded["wallet_address"])
        await engine.dispose()


# ---------------------------------------------------------------------
# 3. refuse_unless_scratch_database refuses any non-scratch target
#    before any write/network -- unit-level, no Postgres needed.
# ---------------------------------------------------------------------


def test_refuse_unless_scratch_database_rejects_non_scratch_names() -> None:
    for bad_name in [
        "argus",
        "argus_dev",
        "postgres",
        "argus_phase4",
        "notargus_phase4_replay_demo_abc123",
    ]:
        with pytest.raises(replay_demo.UnsafeReplayDatabaseTargetError):
            replay_demo.refuse_unless_scratch_database(bad_name)


def test_refuse_unless_scratch_database_allows_scratch_prefixed_names() -> None:
    for ok_name in [
        replay_demo.SCRATCH_DATABASE_PREFIX + "abc123",
        replay_demo._new_scratch_database_name(),
    ]:
        replay_demo.refuse_unless_scratch_database(ok_name)  # must not raise


# ---------------------------------------------------------------------
# 4. The scratch database is really dropped after a successful run --
#    proving cleanup is real, not just claimed.
# ---------------------------------------------------------------------


async def test_scratch_database_is_actually_dropped_after_successful_run(
    admin_engine, tmp_path: Path
) -> None:
    result = _run_script(tmp_path)
    assert result.returncode == 0, (
        f"successful run expected, got exit {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    events = _extract_json(result.stdout)
    scratch_name = events["scratch_database"]
    assert scratch_name.startswith(replay_demo.SCRATCH_DATABASE_PREFIX)

    async with admin_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": scratch_name}
            )
        ).fetchone()
    assert row is None, f"scratch database {scratch_name!r} was not dropped"
