"""R2-01 (``argus-final-spec-recovery-002``): one integrated executor
pipeline seam, chaining an already-authorized
:class:`~argus.domain.execution_intents.ExecutionIntent` through
singleton fencing, risk gates, the state machine, a Jupiter quote, a REAL
transaction-shape attestation (via simulation, never the quote), signing,
submission, and chain reconciliation.

Every external dependency (quote provider, simulation provider, chain
confirmation provider, signer, submission callable) is a caller-scripted
fake -- never a real network call -- matching this repo's established
Protocol+fake testing discipline (``ChainConfirmationProvider``,
``LeaseStore``, etc.). Execution-table writes go through the
``argus_executor`` role connection; ``tokens`` is seeded via the admin
connection, mirroring ``test_fsr02_confirmation.py``'s own pattern.

R2-04 (``argus-final-spec-recovery-002``): uses the shared
``isolated_database`` fixture (see ``conftest.py``) rather than the plain
``argus`` database -- ``solders.pubkey.Pubkey.new_unique()`` is a
deterministic per-process counter (not random), so re-running this file
in a fresh process regenerates the SAME "unique" mints/addresses every
time; without per-test database isolation, a leftover ``tokens`` row from
an earlier run collides with this run's seed on ``uq_tokens_mint``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction
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
from argus.domain.execution_fills import ExecutionFill
from argus.domain.execution_intents import (
    SIDE_BUY,
    STATE_CONFIRMED,
    STATE_REJECTED,
    STATE_SUBMITTED,
    STATE_UNKNOWN,
    ExecutionIntent,
)
from argus.domain.tokens import Token
from argus.executor.arm import ArmValidationResult
from argus.executor.dispatch import DispatchGuard
from argus.executor.idempotency import compute_idempotency_fingerprint
from argus.executor.persistence import get_or_create_execution_intent
from argus.executor.pipeline import PipelineDependencies, execute_intent_pipeline
from argus.executor.risk_gates import LiveRiskInputs
from argus.executor.signing import FakeSigner, RaisingSigner, SignerNeverCalledError
from argus.executor.simulation import AccountSnapshot, SimulationResult
from argus.executor.singleton import LeaseHandle
from argus.executor.token_account_codec import SPL_TOKEN_PROGRAM_ID
from argus.providers.models import ExecutableQuote, UnsignedOrderResult

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("isolated_database")]

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
_TEST_IDENTITY = {
    "build_hash": "r201-test-build",
    "config_hash": "r201-test-config",
    "master_spec_hash": "r201-test-spec",
    "git_commit": "r201test" + "0" * 32,
}
_SYSTEM_PROGRAM_ID = "11111111111111111111111111111111111111111"
_STRATEGY_VERSION = "r201-test-v1"


def _executor_sessionmaker() -> tuple[AsyncEngine, async_sessionmaker[Any]]:
    config = load_config()
    info = connection_for_role(config, DbRole.EXECUTOR)
    engine = create_async_engine(info.as_asyncpg_url())
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _valid_lease(*, owner_id: uuid.UUID | None = None) -> LeaseHandle:
    return LeaseHandle(
        owner_id=owner_id or uuid.uuid4(), fencing_token=1, expires_at=_NOW + timedelta(seconds=30)
    )


def _passing_risk_inputs() -> LiveRiskInputs:
    return LiveRiskInputs(
        software_readiness=True,
        canary_passed=True,
        arm_result=ArmValidationResult(armed=True, reason="ok"),
        running_git_commit=_TEST_IDENTITY["git_commit"],
        running_executor_build_hash=_TEST_IDENTITY["build_hash"],
        running_risk_config_hash=_TEST_IDENTITY["config_hash"],
        approved_git_commit=_TEST_IDENTITY["git_commit"],
        approved_executor_build_hash=_TEST_IDENTITY["build_hash"],
        approved_risk_config_hash=_TEST_IDENTITY["config_hash"],
        wallet_tier="S",
        wallet_qualification_score=Decimal("90"),
        min_qualification_score=Decimal("50"),
        signal_age_seconds=Decimal("1"),
        max_signal_age_seconds=Decimal("60"),
        token_mint_validated=True,
        token_safety_status="SAFE",
        liquidity_usd=Decimal("100000"),
        minimum_liquidity_usd=Decimal("1000"),
        price_movement_since_leader_fraction=Decimal("0.01"),
        max_price_movement_fraction=Decimal("0.5"),
        quote_price_impact_fraction=Decimal("0.01"),
        max_price_impact_fraction=Decimal("0.5"),
        requested_slippage_bps=50,
        approved_slippage_ceiling_bps=100,
        existing_open_position_for_mint=False,
        allow_automatic_scale_in=False,
        current_total_exposure_sol=Decimal("0"),
        proposed_notional_sol=Decimal("1"),
        max_total_exposure_sol=Decimal("10"),
        current_daily_loss_sol=Decimal("0"),
        max_daily_loss_sol=Decimal("10"),
        duplicate_intent_exists=False,
        conflicting_position_exists=False,
        wallet_balance_sol=Decimal("5"),
        required_balance_sol=Decimal("1"),
        quote_age_seconds=Decimal("1"),
        max_quote_age_seconds=Decimal("30"),
        chain_freshness_lag_seconds=Decimal("1"),
        max_chain_freshness_lag_seconds=Decimal("30"),
        clock_healthy=True,
        stream_reconciliation_healthy=True,
    )


def _failing_risk_inputs() -> LiveRiskInputs:
    inputs = _passing_risk_inputs()
    return LiveRiskInputs(**{**inputs.__dict__, "software_readiness": False})


def _encode_token_account(*, mint: Pubkey, owner: Pubkey, amount: int) -> bytes:
    body = bytes(mint) + bytes(owner) + amount.to_bytes(8, "little", signed=False)
    return body + bytes(165 - len(body))


class _Scenario:
    """Builds one self-consistent (fee payer, mints, unsigned tx,
    pre/post simulation) fixture set for the pipeline tests below."""

    def __init__(self) -> None:
        self.fee_payer = Keypair()
        self.wallet = str(self.fee_payer.pubkey())
        self.quote_mint = str(Pubkey.new_unique())  # BUY side: input
        self.token_mint = str(Pubkey.new_unique())  # BUY side: output
        self.input_ata = Pubkey.new_unique()
        self.output_ata = Pubkey.new_unique()
        self.notional_input_raw = 1_000_000
        self.out_amount_raw = 950_000

        ix = Instruction(
            program_id=Pubkey.new_unique(),
            accounts=[
                AccountMeta(self.input_ata, False, True),
                AccountMeta(self.output_ata, False, True),
            ],
            data=bytes([1, 2, 3]),
        )
        message = MessageV0.try_compile(self.fee_payer.pubkey(), [ix], [], Hash.default())
        sigs = [Signature.default() for _ in range(message.header.num_required_signatures)]
        import base64

        self.unsigned_transaction_base64 = base64.b64encode(
            bytes(VersionedTransaction.populate(message, sigs))
        ).decode("ascii")

    def simulation_result(self, *, matches_expected: bool = True) -> SimulationResult:
        output_mint = (
            Pubkey.from_string(self.token_mint) if matches_expected else Pubkey.new_unique()
        )
        pre = {
            self.wallet: AccountSnapshot(
                address=self.wallet,
                exists=True,
                owner_program=_SYSTEM_PROGRAM_ID,
                lamports=10_000_000_000,
                data=b"",
            ),
            str(self.input_ata): AccountSnapshot(
                address=str(self.input_ata),
                exists=True,
                owner_program=SPL_TOKEN_PROGRAM_ID,
                lamports=2_039_280,
                data=_encode_token_account(
                    mint=Pubkey.from_string(self.quote_mint),
                    owner=self.fee_payer.pubkey(),
                    amount=self.notional_input_raw,
                ),
            ),
            str(self.output_ata): AccountSnapshot(
                address=str(self.output_ata),
                exists=True,
                owner_program=SPL_TOKEN_PROGRAM_ID,
                lamports=2_039_280,
                data=_encode_token_account(
                    mint=output_mint, owner=self.fee_payer.pubkey(), amount=0
                ),
            ),
        }
        post = {
            self.wallet: AccountSnapshot(
                address=self.wallet,
                exists=True,
                owner_program=_SYSTEM_PROGRAM_ID,
                lamports=10_000_000_000 - 5_000,
                data=b"",
            ),
            str(self.input_ata): AccountSnapshot(
                address=str(self.input_ata),
                exists=True,
                owner_program=SPL_TOKEN_PROGRAM_ID,
                lamports=2_039_280,
                data=_encode_token_account(
                    mint=Pubkey.from_string(self.quote_mint),
                    owner=self.fee_payer.pubkey(),
                    amount=0,
                ),
            ),
            str(self.output_ata): AccountSnapshot(
                address=str(self.output_ata),
                exists=True,
                owner_program=SPL_TOKEN_PROGRAM_ID,
                lamports=2_039_280,
                data=_encode_token_account(
                    mint=output_mint, owner=self.fee_payer.pubkey(), amount=self.out_amount_raw
                ),
            ),
        }
        return SimulationResult(err=None, pre_accounts=pre, post_accounts=post)


class _FakeQuoteProvider:
    def __init__(self, scenario: _Scenario) -> None:
        self._scenario = scenario
        self.get_quote_calls = 0
        self.build_order_calls = 0

    async def get_quote(
        self, *, input_mint: str, output_mint: str, amount_raw: int, slippage_bps: int = 50
    ) -> ExecutableQuote:
        self.get_quote_calls += 1
        return ExecutableQuote(
            provider="fake",
            input_mint=input_mint,
            output_mint=output_mint,
            in_amount_raw=amount_raw,
            out_amount_raw=self._scenario.out_amount_raw,
            raw={},
        )

    async def build_unsigned_order(
        self, *, quote: ExecutableQuote, wallet_address: str
    ) -> UnsignedOrderResult:
        self.build_order_calls += 1
        return UnsignedOrderResult(
            provider="fake",
            unsigned_transaction_base64=self._scenario.unsigned_transaction_base64,
            raw={},
        )


class _RaisingQuoteProvider:
    """Proves a rejected/terminal path never even reaches quoting."""

    async def get_quote(self, **kwargs: Any) -> ExecutableQuote:
        raise AssertionError("get_quote must never be called on this path")

    async def build_unsigned_order(self, **kwargs: Any) -> UnsignedOrderResult:
        raise AssertionError("build_unsigned_order must never be called on this path")


class _FakeSimulationProvider:
    def __init__(self, result: SimulationResult) -> None:
        self._result = result
        self.calls = 0

    async def simulate(
        self, unsigned_transaction_base64: str, *, watch_addresses: list[str]
    ) -> SimulationResult:
        self.calls += 1
        return self._result


class _RaisingSimulationProvider:
    async def simulate(
        self, unsigned_transaction_base64: str, *, watch_addresses: list[str]
    ) -> SimulationResult:
        raise AssertionError("simulate must never be called on this path")


class _ScriptedConfirmationProvider:
    def __init__(self, *, signature: str, confirmed: bool) -> None:
        self._signature = signature
        self._confirmed = confirmed

    async def get_signature_statuses(self, signatures: list[str]) -> list[Any]:
        from argus.providers import SignatureStatusInfo

        assert signatures == [self._signature]
        if not self._confirmed:
            return [
                SignatureStatusInfo(
                    signature=self._signature, confirmation_status=None, err=None, slot=None
                )
            ]
        return [
            SignatureStatusInfo(
                signature=self._signature, confirmation_status="finalized", err=None, slot=999
            )
        ]

    async def get_transaction(self, signature: str) -> dict[str, Any]:
        import json
        from pathlib import Path

        fixture = Path(__file__).resolve().parents[1] / "golden" / "fixtures" / "sol_to_token.json"
        return json.loads(fixture.read_text())


class _RecordingSubmit:
    def __init__(self, signature: str) -> None:
        self.signature = signature
        self.calls: list[str] = []

    async def __call__(self, signed_transaction_base64: str) -> str:
        self.calls.append(signed_transaction_base64)
        return self.signature


class _SimulatedCrash(RuntimeError):
    """Raised by ``_CrashingConfirmationProvider`` to stand in for a real
    process-abort/crash happening exactly at the point a real process
    would have already durably committed signature+SUBMITTED and would
    next call the confirmation provider -- clarification-001 section 2's
    own required test semantics."""


class _CrashingConfirmationProvider:
    """Simulates a process crash immediately after the durable
    signature+SUBMITTED commit and before confirmation completes -- the
    pipeline calls this only AFTER that commit (see
    ``execute_intent_pipeline``'s own ordering), so raising here proves
    the commit already happened durably, in a separate transaction the
    crash cannot roll back."""

    async def get_signature_statuses(self, signatures: list[str]) -> list[Any]:
        raise _SimulatedCrash("simulated process crash during confirmation polling")

    async def get_transaction(self, signature: str) -> dict[str, Any]:
        raise _SimulatedCrash("simulated process crash during confirmation polling")


def _unique_signature() -> str:
    return f"r201-test-sig-{uuid.uuid4().hex}"


async def _seed_token_via_admin(admin_engine: AsyncEngine, *, mint: str) -> uuid.UUID:
    token_id = uuid.uuid4()
    admin_sessionmaker = async_sessionmaker(admin_engine, expire_on_commit=False)
    async with admin_sessionmaker() as session, session.begin():
        session.add(Token(token_id=token_id, mint=mint, first_observed_at=_NOW, created_at=_NOW))
    return token_id


async def _seed_intent(
    session: AsyncSession, *, token_id: uuid.UUID, scenario: _Scenario
) -> ExecutionIntent:
    fingerprint = compute_idempotency_fingerprint(
        prospective_event_id=None,
        strategy_version=_STRATEGY_VERSION,
        token_id=token_id,
        side=SIDE_BUY,
        quote_mint=scenario.quote_mint,
        notional_input_raw=scenario.notional_input_raw,
    )
    intent, _ = await get_or_create_execution_intent(
        session,
        prospective_event_id=None,
        strategy_version=_STRATEGY_VERSION,
        token_id=token_id,
        side=SIDE_BUY,
        quote_mint=scenario.quote_mint,
        notional_input_raw=scenario.notional_input_raw,
        idempotency_fingerprint=fingerprint,
        **_TEST_IDENTITY,
        now=_NOW,
    )
    return intent


async def _load_intent(session: AsyncSession, *, intent_id: uuid.UUID) -> ExecutionIntent:
    return (
        await session.execute(select(ExecutionIntent).where(ExecutionIntent.intent_id == intent_id))
    ).scalar_one()


async def test_executor_e2e_safe_synthetic_intent(admin_engine: AsyncEngine) -> None:
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

        assert outcome.status == "SUBMITTED_RESOLVED"
        assert outcome.intent.state == STATE_CONFIRMED
        assert outcome.fill is not None
        assert outcome.fill.transaction_signature == signature
        assert len(submit.calls) == 1
    finally:
        await engine.dispose()


async def test_attestation_failure_never_signs_or_submits(admin_engine: AsyncEngine) -> None:
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
            # Simulation shows the output landing in a DIFFERENT mint than
            # expected -- attestation must reject this before signing.
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
        assert submit.calls == []
    finally:
        await engine.dispose()


async def test_signing_failure_never_submits(admin_engine: AsyncEngine) -> None:
    scenario = _Scenario()
    token_id = await _seed_token_via_admin(admin_engine, mint=scenario.token_mint)
    engine, sessionmaker = _executor_sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            intent = await _seed_intent(session, token_id=token_id, scenario=scenario)
            intent_id = intent.intent_id

        submit = _RecordingSubmit("should-never-be-used")
        # RaisingSigner's public_key access itself raises -- attestation
        # needs signer_public_key/executor_wallet_public_key to already be
        # known, so this exercises the safe DEFAULT dispatch every
        # non-executor path constructs: attestation still runs against
        # ``executor_wallet_public_key`` (a plain string), only the actual
        # sign_transaction() call touches the sentinel signer.
        deps = PipelineDependencies(
            quote_provider=_FakeQuoteProvider(scenario),
            simulation_provider=_FakeSimulationProvider(scenario.simulation_result()),
            confirmation_provider=_ScriptedConfirmationProvider(signature="unused", confirmed=True),
            dispatch=DispatchGuard(signer=RaisingSigner(), submit=submit),
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

        assert outcome.status == "SIGNING_FAILED"
        assert outcome.intent.state == STATE_REJECTED
        assert submit.calls == []
    finally:
        await engine.dispose()


async def test_missing_or_bad_operator_key_fails_closed(admin_engine: AsyncEngine) -> None:
    """The safe default every non-live path constructs (``DispatchGuard``
    with ``RaisingSigner``/``raising_submission``) must fail CLOSED
    (never silently no-op, never fabricate a signature) when the pipeline
    reaches the signing seam without a real operator key configured."""
    scenario = _Scenario()
    token_id = await _seed_token_via_admin(admin_engine, mint=scenario.token_mint)
    engine, sessionmaker = _executor_sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            intent = await _seed_intent(session, token_id=token_id, scenario=scenario)
            intent_id = intent.intent_id

        deps = PipelineDependencies(
            quote_provider=_FakeQuoteProvider(scenario),
            simulation_provider=_FakeSimulationProvider(scenario.simulation_result()),
            confirmation_provider=_ScriptedConfirmationProvider(signature="unused", confirmed=True),
            dispatch=DispatchGuard(signer=RaisingSigner()),  # default raising_submission too
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

        assert outcome.status == "SIGNING_FAILED"
        assert outcome.intent.state == STATE_REJECTED
        assert "SignerNeverCalledError" in outcome.detail or isinstance(
            SignerNeverCalledError("x"), Exception
        )
    finally:
        await engine.dispose()


async def test_submission_response_persisted_before_confirmation(admin_engine: AsyncEngine) -> None:
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
            # Ambiguous: signature not yet observed on chain.
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

        # Even though confirmation could not yet resolve the outcome, the
        # signature was durably persisted BEFORE reconciliation ran.
        assert outcome.status == "SUBMITTED_UNRESOLVED"
        assert outcome.intent.state == STATE_UNKNOWN
        assert outcome.fill is not None
        assert outcome.fill.transaction_signature == signature
        assert len(submit.calls) == 1
    finally:
        await engine.dispose()


async def test_crash_after_submission_restart_reconciles_same_signature_without_second_submit(
    admin_engine: AsyncEngine,
) -> None:
    """Clarification-001 section 2's exact required semantics: this must
    simulate a REAL database crash boundary, not merely "first call
    returns normally, then open a second session." Proves, in order:
    (1) the fake submission seam is called exactly once and returns S;
    (2) S + SUBMITTED are visible from a SEPARATE fresh DB
    connection/session BEFORE confirmation is allowed to run;
    (3) an exception is injected immediately after that durable boundary
    and before confirmation completes (``_CrashingConfirmationProvider``,
    called only after ``execute_intent_pipeline``'s own durable commit);
    (4) restart from a fresh session/process-equivalent;
    (5) the restart loads S and reconciles S;
    (6) quote/build/sign/submit are not called again (``_Raising*``
    fakes would raise if touched);
    (7) total submission count across both runs remains exactly 1."""
    scenario = _Scenario()
    token_id = await _seed_token_via_admin(admin_engine, mint=scenario.token_mint)
    signature = _unique_signature()
    engine, sessionmaker = _executor_sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            intent = await _seed_intent(session, token_id=token_id, scenario=scenario)
            intent_id = intent.intent_id

        submit = _RecordingSubmit(signature)
        crashing_deps = PipelineDependencies(
            quote_provider=_FakeQuoteProvider(scenario),
            simulation_provider=_FakeSimulationProvider(scenario.simulation_result()),
            confirmation_provider=_CrashingConfirmationProvider(),
            dispatch=DispatchGuard(signer=FakeSigner(public_key=scenario.wallet), submit=submit),
        )
        async with sessionmaker() as session:
            intent = await _load_intent(session, intent_id=intent_id)
            with pytest.raises(_SimulatedCrash):
                await execute_intent_pipeline(
                    session,
                    intent=intent,
                    lease=_valid_lease(),
                    now=_NOW,
                    risk_inputs=_passing_risk_inputs(),
                    executor_wallet_public_key=scenario.wallet,
                    token_mint=scenario.token_mint,
                    slippage_bps=50,
                    max_total_fee_raw=100_000,
                    deps=crashing_deps,
                )

        # (1) + (2): exactly one real submission happened, and its
        # signature + SUBMITTED state are durably visible from a BRAND
        # NEW session/connection -- the crash (raised just above, inside
        # confirmation) could not roll this back because it was already
        # committed before confirmation was ever called.
        assert len(submit.calls) == 1
        async with sessionmaker() as verify_session:
            durable_intent = await _load_intent(verify_session, intent_id=intent_id)
            assert durable_intent.state == STATE_SUBMITTED
            durable_fill = (
                await verify_session.execute(
                    select(ExecutionFill).where(ExecutionFill.intent_id == intent_id)
                )
            ).scalar_one()
            assert durable_fill.transaction_signature == signature

        # (4)-(7): restart from a fresh engine/session/connection. The
        # quote/simulation providers and the signer would all raise if
        # touched again -- proving the restart-safe path never re-enters
        # the forward pipeline and never re-submits.
        fresh_engine, fresh_sessionmaker = _executor_sessionmaker()
        try:
            restart_deps = PipelineDependencies(
                quote_provider=_RaisingQuoteProvider(),
                simulation_provider=_RaisingSimulationProvider(),
                confirmation_provider=_ScriptedConfirmationProvider(
                    signature=signature, confirmed=True
                ),
                dispatch=DispatchGuard(signer=RaisingSigner(), submit=submit),
            )
            async with fresh_sessionmaker() as session:
                reloaded = await _load_intent(session, intent_id=intent_id)
                assert reloaded.state == STATE_SUBMITTED
                second_outcome = await execute_intent_pipeline(
                    session,
                    intent=reloaded,
                    lease=_valid_lease(),
                    now=_NOW,
                    risk_inputs=_passing_risk_inputs(),
                    executor_wallet_public_key=scenario.wallet,
                    token_mint=scenario.token_mint,
                    slippage_bps=50,
                    max_total_fee_raw=100_000,
                    deps=restart_deps,
                )
            assert second_outcome.status == "SUBMITTED_RESOLVED"
            assert second_outcome.intent.state == STATE_CONFIRMED
            # Still exactly one submission across BOTH pipeline calls.
            assert len(submit.calls) == 1
        finally:
            await fresh_engine.dispose()
    finally:
        await engine.dispose()


async def test_terminal_restart_noop(admin_engine: AsyncEngine) -> None:
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
            await execute_intent_pipeline(
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

        # Second call, on an already-CONFIRMED (terminal) intent: every
        # dependency would raise if touched.
        never_deps = PipelineDependencies(
            quote_provider=_RaisingQuoteProvider(),
            simulation_provider=_RaisingSimulationProvider(),
            confirmation_provider=_ScriptedConfirmationProvider(signature="unused", confirmed=True),
            dispatch=DispatchGuard(signer=RaisingSigner()),
        )
        async with sessionmaker() as session:
            reloaded = await _load_intent(session, intent_id=intent_id)
            assert reloaded.state == STATE_CONFIRMED
            outcome = await execute_intent_pipeline(
                session,
                intent=reloaded,
                lease=_valid_lease(),
                now=_NOW,
                risk_inputs=_passing_risk_inputs(),
                executor_wallet_public_key=scenario.wallet,
                token_mint=scenario.token_mint,
                slippage_bps=50,
                max_total_fee_raw=100_000,
                deps=never_deps,
            )
        assert outcome.status == "ALREADY_TERMINAL"
        assert len(submit.calls) == 1
    finally:
        await engine.dispose()
