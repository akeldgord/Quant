"""``wallet_score_snapshots`` — MASTER_SPEC.md section 38 (WALLET
QUALIFICATION SCORE v1), section 39 (QUALIFICATION SAMPLE REQUIREMENTS
v1), section 30 (CRITICAL ANTI-SURVIVORSHIP RULE), Phase 3
(`argus-phase-3-001`).

The one audit-critical *decision* ledger Phase 3 adds -- matching
``token_mint_validations``/``archaeology_runs``'s precedent from Phase 2,
this is the table that carries the full CORE-004 identity block
(``build_hash``/``config_hash``/``master_spec_hash``/``git_commit``), not
just ``algorithm_version``. Every qualification/descriptive score is a
real, reproducible, audit-critical decision this project must be able to
explain years later.

This table is the concrete, queryable proof of the discovery-contamination
firewall (section 3 of `argus-phase-3-001`, section 30 of MASTER_SPEC):
``excluded_discovery_token_ids`` names exactly which tokens' observations
were excluded from THIS wallet's qualification score because
``wallet_discovery_events`` shows this wallet was discovered through that
token -- never inferred from a fixture name or a hand-maintained list,
always derived from that real persisted provenance at scoring time (see
``argus.wallets.scoring``). ``descriptive_score`` may legitimately differ
from ``qualification_score`` for exactly this reason -- a huge winner that
discovered the wallet may inflate the descriptive number while being
mechanically excluded from the qualification number.

Never updated in place: a new score for the same wallet is a new row
(``score_version`` distinguishes accounting/weight versions;
``created_at``/``as_of`` distinguish point-in-time snapshots under the
same version). Downstream tier-lifecycle logic always reads the latest
row per wallet.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from argus.db.base import Base
from argus.domain.identity_mixin import FullIdentityMixin, full_identity_check_constraints


class WalletScoreSnapshot(FullIdentityMixin, Base):
    """One reproducible, versioned qualification/descriptive score for
    one wallet, with every component, penalty, and excluded discovery
    observation named explicitly."""

    __tablename__ = "wallet_score_snapshots"
    __table_args__ = (
        CheckConstraint("length(score_version) > 0", name="ck_wallet_score_version_nonempty"),
        CheckConstraint(
            "length(sample_gate_reason) > 0", name="ck_wallet_score_sample_gate_reason_nonempty"
        ),
        *full_identity_check_constraints("wallet_score_snapshots"),
    )

    score_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.wallet_id"), nullable=False, index=True
    )

    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    score_version: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    descriptive_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    qualification_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)

    # {"selection_alpha": ..., "consistency": ..., "entry_timing": ...,
    #  "forward_information": ..., "risk_adjusted_return": ...,
    #  "exit_capture": ..., "recency": ..., "data_confidence": ...} --
    # the exact 8 frozen v1 weighted components (section 38), each 0-100
    # or null if not computable, stored verbatim so the final score is
    # always independently recomputable from its own stated inputs.
    component_values: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # {"insider_penalty": ..., "cluster_uncertainty_penalty": ...,
    #  "lottery_dominance_penalty": ..., "data_quality_penalty": ...,
    #  "predation_penalty": ...} -- applied separately, never folded
    #  silently into a component value.
    penalties: Mapped[dict] = mapped_column(JSONB, nullable=False)

    confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Token UUIDs (as strings) excluded from this wallet's qualification
    # score because wallet_discovery_events shows this wallet was
    # discovered through that token -- the discovery-contamination
    # firewall's own persisted, queryable proof.
    excluded_discovery_token_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Section 39: whether the >=20 closed positions / >=10 distinct
    # tokens / non-LOW-UNKNOWN completeness gate was met, and why --
    # always populated, even when eligible=True, so a "why is this
    # wallet not A/S" question never requires re-deriving the gate.
    eligible_for_qualification: Mapped[bool] = mapped_column(Boolean, nullable=False)
    sample_gate_reason: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
