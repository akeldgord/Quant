"""Phase 1.5 (instruction argus-phase-1-5-001) Test C regression coverage.

Loads ``scripts/phase_1_5_feasibility.py`` the same way
``tests/unit/test_orchestrator_watch.py`` loads the watcher script (a
standalone script, not part of the ``argus`` package), and re-runs its
cross-validation of every real, GitHub-sourced transaction in
``orchestration/phase_1_5/evidence/raw/`` against the existing
deterministic Phase 1 parser. This is what "run the new/relevant Phase
1.5 tests" (this instruction's mandatory evidence requirement) exercises
going forward, not just the one-off script invocation recorded in the
checkpoint.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "phase_1_5_feasibility.py"
_spec = importlib.util.spec_from_file_location("phase_1_5_feasibility", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
spike = importlib.util.module_from_spec(_spec)
sys.modules["phase_1_5_feasibility"] = spike
_spec.loader.exec_module(spike)


def _all_results() -> list[dict]:
    results = []
    token_result = spike.cross_validate_one(
        spike.RAW_DIR / spike.TOKEN_FILE, spike.TOKEN_CREATOR_WALLET
    )
    results.append(token_result)
    for filename in spike.WALLET_FILES:
        results.append(spike.cross_validate_one(spike.RAW_DIR / filename, spike.CANDIDATE_WALLET))
    for filename in spike.SUPPLEMENTARY_FILES:
        results.append(
            spike.cross_validate_one(spike.RAW_DIR / filename, spike.SUPPLEMENTARY_WALLET)
        )
    return results


def test_at_least_20_real_transactions_are_available_for_cross_validation() -> None:
    results = _all_results()
    assert len(results) >= 20


def test_independent_recomputation_agrees_with_the_parser_for_every_transaction() -> None:
    """The core Test C delta-ARITHMETIC assertion only: an independently-
    written, from-scratch recomputation of each wallet's net raw deltas
    directly from meta.preBalances/postBalances/preTokenBalances/
    postTokenBalances (never calling into argus.parsing) must equal what
    compute_account_level_deltas() actually reports, for every one of the
    real transactions gathered for this spike. This proves the balance-
    delta math is correct -- it does NOT by itself prove any row's
    semantic classification or copy-eligibility (Phase 1.5 remediation
    round 1: see test_solend_and_xstep_false_positives_are_now_ineligible
    and test_every_copy_eligible_row_has_independent_semantic_evidence for
    that separate claim)."""
    results = _all_results()
    disagreements = [r for r in results if not r["delta_arithmetic_agrees"]]
    assert disagreements == [], disagreements


def test_token_creator_initial_buy_is_a_real_recoverable_early_buyer_event() -> None:
    """Test A's one concrete recovered data point: the pump.fun token's
    own creation transaction bundles the creator's initial dev-buy,
    independently verified here as a genuine SWAP_SIMPLE inflow of the
    newly-created mint, backed by positive instruction-AND-discriminator
    evidence (the real pump.fun `buy` instruction, Phase 1.5 remediation
    round 2), not merely a balance shape or bare program ID -- not merely
    asserted in prose."""
    result = spike.cross_validate_one(spike.RAW_DIR / spike.TOKEN_FILE, spike.TOKEN_CREATOR_WALLET)
    assert result["classification"] == "SWAP_SIMPLE"
    assert spike.TOKEN_MINT in result["parser_reported_deltas"]
    assert result["parser_reported_deltas"][spike.TOKEN_MINT] > 0
    assert result["matched_swap_program_id"] == "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
    assert result["matched_semantic_label"] == "buy"
    assert result["matched_discriminator_hex"] == "66063d1201daebea"
    assert result["is_copy_eligible"] is True


def test_solend_and_xstep_false_positives_are_now_ineligible() -> None:
    """The exact SPEC_BLOCKING finding from argus-phase-1-5-remediation-001:
    the Solend withdrawal/redemption and xStep stake fixtures have the
    same clean one-negative/one-positive balance shape as a genuine swap
    (so the parser still, correctly, reports SWAP_SIMPLE as its balance-
    shape research classification) but neither transaction's own
    instructions invoke a supported trade-venue program -- both must be
    ineligible and expose no swap semantic match at all (T5)."""
    solend = spike.cross_validate_one(
        spike.RAW_DIR / "wallet_05_solend_withdraw_all.json", spike.CANDIDATE_WALLET
    )
    xstep = spike.cross_validate_one(
        spike.RAW_DIR / "suppl_09_xstep_full_stake_ix.json", spike.SUPPLEMENTARY_WALLET
    )
    for result in (solend, xstep):
        assert result["classification"] == "SWAP_SIMPLE"
        assert result["matched_swap_program_id"] is None
        assert result["matched_semantic_label"] is None
        assert result["matched_discriminator_hex"] is None
        assert result["is_copy_eligible"] is False


def test_titan_swap_2_is_now_ineligible_under_the_stricter_discriminator_gate() -> None:
    """Phase 1.5 remediation round 2, honest disclosure: round 1's
    program-only gate marked suppl_13_titan_swap_with_fees_2.json eligible
    because it invokes the real Raydium AMM V4 program somewhere in its
    instructions -- but that specific Raydium invocation's own decoded
    instruction tag is 0x10, not the registered `swap_base_in` (0x09) this
    project has independently verified from two other authentic fixtures.
    Round 2 correctly makes this row ineligible: "program appeared
    somewhere" was never proof of a trade instruction. Not treated as a
    regression -- the instruction explicitly permits any row losing
    eligibility when its own evidence does not support an exact pair."""
    result = spike.cross_validate_one(
        spike.RAW_DIR / "suppl_13_titan_swap_with_fees_2.json", spike.SUPPLEMENTARY_WALLET
    )
    assert result["classification"] == "SWAP_SIMPLE"
    assert result["matched_swap_program_id"] is None
    assert result["matched_semantic_label"] is None
    assert result["matched_discriminator_hex"] is None
    assert result["is_copy_eligible"] is False


# T11 -- the Phase 1.5 oracle is independent: every eligible row's parser
# result is compared to a fixed table written directly from authentic raw
# evidence (file, signature, program ID, semantic label, exact
# discriminator hex, source instruction location, supporting log text).
# This table does NOT import argus.parsing.generic_parser's registry and
# does NOT call its matcher to derive any expected value -- correcting the
# exact defect the round-2 audit found in this file's own prior version
# (which checked membership in the production registry, not an
# independent semantic oracle).
_PHASE_1_5_ELIGIBLE_ORACLE = [
    {
        "file": "token_00_pumpfun_create.json",
        "signature": (
            "2s393PSYYxJJJfGiwHf18HZeC68nZs44ssbeB4aAkeYMyd1dyiiu3yVmGyRWZuArk5HzYDgVxYfhKLYd2CJ8kCBj"
        ),
        "wallet": "6xo262KbDXepWbF3vPTrFXysr5vJwk3mozBXmXk3hmMx",
        "program_id": "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
        "semantic_label": "buy",
        "discriminator_hex": "66063d1201daebea",
        "instruction_location": "top-level instruction index 5",
        "supporting_log_text": "Program log: Instruction: Buy",
    },
    {
        "file": "suppl_08_jupiter_no_dooot.json",
        "signature": (
            "BMRnQSJSdTPgD2A4sLcWYEwv8gCiLne429aqR8iiDs3Upo1NTc5bcZRojHVC9gWvrpvEYmEqWB1ZFYDVvpS3JU9"
        ),
        "wallet": "qUeL7JzC52V1DvvPkqnMd74QjThWtSJY5G1PkKv1ur7",
        "program_id": "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
        "semantic_label": "shared_accounts_route",
        "discriminator_hex": "c1209b3341d69c81",
        "instruction_location": "top-level instruction index 2",
        "supporting_log_text": "Program log: Instruction: SharedAccountsRoute",
    },
    {
        "file": "suppl_11_dflow_swap_with_fee.json",
        "signature": (
            "627zjqXdMpkogJFCxhcnVTtFCUHWpkAWXoMQPCwQKWnpCJcAzqeg5kx29p8cxmTKHAhXorxEjAVF8Rc1xryyyT7B"
        ),
        "wallet": "qUeL7JzC52V1DvvPkqnMd74QjThWtSJY5G1PkKv1ur7",
        "program_id": "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
        "semantic_label": "swap",
        "discriminator_hex": "f8c69e91e17587c8",
        "instruction_location": ("inner instruction of top-level instruction index 3, position 25"),
        "supporting_log_text": (
            "Program whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc invoke [2] / "
            "Program log: Instruction: Swap"
        ),
    },
]


def test_every_copy_eligible_row_matches_the_independent_fixed_oracle() -> None:
    """T11: compares every eligible row's parser result to the fixed
    oracle table above, and separately confirms the eligible-row SET
    itself is exactly the oracle's three rows -- no more, no fewer."""
    results = _all_results()
    eligible = {r["file"]: r for r in results if r["is_copy_eligible"]}
    assert eligible, "expected at least one genuinely eligible row to check"
    assert set(eligible) == {row["file"] for row in _PHASE_1_5_ELIGIBLE_ORACLE}

    for row in _PHASE_1_5_ELIGIBLE_ORACLE:
        result = eligible[row["file"]]
        assert result["signature"] == row["signature"]
        assert result["wallet"] == row["wallet"]
        assert result["matched_swap_program_id"] == row["program_id"]
        assert result["matched_semantic_label"] == row["semantic_label"]
        assert result["matched_discriminator_hex"] == row["discriminator_hex"]


def test_candidate_wallet_history_spans_multiple_required_dimensions() -> None:
    """Test B: the 14 real candidate-wallet transactions must cover more
    than one classification/protocol shape, not a single repeated case,
    to genuinely exercise wallet-level signatures, token-account
    activity, swaps, transfers, and position-lifecycle events."""
    results = [
        spike.cross_validate_one(spike.RAW_DIR / f, spike.CANDIDATE_WALLET)
        for f in spike.WALLET_FILES
    ]
    classifications = {r["classification"] for r in results}
    assert len(classifications) >= 3
    assert all(r["signature"] for r in results)
    assert len({r["signature"] for r in results}) == len(results)
