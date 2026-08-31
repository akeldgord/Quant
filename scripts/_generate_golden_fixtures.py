#!/usr/bin/env python3
"""One-off generator for tests/golden/fixtures/*.json.

Not part of the ARGUS application -- a development-time helper only, run
once to produce the sanitized, synthetic Solana `getTransaction`-shaped
fixtures the golden parser tests load. These are hand-constructed to match
the real Solana JSON RPC transaction schema precisely (this sandbox has no
live network access to pull real transactions -- see docs/DECISION_LOG.md),
using well-known public constants (the wrapped-SOL mint, the real USDC
mint) plus fabricated wallet/counterparty/signature/mint values that are
clearly not real addresses.
"""

from __future__ import annotations

import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "tests" / "golden" / "fixtures"

WALLET = "GoLDeN1WaLLeTFixTuReAddreSSNoTReaL11111111"
COUNTERPARTY = "CounterPartyAccounTFixTuReNoTReaL111111111"
WSOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
TOKEN_A_MINT = "TokenAFixtureMintAddressNotReal1111111111"
TOKEN_B_MINT = "TokenBFixtureMintAddressNotReal1111111111"
TOKEN_C_MINT = "TokenCFixtureMintAddressNotReal1111111111"
NEW_TOKEN_MINT = "NewlyCreatedTokenMintFixtureNotReal111111"
NFT_MINT = "NonFungibleFixtureMintAddressNotReal11111"

# Phase 1.5 remediation round 1: real, independently-verified swap-venue
# program IDs (see argus.parsing.generic_parser._SUPPORTED_SWAP_PROGRAM_IDS)
# used to give the synthetic "known genuine swap" fixtures below the same
# positive instruction-level evidence a real swap transaction actually
# carries -- a fixture claiming to be a genuine, copy-eligible swap must
# now demonstrate that under the same rule production data does.
JUPITER_V6_PROGRAM = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
RAYDIUM_LP_V4_PROGRAM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"


def _account_keys(*extra: str) -> list[str]:
    return [WALLET, *extra]


def _swap_instruction(program_id: str) -> list[dict]:
    """A single top-level instruction invoking `program_id`, with no
    accounts/data content -- sufficient to positively identify the
    supported swap venue this fixture's raw evidence claims to have used,
    without fabricating opaque instruction data this generator has no way
    to make realistic."""
    return [{"programId": program_id, "accounts": [], "data": ""}]


def _tx(
    *,
    signature: str,
    slot: int,
    block_time: int,
    account_keys: list[str],
    pre_balances: list[int],
    post_balances: list[int],
    fee: int,
    pre_token_balances: list[dict],
    post_token_balances: list[dict],
    err: dict | None = None,
    instructions: list[dict] | None = None,
) -> dict:
    message: dict = {"accountKeys": account_keys}
    if instructions is not None:
        message["instructions"] = instructions
    return {
        "slot": slot,
        "blockTime": block_time,
        "transaction": {
            "signatures": [signature],
            "message": message,
        },
        "meta": {
            "err": err,
            "fee": fee,
            "preBalances": pre_balances,
            "postBalances": post_balances,
            "preTokenBalances": pre_token_balances,
            "postTokenBalances": post_token_balances,
        },
    }


def _tok(account_index: int, mint: str, owner: str, amount: str, decimals: int) -> dict:
    return {
        "accountIndex": account_index,
        "mint": mint,
        "owner": owner,
        "uiTokenAmount": {
            "amount": amount,
            "decimals": decimals,
            "uiAmount": int(amount) / (10**decimals),
        },
    }


FIXTURES: dict[str, dict] = {}

# 1. SOL to token: wallet spends 1.0 SOL (+ fee), receives 500 of TOKEN_A (6 decimals).
FIXTURES["sol_to_token"] = _tx(
    signature="golden-sol-to-token-0000000000000000000000",
    slot=100_000_001,
    block_time=1_735_000_001,
    account_keys=_account_keys(COUNTERPARTY),
    pre_balances=[5_000_000_000, 1_000_000_000],
    post_balances=[3_999_995_000, 2_000_000_000],
    fee=5000,
    pre_token_balances=[],
    post_token_balances=[_tok(0, TOKEN_A_MINT, WALLET, "500000000", 6)],
    instructions=_swap_instruction(JUPITER_V6_PROGRAM),
)

# 2. token to SOL: wallet spends 500 of TOKEN_A, receives ~1.0 SOL.
FIXTURES["token_to_sol"] = _tx(
    signature="golden-token-to-sol-0000000000000000000000",
    slot=100_000_002,
    block_time=1_735_000_002,
    account_keys=_account_keys(COUNTERPARTY),
    pre_balances=[3_000_000_000, 500_000_000],
    post_balances=[3_999_995_000, 0],
    fee=5000,
    pre_token_balances=[_tok(0, TOKEN_A_MINT, WALLET, "500000000", 6)],
    post_token_balances=[_tok(0, TOKEN_A_MINT, WALLET, "0", 6)],
    instructions=_swap_instruction(RAYDIUM_LP_V4_PROGRAM),
)

# 3. token to USDC: wallet spends 1000 of TOKEN_B, receives 250 USDC.
FIXTURES["token_to_usdc"] = _tx(
    signature="golden-token-to-usdc-000000000000000000000",
    slot=100_000_003,
    block_time=1_735_000_003,
    account_keys=_account_keys(COUNTERPARTY),
    pre_balances=[2_000_000_000, 1_000_000_000],
    post_balances=[1_999_995_000, 1_000_000_000],
    fee=5000,
    pre_token_balances=[_tok(0, TOKEN_B_MINT, WALLET, "1000000000", 6)],
    post_token_balances=[
        _tok(0, TOKEN_B_MINT, WALLET, "0", 6),
        _tok(0, USDC_MINT, WALLET, "250000000", 6),
    ],
    instructions=_swap_instruction(JUPITER_V6_PROGRAM),
)

# 4. multi-hop swap: wallet spends SOL, TOKEN_A decreases too (routed through an
#    intermediate leg), receives TOKEN_C -- multiple assets moved on both sides.
FIXTURES["multi_hop_swap"] = _tx(
    signature="golden-multi-hop-0000000000000000000000000",
    slot=100_000_004,
    block_time=1_735_000_004,
    account_keys=_account_keys(COUNTERPARTY),
    pre_balances=[5_000_000_000, 1_000_000_000],
    post_balances=[4_499_995_000, 2_000_000_000],
    fee=5000,
    pre_token_balances=[_tok(0, TOKEN_A_MINT, WALLET, "200000000", 6)],
    post_token_balances=[
        _tok(0, TOKEN_A_MINT, WALLET, "0", 6),
        _tok(0, TOKEN_C_MINT, WALLET, "750000000", 6),
    ],
)

# 5. simple transfer: wallet receives 2.0 SOL from a counterparty, wallet is not
#    the fee payer (counterparty pays the fee).
FIXTURES["simple_transfer"] = _tx(
    signature="golden-simple-transfer-00000000000000000000",
    slot=100_000_005,
    block_time=1_735_000_005,
    account_keys=[COUNTERPARTY, WALLET],
    pre_balances=[3_000_000_000, 1_000_000_000],
    post_balances=[995_000, 3_000_000_000],
    fee=5000,
    pre_token_balances=[],
    post_token_balances=[],
)

# 6. partial sell: wallet holds 1000 of TOKEN_A, sells only 300 of it for SOL,
#    keeping 700 -- same shape as #2 but demonstrates a partial-balance close.
FIXTURES["partial_sell"] = _tx(
    signature="golden-partial-sell-0000000000000000000000",
    slot=100_000_006,
    block_time=1_735_000_006,
    account_keys=_account_keys(COUNTERPARTY),
    pre_balances=[3_000_000_000, 500_000_000],
    post_balances=[3_599_995_000, 200_000_000],
    fee=5000,
    pre_token_balances=[_tok(0, TOKEN_A_MINT, WALLET, "1000000000", 6)],
    post_token_balances=[_tok(0, TOKEN_A_MINT, WALLET, "700000000", 6)],
    instructions=_swap_instruction(RAYDIUM_LP_V4_PROGRAM),
)

# 7. multiple token accounts (LP add): wallet gives up TOKEN_A and TOKEN_B
#    together, no offsetting asset received -- liquidity-add pattern.
FIXTURES["multiple_token_accounts_lp_add"] = _tx(
    signature="golden-lp-add-00000000000000000000000000000",
    slot=100_000_007,
    block_time=1_735_000_007,
    account_keys=_account_keys(COUNTERPARTY),
    pre_balances=[3_000_000_000, 1_000_000_000],
    post_balances=[2_999_995_000, 1_000_000_000],
    fee=5000,
    pre_token_balances=[
        _tok(0, TOKEN_A_MINT, WALLET, "500000000", 6),
        _tok(0, TOKEN_B_MINT, WALLET, "300000000", 6),
    ],
    post_token_balances=[
        _tok(0, TOKEN_A_MINT, WALLET, "200000000", 6),
        _tok(0, TOKEN_B_MINT, WALLET, "100000000", 6),
    ],
)

# 8. ambiguous multi-asset transaction: wallet is only the fee payer of a
#    transaction that doesn't otherwise touch its own balances (e.g. relaying
#    a swap between two other parties) -- after fee adjustment there is no
#    wallet-relevant delta at all, so this must be UNKNOWN, not guessed at.
FIXTURES["ambiguous_fee_payer_only"] = _tx(
    signature="golden-ambiguous-00000000000000000000000000",
    slot=100_000_008,
    block_time=1_735_000_008,
    account_keys=_account_keys(COUNTERPARTY),
    pre_balances=[1_000_000_000, 500_000_000],
    post_balances=[999_995_000, 500_000_000],
    fee=5000,
    pre_token_balances=[],
    post_token_balances=[],
)

# 9. failed transaction: an on-chain error is recorded; wallet still paid the
#    fee, but no swap semantics should ever be inferred.
FIXTURES["failed_transaction"] = _tx(
    signature="golden-failed-tx-000000000000000000000000000",
    slot=100_000_009,
    block_time=1_735_000_009,
    account_keys=_account_keys(COUNTERPARTY),
    pre_balances=[1_000_000_000, 500_000_000],
    post_balances=[999_995_000, 500_000_000],
    fee=5000,
    pre_token_balances=[],
    post_token_balances=[],
    err={"InstructionError": [0, "Custom slippage tolerance exceeded"]},
)

# Extra (not in the mandatory 9, but exercises the two remaining
# classifications so all 7 are covered somewhere in the golden suite).
FIXTURES["transfer_out"] = _tx(
    signature="golden-transfer-out-0000000000000000000000",
    slot=100_000_010,
    block_time=1_735_000_010,
    account_keys=_account_keys(COUNTERPARTY),
    pre_balances=[2_000_000_000, 500_000_000],
    post_balances=[999_995_000, 1_500_000_000],
    fee=5000,
    pre_token_balances=[],
    post_token_balances=[],
)

FIXTURES["token_create"] = _tx(
    signature="golden-token-create-0000000000000000000000",
    slot=100_000_011,
    block_time=1_735_000_011,
    account_keys=_account_keys(COUNTERPARTY),
    pre_balances=[1_000_000_000, 500_000_000],
    post_balances=[997_961_120, 500_000_000],  # paid rent-exemption + fee
    fee=5000,
    pre_token_balances=[],
    post_token_balances=[_tok(0, NEW_TOKEN_MINT, WALLET, "0", 6)],
)

# 12. genuinely ambiguous multi-asset transaction (Phase 1 remediation
#     round 5, finding #4): wallet receives a native-SOL rent refund AND
#     an unrelated token release in the same instruction, with nothing
#     given up -- structurally identical to the real DCA-order-close case
#     this project's real-chain fixtures already document. Two distinct
#     assets inflow together must be UNKNOWN, never a confident TRANSFER_IN
#     that silently picks the larger leg.
FIXTURES["ambiguous_multi_asset_dual_inflow"] = _tx(
    signature="golden-ambiguous-multi-asset-00000000000000",
    slot=100_000_012,
    block_time=1_735_000_012,
    account_keys=[COUNTERPARTY, WALLET],  # wallet is NOT the fee payer (index 0)
    pre_balances=[3_000_000_000, 500_000_000],
    post_balances=[2_994_995_000, 1_000_000_000],  # wallet: +0.5 SOL exactly
    fee=5000,
    pre_token_balances=[_tok(1, TOKEN_A_MINT, WALLET, "0", 6)],
    post_token_balances=[_tok(1, TOKEN_A_MINT, WALLET, "100000000", 6)],
)

# 13. NFT purchase (decimals == 0): wallet spends SOL, receives exactly one
#     unit of a non-fungible (decimals=0) mint -- a "clean" one-for-one
#     balance-delta shape identical to an ordinary fungible SWAP_SIMPLE,
#     but must never be automatically copy-eligible (Phase 1 remediation
#     round 5, finding #4).
FIXTURES["nft_purchase_decimals_zero"] = _tx(
    signature="golden-nft-purchase-000000000000000000000000",
    slot=100_000_013,
    block_time=1_735_000_013,
    account_keys=_account_keys(COUNTERPARTY),
    pre_balances=[5_000_000_000, 1_000_000_000],
    post_balances=[2_999_995_000, 3_000_000_000],  # spent 2.0 SOL + fee
    fee=5000,
    pre_token_balances=[],
    post_token_balances=[_tok(0, NFT_MINT, WALLET, "1", 0)],
)

# 14. Phase 1.5 remediation round 1 -- the exact false-positive shape the
#     positive semantic proof gate exists to close: a clean one-asset-out/
#     one-asset-in balance delta (identical in shape to #1-#3 above) whose
#     only instruction invokes a program that is NOT in
#     _SUPPORTED_SWAP_PROGRAM_IDS (a fictitious "lending market" program,
#     standing in for a real Solend/xStep-shaped non-trade action). Must
#     stay SWAP_SIMPLE (the balance shape genuinely is a clean one-for-one
#     move -- the classifier has no reason to doubt that) but must never
#     be copy eligible without positive trade-venue evidence.
FIXTURES["one_for_one_unsupported_program"] = _tx(
    signature="golden-unsupported-program-000000000000000000",
    slot=100_000_014,
    block_time=1_735_000_014,
    account_keys=_account_keys(COUNTERPARTY),
    pre_balances=[3_000_000_000, 1_000_000_000],
    post_balances=[1_999_995_000, 1_000_000_000],
    fee=5000,
    pre_token_balances=[],
    post_token_balances=[_tok(0, TOKEN_A_MINT, WALLET, "500000000", 6)],
    instructions=_swap_instruction("FictitiousLendingMarketProgramNotARealDexNotReal11"),
)

# 15. Same false-positive shape as #14, but with no `instructions` field at
#     all (the exact raw shape every synthetic fixture above #1-#13 used
#     to have, and the shape v1's defect actually manifested on with real
#     Solend/xStep evidence, which likewise offers no top-level swap-venue
#     instruction the wallet's own action is the primary one). Proves the
#     gate fails closed on *absence* of evidence, not only on a
#     *mismatched* program.
FIXTURES["one_for_one_no_instruction_evidence"] = _tx(
    signature="golden-no-instruction-evidence-0000000000000",
    slot=100_000_015,
    block_time=1_735_000_015,
    account_keys=_account_keys(COUNTERPARTY),
    pre_balances=[3_000_000_000, 1_000_000_000],
    post_balances=[1_999_995_000, 1_000_000_000],
    fee=5000,
    pre_token_balances=[],
    post_token_balances=[_tok(0, TOKEN_B_MINT, WALLET, "500000000", 6)],
)


def main() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    for name, tx in FIXTURES.items():
        path = FIXTURES_DIR / f"{name}.json"
        path.write_text(json.dumps(tx, indent=2, sort_keys=True) + "\n")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
