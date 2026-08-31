from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from argus.config import load_config  # noqa: E402
from argus.db.base import Base  # noqa: E402
from argus.db.connection import connection_for_admin  # noqa: E402
from argus.domain import (
    chain_events,  # noqa: E402,F401  (registers ORM metadata)
    clock_health,  # noqa: E402,F401  (registers ORM metadata)
    provider_usage,  # noqa: E402,F401  (registers ORM metadata)
    swaps,  # noqa: E402,F401  (registers ORM metadata)
    wallet_stream_state,  # noqa: E402,F401  (registers ORM metadata)
)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    argus_config = load_config()
    return connection_for_admin(argus_config).as_asyncpg_url()


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        {"sqlalchemy.url": get_url()},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
