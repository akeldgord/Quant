"""Async SQLAlchemy engine/session management, one engine per DB role.

Domain code should request a session for the role appropriate to what it is
doing (ingestion, research, or execution) rather than sharing one
all-privileged connection — this is what makes the privilege separation in
section 72 real rather than aspirational.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from argus.db.roles import DbRole


@dataclass(frozen=True, slots=True)
class DbConnectionInfo:
    host: str
    port: int
    database: str
    user: str
    password: str

    def as_asyncpg_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )


class RoleEngines:
    """Holds one async engine + sessionmaker per :class:`DbRole`."""

    def __init__(self, connections: dict[DbRole, DbConnectionInfo]) -> None:
        self._engines: dict[DbRole, AsyncEngine] = {
            role: create_async_engine(info.as_asyncpg_url(), pool_pre_ping=True)
            for role, info in connections.items()
        }
        self._sessionmakers: dict[DbRole, async_sessionmaker[AsyncSession]] = {
            role: async_sessionmaker(engine, expire_on_commit=False)
            for role, engine in self._engines.items()
        }

    def engine(self, role: DbRole) -> AsyncEngine:
        return self._engines[role]

    @asynccontextmanager
    async def session(self, role: DbRole) -> AsyncIterator[AsyncSession]:
        sessionmaker = self._sessionmakers[role]
        async with sessionmaker() as session:
            yield session

    async def dispose_all(self) -> None:
        for engine in self._engines.values():
            await engine.dispose()
