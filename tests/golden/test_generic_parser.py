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


# --- Phase 1 remediation round 6, finding #3: compute_account_level_deltas -


def _two_accounts_same_mint_payload() -> dict:
    """Two distinct wallet-owned token accounts of the *same* mint moving
    in opposite directions by the same magnitude -- by-mint aggregation
    nets them to exactly zero and the asset vanishes entirely from
    compute_asset_deltas's output, even though both accounts genuinely,
    materially changed. This is exactly the account-level evidence a
    multiple-token-account/LP-style oracle needs and by-mint aggregation
    alone cannot supply (Phase 1 remediation round 6, finding #3)."""
    return {
        "slot": 1,
        "version": "legacy",
        "transaction": {
            "signatures": ["TwoAccountsSameMintSignatureNotReal1111111111111111111111111111111"],
            "message": {
                "accountKeys": [WALLET, "OtherPubkeyNotReal11111111111111111111111"],
                "header": {
                    "numReadonlySignedAccounts": 0,
                    "numReadonlyUnsignedAccounts": 1,
                    "numRequiredSignatures": 1,
                },
                "instructions": [],
                "recentBlockhash": "BlockhashNotReal111111111111111111111111111",
            },
        },
        "meta": {
            "fee": 5000,
            "preBalances": [1_000_000_000, 0],
            "postBalances": [994_995_000, 0],
            "status": {"Ok": None},
            "err": None,
            "preTokenBalances": [
                {
                    "accountIndex": 1,
                    "mint": TOKEN_A_MINT,
                    "owner": WALLET,
                    "uiTokenAmount": {"amount": "1000", "decimals": 6},
                },
                {
                    "accountIndex": 2,
                    "mint": TOKEN_A_MINT,
                    "owner": WALLET,
                    "uiTokenAmount": {"amount": "100", "decimals": 6},
                },
            ],
            "postTokenBalances": [
                {
                    "accountIndex": 1,
                    "mint": TOKEN_A_MINT,
                    "owner": WALLET,
                    "uiTokenAmount": {"amount": "400", "decimals": 6},
                },
                {
                    "accountIndex": 2,
                    "mint": TOKEN_A_MINT,
                    "owner": WALLET,
                    "uiTokenAmount": {"amount": "700", "decimals": 6},
                },
            ],
        },
    }


def test_by_mint_aggregation_erases_two_same_mint_accounts_netting_to_zero() -> None:
    """Establishes the defect account_deltas exists to fix: two accounts
    of the same mint moving oppositely by equal magnitude (-600 and +600)
    net to a zero by-mint delta and vanish from compute_asset_deltas
    entirely -- a wallet-level view alone cannot tell this transaction
    apart from one where nothing happened to that mint at all."""
    raw = _two_accounts_same_mint_payload()
    deltas = compute_asset_deltas(raw, WALLET)
    assert TOKEN_A_MINT not in {d.asset for d in deltas}


def test_compute_account_level_deltas_preserves_both_same_mint_accounts() -> None:
    """The account-level oracle must not make the same mistake: both
    accounts' genuine, materially-opposite changes must appear as
    separate rows, never summed away."""
    from argus.parsing.generic_parser import compute_account_level_deltas

    raw = _two_accounts_same_mint_payload()
    rows = compute_account_level_deltas(raw, WALLET)

    token_rows = [r for r in rows if r.mint == TOKEN_A_MINT]
    assert len(token_rows) == 2
    by_index = {r.account_index: r for r in token_rows}
    assert by_index[1].net_raw_delta == -600
    assert by_index[1].pre_raw_amount == 1000
    assert by_index[1].post_raw_amount == 400
    assert by_index[1].owner == WALLET
    assert by_index[2].net_raw_delta == 600
    assert by_index[2].pre_raw_amount == 100
    assert by_index[2].post_raw_amount == 700
    # Both accounts are wallet-owned but distinct -- their identifiers
    # must differ even though their mint is identical.
    assert by_index[1].account_identifier != by_index[2].account_identifier


def test_compute_account_level_deltas_empty_for_failed_transaction() -> None:
    from argus.parsing.generic_parser import compute_account_level_deltas

    raw = _load("failed_transaction")
    assert compute_account_level_deltas(raw, WALLET) == ()


def test_compute_account_level_deltas_is_deterministically_ordered() -> None:
    from argus.parsing.generic_parser import compute_account_level_deltas

    raw = _two_accounts_same_mint_payload()
    rows = compute_account_level_deltas(raw, WALLET)
    assert [(r.account_index, r.mint) for r in rows] == sorted(
        (r.account_index, r.mint) for r in rows
    )


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
        "one_for_one_unsupported_program",  # SWAP_SIMPLE but no positive swap-venue evidence
        "one_for_one_no_instruction_evidence",  # SWAP_SIMPLE but no instructions at all
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
        "one_for_one_unsupported_program",
        "one_for_one_no_instruction_evidence",
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


# ---------------------------------------------------------------------
# Phase 1.5 remediation round 1 -- positive semantic proof gate for
# automatic copy eligibility. A one-negative/one-positive balance shape
# is no longer sufficient by itself: SWAP_SIMPLE additionally requires
# positive instruction-level evidence that the transaction actually
# routed through a program independently verified to be a real trade
# venue (argus.parsing.generic_parser._SUPPORTED_SWAP_PROGRAM_IDS).
# ---------------------------------------------------------------------

PHASE_1_5_EVIDENCE_DIR = (
    Path(__file__).resolve().parents[2] / "orchestration" / "phase_1_5" / "evidence" / "raw"
)


def _load_phase_1_5_evidence(filename: str) -> dict:
    data = json.loads((PHASE_1_5_EVIDENCE_DIR / filename).read_text())
    return data[0] if isinstance(data, list) else data.get("result", data)


def test_authentic_solend_withdrawal_is_not_copy_eligible() -> None:
    """T5 / the exact SPEC_BLOCKING false positive named by
    argus-phase-1-5-remediation-001: a real Solend `Withdraw Obligation
    Collateral and Redeem Reserve Collateral` transaction has a clean
    one-negative/one-positive balance shape (so the balance-delta
    classifier correctly still calls it SWAP_SIMPLE-shaped) but its only
    instruction invokes the real Solend program
    (So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo), which is not a
    supported trade venue -- it must never be copy eligible and must
    expose no swap semantic match at all."""
    raw = _load_phase_1_5_evidence("wallet_05_solend_withdraw_all.json")
    result = parse_transaction(
        raw,
        wallet_address="JAMESC37CTVoFEt7TAEcqBjdjAfAWZiPR1YdWotAFjeQ",
        slot=raw["slot"],
        block_time=None,
    )
    assert result.classification == "SWAP_SIMPLE"
    assert result.is_copy_eligible is False
    assert result.matched_swap_program_id is None
    assert result.matched_semantic_label is None
    assert result.matched_discriminator_hex is None


def test_authentic_xstep_stake_is_not_copy_eligible() -> None:
    """T5 / the second SPEC_BLOCKING false positive named by
    argus-phase-1-5-remediation-001: a real xStep `Stake` transaction has
    the same clean one-for-one balance shape but is a staking deposit,
    not a swap -- must never be copy eligible and must expose no swap
    semantic match at all."""
    raw = _load_phase_1_5_evidence("suppl_09_xstep_full_stake_ix.json")
    result = parse_transaction(
        raw,
        wallet_address="qUeL7JzC52V1DvvPkqnMd74QjThWtSJY5G1PkKv1ur7",
        slot=raw["slot"],
        block_time=None,
    )
    assert result.classification == "SWAP_SIMPLE"
    assert result.is_copy_eligible is False
    assert result.matched_swap_program_id is None
    assert result.matched_semantic_label is None
    assert result.matched_discriminator_hex is None


def test_one_for_one_unsupported_program_is_not_copy_eligible() -> None:
    """A synthetic one-negative/one-positive transaction whose only
    instruction invokes a program absent from the supported-swap-venue
    registry must never be copy eligible -- proving the gate is a
    positive allowlist, not a Solend/xStep-specific denylist (required
    test #3: an unknown/unsupported program, not just the two named
    fixtures)."""
    result = _parse("one_for_one_unsupported_program")
    assert result.classification == "SWAP_SIMPLE"
    assert result.is_copy_eligible is False
    assert result.matched_swap_program_id is None


@pytest.mark.parametrize(
    ("fixture_name", "expected_program", "expected_label", "expected_discriminator_hex"),
    [
        (
            "sol_to_token",
            "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
            "shared_accounts_route",
            "c1209b3341d69c81",
        ),
        (
            "token_to_sol",
            "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
            "swap_base_in",
            "09",
        ),
        (
            "token_to_usdc",
            "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
            "shared_accounts_route",
            "c1209b3341d69c81",
        ),
        (
            "partial_sell",
            "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
            "swap_base_in",
            "09",
        ),
    ],
)
def test_genuine_swap_fixtures_remain_eligible_with_positive_evidence(
    fixture_name: str,
    expected_program: str,
    expected_label: str,
    expected_discriminator_hex: str,
) -> None:
    """Known genuine swap/trade fixtures remain copy eligible only
    because their canonical raw evidence satisfies the positive semantic
    gate -- not merely because their balance shape looks like a swap
    (required test #4), and now (Phase 1.5 remediation round 2) because
    that same instruction's own decoded data carries the exact registered
    discriminator, not merely an allowlisted program ID."""
    result = _parse(fixture_name)
    assert result.classification == "SWAP_SIMPLE"
    assert result.matched_swap_program_id == expected_program
    assert result.matched_semantic_label == expected_label
    assert result.matched_discriminator_hex == expected_discriminator_hex
    assert result.is_copy_eligible is True


def test_reparse_of_identical_canonical_input_is_deterministic() -> None:
    """Reparsing the exact same raw evidence under the same parser
    version twice must produce identical output, including the new
    matched_swap_program_id/matched_semantic_label/
    matched_discriminator_hex/is_copy_eligible fields -- no hidden
    nondeterminism (e.g. set/dict iteration order) in the positive-
    evidence lookup (required test #6; T10)."""
    raw = _load("sol_to_token")
    first = parse_transaction(raw, wallet_address=WALLET, slot=raw["slot"], block_time=None)
    second = parse_transaction(raw, wallet_address=WALLET, slot=raw["slot"], block_time=None)
    assert first == second
    assert (
        first.matched_swap_program_id
        == second.matched_swap_program_id
        == "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
    )
    assert first.matched_semantic_label == second.matched_semantic_label == "shared_accounts_route"
    assert first.matched_discriminator_hex == second.matched_discriminator_hex == "c1209b3341d69c81"


# ---------------------------------------------------------------------
# Phase 1.5 remediation round 2 -- program-AND-instruction-discriminator
# semantic gate. Round 1's gate proved only that some instruction invoked
# an allowlisted program; the same programs also execute genuine non-trade
# instructions (proven by this project's own
# real_mainnet_orca_close_position_multi_account.json). A positive match
# now binds the resolved program ID, the instruction's own raw `data`
# bytes, and an exact registered discriminator for that same program, all
# on one canonical instruction object
# (argus.parsing.generic_parser._SWAP_INSTRUCTION_REGISTRY/
# _matched_swap_instruction()).
# ---------------------------------------------------------------------

import copy  # noqa: E402

from argus.parsing.generic_parser import (  # noqa: E402
    _SWAP_INSTRUCTION_REGISTRY,
    _decode_base58_strict,
)

_REGISTERED_PROGRAM_IDS = [entry.program_id for entry in _SWAP_INSTRUCTION_REGISTRY]

_BASE58_ALPHABET_LOCAL = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58encode_local(raw: bytes) -> str:
    """A standalone base58 encoder used only to build test INPUT instruction
    data -- deliberately not the production module's internal encoder, so
    constructing adversarial probes never depends on production internals
    behaving correctly."""
    n_leading_zeros = len(raw) - len(raw.lstrip(b"\x00"))
    num = int.from_bytes(raw, "big")
    digits: list[str] = []
    while num > 0:
        num, rem = divmod(num, 58)
        digits.append(_BASE58_ALPHABET_LOCAL[rem])
    return ("1" * n_leading_zeros) + "".join(reversed(digits))


def _one_for_one_with_instructions(
    instructions: list[dict], *, log_messages: list[str] | None = None
) -> dict:
    """Loads the existing one-negative/one-positive
    `one_for_one_unsupported_program` fixture and replaces only its
    `instructions` (and optionally injects `meta.logMessages`) --
    mirroring exactly the independent audit's own probe methodology:
    preserve the balance shape, vary only the instruction evidence."""
    raw = copy.deepcopy(_load("one_for_one_unsupported_program"))
    raw["transaction"]["message"]["instructions"] = instructions
    if log_messages is not None:
        raw.setdefault("meta", {})["logMessages"] = log_messages
    return raw


def _assert_no_swap_evidence(result) -> None:  # type: ignore[no-untyped-def]
    assert result.classification == "SWAP_SIMPLE"
    assert result.matched_swap_program_id is None
    assert result.matched_semantic_label is None
    assert result.matched_discriminator_hex is None
    assert result.is_copy_eligible is False


# --- T1: allowlisted program + missing data is ineligible ---------------


@pytest.mark.parametrize("program_id", _REGISTERED_PROGRAM_IDS)
@pytest.mark.parametrize("data_present", [True, False])
def test_t1_allowlisted_program_missing_data_is_ineligible(
    program_id: str, data_present: bool
) -> None:
    ix: dict = {"programId": program_id, "accounts": []}
    if data_present:
        ix["data"] = ""  # present but empty
    # else: absent entirely
    raw = _one_for_one_with_instructions([ix])
    result = parse_transaction(raw, wallet_address=WALLET, slot=raw["slot"], block_time=None)
    _assert_no_swap_evidence(result)


# --- T2: allowlisted program + unknown/non-swap discriminator is --------
# --- ineligible -----------------------------------------------------------

# Verbatim `data` field from real_mainnet_orca_close_position_multi_account
# .json's own top-level instruction index 4 (Orca Whirlpool
# `DecreaseLiquidity`, discriminator a026d06f685b2c01 =
# sha256("global:decrease_liquidity")[:8]) -- see
# tests/golden/fixtures/real/sources/
# 0f6a7a1fc80144eba665b41472453d63ec3d4828.source.json, signature
# 2xoDWqKZP3p9eDF4iqpur4rmkuAvk1KnW2Gg18tGBgo1x76hdbXU4M1dL37cJoMDiCnaUACmCeRo24yQPUyH26VN.
_ORCA_AUTHENTIC_DECREASE_LIQUIDITY_DATA_B58 = (
    "8xY8jsAzTgXceEKMQYEYCAhGA9RT2cmip4SX8gr4skn9jhKveyDfKv7"
)

_T2_NON_SWAP_DATA_BY_PROGRAM = {
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": _b58encode_local(
        bytes.fromhex("deadbeefdeadbeef")
    ),
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": _b58encode_local(bytes.fromhex("01")),
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc": _ORCA_AUTHENTIC_DECREASE_LIQUIDITY_DATA_B58,
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P": _b58encode_local(
        bytes.fromhex("deadbeefdeadbeef")
    ),
}


@pytest.mark.parametrize("program_id", _REGISTERED_PROGRAM_IDS)
def test_t2_allowlisted_program_non_swap_discriminator_is_ineligible(program_id: str) -> None:
    data_b58 = _T2_NON_SWAP_DATA_BY_PROGRAM[program_id]
    raw = _one_for_one_with_instructions(
        [{"programId": program_id, "accounts": [], "data": data_b58}]
    )
    result = parse_transaction(raw, wallet_address=WALLET, slot=raw["slot"], block_time=None)
    _assert_no_swap_evidence(result)


def test_t2_authentic_orca_non_swap_bytes_decode_to_the_expected_discriminator() -> None:
    """Sanity check on the T2 fixture itself: the verbatim authentic Orca
    bytes really do decode to the real `decrease_liquidity` discriminator,
    not something coincidentally matching the registry."""
    decoded = _decode_base58_strict(_ORCA_AUTHENTIC_DECREASE_LIQUIDITY_DATA_B58)
    assert decoded is not None
    assert decoded[:8].hex() == "a026d06f685b2c01"
    # And it must differ from the registered Orca swap discriminator.
    registered = next(
        e
        for e in _SWAP_INSTRUCTION_REGISTRY
        if e.program_id == "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc"
    )
    assert decoded[: len(registered.discriminator)] != registered.discriminator


# --- T3: program and discriminator must belong together -----------------


def test_t3_recognized_discriminator_under_wrong_program_is_ineligible() -> None:
    """pump.fun's real `buy` discriminator, replayed verbatim under
    Jupiter's program ID -- a recognized discriminator does not grant
    eligibility unless it is registered for THIS program."""
    pumpfun_buy_data = _b58encode_local(bytes.fromhex("66063d1201daebea"))
    raw = _one_for_one_with_instructions(
        [
            {
                "programId": "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
                "accounts": [],
                "data": pumpfun_buy_data,
            }
        ]
    )
    result = parse_transaction(raw, wallet_address=WALLET, slot=raw["slot"], block_time=None)
    _assert_no_swap_evidence(result)


def test_t3_recognized_discriminator_under_unknown_program_is_ineligible() -> None:
    pumpfun_buy_data = _b58encode_local(bytes.fromhex("66063d1201daebea"))
    raw = _one_for_one_with_instructions(
        [
            {
                "programId": "FictitiousUnknownProgramNotInRegistry1111111",
                "accounts": [],
                "data": pumpfun_buy_data,
            }
        ]
    )
    result = parse_transaction(raw, wallet_address=WALLET, slot=raw["slot"], block_time=None)
    _assert_no_swap_evidence(result)


# --- T4: log text cannot grant eligibility -------------------------------


def test_t4_log_text_alone_cannot_grant_eligibility() -> None:
    raw = _one_for_one_with_instructions(
        [
            {
                "programId": "FictitiousLendingMarketProgramNotARealDexNotReal11",
                "accounts": [],
                "data": "",
            }
        ],
        log_messages=["Program log: Instruction: Swap"],
    )
    result = parse_transaction(raw, wallet_address=WALLET, slot=raw["slot"], block_time=None)
    _assert_no_swap_evidence(result)


def test_t4_log_text_on_an_allowlisted_program_with_non_swap_data_still_ineligible() -> None:
    """The strongest form of T4: a real allowlisted program ID, a
    non-swap discriminator, AND a `Program log: Instruction: Swap` line
    all present together -- logs never override the instruction's own
    decoded data."""
    raw = _one_for_one_with_instructions(
        [
            {
                "programId": "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
                "accounts": [],
                "data": _ORCA_AUTHENTIC_DECREASE_LIQUIDITY_DATA_B58,
            }
        ],
        log_messages=["Program log: Instruction: Swap"],
    )
    result = parse_transaction(raw, wallet_address=WALLET, slot=raw["slot"], block_time=None)
    _assert_no_swap_evidence(result)


# --- T6: authentic supported swaps require exact evidence ----------------

# Independently derived (not via the production registry or matcher) from
# each cited fixture's own raw instruction `data`. Locations and expected
# bytes were established by direct inspection of the source JSON during
# this remediation, cross-checked against each fixture's own captured
# program log text where present.
_T6_ORACLE = [
    {
        "source_path": (
            "tests/golden/fixtures/real/sources/"
            "91f3b3675779c6a4fb0a994ef0ff1e91b9e79283.source.json"
        ),
        "friendly_name": "real_mainnet_token_to_usdc_swap",
        "signature": (
            "rNMFZpBmbr6R8g4hStbC5qAictmWvGFQVTwQyXoCY6QDrcq9UV2QfHJ6oARNuS1VaUh3HVe799CDn44dWQReAye"
        ),
        "top_level_index": 2,
        "program_id": "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
        "expected_discriminator_hex": "c1209b3341d69c81",
        "semantic_label": "shared_accounts_route",
    },
    {
        "source_path": (
            "tests/golden/fixtures/real/sources/"
            "eb7e24823b36abbcfd049942b3fcf6b27763fa12.source.json"
        ),
        "friendly_name": "real_mainnet_partial_sell",
        "signature": (
            "2XgzfkWeDeua4oemWXrj3JzhxVsV4mGsqVZfETSbhn6hGFuLvi2fjdK2TGcmuQQnZSEjUmMmPjUnCFWDebGJcgWQ"
        ),
        "top_level_index": 3,
        "program_id": "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
        "expected_discriminator_hex": "09",
        "semantic_label": "swap_base_in",
    },
    {
        "source_path": (
            "tests/golden/fixtures/real/sources/"
            "fa277c7d4ff997f320c38f8e15e8e02ec49983cb.source.json"
        ),
        "friendly_name": "real_mainnet_token_to_sol_swap",
        "signature": (
            "3aQZsNRUbNXpH54GQEaxFpWZsmL554cYGGtWqqoypz8b6LUDYprbRd9AwgivXRLtFBYCU6MU6e9ANurwP8dCMV6"
        ),
        "top_level_index": 4,
        "program_id": "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
        "expected_discriminator_hex": "09",
        "semantic_label": "swap_base_in",
    },
    {
        "source_path": (
            "tests/golden/fixtures/real/sources/"
            "d8f98b52dda0de05f9868ddb0605a25e818beaef.source.json"
        ),
        "friendly_name": "real_mainnet_sol_to_token_swap",
        "signature": (
            "4U8kypMuCUCkR6teu2Vn8ujaEJUR3dcUU5QExZxSMMeJ5fRTvYfWs5M5AB9yNjjHKAQ4w433QVyUivc3Pp8gvG1R"
        ),
        "top_level_index": 2,
        "program_id": "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
        "expected_discriminator_hex": "66063d1201daebea",
        "semantic_label": "buy",
    },
]


def _independent_b58decode(s: str) -> bytes:
    """A second, standalone base58 decoder -- independent of both the
    production module's `_decode_base58_strict` and this test file's own
    `_b58encode_local`/registry -- used only to independently verify T6's
    oracle bytes against the raw source JSON."""
    idx = {c: i for i, c in enumerate(_BASE58_ALPHABET_LOCAL)}
    num = 0
    for ch in s:
        num = num * 58 + idx[ch]
    body = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    n_pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * n_pad + body


def _source_account_keys(msg: dict) -> list[str]:
    return [k["pubkey"] if isinstance(k, dict) else k for k in msg["accountKeys"]]


@pytest.mark.parametrize("row", _T6_ORACLE, ids=[r["friendly_name"] for r in _T6_ORACLE])
def test_t6_authentic_swap_evidence_matches_fixed_independent_oracle(row: dict) -> None:
    source = json.loads((Path(row["source_path"])).read_text())
    if isinstance(source, list):
        source = source[0]
    txn = source["transaction"]
    msg = txn["message"]
    keys = _source_account_keys(msg)
    assert txn["signatures"][0] == row["signature"]

    ix = msg["instructions"][row["top_level_index"]]
    program_id = ix.get("programId") or keys[ix["programIdIndex"]]
    assert program_id == row["program_id"]

    decoded = _independent_b58decode(ix["data"])
    n = len(bytes.fromhex(row["expected_discriminator_hex"]))
    assert decoded[:n].hex() == row["expected_discriminator_hex"]

    # Now assert the production parser reports exactly this evidence.
    result = parse_transaction(source, wallet_address=keys[0], slot=source["slot"], block_time=None)
    assert result.matched_swap_program_id == row["program_id"]
    assert result.matched_semantic_label == row["semantic_label"]
    assert result.matched_discriminator_hex == row["expected_discriminator_hex"]


def test_t6_orca_swap_evidence_matches_fixed_independent_oracle_from_phase_1_5_evidence() -> None:
    """The Orca Whirlpool registry entry is cited from a Phase 1.5
    evidence file (not the permanent real-chain corpus), since no genuine
    Orca `swap` instruction is committed there -- the inner-instruction
    location is independently re-derived here from raw evidence, not
    imported from the production registry."""
    path = PHASE_1_5_EVIDENCE_DIR / "suppl_11_dflow_swap_with_fee.json"
    raw = _load_phase_1_5_evidence(path.name)
    assert raw["transaction"]["signatures"][0] == (
        "627zjqXdMpkogJFCxhcnVTtFCUHWpkAWXoMQPCwQKWnpCJcAzqeg5kx29p8cxmTKHAhXorxEjAVF8Rc1xryyyT7B"
    )
    keys = _source_account_keys(raw["transaction"]["message"])
    inner_group = next(g for g in raw["meta"]["innerInstructions"] if g["index"] == 3)
    ix = inner_group["instructions"][25]
    program_id = ix.get("programId") or keys[ix["programIdIndex"]]
    assert program_id == "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc"
    decoded = _independent_b58decode(ix["data"])
    assert decoded[:8].hex() == "f8c69e91e17587c8"

    result = parse_transaction(
        raw,
        wallet_address="qUeL7JzC52V1DvvPkqnMd74QjThWtSJY5G1PkKv1ur7",
        slot=raw["slot"],
        block_time=None,
    )
    assert result.matched_swap_program_id == "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc"
    assert result.matched_semantic_label == "swap"
    assert result.matched_discriminator_hex == "f8c69e91e17587c8"


# --- T7: altered authentic swap evidence fails closed --------------------


@pytest.mark.parametrize("row", _T6_ORACLE, ids=[r["friendly_name"] for r in _T6_ORACLE])
def test_t7_altered_authentic_swap_data_fails_closed(row: dict) -> None:
    source = json.loads(Path(row["source_path"]).read_text())
    if isinstance(source, list):
        source = source[0]
    keys = _source_account_keys(source["transaction"]["message"])
    wallet = keys[0]

    before = parse_transaction(
        copy.deepcopy(source), wallet_address=wallet, slot=source["slot"], block_time=None
    )
    assert before.is_copy_eligible is True

    for mutation in ("remove", "truncate", "corrupt", "replace_empty"):
        mutated = copy.deepcopy(source)
        ix = mutated["transaction"]["message"]["instructions"][row["top_level_index"]]
        if mutation == "remove":
            del ix["data"]
        elif mutation == "truncate":
            ix["data"] = ix["data"][:1]
        elif mutation == "corrupt":
            # Flip the base58 text so it decodes to different bytes
            # entirely (still valid base58, still same overall balance
            # shape -- only the matched instruction's own data changes).
            ix["data"] = _b58encode_local(
                b"\x00" + bytes.fromhex(row["expected_discriminator_hex"])[1:]
            )
        elif mutation == "replace_empty":
            ix["data"] = ""
        after = parse_transaction(
            mutated, wallet_address=wallet, slot=mutated["slot"], block_time=None
        )
        assert after.classification == "SWAP_SIMPLE"
        assert after.is_copy_eligible is False, f"{row['friendly_name']}/{mutation}"


# --- T8: malformed base58 fails closed ------------------------------------


@pytest.mark.parametrize(
    "bad_value",
    [
        "",
        None,
        123,
        123.0,
        b"AJTQ2h9DXrBqwr1RKF96PBkbRqB83L5oD",
        [],
        {},
        True,
        False,
        "not-base58-0OIl",  # 0/O/I/l are outside the Solana alphabet
        "x" * 5000,  # oversized
    ],
)
def test_t8_malformed_base58_decodes_to_none(bad_value: object) -> None:
    assert _decode_base58_strict(bad_value) is None


def test_t8_decoded_data_shorter_than_the_required_discriminator_is_ineligible() -> None:
    """ "1" is valid base58 (decodes to a single zero byte, b"\\x00") -- not
    a decoder failure -- but that one byte is shorter than every
    multi-byte registered discriminator, so it must still produce no
    match for those programs."""
    assert _decode_base58_strict("1") == b"\x00"
    for program_id in (
        "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
        "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
        "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
    ):
        raw = _one_for_one_with_instructions(
            [{"programId": program_id, "accounts": [], "data": "1"}]
        )
        result = parse_transaction(raw, wallet_address=WALLET, slot=raw["slot"], block_time=None)
        _assert_no_swap_evidence(result)


def test_t8_malformed_base58_produces_no_match_and_no_eligibility() -> None:
    for bad_data in ["", "0OIl", "x" * 5000]:
        raw = _one_for_one_with_instructions(
            [
                {
                    "programId": "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
                    "accounts": [],
                    "data": bad_data,
                }
            ]
        )
        result = parse_transaction(raw, wallet_address=WALLET, slot=raw["slot"], block_time=None)
        _assert_no_swap_evidence(result)


def test_t8_base58_decode_is_deterministic_and_round_trips() -> None:
    # b"" is deliberately excluded: it base58-encodes to the empty string,
    # which _decode_base58_strict rejects outright ("empty ... data
    # produces no semantic match") -- not a round-trip failure, an
    # intentional fail-closed rule on empty instruction data.
    for raw_bytes in (b"\x00", b"\x00\x00", b"\x01", b"\xff" * 8, bytes(range(32))):
        encoded = _b58encode_local(raw_bytes)
        decoded_once = _decode_base58_strict(encoded)
        decoded_twice = _decode_base58_strict(encoded)
        assert decoded_once == decoded_twice == raw_bytes


def test_t8_program_id_index_bool_is_never_treated_as_a_real_index() -> None:
    """`programIdIndex: True`/`False` must never resolve to accountKeys[1]/
    accountKeys[0] via Python's bool-is-an-int coercion."""
    raw = _one_for_one_with_instructions([{"programIdIndex": True, "accounts": [], "data": ""}])
    result = parse_transaction(raw, wallet_address=WALLET, slot=raw["slot"], block_time=None)
    _assert_no_swap_evidence(result)


# --- T9: existing ambiguous and non-trade cases remain ineligible --------


def test_t9_all_previously_ineligible_fixtures_remain_ineligible() -> None:
    for name in [
        "multi_hop_swap",
        "simple_transfer",
        "multiple_token_accounts_lp_add",
        "ambiguous_fee_payer_only",
        "ambiguous_multi_asset_dual_inflow",
        "failed_transaction",
        "transfer_out",
        "token_create",
        "nft_purchase_decimals_zero",
        "one_for_one_unsupported_program",
        "one_for_one_no_instruction_evidence",
    ]:
        result = _parse(name)
        assert result.is_copy_eligible is False, name


def test_t9_authentic_orca_close_position_remains_ineligible() -> None:
    raw = json.loads(
        (FIXTURES_DIR / "real" / "real_mainnet_orca_close_position_multi_account.json").read_text()
    )
    wallet = _source_account_keys(raw["transaction"]["message"])[0]
    result = parse_transaction(raw, wallet_address=wallet, slot=raw["slot"], block_time=None)
    assert result.is_copy_eligible is False
    assert result.matched_swap_program_id is None


def test_t9_solend_and_xstep_remain_ineligible() -> None:
    solend = _load_phase_1_5_evidence("wallet_05_solend_withdraw_all.json")
    result = parse_transaction(
        solend,
        wallet_address="JAMESC37CTVoFEt7TAEcqBjdjAfAWZiPR1YdWotAFjeQ",
        slot=solend["slot"],
        block_time=None,
    )
    assert result.is_copy_eligible is False
    xstep = _load_phase_1_5_evidence("suppl_09_xstep_full_stake_ix.json")
    result = parse_transaction(
        xstep,
        wallet_address="qUeL7JzC52V1DvvPkqnMd74QjThWtSJY5G1PkKv1ur7",
        slot=xstep["slot"],
        block_time=None,
    )
    assert result.is_copy_eligible is False


# --- T10: deterministic reparse and version identity ----------------------


def test_t10_parser_version_changed_between_v2_and_v3() -> None:
    assert PARSER_VERSION == "generic_balance_delta_v3"
    assert PARSER_VERSION != "generic_balance_delta_v2"


@pytest.mark.parametrize("row", _T6_ORACLE, ids=[r["friendly_name"] for r in _T6_ORACLE])
def test_t10_reparse_of_authentic_swap_evidence_is_byte_for_byte_deterministic(row: dict) -> None:
    source = json.loads(Path(row["source_path"]).read_text())
    if isinstance(source, list):
        source = source[0]
    keys = _source_account_keys(source["transaction"]["message"])
    wallet = keys[0]
    first = parse_transaction(
        copy.deepcopy(source), wallet_address=wallet, slot=source["slot"], block_time=None
    )
    second = parse_transaction(
        copy.deepcopy(source), wallet_address=wallet, slot=source["slot"], block_time=None
    )
    assert first == second
    assert first.matched_discriminator_hex == row["expected_discriminator_hex"]
