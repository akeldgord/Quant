"""argus.convergence.independence -- MASTER_SPEC.md Phase 8 (CONVERGENCE
+ NEGATIVE EVIDENCE), section 43 (CONSERVATIVE INDEPENDENCE): turns a
group of wallets that converged on the same token into an effective
independent-actor count, reusing Phase 3's own per-wallet cluster-risk
assessment (``argus.wallets.clustering.assess_wallet_cluster_risk``)
rather than inventing new independence math.

Section 43's own example -- "three addresses likely belonging to one
actor count approximately as one source of information" -- falls out
naturally from this: if two wallets in the group have a strong pairwise
common-control link, one gets a low independence weight (near 0) while
the other keeps its own, so their combined contribution collapses toward
1 rather than 2. A known, disclosed limitation (inherited from Phase 3's
own scope limit, ``argus.wallets.clustering``'s module docstring): only
the single strongest pairwise link per wallet is used, not a transitive
clique closure, so a group of three mutually-linked wallets with no one
link dominating can undercount rather than converge to ~1.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Final

from argus.copyability.identity import known_by_cutoff
from argus.wallets.clustering import ClusterLinkEvidence, assess_wallet_cluster_risk

ALGORITHM_VERSION: Final[str] = "convergence_independence_v1"

# Section 43: "uncertain dependence contributes less than confidently
# independent actors." A wallet with zero recorded cluster-link evidence
# against the OTHER members of its own convergence group is neither
# assumed independent (weight 1, which section 43 explicitly forbids
# inferring from absence of evidence) nor assumed fully dependent (weight
# 0, which would be equally fabricated). This is a disclosed policy
# constant, mirroring ``argus.wallets.clustering.CLUSTER_UNCERTAINTY_PENALTY``'s
# own precedent for handling an "uncertain" case with a named, versioned
# constant rather than a silent default.
DEFAULT_UNKNOWN_INDEPENDENCE_WEIGHT: Final[Decimal] = Decimal("0.75")


def compute_independence_weights(
    group_wallet_ids: list[uuid.UUID],
    links_by_wallet: dict[uuid.UUID, list[ClusterLinkEvidence]],
    *,
    cutoff: datetime,
    unknown_independence_weight: Decimal = DEFAULT_UNKNOWN_INDEPENDENCE_WEIGHT,
) -> dict[uuid.UUID, Decimal]:
    """For each wallet in ``group_wallet_ids``, its contribution (0, 1]
    toward this group's effective independent-actor count.
    ``links_by_wallet`` may carry evidence against wallets outside this
    specific group (e.g. loaded once for a larger universe and reused
    across many groups) -- this function itself restricts each wallet's
    evidence to links whose OTHER endpoint is also a member of
    ``group_wallet_ids``, since a link to a wallet that did not converge
    on this token carries no information about THIS group's own
    independence.

    FSR-04: ``cutoff`` is this specific group's OWN decision time (e.g. a
    convergence episode's ``window_end``, never a single run-wide
    cutoff) -- a cluster-link estimate not yet known by ``cutoff`` (per
    M1's ``known_by_cutoff``, using the link's own ``as_of``/
    ``created_at``) is excluded exactly like any other not-yet-known
    evidence, never used just because it was loaded into the same
    run-wide ``links_by_wallet`` map."""
    group_ids_as_text = {str(w) for w in group_wallet_ids}
    weights: dict[uuid.UUID, Decimal] = {}
    for wallet_id in group_wallet_ids:
        restricted = [
            link
            for link in links_by_wallet.get(wallet_id, [])
            if link.other_wallet_id in group_ids_as_text
            and known_by_cutoff(created_at=link.created_at, effective_at=link.as_of, cutoff=cutoff)
        ]
        assessment = assess_wallet_cluster_risk(restricted)
        weights[wallet_id] = (
            assessment.independence_probability
            if assessment.independence_probability is not None
            else unknown_independence_weight
        )
    return weights


def estimated_independent_actors(
    group_wallet_ids: list[uuid.UUID], weights: dict[uuid.UUID, Decimal]
) -> Decimal:
    """The group's total effective independent-actor count -- the sum of
    each member's own independence weight."""
    return sum((weights[w] for w in group_wallet_ids), Decimal(0))
