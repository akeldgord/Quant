"""Unit tests for argus.convergence.independence (MASTER_SPEC.md Phase 8,
section 43 CONSERVATIVE INDEPENDENCE): effective independent-actor count
from Phase 3 cluster-link evidence.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from argus.convergence.independence import (
    DEFAULT_UNKNOWN_INDEPENDENCE_WEIGHT,
    compute_independence_weights,
    estimated_independent_actors,
)
from argus.wallets.clustering import ClusterLinkEvidence

_CUTOFF = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)


def _link(*, other_wallet_id: str, evidence_type: str, probability: Decimal) -> ClusterLinkEvidence:
    return ClusterLinkEvidence(
        other_wallet_id=other_wallet_id,
        evidence_type=evidence_type,
        probability=probability,
        as_of=_CUTOFF - timedelta(days=1),
        created_at=_CUTOFF - timedelta(days=1),
    )


def test_wallet_with_no_links_gets_unknown_weight_never_full_independence() -> None:
    wallet = uuid.uuid4()
    weights = compute_independence_weights([wallet], {}, cutoff=_CUTOFF)
    assert weights[wallet] == DEFAULT_UNKNOWN_INDEPENDENCE_WEIGHT
    assert weights[wallet] < Decimal(1)


def test_strong_pairwise_link_collapses_pair_toward_one_source() -> None:
    wallet_a, wallet_b = uuid.uuid4(), uuid.uuid4()
    links_by_wallet = {
        wallet_a: [
            _link(
                other_wallet_id=str(wallet_b),
                evidence_type="DIRECT_TRANSFER",
                probability=Decimal("0.95"),
            )
        ],
        wallet_b: [
            _link(
                other_wallet_id=str(wallet_a),
                evidence_type="DIRECT_TRANSFER",
                probability=Decimal("0.95"),
            )
        ],
    }
    weights = compute_independence_weights([wallet_a, wallet_b], links_by_wallet, cutoff=_CUTOFF)
    total = estimated_independent_actors([wallet_a, wallet_b], weights)
    # wallet_a's own weight is 1 - 0.95 = 0.05; wallet_b's own link is not
    # restricted (both endpoints are in-group) so it also gets 0.05.
    # Total collapses to ~0.1, far below the raw count of 2 -- "count
    # approximately as one source" only holds when one side's OWN weight
    # stays near 1 (this symmetric-link case shows the module's own
    # documented limitation: no transitive-closure asymmetry resolution).
    assert total < Decimal("2.0")
    assert weights[wallet_a] == Decimal("0.05")
    assert weights[wallet_b] == Decimal("0.05")


def test_link_to_wallet_outside_group_is_ignored() -> None:
    wallet_a, wallet_b, outsider = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    links_by_wallet = {
        wallet_a: [
            _link(
                other_wallet_id=str(outsider),
                evidence_type="DIRECT_TRANSFER",
                probability=Decimal("0.99"),
            )
        ],
    }
    weights = compute_independence_weights([wallet_a, wallet_b], links_by_wallet, cutoff=_CUTOFF)
    # outsider is not part of this group, so wallet_a's link to it must
    # not affect its independence weight within THIS group.
    assert weights[wallet_a] == DEFAULT_UNKNOWN_INDEPENDENCE_WEIGHT


def test_estimated_independent_actors_sums_weights() -> None:
    wallets = [uuid.uuid4() for _ in range(3)]
    weights = {wallets[0]: Decimal("1.0"), wallets[1]: Decimal("0.5"), wallets[2]: Decimal("0.75")}
    assert estimated_independent_actors(wallets, weights) == Decimal("2.25")


def test_custom_unknown_weight_is_honored() -> None:
    wallet = uuid.uuid4()
    weights = compute_independence_weights(
        [wallet], {}, cutoff=_CUTOFF, unknown_independence_weight=Decimal("0.4")
    )
    assert weights[wallet] == Decimal("0.4")


def test_fsr04_link_not_yet_known_by_cutoff_is_excluded() -> None:
    """FSR-04: a cluster-link estimate recorded (or effective) AFTER this
    group's own decision-time cutoff must not affect its independence
    weight, even though it was loaded into the same run-wide
    ``links_by_wallet`` map."""
    wallet_a, wallet_b = uuid.uuid4(), uuid.uuid4()
    future_link = ClusterLinkEvidence(
        other_wallet_id=str(wallet_b),
        evidence_type="DIRECT_TRANSFER",
        probability=Decimal("0.95"),
        as_of=_CUTOFF + timedelta(days=1),
        created_at=_CUTOFF + timedelta(days=1),
    )
    links_by_wallet = {wallet_a: [future_link]}
    weights = compute_independence_weights([wallet_a, wallet_b], links_by_wallet, cutoff=_CUTOFF)
    assert weights[wallet_a] == DEFAULT_UNKNOWN_INDEPENDENCE_WEIGHT
