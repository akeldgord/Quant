# Real-chain fixture import evidence-file schema

Used by `argus fixtures import-real-chain --evidence-file <path>` and
`argus.golden_fixtures.import_real_chain_fixture_from_evidence_file`
(Phase 1 remediation round 5, findings #1/#2; `upstream_tree_attestation`
rewritten and `account_deltas` added by round 6, findings #2/#3). The
independent expectation and cryptographic provenance-binding schema is
too rich for individual CLI flags, so it is bundled as one JSON file
instead.

```json
{
  "category": "real_mainnet_example",
  "upstream_repo": "owner/repo",
  "upstream_commit": "<40-char immutable commit SHA>",
  "upstream_path_note": "free-text context: e.g. why this path/commit was chosen, "
                          "what transform the upstream repo's own convention requires",
  "upstream_tree_attestation": {
    "commit_sha": "<40-char commit SHA, resolved and self-verified by attest_git_tree>",
    "commit_object_b64": "<base64 of the raw git commit object's content>",
    "path": "path/at/that/commit.json",
    "path_components": ["path", "at", "that", "commit.json"],
    "tree_object_chain_b64": ["<base64 raw tree object>", "... one per path component, root-first"],
    "mode": "100644",
    "blob_sha1": "<git blob SHA-1 the path resolves to>",
    "captured_at": "<ISO8601, when attest_git_tree actually walked the repo>"
  },
  "upstream_license": {
    "spdx_id": "MIT",
    "path": "LICENSE",
    "tree_attestation": { "...": "same shape as upstream_tree_attestation, for the LICENSE file's own path" },
    "bytes_sha256": "<sha256 of the exact preserved license bytes>",
    "compatibility_decision": "free-text: why this license permits reuse of one immutable data file",
    "attribution": "free-text: required attribution/copyright notice"
  },
  "expectation": {
    "classification": "SWAP_SIMPLE",
    "is_copy_eligible": true,
    "wallet_perspective": {
      "wallet_address": "...",
      "method": "free-text: how this wallet's role was established"
    },
    "asset_deltas": [
      {
        "mint": "SOL",
        "account_context": null,
        "raw_amount": -1000000000,
        "decimals": 9,
        "ui_amount": "-1.000000000"
      }
    ],
    "account_deltas": [
      {
        "account_identifier": "<accountKeys[account_index], or the wallet address for the native-SOL row>",
        "account_index": 0,
        "owner": "<the wallet address that owns this account>",
        "mint": "SOL",
        "pre_raw_amount": 2000000000,
        "post_raw_amount": 1000000000,
        "net_raw_delta": -1000000000,
        "decimals": 9,
        "ui_delta": "-1.000000000"
      }
    ],
    "expected_input_mint": "SOL",
    "expected_input_amount_raw": 1000000000,
    "expected_output_mint": "<mint>",
    "expected_output_amount_raw": 500000000,
    "network_fee_raw": 5000,
    "transaction_failed": false,
    "expected_confidence": "1.000",
    "confidence_rule": "free-text: exact value or bounded rule + why",
    "reviewer": {
      "method": "free-text: how this was reviewed",
      "rationale": "free-text: semantic explanation of why this classification/eligibility is correct",
      "evidence_refs": ["https://...", "instruction name, program ID, etc."]
    }
  },
  "quarantine_reason": null
}
```

`quarantine_reason`: omit or `null` for a normal fixture (the parser's
observed output must match the expectation on every checked field, or
the import is refused). Set to a non-empty string to deliberately import
a known-divergent research fixture anyway -- it is recorded with
`quarantined: true`, always fails `validate-real-chain`, and never
counts as passing category coverage.

`asset_deltas` must list every asset the transaction moved for the named
wallet (not just the primary in/out leg), in the same order
`argus.parsing.generic_parser.compute_asset_deltas` returns them
(sorted by asset identifier) -- `import_real_chain_fixture` compares
them field-for-field.

`account_deltas` (Phase 1 remediation round 6, finding #3) must list
every *account*-level change the transaction produced for the named
wallet (never aggregated by mint -- two accounts of the same mint moving
differently must both appear as separate rows), in the same order
`argus.parsing.generic_parser.compute_account_level_deltas` returns them
(sorted by ``(account_index, mint)``) -- this is the oracle that actually
proves a multiple-token-account/LP-style transaction happened, since
`asset_deltas`'s by-mint aggregation can make two accounts of the same
mint moving in opposite directions net to zero and disappear entirely.

`upstream_tree_attestation`/the license's own `tree_attestation` must be
produced by `argus.golden_fixtures.attest_git_tree` against a local clone
of the upstream repository -- never hand-constructed. The offline
validator (`verify_git_object_chain`) independently recomputes every
git object ID from the preserved raw commit/tree object bytes and walks
`path_components` to confirm the declared path resolves to `blob_sha1`;
it proves Git object-chain *content* integrity, not that a particular
remote hostname actually served `commit_sha` -- that acquisition fact is
inherently online-only and is not claimed as an offline-proven property.
