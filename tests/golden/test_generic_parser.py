"""Golden tests for argus.parsing.generic_parser.

Each fixture in tests/golden/fixtures/*.json is a sanitized, synthetic
Solana `getTransaction`-shaped payload (see
scripts/_generate_golden_fixtures.py for how they were constructed --
this sandbox has no live network access to pull real transactions, so
these are hand-built to match the real RPC schema precisely rather than
captured live; see docs/DECISION_LOG.md). Every assertion here is an exact
expected classification/amount, per MASTER_SPEC.md section 21's "golden
fixture output changes must fail until reviewed" requirement -- a parser
change that alters any of these outputs will fail this suite until a human
deliberately updates the expectation.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from argus.parsing.generic_parser import PARSER_VERSION, parse_transaction

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
WALLET = "GoLDeN1WaLLeTFixTuReAddreSSNoTReaL11111111"
WSOL = "SOL"  # canonical asset id used by the parser, not a mint address
TOKEN_A_MINT = "TokenAFixtureMintAddressNotReal1111111111"
TOKEN_B_MINT = "TokenBFixtureMintAddressNotReal1111111111"
TOKEN_C_MINT = "TokenCFixtureMintAddressNotReal1111111111"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def _load(name: str) -> dict:
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text())


def _parse(name: str):
    raw = _load(name)
    return parse_transaction(raw, wallet_address=WALLET, slot=raw["slot"], block_time=None)


def test_sol_to_token_is_swap_simple() -> None:
    result = _parse("sol_to_token")
    assert result.classification == "SWAP_SIMPLE"
    assert result.confidence == Decimal("1.000")
    assert result.input_mint == WSOL
    assert result.input_amount_raw == 1_000_000_000
    assert result.input_amount_ui == Decimal("1.000000000")
    assert result.output_mint == TOKEN_A_MINT
    assert result.output_amount_raw == 500_000_000
    assert result.output_amount_ui == Decimal("500.000000")
    assert result.network_fee_raw == 5000
    assert result.parser_version == PARSER_VERSION
    assert result.is_copy_eligible is True


def test_token_to_sol_is_swap_simple() -> None:
    result = _parse("token_to_sol")
    assert result.classification == "SWAP_SIMPLE"
    assert result.input_mint == TOKEN_A_MINT
    assert result.input_amount_raw == 500_000_000
    assert result.output_mint == WSOL
    assert result.output_amount_raw == 1_000_000_000
    assert result.is_copy_eligible is True


def test_token_to_usdc_is_swap_simple() -> None:
    result = _parse("token_to_usdc")
    assert result.classification == "SWAP_SIMPLE"
    assert result.input_mint == TOKEN_B_MINT
    assert result.input_amount_raw == 1_000_000_000
    assert result.output_mint == USDC_MINT
    assert result.output_amount_raw == 250_000_000
    assert result.is_copy_eligible is True


def test_multi_hop_swap_is_swap_complex() -> None:
    result = _parse("multi_hop_swap")
    assert result.classification == "SWAP_COMPLEX"
    assert result.confidence == Decimal("0.700")
    # Largest-magnitude outflow/inflow reported as the primary leg.
    assert result.input_mint == WSOL
    assert result.input_amount_raw == 500_000_000
    assert result.output_mint == TOKEN_C_MINT
    assert result.output_amount_raw == 750_000_000
    assert result.is_copy_eligible is True


def test_simple_transfer_is_transfer_in() -> None:
    result = _parse("simple_transfer")
    assert result.classification == "TRANSFER_IN"
    assert result.confidence == Decimal("1.000")
    assert result.output_mint == WSOL
    assert result.output_amount_raw == 2_000_000_000
    assert result.input_mint is None
    assert result.network_fee_raw == 0  # wallet was not the fee payer
    assert result.is_copy_eligible is False  # not a trade -- must never drive a copy signal


def test_partial_sell_is_swap_simple_with_partial_amount() -> None:
    result = _parse("partial_sell")
    assert result.classification == "SWAP_SIMPLE"
    assert result.input_mint == TOKEN_A_MINT
    assert result.input_amount_raw == 300_000_000  # sold only part of the 1000 held
    assert result.output_mint == WSOL


def test_multiple_token_accounts_is_lp_action() -> None:
    result = _parse("multiple_token_accounts_lp_add")
    assert result.classification == "LP_ACTION"
    assert result.confidence == Decimal("0.600")
    assert result.is_copy_eligible is False  # LP actions are never copy-trade signals


def test_ambiguous_fee_payer_only_is_unknown() -> None:
    result = _parse("ambiguous_fee_payer_only")
    assert result.classification == "UNKNOWN"
    assert result.confidence == Decimal("0.000")
    assert result.is_copy_eligible is False


def test_failed_transaction_is_unknown() -> None:
    result = _parse("failed_transaction")
    assert result.classification == "UNKNOWN"
    assert result.confidence == Decimal("0.000")
    assert "failed on-chain" in result.reason
    assert result.is_copy_eligible is False


def test_transfer_out_is_transfer_out() -> None:
    result = _parse("transfer_out")
    assert result.classification == "TRANSFER_OUT"
    assert result.input_mint == WSOL
    assert result.input_amount_raw == 1_000_000_000
    assert result.is_copy_eligible is False


def test_token_create_is_token_create_not_a_swap() -> None:
    """Regression test for a real bug caught while building this fixture
    set: the original TOKEN_CREATE heuristic matched on "a brand-new mint
    appears in positives", which also matches an ordinary first-time-buy
    swap (buying a token you've never held before also makes it a "new"
    account). The fixed heuristic requires the new account's balance delta
    to be exactly zero (nothing actually received) -- see sol_to_token
    above for the case this must NOT match."""
    result = _parse("token_create")
    assert result.classification == "TOKEN_CREATE"
    assert result.confidence == Decimal("0.600")
    assert result.is_copy_eligible is False


@pytest.mark.parametrize(
    "name",
    [
        "sol_to_token",
        "token_to_sol",
        "token_to_usdc",
        "multi_hop_swap",
        "simple_transfer",
        "partial_sell",
        "multiple_token_accounts_lp_add",
        "ambiguous_fee_payer_only",
        "failed_transaction",
        "transfer_out",
        "token_create",
    ],
)
def test_all_fixtures_parse_without_raising(name: str) -> None:
    _parse(name)


def test_all_seven_classifications_are_exercised_somewhere() -> None:
    names = [
        "sol_to_token",
        "token_to_sol",
        "token_to_usdc",
        "multi_hop_swap",
        "simple_transfer",
        "partial_sell",
        "multiple_token_accounts_lp_add",
        "ambiguous_fee_payer_only",
        "failed_transaction",
        "transfer_out",
        "token_create",
    ]
    seen = {_parse(n).classification for n in names}
    assert seen == {
        "SWAP_SIMPLE",
        "SWAP_COMPLEX",
        "TRANSFER_IN",
        "TRANSFER_OUT",
        "TOKEN_CREATE",
        "LP_ACTION",
        "UNKNOWN",
    }
