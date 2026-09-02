"""Alembic migration tests (Phase 1 remediation round 3, finding #5):
migration-from-zero, upgrade-from-0003/0005, downgrade, idempotency, and
restart-safety for the ``parse_attempts`` build/config/MASTER_SPEC/git
identity columns added by migration 0006.

Every test here runs against a brand-new, disposable scratch Postgres
database -- created and dropped per test -- never against the shared dev
database ``tests/integration/conftest.py``'s ``admin_engine`` fixture
uses (which every other integration test assumes is already migrated to
head; running destructive downgrade/upgrade cycles against it would break
every other test in the suite). Skips (never fails) if Postgres isn't
reachable or the admin role can't create a database -- the real
acceptance check (``make up && make test``) always exercises this for
real.

Alembic's own ``env.py`` resolves its target database from
``ARGUS_DB_NAME`` (via ``ArgusConfig``/``connection_for_admin``) fresh on
every invocation, so pointing a migration command at the scratch database
is just overriding that one environment variable for the duration of the
command -- see ``scratch_database`` below.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from argus.clock import Clock
from argus.config import REPO_ROOT, load_config
from argus.db.connection import connection_for_admin, connection_for_role
from argus.db.roles import DbRole

_IDENTITY_COLUMNS = ("build_hash", "config_hash", "master_spec_hash", "git_commit")
_BACKFILL_SENTINEL = "NOT_CAPTURED_PRE_R3_REMEDIATION"


def _alembic_config() -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return cfg


async def _maintenance_execute(sql: str) -> None:
    """Runs one autocommit DDL statement (CREATE/DROP DATABASE, which
    Postgres refuses inside a transaction block) against the maintenance
    ``postgres`` database, using the same admin credentials every other
    migration/DDL operation in this repo uses."""
    admin = connection_for_admin(load_config())
    maintenance = dataclasses.replace(admin, database="postgres")
    engine = create_async_engine(maintenance.as_asyncpg_url(), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(sql))
    finally:
        await engine.dispose()


def _query(database: str, sql: str, params: dict[str, Any] | None = None) -> list[Any]:
    async def _run() -> list[Any]:
        admin = dataclasses.replace(connection_for_admin(load_config()), database=database)
        engine = create_async_engine(admin.as_asyncpg_url())
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text(sql), params or {})
                return list(result)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _execute(database: str, sql: str, params: dict[str, Any] | None = None) -> None:
    async def _run() -> None:
        admin = dataclasses.replace(connection_for_admin(load_config()), database=database)
        engine = create_async_engine(admin.as_asyncpg_url())
        try:
            async with engine.connect() as conn:
                await conn.execute(text(sql), params or {})
                await conn.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


@pytest.fixture
def scratch_database() -> Iterator[str]:
    """Creates a fresh, empty Postgres database for exactly one test and
    drops it afterward. Yields the database name; while this fixture is
    active, ``ARGUS_DB_NAME`` is overridden so every ``load_config()``
    call (including alembic's own ``env.py``) targets it instead of the
    shared dev database."""
    name = f"argus_migration_test_{uuid.uuid4().hex[:12]}"
    try:
        asyncio.run(_maintenance_execute(f'CREATE DATABASE "{name}"'))
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"Postgres not reachable / cannot create a scratch database: {exc}")

    previous = os.environ.get("ARGUS_DB_NAME")
    os.environ["ARGUS_DB_NAME"] = name
    try:
        yield name
    finally:
        if previous is None:
            os.environ.pop("ARGUS_DB_NAME", None)
        else:
            os.environ["ARGUS_DB_NAME"] = previous
        asyncio.run(_maintenance_execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def _column_names(database: str, table: str) -> set[str]:
    rows = _query(
        database,
        "SELECT column_name FROM information_schema.columns WHERE table_name = :t",
        {"t": table},
    )
    return {r[0] for r in rows}


def _check_constraint_names(database: str, table: str) -> set[str]:
    rows = _query(
        database,
        """
        SELECT con.conname FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        WHERE rel.relname = :t AND con.contype = 'c'
        """,
        {"t": table},
    )
    return {r[0] for r in rows}


def _unique_constraint_names(database: str, table: str) -> set[str]:
    rows = _query(
        database,
        """
        SELECT con.conname FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        WHERE rel.relname = :t AND con.contype = 'u'
        """,
        {"t": table},
    )
    return {r[0] for r in rows}


def _current_revision(database: str) -> str:
    rows = _query(database, "SELECT version_num FROM alembic_version")
    assert len(rows) == 1  # exactly one row, never duplicated across upgrades
    return str(rows[0][0])


def test_migration_from_zero_to_head_creates_identity_columns(scratch_database: str) -> None:
    command.upgrade(_alembic_config(), "head")

    assert _current_revision(scratch_database) == "0021"
    columns = _column_names(scratch_database, "parse_attempts")
    assert set(_IDENTITY_COLUMNS).issubset(columns)
    constraints = _check_constraint_names(scratch_database, "parse_attempts")
    for column in _IDENTITY_COLUMNS:
        assert f"ck_parse_attempts_{column}_nonempty" in constraints


def test_upgrade_from_0003_through_head_creates_table_and_columns_together(
    scratch_database: str,
) -> None:
    """0003 predates ``parse_attempts`` entirely (it's created in 0004) --
    replaying 0004 -> 0005 -> 0006 in one continuous upgrade from that
    baseline exercises table creation, the independent 0005 column, and
    the identity columns/constraints all landing correctly in sequence,
    not just a direct jump to head on an empty database."""
    cfg = _alembic_config()
    command.upgrade(cfg, "0003")
    assert _current_revision(scratch_database) == "0003"
    existing_tables = {
        r[0]
        for r in _query(
            scratch_database,
            "SELECT table_name FROM information_schema.tables WHERE table_name = 'parse_attempts'",
        )
    }
    assert "parse_attempts" not in existing_tables

    command.upgrade(cfg, "head")
    assert _current_revision(scratch_database) == "0021"
    columns = _column_names(scratch_database, "parse_attempts")
    assert set(_IDENTITY_COLUMNS).issubset(columns)


def test_upgrade_from_0005_backfills_sentinel_on_preexisting_rows(scratch_database: str) -> None:
    """A row recorded under round 2's schema (0004/0005, before the
    identity columns existed) must never be silently dropped or rewritten
    with a fabricated value -- migration 0006 backfills the explicit,
    honest sentinel, and the CHECK constraints must accept it (it is
    non-empty) without touching the row's other, pre-existing fields."""
    cfg = _alembic_config()
    command.upgrade(cfg, "0005")
    assert "build_hash" not in _column_names(scratch_database, "parse_attempts")

    event_id = str(uuid.uuid4())
    attempt_id = str(uuid.uuid4())
    now = datetime(2026, 1, 1, tzinfo=UTC)
    _execute(
        scratch_database,
        """
        INSERT INTO chain_events (
            event_id, chain, slot, first_seen_at, provider, provider_received_at,
            transaction_signature, event_type, wallet_address, raw_payload,
            payload_hash, parser_version, created_at
        ) VALUES (
            :event_id, 'solana', 1, :now, 'pre-r3-test', :now,
            :sig, 'TRANSACTION_OBSERVED', 'PreR3Wallet1111111111111111111111111111', '{}',
            'deadbeef', 'v1', :now
        )
        """,
        {"event_id": event_id, "now": now, "sig": f"pre-r3-sig-{uuid.uuid4().hex[:8]}"},
    )
    _execute(
        scratch_database,
        """
        INSERT INTO parse_attempts (
            attempt_id, event_id, parser_version, attempted_at, outcome,
            input_payload_hash, retry_disposition, created_at
        ) VALUES (
            :attempt_id, :event_id, 'v1', :now, 'SUCCESS', 'deadbeef', 'NOT_APPLICABLE', :now
        )
        """,
        {"attempt_id": attempt_id, "event_id": event_id, "now": now},
    )

    command.upgrade(cfg, "0006")

    rows = _query(
        scratch_database,
        "SELECT build_hash, config_hash, master_spec_hash, git_commit FROM parse_attempts "
        "WHERE attempt_id = :a",
        {"a": attempt_id},
    )
    assert len(rows) == 1
    assert all(value == _BACKFILL_SENTINEL for value in rows[0])

    # The CHECK constraint genuinely enforces non-empty at the database
    # layer -- an application bug that tries to insert an empty identity
    # value is rejected, not silently accepted.
    with pytest.raises(Exception, match="ck_parse_attempts_build_hash_nonempty|violates check"):
        _execute(
            scratch_database,
            """
            INSERT INTO parse_attempts (
                attempt_id, event_id, parser_version, attempted_at, outcome,
                input_payload_hash, retry_disposition, build_hash, config_hash,
                master_spec_hash, git_commit, created_at
            ) VALUES (
                :attempt_id, :event_id, 'v1', :now, 'SUCCESS', 'deadbeef', 'NOT_APPLICABLE',
                '', 'real-config-hash', 'real-spec-hash', 'real-git-commit', :now
            )
            """,
            {"attempt_id": str(uuid.uuid4()), "event_id": event_id, "now": now},
        )


def test_downgrade_to_0005_drops_identity_columns_and_constraints(scratch_database: str) -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    assert set(_IDENTITY_COLUMNS).issubset(_column_names(scratch_database, "parse_attempts"))

    command.downgrade(cfg, "0005")

    assert _current_revision(scratch_database) == "0005"
    columns = _column_names(scratch_database, "parse_attempts")
    assert not set(_IDENTITY_COLUMNS) & columns
    assert not _check_constraint_names(scratch_database, "parse_attempts") & {
        f"ck_parse_attempts_{c}_nonempty" for c in _IDENTITY_COLUMNS
    }


def test_upgrade_head_is_idempotent_and_restart_safe(scratch_database: str) -> None:
    """Simulates a service that runs "migrate to head" on every process
    start: running the upgrade a second time against an already-current
    database must be a safe no-op, not an error and not a duplicated
    ``alembic_version`` row."""
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    first_columns = _column_names(scratch_database, "parse_attempts")

    command.upgrade(cfg, "head")  # simulated restart

    assert _current_revision(scratch_database) == "0021"
    assert _column_names(scratch_database, "parse_attempts") == first_columns


def test_downgrade_then_upgrade_restores_identity_columns_cleanly(scratch_database: str) -> None:
    """A downgrade followed by re-upgrading (e.g. an operator rolling
    back then forward again) must land in exactly the same schema state
    as a direct upgrade -- no leftover constraint/column from the first
    pass, no missing one from the second."""
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0005")
    command.upgrade(cfg, "head")

    assert _current_revision(scratch_database) == "0021"
    columns = _column_names(scratch_database, "parse_attempts")
    assert set(_IDENTITY_COLUMNS).issubset(columns)
    constraints = _check_constraint_names(scratch_database, "parse_attempts")
    for column in _IDENTITY_COLUMNS:
        assert f"ck_parse_attempts_{column}_nonempty" in constraints


# --- Phase 1 remediation round 5, finding #8: migration 0007's downgrade()
# --- against a *populated* database, not an empty one -- the previous
# --- round's claimed downgrade-to-base result never actually proved
# --- anything about what downgrading does once real swaps rows exist.


def _insert_chain_event(database: str, event_id: str, *, signature: str) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    _execute(
        database,
        """
        INSERT INTO chain_events (
            event_id, chain, slot, first_seen_at, provider, provider_received_at,
            transaction_signature, event_type, wallet_address, raw_payload,
            payload_hash, parser_version, created_at
        ) VALUES (
            :event_id, 'solana', 1, :now, 'r5-migration-test', :now,
            :sig, 'TRANSACTION_OBSERVED', 'R5MigrationTestWallet11111111111111111111', '{}',
            'deadbeef', 'v1', :now
        )
        """,
        {"event_id": event_id, "now": now, "sig": signature},
    )


def _insert_swap(
    database: str, *, swap_id: str, event_id: str, parser_version: str, build_hash: str
) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    _execute(
        database,
        """
        INSERT INTO swaps (
            swap_id, event_id, wallet_address, classification, slot, first_seen_at,
            confidence, parser_version, build_hash, created_at
        ) VALUES (
            :swap_id, :event_id, 'R5MigrationTestWallet11111111111111111111', 'SWAP_SIMPLE', 1,
            :now, 1.000, :parser_version, :build_hash, :now
        )
        """,
        {
            "swap_id": swap_id,
            "event_id": event_id,
            "parser_version": parser_version,
            "build_hash": build_hash,
            "now": now,
        },
    )


def test_downgrade_from_0007_succeeds_with_a_single_build_hash_per_event(
    scratch_database: str,
) -> None:
    """The common, fully-supported case: at most one parser build has
    ever produced a swaps row per (event_id, parser_version) -- proven
    here against a genuinely populated 'swaps' table, not an empty one."""
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    event_id = str(uuid.uuid4())
    _insert_chain_event(scratch_database, event_id, signature=f"r5-sig-{uuid.uuid4().hex[:8]}")
    _insert_swap(
        scratch_database,
        swap_id=str(uuid.uuid4()),
        event_id=event_id,
        parser_version="v1",
        build_hash="build-a",
    )

    command.downgrade(cfg, "0006")

    assert _current_revision(scratch_database) == "0006"
    assert "build_hash" not in _column_names(scratch_database, "swaps")
    assert "uq_swaps_event_id_parser_version" in _unique_constraint_names(scratch_database, "swaps")
    # The row itself survives the downgrade untouched -- only the schema
    # around it changed.
    rows = _query(
        scratch_database, "SELECT classification FROM swaps WHERE event_id = :e", {"e": event_id}
    )
    assert len(rows) == 1
    assert rows[0][0] == "SWAP_SIMPLE"


def test_downgrade_from_0007_fails_closed_with_multiple_build_hashes_per_event(
    scratch_database: str,
) -> None:
    """The case migration 0007 exists specifically to allow: two
    different parser builds, same version label, both honestly recording
    a swaps row for the same event. Downgrading cannot represent this
    under the narrower pre-0007 (event_id, parser_version) uniqueness --
    it must refuse with a precise, actionable reason, and must leave the
    schema and every row completely untouched (never partially applying
    the downgrade, never silently deleting/merging/selecting one row)."""
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    event_id = str(uuid.uuid4())
    _insert_chain_event(scratch_database, event_id, signature=f"r5-sig-{uuid.uuid4().hex[:8]}")
    swap_id_a = str(uuid.uuid4())
    swap_id_b = str(uuid.uuid4())
    _insert_swap(
        scratch_database,
        swap_id=swap_id_a,
        event_id=event_id,
        parser_version="v1",
        build_hash="build-a",
    )
    _insert_swap(
        scratch_database,
        swap_id=swap_id_b,
        event_id=event_id,
        parser_version="v1",
        build_hash="build-b",
    )

    with pytest.raises(Exception, match="cannot downgrade past revision 0007"):
        command.downgrade(cfg, "0006")

    # Refused before touching anything: still at head, build_hash column
    # and both append-only rows still present and unmodified.
    assert _current_revision(scratch_database) == "0021"
    assert "build_hash" in _column_names(scratch_database, "swaps")
    rows = _query(
        scratch_database,
        "SELECT swap_id, build_hash FROM swaps WHERE event_id = :e ORDER BY build_hash",
        {"e": event_id},
    )
    assert [(str(r[0]), r[1]) for r in rows] == [
        (swap_id_a, "build-a"),
        (swap_id_b, "build-b"),
    ]


# --- Phase 2 remediation (argus-phase-2-remediation-001), finding P2-R7:
# --- supply_raw/amount_raw widened from signed BIGINT to an exact
# --- unsigned-64-bit-capable NUMERIC(39,10) with range/integrality CHECK
# --- constraints (migration 0009). See src/argus/domain/u64.py.

_U64_MAX = 2**64 - 1
_BIGINT_MAX = 2**63 - 1


def _insert_token(database: str, token_id: str, mint: str) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    _execute(
        database,
        """
        INSERT INTO tokens (token_id, mint, chain, first_observed_at, mint_validated, created_at)
        VALUES (:token_id, :mint, 'solana', :now, false, :now)
        """,
        {"token_id": token_id, "mint": mint, "now": now},
    )


def test_p2r7_upgrade_to_0009_round_trips_u64_boundary_values(scratch_database: str) -> None:
    """0/1/2**63/2**64-1 all store and read back exactly, unchanged, in
    the widened ``token_market_snapshots.supply_raw`` column -- values
    that (2**63 and above) could never even be stored under the
    pre-0009 signed BIGINT column at all."""
    cfg = _alembic_config()
    command.upgrade(cfg, "head")

    token_id = str(uuid.uuid4())
    _insert_token(scratch_database, token_id, f"P2R7Mint{uuid.uuid4().hex[:36]}")

    boundary_values = [0, 1, 2**63, _U64_MAX]
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for i, value in enumerate(boundary_values):
        _execute(
            scratch_database,
            """
            INSERT INTO token_market_snapshots (
                snapshot_id, token_id, observed_at, lifecycle_stage, supply_raw,
                source, algorithm_version, build_hash, created_at
            ) VALUES (
                :snapshot_id, :token_id, :now, 'TOKEN_CREATION', :supply_raw,
                'p2r7-test', 'v1', 'deadbeef', :now
            )
            """,
            {
                "snapshot_id": str(uuid.uuid4()),
                "token_id": token_id,
                "now": now.replace(microsecond=i),
                "supply_raw": value,
            },
        )

    rows = _query(
        scratch_database,
        "SELECT supply_raw FROM token_market_snapshots WHERE token_id = :t ORDER BY supply_raw",
        {"t": token_id},
    )
    stored = [int(r[0]) for r in rows]
    assert stored == sorted(boundary_values)
    for value in stored:
        assert isinstance(value, int)


def test_p2r7_0009_rejects_negative_and_out_of_range_supply_raw(scratch_database: str) -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    token_id = str(uuid.uuid4())
    _insert_token(scratch_database, token_id, f"P2R7Mint{uuid.uuid4().hex[:36]}")
    now = datetime(2026, 1, 1, tzinfo=UTC)

    def _insert(value: Any) -> None:
        _execute(
            scratch_database,
            """
            INSERT INTO token_market_snapshots (
                snapshot_id, token_id, observed_at, lifecycle_stage, supply_raw,
                source, algorithm_version, build_hash, created_at
            ) VALUES (
                :snapshot_id, :token_id, :now, 'TOKEN_CREATION', :supply_raw,
                'p2r7-test', 'v1', 'deadbeef', :now
            )
            """,
            {
                "snapshot_id": str(uuid.uuid4()),
                "token_id": token_id,
                "now": now,
                "supply_raw": value,
            },
        )

    with pytest.raises(Exception, match="u64_range|violates check"):
        _insert(-1)
    with pytest.raises(Exception, match="u64_range|violates check"):
        _insert(_U64_MAX + 1)
    with pytest.raises(Exception, match="u64_integral|violates check"):
        _insert("1.5")

    # Nothing from the three rejected attempts was persisted.
    count = _query(
        scratch_database,
        "SELECT COUNT(*) FROM token_market_snapshots WHERE token_id = :t",
        {"t": token_id},
    )[0][0]
    assert count == 0


def test_p2r7_downgrade_from_0009_fails_closed_when_value_exceeds_bigint_range(
    scratch_database: str,
) -> None:
    """A supply_raw value between 2**63 and 2**64-1 (genuinely storable
    only since 0009) cannot be represented by the pre-0009 signed
    BIGINT column -- the downgrade must refuse, not silently truncate
    or corrupt the value."""
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    token_id = str(uuid.uuid4())
    _insert_token(scratch_database, token_id, f"P2R7Mint{uuid.uuid4().hex[:36]}")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    _execute(
        scratch_database,
        """
        INSERT INTO token_market_snapshots (
            snapshot_id, token_id, observed_at, lifecycle_stage, supply_raw,
            source, algorithm_version, build_hash, created_at
        ) VALUES (
            :snapshot_id, :token_id, :now, 'TOKEN_CREATION', :supply_raw,
            'p2r7-test', 'v1', 'deadbeef', :now
        )
        """,
        {
            "snapshot_id": str(uuid.uuid4()),
            "token_id": token_id,
            "now": now,
            "supply_raw": _BIGINT_MAX + 1,
        },
    )

    with pytest.raises(Exception, match="cannot downgrade past revision 0009"):
        command.downgrade(cfg, "0008")

    # Refused before touching anything: still at head, value unchanged.
    assert _current_revision(scratch_database) == "0021"
    stored = _query(
        scratch_database,
        "SELECT supply_raw FROM token_market_snapshots WHERE token_id = :t",
        {"t": token_id},
    )[0][0]
    assert int(stored) == _BIGINT_MAX + 1


def test_p2r7_downgrade_from_0009_succeeds_when_values_fit_bigint_range(
    scratch_database: str,
) -> None:
    """A downgrade with no out-of-BIGINT-range data present succeeds
    cleanly, restoring the pre-0009 BIGINT column and dropping the
    0009 CHECK constraints -- proving the fails-closed test above is
    about the *data*, not the migration being broken outright."""
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    token_id = str(uuid.uuid4())
    _insert_token(scratch_database, token_id, f"P2R7Mint{uuid.uuid4().hex[:36]}")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    _execute(
        scratch_database,
        """
        INSERT INTO token_market_snapshots (
            snapshot_id, token_id, observed_at, lifecycle_stage, supply_raw,
            source, algorithm_version, build_hash, created_at
        ) VALUES (
            :snapshot_id, :token_id, :now, 'TOKEN_CREATION', 1000000,
            'p2r7-test', 'v1', 'deadbeef', :now
        )
        """,
        {"snapshot_id": str(uuid.uuid4()), "token_id": token_id, "now": now},
    )

    command.downgrade(cfg, "0008")

    assert _current_revision(scratch_database) == "0008"
    constraints = _check_constraint_names(scratch_database, "token_market_snapshots")
    assert "ck_token_market_snapshots_supply_raw_u64_range" not in constraints
    assert "ck_token_market_snapshots_supply_raw_u64_integral" not in constraints
    rows = _query(
        scratch_database,
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = 'token_market_snapshots' AND column_name = 'supply_raw'",
    )
    assert rows[0][0] == "bigint"
    stored = _query(
        scratch_database,
        "SELECT supply_raw FROM token_market_snapshots WHERE token_id = :t",
        {"t": token_id},
    )[0][0]
    assert stored == 1_000_000

    command.upgrade(cfg, "head")
    assert _current_revision(scratch_database) == "0021"


def test_p2r7_early_buyers_amount_raw_shares_the_same_u64_widening(scratch_database: str) -> None:
    """``early_buyers.amount_raw`` (the second P2-R7 column) gets the
    identical treatment: widened type, both CHECK constraints, and a
    genuine 2**64-1 round trip."""
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    now = datetime(2026, 1, 1, tzinfo=UTC)

    token_id = str(uuid.uuid4())
    _insert_token(scratch_database, token_id, f"P2R7Mint{uuid.uuid4().hex[:36]}")
    wallet_id = str(uuid.uuid4())
    _execute(
        scratch_database,
        "INSERT INTO wallets (wallet_id, wallet_address, first_discovered_at, created_at) "
        "VALUES (:w, :addr, :now, :now)",
        {"w": wallet_id, "addr": f"P2R7Wallet{uuid.uuid4().hex[:34]}", "now": now},
    )
    run_id = str(uuid.uuid4())
    _execute(
        scratch_database,
        """
        INSERT INTO archaeology_runs (
            run_id, token_id, run_type, source_provider_set, input_evidence_reference,
            completeness_statement, status, started_at, algorithm_version, build_hash,
            config_hash, master_spec_hash, git_commit, created_at
        ) VALUES (
            :run_id, :token_id, 'HISTORICAL_WINNER', 'p2r7-test', 'p2r7-test',
            'p2r7-test', 'COMPLETED', :now, 'v1', 'deadbeef', 'deadbeef', 'deadbeef',
            'deadbeef', :now
        )
        """,
        {"run_id": run_id, "token_id": token_id, "now": now},
    )

    constraints = _check_constraint_names(scratch_database, "early_buyers")
    assert "ck_early_buyers_amount_raw_u64_range" in constraints
    assert "ck_early_buyers_amount_raw_u64_integral" in constraints

    _execute(
        scratch_database,
        """
        INSERT INTO early_buyers (
            early_buyer_id, token_id, wallet_id, source_run_id, first_buy_slot,
            sequence_number, amount_raw, amount_decimals, evidence_reference,
            algorithm_version, created_at
        ) VALUES (
            :id, :token_id, :wallet_id, :run_id, 1, 1, :amount_raw, 6, 'p2r7-test',
            'v1', :now
        )
        """,
        {
            "id": str(uuid.uuid4()),
            "token_id": token_id,
            "wallet_id": wallet_id,
            "run_id": run_id,
            "amount_raw": _U64_MAX,
            "now": now,
        },
    )
    stored = _query(
        scratch_database,
        "SELECT amount_raw FROM early_buyers WHERE token_id = :t",
        {"t": token_id},
    )[0][0]
    assert int(stored) == _U64_MAX


# --- Phase 3 remediation round 2 (argus-phase-3-remediation-002),
# --- finding P3-R6a: migration 0011's original form deleted every
# --- existing wallet_positions/wallet_score_snapshots/
# --- wallet_metrics_snapshots/wallet_tier_history row and reset
# --- wallets.current_tier so its three new columns could be NOT NULL.
# --- It was amended (still UNAPPROVED, narrow change-control) to make
# --- those columns nullable instead and never delete anything; migration
# --- 0012 separately widens the same columns for a database that already
# --- ran 0011's original (pre-amendment) NOT-NULL form.

_P3_NOW = datetime(2026, 6, 1, tzinfo=UTC)


def _insert_wallet(database: str, wallet_id: str, address: str) -> None:
    _execute(
        database,
        """
        INSERT INTO wallets (wallet_id, wallet_address, first_discovered_at, created_at)
        VALUES (:wallet_id, :address, :now, :now)
        """,
        {"wallet_id": wallet_id, "address": address, "now": _P3_NOW},
    )


def _insert_history_quality(database: str, history_id: str, wallet_id: str) -> None:
    _execute(
        database,
        """
        INSERT INTO wallet_history_quality (
            history_id, wallet_id, history_provider_set, history_completeness,
            history_completeness_reason, algorithm_version, created_at
        ) VALUES (
            :history_id, :wallet_id, 'p3r6a-test', 'HIGH', 'legacy test row',
            'history_reconstruction_v1', :now
        )
        """,
        {"history_id": history_id, "wallet_id": wallet_id, "now": _P3_NOW},
    )


def _insert_legacy_wallet_position(
    database: str, position_id: str, wallet_id: str, token_id: str, history_id: str
) -> None:
    """A position row shaped exactly as migration 0010 left it -- no
    ``round_trip_index``/``input_manifest_digest`` column exists yet."""
    _execute(
        database,
        """
        INSERT INTO wallet_positions (
            position_id, wallet_id, token_id, history_id, quote_asset_mint,
            entry_quantity, realized_pnl_quote, partial_exit_count, confidence,
            status, algorithm_version, git_commit, created_at
        ) VALUES (
            :position_id, :wallet_id, :token_id, :history_id, 'SOL',
            100, 5, 0, 'HIGH', 'CLOSED', 'position_reconstruction_v1',
            'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef', :now
        )
        """,
        {
            "position_id": position_id,
            "wallet_id": wallet_id,
            "token_id": token_id,
            "history_id": history_id,
            "now": _P3_NOW,
        },
    )


def _insert_legacy_score_snapshot(database: str, score_id: str, wallet_id: str) -> None:
    """A score row shaped exactly as migration 0010 left it -- no
    ``input_manifest_digest`` column exists yet."""
    _execute(
        database,
        """
        INSERT INTO wallet_score_snapshots (
            score_id, wallet_id, as_of, score_version, qualification_score,
            descriptive_score, component_values, penalties,
            eligible_for_qualification, sample_gate_reason, build_hash,
            config_hash, master_spec_hash, git_commit, created_at
        ) VALUES (
            :score_id, :wallet_id, :now, 'wallet_qualification_v1', 42.5, 50.0,
            '{}'::jsonb, '{}'::jsonb, false, 'legacy test row',
            'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef',
            'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef',
            'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef',
            'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef', :now
        )
        """,
        {"score_id": score_id, "wallet_id": wallet_id, "now": _P3_NOW},
    )


def _insert_legacy_metrics_snapshot(database: str, snapshot_id: str, wallet_id: str) -> None:
    _execute(
        database,
        """
        INSERT INTO wallet_metrics_snapshots (
            snapshot_id, wallet_id, as_of, metrics_window, algorithm_version,
            git_commit, created_at
        ) VALUES (
            :snapshot_id, :wallet_id, :now, 'LIFETIME', 'wallet_qualification_v1',
            'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef', :now
        )
        """,
        {"snapshot_id": snapshot_id, "wallet_id": wallet_id, "now": _P3_NOW},
    )


def _insert_legacy_tier_transition(
    database: str, transition_id: str, wallet_id: str, source_score_id: str, to_tier: str
) -> None:
    _execute(
        database,
        """
        INSERT INTO wallet_tier_history (
            transition_id, wallet_id, source_score_id, from_tier, to_tier,
            reason, transitioned_at, created_at
        ) VALUES (
            :transition_id, :wallet_id, :source_score_id, NULL, :to_tier,
            'legacy test transition', :now, :now
        )
        """,
        {
            "transition_id": transition_id,
            "wallet_id": wallet_id,
            "source_score_id": source_score_id,
            "to_tier": to_tier,
            "now": _P3_NOW,
        },
    )


def test_p3r6a_populated_0010_database_preserves_all_rows_through_head(
    scratch_database: str,
) -> None:
    """The primary required proof: a database with real, identifiable
    legacy position/score/metric/tier-transition/current-tier rows,
    computed entirely under migration 0010's schema (before P3-R1..R7
    remediation existed), upgrades cleanly to head -- every original
    value, FK, and row count is unchanged. This is what migration 0011's
    original DELETE-based form made impossible."""
    cfg = _alembic_config()
    command.upgrade(cfg, "0010")

    wallet_id = str(uuid.uuid4())
    token_id = str(uuid.uuid4())
    history_id = str(uuid.uuid4())
    position_id = str(uuid.uuid4())
    score_id = str(uuid.uuid4())
    metrics_id = str(uuid.uuid4())
    transition_id = str(uuid.uuid4())

    _insert_wallet(scratch_database, wallet_id, f"P3R6aWallet{uuid.uuid4().hex[:36]}")
    _insert_token(scratch_database, token_id, f"P3R6aMint{uuid.uuid4().hex[:36]}")
    _insert_history_quality(scratch_database, history_id, wallet_id)
    _insert_legacy_wallet_position(scratch_database, position_id, wallet_id, token_id, history_id)
    _insert_legacy_score_snapshot(scratch_database, score_id, wallet_id)
    _insert_legacy_metrics_snapshot(scratch_database, metrics_id, wallet_id)
    _insert_legacy_tier_transition(scratch_database, transition_id, wallet_id, score_id, "B")
    _execute(
        scratch_database,
        "UPDATE wallets SET current_tier = 'B' WHERE wallet_id = :w",
        {"w": wallet_id},
    )

    command.upgrade(cfg, "head")

    assert _current_revision(scratch_database) == "0021"

    position_row = _query(
        scratch_database,
        "SELECT realized_pnl_quote, round_trip_index, input_manifest_digest "
        "FROM wallet_positions WHERE position_id = :p",
        {"p": position_id},
    )
    assert len(position_row) == 1
    assert position_row[0][0] == Decimal("5")
    assert position_row[0][1] is None
    assert position_row[0][2] is None

    score_row = _query(
        scratch_database,
        "SELECT qualification_score, input_manifest_digest "
        "FROM wallet_score_snapshots WHERE score_id = :s",
        {"s": score_id},
    )
    assert len(score_row) == 1
    assert score_row[0][0] == Decimal("42.500")
    assert score_row[0][1] is None

    metrics_row = _query(
        scratch_database,
        "SELECT metrics_window FROM wallet_metrics_snapshots WHERE snapshot_id = :m",
        {"m": metrics_id},
    )
    assert len(metrics_row) == 1
    assert metrics_row[0][0] == "LIFETIME"

    transition_row = _query(
        scratch_database,
        "SELECT to_tier, source_score_id FROM wallet_tier_history WHERE transition_id = :t",
        {"t": transition_id},
    )
    assert len(transition_row) == 1
    assert transition_row[0][0] == "B"
    assert str(transition_row[0][1]) == score_id

    wallet_row = _query(
        scratch_database, "SELECT current_tier FROM wallets WHERE wallet_id = :w", {"w": wallet_id}
    )
    assert wallet_row[0][0] == "B"


def test_p3r6a_already_at_0011_upgrades_to_0012_safely_no_data_loss(
    scratch_database: str,
) -> None:
    """A database already stamped 0011 (this repo's own amended,
    non-destructive form) upgrading the remaining single step to 0012
    never loses or alters an existing row -- 0012's own operations
    (widen-nullable, replace check constraints) are idempotent-safe
    against a database that already has the amended, nullable 0011
    schema, which is exactly what a database landing on 0011 from this
    repo's current migration file always has."""
    cfg = _alembic_config()
    command.upgrade(cfg, "0011")

    wallet_id = str(uuid.uuid4())
    token_id = str(uuid.uuid4())
    history_id = str(uuid.uuid4())
    position_id = str(uuid.uuid4())

    _insert_wallet(scratch_database, wallet_id, f"P3R6aWallet{uuid.uuid4().hex[:36]}")
    _insert_token(scratch_database, token_id, f"P3R6aMint{uuid.uuid4().hex[:36]}")
    _insert_history_quality(scratch_database, history_id, wallet_id)
    _execute(
        scratch_database,
        """
        INSERT INTO wallet_positions (
            position_id, wallet_id, token_id, history_id, quote_asset_mint,
            round_trip_index, input_manifest_digest, entry_quantity,
            partial_exit_count, confidence, status, algorithm_version,
            git_commit, created_at
        ) VALUES (
            :position_id, :wallet_id, :token_id, :history_id, 'SOL', 0,
            '11112222333344445555666677778888999900001111222233334444555566',
            100, 0, 'HIGH', 'CLOSED', 'position_reconstruction_v2',
            'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef', :now
        )
        """,
        {
            "position_id": position_id,
            "wallet_id": wallet_id,
            "token_id": token_id,
            "history_id": history_id,
            "now": _P3_NOW,
        },
    )

    command.upgrade(cfg, "0012")

    assert _current_revision(scratch_database) == "0012"
    row = _query(
        scratch_database,
        "SELECT round_trip_index, input_manifest_digest FROM wallet_positions WHERE position_id = :p",
        {"p": position_id},
    )
    assert len(row) == 1
    assert row[0][0] == 0
    assert row[0][1] == "11112222333344445555666677778888999900001111222233334444555566"


def test_p3r6a_downgrade_from_0012_fails_closed_with_legacy_null_rows(
    scratch_database: str,
) -> None:
    """A legacy row with NULL round_trip_index/input_manifest_digest
    cannot be represented under the narrower pre-0012 NOT NULL
    constraint -- downgrading must refuse with a precise reason rather
    than deleting the row or fabricating a value for it."""
    cfg = _alembic_config()
    command.upgrade(cfg, "0010")
    wallet_id = str(uuid.uuid4())
    token_id = str(uuid.uuid4())
    history_id = str(uuid.uuid4())
    position_id = str(uuid.uuid4())
    _insert_wallet(scratch_database, wallet_id, f"P3R6aWallet{uuid.uuid4().hex[:36]}")
    _insert_token(scratch_database, token_id, f"P3R6aMint{uuid.uuid4().hex[:36]}")
    _insert_history_quality(scratch_database, history_id, wallet_id)
    _insert_legacy_wallet_position(scratch_database, position_id, wallet_id, token_id, history_id)
    command.upgrade(cfg, "head")

    with pytest.raises(Exception, match="cannot downgrade past revision 0012"):
        command.downgrade(cfg, "0011")

    # Refused before touching anything: still at head, legacy row intact.
    assert _current_revision(scratch_database) == "0021"
    row = _query(
        scratch_database,
        "SELECT round_trip_index FROM wallet_positions WHERE position_id = :p",
        {"p": position_id},
    )
    assert len(row) == 1
    assert row[0][0] is None


def test_p3r6a_downgrade_from_0012_succeeds_with_no_legacy_null_rows(
    scratch_database: str,
) -> None:
    """The ordinary case: no legacy NULL-provenance row exists, so
    downgrading to 0011 (still nullable there) succeeds cleanly."""
    cfg = _alembic_config()
    command.upgrade(cfg, "head")

    command.downgrade(cfg, "0011")

    assert _current_revision(scratch_database) == "0011"
    constraints = _check_constraint_names(scratch_database, "wallet_positions")
    assert "ck_wallet_positions_round_trip_index" in constraints


# --- P4-REC-04 (argus-phase-4-recovery-001, frozen finding R4-M from
# --- argus-phase-4-failure-review-001): migration 0020's own CHECK
# --- constraint (responded_at IS NULL OR terminal_at IS NOT NULL) is
# --- validated against every EXISTING row the instant it is created. A
# --- real populated database upgrading through 0020 for the first time
# --- has completed rows (responded_at set) with no terminal_at value at
# --- all -- that column did not exist before this exact migration. These
# --- tests prove the backfill 0020 now performs BEFORE creating the CHECK
# --- constraint makes a real populated upgrade succeed, preserves every
# --- byte of pre-existing evidence untouched, correctly terminalizes
# --- every legacy completed row (and only those), leaves a pending row
# --- claimable, and is idempotent under a repeated pass.

_P4REC04_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _insert_prospective_event(
    database: str, prospective_event_id: str, *, wallet_id: str, swap_id: str, chain_event_id: str
) -> None:
    _execute(
        database,
        """
        INSERT INTO prospective_events (
            prospective_event_id, wallet_id, swap_id, event_id, first_seen_at,
            wallet_tier_snapshot, token_state_snapshot, position_size_context,
            cluster_state_snapshot, graph_state_snapshot, algorithm_version, created_at
        ) VALUES (
            :prospective_event_id, :wallet_id, :swap_id, :chain_event_id, :now,
            'A', '{}', '{}', '{}', '{}', 'p4rec04-test', :now
        )
        """,
        {
            "prospective_event_id": prospective_event_id,
            "wallet_id": wallet_id,
            "swap_id": swap_id,
            "chain_event_id": chain_event_id,
            "now": _P4REC04_NOW,
        },
    )


def _insert_shadow_intent(
    database: str, intent_id: str, *, prospective_event_id: str, wallet_id: str
) -> None:
    _execute(
        database,
        """
        INSERT INTO shadow_intents (
            shadow_intent_id, prospective_event_id, wallet_id, input_mint, output_mint,
            notional_input_amount_raw, config_hash, algorithm_version, created_at
        ) VALUES (
            :intent_id, :prospective_event_id, :wallet_id,
            'So11111111111111111111111111111111111111112', :output_mint,
            100000000, 'p4rec04-test', 'p4rec04-test', :now
        )
        """,
        {
            "intent_id": intent_id,
            "prospective_event_id": prospective_event_id,
            "wallet_id": wallet_id,
            "output_mint": f"P4REC04Mint{uuid.uuid4().hex[:30]}",
            "now": _P4REC04_NOW,
        },
    )


def _insert_shadow_quote_probe(
    database: str,
    probe_id: str,
    *,
    shadow_intent_id: str,
    target_label: str,
    requested_at: datetime | None,
    responded_at: datetime | None,
    outcome: str,
) -> None:
    """A predecessor-revision-0018-shaped row -- no ``terminal_at``
    column exists yet at that revision, so it is never referenced here."""
    _execute(
        database,
        """
        INSERT INTO shadow_quote_probes (
            probe_id, probe_kind, target_label, shadow_intent_id, input_mint, output_mint,
            notional_input_amount_raw, target_due_at, requested_at, responded_at,
            outcome, algorithm_version, created_at
        ) VALUES (
            :probe_id, 'ENTRY_DELAY', :target_label, :shadow_intent_id,
            'So11111111111111111111111111111111111111112', :output_mint,
            100000000, :now, :requested_at, :responded_at,
            :outcome, 'p4rec04-test', :now
        )
        """,
        {
            "probe_id": probe_id,
            "target_label": target_label,
            "shadow_intent_id": shadow_intent_id,
            "output_mint": f"P4REC04Mint{uuid.uuid4().hex[:30]}",
            "now": _P4REC04_NOW,
            "requested_at": requested_at,
            "responded_at": responded_at,
            "outcome": outcome,
        },
    )


def _seed_p4rec04_legacy_probes(
    scratch_database: str,
) -> dict[str, str]:
    """Seeds one wallet/chain_event/swap/prospective_event/shadow_intent
    chain at predecessor revision 0018, plus four ``shadow_quote_probes``
    rows -- completed-success, completed-error/no-route, completed
    (HTTP-429-shaped) capacity-miss, and a still-pending row -- exactly
    the P4-REC-04 test 1 minimum required set. Returns the probe ids
    keyed by their category."""
    wallet_id = str(uuid.uuid4())
    _insert_wallet(scratch_database, wallet_id, f"P4REC04Wallet{uuid.uuid4().hex[:34]}")
    event_id = str(uuid.uuid4())
    _insert_chain_event(scratch_database, event_id, signature=f"p4rec04-sig-{uuid.uuid4().hex[:8]}")
    swap_id = str(uuid.uuid4())
    _insert_swap(
        scratch_database,
        swap_id=swap_id,
        event_id=event_id,
        parser_version="v1",
        build_hash="deadbeef",
    )
    prospective_event_id = str(uuid.uuid4())
    _insert_prospective_event(
        scratch_database,
        prospective_event_id,
        wallet_id=wallet_id,
        swap_id=swap_id,
        chain_event_id=event_id,
    )
    intent_id = str(uuid.uuid4())
    _insert_shadow_intent(
        scratch_database, intent_id, prospective_event_id=prospective_event_id, wallet_id=wallet_id
    )

    success_id = str(uuid.uuid4())
    _insert_shadow_quote_probe(
        scratch_database,
        success_id,
        shadow_intent_id=intent_id,
        target_label="1s",
        requested_at=_P4REC04_NOW,
        responded_at=_P4REC04_NOW,
        outcome="SUCCESS",
    )
    no_route_id = str(uuid.uuid4())
    _insert_shadow_quote_probe(
        scratch_database,
        no_route_id,
        shadow_intent_id=intent_id,
        target_label="5s",
        requested_at=_P4REC04_NOW,
        responded_at=_P4REC04_NOW,
        outcome="NO_ROUTE",
    )
    capacity_miss_id = str(uuid.uuid4())
    _insert_shadow_quote_probe(
        scratch_database,
        capacity_miss_id,
        shadow_intent_id=intent_id,
        target_label="15s",
        # A real dispatch happened (an HTTP 429 -- P4-remediation-002 R4's
        # own "HTTP429 DID make a request" rule) -- responded_at is set
        # even though the outcome is a capacity miss.
        requested_at=_P4REC04_NOW,
        responded_at=_P4REC04_NOW,
        outcome="PROVIDER_CAPACITY_MISS",
    )
    pending_id = str(uuid.uuid4())
    _insert_shadow_quote_probe(
        scratch_database,
        pending_id,
        shadow_intent_id=intent_id,
        target_label="30s",
        requested_at=None,
        responded_at=None,
        outcome="PENDING",
    )
    return {
        "success": success_id,
        "no_route": no_route_id,
        "capacity_miss": capacity_miss_id,
        "pending": pending_id,
    }


def test_p4rec04_populated_0018_upgrade_through_0020_backfills_terminal_at(
    scratch_database: str,
) -> None:
    """Required tests 1-4 and 6: a populated predecessor-revision-0018
    database (completed-success, completed-error/no-route, completed
    capacity-miss, and pending rows) upgrades through 0020 successfully;
    every legacy completed row is correctly terminalized with
    terminal_at deterministically derived from its own already-real
    responded_at; the pending row is left alone (still NULL, still
    claimable); every other pre-existing field is byte-for-byte
    unchanged."""
    cfg = _alembic_config()
    command.upgrade(cfg, "0018")
    ids = _seed_p4rec04_legacy_probes(scratch_database)

    command.upgrade(cfg, "head")
    assert _current_revision(scratch_database) == "0021"

    rows = {
        str(r[0]): r
        for r in _query(
            scratch_database,
            "SELECT probe_id, outcome, requested_at, responded_at, terminal_at, "
            "target_label, notional_input_amount_raw FROM shadow_quote_probes "
            "WHERE probe_id = ANY(:ids)",
            {"ids": list(ids.values())},
        )
    }
    assert len(rows) == 4

    for category in ("success", "no_route", "capacity_miss"):
        probe_id = ids[category]
        row = rows[probe_id]
        _probe_id, _outcome, _requested_at, responded_at, terminal_at, _label, _notional = row
        assert responded_at is not None
        # The frozen requirement itself: deterministically derived from
        # the row's own already-real responded_at, never fabricated.
        assert terminal_at == responded_at

    pending_row = rows[ids["pending"]]
    assert pending_row[2] is None  # requested_at
    assert pending_row[3] is None  # responded_at
    assert pending_row[4] is None  # terminal_at -- never falsely terminalized

    # Old evidence (outcome, ids, labels, notional amount) is completely
    # unchanged -- only the new terminal_at column was ever touched.
    assert rows[ids["success"]][1] == "SUCCESS"
    assert rows[ids["no_route"]][1] == "NO_ROUTE"
    assert rows[ids["capacity_miss"]][1] == "PROVIDER_CAPACITY_MISS"
    assert rows[ids["pending"]][1] == "PENDING"
    for row in rows.values():
        assert row[6] == 100000000

    # The CHECK constraint this migration adds genuinely holds for every
    # row now, not merely for the four fixture rows above.
    with pytest.raises(
        Exception, match="ck_shadow_probes_responded_requires_terminal|violates check"
    ):
        _execute(
            scratch_database,
            """
            UPDATE shadow_quote_probes SET terminal_at = NULL
            WHERE probe_id = :p
            """,
            {"p": ids["success"]},
        )


def test_p4rec04_backfill_update_is_idempotent(scratch_database: str) -> None:
    """Required test 7: repeated startup/migration state is stable --
    re-running the exact backfill statement migration 0020 itself uses
    (the same statement a repeated 'migrate to head on every process
    start' pattern would execute if it were ever re-applied) is a
    genuine no-op against an already-migrated database: it touches zero
    additional rows and never overwrites an already-correct value."""
    cfg = _alembic_config()
    command.upgrade(cfg, "0018")
    ids = _seed_p4rec04_legacy_probes(scratch_database)
    command.upgrade(cfg, "head")

    before = _query(
        scratch_database,
        "SELECT probe_id, terminal_at FROM shadow_quote_probes WHERE probe_id = ANY(:ids)",
        {"ids": list(ids.values())},
    )
    before_by_id = {str(r[0]): r[1] for r in before}

    _execute(
        scratch_database,
        "UPDATE shadow_quote_probes SET terminal_at = responded_at "
        "WHERE responded_at IS NOT NULL AND terminal_at IS NULL",
    )

    after = _query(
        scratch_database,
        "SELECT probe_id, terminal_at FROM shadow_quote_probes WHERE probe_id = ANY(:ids)",
        {"ids": list(ids.values())},
    )
    after_by_id = {str(r[0]): r[1] for r in after}
    assert after_by_id == before_by_id
    assert after_by_id[ids["pending"]] is None

    # Upgrading to head a second time (a genuine repeated-startup pass)
    # is itself stable too.
    command.upgrade(cfg, "head")
    assert _current_revision(scratch_database) == "0021"


def _p4rec04_sessionmaker(scratch_database: str) -> tuple[Any, Any]:
    config = load_config()
    info = connection_for_role(config, DbRole.INGEST)
    engine = create_async_engine(info.as_asyncpg_url())
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@dataclasses.dataclass
class _P4REC04FakeProvider:
    """A minimal fake ``ExecutionProvider`` -- SUCCESS on every call, used
    only to prove which probes the real claim query actually selects."""

    calls: list[tuple[str, str, int]] = dataclasses.field(default_factory=list)

    async def get_quote(
        self, *, input_mint: str, output_mint: str, amount_raw: int, slippage_bps: int = 50
    ) -> Any:
        from argus.providers.models import ExecutableQuote

        self.calls.append((input_mint, output_mint, amount_raw))
        return ExecutableQuote(
            provider="jupiter-fake",
            input_mint=input_mint,
            output_mint=output_mint,
            in_amount_raw=amount_raw,
            out_amount_raw=500_000,
            raw={
                "inputMint": input_mint,
                "outputMint": output_mint,
                "priceImpactPct": "0.01",
                "inAmount": str(amount_raw),
                "outAmount": "500000",
                "routePlan": [
                    {
                        "swapInfo": {
                            "label": "fake-amm",
                            "inputMint": input_mint,
                            "outputMint": output_mint,
                            "inAmount": str(amount_raw),
                            "outAmount": "500000",
                        },
                        "percent": 100,
                    }
                ],
            },
        )

    async def build_unsigned_order(self, *, quote: Any, wallet_address: str) -> Any:
        raise NotImplementedError


async def _p4rec04_run_due_entry_probes(
    scratch_database: str, *, now: datetime
) -> tuple[list, int]:
    from argus.shadow.quote_jobs import run_due_entry_probes

    engine, sessionmaker = _p4rec04_sessionmaker(scratch_database)
    try:
        provider = _P4REC04FakeProvider()
        config = load_config()
        processed = await run_due_entry_probes(
            sessionmaker, provider, config=config, clock=Clock(), now=now, limit=50
        )
        return processed, len(provider.calls)
    finally:
        await engine.dispose()


def test_p4rec04_legacy_completed_rows_never_reclaimed_zero_provider_calls(
    scratch_database: str,
) -> None:
    """Required test 5: a replay/worker pass over the migrated database
    makes ZERO provider calls for the legacy completed rows -- the real
    production claim query (argus.shadow.quote_jobs._claim_due_probes)
    excludes every row whose terminal_at is now non-null, exactly like
    it already does for a freshly-created terminal row."""
    cfg = _alembic_config()
    command.upgrade(cfg, "0018")
    ids = _seed_p4rec04_legacy_probes(scratch_database)
    command.upgrade(cfg, "head")

    far_future = _P4REC04_NOW + timedelta(days=1)
    processed, call_count = asyncio.run(
        _p4rec04_run_due_entry_probes(scratch_database, now=far_future)
    )
    # Only the genuinely pending row is claimable -- the three legacy
    # completed rows are correctly excluded.
    assert len(processed) == 1
    assert processed[0].probe_id == uuid.UUID(ids["pending"])
    assert call_count == 1


def test_p4rec04_pending_row_remains_claimable_after_migration(scratch_database: str) -> None:
    """Required test 6 (claim path): the pending legacy row is not merely
    left with a NULL terminal_at -- it is genuinely still claimable and
    runnable through the real worker path, and resolves normally."""
    cfg = _alembic_config()
    command.upgrade(cfg, "0018")
    ids = _seed_p4rec04_legacy_probes(scratch_database)
    command.upgrade(cfg, "head")

    far_future = _P4REC04_NOW + timedelta(days=1)
    processed, _call_count = asyncio.run(
        _p4rec04_run_due_entry_probes(scratch_database, now=far_future)
    )
    assert len(processed) == 1
    probe = processed[0]
    assert probe.probe_id == uuid.UUID(ids["pending"])
    assert probe.outcome == "SUCCESS"
    assert probe.terminal_at is not None
    assert probe.responded_at is not None
