"""Phase 2 (TOKEN + WALLET DISCOVERY) pure-function unit tests -- no
database required. Covers the parts of P2-T1 (mint validation), P2-T5
(early-buyer extraction reproducibility), P2-T7 (winner-milestone
detection), and P2-T11 (predecessor regression/safety) that are pure
functions with no persistence dependency. The DB-integration parts of
these same required tests live in
``tests/integration/test_phase2_discovery.py``.
"""

from __future__ import annotations

import base64
import subprocess
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from argus.tokens.mint_validation import (
    SOURCE_ACCOUNT_INFO,
    SOURCE_TOKEN_BALANCE_EVIDENCE,
    STATUS_INVALID,
    STATUS_UNAVAILABLE,
    STATUS_VALID,
    mint_address_shape_error,
    validate_from_account_info,
    validate_from_token_balance_evidence,
)
from argus.wallets.early_buyer_extraction import RawTransactionEvidence, extract_early_buyers
from argus.wallets.winner_watcher import (
    SnapshotView,
    compute_new_milestone_crossings,
    select_baseline,
    select_peak,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
_REAL_MINT_ACCOUNT_LAYOUT = (
    bytes(4) + bytes(32) + (1_000_000).to_bytes(8, "little") + bytes([6]) + bytes([1]) + bytes(36)
)
assert len(_REAL_MINT_ACCOUNT_LAYOUT) == 82


def _account_info(owner: str, data: bytes) -> dict:
    return {"value": {"owner": owner, "data": [base64.b64encode(data).decode(), "base64"]}}


# ---------------------------------------------------------------------
# P2-T1 -- mint validation fails closed
# ---------------------------------------------------------------------


def test_p2t1_valid_committed_mint_evidence_is_valid() -> None:
    from argus.tokens.mint_validation import SPL_TOKEN_PROGRAM_ID

    result = validate_from_account_info(
        _account_info(SPL_TOKEN_PROGRAM_ID, _REAL_MINT_ACCOUNT_LAYOUT),
        mint="5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump",
        evidence_reference="unit-test",
    )
    assert result.status == STATUS_VALID
    assert result.decimals == 6
    assert result.validation_source == SOURCE_ACCOUNT_INFO


def test_p2t1_malformed_address_is_invalid() -> None:
    assert mint_address_shape_error("not-base58-0OIl") is not None
    result = validate_from_account_info({"value": None}, mint="short", evidence_reference="x")
    assert result.status == STATUS_INVALID
    assert "length" in (result.reason or "")


def test_p2t1_valid_shaped_non_mint_account_is_invalid() -> None:
    from argus.tokens.mint_validation import SPL_TOKEN_PROGRAM_ID

    # A genuine SPL token ACCOUNT (165 bytes) is a plausible-shaped
    # base64 payload under the right owner, but it is not a Mint (too
    # short for one interpretation, and semantically the wrong account
    # type) -- here we simulate the "too short for the Mint layout" case,
    # which is what this module can actually detect without a full
    # second account-type decoder.
    token_account_shaped = bytes(70)
    result = validate_from_account_info(
        _account_info(SPL_TOKEN_PROGRAM_ID, token_account_shaped),
        mint="5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump",
        evidence_reference="x",
    )
    assert result.status == STATUS_INVALID
    assert "shorter than" in (result.reason or "")


def test_p2t1_wrong_owner_is_invalid() -> None:
    result = validate_from_account_info(
        _account_info("11111111111111111111111111111111", _REAL_MINT_ACCOUNT_LAYOUT),
        mint="5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump",
        evidence_reference="x",
    )
    assert result.status == STATUS_INVALID
    assert "not the SPL Token" in (result.reason or "")


def test_p2t1_missing_account_is_invalid() -> None:
    result = validate_from_account_info(
        {"value": None}, mint="5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump", evidence_reference="x"
    )
    assert result.status == STATUS_INVALID
    assert "does not exist" in (result.reason or "")


def test_p2t1_malformed_provider_response_is_unavailable() -> None:
    assert (
        validate_from_account_info(
            {}, mint="5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump", evidence_reference="x"
        ).status
        == STATUS_UNAVAILABLE
    )
    assert (
        validate_from_account_info(
            {"value": "not-an-object"},
            mint="5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump",
            evidence_reference="x",
        ).status
        == STATUS_UNAVAILABLE
    )
    from argus.tokens.mint_validation import SPL_TOKEN_PROGRAM_ID

    assert (
        validate_from_account_info(
            {"value": {"owner": SPL_TOKEN_PROGRAM_ID, "data": ["not-valid-base64!!!", "base64"]}},
            mint="5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump",
            evidence_reference="x",
        ).status
        == STATUS_UNAVAILABLE
    )


def test_p2t1_unavailable_provider_is_unavailable_never_valid() -> None:
    result = validate_from_account_info(
        None, mint="5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump", evidence_reference="x"
    )
    assert result.status == STATUS_UNAVAILABLE
    assert result.status != STATUS_VALID


def test_p2t1_token_balance_path_valid_from_real_committed_evidence() -> None:
    import json

    raw = json.loads(
        (
            REPO_ROOT / "orchestration/phase_1_5/evidence/raw/token_00_pumpfun_create.json"
        ).read_text()
    )
    if isinstance(raw, list):
        raw = raw[0]
    result = validate_from_token_balance_evidence(
        raw,
        mint="5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump",
        evidence_reference="orchestration/phase_1_5/evidence/raw/token_00_pumpfun_create.json",
    )
    assert result.status == STATUS_VALID
    assert result.decimals == 6
    assert result.validation_source == SOURCE_TOKEN_BALANCE_EVIDENCE


def test_p2t1_token_balance_path_unavailable_when_mint_not_referenced() -> None:
    result = validate_from_token_balance_evidence(
        {"meta": {"preTokenBalances": [], "postTokenBalances": []}},
        mint="5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump",
        evidence_reference="x",
    )
    assert result.status == STATUS_UNAVAILABLE


# ---------------------------------------------------------------------
# P2-T5 -- early-buyer extraction is reproducible
# ---------------------------------------------------------------------


def _synthetic_tx(
    *, slot: int, signature: str, buyer: str, mint: str, amount: int
) -> RawTransactionEvidence:
    raw = {
        "meta": {
            "err": None,
            "preTokenBalances": [],
            "postTokenBalances": [
                {
                    "accountIndex": 0,
                    "mint": mint,
                    "owner": buyer,
                    "uiTokenAmount": {"amount": str(amount), "decimals": 6},
                }
            ],
        },
    }
    return RawTransactionEvidence(
        raw=raw, signature=signature, slot=slot, block_time=None, evidence_reference=signature
    )


def test_p2t5_extraction_is_order_independent_and_deterministic() -> None:
    mint = "TestMintFixtureNotReal1111111111111111111"
    tx_a = _synthetic_tx(
        slot=100,
        signature="sigA",
        buyer="WalletA1111111111111111111111111111111111",
        mint=mint,
        amount=500,
    )
    tx_b = _synthetic_tx(
        slot=101,
        signature="sigB",
        buyer="WalletB1111111111111111111111111111111111",
        mint=mint,
        amount=200,
    )
    tx_c = _synthetic_tx(
        slot=102,
        signature="sigC",
        buyer="WalletA1111111111111111111111111111111111",
        mint=mint,
        amount=999,
    )

    forward = extract_early_buyers([tx_a, tx_b, tx_c], mint=mint)
    reversed_order = extract_early_buyers([tx_c, tx_b, tx_a], mint=mint)
    shuffled = extract_early_buyers([tx_b, tx_c, tx_a], mint=mint)

    assert forward == reversed_order == shuffled
    # WalletA's FIRST buy (slot 100, sigA) wins -- the later slot-102
    # repurchase (sigC) must never overwrite it.
    wallet_a = next(
        c for c in forward if c.wallet_address == "WalletA1111111111111111111111111111111111"
    )
    assert wallet_a.first_buy_slot == 100
    assert wallet_a.amount_raw == 500
    # Stable sequence order: earliest (slot, signature) first.
    assert [c.wallet_address for c in forward] == [
        "WalletA1111111111111111111111111111111111",
        "WalletB1111111111111111111111111111111111",
    ]
    assert [c.sequence_number for c in forward] == [1, 2]


def test_p2t5_paginated_delivery_reproduces_identical_result() -> None:
    """Feeding the same evidence split into different "pages" (subsets
    delivered and unioned in different groupings) must still reproduce
    the identical final candidate set -- P2-T5's explicit "different
    page/delivery order" requirement."""
    mint = "TestMintFixtureNotReal1111111111111111111"
    txs = [
        _synthetic_tx(
            slot=100 + i,
            signature=f"sig{i}",
            buyer=f"Wallet{i:02d}1111111111111111111111111111",
            mint=mint,
            amount=100 + i,
        )
        for i in range(10)
    ]
    whole = extract_early_buyers(txs, mint=mint)

    # Simulate two "pages" delivered and combined out of order.
    page1 = txs[5:]
    page2 = txs[:5]
    paginated = extract_early_buyers(page2 + page1, mint=mint)
    assert whole == paginated


def test_p2t5_failed_transaction_contributes_no_candidate() -> None:
    mint = "TestMintFixtureNotReal1111111111111111111"
    raw = {
        "meta": {
            "err": {"InstructionError": [0, "Custom"]},
            "postTokenBalances": [
                {
                    "accountIndex": 0,
                    "mint": mint,
                    "owner": "WalletA1111111111111111111111111111111111",
                    "uiTokenAmount": {"amount": "500", "decimals": 6},
                }
            ],
        }
    }
    tx = RawTransactionEvidence(
        raw=raw, signature="failed-sig", slot=1, block_time=None, evidence_reference="x"
    )
    assert extract_early_buyers([tx], mint=mint) == []


def test_p2t5_never_invents_a_buyer_beyond_the_evidence() -> None:
    mint = "TestMintFixtureNotReal1111111111111111111"
    assert extract_early_buyers([], mint=mint) == []


def test_p2t5_deployer_tag_never_excludes_the_wallet() -> None:
    mint = "TestMintFixtureNotReal1111111111111111111"
    deployer = "DeployerWallet111111111111111111111111111"
    tx = _synthetic_tx(slot=1, signature="sig1", buyer=deployer, mint=mint, amount=1000)
    result = extract_early_buyers([tx], mint=mint, deployer_wallet=deployer)
    assert len(result) == 1
    assert result[0].possible_deployer is True
    assert result[0].wallet_address == deployer  # tagged, never removed


# ---------------------------------------------------------------------
# P2-T7 -- winner-milestone detection (pure logic)
# ---------------------------------------------------------------------


def _snap(days: int, price: str | None, liquidity: str | None) -> SnapshotView:
    return SnapshotView(
        snapshot_id=uuid.uuid4(),
        observed_at=datetime(2026, 1, 1 + days, tzinfo=UTC),
        price_usd=Decimal(price) if price is not None else None,
        liquidity_usd=Decimal(liquidity) if liquidity is not None else None,
    )


def test_p2t7_below_threshold_crosses_nothing() -> None:
    token_id = uuid.uuid4()
    snapshots = [_snap(0, "1.0", "1000"), _snap(1, "5.0", "2000")]  # 5x only
    crossings = compute_new_milestone_crossings(
        token_id=token_id, snapshots=snapshots, already_recorded_categories=frozenset()
    )
    assert crossings == []


def test_p2t7_exact_threshold_crossing_creates_exactly_one_new_category() -> None:
    token_id = uuid.uuid4()
    snapshots = [_snap(0, "1.0", "1000"), _snap(1, "10.0", "2000")]  # exactly 10x
    crossings = compute_new_milestone_crossings(
        token_id=token_id, snapshots=snapshots, already_recorded_categories=frozenset()
    )
    assert [c.category for c in crossings] == ["MAJOR_WINNER"]


def test_p2t7_duplicate_and_stale_observations_never_recreate_a_recorded_category() -> None:
    token_id = uuid.uuid4()
    snapshots = [_snap(0, "1.0", "1000"), _snap(1, "10.0", "2000")]
    already = frozenset({"MAJOR_WINNER"})
    # Replaying the exact same snapshots, or even a stale/duplicate
    # snapshot inserted out of order, must not recreate MAJOR_WINNER.
    crossings = compute_new_milestone_crossings(
        token_id=token_id, snapshots=snapshots, already_recorded_categories=already
    )
    assert crossings == []
    out_of_order = [*snapshots, _snap(0, "1.0", "1000")]  # duplicate/stale re-delivery
    crossings2 = compute_new_milestone_crossings(
        token_id=token_id, snapshots=out_of_order, already_recorded_categories=already
    )
    assert crossings2 == []


def test_p2t7_restarted_worker_replaying_full_history_reproduces_same_crossings() -> None:
    """Simulates a crashed/restarted worker re-evaluating a token's full
    history from scratch: passing already_recorded_categories=frozenset()
    (as if nothing had been persisted yet) must reproduce byte-identical
    crossings to the original run, not something different."""
    token_id = uuid.uuid4()
    snapshots = [_snap(0, "0", "0"), _snap(1, "1.0", "1000"), _snap(2, "25.0", "5000")]
    first = compute_new_milestone_crossings(
        token_id=token_id, snapshots=snapshots, already_recorded_categories=frozenset()
    )
    restarted = compute_new_milestone_crossings(
        token_id=token_id,
        snapshots=list(reversed(snapshots)),
        already_recorded_categories=frozenset(),
    )
    assert first == restarted
    assert {c.category for c in first} == {"MAJOR_WINNER", "MONSTER"}


def test_p2t7_zero_liquidity_launch_never_inflates_the_baseline() -> None:
    token_id = uuid.uuid4()
    # A zero-liquidity "launch instant" at an artificially tiny price,
    # then the real first tradable state -- the multiple must be computed
    # from the tradable state, not the untradeable one.
    snapshots = [_snap(0, "0.0000001", "0"), _snap(1, "1.0", "1000"), _snap(2, "5.0", "2000")]
    baseline = select_baseline(snapshots)
    assert baseline is not None
    assert baseline.price_usd == Decimal("1.0")
    crossings = compute_new_milestone_crossings(
        token_id=token_id, snapshots=snapshots, already_recorded_categories=frozenset()
    )
    assert crossings == []  # 5x only, below MAJOR_WINNER's 10x -- proves baseline wasn't 0.0000001


def test_p2t7_no_tradable_state_selects_no_baseline_or_peak() -> None:
    assert select_baseline([_snap(0, "0", "0"), _snap(1, None, None)]) is None
    assert select_peak([], at_or_after=datetime(2026, 1, 1, tzinfo=UTC)) is None


def test_p2t7_milestone_crossing_dataclass_has_no_trade_execution_fields() -> None:
    """Research labels only: MilestoneCrossing must not carry anything
    resembling an order/quote/execution field."""
    from argus.wallets.winner_watcher import MilestoneCrossing

    field_names = {f.name for f in __import__("dataclasses").fields(MilestoneCrossing)}
    forbidden = {
        "order_id",
        "quote",
        "signed_transaction",
        "execution_id",
        "signature_to_broadcast",
    }
    assert not (field_names & forbidden)


# ---------------------------------------------------------------------
# P2-T11 -- predecessor regression and safety
# ---------------------------------------------------------------------


def test_p2t11_parser_version_unchanged_by_phase2_work() -> None:
    from argus.parsing.generic_parser import PARSER_VERSION

    assert PARSER_VERSION == "generic_balance_delta_v3"


def test_p2t11_no_signer_or_execution_path_introduced_in_phase2_modules() -> None:
    """Static scan: none of the new Phase 2 source files may reference a
    signing/broadcast/execution primitive. A grep-based check is
    deliberately blunt (it can't prove a *capability* doesn't exist) but
    it is a real, verifiable check that no unmissable naming for such a
    path was introduced, matching MASTER_SPEC.md's absolute prohibition
    and this instruction's explicit invariant 12."""
    forbidden_terms = [
        "sign_transaction",
        "signTransaction",
        "private_key",
        "PRIVATE_KEY",
        "seed_phrase",
        "broadcast_transaction",
        "submit_transaction",
        "Keypair",
        "send_and_confirm",
    ]
    phase2_dirs = [
        REPO_ROOT / "src/argus/tokens",
        REPO_ROOT / "src/argus/wallets",
    ]
    offending: list[str] = []
    for directory in phase2_dirs:
        for path in directory.rglob("*.py"):
            text = path.read_text()
            for term in forbidden_terms:
                if term in text:
                    offending.append(f"{path}: {term}")
    assert offending == [], offending


def test_p2t11_no_paid_provider_upgrade_path_in_phase2_modules() -> None:
    forbidden_terms = ["upgrade_tier", "enable_paid", "PAID_API_KEY"]
    phase2_dirs = [REPO_ROOT / "src/argus/tokens", REPO_ROOT / "src/argus/wallets"]
    offending: list[str] = []
    for directory in phase2_dirs:
        for path in directory.rglob("*.py"):
            text = path.read_text()
            for term in forbidden_terms:
                if term in text:
                    offending.append(f"{path}: {term}")
    assert offending == [], offending


def test_p2t11_golden_and_phase_1_5_suites_still_collect_and_pass() -> None:
    """A cheap, in-process regression tripwire (the full replay is also
    run directly as part of the mandatory validation suite -- see the
    checkpoint): golden parser fixtures and the Phase 1.5 semantic-gate
    tests must still collect and pass under pytest, proving Phase 2 work
    introduced no import-time breakage in those modules."""
    result = subprocess.run(
        ["python3", "-m", "pytest", "tests/golden", "tests/phase_1_5", "-q", "--no-header"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
