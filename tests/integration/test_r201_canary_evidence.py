"""Clarification-002 (``argus-final-spec-recovery-002-clarification-002``)
section 2: the persisted canary-evidence contract --
``argus.executor.persistence.record_canary_result`` /
``load_passed_canary_result_for_identity`` -- and the exact success-only
gating condition ``argus.executor.main.run_single_intent_if_configured``
applies before ever calling ``record_canary_result``.

``run_single_intent_if_configured`` itself hardcodes concrete provider
adapters (Jupiter/Helius/Solana submission) and cannot be driven
end-to-end with fakes (matching this repo's own established precedent:
see ``test_r201_single_intent_mode.py``'s docstring and its exclusively
fail-closed-path coverage). These tests instead prove the two real
building blocks ``main.py`` composes: (1) ``execute_intent_pipeline``'s
outcome for a genuine on-chain ``CONFIRMED`` success versus every other
non-success outcome, reusing ``test_r201_executor_pipeline.py``'s own
fakes; and (2) the persistence functions' identity-scoped read/write
contract -- and that the exact ``main.py`` gating condition (``status ==
"SUBMITTED_RESOLVED" and intent.state == STATE_CONFIRMED and fill is not
None``) only ever evaluates True for the genuine-success outcome.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from argus.config import load_config
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.execution_intents import STATE_CONFIRMED, STATE_REJECTED
from argus.executor.arm import ApprovedIdentity
from argus.executor.dispatch import DispatchGuard
from argus.executor.persistence import (
    load_passed_canary_result_for_identity,
    record_canary_result,
)
from argus.executor.pipeline import PipelineDependencies, execute_intent_pipeline
from argus.executor.signing import FakeSigner
from tests.integration.test_r201_executor_pipeline import (
    _NOW,
    _TEST_IDENTITY,
    _FakeQuoteProvider,
    _FakeSimulationProvider,
    _load_intent,
    _passing_risk_inputs,
    _RecordingSubmit,
    _Scenario,
    _ScriptedConfirmationProvider,
    _seed_intent,
    _seed_token_via_admin,
    _unique_signature,
    _valid_lease,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("isolated_database")]

_OTHER_IDENTITY = ApprovedIdentity(
    git_commit="b" * 40,
    executor_build_hash="other-build",
    risk_config_hash="other-config",
    strategy_versions=frozenset({"v1"}),
)


def _executor_sessionmaker() -> tuple[AsyncEngine, async_sessionmaker[Any]]:
    config = load_config()
    info = connection_for_role(config, DbRole.EXECUTOR)
    engine = create_async_engine(info.as_asyncpg_url())
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _approved() -> ApprovedIdentity:
    return ApprovedIdentity(
        git_commit=_TEST_IDENTITY["git_commit"],
        executor_build_hash=_TEST_IDENTITY["build_hash"],
        risk_config_hash=_TEST_IDENTITY["config_hash"],
        strategy_versions=frozenset({"v1"}),
    )


def _satisfies_main_py_canary_gate(outcome: Any) -> bool:
    """Mirrors ``run_single_intent_if_configured``'s exact success-only
    gating condition (``main.py``) without duplicating its DB-writing
    body -- used below to prove the condition itself only ever admits the
    one genuine-success outcome shape, for every outcome family
    ``execute_intent_pipeline`` can return."""
    return bool(
        outcome.status == "SUBMITTED_RESOLVED"
        and outcome.intent.state == STATE_CONFIRMED
        and outcome.fill is not None
        and outcome.fill.transaction_signature
    )


async def test_record_canary_result_persists_evidence_loadable_by_identity(
    admin_engine: AsyncEngine,
) -> None:
    scenario = _Scenario()
    token_id = await _seed_token_via_admin(admin_engine, mint=scenario.token_mint)
    engine, sessionmaker = _executor_sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            intent = await _seed_intent(session, token_id=token_id, scenario=scenario)
            intent_id = intent.intent_id

        approved = _approved()
        async with sessionmaker() as session, session.begin():
            assert await load_passed_canary_result_for_identity(session, approved=approved) is None
            await record_canary_result(
                session,
                intent_id=intent_id,
                transaction_signature=_unique_signature(),
                approved=approved,
                completed_at=_NOW,
            )

        async with sessionmaker() as session:
            loaded = await load_passed_canary_result_for_identity(session, approved=approved)
            assert loaded is not None
            assert loaded.intent_id == intent_id
    finally:
        await engine.dispose()


async def test_canary_result_not_visible_under_a_different_identity(
    admin_engine: AsyncEngine,
) -> None:
    """A pass recorded under one running build/config identity must never
    be found -- and so must never authorize execution -- under a
    different one."""
    scenario = _Scenario()
    token_id = await _seed_token_via_admin(admin_engine, mint=scenario.token_mint)
    engine, sessionmaker = _executor_sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            intent = await _seed_intent(session, token_id=token_id, scenario=scenario)
            intent_id = intent.intent_id

        async with sessionmaker() as session, session.begin():
            await record_canary_result(
                session,
                intent_id=intent_id,
                transaction_signature=_unique_signature(),
                approved=_approved(),
                completed_at=_NOW,
            )

        async with sessionmaker() as session:
            assert (
                await load_passed_canary_result_for_identity(session, approved=_OTHER_IDENTITY)
                is None
            )
            assert (
                await load_passed_canary_result_for_identity(session, approved=_approved())
                is not None
            )
    finally:
        await engine.dispose()


async def test_second_record_for_same_intent_is_rejected(admin_engine: AsyncEngine) -> None:
    """``intent_id`` is UNIQUE (migration 0042): an intent is terminal
    once ``CONFIRMED``, so a second recording attempt for the same intent
    must never silently create a second, potentially-inconsistent row."""
    scenario = _Scenario()
    token_id = await _seed_token_via_admin(admin_engine, mint=scenario.token_mint)
    engine, sessionmaker = _executor_sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            intent = await _seed_intent(session, token_id=token_id, scenario=scenario)
            intent_id = intent.intent_id

        approved = _approved()
        async with sessionmaker() as session, session.begin():
            await record_canary_result(
                session,
                intent_id=intent_id,
                transaction_signature=_unique_signature(),
                approved=approved,
                completed_at=_NOW,
            )

        async with sessionmaker() as session, session.begin():
            with pytest.raises(IntegrityError):
                await record_canary_result(
                    session,
                    intent_id=intent_id,
                    transaction_signature=_unique_signature(),
                    approved=approved,
                    completed_at=_NOW,
                )
    finally:
        await engine.dispose()


async def test_genuine_confirmed_pipeline_success_satisfies_main_py_canary_gate(
    admin_engine: AsyncEngine,
) -> None:
    """Reuses R2-01's own real pipeline fakes: a genuine on-chain
    CONFIRMED fill is the ONE outcome shape for which ``main.py``'s
    success-only gating condition evaluates True -- proving the
    persisted-evidence path is reachable from a real pipeline outcome,
    then that ``record_canary_result`` under that exact condition
    round-trips through ``load_passed_canary_result_for_identity``."""
    scenario = _Scenario()
    token_id = await _seed_token_via_admin(admin_engine, mint=scenario.token_mint)
    signature = _unique_signature()
    engine, sessionmaker = _executor_sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            intent = await _seed_intent(session, token_id=token_id, scenario=scenario)
            intent_id = intent.intent_id

        submit = _RecordingSubmit(signature)
        deps = PipelineDependencies(
            quote_provider=_FakeQuoteProvider(scenario),
            simulation_provider=_FakeSimulationProvider(scenario.simulation_result()),
            confirmation_provider=_ScriptedConfirmationProvider(
                signature=signature, confirmed=True
            ),
            dispatch=DispatchGuard(signer=FakeSigner(public_key=scenario.wallet), submit=submit),
        )
        async with sessionmaker() as session:
            intent = await _load_intent(session, intent_id=intent_id)
            outcome = await execute_intent_pipeline(
                session,
                intent=intent,
                lease=_valid_lease(),
                now=_NOW,
                risk_inputs=_passing_risk_inputs(),
                executor_wallet_public_key=scenario.wallet,
                token_mint=scenario.token_mint,
                slippage_bps=50,
                max_total_fee_raw=100_000,
                deps=deps,
            )

        approved = _approved()
        assert _satisfies_main_py_canary_gate(outcome)
        assert outcome.fill is not None
        signature_from_fill = outcome.fill.transaction_signature
        assert signature_from_fill

        async with sessionmaker() as session, session.begin():
            assert await load_passed_canary_result_for_identity(session, approved=approved) is None
            await record_canary_result(
                session,
                intent_id=intent_id,
                transaction_signature=signature_from_fill,
                approved=approved,
                completed_at=_NOW,
            )

        async with sessionmaker() as session:
            loaded = await load_passed_canary_result_for_identity(session, approved=approved)
            assert loaded is not None
            assert loaded.transaction_signature == signature
    finally:
        await engine.dispose()


async def test_attestation_rejection_never_satisfies_main_py_canary_gate(
    admin_engine: AsyncEngine,
) -> None:
    """A failed canary attempt must never produce evidence: an attestation
    rejection (never signed/submitted) fails the exact ``main.py`` gating
    condition, and no canary result is ever loadable afterward."""
    scenario = _Scenario()
    token_id = await _seed_token_via_admin(admin_engine, mint=scenario.token_mint)
    engine, sessionmaker = _executor_sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            intent = await _seed_intent(session, token_id=token_id, scenario=scenario)
            intent_id = intent.intent_id

        submit = _RecordingSubmit("should-never-be-used")
        deps = PipelineDependencies(
            quote_provider=_FakeQuoteProvider(scenario),
            simulation_provider=_FakeSimulationProvider(
                scenario.simulation_result(matches_expected=False)
            ),
            confirmation_provider=_ScriptedConfirmationProvider(signature="unused", confirmed=True),
            dispatch=DispatchGuard(signer=FakeSigner(public_key=scenario.wallet), submit=submit),
        )
        async with sessionmaker() as session:
            intent = await _load_intent(session, intent_id=intent_id)
            outcome = await execute_intent_pipeline(
                session,
                intent=intent,
                lease=_valid_lease(),
                now=_NOW,
                risk_inputs=_passing_risk_inputs(),
                executor_wallet_public_key=scenario.wallet,
                token_mint=scenario.token_mint,
                slippage_bps=50,
                max_total_fee_raw=100_000,
                deps=deps,
            )

        assert outcome.status == "REJECTED_ATTESTATION"
        assert outcome.intent.state == STATE_REJECTED
        approved = _approved()
        assert not _satisfies_main_py_canary_gate(outcome)
        async with sessionmaker() as session:
            assert await load_passed_canary_result_for_identity(session, approved=approved) is None
    finally:
        await engine.dispose()


async def test_submitted_unresolved_never_satisfies_main_py_canary_gate(
    admin_engine: AsyncEngine,
) -> None:
    """A submitted-but-not-yet-resolved outcome (ambiguous chain state)
    must also never produce canary evidence -- only a genuinely resolved
    CONFIRMED fill may."""
    scenario = _Scenario()
    token_id = await _seed_token_via_admin(admin_engine, mint=scenario.token_mint)
    signature = _unique_signature()
    engine, sessionmaker = _executor_sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            intent = await _seed_intent(session, token_id=token_id, scenario=scenario)
            intent_id = intent.intent_id

        submit = _RecordingSubmit(signature)
        deps = PipelineDependencies(
            quote_provider=_FakeQuoteProvider(scenario),
            simulation_provider=_FakeSimulationProvider(scenario.simulation_result()),
            confirmation_provider=_ScriptedConfirmationProvider(
                signature=signature, confirmed=False
            ),
            dispatch=DispatchGuard(signer=FakeSigner(public_key=scenario.wallet), submit=submit),
        )
        async with sessionmaker() as session:
            intent = await _load_intent(session, intent_id=intent_id)
            outcome = await execute_intent_pipeline(
                session,
                intent=intent,
                lease=_valid_lease(),
                now=_NOW,
                risk_inputs=_passing_risk_inputs(),
                executor_wallet_public_key=scenario.wallet,
                token_mint=scenario.token_mint,
                slippage_bps=50,
                max_total_fee_raw=100_000,
                deps=deps,
            )

        assert outcome.status == "SUBMITTED_UNRESOLVED"
        approved = _approved()
        assert not _satisfies_main_py_canary_gate(outcome)
        async with sessionmaker() as session:
            assert await load_passed_canary_result_for_identity(session, approved=approved) is None
    finally:
        await engine.dispose()
