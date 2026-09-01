"""``wallet_cluster_links`` — MASTER_SPEC.md section 42 (WALLET
CLUSTERING), section 43 (CONSERVATIVE INDEPENDENCE), Phase 3
(`argus-phase-3-001`).

Only the initial Phase 3 clustering necessary for qualification and
confidence (this instruction's own explicit scope limit -- "implement
only the initial Phase 3 clustering necessary," not a full graph-
clustering system). Rather than a separate cluster-group/membership/
evidence table triple, this is a single, versioned, append-only pairwise
evidence table: one row per (wallet A, wallet B, evidence type) common-
control observation, with an estimated probability. A wallet's aggregate
``cluster_risk``/``independence_probability``
(``argus.domain.wallet_metrics_snapshots``) is computed FROM these rows at
scoring time (``argus.wallets.clustering``), not cached here -- the exact
same "derived value lives on the consuming snapshot, raw evidence lives
here" split ``wallet_positions``/``wallet_score_snapshots`` already use.

ARGUS estimates a probability of common control; it never claims
real-world identity (section 42's own explicit rule). Cluster conclusions
are temporal and versioned -- a later row for the same pair does not
overwrite an earlier one, since the evidence that justified the earlier
estimate remains real, permanent evidence of what was known then.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base

EVIDENCE_COMMON_FUNDING_SOURCE = "COMMON_FUNDING_SOURCE"
EVIDENCE_DIRECT_TRANSFER = "DIRECT_TRANSFER"
EVIDENCE_SAME_INITIAL_FUNDER = "SAME_INITIAL_FUNDER"
EVIDENCE_SYNCHRONIZED_ACTIVITY = "SYNCHRONIZED_ACTIVITY"
EVIDENCE_REPEATED_SIZING = "REPEATED_SIZING"
EVIDENCE_REPEATED_TOKEN_SEQUENCE = "REPEATED_TOKEN_SEQUENCE"
EVIDENCE_SHARED_DEPLOYER_RELATION = "SHARED_DEPLOYER_RELATION"
EVIDENCE_SHARED_CASHOUT_DESTINATION = "SHARED_CASHOUT_DESTINATION"
EVIDENCE_TEMPORAL_COOCCURRENCE = "TEMPORAL_COOCCURRENCE"

CLUSTER_EVIDENCE_TYPES: tuple[str, ...] = (
    EVIDENCE_COMMON_FUNDING_SOURCE,
    EVIDENCE_DIRECT_TRANSFER,
    EVIDENCE_SAME_INITIAL_FUNDER,
    EVIDENCE_SYNCHRONIZED_ACTIVITY,
    EVIDENCE_REPEATED_SIZING,
    EVIDENCE_REPEATED_TOKEN_SEQUENCE,
    EVIDENCE_SHARED_DEPLOYER_RELATION,
    EVIDENCE_SHARED_CASHOUT_DESTINATION,
    EVIDENCE_TEMPORAL_COOCCURRENCE,
)

_EVIDENCE_TYPE_LIST_SQL = ", ".join(f"'{e}'" for e in CLUSTER_EVIDENCE_TYPES)


class WalletClusterLink(Base):
    """One versioned, evidence-grounded common-control probability
    estimate between two wallets."""

    __tablename__ = "wallet_cluster_links"
    __table_args__ = (
        CheckConstraint(
            f"evidence_type IN ({_EVIDENCE_TYPE_LIST_SQL})",
            name="ck_wallet_cluster_links_evidence_type",
        ),
        CheckConstraint(
            "probability >= 0 AND probability <= 1", name="ck_wallet_cluster_links_probability"
        ),
        CheckConstraint(
            "length(evidence_reference) > 0", name="ck_wallet_cluster_links_evidence_ref_nonempty"
        ),
        CheckConstraint("wallet_a_id <> wallet_b_id", name="ck_wallet_cluster_links_distinct"),
    )

    link_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Always stored with wallet_a_id < wallet_b_id (as text) by the
    # writer, so a pair is never accidentally double-counted under two
    # orderings by a naive aggregate query.
    wallet_a_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=False, index=True
    )
    wallet_b_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=False, index=True
    )

    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    evidence_reference: Mapped[str] = mapped_column(Text, nullable=False)
    # ARGUS's own estimated probability of common control for this one
    # piece of evidence -- never a real-world identity claim.
    probability: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)

    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)

    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
