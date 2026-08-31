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
from datetime import UTC, datetime
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from argus.config import REPO_ROOT, load_config
from argus.db.connection import connection_for_admin

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

    assert _current_revision(scratch_database) == "0007"
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
    assert _current_revision(scratch_database) == "0007"
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

    assert _current_revision(scratch_database) == "0007"
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

    assert _current_revision(scratch_database) == "0007"
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
    assert _current_revision(scratch_database) == "0007"
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
