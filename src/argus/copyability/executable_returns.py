"""M2 (executable outcomes/delay curves) — MASTER_SPEC.md sections 47-48,
Phase 5 (``argus-phase-5-001``).

Pure arithmetic over one entry fill (spend ``I`` of the quote mint,
acquire ``Q`` of the target mint) and one reverse-executable quote that
sold exactly ``Q`` back for ``O`` of the quote mint. Units always cancel
inside a single mint-pair ratio (``O/I``), so raw integer amounts are used
directly -- never a cross-mint currency sum (this instruction's own
explicit rule).

The six terminal failure classes mirror
``argus.domain.shadow_quote_probes.UNSELLABLE_OUTCOMES`` plus
``OUTCOME_PROVIDER_CAPACITY_MISS`` -- "unsellable is a real outcome"
(section 48): a failure is recorded honestly, never silently dropped, and
never produces a fabricated return.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

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

TERMINAL_FAILURE_CLASSES = frozenset(
    {
        OUTCOME_NO_ROUTE,
        OUTCOME_INSUFFICIENT_LIQUIDITY,
        OUTCOME_PRICE_IMPACT_EXCESSIVE,
        OUTCOME_QUOTE_FAILED,
        OUTCOME_TOKEN_RESTRICTED,
        OUTCOME_PROVIDER_CAPACITY_MISS,
    }
)

ExecutableReturnStatus = Literal["SUCCESS", "PENDING", "FAILED", "UNAVAILABLE"]


@dataclass(frozen=True)
class EntryFill:
    """The entry side: spent ``input_amount_raw`` of ``input_mint`` to
    acquire exactly ``output_amount_raw`` of ``output_mint``."""

    input_mint: str
    output_mint: str
    input_amount_raw: int
    output_amount_raw: int


@dataclass(frozen=True)
class ReverseQuote:
    """One ``REVERSE_EXECUTABLE`` probe result, valuing a reverse-sell of
    ``input_amount_raw`` of ``input_mint`` (must equal the entry's
    acquired quantity/mint) back into ``output_amount_raw`` of
    ``output_mint`` (must equal the entry's spent mint)."""

    outcome: str
    input_mint: str | None = None
    output_mint: str | None = None
    input_amount_raw: int | None = None
    output_amount_raw: int | None = None


@dataclass(frozen=True)
class AdditionalCost:
    """A separately-evidenced additional cost in the SAME quote unit as
    the entry's spent mint. ``already_included_in_output`` marks a cost
    (e.g. a fee) that the reverse quote's ``output_amount_raw`` already
    reflects -- subtracting it again would double-count (this
    instruction's own explicit rule)."""

    amount_raw: int
    quote_unit_mint: str
    already_included_in_output: bool = False


@dataclass(frozen=True)
class ExecutableReturnResult:
    status: ExecutableReturnStatus
    gross_return_fraction: Decimal | None = None
    gross_return_pct: Decimal | None = None
    net_return_fraction: Decimal | None = None
    net_return_pct: Decimal | None = None
    cost_known: bool = False
    failure_class: str | None = None
    unavailable_reason: str | None = None


def _unavailable(reason: str) -> ExecutableReturnResult:
    return ExecutableReturnResult(status="UNAVAILABLE", unavailable_reason=reason)


def compute_executable_return(
    entry: EntryFill,
    reverse: ReverseQuote,
    cost: AdditionalCost | None = None,
) -> ExecutableReturnResult:
    """Never fabricates a return: every terminal failure and every
    validation rejection returns an explicit, reasoned non-numeric
    result -- section 48's "unsellable is a real outcome" plus this
    instruction's explicit reject list (zero/nonpositive denominator,
    mismatched mint, mismatched quantity, nonfinite values)."""

    if reverse.outcome == OUTCOME_PENDING:
        return ExecutableReturnResult(
            status="PENDING", unavailable_reason="reverse-executable probe still pending"
        )
    if reverse.outcome in TERMINAL_FAILURE_CLASSES:
        return ExecutableReturnResult(
            status="FAILED",
            failure_class=reverse.outcome,
            unavailable_reason=f"terminal reverse-quote failure: {reverse.outcome}",
        )
    if reverse.outcome != OUTCOME_SUCCESS:
        return _unavailable(f"unrecognized reverse-quote outcome: {reverse.outcome!r}")

    if entry.input_amount_raw <= 0:
        return _unavailable("zero or nonpositive entry input amount (denominator)")
    if entry.output_amount_raw <= 0:
        return _unavailable("zero or nonpositive entry output amount (acquired quantity)")
    if reverse.input_mint is None or reverse.output_mint is None:
        return _unavailable("reverse quote missing mint identity")
    if reverse.input_mint != entry.output_mint or reverse.output_mint != entry.input_mint:
        return _unavailable("mismatched mint: reverse quote does not close this exact pair")
    if reverse.input_amount_raw != entry.output_amount_raw:
        return _unavailable(
            "mismatched quantity: reverse quote did not sell exactly the acquired quantity"
        )
    if reverse.output_amount_raw is None:
        return _unavailable("reverse quote missing output amount")

    entry_input = Decimal(entry.input_amount_raw)
    reverse_output = Decimal(reverse.output_amount_raw)
    if not entry_input.is_finite() or not reverse_output.is_finite():
        return _unavailable("nonfinite amount")

    gross_return_fraction = reverse_output / entry_input - 1
    gross_return_pct = gross_return_fraction * 100

    net_return_fraction: Decimal | None = None
    net_return_pct: Decimal | None = None
    cost_known = False
    if cost is not None:
        cost_known = True
        if cost.quote_unit_mint != entry.input_mint:
            return _unavailable(
                "additional cost quoted in a mismatched mint; never summed across mints"
            )
        cost_amount = Decimal(cost.amount_raw)
        if not cost_amount.is_finite():
            return _unavailable("nonfinite additional cost")
        if cost.already_included_in_output:
            # Already reflected in reverse_output -- never subtracted twice.
            net_return_fraction = gross_return_fraction
        else:
            net_return_fraction = (reverse_output - cost_amount) / entry_input - 1
        net_return_pct = net_return_fraction * 100

    return ExecutableReturnResult(
        status="SUCCESS",
        gross_return_fraction=gross_return_fraction,
        gross_return_pct=gross_return_pct,
        net_return_fraction=net_return_fraction,
        net_return_pct=net_return_pct,
        cost_known=cost_known,
    )
