"""Real, database-backed :class:`argus.ingestion.parse_ledger.ParseAttemptRecorder`.

Persists to ``parse_attempts`` (append-only; never updated or deleted by
application code -- migration 0004, finding #6).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from argus.domain.chain_events import ChainEvent
from argus.domain.parse_attempts import PARSE_OUTCOME_FAILURE, ParseAttempt
from argus.ingestion.parse_ledger import ParseAttemptDraft


class SqlParseAttemptRecorder:
    """One instance per unit-of-work; callers manage the session lifetime."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, draft: ParseAttemptDraft) -> None:
        row = ParseAttempt(
            attempt_id=draft.attempt_id,
            event_id=draft.event_id,
            parser_version=draft.parser_version,
            attempted_at=draft.attempted_at,
            outcome=draft.outcome,
            error_class=draft.error_class,
            error_reason=draft.error_reason,
            input_payload_hash=draft.input_payload_hash,
            retry_disposition=draft.retry_disposition,
            build_hash=draft.build_hash,
            config_hash=draft.config_hash,
            master_spec_hash=draft.master_spec_hash,
            git_commit=draft.git_commit,
            created_at=draft.created_at,
        )
        self._session.add(row)
        await self._session.flush()

    async def events_pending_for_artifact(
        self, parser_version: str, build_hash: str, *, limit: int
    ) -> list[uuid.UUID]:
        """Every ``chain_events.event_id`` lacking a ``SUCCESS``/``UNKNOWN``
        ``parse_attempts`` row under this exact parser artifact --
        ``parser_version`` *and* ``build_hash`` together (Phase 1
        remediation round 4, finding #5: ``parser_version`` alone let a
        rebuilt parser under an unbumped version label never re-select
        events an old build had already "succeeded" on) -- never-yet-
        attempted events under this artifact, and events whose only
        attempts under this artifact were failures. A SUCCESS/UNKNOWN
        attempt recorded under a *different* build_hash never suppresses
        selection here. Ordered oldest-first (``first_seen_at``) so a
        bounded sweep makes deterministic forward progress across
        repeated runs."""
        non_failure_exists = (
            select(ParseAttempt.attempt_id)
            .where(
                ParseAttempt.event_id == ChainEvent.event_id,
                ParseAttempt.parser_version == parser_version,
                ParseAttempt.build_hash == build_hash,
                ParseAttempt.outcome != PARSE_OUTCOME_FAILURE,
            )
            .exists()
        )
        result = await self._session.execute(
            select(ChainEvent.event_id)
            .where(~non_failure_exists)
            .order_by(ChainEvent.first_seen_at)
            .limit(limit)
        )
        return list(result.scalars().all())
