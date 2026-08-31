"""Real, database-backed :class:`argus.ingestion.reconciliation.SwapRecorder`.

Persists to ``swaps`` (MASTER_SPEC.md section 21), deduplicated on
``(event_id, parser_version)`` via the table's own unique constraint --
re-running the same parser version against the same event is idempotent;
a new parser version may add an additional row without disturbing a prior
point-in-time result (Phase 1 remediation round 1, finding #4).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from argus.domain.swaps import Swap
from argus.parsing.generic_parser import ParsedTransaction


class SqlSwapRecorder:
    """One instance per unit-of-work; callers manage the session lifetime."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        event_id: uuid.UUID,
        wallet_address: str,
        parsed: ParsedTransaction,
        created_at: datetime,
    ) -> bool:
        row = Swap(
            swap_id=uuid.uuid4(),
            event_id=event_id,
            wallet_address=wallet_address,
            classification=parsed.classification,
            input_mint=parsed.input_mint,
            input_amount_raw=parsed.input_amount_raw,
            input_amount_ui=parsed.input_amount_ui,
            output_mint=parsed.output_mint,
            output_amount_raw=parsed.output_amount_raw,
            output_amount_ui=parsed.output_amount_ui,
            network_fee_raw=parsed.network_fee_raw,
            slot=parsed.slot,
            block_time=parsed.block_time,
            first_seen_at=created_at,
            confidence=parsed.confidence,
            parser_version=parsed.parser_version,
            created_at=created_at,
        )
        try:
            # Same SAVEPOINT dedup pattern as SqlEventRecorder: confines a
            # duplicate-key rollback to this one insert, never discarding
            # other rows already flushed-but-uncommitted in the same
            # multi-item reconcile() session.
            async with self._session.begin_nested():
                self._session.add(row)
                await self._session.flush()
        except IntegrityError:
            return False
        return True
