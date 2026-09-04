"""argus.executor.persistence — the durable, transactional write paths for
Phase 6 (``argus-phase-6-001``): execution intents, their audited state
transitions, attestations, fills, live positions, risk exit events, and
token safety assessments.

Mirrors ``argus.copyability.persistence``'s established idempotent-insert
pattern (P5-09/F5-05): a new intent is created only under its
``idempotency_fingerprint`` identity via ``INSERT ... ON CONFLICT DO
NOTHING`` + re-select-within-transaction on a lost race, so a restart or
replay can never create two rows for the same semantic intent -- the
database's own unique constraint (migration ``0024``) is the final
backstop, not merely this module's own check.

State transitions are validated by the pure ``argus.executor.state_machine``
function before any write, and always write the new ``state`` on the intent
row and an append-only audit row in the SAME still-open transaction --
never one without the other.

Opening a live position relies on ``live_positions``'s own partial unique
index (``WHERE status = 'OPEN'``) as the actual one-position-per-mint
enforcement mechanism (section 65): this module never pre-checks "is there
already an open position for this mint" and then inserts, since that
check-then-act would itself be a race; the insert is attempted directly and
a concurrent violation surfaces as a normal ``IntegrityError`` from the
database, never silently swallowed.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from argus.domain.execution_attestations import RESULT_FAIL, RESULT_PASS, ExecutionAttestation
from argus.domain.execution_fills import ExecutionFill
from argus.domain.execution_intent_transitions import ExecutionIntentTransition
from argus.domain.execution_intents import STATE_CREATED, ExecutionIntent
from argus.domain.live_positions import STATUS_CLOSED, STATUS_OPEN, LivePosition
from argus.domain.risk_exit_events import RiskExitEvent
from argus.domain.token_safety_assessments import TokenSafetyAssessment
from argus.executor.attestation import AttestationResult
from argus.executor.fill_accounting import ALL_CONFIRMATION_STATES, FillEvidence
from argus.executor.risk_exits import RiskExitTrigger
from argus.executor.state_machine import transition as validate_transition

# Ordinal rank of confirmation_state -- FSR-02's "confirmed chain evidence
# always wins" applies over time too: a later, weaker observation (e.g. a
# transient RPC hiccup re-reporting UNKNOWN) must never overwrite evidence
# already recorded at a stronger level. FAILED ranks with FINALIZED/
# CONFIRMED -- it is just as definitive a terminal chain outcome, only a
# negative one.
_CONFIRMATION_STATE_RANK: dict[str, int] = {
    "UNKNOWN": 0,
    "PROCESSED": 1,
    "CONFIRMED": 2,
    "FINALIZED": 3,
    "FAILED": 3,
}


class StaleFillEvidenceError(RuntimeError):
    """Raised instead of silently overwriting stronger, already-recorded
    fill evidence with a weaker/older observation."""


def _row_values(row: object, table) -> dict:
    return {column.name: getattr(row, column.name) for column in table.columns}


async def get_or_create_execution_intent(
    session: AsyncSession,
    *,
    prospective_event_id: uuid.UUID | None,
    strategy_version: str,
    token_id: uuid.UUID,
    side: str,
    quote_mint: str,
    notional_input_raw: int,
    idempotency_fingerprint: str,
    build_hash: str,
    config_hash: str,
    master_spec_hash: str,
    git_commit: str,
    now: datetime,
) -> tuple[ExecutionIntent, bool]:
    """Returns ``(intent, created)``. A rerun with the same
    ``idempotency_fingerprint`` always reuses the existing row -- a
    restart/replay structurally cannot create a duplicate intent
    (``execution_intents.idempotency_fingerprint`` is UNIQUE, migration
    ``0024``). A freshly-created intent starts life in ``STATE_CREATED``
    with a matching first transition row, written in this same call so an
    intent row never exists without its own creation audit entry."""
    identity = (ExecutionIntent.idempotency_fingerprint == idempotency_fingerprint,)
    existing = (
        await session.execute(select(ExecutionIntent).where(*identity))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    row = ExecutionIntent(
        intent_id=uuid.uuid4(),
        prospective_event_id=prospective_event_id,
        strategy_version=strategy_version,
        token_id=token_id,
        side=side,
        quote_mint=quote_mint,
        notional_input_raw=notional_input_raw,
        state=STATE_CREATED,
        idempotency_fingerprint=idempotency_fingerprint,
        build_hash=build_hash,
        config_hash=config_hash,
        master_spec_hash=master_spec_hash,
        git_commit=git_commit,
        created_at=now,
        updated_at=now,
    )
    stmt = (
        pg_insert(ExecutionIntent)
        .values(**_row_values(row, ExecutionIntent.__table__))
        .on_conflict_do_nothing(constraint="uq_execution_intents_idempotency_fingerprint")
        .returning(ExecutionIntent.intent_id)
    )
    inserted_id = (await session.execute(stmt)).scalar_one_or_none()
    if inserted_id is None:
        # Lost the race -- re-select the winner's row within this SAME
        # still-active transaction rather than rolling back.
        return (await session.execute(select(ExecutionIntent).where(*identity))).scalar_one(), False

    session.add(
        ExecutionIntentTransition(
            transition_id=uuid.uuid4(),
            intent_id=row.intent_id,
            from_state=None,
            to_state=STATE_CREATED,
            reason="intent created",
            created_at=now,
        )
    )
    # The raw INSERT above bypassed the ORM unit of work, so `row` itself
    # is a transient object the session has never tracked -- mutating it
    # later (e.g. apply_transition) would silently be lost at flush time.
    # Re-selecting attaches a session-tracked instance instead, matching
    # the "existing"/"lost the race" branches above.
    return (await session.execute(select(ExecutionIntent).where(*identity))).scalar_one(), True


async def apply_transition(
    session: AsyncSession,
    *,
    intent: ExecutionIntent,
    to_state: str,
    reason: str,
    now: datetime,
) -> ExecutionIntentTransition:
    """Validates the transition against the frozen state machine BEFORE
    writing anything (``argus.executor.state_machine.transition`` raises
    :class:`~argus.executor.state_machine.IllegalTransitionError` rather
    than let an illegal transition through); the intent's own ``state``
    column and its append-only audit row are then both written in this
    same call, so the two can never disagree."""
    validate_transition(intent.state, to_state)
    from_state = intent.state
    intent.state = to_state
    intent.updated_at = now
    row = ExecutionIntentTransition(
        transition_id=uuid.uuid4(),
        intent_id=intent.intent_id,
        from_state=from_state,
        to_state=to_state,
        reason=reason,
        created_at=now,
    )
    session.add(row)
    return row


async def record_attestations(
    session: AsyncSession,
    *,
    intent_id: uuid.UUID,
    result: AttestationResult,
    now: datetime,
) -> list[ExecutionAttestation]:
    """Persists one audit row per attestation dimension (section 78) --
    every dimension is recorded, PASS or FAIL, never only the failures, so
    the audit trail proves every required check actually ran."""
    rows = [
        ExecutionAttestation(
            attestation_id=uuid.uuid4(),
            intent_id=intent_id,
            dimension=dim_result.dimension,
            result=RESULT_PASS if dim_result.passed else RESULT_FAIL,
            detail=dim_result.detail,
            created_at=now,
        )
        for dim_result in result.dimension_results
    ]
    session.add_all(rows)
    return rows


async def get_or_create_execution_fill(
    session: AsyncSession,
    *,
    intent_id: uuid.UUID,
    evidence: FillEvidence,
    now: datetime,
) -> tuple[ExecutionFill, bool]:
    """One fill row per intent (``execution_fills.intent_id`` is UNIQUE) --
    idempotent under the same ``INSERT ... ON CONFLICT DO NOTHING`` +
    re-select pattern as :func:`get_or_create_execution_intent`. A rerun
    against an already-existing row never overwrites it -- evidence that
    arrives after creation (FSR-02: chain confirmation resolving an
    ambiguous submission) goes through
    :func:`update_execution_fill_chain_evidence` instead, which enforces
    that confirmation never regresses."""
    identity = (ExecutionFill.intent_id == intent_id,)
    existing = (await session.execute(select(ExecutionFill).where(*identity))).scalar_one_or_none()
    if existing is not None:
        return existing, False

    row = ExecutionFill(
        fill_id=uuid.uuid4(),
        intent_id=intent_id,
        quoted_input_raw=evidence.quoted_input_raw,
        quoted_output_raw=evidence.quoted_output_raw,
        simulated_input_raw=evidence.simulated_input_raw,
        simulated_output_raw=evidence.simulated_output_raw,
        actual_input_raw=evidence.actual_input_raw,
        actual_output_raw=evidence.actual_output_raw,
        network_fee_raw=evidence.network_fee_raw,
        priority_fee_raw=evidence.priority_fee_raw,
        tip_raw=evidence.tip_raw,
        rent_raw=evidence.rent_raw,
        transaction_signature=evidence.transaction_signature,
        slot=evidence.slot,
        confirmation_state=evidence.confirmation_state,
        created_at=now,
        updated_at=None,
    )
    stmt = (
        pg_insert(ExecutionFill)
        .values(**_row_values(row, ExecutionFill.__table__))
        .on_conflict_do_nothing(constraint="uq_execution_fills_intent_id")
        .returning(ExecutionFill.fill_id)
    )
    inserted_id = (await session.execute(stmt)).scalar_one_or_none()
    if inserted_id is None:
        return (await session.execute(select(ExecutionFill).where(*identity))).scalar_one(), False
    # As in get_or_create_execution_intent: re-select so the returned
    # object is session-tracked, not a transient instance whose later
    # mutations (update_execution_fill_chain_evidence) would be lost.
    return (await session.execute(select(ExecutionFill).where(*identity))).scalar_one(), True


async def load_execution_fill_for_intent(
    session: AsyncSession, *, intent_id: uuid.UUID
) -> ExecutionFill | None:
    """FSR-02's read path for reconciliation: is there already a fill row
    for this intent, and at what confirmation level?"""
    return (
        await session.execute(select(ExecutionFill).where(ExecutionFill.intent_id == intent_id))
    ).scalar_one_or_none()


async def update_execution_fill_chain_evidence(
    session: AsyncSession,
    *,
    fill: ExecutionFill,
    evidence: FillEvidence,
    now: datetime,
) -> ExecutionFill:
    """Updates a fill row's chain-confirmation evidence in place -- the
    ONE update path this otherwise append-only table has (FSR-02). Only
    ``actual_input_raw``/``actual_output_raw``/``network_fee_raw``/
    ``transaction_signature``/``slot``/``confirmation_state`` are ever
    touched here; ``quoted_*``/``simulated_*``/``priority_fee_raw``/
    ``tip_raw``/``rent_raw`` are set once at creation and never revised by
    this function.

    Fails closed (:class:`StaleFillEvidenceError`) rather than silently
    discard evidence: a caller must never pass a ``confirmation_state``
    that ranks weaker than the row's current one (e.g. re-applying a
    transient ``UNKNOWN`` observation over an already-recorded
    ``CONFIRMED``/``FAILED`` outcome)."""
    if evidence.confirmation_state is None or evidence.confirmation_state not in (
        ALL_CONFIRMATION_STATES
    ):
        raise StaleFillEvidenceError(
            f"update_execution_fill_chain_evidence requires a valid confirmation_state, "
            f"got {evidence.confirmation_state!r}"
        )
    existing_rank = _CONFIRMATION_STATE_RANK.get(fill.confirmation_state or "UNKNOWN", 0)
    new_rank = _CONFIRMATION_STATE_RANK[evidence.confirmation_state]
    if new_rank < existing_rank:
        raise StaleFillEvidenceError(
            f"refusing to downgrade execution_fills.confirmation_state from "
            f"{fill.confirmation_state!r} to {evidence.confirmation_state!r} "
            f"(intent_id={fill.intent_id})"
        )

    fill.actual_input_raw = evidence.actual_input_raw
    fill.actual_output_raw = evidence.actual_output_raw
    fill.network_fee_raw = evidence.network_fee_raw
    fill.transaction_signature = evidence.transaction_signature
    fill.slot = evidence.slot
    fill.confirmation_state = evidence.confirmation_state
    fill.updated_at = now
    return fill


async def open_live_position(
    session: AsyncSession,
    *,
    token_id: uuid.UUID,
    opening_intent_id: uuid.UUID,
    opened_at: datetime,
    now: datetime,
) -> LivePosition:
    """Inserts a new ``OPEN`` position directly -- never pre-checks "is one
    already open for this mint" first, since that check-then-act would
    itself race against a concurrent opener. The database's own partial
    unique index (``uq_live_positions_one_open_per_token``, migration
    ``0024``) is the real one-position-per-mint enforcement: a concurrent
    or mistaken second open for the same ``token_id`` raises
    ``IntegrityError`` from the database rather than being silently
    prevented or swallowed here."""
    row = LivePosition(
        position_id=uuid.uuid4(),
        token_id=token_id,
        opening_intent_id=opening_intent_id,
        status=STATUS_OPEN,
        opened_at=opened_at,
        closed_at=None,
        created_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def close_live_position(
    session: AsyncSession,
    *,
    position: LivePosition,
    closed_at: datetime,
) -> LivePosition:
    position.status = STATUS_CLOSED
    position.closed_at = closed_at
    return position


async def record_risk_exit_events(
    session: AsyncSession,
    *,
    position_id: uuid.UUID,
    triggers: Iterable[RiskExitTrigger],
    now: datetime,
) -> list[RiskExitEvent]:
    """Persists every independently-true trigger returned by
    ``argus.executor.risk_exits.evaluate_risk_exits`` -- never only the
    first, since co-occurring triggers (e.g. a liquidity collapse
    alongside a daily-loss breach) must each leave their own audit row."""
    rows = [
        RiskExitEvent(
            risk_exit_id=uuid.uuid4(),
            position_id=position_id,
            trigger_type=trigger.trigger_type,
            detail=trigger.detail,
            created_at=now,
        )
        for trigger in triggers
    ]
    session.add_all(rows)
    return rows


async def record_token_safety_assessment(
    session: AsyncSession,
    *,
    token_id: uuid.UUID,
    token_risk_flags: dict[str, str],
    token_risk_version: str,
    overall_status: str,
    now: datetime,
) -> TokenSafetyAssessment:
    """Always inserts a fresh row -- a token's safety status can
    legitimately change between assessments (section 68), so this is an
    append-only history, never an update-in-place upsert."""
    row = TokenSafetyAssessment(
        assessment_id=uuid.uuid4(),
        token_id=token_id,
        token_risk_flags=dict(token_risk_flags),
        token_risk_version=token_risk_version,
        overall_status=overall_status,
        created_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def load_open_position_for_token(
    session: AsyncSession, *, token_id: uuid.UUID
) -> LivePosition | None:
    """Section 65/66's own read path: is there currently an ``OPEN``
    position for this mint? Used by ``argus.executor.position_policy`` /
    copy-sell callers to decide entry vs. scale-in-prohibition vs.
    copy-sell eligibility -- never used as a pre-check immediately before
    :func:`open_live_position` (see that function's own docstring)."""
    return (
        await session.execute(
            select(LivePosition).where(
                LivePosition.token_id == token_id, LivePosition.status == STATUS_OPEN
            )
        )
    ).scalar_one_or_none()
