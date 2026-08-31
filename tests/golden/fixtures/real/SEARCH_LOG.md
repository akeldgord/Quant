# Real-chain fixture search log -- Phase 1 remediation round 2, finding #12

Hand-written, not tool-managed (unlike `PROVENANCE.md`/`provenance.json`,
which `argus fixtures import-real-chain` regenerates on every import --
this file is never overwritten by that command). Records the actual
search process this round, so the honest PARTIAL/NOT-TESTED disposition
below is independently verifiable rather than asserted.

## What this sandbox can and cannot reach

Confirmed directly this round:

- **GitHub read access works.** `git clone` (anonymous, via this
  session's proxy) succeeds against public GitHub repositories --
  contrary to round 1's finding, which only tested raw chain-data/market-
  data hosts.
- **General RPC egress is still blocked.** `curl -X POST
  https://api.mainnet-beta.solana.com -d '{"jsonrpc":"2.0","id":1,
  "method":"getVersion"}'` fails with `CONNECT tunnel failed, response
  403` -- a proxy-level policy denial, not a transient failure. The
  `orchestration-managed` `__agentproxy/status` endpoint's `noProxy`
  allowlist covers only package registries and Anthropic's own API, same
  as round 1.

This matches the round 2 instruction's own premise exactly ("The sandbox
can access GitHub even though general RPC egress is blocked") and is why
the import command (`argus.golden_fixtures`) is deliberately offline: it
can validate/register a payload some other, network-enabled host
captured, but can never capture one itself from here.

## Repositories checked

| Repository | Commit checked | License | Result |
|---|---|---|---|
| `solana-labs/solana-web3.js` | `5b4e63daed1561ce58585a639041732c04aa354a` | MIT | `test/connection.test.ts` embeds hand-built `mockRpcResponse` objects (placeholder account keys like `va12u4o9DipLEB2z4fuoHszroq1U9NcAB9aooFDPJSf` from a local test-validator run) -- not real captured data; would fail "do not invent a signature or claim authenticity from payload shape alone". No usable fixture. |
| `solana-labs/explorer` | `f144a3103cb9cb4df66616f40fb80b317f44dc86` | MIT | **Usable.** `app/entities/transfer-instruction/__fixtures__/` embeds complete, real `getTransaction` JSON-RPC responses (full envelope: `{"jsonrpc","result","id"}`), with the repo's own `load-fixture.ts` explicitly typing/naming them `mainnet-*` vs `devnet-*`/`surfpool-*` (a local-validator tool) -- the upstream project's own provenance labeling, not an inference from payload shape alone. 4 fixtures imported from here (see table below). |
| `michaelhly/solana-py` | `c9ea54166f605b39caa858093fcc9b06be81d99f` | MIT | `tests/fixture_accounts.py` is account fixtures, not transactions; `tests/integration/*` fetch live from a real cluster at test-run time (no embedded bytes). No usable fixture. |
| `helius-labs/helius-sdk` | `c4b0322c12a07affe5b23a9043f99a564a126ddb` | (not checked -- no fixture found) | Only 2 JSON files in the whole repo (`typedoc.json`, `.eslintrc.json`); no embedded transaction data. No usable fixture. |
| `debridge-finance/solana-tx-parser-public` | `ff51fa9df0b7e75995f8baed0ec65255b911eab8` | LGPL-2.1 | Tests fetch live via `connection.getTransaction(signature)` using real signatures (e.g. `4U9MhiLjCLXwi8q2mC7NrejGGkCExTuo8ibUm2xHG5qu6BiVeDaLieZkxKnusJY7fUH2LTqPL6E23pxpkJQusKdn`, a real mainnet swap+order transaction per `tests/parseLogs.test.ts`) -- no embedded payload bytes to import, and the license is copyleft (skipped even if bytes had been present, to stay unambiguously on the safe side of "license permits reuse"). No usable fixture from this sandbox, though the signature itself is a legitimate lead for a future network-enabled capture. |
| `anza-xyz/agave` | `f33a3f3bad4906439eebb17f6cc2d1c496961c05` | Apache-2.0 | Sparse-checked out `transaction-status`/`rpc`/`rpc-client-api` (a full clone of this monorepo was avoided as impractical at this sandbox's bandwidth/time budget). Zero `.json` files in any of the three -- the crate's own tests build `EncodedTransaction`/`UiTransactionStatusMeta` structs programmatically in Rust, never from fixture files. No usable fixture. |

Repos considered but not reachable this round: `shyft-to/solana-transaction-parser`
(the `add_repo` tool rejected it with "cross-tier adds are not supported
in v1" -- inconclusive as to whether the repo exists under that exact
name; not retried under a different name given the time already spent).

## What was imported

4 fixtures, all from `solana-labs/explorer`, all genuinely captured
mainnet transactions (see `PROVENANCE.md` for full per-fixture
provenance -- signature, slot, hashes, license, exact upstream path):

| `argus fixtures` category | Real signature | Satisfies which round 1 required category |
|---|---|---|
| `real_mainnet_sol_transfer_single` | `2kHbPUGzehenUXQbBfAVZGcuTrSUVDMEyU2aGcjFbuUAJkG28CyQPCGZF68u369MU7WHMvJboyioqyihvtR75nLn` | "simple transfer", sender's (TRANSFER_OUT) perspective |
| `real_mainnet_sol_transfer_received` | same signature, receiver's perspective | "simple transfer", receiver's (TRANSFER_IN) perspective |
| `real_mainnet_sol_transfer_multi` | `2msqMqeUTTZhgite3PvWSLJhZJ3m4v4UMbDAcXymTPpXwKM5PcKfZFfxn4izZ2UTZmngYJeWSf1ztdD6kdeDkdbr` | partial support for "multiple token accounts" in spirit only (multiple SOL transfers to different destinations in one transaction) -- **not** claimed as satisfying it: the required category is about multiple *token* accounts (an LP-style action), and this is a plain multi-recipient SOL transfer. Kept as an additional TRANSFER_OUT real-chain data point, not mapped to a required category. |
| `real_mainnet_usdc_transfer` | `4LXpF3MCdp69iFmD27Sn812UNpqFPHM4qXH7Y12E964p9GHXvwMe1XEmyasogVT2N4XEctdQQLf1sHY6Gvsa5sFX` | a real SPL-token (USDC, the same mint this project already treats as canonical) transfer -- **not** a swap, so does **not** satisfy "token-to-USDC" (that category means a DEX swap output, not a plain token transfer); kept as an additional real-chain TRANSFER_OUT data point over a non-SOL asset. |

## What remains NOT TESTED, and why

The remaining round 1 required categories -- SOL-to-token swap,
token-to-SOL swap, token-to-USDC swap, multi-hop swap, partial sell,
multiple token accounts (LP action), ambiguous multi-asset transaction,
failed transaction -- were **not** sourced this round. Every repository
searched that plausibly could contain them either fetches live from RPC
(no embedded bytes to import without egress this sandbox doesn't have)
or has no fixture files at all. None of the repos checked are DEX/AMM
program repositories (Jupiter, Raydium, Orca) or a general-purpose
indexer with a committed real-swap-transaction test corpus; that is the
next place to look, not yet checked, if this search continues.

Per the round 2 instruction's own explicit allowance: *"If a category
cannot be sourced and independently supported from GitHub evidence,
leave it NOT TESTED and return PARTIAL."* This is that outcome, honestly
recorded, for these 8 of 9 required categories -- not claimed as PASS,
and no signature or payload was invented for any of them.

## For a future network-enabled host

`argus fixtures import-real-chain --input <captured.json> --category
<name> --upstream-repo <owner/repo> --upstream-commit <sha>
--upstream-path <path-or-note> --upstream-license <spdx>
[--wallet-address <addr>]` validates, canonicalizes, and records
provenance for one payload already captured elsewhere -- it never makes
a network call itself. `argus fixtures validate-real-chain` re-verifies
every currently-imported fixture's hash and parser output against what
was recorded at import time. Concrete next step: capture
`getTransaction` for the debridge-finance swap signature above (a real,
already-traceable lead), plus any Jupiter/Raydium/Orca-parsing repo's
own committed test transactions, and run them through this same command.

## Round 3 search (argus-phase-1-remediation-003, finding #1)

Continues directly from round 2's own "concrete next step" above: this
round specifically targeted DEX/AMM program repositories and
general-purpose transaction-parser/indexer repositories for committed
real `getTransaction` fixtures, which round 2 had not yet checked.

### Repositories checked

| Repository | Commit checked | License | Result |
|---|---|---|---|
| `raydium-io/raydium-sdk` | (shallow clone, HEAD at check time) | (not reached -- no fixture found) | No JSON files or any other file embedding `preBalances`/`postTokenBalances`/`preTokenBalances` anywhere in the repo. Program-interaction SDK, not a transaction-history/parser test corpus. No usable fixture. |
| `orca-so/whirlpools` | (shallow clone, HEAD at check time) | (not reached -- no fixture found) | `tests/utils/fixture.ts`, `tests/utils/litesvm.ts`, `tests/utils/mockRpc.ts` exist but build synthetic on-chain state via `litesvm` (an in-process local-validator simulator) or hand-constructed mock RPC responses -- never embed a real captured `getTransaction` payload. No usable fixture. |
| `Ellipsis-Labs/phoenix-sdk` | (shallow clone, HEAD at check time) | (not reached -- no fixture found) | No balance-shaped fixture files anywhere in the repo. No usable fixture. |
| `openbook-dex/program` | (shallow clone, HEAD at check time) | (not reached -- no fixture found) | No balance-shaped fixture files anywhere in the repo. No usable fixture. |
| `MeteoraAg/dlmm-sdk` | (shallow clone, HEAD at check time) | (not reached -- no fixture found) | `commons/tests/fixtures/<pubkey>/*.bin` exist, but are raw per-account state snapshots (`lb_pair.bin`, `reserve_x.bin`, `bin_array_*.bin`, etc.) for on-chain account *state*, not `getTransaction` responses -- no transaction envelope, no signature, no meta/preBalances at all. No usable fixture. |
| `franco-bianco/solanaswap-go` | (shallow clone, HEAD at check time) | (not reached -- no fixture found) | No balance-shaped fixture files anywhere in the repo. No usable fixture. |
| `cxcx-ai/solana-dex-parser` | (shallow clone, HEAD at check time) | (not reached -- no fixture found) | No balance-shaped fixture files anywhere in the repo. No usable fixture. |
| `kiyoshi-work/solana-wallet-analyzer` | (shallow clone, HEAD at check time) | (not reached -- no fixture found) | No balance-shaped fixture files anywhere in the repo. No usable fixture. |
| `jup-ag/jupiter-core` | n/a | n/a | Repository does not exist under that name (clone rejected outright, not merely empty). Not retried under a different name. |
| **`0xjeffro/tx-parser`** | **`475b1ebff79a2f41ec966919fdefa01f11f6c5d7`** | **MPL-2.0** | **Usable.** `solana/data/` contains 26 real, complete `getTransaction`-shaped JSON files (each a single-element JSON array wrapping one genuine captured response -- `blockTime`/`meta`/`slot`/`transaction`/`version`, real base58 signatures, real slots, real `preTokenBalances`/`postTokenBalances`), covering Jupiter Aggregator V6 (`Route` and `sharedAccountsRoute` instructions), Raydium Liquidity Pool V4 swaps, pump.fun buy/sell/create, OKX DEX aggregator swaps, and Jupiter DCA order open/close. Directly named after the exact program instruction each captures -- the repository's own naming, not an inference from payload shape. 6 fixtures imported from here (see table below). |

License note on MPL-2.0: a weak, file-level copyleft (unlike the LGPL
repository round 2 skipped out of caution) -- reusing an individual data
file verbatim, with full attribution (upstream repo, exact immutable
commit, exact path, license) recorded in `provenance.json`/
`PROVENANCE.md` exactly as done here, is squarely within its terms. No
source code from the upstream repository is used, modified, or
redistributed -- only immutable, already-public on-chain transaction
bytes the repository itself captured and committed.

Every file in `0xjeffro/tx-parser`'s `solana/data/` is a **JSON array
containing exactly one element** (`[{...}]`), not the bare object
`argus fixtures import-real-chain` expects -- this is the upstream
repository's own Go test-fixture-loading convention, not a shape this
project invented. Each imported payload was mechanically unwrapped
(`json.load(...)[0]`, re-serialized) before being passed to
`--input`; this changes zero bytes of the actual captured transaction
data and is recorded verbatim in each fixture's `--upstream-path` note.

Also checked in this repository and explicitly **not** usable:
`broken_data_0.json` (the literal string `"This is a broken data
file"` -- the upstream repo's own malformed-API-response test case, not
chain data at all) and `broken_data_1.json` (a real transaction, but
with `meta.err = null` like every other fixture in the directory --
despite its filename, not an on-chain-failed transaction). A full sweep
of every JSON file's `meta.err` field across the entire `solana/data/`
directory found zero transactions with a non-null `err` -- **no failed-
transaction fixture exists in this repository.**

### What was imported

6 new fixtures, all from `0xjeffro/tx-parser` (see `PROVENANCE.md` for
full per-fixture provenance):

| `argus fixtures` category | Real signature | Satisfies which required category |
|---|---|---|
| `real_mainnet_sol_to_token_swap` | `4U8kypMuCUCkR6teu2Vn8ujaEJUR3dcUU5QExZxSMMeJ5fRTvYfWs5M5AB9yNjjHKAQ4w433QVyUivc3Pp8gvG1R` | "SOL to token swap" -- pump.fun buy; signer's native SOL decreases (~3.08 SOL, the purchase + fee), a brand-new SPL token balance appears. Parser: `SWAP_SIMPLE` (1.000). |
| `real_mainnet_token_to_sol_swap` | `3aQZsNRUbNXpH54GQEaxFpWZsmL554cYGGtWqqoypz8b6LUDYprbRd9AwgivXRLtFBYCU6MU6e9ANurwP8dCMV6` | "token to SOL swap" -- Raydium Liquidity Pool V4 swap; signer's SPL token balance goes to exactly zero (full liquidation), native SOL increases. Parser: `SWAP_SIMPLE` (1.000). |
| `real_mainnet_token_to_usdc_swap` | `rNMFZpBmbr6R8g4hStbC5qAictmWvGFQVTwQyXoCY6QDrcq9UV2QfHJ6oARNuS1VaUh3HVe799CDn44dWQReAye` | "token to USDC swap" -- Jupiter `sharedAccountsRoute`; signer's SPL token balance goes to zero, real USDC mint (`EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`) balance increases by ~47.46. Parser: `SWAP_SIMPLE` (1.000). |
| `real_mainnet_multi_hop_swap` | `51SfoFAgv3nxEaajLFPCcQpnYaqoLdfZh3ZBWGdNB6c4VSRLcfNzxTnK77ggbsR5HjhDzakQsy35uFZg8KtFAkSj` | "multi-hop swap" -- Jupiter Aggregator V6's `sharedAccountsRoute` instruction, Jupiter's own multi-hop routing mechanism; the transaction touches 4 distinct mints (wSOL, USDC, an intermediate SPL token, and the ORE token), not just an input/output pair. Parser: `SWAP_COMPLEX` (0.700) -- correctly lower-confidence than a clean two-asset swap, reflecting the genuine multi-asset complexity. |
| `real_mainnet_partial_sell` | `2XgzfkWeDeua4oemWXrj3JzhxVsV4mGsqVZfETSbhn6hGFuLvi2fjdK2TGcmuQQnZSEjUmMmPjUnCFWDebGJcgWQ` | "partial sell" -- Raydium Liquidity Pool V4 swap; signer's SPL token balance decreases by ~1% of a much larger holding (2,225,434.28 -> 2,203,179.94), receiving SOL in return, while retaining the large majority of the position -- a genuine partial, not full, liquidation. Parser: `SWAP_SIMPLE` (1.000). |
| `real_mainnet_ambiguous_multi_asset` | `5EZNycMMgz8k1RNxVPxoMB2pCh97qUZ9R4PoxbgGvigsM26poK2AHSXYdHUetWKzsP7QchVfBPixqzwx2HULaSpb` | "ambiguous multi-asset transaction" -- a Jupiter DCA `CloseDca` order-close; the signer receives **two independent, simultaneous asset inflows** (a native-SOL rent refund from a closed program account, and a released escrowed SPL token balance) with **no counter-asset given up** in this instruction -- structurally distinct from a two-sided swap (one asset out, one in) or a plain transfer (one asset, one direction), and exactly the kind of genuinely multi-asset, non-swap on-chain event this category is meant to exercise. **Recorded transparently, not overclaimed**: this project's own parser classifies it as `TRANSFER_IN` at confidence 1.000, not `UNKNOWN` -- the *transaction* is honestly multi-asset and ambiguous in structure (a naive two-asset-delta swap heuristic could easily misread it as a swap), but the parser resolves it decisively rather than flagging it as unresolved; both facts are recorded here and in `PROVENANCE.md`'s `expected classification` field exactly as the parser actually produced, per this category's own requirement to record genuine parser output, not an invented one. |

Two more `0xjeffro/tx-parser` candidates were evaluated as possible
"ambiguous multi-asset" fixtures and rejected before the one above was
chosen, specifically because the real parser resolved them *confidently*
to an ordinary classification rather than exhibiting any genuine
ambiguity: `jupiterDca_openDcaV2_0.json` (a single-asset escrow deposit,
`TRANSFER_OUT` at 1.000) and `OKXDEX_commissionSplProxySwap.json` (a
three-mint aggregator swap, `SWAP_COMPLEX` at 0.700 -- indistinguishable
in kind from the multi-hop fixture already imported). Neither was
imported.

### What remains NOT TESTED, and why

Two of the original eight remaining categories are still NOT TESTED
after this round's search:

- **multiple token-account / LP-style action** -- every DEX/AMM repository
  checked this round tests liquidity actions (`increaseLiquidity`,
  `decreaseLiquidity`, add/remove-liquidity instructions) exclusively
  against synthetic local-validator state (`litesvm`, hand-built mock
  RPC responses, or raw per-account `.bin` state snapshots with no
  transaction envelope at all) -- never a captured `getTransaction`
  response for an actual liquidity-provision transaction. None of the
  swap-focused fixtures found in `0xjeffro/tx-parser` are an LP action
  (all are swaps, transfers, or DCA order operations).
- **failed transaction** -- confirmed NOT present anywhere in
  `0xjeffro/tx-parser`'s entire fixture directory (every `meta.err` is
  `null`), and no other repository checked this round or in round 2
  embeds real transaction bytes at all, let alone a failed one.

Per the round 3 instruction's own explicit allowance: *"If a category
still cannot be authenticated from available evidence, leave it NOT
TESTED and return PARTIAL."* This is that outcome, honestly recorded,
for these 2 of 8 categories that were still open going into this round
-- not claimed as PASS, and no signature or payload was invented for
either. The checkpoint's overall status remains `PARTIAL`.

### For a future network-enabled host (unchanged)

The debridge-finance signature and any DEX/AMM program's own
liquidity-action integration tests (which fetch live from a real cluster
at test-run time rather than embedding bytes) remain legitimate leads
for a host with real RPC egress to capture and feed through
`argus fixtures import-real-chain`, closing the two remaining gaps
above.
