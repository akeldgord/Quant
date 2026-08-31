"""Durable parse-attempt ledger protocol (Phase 1 remediation round 2,
finding #9) -- see ``argus.domain.parse_attempts`` for the schema
rationale. Written against a protocol, matching every other
``argus.ingestion`` repository, so ``ReconciliationEngine`` and the
``argus ingest reparse`` sweep never depend on a real database directly.
"""

from __future__ import annotations

import dataclasses
import hashlib
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from argus.domain.parse_attempts import (
    PARSE_OUTCOME_FAILURE,
    PARSE_OUTCOME_SUCCESS,
    PARSE_OUTCOME_UNKNOWN,
    PARSE_RETRY_NOT_APPLICABLE,
    PARSE_RETRY_RETRYABLE,
)

if TYPE_CHECKING:
    from argus.config import ArgusConfig

_CLASSIFICATION_UNKNOWN = "UNKNOWN"


@dataclasses.dataclass(frozen=True, slots=True)
class ParseAttemptIdentity:
    """The canonical build/config/spec/git identities MASTER_SPEC.md's
    CORE-004 requires every meaningful decision to record (Phase 1
    remediation round 3, finding #5) -- captured once per process (or
    once per reparse sweep run) and stamped onto every
    :class:`ParseAttemptDraft` recorded under it, so a durable parse
    attempt can always be reproduced against the exact code and
    configuration that produced it, not just the human-assigned
    ``parser_version`` label."""

    build_hash: str
    config_hash: str
    master_spec_hash: str
    git_commit: str


def capture_parse_identity(
    config: ArgusConfig, *, allow_unverified_git: bool = False
) -> ParseAttemptIdentity:
    """Real production wiring's single source of truth for
    :class:`ParseAttemptIdentity` -- every value is a genuine, non-empty
    capture, never a placeholder: the parser module's own content hash,
    this process's effective config hash, MASTER_SPEC.md's own hash, and
    a validated exact git commit.

    Phase 1 remediation round 4, finding #7: ``allow_unverified_git``
    defaults to ``False``, meaning the git identity is resolved via
    :func:`argus.config.resolve_production_git_commit`, which *fails
    closed* (raises ``GitIdentityUnavailableError``) on a dirty checkout,
    a missing git checkout with no build-time override, or an invalid
    override -- production ingestion/reparse must never silently record
    an unverifiable git identity as if it were real. Pass
    ``allow_unverified_git=True`` only from an explicit non-production
    caller (``--test-mode``) where the best-effort
    ``GIT_COMMIT_UNAVAILABLE`` sentinel is an acceptable, honest fallback
    instead of a hard failure."""
    from argus.config import master_spec_hash, resolve_production_git_commit
    from argus.parsing.generic_parser import PARSER_BUILD_HASH

    return ParseAttemptIdentity(
        build_hash=PARSER_BUILD_HASH,
        config_hash=config.config_hash,
        master_spec_hash=master_spec_hash(),
        git_commit=resolve_production_git_commit(allow_unverified=allow_unverified_git),
    )


@dataclasses.dataclass(frozen=True, slots=True)
class ParseAttemptDraft:
    attempt_id: uuid.UUID
    event_id: uuid.UUID
    parser_version: str
    attempted_at: datetime
    outcome: str
    error_class: str | None
    error_reason: str | None
    input_payload_hash: str
    retry_disposition: str
    build_hash: str
    config_hash: str
    master_spec_hash: str
    git_commit: str
    created_at: datetime


class ParseAttemptRecorder(Protocol):
    """A real implementation backs onto ``parse_attempts``; a fake for
    tests is a plain in-memory list."""

    async def record(self, draft: ParseAttemptDraft) -> None: ...
    async def events_pending_for_artifact(
        self, parser_version: str, build_hash: str, *, limit: int
    ) -> list[uuid.UUID]:
        """Every ``event_id`` that has never had a ``SUCCESS`` or
        ``UNKNOWN`` attempt recorded under this exact parser artifact --
        ``parser_version`` *and* ``build_hash`` together (Phase 1
        remediation round 4, finding #5; previously ``parser_version``
        alone, which meant a rebuilt parser under an unbumped version
        label never selected events an old build had already
        "succeeded" on, even though round 3's own finding #5 established
        that a new build identity creates a new attempt). i.e. events
        ``argus ingest reparse`` should retry: never-yet-attempted events
        under this artifact, and events whose only attempts under this
        artifact were failures. Never includes an event that already has
        a non-failure attempt under this exact artifact (idempotent:
        re-running the sweep is safe). A SUCCESS/UNKNOWN attempt recorded
        under a *different* build_hash (even the same parser_version)
        never suppresses selection here -- it is evidence for a different
        artifact, not this one."""
        ...


def payload_hash(raw_payload: dict[str, object]) -> str:
    """Shared with ``argus.ingestion.reconciliation._payload_hash`` in
    spirit (same canonical-JSON SHA-256 scheme) -- kept as a separate,
    trivially-reusable function here so the parse ledger never needs to
    import reconciliation just for this."""
    import json

    canonical = json.dumps(raw_payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def outcome_for(*, classification: str | None, exc: BaseException | None) -> tuple[str, str]:
    """Maps a parse attempt's real result to ``(outcome, retry_disposition)``."""
    if exc is not None:
        return PARSE_OUTCOME_FAILURE, PARSE_RETRY_RETRYABLE
    if classification == _CLASSIFICATION_UNKNOWN:
        return PARSE_OUTCOME_UNKNOWN, PARSE_RETRY_NOT_APPLICABLE
    return PARSE_OUTCOME_SUCCESS, PARSE_RETRY_NOT_APPLICABLE


class InMemoryParseAttemptRecorder:
    """Reference in-memory :class:`ParseAttemptRecorder` for
    ``argus.ingestion.test_mode`` and the unit-test suite."""

    def __init__(self) -> None:
        self.attempts: list[ParseAttemptDraft] = []

    async def record(self, draft: ParseAttemptDraft) -> None:
        self.attempts.append(draft)

    async def events_pending_for_artifact(
        self, parser_version: str, build_hash: str, *, limit: int
    ) -> list[uuid.UUID]:
        succeeded_or_unknown = {
            a.event_id
            for a in self.attempts
            if a.parser_version == parser_version
            and a.build_hash == build_hash
            and a.outcome != PARSE_OUTCOME_FAILURE
        }
        pending: list[uuid.UUID] = []
        seen: set[uuid.UUID] = set()
        for attempt in self.attempts:
            if attempt.event_id in succeeded_or_unknown or attempt.event_id in seen:
                continue
            seen.add(attempt.event_id)
            pending.append(attempt.event_id)
            if len(pending) >= limit:
                break
        return pending
