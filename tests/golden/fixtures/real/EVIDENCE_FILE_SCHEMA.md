# Real-chain fixture import evidence-file schema

Used by `argus fixtures import-real-chain --evidence-file <path>` and
`argus.golden_fixtures.import_real_chain_fixture_from_evidence_file`
(Phase 1 remediation round 5, findings #1/#2). The new independent
expectation and cryptographic provenance-binding schema is too rich for
individual CLI flags, so it is bundled as one JSON file instead.

```json
{
  "category": "real_mainnet_example",
  "upstream_repo": "owner/repo",
  "upstream_commit": "<40-char immutable commit SHA>",
  "upstream_path_note": "free-text context: e.g. why this path/commit was chosen, "
                          "what transform the upstream repo's own convention requires",
  "upstream_tree_attestation": {
    "mode": "100644",
    "object_type": "blob",
    "blob_sha1": "<git blob SHA-1>",
    "path": "path/at/that/commit.json",
    "raw_ls_tree_line": "100644 blob <sha>\tpath/at/that/commit.json",
    "captured_at": "<ISO8601, when `git ls-tree` was actually run>"
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
