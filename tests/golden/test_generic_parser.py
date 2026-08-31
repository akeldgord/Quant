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

from argus.parsing.generic_parser import PARSER_VERSION, compute_asset_deltas, parse_transaction

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
    # Phase 1 remediation round 5, finding #4: SWAP_COMPLEX is real,
    # useful research evidence, but balance deltas alone cannot prove
    # which leg of a multi-hop route is the "real" trade -- never
    # copy-eligible in v1 absent a separate deterministic proof rule.
    assert result.is_copy_eligible is False


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


# --- Phase 1 remediation round 5, finding #1: compute_asset_deltas -------


def test_compute_asset_deltas_matches_primary_legs_for_a_simple_swap() -> None:
    raw = _load("sol_to_token")
    deltas = compute_asset_deltas(raw, WALLET)
    assets = {d.asset: d for d in deltas}
    assert set(assets) == {WSOL, TOKEN_A_MINT}
    assert assets[WSOL].amount_raw == -1_000_000_000
    assert assets[WSOL].decimals == 9
    assert assets[TOKEN_A_MINT].amount_raw == 500_000_000
    assert assets[TOKEN_A_MINT].decimals == 6


def test_compute_asset_deltas_captures_the_full_ambiguous_multi_asset_set() -> None:
    """Unlike ParsedTransaction (which only reports a single primary
    in/out leg), compute_asset_deltas exposes every asset that actually
    moved -- exactly what an independent reviewer's typed expectation
    needs to assert against for a case the classifier itself calls
    UNKNOWN."""
    raw = _load("ambiguous_multi_asset_dual_inflow")
    deltas = compute_asset_deltas(raw, WALLET)
    assets = {d.asset: d.amount_raw for d in deltas}
    assert assets == {WSOL: 500_000_000, TOKEN_A_MINT: 100_000_000}


def test_compute_asset_deltas_empty_for_failed_transaction() -> None:
    raw = _load("failed_transaction")
    assert compute_asset_deltas(raw, WALLET) == ()


def test_compute_asset_deltas_is_deterministically_ordered() -> None:
    raw = _load("ambiguous_multi_asset_dual_inflow")
    deltas = compute_asset_deltas(raw, WALLET)
    assert [d.asset for d in deltas] == sorted(d.asset for d in deltas)


# --- Phase 1 remediation round 5, finding #4: fail-closed v1 eligibility ---


def test_ambiguous_multi_asset_dual_inflow_is_unknown_and_ineligible() -> None:
    """A native-SOL rent refund alongside an unrelated token release, both
    received with nothing given up, is genuinely ambiguous -- the same
    structural shape as this project's real DCA-order-close fixture. Must
    be UNKNOWN, never a confident TRANSFER_IN that silently picks the
    larger leg."""
    result = _parse("ambiguous_multi_asset_dual_inflow")
    assert result.classification == "UNKNOWN"
    assert result.confidence == Decimal("0.000")
    assert "ambiguous multi-asset inflow" in result.reason
    assert result.is_copy_eligible is False


def test_nft_purchase_decimals_zero_swap_simple_but_ineligible() -> None:
    """A one-for-one balance-delta shape looks identical for "bought a
    fungible token" and "bought a single NFT" (decimals == 0) -- the
    classification is still the honest SWAP_SIMPLE research evidence, but
    it must never be automatically copy-eligible."""
    result = _parse("nft_purchase_decimals_zero")
    assert result.classification == "SWAP_SIMPLE"
    assert result.confidence == Decimal("1.000")
    assert result.output_decimals == 0
    assert result.output_amount_raw == 1
    assert result.is_copy_eligible is False


def test_no_ambiguous_or_ineligible_classification_ever_reports_eligible() -> None:
    """Demonstrates the fail-closed invariant across every fixture that
    is NOT a clean fungible SWAP_SIMPLE: no ambiguous, LP, multi-hop, NFT,
    failed, or plain-transfer event can ever emit an eligible signal."""
    never_eligible = [
        "multi_hop_swap",  # SWAP_COMPLEX
        "simple_transfer",  # TRANSFER_IN
        "multiple_token_accounts_lp_add",  # LP_ACTION
        "ambiguous_fee_payer_only",  # UNKNOWN (no wallet-relevant delta)
        "ambiguous_multi_asset_dual_inflow",  # UNKNOWN (genuine multi-asset ambiguity)
        "failed_transaction",  # UNKNOWN (meta.err)
        "transfer_out",  # TRANSFER_OUT
        "token_create",  # TOKEN_CREATE
        "nft_purchase_decimals_zero",  # SWAP_SIMPLE but decimals == 0
    ]
    for name in never_eligible:
        result = _parse(name)
        assert result.is_copy_eligible is False, f"{name} must never be copy-eligible"


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
        "ambiguous_multi_asset_dual_inflow",
        "nft_purchase_decimals_zero",
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
