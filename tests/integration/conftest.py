from __future__ import annotations

import asyncio
import dataclasses
import os
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from argus.config import REPO_ROOT, load_config
from argus.db.connection import connection_for_admin


@pytest_asyncio.fixture
async def admin_engine() -> AsyncIterator[AsyncEngine]:
    """An async engine using admin credentials, for schema/role assertions.

    Skips the test (rather than failing) if Postgres isn't reachable, so
    `pytest` still runs cleanly on a machine without Docker — the real
    Phase 0 acceptance check (`make up && make test`) always exercises this
    for real.
    """
    config = load_config()
    info = connection_for_admin(config)
    engine = create_async_engine(info.as_asyncpg_url())
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover
        await engine.dispose()
        pytest.skip(f"Postgres not reachable for integration tests: {exc}")
    yield engine
    await engine.dispose()


def _alembic_config() -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return cfg


async def _maintenance_execute(sql: str) -> None:
    """Runs one autocommit DDL statement (CREATE/DROP DATABASE, which
    Postgres refuses inside a transaction block) against the maintenance
    ``postgres`` database, using the same admin credentials every other
    migration/DDL operation in this repo uses. Mirrors
    ``test_migrations.py``'s own identically-named helper -- kept as a
    small, independent copy here rather than importing across test
    modules."""
    admin = connection_for_admin(load_config())
    maintenance = dataclasses.replace(admin, database="postgres")
    engine = create_async_engine(maintenance.as_asyncpg_url(), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(sql))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def _migrated_template_database() -> Iterator[str]:
    """Migrates ONE throwaway database to head, ONCE for the whole test
    session -- the expensive part (a full ``alembic upgrade head`` run,
    re-establishing every migration's own role GRANT statements) never
    needs to repeat per test. ``isolated_database`` below clones this via
    Postgres's own ``CREATE DATABASE ... TEMPLATE`` (a fast filesystem-level
    copy, not a second migration run) to give each TEST its own real,
    independent database. Skips (never fails) the whole session if
    Postgres is unreachable, matching every other ``admin_engine``-gated
    integration test's own skip discipline."""
    name = f"argus_template_{uuid.uuid4().hex[:12]}"
    try:
        asyncio.run(_maintenance_execute(f'CREATE DATABASE "{name}"'))
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"Postgres not reachable / cannot create a template database: {exc}")

    previous = os.environ.get("ARGUS_DB_NAME")
    os.environ["ARGUS_DB_NAME"] = name
    try:
        command.upgrade(_alembic_config(), "head")
    finally:
        if previous is None:
            os.environ.pop("ARGUS_DB_NAME", None)
        else:
            os.environ["ARGUS_DB_NAME"] = previous
    yield name
    asyncio.run(_maintenance_execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture
def isolated_database(_migrated_template_database: str) -> Iterator[str]:
    """R2-04 (``argus-final-spec-recovery-002``): gives EACH TEST FUNCTION
    that requests this fixture (via ``pytestmark =
    pytest.mark.usefixtures("isolated_database")``, applied once per
    module -- pytest still instantiates a fresh instance of a
    function-scoped fixture for every single test function in that
    module) its own real, independent Postgres database, cloned instantly
    from ``_migrated_template_database`` via ``CREATE DATABASE ...
    TEMPLATE`` (a fast filesystem-level copy -- no second migration run
    per test) and dropped immediately after that one test.

    Per-test (not per-module) isolation is deliberate and required: several
    Phase 7/8/9/10/11 production queries (``compute_and_persist_directional_
    edges``, Strategy A/B/C/D/E's own entry/exit loaders, convergence
    episode detection, etc.) scan ALL matching rows in a table, by design
    -- "any tracked wallet's real buy" genuinely means every wallet in the
    database, not a test-scoped subset. A per-MODULE database only stops
    cross-MODULE pollution; two tests in the SAME module would still see
    each other's seeded wallets/entries and silently corrupt each other's
    assertions (confirmed empirically: switching this fixture from module
    to function scope was the fix for exactly that failure mode). This is
    the "equivalently strong per-test isolated database" alternative the
    R2-04 instruction explicitly allows.

    While active, ``ARGUS_DB_NAME`` is overridden (matching
    ``scratch_database``'s own established technique) so every
    ``load_config()`` call any test/helper makes -- including each file's
    own local ``_sessionmaker()`` helper and the ``admin_engine`` fixture --
    transparently targets this test's own isolated database, with NO other
    code change needed anywhere in the module. Never touches the shared
    ``argus`` database itself."""
    name = f"argus_isolated_{uuid.uuid4().hex[:12]}"
    try:
        asyncio.run(
            _maintenance_execute(
                f'CREATE DATABASE "{name}" TEMPLATE "{_migrated_template_database}"'
            )
        )
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"Postgres not reachable / cannot clone an isolated database: {exc}")

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
