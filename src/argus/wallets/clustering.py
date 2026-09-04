"""Initial Phase 3 wallet clustering (MASTER_SPEC.md section 42 WALLET
CLUSTERING, section 43 CONSERVATIVE INDEPENDENCE; Phase 3,
`argus-phase-3-001`).

Only the initial clustering necessary for qualification confidence (this
instruction's own explicit scope limit) -- a single, versioned, pairwise
evidence table (``wallet_cluster_links``), never a full cluster-group/
membership/independence-snapshot table triple. A wallet's aggregate
``cluster_risk``/``independence_probability`` is computed HERE, from its
own pairwise links, and handed to ``argus.wallets.scoring`` as an
ordinary evidence input -- it is never cached back onto
``wallet_cluster_links`` itself (that table stays raw, versioned
evidence; this module's output is the derived value, matching the same
"raw evidence lives on its own table, derived value lives on the
consuming snapshot" split ``wallet_positions``/``wallet_score_snapshots``
already use).

ARGUS estimates a probability of common control; it never claims
real-world identity (section 42's own explicit rule), and absence of a
cluster link is NOT proof of independence (section 43's own explicit
rule) -- a wallet with zero recorded links gets ``cluster_risk=None``/
``independence_probability=None`` (genuinely unassessed), never a
fabricated "independent" value.

Section 43's own further point -- that several highly-correlated wallets
should collectively count as approximately one source of information for
LIVE portfolio convergence -- is explicitly a later-phase (portfolio
construction / Phase 4 convergence) consumer of this module's estimates,
not something Phase 3 itself implements; this module only produces the
per-wallet probability estimate.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from decimal import Decimal
from typing import Final

ALGORITHM_VERSION: Final[str] = "wallet_clustering_v1"

# section 40/38-style penalty scale: a wallet whose highest pairwise
# common-control estimate exceeds this is penalized in scoring
# (argus.wallets.scoring's own "cluster_uncertainty_penalty").
CLUSTER_RISK_PENALTY_THRESHOLD: Final[Decimal] = Decimal("0.50")
CLUSTER_UNCERTAINTY_PENALTY: Final[Decimal] = Decimal("10")


@dataclasses.dataclass(frozen=True, slots=True)
class ClusterLinkEvidence:
    """The subset of one ``wallet_cluster_links`` row this module needs.

    FSR-04: ``as_of``/``created_at`` carry the row's own M1 point-in-time
    identity through unchanged -- this module's own aggregation never
    needs them (a caller that must restrict evidence to what was known
    by some cutoff, e.g. ``argus.convergence.independence``, filters on
    them before calling :func:`assess_wallet_cluster_risk`)."""

    other_wallet_id: str
    evidence_type: str
    probability: Decimal
    as_of: datetime
    created_at: datetime


@dataclasses.dataclass(frozen=True, slots=True)
class ClusterAssessment:
    cluster_risk: Decimal | None
    independence_probability: Decimal | None
    cluster_uncertainty_penalty: Decimal
    highest_linked_wallet_id: str | None
    highest_probability: Decimal | None


def assess_wallet_cluster_risk(links: list[ClusterLinkEvidence]) -> ClusterAssessment:
    """Aggregates one wallet's own pairwise cluster-link evidence into a
    single risk/independence estimate, using only the single
    highest-probability link (a wallet linked to several distinct
    others is at least as suspect as its single strongest link -- taking
    a mean would dilute a genuinely strong single piece of evidence
    against several weak/irrelevant ones)."""
    if not links:
        return ClusterAssessment(
            cluster_risk=None,
            independence_probability=None,
            cluster_uncertainty_penalty=Decimal(0),
            highest_linked_wallet_id=None,
            highest_probability=None,
        )

    strongest = max(links, key=lambda link: link.probability)
    cluster_risk = strongest.probability * Decimal(100)
    independence_probability = Decimal(1) - strongest.probability
    penalty = (
        CLUSTER_UNCERTAINTY_PENALTY
        if strongest.probability > CLUSTER_RISK_PENALTY_THRESHOLD
        else Decimal(0)
    )
    return ClusterAssessment(
        cluster_risk=cluster_risk,
        independence_probability=independence_probability,
        cluster_uncertainty_penalty=penalty,
        highest_linked_wallet_id=strongest.other_wallet_id,
        highest_probability=strongest.probability,
    )
