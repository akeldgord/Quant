"""argus.executor.confirmation — MASTER_SPEC.md section 79 (ACTUAL FILL
ACCOUNTING) + section 76/77 (EXECUTION STATE MACHINE / crash recovery),
FSR-02 (``argus-final-spec-recovery-001``).

Resolves a ``SUBMITTED`` execution intent's real on-chain outcome:
queries confirmed chain state (never trusts the provider quote/response as
a substitute), reconstructs ``actual_input_raw``/``actual_output_raw``/
``network_fee_raw`` from the SAME balance-delta parser Phase 1 uses for
tracked-wallet ingestion (``argus.parsing.generic_parser.parse_transaction``
-- one code path, not a second reimplementation), and drives the intent's
state machine (``argus.executor.state_machine``) to ``CONFIRMED``/
``FAILED``, or leaves it ambiguous at ``UNKNOWN`` when the signature has
not yet been observed on chain or is still at the weak ``processed``
commitment level.

Idempotent and crash-safe: calling this twice for the same intent/
signature -- including after a process restart -- never re-applies an
illegal state transition and never regresses already-recorded evidence
(:func:`argus.executor.persistence.update_execution_fill_chain_evidence`
enforces the second half; this module enforces the first by treating an
already-terminal intent as a no-op read).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from argus.domain.execution_fills import ExecutionFill
from argus.domain.execution_intents import (
    STATE_CONFIRMED,
    STATE_FAILED,
    STATE_SUBMITTED,
    STATE_UNKNOWN,
    ExecutionIntent,
)
from argus.executor.fill_accounting import (
    CONFIRMATION_CONFIRMED,
    CONFIRMATION_FAILED,
    CONFIRMATION_FINALIZED,
    CONFIRMATION_PROCESSED,
    CONFIRMATION_UNKNOWN,
    FillEvidence,
)
from argus.executor.persistence import (
    apply_transition,
    get_or_create_execution_fill,
    load_execution_fill_for_intent,
    update_execution_fill_chain_evidence,
)
from argus.parsing.generic_parser import parse_transaction
from argus.providers import SignatureStatusInfo

# Only "confirmed" and above are safe to treat as a durable, non-reversible
# on-chain outcome -- Solana's weakest "processed" commitment can still be
# rolled back, so it is recorded as evidence but the intent stays UNKNOWN
# (ambiguous, needs another reconciliation pass) rather than CONFIRMED.
_SOLANA_COMMITMENT_TO_CONFIRMATION_STATE = {
    "processed": CONFIRMATION_PROCESSED,
    "confirmed": CONFIRMATION_CONFIRMED,
    "finalized": CONFIRMATION_FINALIZED,
}
_DURABLE_CONFIRMATION_STATES = frozenset({CONFIRMATION_CONFIRMED, CONFIRMATION_FINALIZED})


class ChainConfirmationProvider(Protocol):
    """The minimal read-only chain-query seam reconciliation needs --
    exactly the two methods ``argus.providers.helius.client.HeliusRpcClient``
    already implements, narrowed to a ``Protocol`` so tests can supply a
    fake without a real network/DB dependency. ``get_signature_statuses``
    is typed against the real, shared ``SignatureStatusInfo`` shape
    (never a second hand-written structural duplicate of it) -- a fake
    test double constructs and returns real ``SignatureStatusInfo``
    instances too."""

    async def get_signature_statuses(
        self, signatures: list[str]
    ) -> Sequence[SignatureStatusInfo]: ...

    async def get_transaction(self, signature: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ReconciliationOutcome:
    intent_state: str
    confirmation_state: str
    fill: ExecutionFill
    resolved: bool
    """``True`` once the intent has reached a terminal state
    (``CONFIRMED``/``FAILED``) -- ``False`` while still ``UNKNOWN`` and
    requiring another reconciliation pass."""


async def reconcile_submitted_fill(
    session: AsyncSession,
    *,
    intent: ExecutionIntent,
    signature: str,
    wallet_address: str,
    provider: ChainConfirmationProvider,
    prior_evidence: FillEvidence,
    now: datetime,
) -> ReconciliationOutcome:
    """Resolves ``intent`` (currently ``SUBMITTED`` or ``UNKNOWN``)
    against real confirmed chain state. Never called for a
    ``CREATED``/``VALIDATING``/... intent that has not actually submitted
    a transaction -- ``signature`` must already be known.

    ``prior_evidence`` carries the quoted/simulated evidence already
    captured before submission; this function only ever adds to it
    (``actual_*``/``network_fee_raw``/evidence-reference fields), it never
    fabricates a quote/simulation value it wasn't given."""
    if intent.state in (STATE_CONFIRMED, STATE_FAILED):
        # Idempotent restart: the intent already reached a durable
        # terminal outcome on a prior pass. Re-applying apply_transition
        # here would raise IllegalTransitionError (CONFIRMED/FAILED have
        # no legal next state) -- this is a read-only no-op instead,
        # never a silent re-derivation of evidence that already exists.
        existing_fill = await load_execution_fill_for_intent(session, intent_id=intent.intent_id)
        assert existing_fill is not None, (
            f"intent {intent.intent_id} reached {intent.state} without a fill row"
        )
        return ReconciliationOutcome(
            intent_state=intent.state,
            confirmation_state=existing_fill.confirmation_state or CONFIRMATION_UNKNOWN,
            fill=existing_fill,
            resolved=True,
        )

    if intent.state not in (STATE_SUBMITTED, STATE_UNKNOWN):
        raise ValueError(
            f"reconcile_submitted_fill requires a SUBMITTED or UNKNOWN intent, got {intent.state!r}"
        )

    statuses = await provider.get_signature_statuses([signature])
    status = statuses[0]

    if status.confirmation_status is None:
        # Not yet observed on chain at all -- ambiguous, matches
        # STATE_UNKNOWN's own definition (section 77).
        evidence = FillEvidence(
            quoted_input_raw=prior_evidence.quoted_input_raw,
            quoted_output_raw=prior_evidence.quoted_output_raw,
            simulated_input_raw=prior_evidence.simulated_input_raw,
            simulated_output_raw=prior_evidence.simulated_output_raw,
            priority_fee_raw=prior_evidence.priority_fee_raw,
            tip_raw=prior_evidence.tip_raw,
            rent_raw=prior_evidence.rent_raw,
            transaction_signature=signature,
            confirmation_state=CONFIRMATION_UNKNOWN,
        )
        fill = await _persist_evidence(session, intent=intent, evidence=evidence, now=now)
        if intent.state == STATE_SUBMITTED:
            await apply_transition(
                session,
                intent=intent,
                to_state=STATE_UNKNOWN,
                reason="signature not yet observed on chain",
                now=now,
            )
        return ReconciliationOutcome(
            intent_state=intent.state,
            confirmation_state=CONFIRMATION_UNKNOWN,
            fill=fill,
            resolved=False,
        )

    if status.err is not None:
        raw_transaction = await provider.get_transaction(signature)
        parsed = parse_transaction(
            raw_transaction, wallet_address=wallet_address, slot=status.slot or 0, block_time=None
        )
        # A failed transaction moves no swap funds, but the network fee is
        # still real chain evidence (Solana charges the fee-payer even on
        # instruction failure) -- recorded, never fabricated into a
        # nonexistent successful swap.
        evidence = FillEvidence(
            quoted_input_raw=prior_evidence.quoted_input_raw,
            quoted_output_raw=prior_evidence.quoted_output_raw,
            simulated_input_raw=prior_evidence.simulated_input_raw,
            simulated_output_raw=prior_evidence.simulated_output_raw,
            priority_fee_raw=prior_evidence.priority_fee_raw,
            tip_raw=prior_evidence.tip_raw,
            rent_raw=prior_evidence.rent_raw,
            network_fee_raw=parsed.network_fee_raw,
            transaction_signature=signature,
            slot=status.slot,
            confirmation_state=CONFIRMATION_FAILED,
        )
        fill = await _persist_evidence(session, intent=intent, evidence=evidence, now=now)
        await apply_transition(
            session,
            intent=intent,
            to_state=STATE_FAILED,
            reason="confirmed on-chain transaction failed",
            now=now,
        )
        return ReconciliationOutcome(
            intent_state=STATE_FAILED,
            confirmation_state=CONFIRMATION_FAILED,
            fill=fill,
            resolved=True,
        )

    confirmation_state = _SOLANA_COMMITMENT_TO_CONFIRMATION_STATE[status.confirmation_status]
    raw_transaction = await provider.get_transaction(signature)
    parsed = parse_transaction(
        raw_transaction, wallet_address=wallet_address, slot=status.slot or 0, block_time=None
    )
    evidence = FillEvidence(
        quoted_input_raw=prior_evidence.quoted_input_raw,
        quoted_output_raw=prior_evidence.quoted_output_raw,
        simulated_input_raw=prior_evidence.simulated_input_raw,
        simulated_output_raw=prior_evidence.simulated_output_raw,
        # Chain-confirmed actual evidence -- never copied from the quote;
        # None when the parser could not positively classify a swap leg
        # (matches FillEvidence's own "missing stays None" rule).
        actual_input_raw=parsed.input_amount_raw,
        actual_output_raw=parsed.output_amount_raw,
        network_fee_raw=parsed.network_fee_raw,
        priority_fee_raw=prior_evidence.priority_fee_raw,
        tip_raw=prior_evidence.tip_raw,
        rent_raw=prior_evidence.rent_raw,
        transaction_signature=signature,
        slot=status.slot,
        confirmation_state=confirmation_state,
    )
    fill = await _persist_evidence(session, intent=intent, evidence=evidence, now=now)

    if confirmation_state not in _DURABLE_CONFIRMATION_STATES:
        # "processed" only -- too weak to treat as final; stays ambiguous.
        if intent.state == STATE_SUBMITTED:
            await apply_transition(
                session,
                intent=intent,
                to_state=STATE_UNKNOWN,
                reason="observed at 'processed' commitment only, not yet durable",
                now=now,
            )
        return ReconciliationOutcome(
            intent_state=intent.state,
            confirmation_state=confirmation_state,
            fill=fill,
            resolved=False,
        )

    await apply_transition(
        session,
        intent=intent,
        to_state=STATE_CONFIRMED,
        reason=f"confirmed on chain at {status.confirmation_status}",
        now=now,
    )
    return ReconciliationOutcome(
        intent_state=STATE_CONFIRMED,
        confirmation_state=confirmation_state,
        fill=fill,
        resolved=True,
    )


async def _persist_evidence(
    session: AsyncSession, *, intent: ExecutionIntent, evidence: FillEvidence, now: datetime
) -> ExecutionFill:
    existing = await load_execution_fill_for_intent(session, intent_id=intent.intent_id)
    if existing is None:
        fill, _ = await get_or_create_execution_fill(
            session, intent_id=intent.intent_id, evidence=evidence, now=now
        )
        return fill
    return await update_execution_fill_chain_evidence(
        session, fill=existing, evidence=evidence, now=now
    )
