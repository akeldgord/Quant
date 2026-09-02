"""P5-02 (SPEC_BLOCKING): executable arithmetic/failures/matching --
MASTER_SPEC.md sections 47-48, mechanic M2 (``argus.copyability.
executable_returns``), orchestrator instruction ``argus-phase-5-001``.

Every frozen numeric/edge case in the sealed acceptance contract's P5-02
row is mapped to one test function here.
"""

from __future__ import annotations

from decimal import Decimal

from argus.copyability.executable_returns import (
    AdditionalCost,
    EntryFill,
    ReverseQuote,
    compute_executable_return,
)
from argus.domain.shadow_quote_probes import (
    OUTCOME_INSUFFICIENT_LIQUIDITY,
    OUTCOME_NO_ROUTE,
    OUTCOME_PENDING,
    OUTCOME_PRICE_IMPACT_EXCESSIVE,
    OUTCOME_PROVIDER_CAPACITY_MISS,
    OUTCOME_QUOTE_FAILED,
    OUTCOME_SUCCESS,
    OUTCOME_TOKEN_RESTRICTED,
)

QUOTE = "So11111111111111111111111111111111111111112"
TOKEN = "TokenMintAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


def _entry(i: int = 100, q: int = 200) -> EntryFill:
    return EntryFill(input_mint=QUOTE, output_mint=TOKEN, input_amount_raw=i, output_amount_raw=q)


def test_gross_return_20_percent_for_i100_q200_o120() -> None:
    entry = _entry(100, 200)
    reverse = ReverseQuote(OUTCOME_SUCCESS, TOKEN, QUOTE, 200, 120)
    result = compute_executable_return(entry, reverse)
    assert result.status == "SUCCESS"
    assert result.gross_return_fraction == Decimal("0.2")
    assert result.gross_return_pct == Decimal("20.0")


def test_net_return_15_percent_with_extra_cost_5() -> None:
    entry = _entry(100, 200)
    reverse = ReverseQuote(OUTCOME_SUCCESS, TOKEN, QUOTE, 200, 120)
    result = compute_executable_return(entry, reverse, AdditionalCost(5, QUOTE))
    assert result.cost_known is True
    assert result.net_return_fraction == Decimal("0.15")
    assert result.net_return_pct == Decimal("15.0")


def test_absent_cost_flags_cost_unknown() -> None:
    entry = _entry(100, 200)
    reverse = ReverseQuote(OUTCOME_SUCCESS, TOKEN, QUOTE, 200, 120)
    result = compute_executable_return(entry, reverse)
    assert result.cost_known is False
    assert result.net_return_fraction is None
    assert result.gross_return_fraction == Decimal("0.2")


def test_fee_already_in_output_not_double_subtracted() -> None:
    entry = _entry(100, 200)
    reverse = ReverseQuote(OUTCOME_SUCCESS, TOKEN, QUOTE, 200, 120)
    result = compute_executable_return(
        entry, reverse, AdditionalCost(5, QUOTE, already_included_in_output=True)
    )
    # net == gross: the cost is already reflected in reverse_output.
    assert result.net_return_fraction == result.gross_return_fraction == Decimal("0.2")


def test_zero_denominator_is_unavailable() -> None:
    entry = EntryFill(QUOTE, TOKEN, 0, 200)
    reverse = ReverseQuote(OUTCOME_SUCCESS, TOKEN, QUOTE, 200, 120)
    result = compute_executable_return(entry, reverse)
    assert result.status == "UNAVAILABLE"
    assert result.gross_return_fraction is None
    assert "denominator" in result.unavailable_reason


def test_negative_denominator_is_unavailable() -> None:
    entry = EntryFill(QUOTE, TOKEN, -50, 200)
    reverse = ReverseQuote(OUTCOME_SUCCESS, TOKEN, QUOTE, 200, 120)
    result = compute_executable_return(entry, reverse)
    assert result.status == "UNAVAILABLE"


def test_wrong_mint_is_unavailable() -> None:
    entry = _entry(100, 200)
    reverse = ReverseQuote(OUTCOME_SUCCESS, "WrongMint", QUOTE, 200, 120)
    result = compute_executable_return(entry, reverse)
    assert result.status == "UNAVAILABLE"
    assert "mint" in result.unavailable_reason


def test_reverse_quantity_201_not_200_is_unavailable() -> None:
    entry = _entry(100, 200)
    reverse = ReverseQuote(OUTCOME_SUCCESS, TOKEN, QUOTE, 201, 120)
    result = compute_executable_return(entry, reverse)
    assert result.status == "UNAVAILABLE"
    assert "quantity" in result.unavailable_reason


def test_nonfinite_additional_cost_is_unavailable() -> None:
    """Raw entry/reverse amounts are always-finite ints by construction;
    the one place a non-finite Decimal can genuinely reach this function
    is a caller-supplied additional cost -- proven directly here."""
    entry = _entry(100, 200)
    reverse = ReverseQuote(OUTCOME_SUCCESS, TOKEN, QUOTE, 200, 120)
    cost = AdditionalCost(amount_raw=float("nan"), quote_unit_mint=QUOTE)  # type: ignore[arg-type]
    result = compute_executable_return(entry, reverse, cost)
    assert result.status == "UNAVAILABLE"
    assert "nonfinite" in result.unavailable_reason


def test_all_six_terminal_failure_classes_never_fabricate_a_return() -> None:
    entry = _entry(100, 200)
    for outcome in (
        OUTCOME_NO_ROUTE,
        OUTCOME_INSUFFICIENT_LIQUIDITY,
        OUTCOME_PRICE_IMPACT_EXCESSIVE,
        OUTCOME_QUOTE_FAILED,
        OUTCOME_TOKEN_RESTRICTED,
        OUTCOME_PROVIDER_CAPACITY_MISS,
    ):
        reverse = ReverseQuote(outcome)
        result = compute_executable_return(entry, reverse)
        assert result.status == "FAILED", outcome
        assert result.failure_class == outcome
        assert result.gross_return_fraction is None
        assert result.net_return_fraction is None


def test_pending_reverse_quote_never_fabricates_a_return() -> None:
    entry = _entry(100, 200)
    reverse = ReverseQuote(OUTCOME_PENDING)
    result = compute_executable_return(entry, reverse)
    assert result.status == "PENDING"
    assert result.gross_return_fraction is None


def test_mark_plus_500_percent_with_no_route_has_no_positive_executable_return() -> None:
    """A +500% mark move with a NO_ROUTE reverse quote must never be read
    as a +500% executable outcome (section 48)."""
    entry = _entry(100, 200)
    reverse = ReverseQuote(OUTCOME_NO_ROUTE)
    result = compute_executable_return(entry, reverse)
    assert result.status == "FAILED"
    assert result.gross_return_fraction is None
    assert result.gross_return_pct is None


def test_later_delay_entry_with_different_quantity_cannot_reuse_first_reverse_quote() -> None:
    """The schema itself enforces this (one ShadowPosition per intent, at
    the first successful entry probe) -- a second, differently-sized
    hypothetical fill has no ShadowPosition and therefore no
    REVERSE_EXECUTABLE probe of its own; valuing it against the FIRST
    position's reverse quote is a quantity mismatch this function must
    reject, never silently scale."""
    first_entry = _entry(i=100, q=200)  # filled at, say, +1s
    first_reverse = ReverseQuote(OUTCOME_SUCCESS, TOKEN, QUOTE, 200, 120)
    assert compute_executable_return(first_entry, first_reverse).status == "SUCCESS"

    # A later-delay probe would have acquired a DIFFERENT quantity (e.g.
    # 250, due to price movement) -- reusing the first position's reverse
    # quote (sized for 200) against this different entry must be rejected.
    later_entry = _entry(i=100, q=250)
    result = compute_executable_return(later_entry, first_reverse)
    assert result.status == "UNAVAILABLE"
    assert "quantity" in result.unavailable_reason
