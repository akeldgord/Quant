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
    """The core Test C assertion: an independently-written, from-scratch
    recomputation of each wallet's net raw deltas directly from
    meta.preBalances/postBalances/preTokenBalances/postTokenBalances
    (never calling into argus.parsing) must equal what
    compute_account_level_deltas() actually reports, for every one of the
    real transactions gathered for this spike."""
    results = _all_results()
    disagreements = [r for r in results if not r["agrees"]]
    assert disagreements == [], disagreements


def test_token_creator_initial_buy_is_a_real_recoverable_early_buyer_event() -> None:
    """Test A's one concrete recovered data point: the pump.fun token's
    own creation transaction bundles the creator's initial dev-buy,
    independently verified here as a genuine SWAP_SIMPLE inflow of the
    newly-created mint, not merely asserted in prose."""
    result = spike.cross_validate_one(spike.RAW_DIR / spike.TOKEN_FILE, spike.TOKEN_CREATOR_WALLET)
    assert result["classification"] == "SWAP_SIMPLE"
    assert spike.TOKEN_MINT in result["parser_reported_deltas"]
    assert result["parser_reported_deltas"][spike.TOKEN_MINT] > 0


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
