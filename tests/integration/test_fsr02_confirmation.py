"""FSR-02 (``argus-final-spec-recovery-001``): real chain-based fill
reconstruction + crash-safe reconciliation.

Reuses the existing Phase 1 golden fixture ``sol_to_token.json`` (a
sanitized, synthetic ``getTransaction``-shaped payload -- see
``tests/golden/test_generic_parser.py``) as the confirmed chain evidence:
1 SOL in, 500,000,000 raw units of TokenA out, 5,000 lamport network fee.
Reusing it here (rather than a second hand-built fixture) proves FSR-02's
reconstruction goes through the SAME parser Phase 1 ingestion already
uses, not a second reimplementation.

Execution-table writes (``execution_intents``/``execution_fills``) go
through the ``argus_executor`` role connection, matching that least-
privilege role's own grants (migration ``0024``: only ``argus_executor``
may INSERT/UPDATE those tables). ``tokens`` (Phase 2) is seeded via the
admin connection instead, since ``argus_executor`` deliberately has no
privilege there either (migration ``0008``) -- this test is exercising
FSR-02's execution/fill write path, not Phase 2's own role boundary.

Follows the exact ``admin_engine``-gated skip pattern every other
DB-backed integration test in this repo uses.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from argus.config import load_config
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.execution_intents import STATE_CONFIRMED, STATE_UNKNOWN, ExecutionIntent
from argus.domain.tokens import Token
from argus.executor.confirmation import reconcile_submitted_fill
from argus.executor.fill_accounting import (
    CONFIRMATION_FINALIZED,
    CONFIRMATION_UNKNOWN,
    FillEvidence,
)
from argus.executor.idempotency import compute_idempotency_fingerprint
from argus.executor.persistence import apply_transition, get_or_create_execution_intent
from argus.providers import SignatureStatusInfo

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("isolated_database")]

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
_TEST_IDENTITY = {
    "build_hash": "fsr02-test-build",
    "config_hash": "fsr02-test-config",
    "master_spec_hash": "fsr02-test-spec",
    "git_commit": "fsr02" + "0" * 35,
}
_WALLET = "GoLDeN1WaLLeTFixTuReAddreSSNoTReaL11111111"
_FIXTURE = Path(__file__).resolve().parents[1] / "golden" / "fixtures" / "sol_to_token.json"


def _unique_signature() -> str:
    # ``execution_fills.transaction_signature`` is unique across the whole
    # table (migration 0037) -- a real Solana signature is globally
    # unique too, so each test uses its own fake one rather than sharing
    # the golden fixture's embedded literal, which would collide with
    # rows other tests (or a prior run against this same shared dev DB)
    # already left behind.
    return f"fsr02-test-sig-{uuid.uuid4().hex}"


_PRIOR_EVIDENCE = FillEvidence(
    quoted_input_raw=1_000_000_000,
    quoted_output_raw=510_000_000,
    simulated_input_raw=1_000_000_000,
    simulated_output_raw=505_000_000,
    priority_fee_raw=1_000,
    tip_raw=500,
    rent_raw=0,
)


def _load_raw_transaction() -> dict[str, Any]:
    return json.loads(_FIXTURE.read_text())


def _executor_sessionmaker() -> tuple[AsyncEngine, async_sessionmaker[Any]]:
    config = load_config()
    info = connection_for_role(config, DbRole.EXECUTOR)
    engine = create_async_engine(info.as_asyncpg_url())
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _unique_mint() -> str:
    return f"FSR02TOK{uuid.uuid4().hex[:36]}"


async def _seed_token_via_admin(admin_engine: AsyncEngine) -> uuid.UUID:
    token_id = uuid.uuid4()
    admin_sessionmaker = async_sessionmaker(admin_engine, expire_on_commit=False)
    async with admin_sessionmaker() as session, session.begin():
        session.add(
            Token(token_id=token_id, mint=_unique_mint(), first_observed_at=_NOW, created_at=_NOW)
        )
    return token_id


async def _seed_submitted_intent(session: AsyncSession, *, token_id: uuid.UUID) -> uuid.UUID:
    fingerprint = compute_idempotency_fingerprint(
        prospective_event_id=None,
        strategy_version="fsr02-test-v1",
        token_id=token_id,
        side="BUY",
        quote_mint="So11111111111111111111111111111111111111112",
        notional_input_raw=1_000_000_000,
    )
    intent, _ = await get_or_create_execution_intent(
        session,
        prospective_event_id=None,
        strategy_version="fsr02-test-v1",
        token_id=token_id,
        side="BUY",
        quote_mint="So11111111111111111111111111111111111111112",
        notional_input_raw=1_000_000_000,
        idempotency_fingerprint=fingerprint,
        **_TEST_IDENTITY,
        now=_NOW,
    )
    for to_state in (
        "VALIDATING",
        "ORDER_REQUESTED",
        "ORDER_READY",
        "ATTESTING",
        "SIGNED",
        "SUBMITTED",
    ):
        await apply_transition(session, intent=intent, to_state=to_state, reason="test", now=_NOW)
    return intent.intent_id


async def _load_intent(session: AsyncSession, *, intent_id: uuid.UUID) -> ExecutionIntent:
    return (
        await session.execute(select(ExecutionIntent).where(ExecutionIntent.intent_id == intent_id))
    ).scalar_one()


class _FakeChainProvider:
    """Test double for ``argus.executor.confirmation.ChainConfirmationProvider``
    -- no real network, no real chain, entirely caller-scripted."""

    def __init__(
        self,
        *,
        signature: str,
        status: SignatureStatusInfo | None,
        raw_transaction: dict[str, Any] | None,
    ) -> None:
        self._signature = signature
        self._status = status
        self._raw_transaction = raw_transaction

    async def get_signature_statuses(self, signatures: list[str]) -> list[SignatureStatusInfo]:
        assert signatures == [self._signature]
        if self._status is None:
            return [
                SignatureStatusInfo(
                    signature=self._signature, confirmation_status=None, err=None, slot=None
                )
            ]
        return [self._status]

    async def get_transaction(self, signature: str) -> dict[str, Any]:
        assert signature == self._signature
        assert self._raw_transaction is not None
        return self._raw_transaction


def _finalized_provider(signature: str) -> _FakeChainProvider:
    return _FakeChainProvider(
        signature=signature,
        status=SignatureStatusInfo(
            signature=signature, confirmation_status="finalized", err=None, slot=100_000_001
        ),
        raw_transaction=_load_raw_transaction(),
    )


def _unknown_provider(signature: str) -> _FakeChainProvider:
    return _FakeChainProvider(signature=signature, status=None, raw_transaction=None)


async def test_confirmed_chain_evidence_differs_from_quote_and_simulation(
    admin_engine: AsyncEngine,
) -> None:
    """The exact FSR-02 requirement: quoted != simulated != actual, all
    three retained, actual sourced from real confirmed chain data (the
    golden fixture), never copied from the quote."""
    token_id = await _seed_token_via_admin(admin_engine)
    signature = _unique_signature()
    engine, sessionmaker = _executor_sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            intent_id = await _seed_submitted_intent(session, token_id=token_id)
        async with sessionmaker() as session, session.begin():
            intent = await _load_intent(session, intent_id=intent_id)
            outcome = await reconcile_submitted_fill(
                session,
                intent=intent,
                signature=signature,
                wallet_address=_WALLET,
                provider=_finalized_provider(signature),
                prior_evidence=_PRIOR_EVIDENCE,
                now=_NOW,
            )
        assert outcome.resolved is True
        assert outcome.intent_state == STATE_CONFIRMED
        assert outcome.confirmation_state == CONFIRMATION_FINALIZED
        fill = outcome.fill
        assert fill.quoted_output_raw == 510_000_000
        assert fill.simulated_output_raw == 505_000_000
        assert fill.actual_output_raw == 500_000_000
        assert fill.actual_input_raw == 1_000_000_000
        # Confirmed chain evidence never equals the quote/simulation here --
        # proves it was really reconstructed, not copied.
        assert fill.actual_output_raw not in (fill.quoted_output_raw, fill.simulated_output_raw)
        assert fill.transaction_signature == signature
        assert fill.slot == 100_000_001
    finally:
        await engine.dispose()


async def test_fee_priority_fee_tip_rent_are_all_tracked_separately(
    admin_engine: AsyncEngine,
) -> None:
    token_id = await _seed_token_via_admin(admin_engine)
    signature = _unique_signature()
    engine, sessionmaker = _executor_sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            intent_id = await _seed_submitted_intent(session, token_id=token_id)
        async with sessionmaker() as session, session.begin():
            intent = await _load_intent(session, intent_id=intent_id)
            outcome = await reconcile_submitted_fill(
                session,
                intent=intent,
                signature=signature,
                wallet_address=_WALLET,
                provider=_finalized_provider(signature),
                prior_evidence=_PRIOR_EVIDENCE,
                now=_NOW,
            )
        fill = outcome.fill
        # network_fee_raw comes from real chain evidence (meta.fee = 5000
        # in the fixture); priority_fee/tip/rent are carried through
        # unchanged from the pre-submission evidence -- never conflated.
        assert fill.network_fee_raw == 5_000
        assert fill.priority_fee_raw == 1_000
        assert fill.tip_raw == 500
        assert fill.rent_raw == 0
    finally:
        await engine.dispose()


async def test_signature_not_yet_observed_leaves_intent_ambiguous_at_unknown(
    admin_engine: AsyncEngine,
) -> None:
    token_id = await _seed_token_via_admin(admin_engine)
    signature = _unique_signature()
    engine, sessionmaker = _executor_sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            intent_id = await _seed_submitted_intent(session, token_id=token_id)
        async with sessionmaker() as session, session.begin():
            intent = await _load_intent(session, intent_id=intent_id)
            outcome = await reconcile_submitted_fill(
                session,
                intent=intent,
                signature=signature,
                wallet_address=_WALLET,
                provider=_unknown_provider(signature),
                prior_evidence=_PRIOR_EVIDENCE,
                now=_NOW,
            )
        assert outcome.resolved is False
        assert outcome.intent_state == STATE_UNKNOWN
        assert outcome.confirmation_state == CONFIRMATION_UNKNOWN
        # Missing evidence stays explicitly unresolved -- never copied
        # from the quote as a substitute.
        assert outcome.fill.actual_input_raw is None
        assert outcome.fill.actual_output_raw is None
        assert outcome.fill.quoted_output_raw == 510_000_000  # quote still retained
    finally:
        await engine.dispose()


async def test_crash_after_submit_before_confirmation_then_restart_resolves(
    admin_engine: AsyncEngine,
) -> None:
    """The crash-recovery scenario: first reconciliation pass finds no
    chain evidence yet (SUBMITTED -> UNKNOWN, matching a simulated
    process crash right after submission); a later pass (simulating a
    restart) finds the transaction now confirmed and resolves it fully,
    never re-deriving evidence that partially existed, never regressing."""
    token_id = await _seed_token_via_admin(admin_engine)
    signature = _unique_signature()
    engine, sessionmaker = _executor_sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            intent_id = await _seed_submitted_intent(session, token_id=token_id)

        # Pass 1: ambiguous.
        async with sessionmaker() as session, session.begin():
            intent = await _load_intent(session, intent_id=intent_id)
            outcome_1 = await reconcile_submitted_fill(
                session,
                intent=intent,
                signature=signature,
                wallet_address=_WALLET,
                provider=_unknown_provider(signature),
                prior_evidence=_PRIOR_EVIDENCE,
                now=_NOW,
            )
        assert outcome_1.intent_state == STATE_UNKNOWN

        # Simulated restart: brand-new engine/session, reload from scratch.
        fresh_engine, fresh_sessionmaker = _executor_sessionmaker()
        try:
            async with fresh_sessionmaker() as session, session.begin():
                reloaded = await _load_intent(session, intent_id=intent_id)
                assert reloaded.state == STATE_UNKNOWN
                outcome_2 = await reconcile_submitted_fill(
                    session,
                    intent=reloaded,
                    signature=signature,
                    wallet_address=_WALLET,
                    provider=_finalized_provider(signature),
                    prior_evidence=_PRIOR_EVIDENCE,
                    now=_NOW,
                )
            assert outcome_2.resolved is True
            assert outcome_2.intent_state == STATE_CONFIRMED
            assert outcome_2.fill.actual_output_raw == 500_000_000
        finally:
            await fresh_engine.dispose()

        async with sessionmaker() as session:
            final = await _load_intent(session, intent_id=intent_id)
            assert final.state == STATE_CONFIRMED
    finally:
        await engine.dispose()


async def test_already_durable_confirmation_restart_is_idempotent(
    admin_engine: AsyncEngine,
) -> None:
    """A restart AFTER the intent already reached CONFIRMED must never
    re-apply the (now illegal) transition, never regress evidence, and
    must return the exact same durable evidence unchanged."""
    token_id = await _seed_token_via_admin(admin_engine)
    signature = _unique_signature()
    engine, sessionmaker = _executor_sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            intent_id = await _seed_submitted_intent(session, token_id=token_id)

        async with sessionmaker() as session, session.begin():
            intent = await _load_intent(session, intent_id=intent_id)
            await reconcile_submitted_fill(
                session,
                intent=intent,
                signature=signature,
                wallet_address=_WALLET,
                provider=_finalized_provider(signature),
                prior_evidence=_PRIOR_EVIDENCE,
                now=_NOW,
            )

        # Restart: reload, reconcile again -- the already-terminal
        # short-circuit means the provider is never queried for a second
        # get_transaction call, and the transition is never re-applied.
        fresh_engine, fresh_sessionmaker = _executor_sessionmaker()
        try:
            async with fresh_sessionmaker() as session, session.begin():
                reloaded = await _load_intent(session, intent_id=intent_id)
                assert reloaded.state == STATE_CONFIRMED
                outcome = await reconcile_submitted_fill(
                    session,
                    intent=reloaded,
                    signature=signature,
                    wallet_address=_WALLET,
                    provider=_finalized_provider(signature),
                    prior_evidence=_PRIOR_EVIDENCE,
                    now=_NOW,
                )
            assert outcome.resolved is True
            assert outcome.intent_state == STATE_CONFIRMED
            assert outcome.fill.actual_output_raw == 500_000_000
        finally:
            await fresh_engine.dispose()
    finally:
        await engine.dispose()
