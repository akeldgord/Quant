"""Phase 1.5 historical-data feasibility spike (instruction argus-phase-1-5-001).

Reuses the existing deterministic Phase 1 parser
(``argus.parsing.generic_parser``) against real, GitHub-sourced Solana
mainnet transactions for one verified historical token and one verified
candidate wallet -- no ad-hoc interpretation path is created for this
spike, per the instruction's explicit requirement.

For each raw transaction this script independently recomputes, from the
raw evidence alone (never by calling into the parser), the tracked
wallet's net SOL and token balance deltas, then compares that
independent recomputation against ``compute_account_level_deltas()``'s
actual output -- this is Test C's "validate concrete interpretations
against raw transaction evidence" requirement, applied mechanically
across every transaction rather than hand-authored per fixture (this is
a spike, not a permanent golden-fixture corpus).

Run with: ``uv run python scripts/phase_1_5_feasibility.py``
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from argus.parsing.generic_parser import (  # noqa: E402
    compute_account_level_deltas,
    parse_transaction,
)

EVIDENCE_DIR = Path(__file__).resolve().parents[1] / "orchestration" / "phase_1_5" / "evidence"
RAW_DIR = EVIDENCE_DIR / "raw"
RESULTS_PATH = EVIDENCE_DIR / "analysis_results.json"

# The verified candidate wallet (Test B): 14 real transactions spanning
# openbook_v2/solend/lulo/meteora_dlmm, sourced from quellen-sol/ingestooor
# (GPL-3.0, commit 74e2039ec8dbc61bc5df1e08540ec5a3f3cd991e).
CANDIDATE_WALLET = "JAMESC37CTVoFEt7TAEcqBjdjAfAWZiPR1YdWotAFjeQ"

WALLET_FILES = [
    "wallet_01_openbook_v2_cancel_order.json",
    "wallet_02_solend_deposit.json",
    "wallet_03_solend_borrow.json",
    "wallet_04_solend_repay_all.json",
    "wallet_05_solend_withdraw_all.json",
    "wallet_06_solend_deposit_with_new_obligation_acc.json",
    "wallet_07_lulo_classic_deposit.json",
    "wallet_08_lulo_boosted_deposit.json",
    "wallet_09_lulo_boosted_withdraw.json",
    "wallet_10_lulo_boosted_withdraw_2.json",
    "wallet_11_lulo_claim.json",
    "wallet_12_meteora_dlmm_deposit.json",
    "wallet_13_meteora_dlmm_claim.json",
    "wallet_14_meteora_dlmm_withdraw_close_all.json",
]

# The verified historical token (Test A): a real pump.fun token creation
# event, whose own transaction bundles the creator's initial dev-buy,
# sourced from 0xjeffro/tx-parser (MPL-2.0, commit
# 475b1ebff79a2f41ec966919fdefa01f11f6c5d7).
TOKEN_MINT = "5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump"
TOKEN_CREATOR_WALLET = "6xo262KbDXepWbF3vPTrFXysr5vJwk3mozBXmXk3hmMx"
TOKEN_FILE = "token_00_pumpfun_create.json"

# Supplementary cross-validation material for Test C (not the Test B
# candidate wallet): a second real wallet, also sourced from
# quellen-sol/ingestooor at the same commit, used only to reach the
# instruction's >=20-interpretation floor honestly (14 candidate-wallet
# transactions + 1 token transaction = 15, short of 20) without
# inflating the count by decomposing single records into multiple
# artificial claims.
SUPPLEMENTARY_WALLET = "qUeL7JzC52V1DvvPkqnMd74QjThWtSJY5G1PkKv1ur7"
SUPPLEMENTARY_FILES = [
    "suppl_01_meteora_farms_stake.json",
    "suppl_02_flash_swap.json",
    "suppl_03_flash_swap2.json",
    "suppl_04_defituna_deposit_lend.json",
    "suppl_05_defituna_claim_pos_rewards.json",
    "suppl_06_kamino_account_creation.json",
    "suppl_07_spl_close_token_account.json",
    "suppl_08_jupiter_no_dooot.json",
    "suppl_09_xstep_full_stake_ix.json",
    "suppl_10_titan_swap_with_fees.json",
    "suppl_11_dflow_swap_with_fee.json",
    "suppl_12_kamino_klend_vaults.json",
    "suppl_13_titan_swap_with_fees_2.json",
]


def _load_raw(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    return data[0] if isinstance(data, list) else data.get("result", data)


def _account_keys(raw: dict[str, Any]) -> list[str]:
    keys = raw["transaction"]["message"]["accountKeys"]
    return [k["pubkey"] if isinstance(k, dict) else k for k in keys]


def _independent_recomputation(raw: dict[str, Any], wallet: str) -> dict[str, int]:
    """A from-scratch, independent re-derivation of the tracked wallet's
    net per-asset raw deltas directly from ``meta.preBalances``/
    ``postBalances``/``preTokenBalances``/``postTokenBalances`` -- written
    without calling any ``argus.parsing`` code, so agreement with
    ``compute_account_level_deltas()`` is a genuine cross-check against
    raw transaction evidence, not a tautology."""
    if raw["meta"].get("err") is not None:
        return {}
    keys = _account_keys(raw)
    meta = raw["meta"]
    deltas: dict[str, int] = {}

    if wallet in keys:
        idx = keys.index(wallet)
        delta = meta["postBalances"][idx] - meta["preBalances"][idx]
        if idx == 0:
            delta += meta.get("fee", 0)
        if delta != 0:
            deltas["SOL"] = deltas.get("SOL", 0) + delta

    pre_by_key: dict[tuple[int, str], int] = {}
    for entry in meta.get("preTokenBalances") or []:
        if entry.get("owner") == wallet:
            pre_by_key[(entry["accountIndex"], entry["mint"])] = int(
                entry["uiTokenAmount"]["amount"]
            )
    post_by_key: dict[tuple[int, str], int] = {}
    for entry in meta.get("postTokenBalances") or []:
        if entry.get("owner") == wallet:
            post_by_key[(entry["accountIndex"], entry["mint"])] = int(
                entry["uiTokenAmount"]["amount"]
            )
    for key in sorted(set(pre_by_key) | set(post_by_key)):
        _, mint = key
        d = post_by_key.get(key, 0) - pre_by_key.get(key, 0)
        if d != 0:
            deltas[mint] = deltas.get(mint, 0) + d

    return deltas


def _parser_reported_deltas(raw: dict[str, Any], wallet: str) -> dict[str, int]:
    combined: dict[str, int] = {}
    for row in compute_account_level_deltas(raw, wallet):
        combined[row.mint] = combined.get(row.mint, 0) + row.net_raw_delta
    return combined


def cross_validate_one(path: Path, wallet: str) -> dict[str, Any]:
    raw = _load_raw(path)
    independent = _independent_recomputation(raw, wallet)
    parser_reported = _parser_reported_deltas(raw, wallet)
    agrees = independent == parser_reported

    block_time = datetime.fromtimestamp(raw["blockTime"], tz=UTC) if raw.get("blockTime") else None
    parsed = parse_transaction(raw, wallet_address=wallet, slot=raw["slot"], block_time=block_time)
    sig = raw["transaction"]["signatures"][0]

    return {
        "file": path.name,
        "signature": sig,
        "slot": raw.get("slot"),
        "block_time": raw.get("blockTime"),
        "wallet": wallet,
        "independent_deltas": independent,
        "parser_reported_deltas": parser_reported,
        "agrees": agrees,
        "classification": parsed.classification,
        "confidence": str(parsed.confidence),
        "is_copy_eligible": parsed.is_copy_eligible,
    }


def main() -> None:
    start = time.monotonic()
    results = []

    token_result = cross_validate_one(RAW_DIR / TOKEN_FILE, TOKEN_CREATOR_WALLET)
    token_result["role"] = "token_creator_initial_buy"
    results.append(token_result)

    for filename in WALLET_FILES:
        r = cross_validate_one(RAW_DIR / filename, CANDIDATE_WALLET)
        r["role"] = "candidate_wallet_history"
        results.append(r)

    for filename in SUPPLEMENTARY_FILES:
        r = cross_validate_one(RAW_DIR / filename, SUPPLEMENTARY_WALLET)
        r["role"] = "supplementary_cross_validation"
        results.append(r)

    elapsed_seconds = time.monotonic() - start
    all_files = [TOKEN_FILE, *WALLET_FILES, *SUPPLEMENTARY_FILES]
    disk_bytes = sum((RAW_DIR / f).stat().st_size for f in all_files)

    disagreements = [r for r in results if not r["agrees"]]

    report = {
        "candidate_wallet": CANDIDATE_WALLET,
        "token_mint": TOKEN_MINT,
        "token_creator_wallet": TOKEN_CREATOR_WALLET,
        "supplementary_wallet": SUPPLEMENTARY_WALLET,
        "total_transactions_analyzed": len(results),
        "total_disagreements": len(disagreements),
        "elapsed_seconds": elapsed_seconds,
        "raw_evidence_disk_bytes": disk_bytes,
        "rpc_calls_made": 0,
        "provider_credits_consumed": 0,
        "results": results,
    }

    RESULTS_PATH.write_text(json.dumps(report, indent=2, default=str))

    print(f"Analyzed {len(results)} real transactions in {elapsed_seconds:.3f}s")
    print(f"Raw evidence: {disk_bytes} bytes across {len(results)} files")
    print(f"Disagreements between independent recomputation and parser: {len(disagreements)}")
    for r in results:
        print(
            f"  {r['file']:55s} slot={r['slot']:<10} "
            f"class={r['classification']:15s} agrees={r['agrees']} "
            f"eligible={r['is_copy_eligible']}"
        )
    if disagreements:
        print("\nDISAGREEMENTS:")
        for r in disagreements:
            print(
                f"  {r['file']}: independent={r['independent_deltas']} "
                f"parser={r['parser_reported_deltas']}"
            )
        sys.exit(1)


if __name__ == "__main__":
    main()
