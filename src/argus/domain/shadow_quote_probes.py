"""``shadow_quote_probes`` — MASTER_SPEC.md section 46 (COPYABILITY DELAY
PROBES) and section 47 (EXECUTABLE RETURNS), Phase 4 (`argus-phase-4-001`).

Every scheduled quote attempt this project ever makes -- both the entry
side (``probe_kind='ENTRY_DELAY'``, at the configured delays after ARGUS
observation: 1/5/15/30/60/300 seconds, per
``config/signals_v1.yaml``'s ``copyability_delay_probes_seconds``) and the
exit side (``probe_kind='REVERSE_EXECUTABLE'``, at 5m/30m/1h/6h/24h after
a shadow position opened, per ``executable_outcome_horizons``) -- is one
row in this single table, distinguished by ``probe_kind``/``target_label``
and by which of ``shadow_intent_id``/``shadow_position_id`` is set.

Claim semantics (``claimed_at``/``claimed_by``) make this table
restart-safe (MASTER_SPEC.md section 84: "kill shadow worker mid-job ->
restart -> no duplicate shadow trade"): a worker atomically claims one
due, unclaimed-or-stale-claimed row before calling any provider, and only
a worker holding the claim may write the terminal ``responded_at``/
``outcome`` fields -- see ``argus.shadow.quote_jobs``.

``target_due_at``, ``requested_at``, and ``responded_at`` are always kept
distinct: "Never claim a +1s quote if the call occurred +2.7s later"
(section 46's own explicit rule) -- ``scheduling_delay_seconds`` is the
real, computed gap between the two, never asserted or backdated.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

PROBE_KIND_ENTRY_DELAY = "ENTRY_DELAY"
PROBE_KIND_REVERSE_EXECUTABLE = "REVERSE_EXECUTABLE"
_PROBE_KINDS_SQL = "'ENTRY_DELAY', 'REVERSE_EXECUTABLE'"

OUTCOME_PENDING = "PENDING"
OUTCOME_SUCCESS = "SUCCESS"
OUTCOME_NO_ROUTE = "NO_ROUTE"
OUTCOME_INSUFFICIENT_LIQUIDITY = "INSUFFICIENT_LIQUIDITY"
OUTCOME_PRICE_IMPACT_EXCESSIVE = "PRICE_IMPACT_EXCESSIVE"
OUTCOME_QUOTE_FAILED = "QUOTE_FAILED"
OUTCOME_TOKEN_RESTRICTED = "TOKEN_RESTRICTED"
OUTCOME_PROVIDER_CAPACITY_MISS = "PROVIDER_CAPACITY_MISS"

# The five section-48 "unsellable is a real outcome" reasons, plus this
# project's own SUCCESS/PENDING/PROVIDER_CAPACITY_MISS -- every one is a
# real, honestly-distinct, never-dropped row (section 48's own rule).
_OUTCOMES_SQL = (
    "'PENDING', 'SUCCESS', 'NO_ROUTE', 'INSUFFICIENT_LIQUIDITY', "
    "'PRICE_IMPACT_EXCESSIVE', 'QUOTE_FAILED', 'TOKEN_RESTRICTED', "
    "'PROVIDER_CAPACITY_MISS'"
)

UNSELLABLE_OUTCOMES = frozenset(
    {
        OUTCOME_NO_ROUTE,
        OUTCOME_INSUFFICIENT_LIQUIDITY,
        OUTCOME_PRICE_IMPACT_EXCESSIVE,
        OUTCOME_QUOTE_FAILED,
        OUTCOME_TOKEN_RESTRICTED,
    }
)


class ShadowQuoteProbe(Base):
    """One scheduled (and, once processed, actually-attempted) quote
    probe -- entry-delay or reverse-executable."""

    __tablename__ = "shadow_quote_probes"
    __table_args__ = (
        CheckConstraint(f"probe_kind IN ({_PROBE_KINDS_SQL})", name="ck_shadow_probes_kind"),
        CheckConstraint(f"outcome IN ({_OUTCOMES_SQL})", name="ck_shadow_probes_outcome"),
        CheckConstraint("length(target_label) > 0", name="ck_shadow_probes_target_label_nonempty"),
        CheckConstraint(
            "(probe_kind = 'ENTRY_DELAY' AND shadow_intent_id IS NOT NULL "
            "AND shadow_position_id IS NULL) OR "
            "(probe_kind = 'REVERSE_EXECUTABLE' AND shadow_position_id IS NOT NULL "
            "AND shadow_intent_id IS NULL)",
            name="ck_shadow_probes_kind_matches_parent",
        ),
        CheckConstraint(
            "responded_at IS NULL OR requested_at IS NOT NULL",
            name="ck_shadow_probes_responded_requires_requested",
        ),
        CheckConstraint("notional_input_amount_raw > 0", name="ck_shadow_probes_notional_positive"),
        Index(
            "uq_shadow_probes_entry_intent_label",
            "shadow_intent_id",
            "target_label",
            unique=True,
            postgresql_where="probe_kind = 'ENTRY_DELAY'",
        ),
        Index(
            "uq_shadow_probes_reverse_position_label",
            "shadow_position_id",
            "target_label",
            unique=True,
            postgresql_where="probe_kind = 'REVERSE_EXECUTABLE'",
        ),
    )

    probe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    probe_kind: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    # "1s"/"5s"/"15s"/"30s"/"60s"/"300s" for ENTRY_DELAY;
    # "5m"/"30m"/"1h"/"6h"/"24h" for REVERSE_EXECUTABLE.
    target_label: Mapped[str] = mapped_column(String(16), nullable=False)
    target_seconds_from_observation: Mapped[int | None] = mapped_column(nullable=True)

    shadow_intent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shadow_intents.shadow_intent_id"), nullable=True
    )
    shadow_position_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shadow_positions.shadow_position_id"), nullable=True
    )

    input_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    output_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    notional_input_amount_raw: Mapped[int] = mapped_column(BigInteger, nullable=False)

    target_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # Restart-safety claim (section 84) -- see argus.shadow.quote_jobs.
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # P4-R5 remediation: incremented on every claim (including a stale
    # reclaim). The terminal-write step verifies the generation it read
    # during its own claim still matches before publishing, so a
    # superseded worker's late write can never overwrite a fresher
    # attempt's already-recorded result (section 84).
    claim_generation: Mapped[int] = mapped_column(nullable=False, default=0)

    # Actual timings -- always distinct from target_due_at (section 46).
    # requested_at/responded_at/scheduling_delay_seconds/latency_ms are
    # ALL still None for a genuine scheduler-level capacity drop (no real
    # provider dispatch ever happened -- P4-remediation-002 R4); terminal_at
    # is set on EVERY terminal write regardless, so "is this probe done"
    # queries never have to assume responded_at non-null is the only
    # completion proof.
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduling_delay_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    expected_output_amount_raw: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    price_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    route_present: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    fee_estimate_raw: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    outcome: Mapped[str] = mapped_column(String(24), nullable=False, default=OUTCOME_PENDING)
    raw_quote: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # P4-REC-03: a small, bounded, already-sanitized failure-evidence
    # representation -- populated only on the shared entry/reverse
    # exception seam (argus.shadow.quote_jobs._classify_provider_exception)
    # -- e.g. {"http_status_code": 429} or {"scheduler_drop_reason": "...",
    # "scheduler_priority_class": "..."}. Never the raw response body,
    # headers, or request URL. NULL when no exception was ever raised
    # (a genuine SUCCESS/response-classified outcome) or when the
    # exception carried no positively-identified evidence to preserve.
    failure_evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
