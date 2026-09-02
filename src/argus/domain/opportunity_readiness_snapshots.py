"""``opportunity_readiness_snapshots`` — MASTER_SPEC.md section 53
(TRADE READINESS SCORE v1), Phase 5 (``argus-phase-5-001``), mechanic M6.

One immutable, reproducible per-opportunity (per
:class:`~argus.domain.prospective_events.ProspectiveEvent`) readiness
snapshot: the six master hard gates (evaluated strictly before any score),
and, only when every gate PASSes, an ``actionable_score``. A labeled
research ``diagnostic_score`` may still be computed and displayed with
neutral-50 priors for unavailable components even when ineligible, but it
is never an order or permission (section 53's own explicit "not proven
statistical model" caution) -- real live authorization is unconditionally
false in this phase regardless of either score (P5-14).

Same append-only, stable-identity, never-overwritten convention as
``wallet_copyability_snapshots`` (see that module's docstring, F5-05
remediation) -- ``prospective_event_id`` + ``as_of`` + ``algorithm_version``
+ ``evidence_manifest_digest`` + ``config_hash``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base
from argus.domain.identity_mixin import FullIdentityMixin, full_identity_check_constraints

GATE_PASS: Literal["PASS"] = "PASS"
GATE_FAIL: Literal["FAIL"] = "FAIL"
GATE_UNKNOWN: Literal["UNKNOWN"] = "UNKNOWN"
_GATE_STATUS_SQL = "'PASS', 'FAIL', 'UNKNOWN'"

# The six master hard gates, section 53, evaluated before any eligible
# score -- fixed key names used throughout ``argus.scoring.readiness``.
GATE_TOKEN_SAFETY = "token_safety"
GATE_CHAIN_FRESHNESS = "chain_freshness"
GATE_WALLET_ELIGIBILITY = "wallet_eligibility"
GATE_HISTORY_QUALITY = "history_quality"
GATE_QUOTE_VALIDITY = "quote_validity"
GATE_RISK_CAPS = "risk_caps"
ALL_GATE_KEYS = (
    GATE_TOKEN_SAFETY,
    GATE_CHAIN_FRESHNESS,
    GATE_WALLET_ELIGIBILITY,
    GATE_HISTORY_QUALITY,
    GATE_QUOTE_VALIDITY,
    GATE_RISK_CAPS,
)


class OpportunityReadinessSnapshot(FullIdentityMixin, Base):
    """One reproducible, versioned trade-readiness analytical snapshot for
    one prospective opportunity as-of one decision-time cutoff."""

    __tablename__ = "opportunity_readiness_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "prospective_event_id",
            "as_of",
            "algorithm_version",
            "evidence_manifest_digest",
            "config_hash",
            name="uq_opportunity_readiness_identity",
        ),
        CheckConstraint(
            "length(algorithm_version) > 0", name="ck_opportunity_readiness_algo_nonempty"
        ),
        CheckConstraint(
            "length(evidence_manifest_digest) > 0",
            name="ck_opportunity_readiness_manifest_digest_nonempty",
        ),
        CheckConstraint(
            "eligible = false OR actionable_score IS NOT NULL",
            name="ck_opportunity_readiness_eligible_has_score",
        ),
        *full_identity_check_constraints("opportunity_readiness_snapshots"),
    )

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    prospective_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prospective_events.prospective_event_id"),
        nullable=False,
        index=True,
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=False, index=True
    )

    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    contributing_source_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    excluded_source_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    evidence_manifest_digest: Mapped[str] = mapped_column(String(64), nullable=False)

    # {"token_safety": {"status": "PASS", "reason": "..."}, ...} -- all six
    # ALL_GATE_KEYS always present.
    gates: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    actionable_score: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    # Labeled research-only diagnostic -- populated even when ineligible,
    # using neutral-50 priors for unavailable components. Never an order.
    diagnostic_score: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    components: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
