"""argus.executor.pipeline — the one integrated executor pipeline seam,
R2-01 (``argus-final-spec-recovery-002``).

Chains an already-authorized :class:`~argus.domain.execution_intents.
ExecutionIntent` through every seam Phase 6 built independently (risk
gates, the state machine, Jupiter quoting, transaction attestation,
signing, submission, chain reconciliation) into ONE real orchestration
function -- closing the gap the R2 audit found: every seam existed and
was independently tested, but nothing ever called them in sequence for a
real intent (``argus.executor.main`` only ran a one-shot startup/
readiness check).

Ordering (never reordered, never partially applied):

    singleton fencing (lease still valid)
      -> risk/safety gates (``argus.executor.risk_gates``)
      -> legal state transitions (``argus.executor.state_machine`` via
         ``argus.executor.persistence.apply_transition``)
      -> Jupiter quote + unsigned order
      -> REAL ``UnsignedTransactionShape`` from actual transaction bytes
         (``argus.executor.tx_deserialize``, backed by a real simulation,
         never the provider's own quote)
      -> ``attest_transaction(...).all_passed`` required before signing
      -> injected ``Signer`` (never called before attestation passes)
      -> injected submission seam, called AT MOST ONCE per pipeline
         invocation for a given idempotency fingerprint
      -> signature + SUBMITTED persisted BEFORE any confirmation attempt
      -> ``reconcile_submitted_fill`` against real chain state

Restart-safe: once an intent's fill row carries a
``transaction_signature`` (i.e. its state is already ``SUBMITTED`` or
``UNKNOWN``), this function NEVER re-quotes, re-attests, re-signs, or
re-submits -- it goes straight to reconciliation using the persisted
signature. A terminal intent (``CONFIRMED``/``FAILED``/``REJECTED``) is a
pure read-only no-op. This is what makes calling this function twice for
the same intent (a crash-and-restart, or the same idempotency fingerprint
observed again) always safe.
"""

from __future__ import annotations

import base64
import inspect
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from argus.domain.execution_fills import ExecutionFill
from argus.domain.execution_intents import (
    SIDE_BUY,
    STATE_ATTESTING,
    STATE_ORDER_READY,
    STATE_ORDER_REQUESTED,
    STATE_REJECTED,
    STATE_SIGNED,
    STATE_SUBMITTED,
    STATE_UNKNOWN,
    STATE_VALIDATING,
    ExecutionIntent,
)
from argus.executor.attestation import ExpectedTransactionShape, attest_transaction
from argus.executor.confirmation import ChainConfirmationProvider, reconcile_submitted_fill
from argus.executor.dispatch import DispatchGuard
from argus.executor.fill_accounting import CONFIRMATION_UNKNOWN, FillEvidence
from argus.executor.persistence import (
    apply_transition,
    get_or_create_execution_fill,
    load_execution_fill_for_intent,
    record_attestations,
)
from argus.executor.risk_gates import LiveRiskInputs, build_gates, evaluate_live_risk
from argus.executor.simulation import TransactionSimulationProvider
from argus.executor.singleton import LeaseHandle
from argus.executor.state_machine import TERMINAL_STATES
from argus.executor.tx_deserialize import (
    deserialize_unsigned_transaction_shape,
    unsigned_transaction_account_keys,
)
from argus.providers.models import ExecutableQuote, UnsignedOrderResult


class QuoteProvider(Protocol):
    """Structurally identical to ``argus.providers.jupiter.client.
    JupiterClient`` -- a ``Protocol`` so tests inject a fake without a
    real network dependency."""

    async def get_quote(
        self, *, input_mint: str, output_mint: str, amount_raw: int, slippage_bps: int = 50
    ) -> ExecutableQuote: ...

    async def build_unsigned_order(
        self, *, quote: ExecutableQuote, wallet_address: str
    ) -> UnsignedOrderResult: ...


class LeaseExpiredError(RuntimeError):
    """Raised instead of proceeding past the singleton-fencing check with
    an already-expired lease -- a stale/soon-to-be-superseded owner must
    never sign or submit anything."""


PipelineStatus = Literal[
    "ALREADY_TERMINAL",
    "REJECTED_RISK",
    "REJECTED_ATTESTATION",
    "SIGNING_FAILED",
    "SUBMITTED_RESOLVED",
    "SUBMITTED_UNRESOLVED",
]


@dataclass(frozen=True)
class PipelineOutcome:
    intent: ExecutionIntent
    status: PipelineStatus
    detail: str
    fill: ExecutionFill | None = None


@dataclass(frozen=True)
class PipelineDependencies:
    quote_provider: QuoteProvider
    simulation_provider: TransactionSimulationProvider
    confirmation_provider: ChainConfirmationProvider
    dispatch: DispatchGuard


def _side_mints(*, side: str, quote_mint: str, token_mint: str) -> tuple[str, str]:
    """Returns ``(input_mint, output_mint)`` for the intent's own side --
    a BUY spends ``quote_mint`` for ``token_mint``; a SELL is the
    reverse. Never guessed from anything but the intent's own recorded
    ``side``."""
    if side == SIDE_BUY:
        return quote_mint, token_mint
    return token_mint, quote_mint


async def execute_intent_pipeline(
    session: AsyncSession,
    *,
    intent: ExecutionIntent,
    lease: LeaseHandle,
    now: datetime,
    risk_inputs: LiveRiskInputs,
    executor_wallet_public_key: str,
    token_mint: str,
    slippage_bps: int,
    max_total_fee_raw: int,
    deps: PipelineDependencies,
) -> PipelineOutcome:
    """The one integrated pipeline call for ``intent``. Every external
    dependency (quote provider, simulation provider, chain-confirmation
    provider, signer+submission via ``DispatchGuard``) is injected, so
    this is fully testable without a real network or a real key."""
    if lease.expires_at <= now:
        raise LeaseExpiredError(
            f"executor lease for owner={lease.owner_id} fencing_token={lease.fencing_token} "
            f"expired at {lease.expires_at.isoformat()} (now={now.isoformat()}); refusing to "
            "sign or submit under a stale lease"
        )

    if intent.state in TERMINAL_STATES:
        existing_fill = await load_execution_fill_for_intent(session, intent_id=intent.intent_id)
        return PipelineOutcome(
            intent=intent,
            status="ALREADY_TERMINAL",
            detail=f"intent already terminal at {intent.state}; no-op",
            fill=existing_fill,
        )

    # R2-01 clarification-001: this function owns its own transaction
    # boundaries from here on -- it commits durably on every return path,
    # rather than relying on a caller-managed ambient transaction spanning
    # the whole call. Callers must NOT wrap this call in their own
    # `async with session.begin():` block (SQLAlchemy raises
    # ``InvalidRequestError`` if code inside such a block calls
    # ``session.commit()`` directly, confirmed empirically) -- they may
    # rely on the session's own autobegin behavior instead.

    input_mint, output_mint = _side_mints(
        side=intent.side, quote_mint=intent.quote_mint, token_mint=token_mint
    )

    if intent.state in (STATE_SUBMITTED, STATE_UNKNOWN):
        # Restart-safe path: a signature was ALREADY persisted on a prior
        # pass (this is the only way an intent can reach SUBMITTED/UNKNOWN
        # -- see the forward path below). Never re-quote/re-attest/
        # re-sign/re-submit; go straight to reconciliation.
        existing_fill = await load_execution_fill_for_intent(session, intent_id=intent.intent_id)
        if existing_fill is None or not existing_fill.transaction_signature:
            raise RuntimeError(
                f"intent {intent.intent_id} is in state {intent.state!r} but has no persisted "
                "transaction_signature -- this violates the pipeline's own invariant that a "
                "signature is always persisted before the SUBMITTED transition"
            )
        outcome = await reconcile_submitted_fill(
            session,
            intent=intent,
            signature=existing_fill.transaction_signature,
            wallet_address=executor_wallet_public_key,
            provider=deps.confirmation_provider,
            prior_evidence=FillEvidence(
                quoted_input_raw=existing_fill.quoted_input_raw,
                quoted_output_raw=existing_fill.quoted_output_raw,
                simulated_input_raw=existing_fill.simulated_input_raw,
                simulated_output_raw=existing_fill.simulated_output_raw,
                priority_fee_raw=existing_fill.priority_fee_raw,
                tip_raw=existing_fill.tip_raw,
                rent_raw=existing_fill.rent_raw,
                transaction_signature=existing_fill.transaction_signature,
            ),
            now=now,
        )
        await session.commit()
        return PipelineOutcome(
            intent=intent,
            status="SUBMITTED_RESOLVED" if outcome.resolved else "SUBMITTED_UNRESOLVED",
            detail=f"restart-safe reconciliation resumed from {intent.state}",
            fill=outcome.fill,
        )

    # Forward path: intent is CREATED (or another pre-signing state) --
    # walk it through the full pipeline exactly once.
    await apply_transition(
        session, intent=intent, to_state=STATE_VALIDATING, reason="pipeline started", now=now
    )

    risk_result = evaluate_live_risk(build_gates(risk_inputs))
    if not risk_result.approved:
        await apply_transition(
            session,
            intent=intent,
            to_state=STATE_REJECTED,
            reason=f"risk gates failed: {', '.join(risk_result.reason_codes)}",
            now=now,
        )
        await session.commit()
        return PipelineOutcome(
            intent=intent,
            status="REJECTED_RISK",
            detail=f"failed gates: {risk_result.reason_codes}",
        )

    await apply_transition(
        session, intent=intent, to_state=STATE_ORDER_REQUESTED, reason="requesting quote", now=now
    )
    quote = await deps.quote_provider.get_quote(
        input_mint=input_mint,
        output_mint=output_mint,
        amount_raw=intent.notional_input_raw,
        slippage_bps=slippage_bps,
    )

    await apply_transition(
        session, intent=intent, to_state=STATE_ORDER_READY, reason="unsigned order built", now=now
    )
    order = await deps.quote_provider.build_unsigned_order(
        quote=quote, wallet_address=executor_wallet_public_key
    )

    await apply_transition(
        session, intent=intent, to_state=STATE_ATTESTING, reason="attesting transaction", now=now
    )
    watch_addresses = unsigned_transaction_account_keys(order.unsigned_transaction_base64)
    simulation = await deps.simulation_provider.simulate(
        order.unsigned_transaction_base64, watch_addresses=watch_addresses
    )
    tx_shape = deserialize_unsigned_transaction_shape(
        order.unsigned_transaction_base64,
        simulation=simulation,
        executor_wallet_public_key=executor_wallet_public_key,
        expected_input_mint=input_mint,
        expected_output_mint=output_mint,
    )
    expected = ExpectedTransactionShape(
        expected_signer_public_key=executor_wallet_public_key,
        executor_wallet_public_key=executor_wallet_public_key,
        input_mint=input_mint,
        output_mint=output_mint,
        intended_input_amount_raw=intent.notional_input_raw,
        max_total_fee_raw=max_total_fee_raw,
    )
    attestation = attest_transaction(tx_shape, expected)
    await record_attestations(session, intent_id=intent.intent_id, result=attestation, now=now)
    if not attestation.all_passed:
        await apply_transition(
            session,
            intent=intent,
            to_state=STATE_REJECTED,
            reason=f"attestation failed: {attestation.failed_dimensions}",
            now=now,
        )
        await session.commit()
        return PipelineOutcome(
            intent=intent,
            status="REJECTED_ATTESTATION",
            detail=f"failed dimensions: {attestation.failed_dimensions}",
        )

    try:
        signed_bytes = deps.dispatch.signer.sign_transaction(
            base64.b64decode(order.unsigned_transaction_base64, validate=True)
        )
    except Exception as exc:  # noqa: BLE001 - any signing failure fails closed
        await apply_transition(
            session,
            intent=intent,
            to_state=STATE_REJECTED,
            reason=f"signing failed: {type(exc).__name__}: {exc}",
            now=now,
        )
        await session.commit()
        return PipelineOutcome(intent=intent, status="SIGNING_FAILED", detail=str(exc))

    await apply_transition(
        session, intent=intent, to_state=STATE_SIGNED, reason="transaction signed", now=now
    )

    # The ONE call to the injected submission seam for this pipeline
    # invocation -- exactly once per idempotency fingerprint, since a
    # restart never re-enters this forward path once the signature below
    # is persisted (see the restart-safe branch above).
    signed_b64 = base64.b64encode(signed_bytes).decode("ascii")
    submit_result = deps.dispatch.submit(signed_b64)
    signature = await submit_result if inspect.isawaitable(submit_result) else submit_result
    if not isinstance(signature, str) or not signature:
        raise RuntimeError(f"submission seam returned a non-signature result: {signature!r}")

    prior_evidence = FillEvidence(
        quoted_input_raw=quote.in_amount_raw,
        quoted_output_raw=quote.out_amount_raw,
        simulated_input_raw=tx_shape.input_amount_raw,
        simulated_output_raw=None,
        transaction_signature=signature,
        confirmation_state=CONFIRMATION_UNKNOWN,
    )
    # Signature + SUBMITTED are persisted together and DURABLY COMMITTED
    # (not merely flushed inside a still-open transaction that a crash
    # could still roll back) BEFORE any confirmation attempt -- a crash
    # right after this commit resumes via the restart-safe branch above,
    # never by re-submitting. This is the exact "durable before
    # confirmation" boundary clarification-001 requires: a separate
    # fresh session opened after this point (and before confirmation
    # runs) can already see S/SUBMITTED.
    await get_or_create_execution_fill(
        session, intent_id=intent.intent_id, evidence=prior_evidence, now=now
    )
    await apply_transition(
        session,
        intent=intent,
        to_state=STATE_SUBMITTED,
        reason=f"submitted as {signature}",
        now=now,
    )
    await session.commit()

    outcome = await reconcile_submitted_fill(
        session,
        intent=intent,
        signature=signature,
        wallet_address=executor_wallet_public_key,
        provider=deps.confirmation_provider,
        prior_evidence=prior_evidence,
        now=now,
    )
    await session.commit()
    return PipelineOutcome(
        intent=intent,
        status="SUBMITTED_RESOLVED" if outcome.resolved else "SUBMITTED_UNRESOLVED",
        detail=f"submitted as {signature}",
        fill=outcome.fill,
    )
