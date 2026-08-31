from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from argus.config import load_config
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.chain_events import ChainEvent
from argus.domain.swaps import Swap
from argus.domain.wallet_stream_state import WalletStreamState

pytestmark = pytest.mark.asyncio


async def _engine_for(role: DbRole):
    config = load_config()
    info = connection_for_role(config, role)
    return create_async_engine(info.as_asyncpg_url())


async def test_phase1_tables_exist(admin_engine) -> None:
    async with admin_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name IN ('chain_events', 'swaps', 'wallet_stream_state')"
            )
        )
        tables = {row[0] for row in result}
    assert tables == {"chain_events", "swaps", "wallet_stream_state"}


async def test_chain_events_dedup_constraint_rejects_duplicate(admin_engine) -> None:
    """The mandatory disconnect/reconnect scenario relies on this unique
    constraint: the same (signature, wallet, event_type) observed twice
    (fast path + truth path) must canonicalize to exactly one row."""
    ingest_engine = await _engine_for(DbRole.INGEST)
    now = datetime.now(UTC)
    try:
        sessionmaker = async_sessionmaker(ingest_engine, expire_on_commit=False)
        signature = f"dedup-test-{uuid.uuid4()}"
        async with sessionmaker() as session:
            session.add(
                ChainEvent(
                    event_id=uuid.uuid4(),
                    chain="solana",
                    slot=123,
                    first_seen_at=now,
                    provider="helius",
                    provider_received_at=now,
                    transaction_signature=signature,
                    event_type="TRANSACTION_OBSERVED",
                    wallet_address="WalletA",
                    raw_payload={"x": 1},
                    payload_hash="abc123",
                    parser_version="v1",
                    created_at=now,
                )
            )
            await session.commit()

        async with sessionmaker() as session:
            session.add(
                ChainEvent(
                    event_id=uuid.uuid4(),
                    chain="solana",
                    slot=123,
                    first_seen_at=now,
                    provider="helius",
                    provider_received_at=now,
                    transaction_signature=signature,
                    event_type="TRANSACTION_OBSERVED",
                    wallet_address="WalletA",
                    raw_payload={"x": 1},
                    payload_hash="abc123",
                    parser_version="v1",
                    created_at=now,
                )
            )
            with pytest.raises(Exception):  # noqa: B017 - DBAPIError wrapping a unique violation
                await session.commit()

        research_engine = await _engine_for(DbRole.RESEARCH)
        try:
            research_sessionmaker = async_sessionmaker(research_engine, expire_on_commit=False)
            async with research_sessionmaker() as session:
                result = await session.execute(
                    select(ChainEvent).where(ChainEvent.transaction_signature == signature)
                )
                rows = result.scalars().all()
                assert len(rows) == 1
        finally:
            await research_engine.dispose()
    finally:
        async with admin_engine.connect() as conn:
            await conn.execute(
                text("DELETE FROM chain_events WHERE transaction_signature LIKE 'dedup-test-%'")
            )
            await conn.commit()
        await ingest_engine.dispose()


async def test_swap_and_wallet_stream_state_roundtrip(admin_engine) -> None:
    ingest_engine = await _engine_for(DbRole.INGEST)
    now = datetime.now(UTC)
    event_id = uuid.uuid4()
    wallet = f"roundtrip-wallet-{uuid.uuid4()}"
    try:
        sessionmaker = async_sessionmaker(ingest_engine, expire_on_commit=False)
        async with sessionmaker() as session:
            session.add(
                ChainEvent(
                    event_id=event_id,
                    chain="solana",
                    slot=1,
                    first_seen_at=now,
                    provider="helius",
                    provider_received_at=now,
                    transaction_signature=f"roundtrip-{uuid.uuid4()}",
                    event_type="TRANSACTION_OBSERVED",
                    wallet_address=wallet,
                    raw_payload={},
                    payload_hash="h",
                    parser_version="v1",
                    created_at=now,
                )
            )
            session.add(
                Swap(
                    swap_id=uuid.uuid4(),
                    event_id=event_id,
                    wallet_address=wallet,
                    classification="SWAP_SIMPLE",
                    input_mint="So11111111111111111111111111111111111111112",
                    input_amount_raw=1_000_000_000,
                    input_amount_ui=Decimal("1.0"),
                    output_mint="mint123",
                    output_amount_raw=500,
                    output_amount_ui=Decimal("500"),
                    network_fee_raw=5000,
                    slot=1,
                    first_seen_at=now,
                    confidence=Decimal("1.000"),
                    parser_version="v1",
                    created_at=now,
                )
            )
            session.add(
                WalletStreamState(
                    wallet_address=wallet,
                    last_stream_signature="sig1",
                    last_stream_slot=1,
                    stream_health="OK",
                    wallet_live_state="OK",
                    updated_at=now,
                )
            )
            await session.commit()

        async with sessionmaker() as session:
            swap = (
                await session.execute(select(Swap).where(Swap.wallet_address == wallet))
            ).scalar_one()
            assert swap.classification == "SWAP_SIMPLE"

            state = (
                await session.execute(
                    select(WalletStreamState).where(WalletStreamState.wallet_address == wallet)
                )
            ).scalar_one()
            assert state.wallet_live_state == "OK"
    finally:
        async with admin_engine.connect() as conn:
            await conn.execute(text("DELETE FROM swaps WHERE wallet_address = :w"), {"w": wallet})
            await conn.execute(
                text("DELETE FROM wallet_stream_state WHERE wallet_address = :w"), {"w": wallet}
            )
            await conn.execute(
                text("DELETE FROM chain_events WHERE event_id = :e"), {"e": event_id}
            )
            await conn.commit()
        await ingest_engine.dispose()
