"""``parse_attempts`` -- durable, append-only ledger of every attempt to
parse a canonical ``chain_events`` row into a versioned ``swaps``
classification.

Phase 1 remediation round 2 (argus-phase-1-remediation-002), finding #9:
before this table, a parser failure only incremented an in-memory
counter inside one ``reconcile()`` call and the durable watermark still
advanced past it -- after a restart there was no durable record
explaining why an event lacks a parsed row, and no production retry/
reparse queue could find it again. Every attempt (success, ambiguous
``UNKNOWN`` classification, or failure) is appended here, keyed to the
event and parser version it was attempted against, so:

- a pending/retryable failure is queryable without re-deriving state from
  logs;
- ``argus ingest reparse`` (see ``argus.cli``) can find every event
  lacking a non-failure attempt at a given parser version and safely
  retry it from the already-immutable raw evidence, without rewriting
  this ledger's prior rows or ``chain_events``' raw payload;
- watermark advancement in ``ReconciliationEngine.reconcile()`` only
  proceeds once a row here is durably committed in the *same* transaction
  as the watermark write -- both land or neither does.

Never updated or deleted by application code (finding #6's immutability
requirement applies equally to this ledger).

Phase 1 remediation round 3 (argus-phase-1-remediation-003), finding #5:
``parser_version`` and ``input_payload_hash`` alone cannot reproduce an
attempt against the exact code/configuration that produced it -- a
human-assigned version label can be forgotten to bump, and neither field
says anything about the runtime configuration or MASTER_SPEC.md contract
version in force at the time. Adds four further identity columns
(MASTER_SPEC.md CORE-004: every meaningful decision records algorithm
version, config version/hash, and git commit): ``build_hash`` (a
reproducible content hash of the exact parsing-algorithm source that
ran), ``config_hash`` (``ArgusConfig.config_hash()``), ``master_spec_hash``
(the hash of ``MASTER_SPEC.md`` itself), and ``git_commit``
(``git rev-parse HEAD``). All four are required (never empty) at the
database layer, not merely by application-code convention.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

PARSE_OUTCOME_SUCCESS = "SUCCESS"
PARSE_OUTCOME_UNKNOWN = "UNKNOWN"
PARSE_OUTCOME_FAILURE = "FAILURE"

PARSE_RETRY_NOT_APPLICABLE = "NOT_APPLICABLE"
PARSE_RETRY_RETRYABLE = "RETRYABLE"


class ParseAttempt(Base):
    """One immutable record of one attempt to parse one ``chain_events``
    row under one parser version."""

    __tablename__ = "parse_attempts"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('SUCCESS', 'UNKNOWN', 'FAILURE')",
            name="ck_parse_attempts_outcome",
        ),
        CheckConstraint(
            "retry_disposition IN ('NOT_APPLICABLE', 'RETRYABLE')",
            name="ck_parse_attempts_retry_disposition",
        ),
        CheckConstraint("length(build_hash) > 0", name="ck_parse_attempts_build_hash_nonempty"),
        CheckConstraint("length(config_hash) > 0", name="ck_parse_attempts_config_hash_nonempty"),
        CheckConstraint(
            "length(master_spec_hash) > 0", name="ck_parse_attempts_master_spec_hash_nonempty"
        ),
        CheckConstraint("length(git_commit) > 0", name="ck_parse_attempts_git_commit_nonempty"),
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chain_events.event_id"), nullable=False, index=True
    )
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    error_class: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    input_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    retry_disposition: Mapped[str] = mapped_column(String(16), nullable=False)

    build_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    master_spec_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    git_commit: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
