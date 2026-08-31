"""Real, database-backed :class:`argus.ingestion.reconciliation.WatermarkStore`.

Persists to ``wallet_stream_state`` (MASTER_SPEC.md section 19) via an
injected SQLAlchemy async session -- watermarks must survive process
restart, which an in-memory-only implementation could never satisfy.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from argus.domain.wallet_stream_state import WalletStreamState
from argus.ingestion.reconciliation import WalletWatermark


def _to_dataclass(row: WalletStreamState) -> WalletWatermark:
    return WalletWatermark(
        wallet_address=row.wallet_address,
        last_stream_signature=row.last_stream_signature,
        last_stream_slot=row.last_stream_slot,
        last_reconciled_signature=row.last_reconciled_signature,
        last_reconciled_slot=row.last_reconciled_slot,
        last_reconciliation_at=row.last_reconciliation_at,
        stream_health=row.stream_health,
        wallet_live_state=row.wallet_live_state,
        updated_at=row.updated_at,
    )


class SqlWatermarkStore:
    """One instance per unit-of-work; callers manage the session lifetime
    (commit/rollback) the same way as elsewhere in this codebase."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, wallet_address: str) -> WalletWatermark | None:
        result = await self._session.execute(
            select(WalletStreamState).where(WalletStreamState.wallet_address == wallet_address)
        )
        row = result.scalar_one_or_none()
        return _to_dataclass(row) if row is not None else None

    async def save(self, watermark: WalletWatermark) -> None:
        if watermark.updated_at is None:
            raise ValueError("watermark.updated_at must be set before saving")
        row = await self._session.get(WalletStreamState, watermark.wallet_address)
        if row is None:
            row = WalletStreamState(
                wallet_address=watermark.wallet_address, updated_at=watermark.updated_at
            )
            self._session.add(row)
        row.last_stream_signature = watermark.last_stream_signature
        row.last_stream_slot = watermark.last_stream_slot
        row.last_reconciled_signature = watermark.last_reconciled_signature
        row.last_reconciled_slot = watermark.last_reconciled_slot
        row.last_reconciliation_at = watermark.last_reconciliation_at
        row.stream_health = watermark.stream_health
        row.wallet_live_state = watermark.wallet_live_state
        row.updated_at = watermark.updated_at
        await self._session.flush()
