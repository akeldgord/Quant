"""``wallet_copyability_snapshots`` — MASTER_SPEC.md sections 46-52, Phase 5
(``argus-phase-5-001``), mechanics M1-M5 and M7.

One immutable, reproducible per-wallet analytical snapshot: delay-response
curve, information half-life, forward-information grid, relative
position-size surprise, and the V1 copyability score/components/confidence
(section 49, ``config/signals_v1.yaml``'s ``copyability_weights`` used
byte-exactly, never retuned). Never updated in place -- a changed evidence
set or algorithm/config version is always a new row, matching
``wallet_score_snapshots``'s own append-only precedent (Phase 3).

Stable unique identity (P5-09, widened by F5-05 remediation): ``wallet_id``
+ ``as_of`` + ``algorithm_version`` + ``evidence_manifest_digest`` (a
SHA-256 hex digest over the exact sorted set of contributing source row
identities, computed by
``argus.copyability.identity.evidence_manifest_digest``) + ``config_hash``
-- a config/weights change is never silently absorbed into an old row
under otherwise-identical evidence. A rerun over byte-identical evidence at
the same cutoff and config always reuses the existing row
(``argus.copyability.persistence``); a changed evidence set, upgraded
algorithm, or changed config always produces a new one, never an
overwrite. ``computed_at``
(wall-clock write time) deliberately is NOT part of this identity -- two
runs separated by real time but over the same frozen evidence/config are
the same semantic snapshot (this instruction's own explicit requirement).

M7 (separation/lineage): ``descriptive_extras`` may include
discovery-contaminated observations for display, but every field outside
it -- components, sample counts, coverage, confidence, delay curve,
half-life, size baseline -- is computed by the selection-usable path only
(``argus.copyability.firewall``), never blended with descriptive figures.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base
from argus.domain.identity_mixin import FullIdentityMixin, full_identity_check_constraints

CONFIDENCE_UNKNOWN = "UNKNOWN"
CONFIDENCE_LOW = "LOW"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_HIGH = "HIGH"
_CONFIDENCE_SQL = "'UNKNOWN', 'LOW', 'MEDIUM', 'HIGH'"


class WalletCopyabilitySnapshot(FullIdentityMixin, Base):
    """One reproducible, versioned copyability analytical snapshot for one
    wallet as-of one point-in-time cutoff."""

    __tablename__ = "wallet_copyability_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "wallet_id",
            "as_of",
            "algorithm_version",
            "evidence_manifest_digest",
            "config_hash",
            name="uq_wallet_copyability_identity",
        ),
        CheckConstraint(
            "length(algorithm_version) > 0", name="ck_wallet_copyability_algo_nonempty"
        ),
        CheckConstraint(
            "length(evidence_manifest_digest) > 0",
            name="ck_wallet_copyability_manifest_digest_nonempty",
        ),
        CheckConstraint(
            f"confidence IN ({_CONFIDENCE_SQL})", name="ck_wallet_copyability_confidence"
        ),
        CheckConstraint(
            "sample_n >= 0 AND sample_k >= 0", name="ck_wallet_copyability_sample_nonneg"
        ),
        *full_identity_check_constraints("wallet_copyability_snapshots"),
    )

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=False, index=True
    )

    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # Sorted list of {"type": "shadow_position"|"shadow_quote_probe"|
    # "shadow_mark_outcome"|"wallet_position", "id": "<uuid>"} objects that
    # actually fed this snapshot's selection-usable computation -- the
    # exact set the digest below is derived from (M1).
    contributing_source_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # {"id": ..., "type": ..., "reason": "DISCOVERY_CONTAMINATED"|
    # "FUTURE_KNOWLEDGE"|"EVIDENCE_CLASS_NOT_AUTHENTIC_PROSPECTIVE"|...}
    excluded_source_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    evidence_manifest_digest: Mapped[str] = mapped_column(String(64), nullable=False)

    # M3: {"target_delay_seconds": {"median_return_pct": ..., "n": ...,
    #   "actual_delays_seconds": [...]}, ...} keyed by probe target label.
    delay_curve: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # M3: {"outcome": "PEAK_FOUND"|"NO_POSITIVE_SIGNAL"|"RIGHT_CENSORED"|
    #   "INSUFFICIENT_COMPARABLE_EVIDENCE", "peak_delay_label": ..., ...}
    half_life_result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # M3: {"5s": {...}, "15s": {...}, ..., "24h": {...}} -- 9 fixed keys,
    # each either a measured observation or an explicit unavailable marker.
    forward_information_grid: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # M4: {"median": ..., "mad": ..., "baseline_count": ..., "z": ...,
    #   "component": ..., "unavailable_reason": ...}
    size_surprise: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    copyability_score: Mapped[Decimal | None] = mapped_column(Numeric(20, 15), nullable=True)
    # {"prospective_delayed_follower_alpha": {"value":..,"available":..,
    #   "weight":..,"reason":..}, ...} -- all 7 frozen M5 components.
    copyability_components: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    available_weight: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False, default=0)

    sample_n: Mapped[int] = mapped_column(nullable=False, default=0)
    sample_k: Mapped[int] = mapped_column(nullable=False, default=0)
    sample_coverage: Mapped[Decimal] = mapped_column(Numeric(20, 15), nullable=False, default=0)
    sample_c: Mapped[Decimal] = mapped_column(Numeric(20, 15), nullable=False, default=0)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default=CONFIDENCE_UNKNOWN)

    # M7: discovery-contaminated / non-authentic-prospective descriptive
    # figures for display only -- never read by any selection-usable
    # component, count, or confidence above.
    descriptive_extras: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
