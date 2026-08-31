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
