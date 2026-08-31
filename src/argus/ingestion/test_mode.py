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

Phase 1 remediation round 2, finding #2: :class:`InMemoryReconciliationUnitOfWork`
is the in-memory :class:`~argus.ingestion.reconciliation.ReconciliationUnitOfWork`
-- every call yields the same long-lived in-memory repository bundle (there
is no real transaction/session to scope per-operation for a plain dict, so
"one unit of work per operation" degenerates to "one shared bundle",
which is the correct and only meaningful behavior for a fake).
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from argus.ingestion.commitment import InMemoryCommitmentObservationStore
from argus.ingestion.parse_ledger import InMemoryParseAttemptRecorder
from argus.ingestion.reconciliation import (
    ChainEventDraft,
    ReconciliationRepos,
    RecordOutcome,
    WalletWatermark,
)
from argus.parsing.generic_parser import ParsedTransaction
from argus.providers import SignatureInfo, SignatureStatusInfo, StreamNotification


class NullStreamSubscription:
    """Acknowledges instantly (this *is* the acknowledgement -- test-mode
    has nothing further to wait for) but never yields a notification and
    never disconnects on its own -- proves the manager can start, idle,
    and be stopped cleanly via its own ``stop_event``/cancellation path."""

    async def notifications(self) -> AsyncIterator[StreamNotification]:
        await asyncio.Event().wait()
        return
        yield  # pragma: no cover - unreachable; makes this an async generator function

    async def close(self) -> None:
        return None


class NullLiveStream:
    """Subscribes successfully (see :class:`NullStreamSubscription`) and
    never disconnects on its own."""

    async def open_subscription(self, wallet_address: str) -> NullStreamSubscription:
        return NullStreamSubscription()

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

    async def recent_signatures(
        self, wallet_address: str, *, limit: int
    ) -> list[tuple[uuid.UUID, str]]:
        matches = [d for d in self.rows.values() if d.wallet_address == wallet_address]
        matches.sort(key=lambda d: d.first_seen_at, reverse=True)
        return [(d.event_id, d.transaction_signature) for d in matches[:limit]]


class InMemoryWatermarkStore:
    def __init__(self) -> None:
        self.rows: dict[str, WalletWatermark] = {}

    async def get(self, wallet_address: str) -> WalletWatermark | None:
        return self.rows.get(wallet_address)

    async def save(self, watermark: WalletWatermark) -> None:
        self.rows[watermark.wallet_address] = watermark


class InMemorySwapRecorder:
    def __init__(self) -> None:
        self.rows: dict[tuple[uuid.UUID, str, str], ParsedTransaction] = {}

    async def record(
        self,
        *,
        event_id: uuid.UUID,
        wallet_address: str,
        parsed: ParsedTransaction,
        build_hash: str,
        created_at: datetime,
    ) -> bool:
        key = (event_id, parsed.parser_version, build_hash)
        if key in self.rows:
            return False
        self.rows[key] = parsed
        return True


class InMemoryReconciliationUnitOfWork:
    """Callable :class:`~argus.ingestion.reconciliation.ReconciliationUnitOfWork`
    over a fixed, shared bundle of in-memory repositories -- see module
    docstring for why this doesn't scope a fresh bundle per call the way
    the real SQL unit of work does."""

    def __init__(
        self,
        *,
        watermark_store: InMemoryWatermarkStore | None = None,
        event_recorder: InMemoryEventRecorder | None = None,
        commitment_store: InMemoryCommitmentObservationStore | None = None,
        swap_recorder: InMemorySwapRecorder | None = None,
        parse_attempt_recorder: InMemoryParseAttemptRecorder | None = None,
        recent_event_source_from_event_recorder: bool = True,
    ) -> None:
        event_recorder = event_recorder or InMemoryEventRecorder()
        self._repos = ReconciliationRepos(
            watermark_store=watermark_store or InMemoryWatermarkStore(),
            event_recorder=event_recorder,
            commitment_store=commitment_store or InMemoryCommitmentObservationStore(),
            swap_recorder=swap_recorder or InMemorySwapRecorder(),
            parse_attempt_recorder=parse_attempt_recorder or InMemoryParseAttemptRecorder(),
            recent_event_source=event_recorder if recent_event_source_from_event_recorder else None,
        )

    @property
    def repos(self) -> ReconciliationRepos:
        return self._repos

    @contextlib.asynccontextmanager
    async def __call__(self) -> AsyncIterator[ReconciliationRepos]:
        yield self._repos
