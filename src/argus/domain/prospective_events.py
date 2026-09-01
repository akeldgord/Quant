"""``prospective_events`` — MASTER_SPEC.md section 44 (PROSPECTIVE SHADOW
MONITORING), Phase 4 (`argus-phase-4-001`).

One row per "sufficiently interesting" tracked-wallet trade: a real
``swaps`` row for a wallet ARGUS actively tracks (Phase 1's fast/truth
path already produced the underlying ``chain_events``/``swaps`` evidence
unmodified -- this table never re-derives or re-observes it). Every
point-in-time value used for the original signal -- the wallet's score/
tier, the token's known state, the wallet's own position-size context,
its cluster state, and any (currently unavailable) graph context -- is
frozen here at creation time and never later replaced: "No later
reconstruction may replace point-in-time values used in the original
signal" (section 44's own explicit rule). A wallet's score can move up or
down after this row is written; this row's own snapshot fields never do.

``graph_state_snapshot`` is always the explicit sentinel
``{"available": false, "reason": "Phase 7 (ALPHA ANCESTRY) not yet
implemented"}`` -- Phase 4 must never fabricate graph context that does
not exist yet (this instruction's own explicit "never fabricated" rule).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base


class ProspectiveEvent(Base):
    """One frozen, point-in-time-honest observation of a tracked wallet's
    trade, the seed for a possible :class:`~argus.domain.shadow_intents.ShadowIntent`."""

    __tablename__ = "prospective_events"
    __table_args__ = (
        UniqueConstraint("swap_id", name="uq_prospective_events_swap_id"),
        UniqueConstraint("event_id", name="uq_prospective_events_event_id"),
        CheckConstraint(
            "length(wallet_tier_snapshot) > 0",
            name="ck_prospective_events_tier_snapshot_nonempty",
        ),
        CheckConstraint(
            "length(algorithm_version) > 0", name="ck_prospective_events_algo_nonempty"
        ),
    )

    prospective_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=False, index=True
    )
    swap_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("swaps.swap_id"), nullable=False, index=True
    )
    # P4-R3 remediation: the true "one prospective event per canonical
    # wallet transaction" identity boundary -- a denormalized copy of
    # ``swaps.event_id``, unique here, so two different parser-artifact
    # rows for the SAME raw transaction can never both become prospective
    # events (the pre-existing ``swap_id`` uniqueness alone did not catch
    # this, since a reparse can produce a new ``swap_id`` for the same
    # ``event_id``).
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chain_events.event_id"), nullable=False, index=True
    )
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tokens.token_id"), nullable=True, index=True
    )

    # Distinct times, per section 44 -- never collapsed into one.
    leader_transaction_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmation_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # P4-remediation-002 R3: the exact CommitmentObservation row (a real,
    # immutable, CONFIRMED-or-FINALIZED, genuinely-succeeded observation)
    # that justified ``confirmation_time`` -- so the cached timestamp
    # above is independently checkable against its own cited evidence,
    # the same provenance-binding pattern P4-R1 established for
    # score_snapshot_id/tier_transition_id. Nullable: still pending.
    confirmation_observation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commitment_observations.observation_id"), nullable=True
    )

    # Frozen wallet score/tier at observation time -- never updated to
    # reflect a later re-score (section 44's own explicit rule).
    wallet_score_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    wallet_tier_snapshot: Mapped[str] = mapped_column(String(16), nullable=False)

    # P4-R1 remediation: "preserve selected source identities so the
    # snapshot can be checked" -- the exact score/tier-transition row (if
    # any existed by ``first_seen_at``) that was actually used to compute
    # the two fields above. Nullable: no qualifying row may have existed
    # yet at that cutoff, which is itself an honest, auditable fact.
    score_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallet_score_snapshots.score_id"), nullable=True
    )
    tier_transition_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallet_tier_history.transition_id"), nullable=True
    )

    token_state_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    position_size_context: Mapped[dict] = mapped_column(JSONB, nullable=False)
    cluster_state_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    graph_state_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)

    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
