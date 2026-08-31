# Golden fixture provenance

Phase 1 remediation round 1 (`argus-phase-1-remediation-001`), finding #5:
the ACTIVE Phase 1 instruction required **sanitized real-chain** golden
transaction fixtures. Every fixture in this directory is instead
**synthetic**: hand-built to match the real Solana `getTransaction` JSON-RPC
response schema exactly (see `scripts/_generate_golden_fixtures.py`), not
captured from a live transaction.

**Why:** this sandbox has no general internet egress. Confirmed directly
and repeatedly across this project's work, most recently via the proxy's
own status endpoint, which reports an explicit gateway-level policy denial
for both a public Solana RPC endpoint and a market-data API:

```
recentRelayFailures:
  - host: api.mainnet-beta.solana.com:443
    detail: "gateway answered 403 to CONNECT (policy denial or upstream failure)"
  - host: api.dexscreener.com:443
    detail: "gateway answered 403 to CONNECT (policy denial or upstream failure)"
```

The environment's outbound allowlist (`noProxy`) covers only package
registries (npm, PyPI, crates.io, Go proxy) and Anthropic's own API
endpoints — no chain-data or market-data host is reachable from here. There
is no already-available safe source (no cached real-chain corpus ships
with this repository, no credential-free API this sandbox can reach) from
which authentic transaction signatures/payloads could be obtained.

Per the instruction's own explicit allowance: *"If network/credential
restrictions make acquisition impossible, do not fabricate provenance and
do not relabel synthetic data as real. Return PARTIAL with this criterion
NOT TESTED/blocked. Existing synthetic fixtures may remain as additional
unit fixtures but must be clearly labeled synthetic."* This file is that
label, applied to every fixture individually below rather than only in a
test-file docstring.

Acceptance criterion #15 ("all required authenticated real-chain golden
fixtures pass and their manifests/hash checks validate") is therefore
**NOT TESTED / blocked**, honestly, not claimed as PASS. All 23
golden-parser tests (`tests/golden/test_generic_parser.py`) still pass —
they validate the parser's own determinism and classification logic
against these synthetic-but-schema-accurate fixtures, which is real and
useful, but is not real-chain validation and must never be cited as such.

## Per-fixture record

Every entry: `capture_source: synthetic (hand-built, not captured from a
live transaction)`. `chain: solana`. No `transaction_signature`/`slot` are
real on-chain identifiers — the values inside each fixture are
placeholders chosen to exercise the parser deterministically, not to
resemble any real transaction.

| Fixture file | Required category | Expected classification | SHA-256 |
|---|---|---|---|
| `sol_to_token.json` | SOL to token | `SWAP_SIMPLE` | `87695f850a85be8fc8719de3868ad3a563d78d6b0071e49c349379b80f5cc749` |
| `token_to_sol.json` | token to SOL | `SWAP_SIMPLE` | `7719f972d8c8d1cff42b3ffc020e1b8f0d01f0792209fd1051ba90ebe25d1c93` |
| `token_to_usdc.json` | token to USDC | `SWAP_SIMPLE` | `e4938d2e0eafc0b03975d13e5b750f3ccd8ad83ab0222122a2203e11db679d54` |
| `multi_hop_swap.json` | multi-hop swap | `SWAP_COMPLEX` | `b2c502f74fe1fe42e0a0fbb982177f3eafb898d83d5d38c1d3abb0b4e7ade382` |
| `simple_transfer.json` | simple transfer | `TRANSFER_IN` | `d00ad2319fd2dbd128696ddf6935955bc40e88887420b8ac0cac313c8200a62d` |
| `partial_sell.json` | partial sell | `SWAP_SIMPLE` | `6fe1725344747c033ce987f7f6618e1ee53d2b4a5b64f6400224a1f92cd4906e` |
| `multiple_token_accounts_lp_add.json` | multiple token accounts | `LP_ACTION` | `af223a4ed6269d056ff631aaab77c26fa387940dfc68a31ab29e18c8f295c3fb` |
| `ambiguous_fee_payer_only.json` | ambiguous multi-asset transaction | `UNKNOWN` | `edd7209f9f857ee446d0510b19f420936b8f351a5722f7d13c2f3621ce5b4992` |
| `failed_transaction.json` | failed transaction | `UNKNOWN` | `91b74480c474cfbc412ce5da54c1e59b3338586460ca7d6d150464f8dc6a4d0c` |
| `transfer_out.json` | (extra, beyond the 9 required) | `TRANSFER_OUT` | `a8edee3ebf3ae6ba1fbf2757cfa796c1c60da6aa278bed05e4c009fb46120d68` |
| `token_create.json` | (extra, beyond the 9 required) | `TOKEN_CREATE` | `6d243ed0cccc1ff9686a5ec1e8e00698bf0e99ab143f864ef7374534f8e83fe8` |

The 9 required categories (SOL-to-token, token-to-SOL, token-to-USDC,
multi-hop swap, simple transfer, partial sell, multiple token accounts,
ambiguous multi-asset transaction, failed transaction) are all present;
`transfer_out.json`/`token_create.json` are additional fixtures exercising
the remaining two of the parser's 7 canonical classifications, kept for
unit-test coverage, equally synthetic.

SHA-256 values above are of the fixture file's exact current bytes
(`sha256sum tests/golden/fixtures/<name>.json`) — a mismatch means the
fixture changed since this manifest was written and this table must be
regenerated, per the same "golden fixture output changes must fail until
reviewed" discipline MASTER_SPEC.md section 21 requires of the parser
tests themselves.
