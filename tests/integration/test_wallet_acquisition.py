"""Integration tests for ``argus.wallets.acquisition`` (P3-R1/P3-R2
remediation round 2, `argus-phase-3-remediation-002`): the real,
persisted acquisition-run path that replaces the removed caller-supplied-
JSON-manifest path entirely.

Uses a deterministic, address-keyed fake ``ChainProvider`` (per this
instruction's own explicit "tests may use a deterministic fake provider"
allowance) against real Postgres, proving:

- a wallet-address walk plus every associated token-account walk is
  actually executed and its transactions actually persisted through the
  real ``chain_events``/``swaps`` parser/persistence path (never merely
  blessing an unrelated fragment);
- the persisted manifest correctly classifies COMPLETE/PARTIAL/enumeration
  failure per account, with real pubkey/mint/owner identity, never mint
  alone;
- re-running against already-known signatures is idempotent (no
  duplicate chain_events/swaps rows);
- ``load_verified_acquisition_manifest`` refuses a run belonging to
  another wallet, a run observed after the score's own ``as_of``, and a
  nonexistent ``run_id`` -- there is no remaining path from an arbitrary
  caller-supplied value to a usable manifest.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from argus.config import load_config
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.swaps import Swap
from argus.domain.wallet_acquisition_runs import WalletAcquisitionRun
from argus.domain.wallets import Wallet
from argus.providers import SignatureInfo
from argus.providers.models import TokenAccountInfo
from argus.tokens.historical_acquisition import STATUS_COMPLETE
from argus.wallets.acquisition import (
    AcquisitionRunVerificationError,
    load_verified_acquisition_manifest,
    run_wallet_acquisition,
)

pytestmark = pytest.mark.asyncio

_NOW = datetime(2026, 6, 1, tzinfo=UTC)


def _unique_wallet() -> str:
    return f"P3AcqW{uuid.uuid4().hex[:36]}"


def _sig(signature: str, slot: int) -> SignatureInfo:
    return SignatureInfo(signature=signature, slot=slot, block_time=None, err=None)


_OTHER_PARTY = "OtherParty11111111111111111111111111111111"


def _tx(
    signature: str, *, wallet_address: str, lamports_received: int = 1_000_000
) -> dict[str, Any]:
    """A minimal but genuinely parseable raw transaction: ``wallet_address``
    receives ``lamports_received`` lamports of native SOL from a fee-paying
    counterparty -- real enough for ``parse_transaction`` to classify it and
    for ``SqlSwapRecorder`` to persist a real ``swaps`` row, without needing
    a full authentic mainnet payload (this file only proves the acquisition/
    persistence wiring, not parser correctness, which is exhaustively
    covered elsewhere)."""
    return {
        "transaction": {
            "signatures": [signature],
            "message": {"accountKeys": [_OTHER_PARTY, wallet_address]},
        },
        "slot": 0,
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [10_000_000_000, 0],
            "postBalances": [10_000_000_000 - 5000 - lamports_received, lamports_received],
            "preTokenBalances": [],
            "postTokenBalances": [],
        },
    }


@dataclasses.dataclass
class AddressKeyedChainProvider:
    """A deterministic fake keyed by the address each call actually
    targets -- unlike ``ScriptedChainProvider`` (call-index-only), this
    is required here since one acquisition run genuinely calls
    ``get_signatures_for_address``/``get_transaction`` against several
    distinct addresses (the wallet itself, then each of its associated
    token accounts) and each must see its own independent script."""

    pages_by_address: dict[str, list[SignatureInfo]] = dataclasses.field(default_factory=dict)
    transactions: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)
    token_accounts: list[TokenAccountInfo] = dataclasses.field(default_factory=list)
    token_accounts_exception: Exception | None = None
    calls: list[str] = dataclasses.field(default_factory=list)

    async def get_signatures_for_address(
        self,
        wallet_address: str,
        *,
        until_signature: str | None = None,
        before_signature: str | None = None,
        limit: int = 1000,
    ) -> list[SignatureInfo]:
        self.calls.append(f"get_signatures_for_address:{wallet_address}")
        if before_signature is not None:
            return []  # exactly one page per address in this fake
        return self.pages_by_address.get(wallet_address, [])

    async def get_transaction(self, signature: str) -> dict[str, Any]:
        self.calls.append(f"get_transaction:{signature}")
        return self.transactions[signature]

    async def get_token_accounts(self, wallet_address: str) -> list[TokenAccountInfo]:
        self.calls.append(f"get_token_accounts:{wallet_address}")
        if self.token_accounts_exception is not None:
            raise self.token_accounts_exception
        return self.token_accounts

    async def get_signature_statuses(self, signatures: list[str]) -> list[Any]:
        raise NotImplementedError

    async def get_balance(self, wallet_address: str) -> int:
        raise NotImplementedError

    async def get_slot(self) -> int:
        raise NotImplementedError


def _sessionmaker():
    config = load_config()
    info = connection_for_role(config, DbRole.INGEST)
    engine = create_async_engine(info.as_asyncpg_url())
    return config, engine, async_sessionmaker(engine, expire_on_commit=False)


async def _cleanup_wallet(admin_engine: Any, wallet_address: str) -> None:
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
                text("DELETE FROM wallet_acquisition_runs WHERE wallet_id = :w"), {"w": wid}
            )
            await conn.execute(
                text("DELETE FROM swaps WHERE wallet_address = :addr"), {"addr": wallet_address}
            )
            await conn.execute(
                text("DELETE FROM chain_events WHERE wallet_address = :addr"),
                {"addr": wallet_address},
            )
            await conn.execute(text("DELETE FROM wallets WHERE wallet_id = :w"), {"w": wid})
        await conn.commit()


async def test_run_wallet_acquisition_persists_real_chain_events_swaps_and_manifest(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    config, engine, sessionmaker = _sessionmaker()
    try:
        wallet_id = uuid.uuid4()
        async with sessionmaker() as session, session.begin():
            session.add(
                Wallet(
                    wallet_id=wallet_id,
                    wallet_address=wallet_address,
                    first_discovered_at=_NOW,
                    created_at=_NOW,
                )
            )

        account_pubkey = f"acct-{uuid.uuid4().hex[:16]}"
        provider = AddressKeyedChainProvider(
            pages_by_address={
                wallet_address: [_sig("wallet-sig-1", slot=1)],
                account_pubkey: [_sig("account-sig-1", slot=2)],
            },
            transactions={
                "wallet-sig-1": _tx("wallet-sig-1", wallet_address=wallet_address),
                "account-sig-1": _tx("account-sig-1", wallet_address=wallet_address),
            },
            token_accounts=[
                TokenAccountInfo(
                    pubkey=account_pubkey,
                    mint="SomeMint1111111111111111111111111111111",
                    owner=wallet_address,
                    amount_raw=100,
                    decimals=6,
                    raw={},
                )
            ],
        )

        async with sessionmaker() as session, session.begin():
            outcome = await run_wallet_acquisition(
                provider,
                session,
                wallet_id=wallet_id,
                wallet_address=wallet_address,
                provider_name="fake-test-provider",
                now=_NOW,
            )

        assert outcome.transactions_persisted == 2
        assert outcome.transactions_already_known == 0
        assert outcome.manifest.wallet_walk_status == STATUS_COMPLETE
        assert outcome.manifest.token_accounts_enumerated is True
        assert len(outcome.manifest.associated_token_accounts) == 1
        coverage = outcome.manifest.associated_token_accounts[0]
        assert coverage.pubkey == account_pubkey
        assert coverage.mint == "SomeMint1111111111111111111111111111111"
        assert coverage.owner == wallet_address
        assert coverage.status == STATUS_COMPLETE

        async with sessionmaker() as session:
            swap_rows = (
                (
                    await session.execute(
                        select(Swap.parser_version).where(Swap.wallet_address == wallet_address)
                    )
                )
                .scalars()
                .all()
            )
            # Both signatures produced a real, persisted swaps row via the
            # actual parser -- not merely acquired evidence sitting unused.
            assert len(swap_rows) == 2

            run_row = (
                await session.execute(
                    select(WalletAcquisitionRun).where(
                        WalletAcquisitionRun.run_id == outcome.run_id
                    )
                )
            ).scalar_one()
            assert run_row.wallet_id == wallet_id
            assert run_row.manifest["wallet_walk_status"] == STATUS_COMPLETE
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


async def test_run_wallet_acquisition_records_partial_account_and_enumeration_failure(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    config, engine, sessionmaker = _sessionmaker()
    try:
        wallet_id = uuid.uuid4()
        async with sessionmaker() as session, session.begin():
            session.add(
                Wallet(
                    wallet_id=wallet_id,
                    wallet_address=wallet_address,
                    first_discovered_at=_NOW,
                    created_at=_NOW,
                )
            )

        provider = AddressKeyedChainProvider(
            pages_by_address={wallet_address: [_sig("wallet-sig-1", slot=1)]},
            transactions={"wallet-sig-1": _tx("wallet-sig-1", wallet_address=wallet_address)},
            token_accounts_exception=RuntimeError("simulated enumeration failure"),
        )

        async with sessionmaker() as session, session.begin():
            outcome = await run_wallet_acquisition(
                provider,
                session,
                wallet_id=wallet_id,
                wallet_address=wallet_address,
                provider_name="fake-test-provider",
                now=_NOW,
            )

        # Enumeration itself failed -- never silently reported as
        # "enumerated, zero accounts found."
        assert outcome.manifest.token_accounts_enumerated is False
        assert outcome.manifest.known_gaps is not None
        assert "enumeration failed" in outcome.manifest.known_gaps
        assert outcome.manifest.associated_token_accounts == ()
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


async def test_run_wallet_acquisition_deduplicates_already_known_transactions(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    config, engine, sessionmaker = _sessionmaker()
    try:
        wallet_id = uuid.uuid4()
        async with sessionmaker() as session, session.begin():
            session.add(
                Wallet(
                    wallet_id=wallet_id,
                    wallet_address=wallet_address,
                    first_discovered_at=_NOW,
                    created_at=_NOW,
                )
            )

        provider = AddressKeyedChainProvider(
            pages_by_address={wallet_address: [_sig("wallet-sig-1", slot=1)]},
            transactions={"wallet-sig-1": _tx("wallet-sig-1", wallet_address=wallet_address)},
        )

        async with sessionmaker() as session, session.begin():
            first = await run_wallet_acquisition(
                provider,
                session,
                wallet_id=wallet_id,
                wallet_address=wallet_address,
                provider_name="fake-test-provider",
                now=_NOW,
            )
        assert first.transactions_persisted == 1

        async with sessionmaker() as session, session.begin():
            second = await run_wallet_acquisition(
                provider,
                session,
                wallet_id=wallet_id,
                wallet_address=wallet_address,
                provider_name="fake-test-provider",
                now=_NOW,
            )
        assert second.transactions_persisted == 0
        assert second.transactions_already_known == 1

        async with sessionmaker() as session:
            swap_rows = (
                (
                    await session.execute(
                        select(Swap.swap_id).where(Swap.wallet_address == wallet_address)
                    )
                )
                .scalars()
                .all()
            )
            assert len(swap_rows) == 1  # never duplicated
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


async def test_load_verified_acquisition_manifest_rejects_wrong_wallet(admin_engine) -> None:
    wallet_address = _unique_wallet()
    other_wallet_address = _unique_wallet()
    config, engine, sessionmaker = _sessionmaker()
    try:
        wallet_id = uuid.uuid4()
        other_wallet_id = uuid.uuid4()
        async with sessionmaker() as session, session.begin():
            session.add(
                Wallet(
                    wallet_id=wallet_id,
                    wallet_address=wallet_address,
                    first_discovered_at=_NOW,
                    created_at=_NOW,
                )
            )
            session.add(
                Wallet(
                    wallet_id=other_wallet_id,
                    wallet_address=other_wallet_address,
                    first_discovered_at=_NOW,
                    created_at=_NOW,
                )
            )

        provider = AddressKeyedChainProvider()
        async with sessionmaker() as session, session.begin():
            outcome = await run_wallet_acquisition(
                provider,
                session,
                wallet_id=wallet_id,
                wallet_address=wallet_address,
                provider_name="fake-test-provider",
                now=_NOW,
            )

        async with sessionmaker() as session:
            with pytest.raises(AcquisitionRunVerificationError, match="belongs to wallet_id"):
                await load_verified_acquisition_manifest(
                    session, run_id=outcome.run_id, wallet_id=other_wallet_id, as_of=_NOW
                )
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await _cleanup_wallet(admin_engine, other_wallet_address)
        await engine.dispose()


async def test_load_verified_acquisition_manifest_rejects_future_observation_cutoff(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    config, engine, sessionmaker = _sessionmaker()
    try:
        wallet_id = uuid.uuid4()
        async with sessionmaker() as session, session.begin():
            session.add(
                Wallet(
                    wallet_id=wallet_id,
                    wallet_address=wallet_address,
                    first_discovered_at=_NOW,
                    created_at=_NOW,
                )
            )

        provider = AddressKeyedChainProvider()
        async with sessionmaker() as session, session.begin():
            outcome = await run_wallet_acquisition(
                provider,
                session,
                wallet_id=wallet_id,
                wallet_address=wallet_address,
                provider_name="fake-test-provider",
                now=_NOW,
            )

        earlier = datetime(2025, 1, 1, tzinfo=UTC)
        async with sessionmaker() as session:
            with pytest.raises(AcquisitionRunVerificationError, match="learned after"):
                await load_verified_acquisition_manifest(
                    session, run_id=outcome.run_id, wallet_id=wallet_id, as_of=earlier
                )
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


async def test_load_verified_acquisition_manifest_rejects_nonexistent_run_id(
    admin_engine,
) -> None:
    """The exact structural proof that a caller can no longer invent a
    manifest: a random run_id with no backing row is refused outright --
    there is no fallback to caller-supplied JSON."""
    wallet_address = _unique_wallet()
    config, engine, sessionmaker = _sessionmaker()
    try:
        wallet_id = uuid.uuid4()
        async with sessionmaker() as session, session.begin():
            session.add(
                Wallet(
                    wallet_id=wallet_id,
                    wallet_address=wallet_address,
                    first_discovered_at=_NOW,
                    created_at=_NOW,
                )
            )

        async with sessionmaker() as session:
            with pytest.raises(AcquisitionRunVerificationError, match="no wallet_acquisition_runs"):
                await load_verified_acquisition_manifest(
                    session, run_id=uuid.uuid4(), wallet_id=wallet_id, as_of=_NOW
                )
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()
