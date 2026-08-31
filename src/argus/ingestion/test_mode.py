"""In-memory, network-free harness for ``argus ingest run --test-mode``.

Phase 1 remediation round 1, finding #1 requires "an offline deterministic
``argus ingest run`` smoke test using injected fakes or a dedicated
test-mode harness that cannot broadcast transactions" as one of the
mandatory validation commands. This module is that harness: it proves the
CLI command's own construction/wiring and the
:class:`~argus.ingestion.manager.IngestionManager` orchestration loop work
end-to-end without a credential, a real database, or a live network
connection.

Never claims to validate anything about a real provider's behavior
(MASTER_SPEC.md section 108) -- ``NullLiveStream`` never yields a
notification and ``NullChainProvider`` never has any real transaction
history, so a test-mode run only proves the manager starts, idles, and
stops cleanly, not that live ingestion works.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from argus.ingestion.commitment import CommitmentObservationDraft
from argus.ingestion.reconciliation import ChainEventDraft, RecordOutcome, WalletWatermark
from argus.parsing.generic_parser import ParsedTransaction
from argus.providers import SignatureInfo, SignatureStatusInfo, StreamNotification


class NullLiveStream:
    """Subscribes successfully but never yields a notification, and never
    disconnects on its own -- proves the manager can start, idle, and be
    stopped cleanly via its own ``stop_event``/cancellation path."""

    async def subscribe_wallet(self, wallet_address: str) -> AsyncIterator[StreamNotification]:
        await asyncio.Event().wait()
        return
        yield  # pragma: no cover - unreachable; makes this an async generator function

    async def unsubscribe_wallet(self, wallet_address: str) -> None:
        return None


class NullChainProvider:
    """No real transaction history exists in test mode -- every
    truth-path reconciliation call deterministically finds nothing new."""

    async def get_transaction(self, signature: str) -> dict[str, Any]:
        raise RuntimeError("NullChainProvider has no real transactions -- test-mode only")

    async def get_signatures_for_address(
        self,
        wallet_address: str,
        *,
        until_signature: str | None = None,
        before_signature: str | None = None,
        limit: int = 1000,
    ) -> list[SignatureInfo]:
        return []

    async def get_signature_statuses(self, signatures: list[str]) -> list[SignatureStatusInfo]:
        return []

    async def get_balance(self, wallet_address: str) -> int:
        return 0

    async def get_token_accounts(self, wallet_address: str) -> list[dict[str, Any]]:
        return []

    async def get_slot(self) -> int:
        return 0


class InMemoryEventRecorder:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str | None, str], ChainEventDraft] = {}

    async def record(self, draft: ChainEventDraft) -> RecordOutcome:
        key = (draft.transaction_signature, draft.wallet_address, draft.event_type)
        existing = self.rows.get(key)
        if existing is not None:
            return RecordOutcome(event_id=existing.event_id, is_new=False)
        self.rows[key] = draft
        return RecordOutcome(event_id=draft.event_id, is_new=True)


class InMemoryWatermarkStore:
    def __init__(self) -> None:
        self.rows: dict[str, WalletWatermark] = {}

    async def get(self, wallet_address: str) -> WalletWatermark | None:
        return self.rows.get(wallet_address)

    async def save(self, watermark: WalletWatermark) -> None:
        self.rows[watermark.wallet_address] = watermark


class InMemoryCommitmentStore:
    def __init__(self) -> None:
        self.rows: list[CommitmentObservationDraft] = []

    async def list_for_event(self, event_id: uuid.UUID) -> list[CommitmentObservationDraft]:
        return [r for r in self.rows if r.event_id == event_id]

    async def append(self, observation: CommitmentObservationDraft) -> None:
        self.rows.append(observation)


class InMemorySwapRecorder:
    def __init__(self) -> None:
        self.rows: dict[tuple[uuid.UUID, str], ParsedTransaction] = {}

    async def record(
        self,
        *,
        event_id: uuid.UUID,
        wallet_address: str,
        parsed: ParsedTransaction,
        created_at: datetime,
    ) -> bool:
        key = (event_id, parsed.parser_version)
        if key in self.rows:
            return False
        self.rows[key] = parsed
        return True
