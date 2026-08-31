"""Real, database-backed :class:`argus.ingestion.reconciliation.EventRecorder`.

Persists a :class:`~argus.ingestion.reconciliation.ChainEventDraft` to the
immutable ``chain_events`` table (MASTER_SPEC.md section 18). Dedup is
enforced by the database's own unique constraint
(``uq_chain_events_signature_wallet_type``) rather than a read-then-write
race in application code -- catching the resulting integrity error is what
makes ``record()`` safely concurrent across multiple ingestion paths
observing the same transaction at nearly the same time.

Phase 1 remediation round 2 (argus-phase-1-remediation-002), finding #9:
``record()`` only treats an ``IntegrityError`` as "this is the expected
dedup collision" when the database itself names the exact dedup
constraint as the cause, and only after independently confirming the
expected row now exists -- any other integrity failure (a NOT NULL
violation, a foreign-key violation, an unrelated constraint) is
re-raised, never silently reinterpreted as "duplicate, no-op".
"""

from __future__ import annotations

import uuid

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from argus.db.errors import constraint_name as _constraint_name
from argus.domain.chain_events import ChainEvent
from argus.ingestion.reconciliation import ChainEventDraft, RecordOutcome

_DEDUP_CONSTRAINT = "uq_chain_events_signature_wallet_type"


class SqlEventRecorder:
    """One instance per unit-of-work; callers manage the session lifetime."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, draft: ChainEventDraft) -> RecordOutcome:
        row = ChainEvent(
            event_id=draft.event_id,
            chain=draft.chain,
            slot=draft.slot,
            block_time=draft.block_time,
            first_seen_at=draft.first_seen_at,
            provider=draft.provider,
            provider_received_at=draft.provider_received_at,
            transaction_signature=draft.transaction_signature,
            event_type=draft.event_type,
            wallet_address=draft.wallet_address,
            mint=draft.mint,
            raw_payload=draft.raw_payload,
            payload_hash=draft.payload_hash,
            parser_version=draft.parser_version,
            created_at=draft.created_at,
        )
        try:
            # A SAVEPOINT (not a plain rollback of the whole session): a
            # reconcile() call records many drafts in one shared session
            # before the caller commits. A bare `session.rollback()` on a
            # duplicate would also discard every prior row already
            # flushed-but-uncommitted in this same unit of work -- the
            # nested transaction confines the rollback to this one insert.
            async with self._session.begin_nested():
                self._session.add(row)
                await self._session.flush()
        except IntegrityError as exc:
            if _constraint_name(exc) != _DEDUP_CONSTRAINT:
                raise
            # draft.event_id was never actually stored under this natural
            # key -- look up the real, already-persisted row so callers
            # link any further evidence (commitment observations, parsed
            # output) to the event that genuinely exists, not to a
            # fabricated id that would violate a foreign key. Confirming
            # the row actually exists (rather than trusting the
            # constraint name alone) is what makes this idempotency, not
            # a masked failure -- `.scalar_one()` re-raises if it doesn't.
            existing = (
                await self._session.execute(
                    select(ChainEvent.event_id).where(
                        ChainEvent.transaction_signature == draft.transaction_signature,
                        ChainEvent.wallet_address == draft.wallet_address,
                        ChainEvent.event_type == draft.event_type,
                    )
                )
            ).scalar_one()
            return RecordOutcome(event_id=existing, is_new=False)
        return RecordOutcome(event_id=draft.event_id, is_new=True)

    async def recent_signatures(
        self, wallet_address: str, *, limit: int
    ) -> list[tuple[uuid.UUID, str]]:
        """Implements :class:`argus.ingestion.reconciliation.RecentEventSource`
        -- the most recently first-seen events for this wallet, newest
        first, for a finalization sweep to re-check via
        ``getSignatureStatuses``."""
        result = await self._session.execute(
            select(ChainEvent.event_id, ChainEvent.transaction_signature)
            .where(ChainEvent.wallet_address == wallet_address)
            .order_by(desc(ChainEvent.first_seen_at))
            .limit(limit)
        )
        return [(row.event_id, row.transaction_signature) for row in result.all()]
