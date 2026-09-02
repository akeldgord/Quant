"""P5-04 (SPEC_BLOCKING) remediation coverage for F5-02/F5-07: the REAL
production forward-information-grid evidence assembly
(``argus.copyability.loaders.build_forward_information_observations``),
not merely the pure display-shaping helper
(``argus.copyability.delay_curves.build_forward_information_grid``,
already covered by ``test_phase5_p5_04_forward_information_grid.py``).

This module exists because the audit's F5-02/F5-07 findings explicitly
called out that no test previously exercised this function's real
exact-elapsed-time-match discipline at all -- a regression this file's
own first run caught: ``build_forward_information_observations`` crashed
with ``ValueError`` on every long-horizon label ("5m"/"30m"/"1h"/"6h"/
"24h") because ``_HORIZON_SECONDS.get(label, _entry_delay_seconds(label))``
eagerly evaluates its default argument even when the key IS present,
raising inside ``_entry_delay_seconds`` for any label not ending in "s".
Fixed by looking the value up first and only falling back when actually
missing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from argus.copyability.delay_curves import FORWARD_INFO_HORIZON_LABELS
from argus.copyability.executable_returns import EntryFill, ReverseQuote, compute_executable_return
from argus.copyability.identity import EVIDENCE_CLASS_AUTHENTIC_PROSPECTIVE
from argus.copyability.loaders import (
    OpportunityReverseOutcome,
    WalletOpportunity,
    build_forward_information_observations,
)

SOL = "So11111111111111111111111111111111111111112"
TOKEN = "TokenMintNotUnderTestXXXXXXXXXXXXXXXXXXXXXX"
FIRST_SEEN = datetime(2025, 1, 1, tzinfo=UTC)


def _entry() -> EntryFill:
    return EntryFill(
        input_mint=SOL,
        output_mint=TOKEN,
        input_amount_raw=100_000_000,
        output_amount_raw=200_000_000,
    )


def _opportunity(outcomes: dict[str, tuple[int, int]]) -> WalletOpportunity:
    """``outcomes`` maps target_label -> (reverse_output_raw, actual_elapsed_seconds)."""
    entry = _entry()
    reverse_outcomes = {}
    for label, (output_raw, elapsed_seconds) in outcomes.items():
        reverse = ReverseQuote(
            outcome="SUCCESS",
            input_mint=TOKEN,
            output_mint=SOL,
            input_amount_raw=200_000_000,
            output_amount_raw=output_raw,
        )
        result = compute_executable_return(entry, reverse)
        reverse_outcomes[label] = OpportunityReverseOutcome(
            probe_id=uuid.uuid4(),
            target_label=label,
            raw_outcome="SUCCESS",
            result=result,
            actual_elapsed_seconds_from_first_seen=Decimal(elapsed_seconds),
        )
    return WalletOpportunity(
        shadow_intent_id=uuid.uuid4(),
        token_id=uuid.uuid4(),
        first_seen_at=FIRST_SEEN,
        entry_status="FILLED",
        shadow_position_id=uuid.uuid4(),
        entry_target_label="5s",
        entry_target_seconds=5,
        entry_fill=entry,
        entry_price_impact_pct=None,
        reverse_outcomes=reverse_outcomes,
        evidence_class=EVIDENCE_CLASS_AUTHENTIC_PROSPECTIVE,
    )


def test_all_nine_horizon_labels_present_even_when_empty() -> None:
    result = build_forward_information_observations([])
    assert set(result.keys()) == set(FORWARD_INFO_HORIZON_LABELS)
    assert all(values == [] for values in result.values())


def test_long_horizon_labels_never_raise_valueerror_f5_02_regression() -> None:
    """Regression test for the exact bug this remediation round caught:
    every long-horizon label ("5m"/"30m"/"1h"/"6h"/"24h") used to crash
    with ValueError from inside ``_entry_delay_seconds`` because
    ``dict.get(key, expensive_default())`` evaluates its default
    argument unconditionally, not only on a miss."""
    opp = _opportunity({"5m": (240_000_000, 300)})
    result = build_forward_information_observations([opp])  # must not raise
    # gross_return_fraction = reverse_output / entry_input - 1 (M2's own
    # formula) = 240_000_000 / 100_000_000 - 1.
    assert result["5m"] == [Decimal("240000000") / Decimal("100000000") - 1]


def test_exact_elapsed_match_fills_the_correct_cell() -> None:
    opp = _opportunity({"5m": (240_000_000, 300)})
    result = build_forward_information_observations([opp])
    assert len(result["5m"]) == 1
    assert result["30m"] == []


def test_5s_entry_delay_plus_5m_hold_actual_305s_never_fills_5m_cell() -> None:
    """The exact F5-02 core scenario: an entry delayed 5s that then holds
    for a 5-minute horizon actually resolves at elapsed=305s (5 + 300),
    NOT the nominal 300s -- it must NEVER be relabeled into the "5m"
    cell."""
    opp = _opportunity({"5m": (240_000_000, 305)})
    result = build_forward_information_observations([opp])
    assert result["5m"] == []


def test_short_entry_delay_labels_also_exact_match_only() -> None:
    opp = _opportunity({"5s": (205_000_000, 5)})
    result = build_forward_information_observations([opp])
    assert len(result["5s"]) == 1
    opp_near_miss = _opportunity({"5s": (205_000_000, 6)})
    result_near_miss = build_forward_information_observations([opp_near_miss])
    assert result_near_miss["5s"] == []


def test_multiple_opportunities_aggregate_into_the_same_cell() -> None:
    opp_a = _opportunity({"1h": (250_000_000, 3600)})
    opp_b = _opportunity({"1h": (260_000_000, 3600)})
    result = build_forward_information_observations([opp_a, opp_b])
    assert len(result["1h"]) == 2


def test_failed_outcome_never_contributes() -> None:
    entry = _entry()
    reverse = ReverseQuote(
        outcome="NO_ROUTE",
        input_mint=TOKEN,
        output_mint=SOL,
        input_amount_raw=200_000_000,
        output_amount_raw=None,
    )
    result_obj = compute_executable_return(entry, reverse)
    opp = WalletOpportunity(
        shadow_intent_id=uuid.uuid4(),
        token_id=uuid.uuid4(),
        first_seen_at=FIRST_SEEN,
        entry_status="FILLED",
        shadow_position_id=uuid.uuid4(),
        entry_target_label="5s",
        entry_target_seconds=5,
        entry_fill=entry,
        entry_price_impact_pct=None,
        reverse_outcomes={
            "24h": OpportunityReverseOutcome(
                probe_id=uuid.uuid4(),
                target_label="24h",
                raw_outcome="NO_ROUTE",
                result=result_obj,
                actual_elapsed_seconds_from_first_seen=Decimal(86400),
            )
        },
        evidence_class=EVIDENCE_CLASS_AUTHENTIC_PROSPECTIVE,
    )
    result = build_forward_information_observations([opp])
    assert result["24h"] == []


def test_missing_elapsed_time_never_contributes() -> None:
    entry = _entry()
    reverse = ReverseQuote(
        outcome="SUCCESS",
        input_mint=TOKEN,
        output_mint=SOL,
        input_amount_raw=200_000_000,
        output_amount_raw=240_000_000,
    )
    result_obj = compute_executable_return(entry, reverse)
    opp = WalletOpportunity(
        shadow_intent_id=uuid.uuid4(),
        token_id=uuid.uuid4(),
        first_seen_at=FIRST_SEEN,
        entry_status="FILLED",
        shadow_position_id=uuid.uuid4(),
        entry_target_label="5s",
        entry_target_seconds=5,
        entry_fill=entry,
        entry_price_impact_pct=None,
        reverse_outcomes={
            "5m": OpportunityReverseOutcome(
                probe_id=uuid.uuid4(),
                target_label="5m",
                raw_outcome="SUCCESS",
                result=result_obj,
                actual_elapsed_seconds_from_first_seen=None,
            )
        },
        evidence_class=EVIDENCE_CLASS_AUTHENTIC_PROSPECTIVE,
    )
    result = build_forward_information_observations([opp])
    assert result["5m"] == []
