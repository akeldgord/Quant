"""Real, database-backed :class:`argus.ingestion.reconciliation.EventRecorder`.

Persists a :class:`~argus.ingestion.reconciliation.ChainEventDraft` to the
immutable ``chain_events`` table (MASTER_SPEC.md section 18). Dedup is
enforced by the database's own unique constraint
(``uq_chain_events_signature_wallet_type``) rather than a read-then-write
race in application code -- catching the resulting integrity error is what
makes ``record()`` safely concurrent across multiple ingestion paths
observing the same transaction at nearly the same time.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from argus.domain.chain_events import ChainEvent
from argus.ingestion.reconciliation import ChainEventDraft


class SqlEventRecorder:
    """One instance per unit-of-work; callers manage the session lifetime."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, draft: ChainEventDraft) -> bool:
        row = ChainEvent(
            event_id=draft.event_id,
            chain=draft.chain,
            slot=draft.slot,
            block_time=draft.block_time,
            first_seen_at=draft.first_seen_at,
            confirmed_at=draft.confirmed_at,
            finalized_at=draft.finalized_at,
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
        except IntegrityError:
            return False
        return True
