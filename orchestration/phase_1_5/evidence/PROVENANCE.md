# Phase 1.5 historical-data feasibility spike -- evidence provenance

Instruction `argus-phase-1-5-001`. Every raw transaction below is a real,
independently-sourced Solana mainnet `getTransaction` response captured
by a third-party open-source project's own test suite (not this project),
cited here by upstream repository, exact commit, and file path -- the same
citation discipline used throughout `tests/golden/fixtures/real/`. This
evidence directory is spike-specific: it does not carry the full
tamper-evident Git-object-chain attestation machinery
(`GitTreeAttestation`/`verify_git_object_chain`) built for the permanent
Phase 1 golden-fixture corpus -- reproducibility here means: re-clone the
cited repository at the cited commit and confirm the cited path's bytes
match the file committed in this directory (a `git diff`/`sha256sum`
check any reviewer can run directly).

## Verified historical token (Test A)

- **Token mint:** `5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump`
- **Creator/first-buyer wallet:** `6xo262KbDXepWbF3vPTrFXysr5vJwk3mozBXmXk3hmMx`
- **Source:** `0xjeffro/tx-parser`, commit `475b1ebff79a2f41ec966919fdefa01f11f6c5d7`, path `solana/data/pumpfun_create_0.json`, license MPL-2.0
- **Signature:** `2s393PSYYxJJJfGiwHf18HZeC68nZs44ssbeB4aAkeYMyd1dyiiu3yVmGyRWZuArk5HzYDgVxYfhKLYd2CJ8kCBj`
- **Slot / blockTime:** `292743221` / `1727637145` (2024-09-29 per Unix epoch)
- **Parser classification:** `SWAP_SIMPLE` (confidence 1.000, copy-eligible=True)

## Verified candidate wallet (Test B)

- **Wallet:** `JAMESC37CTVoFEt7TAEcqBjdjAfAWZiPR1YdWotAFjeQ`
- **Source:** `quellen-sol/ingestooor`, commit `74e2039ec8dbc61bc5df1e08540ec5a3f3cd991e`, license GPL-3.0
- **14 real transactions:**

| # | File | Path in repo | Signature | Slot | Classification | Agrees |
|---|---|---|---|---|---|---|
| 1 | `wallet_01_openbook_v2_cancel_order.json` | `crates/parsers/tests/openbook_v2/cancel_order.json` | `5xXck5dUK3A5sdmrp6cNbG6z...` | 280407888 | TRANSFER_IN | True |
| 2 | `wallet_02_solend_deposit.json` | `crates/parsers/tests/solend/deposit.json` | `3E3mNyiwnmwagkoSkzBvgFuw...` | 341281881 | UNKNOWN | True |
| 3 | `wallet_03_solend_borrow.json` | `crates/parsers/tests/solend/borrow.json` | `5ssabqGvmbgFB42eonnaUhfG...` | 341282608 | TRANSFER_IN | True |
| 4 | `wallet_04_solend_repay_all.json` | `crates/parsers/tests/solend/repay_all.json` | `5mH1XYCnpDwLEuJUvFQdKT1H...` | 341299734 | TRANSFER_OUT | True |
| 5 | `wallet_05_solend_withdraw_all.json` | `crates/parsers/tests/solend/withdraw_all.json` | `4QZbHE9X5fN6nSwhYc1YAB3r...` | 341301632 | SWAP_SIMPLE | True |
| 6 | `wallet_06_solend_deposit_with_new_obligation_acc.json` | `crates/parsers/tests/solend/deposit_with_new_obligation_acc.json` | `37hYQAiGqqQGiofme4uUoKW2...` | 341307319 | UNKNOWN | True |
| 7 | `wallet_07_lulo_classic_deposit.json` | `crates/parsers/tests/lulo/classic_deposit.json` | `3e8emyP9JYwAqtoU6QdbrAVQ...` | 352171920 | TRANSFER_OUT | True |
| 8 | `wallet_08_lulo_boosted_deposit.json` | `crates/parsers/tests/lulo/boosted_deposit.json` | `XDWnZDjU8TguzQJidkUJHXXT...` | 352217568 | TRANSFER_OUT | True |
| 9 | `wallet_09_lulo_boosted_withdraw.json` | `crates/parsers/tests/lulo/boosted_withdraw.json` | `3kro28jpPysvqzERojTMbNJM...` | 352432543 | TRANSFER_OUT | True |
| 10 | `wallet_10_lulo_boosted_withdraw_2.json` | `crates/parsers/tests/lulo/boosted_withdraw_2.json` | `wJh9jamkb187meYbEe7HWtcE...` | 353522484 | TRANSFER_OUT | True |
| 11 | `wallet_11_lulo_claim.json` | `crates/parsers/tests/lulo/claim.json` | `2rAz9F5s5FsvpXSWdLCXVzGX...` | 353534112 | UNKNOWN | True |
| 12 | `wallet_12_meteora_dlmm_deposit.json` | `crates/parsers/tests/meteora_dlmm/deposit.json` | `5T2nrVwauDeh7C9B4VM7K8cV...` | 357905913 | UNKNOWN | True |
| 13 | `wallet_13_meteora_dlmm_claim.json` | `crates/parsers/tests/meteora_dlmm/claim.json` | `43rMxzRLSa7qL2Wk4szcVKtk...` | 357907147 | UNKNOWN | True |
| 14 | `wallet_14_meteora_dlmm_withdraw_close_all.json` | `crates/parsers/tests/meteora_dlmm/withdraw_close_all.json` | `4iVr1E6ocK98ehRcpEXF9eh9...` | 357908000 | UNKNOWN | True |

## Supplementary cross-validation wallet (Test C volume only)

- **Wallet:** `qUeL7JzC52V1DvvPkqnMd74QjThWtSJY5G1PkKv1ur7`
- **Source:** `quellen-sol/ingestooor`, commit `74e2039ec8dbc61bc5df1e08540ec5a3f3cd991e`, license GPL-3.0
- Used only to clear the instruction's >=20-interpretation floor for Test C
  honestly (14 candidate-wallet + 1 token transaction = 15, short of 20)
  without decomposing single records into artificial sub-claims -- **not**
  claimed as the Test B candidate wallet.

| # | File | Path in repo | Signature | Slot | Classification | Agrees |
|---|---|---|---|---|---|---|
| 1 | `suppl_01_meteora_farms_stake.json` | `crates/parsers/tests/meteora_farms/stake.json` | `41ZDdMHaSUBsTnQYPkdjee8C...` | 301195276 | TRANSFER_OUT | True |
| 2 | `suppl_02_flash_swap.json` | `crates/parsers/tests/flash/swap.json` | `5mpk4XBaCUgQA3ua3i86N48M...` | 337965929 | TRANSFER_OUT | True |
| 3 | `suppl_03_flash_swap2.json` | `crates/parsers/tests/flash/swap2.json` | `4LVJWC9NktubjCZF1Ev2tR28...` | 337966621 | SWAP_SIMPLE | True |
| 4 | `suppl_04_defituna_deposit_lend.json` | `crates/parsers/tests/defituna/deposit_lend.json` | `3a5F7hbAWGk2nST3XCdB4z7K...` | 346601948 | TRANSFER_OUT | True |
| 5 | `suppl_05_defituna_claim_pos_rewards.json` | `crates/parsers/tests/defituna/claim_pos_rewards.json` | `47pgkQL2BDTHwVaV5iE7kLDd...` | 346607556 | UNKNOWN | True |
| 6 | `suppl_06_kamino_account_creation.json` | `crates/parsers/tests/kamino/account_creation.json` | `rbGkY2BSZx72wPPt8k3sspx6...` | 350237570 | UNKNOWN | True |
| 7 | `suppl_07_spl_close_token_account.json` | `crates/parsers/tests/spl/close-token-account.json` | `2ufzYLFMZFJPXgenxY33k1EG...` | 361339132 | TRANSFER_IN | True |
| 8 | `suppl_08_jupiter_no_dooot.json` | `crates/parsers/tests/jupiter/no-dooot.json` | `BMRnQSJSdTPgD2A4sLcWYEwv...` | 363115966 | SWAP_SIMPLE | True |
| 9 | `suppl_09_xstep_full_stake_ix.json` | `crates/parsers/tests/xstep/full_stake_ix.json` | `3ZuwG45yBvuAFuQR1kCkhpuE...` | 370071836 | SWAP_SIMPLE | True |
| 10 | `suppl_10_titan_swap_with_fees.json` | `crates/parsers/tests/titan/titan_swap_with_fees.json` | `5jvAd6i4HQisk4JDw5Ljcy2r...` | 372075376 | SWAP_SIMPLE | True |
| 11 | `suppl_11_dflow_swap_with_fee.json` | `crates/parsers/tests/dflow/swap_with_fee.json` | `627zjqXdMpkogJFCxhcnVTtF...` | 372276140 | SWAP_SIMPLE | True |
| 12 | `suppl_12_kamino_klend_vaults.json` | `crates/parsers/tests/kamino/klend_vaults.json` | `2aZngDRaDSWb6vjjS9UzsP6C...` | 374021908 | TRANSFER_OUT | True |
| 13 | `suppl_13_titan_swap_with_fees_2.json` | `crates/parsers/tests/titan/swap_with_fees_2.json` | `5T4vmMjpZDRuVGKu4GHBrWGy...` | 375100669 | SWAP_SIMPLE | True |

## Summary

- Total real transactions analyzed: 28
- Disagreements (independent recomputation vs. parser): 0
- Elapsed processing time: 0.006s
- Raw evidence on disk: 926336 bytes
- RPC calls made: 0 (all evidence pre-captured by the upstream repositories; no live network fetch was performed by this spike)
- Provider credits consumed: 0
