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

# A genuine legacy SPL Token *Account* layout (never a Mint): mint(32) +
# owner(32) + amount(8) + delegate_option(4) + delegate(32) + state(1) +
# is_native_option(4) + is_native(8) + delegate_amount(8) +
# close_authority_option(4) + close_authority(32) = 165 bytes exactly.
# Byte 45 (within the "owner" pubkey field, offset 32-64) is deliberately
# set to 1 -- the exact P2-R1 false-positive shape: incidentally
# resembling a plausible is_initialized=1 byte at the same offset the
# (pre-fix) Mint decoder read blindly, without ever confirming this
# payload is actually a Mint layout at all.
_legacy_token_account_buf = bytearray(165)
_legacy_token_account_buf[45] = 1
_LEGACY_TOKEN_ACCOUNT_SHAPE = bytes(_legacy_token_account_buf)
assert len(_LEGACY_TOKEN_ACCOUNT_SHAPE) == 165

# A genuine Token-2022 extended Mint: the same 82-byte base Mint struct,
# zero-padded to 165 bytes, then a single AccountType::Mint (1)
# discriminator byte -- the minimum possible length (166) for any
# Token-2022 account carrying extensions.
_MINT_2022_EXTENDED = (
    _REAL_MINT_ACCOUNT_LAYOUT + bytes(165 - len(_REAL_MINT_ACCOUNT_LAYOUT)) + bytes([1])
)
assert len(_MINT_2022_EXTENDED) == 166

# The same extended layout but with AccountType::Account (2) -- a
# genuine Token-2022 token *account* with extensions, never a Mint.
_ACCOUNT_2022_EXTENDED = (
    _REAL_MINT_ACCOUNT_LAYOUT + bytes(165 - len(_REAL_MINT_ACCOUNT_LAYOUT)) + bytes([2])
)
assert len(_ACCOUNT_2022_EXTENDED) == 166


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
    """P2-R1: a genuine 165-byte legacy SPL Token ACCOUNT payload, with
    byte 45 deliberately set to 1 (the exact pre-fix false-positive
    shape -- byte 45 lands inside the Account layout's "owner" pubkey
    field, not an is_initialized flag), must never validate as a Mint.
    The pre-remediation code's own bare `len(decoded) < 82` check
    accepted this (165 >= 82) and blindly read bytes 44/45 as if they
    were Mint fields; this test independently reproduces that exact
    scenario the frozen finding named and confirms it now fails closed."""
    from argus.tokens.mint_validation import SPL_TOKEN_PROGRAM_ID

    result = validate_from_account_info(
        _account_info(SPL_TOKEN_PROGRAM_ID, _LEGACY_TOKEN_ACCOUNT_SHAPE),
        mint="5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump",
        evidence_reference="x",
    )
    assert result.status == STATUS_INVALID
    assert result.decimals is None
    assert "not a recognized Mint account shape" in (result.reason or "")


def test_p2t1_short_payload_is_invalid() -> None:
    """A payload shorter than both the base Mint layout and the
    Token-2022 extended-account threshold fails closed."""
    from argus.tokens.mint_validation import SPL_TOKEN_PROGRAM_ID

    result = validate_from_account_info(
        _account_info(SPL_TOKEN_PROGRAM_ID, bytes(70)),
        mint="5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump",
        evidence_reference="x",
    )
    assert result.status == STATUS_INVALID
    assert "not a recognized Mint account shape" in (result.reason or "")


def test_p2t1_valid_token2022_mint_no_extensions_is_valid() -> None:
    """A Token-2022 mint with zero extensions serializes as exactly the
    82-byte base Mint struct -- identical size to a legacy mint -- and
    must validate."""
    from argus.tokens.mint_validation import SPL_TOKEN_2022_PROGRAM_ID

    result = validate_from_account_info(
        _account_info(SPL_TOKEN_2022_PROGRAM_ID, _REAL_MINT_ACCOUNT_LAYOUT),
        mint="5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump",
        evidence_reference="x",
    )
    assert result.status == STATUS_VALID
    assert result.decimals == 6


def test_p2t1_valid_token2022_extended_mint_is_valid() -> None:
    """A genuine Token-2022 extended Mint (base struct + padding to 165
    + AccountType::Mint discriminator byte) must validate."""
    from argus.tokens.mint_validation import SPL_TOKEN_2022_PROGRAM_ID

    result = validate_from_account_info(
        _account_info(SPL_TOKEN_2022_PROGRAM_ID, _MINT_2022_EXTENDED),
        mint="5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump",
        evidence_reference="x",
    )
    assert result.status == STATUS_VALID
    assert result.decimals == 6


def test_p2t1_malformed_token2022_extension_account_type_is_invalid() -> None:
    """The same extended layout but with AccountType::Account (2), not
    Mint (1) -- a genuine Token-2022 token account with extensions --
    must never validate as a mint."""
    from argus.tokens.mint_validation import SPL_TOKEN_2022_PROGRAM_ID

    result = validate_from_account_info(
        _account_info(SPL_TOKEN_2022_PROGRAM_ID, _ACCOUNT_2022_EXTENDED),
        mint="5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump",
        evidence_reference="x",
    )
    assert result.status == STATUS_INVALID
    assert "AccountType" in (result.reason or "") or "discriminator" in (result.reason or "")


def test_p2t1_extended_length_under_legacy_program_is_invalid() -> None:
    """An extended-length (>165 byte) payload under the legacy SPL Token
    program (which has no extension mechanism at all) must never
    validate, regardless of its trailing bytes."""
    from argus.tokens.mint_validation import SPL_TOKEN_PROGRAM_ID

    result = validate_from_account_info(
        _account_info(SPL_TOKEN_PROGRAM_ID, _MINT_2022_EXTENDED),
        mint="5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump",
        evidence_reference="x",
    )
    assert result.status == STATUS_INVALID


def test_p2t1_multisig_account_length_is_invalid() -> None:
    """A genuine SPL Token multisig account (355 bytes) must never
    validate as a mint."""
    from argus.tokens.mint_validation import SPL_TOKEN_PROGRAM_ID

    result = validate_from_account_info(
        _account_info(SPL_TOKEN_PROGRAM_ID, bytes(355)),
        mint="5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump",
        evidence_reference="x",
    )
    assert result.status == STATUS_INVALID


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


def _balance_entry(*, program_id: str, decimals: int) -> dict:
    from argus.tokens.mint_validation import SPL_TOKEN_PROGRAM_ID

    return {
        "mint": "5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump",
        "programId": program_id or SPL_TOKEN_PROGRAM_ID,
        "uiTokenAmount": {"decimals": decimals, "amount": "1", "uiAmount": 0.000001},
    }


def test_p2t8_conflicting_decimals_across_entries_is_unavailable() -> None:
    """P2-R1/R8: two balance entries for the same mint in the same
    transaction that disagree on decimals is internally inconsistent
    evidence and must never be resolved by picking the first entry."""
    from argus.tokens.mint_validation import SPL_TOKEN_PROGRAM_ID

    raw = {
        "meta": {
            "err": None,
            "postTokenBalances": [
                _balance_entry(program_id=SPL_TOKEN_PROGRAM_ID, decimals=6),
                _balance_entry(program_id=SPL_TOKEN_PROGRAM_ID, decimals=9),
            ],
            "preTokenBalances": [],
        }
    }
    result = validate_from_token_balance_evidence(
        raw, mint="5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump", evidence_reference="x"
    )
    assert result.status == STATUS_UNAVAILABLE
    assert "conflicting decimals" in (result.reason or "")


def test_p2t8_conflicting_owner_program_across_entries_is_unavailable() -> None:
    from argus.tokens.mint_validation import SPL_TOKEN_2022_PROGRAM_ID, SPL_TOKEN_PROGRAM_ID

    raw = {
        "meta": {
            "err": None,
            "postTokenBalances": [
                _balance_entry(program_id=SPL_TOKEN_PROGRAM_ID, decimals=6),
                _balance_entry(program_id=SPL_TOKEN_2022_PROGRAM_ID, decimals=6),
            ],
            "preTokenBalances": [],
        }
    }
    result = validate_from_token_balance_evidence(
        raw, mint="5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump", evidence_reference="x"
    )
    assert result.status == STATUS_UNAVAILABLE
    assert "conflicting owner program" in (result.reason or "")


def test_p2t8_failed_transaction_evidence_is_unavailable() -> None:
    """A transaction with meta.err set is never usable as validating
    evidence, even if its balance entries otherwise look fine."""
    from argus.tokens.mint_validation import SPL_TOKEN_PROGRAM_ID

    raw = {
        "meta": {
            "err": {"InstructionError": [0, "Custom", 1]},
            "postTokenBalances": [_balance_entry(program_id=SPL_TOKEN_PROGRAM_ID, decimals=6)],
            "preTokenBalances": [],
        }
    }
    result = validate_from_token_balance_evidence(
        raw, mint="5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump", evidence_reference="x"
    )
    assert result.status == STATUS_UNAVAILABLE
    assert "failed on-chain" in (result.reason or "")


def test_p2t8_chain_time_is_derived_from_block_time() -> None:
    """P2-R8: chain_time is populated from the evidence's own blockTime,
    not left None when the evidence actually carries it."""
    from argus.tokens.mint_validation import SPL_TOKEN_PROGRAM_ID

    raw = {
        "blockTime": 1727637145,
        "meta": {
            "err": None,
            "postTokenBalances": [_balance_entry(program_id=SPL_TOKEN_PROGRAM_ID, decimals=6)],
            "preTokenBalances": [],
        },
    }
    result = validate_from_token_balance_evidence(
        raw, mint="5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump", evidence_reference="x"
    )
    assert result.status == STATUS_VALID
    assert result.chain_time == datetime.fromtimestamp(1727637145, tz=UTC)
    assert result.commitment is None


def test_p2t1_real_evidence_persists_chain_time() -> None:
    """The real pump.fun creation-transaction fixture used throughout
    this project's demonstration genuinely carries a blockTime, so its
    validation must persist a non-None chain_time."""
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
        evidence_reference="x",
    )
    assert result.status == STATUS_VALID
    assert result.chain_time is not None
    assert result.chain_time == datetime.fromtimestamp(raw["blockTime"], tz=UTC)


# ---------------------------------------------------------------------
# P2-T5 -- early-buyer extraction is reproducible
# ---------------------------------------------------------------------


def _synthetic_tx(
    *,
    slot: int,
    signature: str,
    buyer: str,
    mint: str,
    amount: int,
    signers: list[str] | None = None,
) -> RawTransactionEvidence:
    raw: dict = {
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
    if signers is not None:
        raw["transaction"] = {
            "message": {
                "header": {"numRequiredSignatures": len(signers)},
                "accountKeys": [*signers, "SomeOtherReadonlyAccount1111111111111111"],
            }
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
# P2-R3 -- deterministic tie-break ordering + semantic buyer classification
# ---------------------------------------------------------------------


def test_p2r3_ties_on_slot_and_signature_break_deterministically_on_wallet_address() -> None:
    """Two distinct owners first-seen in the EXACT same transaction (a
    routine case -- e.g. a bonding-curve reserve and the buyer, both
    credited in the same instruction) tie on (slot, signature) alone.
    The explicit wallet-address tie-breaker must resolve this the same
    way regardless of which owner happened to be inserted first."""
    mint = "TestMintFixtureNotReal1111111111111111111"
    raw = {
        "meta": {
            "err": None,
            "preTokenBalances": [],
            "postTokenBalances": [
                {
                    "accountIndex": 0,
                    "mint": mint,
                    "owner": "ZWallet111111111111111111111111111111111",
                    "uiTokenAmount": {"amount": "500", "decimals": 6},
                },
                {
                    "accountIndex": 1,
                    "mint": mint,
                    "owner": "AWallet111111111111111111111111111111111",
                    "uiTokenAmount": {"amount": "700", "decimals": 6},
                },
            ],
        },
    }
    tx = RawTransactionEvidence(
        raw=raw, signature="sig1", slot=1, block_time=None, evidence_reference="sig1"
    )
    result = extract_early_buyers([tx], mint=mint)
    # Lexicographically-smaller wallet address sorts first, deterministically.
    assert [c.wallet_address for c in result] == [
        "AWallet111111111111111111111111111111111",
        "ZWallet111111111111111111111111111111111",
    ]
    assert [c.sequence_number for c in result] == [1, 2]


def test_p2r3_ordering_is_independent_of_pythonhashseed() -> None:
    """The frozen finding's own reproduction: run the same extraction
    twice as separate subprocesses under different PYTHONHASHSEED values
    and assert byte-identical output -- Python `set`/`dict`-of-`str`
    iteration order (which this project's pre-fix code silently relied
    on for its final tie-break) genuinely varies with the hash seed, so
    this is the only way to actually prove the fix, not merely assert it
    in-process."""
    mint = "TestMintFixtureNotReal1111111111111111111"
    raw = {
        "meta": {
            "err": None,
            "preTokenBalances": [],
            "postTokenBalances": [
                {
                    "accountIndex": i,
                    "mint": mint,
                    "owner": f"Wallet{letter}11111111111111111111111111111111"[:43],
                    "uiTokenAmount": {"amount": str(100 * (i + 1)), "decimals": 6},
                }
                for i, letter in enumerate("MDBQFAZKXY")
            ],
        },
    }
    script = f"""
import json
from argus.wallets.early_buyer_extraction import RawTransactionEvidence, extract_early_buyers

raw = {raw!r}
tx = RawTransactionEvidence(raw=raw, signature="sig1", slot=1, block_time=None, evidence_reference="sig1")
result = extract_early_buyers([tx], mint={mint!r})
print(json.dumps([[c.wallet_address, c.sequence_number] for c in result]))
"""
    import os
    import sys

    outputs = []
    for seed in ("0", "1", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        outputs.append(proc.stdout.strip())
    assert len(set(outputs)) == 1, f"ordering varied by PYTHONHASHSEED: {outputs}"


def test_p2r3_signer_owner_is_classified_as_signer_wallet() -> None:
    from argus.wallets.early_buyer_extraction import OWNERSHIP_SIGNER_WALLET

    mint = "TestMintFixtureNotReal1111111111111111111"
    buyer = "RealBuyerWallet11111111111111111111111111"
    tx = _synthetic_tx(
        slot=1, signature="sig1", buyer=buyer, mint=mint, amount=500, signers=[buyer]
    )
    result = extract_early_buyers([tx], mint=mint)
    assert len(result) == 1
    assert result[0].ownership_classification == OWNERSHIP_SIGNER_WALLET


def test_p2r3_non_signer_owner_is_classified_as_unresolved_non_signer() -> None:
    """The exact real-world shape this fix closes: a program-derived
    reserve/curve account receives tokens in a transaction it never
    signed (only the actual buyer/fee-payer signs)."""
    from argus.wallets.early_buyer_extraction import OWNERSHIP_UNRESOLVED_NON_SIGNER

    mint = "TestMintFixtureNotReal1111111111111111111"
    reserve_pda = "BondingCurveReservePDA111111111111111111"
    real_signer = "ActualSignerWallet11111111111111111111111"
    tx = _synthetic_tx(
        slot=1, signature="sig1", buyer=reserve_pda, mint=mint, amount=500, signers=[real_signer]
    )
    result = extract_early_buyers([tx], mint=mint)
    assert len(result) == 1
    assert result[0].ownership_classification == OWNERSHIP_UNRESOLVED_NON_SIGNER
    assert result[0].wallet_address == reserve_pda  # raw evidence preserved, not erased


def test_p2r3_missing_message_shape_fails_closed_to_unresolved() -> None:
    """No `transaction.message` shape at all (this project's own
    synthetic P2-T5 fixtures, and any malformed/partial evidence) must
    fail closed to unresolved, never silently assumed to be a signer."""
    from argus.wallets.early_buyer_extraction import OWNERSHIP_UNRESOLVED_NON_SIGNER

    mint = "TestMintFixtureNotReal1111111111111111111"
    buyer = "SomeWallet1111111111111111111111111111111"
    tx = _synthetic_tx(slot=1, signature="sig1", buyer=buyer, mint=mint, amount=500)
    result = extract_early_buyers([tx], mint=mint)
    assert result[0].ownership_classification == OWNERSHIP_UNRESOLVED_NON_SIGNER


def test_p2r3_real_pumpfun_evidence_classifies_creator_as_signer_and_curve_as_unresolved() -> None:
    """The exact real evidence this project's own demonstration uses:
    the creator/dev-buy wallet is a genuine transaction signer; the
    bonding-curve reserve PDA is not."""
    import json

    from argus.wallets.early_buyer_extraction import (
        OWNERSHIP_SIGNER_WALLET,
        OWNERSHIP_UNRESOLVED_NON_SIGNER,
    )

    raw = json.loads(
        (
            REPO_ROOT / "orchestration/phase_1_5/evidence/raw/token_00_pumpfun_create.json"
        ).read_text()
    )
    if isinstance(raw, list):
        raw = raw[0]
    mint = "5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump"
    tx = RawTransactionEvidence(
        raw=raw,
        signature=raw["transaction"]["signatures"][0],
        slot=raw["slot"],
        block_time=None,
        evidence_reference="real-evidence-test",
    )
    result = extract_early_buyers([tx], mint=mint)
    by_wallet = {c.wallet_address: c for c in result}
    assert (
        by_wallet["6xo262KbDXepWbF3vPTrFXysr5vJwk3mozBXmXk3hmMx"].ownership_classification
        == OWNERSHIP_SIGNER_WALLET
    )
    assert (
        by_wallet["CQrqvWERJtEjw2rCCQV6EqfM6V6jzTuKjhJjKNFmGB7r"].ownership_classification
        == OWNERSHIP_UNRESOLVED_NON_SIGNER
    )


# ---------------------------------------------------------------------
# P2-T7 -- winner-milestone detection (pure logic)
# ---------------------------------------------------------------------


def _snap(
    days: int, price: str | None, liquidity: str | None, confidence: str | None = "HIGH"
) -> SnapshotView:
    return SnapshotView(
        snapshot_id=uuid.uuid4(),
        observed_at=datetime(2026, 1, 1 + days, tzinfo=UTC),
        price_usd=Decimal(price) if price is not None else None,
        liquidity_usd=Decimal(liquidity) if liquidity is not None else None,
        market_state_confidence=confidence,
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


def test_p2r4_low_confidence_peak_never_creates_a_milestone() -> None:
    """P2-R4: an otherwise-qualifying 100x peak with LOW confidence must
    not be used as the peak -- reproduces the independent audit's own
    12x-with-no-confidence-field probe, corrected."""
    token_id = uuid.uuid4()
    snapshots = [
        _snap(0, "1.0", "1000", confidence="HIGH"),
        _snap(1, "100.0", "50000", confidence="LOW"),
    ]
    crossings = compute_new_milestone_crossings(
        token_id=token_id, snapshots=snapshots, already_recorded_categories=frozenset()
    )
    assert crossings == []
    # The LOW-confidence 100x observation is excluded from peak
    # selection entirely -- the only remaining reliably-tradable
    # candidate at or after the baseline is the baseline itself (1x).
    peak = select_peak(snapshots, at_or_after=snapshots[0].observed_at)
    assert peak is not None
    assert peak.price_usd == Decimal("1.0")


def test_p2r4_unknown_confidence_baseline_is_skipped() -> None:
    """A baseline candidate with UNKNOWN confidence is skipped in favor
    of the next reliably-tradable observation -- never silently used."""
    snapshots = [
        _snap(0, "1.0", "1000", confidence="UNKNOWN"),
        _snap(1, "2.0", "2000", confidence="HIGH"),
    ]
    baseline = select_baseline(snapshots)
    assert baseline is not None
    assert baseline.price_usd == Decimal("2.0")


def test_p2r4_null_confidence_is_excluded_from_baseline_and_peak() -> None:
    snapshots = [
        _snap(0, "1.0", "1000", confidence=None),
        _snap(1, "50.0", "5000", confidence=None),
    ]
    assert select_baseline(snapshots) is None
    assert select_peak(snapshots, at_or_after=snapshots[0].observed_at) is None


def test_p2r4_medium_confidence_is_reliably_tradable() -> None:
    """MEDIUM (unlike LOW/UNKNOWN) is accepted -- the gate is a genuine
    two-tier cut, not "only HIGH ever counts"."""
    snapshots = [
        _snap(0, "1.0", "1000", confidence="MEDIUM"),
        _snap(1, "20.0", "5000", confidence="MEDIUM"),
    ]
    token_id = uuid.uuid4()
    crossings = compute_new_milestone_crossings(
        token_id=token_id, snapshots=snapshots, already_recorded_categories=frozenset()
    )
    assert {c.category for c in crossings} == {"MAJOR_WINNER", "MONSTER"}


def test_p2r4_high_confidence_peak_at_lower_price_beats_low_confidence_spike() -> None:
    """A genuine, reliably-observed 12x peak is still found even when a
    later, unreliable 100x "spike" observation is present and correctly
    ignored -- the fix narrows eligibility, it does not break detection
    of real crossings."""
    token_id = uuid.uuid4()
    snapshots = [
        _snap(0, "1.0", "1000", confidence="HIGH"),
        _snap(1, "12.0", "5000", confidence="HIGH"),
        _snap(2, "100.0", "50000", confidence="LOW"),
    ]
    crossings = compute_new_milestone_crossings(
        token_id=token_id, snapshots=snapshots, already_recorded_categories=frozenset()
    )
    assert {c.category for c in crossings} == {"MAJOR_WINNER"}
    for c in crossings:
        assert c.multiple_x == Decimal("12.000000")
        assert "LOW_CONFIDENCE_SNAPSHOTS_EXCLUDED" in (c.reason_codes or "")


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
