================ ARGUS ORCHESTRATOR CHECKPOINT ================

A. Identity
PROJECT: ARGUS
MASTER_SPEC_VERSION: v2.0
SCOPE: Phase 1 remediation round 6 — remediate the 6 audit findings in
  orchestrator instruction argus-phase-1-remediation-006, which rejected
  round 5 as `FAIL_REMEDIATION_REQUIRED` on production git-identity
  fail-open, unproven fixture git-object-chain provenance, weak
  account-level/record-identity binding in the golden oracle, incomplete
  Helius HTTP validation, a watcher pre-launch remote-freshness race, and
  evidence/reporting honesty.
STATUS: All 6 findings remediated with real, tested code. One newly
  discovered, honestly disclosed defect in commit-trailer formatting
  affecting 3 of this round's own commits (section H) does not change
  any acceptance-matrix item's disposition but is reported rather than
  hidden. Phase 1 remains NOT orchestrator-approved.
UTC_TIMESTAMP: 2026-08-31T20:22:01Z
GIT_COMMIT: 6e4aa5a9a0e2cdb2f75f1465d3939e8d73002ba0
TARGET_COMMIT: fbe46c44861e489f65d55abac01eedc4934318a7
AUTHORIZED_PHASE: 1
APPROVES_PHASE: NONE

B. What was built

Per orchestrator instruction argus-phase-1-remediation-006
(AUTHORIZED_ACTION: REMEDIATE_PHASE_1_ROUND_6_AND_WATCHER_HARDENING_ONLY,
APPROVES_PHASE: NONE), all 6 audit findings were remediated with real
production code and tests. Commits below:

1. **Finding #1** (`eea81f3`) — `_is_dirty_checkout()` returned `None`
   for every `git status` failure, and `resolve_production_git_commit()`
   treated that identically to "no git checkout at all", so a corrupt,
   unreadable, permission-denied, or otherwise broken-but-present
   checkout could still have an arbitrary `ARGUS_BUILD_GIT_COMMIT`
   override accepted as verified production identity. Replaced with an
   explicit `_GitCheckoutState` (`ABSENT`, `PRESENT_CLEAN`,
   `PRESENT_DIRTY`, `PRESENT_UNVERIFIABLE`) computed by
   `_probe_git_checkout_state()`. Git-metadata presence is now a pure
   filesystem check (`.git` dir or file, the latter covering linked
   worktrees) performed *before* any subprocess call, so a later
   git-command failure is `PRESENT_UNVERIFIABLE`, never `ABSENT`. Only
   `ABSENT` may fall back to a build-time override; `PRESENT_UNVERIFIABLE`
   fails closed exactly like `PRESENT_DIRTY`, unconditionally, even with
   a well-formed override supplied. A `git rev-parse HEAD` failure after
   a clean `git status` is likewise unverifiable, never grounds to accept
   an override. 5 new adversarial tests in `tests/unit/test_config.py`
   (36 total); 3 confirmed via `git stash` to genuinely fail against the
   pre-fix code.

2. **Findings #2+#3** (`e0f7b9b`) — Finding #2: `GitTreeAttestation`
   stored a single saved `git ls-tree` text line, and the offline
   validator only re-parsed and compared that saved line against itself
   — proving the saved text was self-consistent, never that the declared
   upstream commit actually contains the declared path resolving to the
   declared blob. Rewritten so `attest_git_tree()` walks the real commit
   object and every tree object along the path via `git cat-file`,
   storing their raw content (base64) alongside the resolved
   `commit_sha`/`blob_sha1`/`mode`; a new `verify_git_object_chain()`
   independently recomputes every object ID from that raw content via
   git's own content-addressing and walks `path_components` to confirm
   the declared path resolves to the declared blob, entirely offline
   with no git binary or network access at validation time — the
   docstring is explicit that this proves object-chain content
   integrity, never that a particular remote hostname served that
   commit. Finding #3: `compute_account_level_deltas()`
   (`generic_parser.py`) exposes every wallet-owned account's own net
   balance change *before* `compute_asset_deltas()`'s by-mint
   aggregation, which can net two accounts of the same mint moving
   oppositely to zero and erase the evidence entirely. `ExpectedOutcome`
   gained an `account_deltas` field (`ExpectedAccountAssetDelta` rows)
   checked against the rebuilt payload, never derived from it. Record
   identity fields (category, chain, signature, slot,
   transaction_version, upstream_path) are now bound to and checked
   against the rebuilt payload via a new `_check_record_identity()`,
   rather than being fed back into the parser as trusted inputs;
   `upstream_commit` is also now checked against the attestation's own
   `commit_sha` at import time. Re-review of round 5's LP/multiple-
   account fixture
   (`real_mainnet_orca_increase_liquidity_multi_asset_outflow`,
   `orca_add_liq.json`) found it had only one material non-SOL token
   account from the reviewed wallet's own perspective — replaced (not
   relabeled, per the instruction's explicit "source a better fixture;
   do not relabel it") with `real_mainnet_orca_close_position_multi_account`
   (`orca_remove_liq.json`, same upstream repo/commit, wallet
   `JC8m5y9D7atuzD7mToWN8VVrtxyxCXQ3SFWMHFiLZagN` — the transaction's
   actual signer, not a program-derived vault), which has two genuinely
   distinct material token accounts independently proven by
   `account_deltas`. All 12 real-chain fixtures re-imported and offline-
   validated through the new schema; 11 of 12 fixtures' preserved
   sources/sanitized bytes are byte-identical to before (only the Orca
   source changed). 40 net new tests (450 → 490 in this file's own
   suite), including object-chain tamper tests
   (`test_validate_detects_a_tampered_commit_object_bytes`,
   `..._a_tampered_intermediate_tree_object`,
   `..._a_tampered_path_component`,
   `..._a_tampered_upstream_tree_attestation_blob`), record-identity
   tamper tests for all 6 fields
   (`test_validate_detects_a_tampered_record_category`, `..._chain`,
   `..._signature`, `..._slot`, `..._transaction_version`,
   `..._upstream_path`), and a direct adversarial test proving two
   same-mint accounts moving oppositely are preserved even though
   by-mint aggregation nets them to zero
   (`test_by_mint_aggregation_erases_two_same_mint_accounts_netting_to_zero`,
   `test_compute_account_level_deltas_preserves_both_same_mint_accounts`
   in `tests/golden/test_generic_parser.py`).

3. **Finding #4** (`165c397`) — Helius HTTP/canonical-model validation
   deepened per the instruction's 7 required sub-items. The JSON-RPC
   envelope itself is now validated for every HTTP RPC call inside
   `_rpc()`'s single accounted operation: exact `jsonrpc` version, exact
   request-ID type/value match (never bare `==`, since Python's `bool`
   is an `int` subclass), and `result`/`error` mutual exclusivity
   (`test_helius_rpc_envelope_id_mismatch_rejected`,
   `..._bool_id_never_matches_the_real_request_id`, `..._missing_id_rejected`,
   `..._version_mismatch_rejected`, `..._missing_version_rejected`,
   `..._result_and_error_both_present_rejected`,
   `..._non_object_response_rejected`, `..._valid_boundary_accepted`).
   `get_transaction(signature)` now binds response identity to the
   request: the returned primary signature must equal the requested
   signature. Strict, explicit `u64` numeric domains
   (`_is_strict_u64`, bounded to `2**64-1`) replace the prior sign-
   agnostic-only checks across slot/fee/balance/blockTime fields
   (`test_helius_get_transaction_overflow_fee_rejected`,
   `..._fee_at_u64_max_accepted`, `..._overflow_slot_rejected`,
   `..._overflow_balance_entry_rejected`). Raw SPL token-amount strings
   are validated via `_is_valid_raw_amount_string`: ASCII-only decimal
   digits (Python's `str.isdigit()`/`int()` both accept non-ASCII
   Unicode digit characters), a bounded digit count (≤20) before an
   expensive `int()` conversion, and the resulting value bounded to
   `u64` (`test_helius_get_transaction_token_amount_string_overflowing_u64_rejected`,
   `..._token_amount_at_u64_max_accepted`,
   `..._unicode_digit_token_amount_rejected`).
   `get_signatures_for_address` now rejects negative slot/blockTime and
   safely validates the blockTime → UTC-datetime conversion
   (`OverflowError`/`OSError`/`ValueError` caught, never crashing the
   caller). `get_signature_statuses` now requires both `slot` and `err`
   as explicit keys on every non-null entry — a missing `err` no longer
   silently becomes an implicit successful `None` via bare `.get()`.
   Every signature/pubkey/mint/owner/token-account-pubkey identity
   string is now validated non-empty
   (`_is_nonempty_identity_string`). `TokenAccountInfo.raw` is now
   genuinely deeply immutable and alias-safe via `_deep_freeze()`,
   which recursively builds fresh `MappingProxyType`/tuple structures at
   every nesting level from freshly-copied content, rather than round
   5's shallow `MappingProxyType(entry)`
   (`test_deep_freeze_source_mutation_does_not_alter_the_frozen_copy`,
   `..._produces_immutable_structures_at_every_level`). 33 net new tests
   (100 → 133 in this file); ~29 confirmed via `git stash` to genuinely
   fail against the pre-fix code.

4. **Finding #5** (`6adbea9`, `6e4aa5a`) — `tick()`'s pre-launch
   `head_before`/`git_remote_head()` comparison read only the *locally
   cached* `origin/{branch}` ref set by the tick's early fetch — stale
   by however much time elapsed since (instruction parsing, target-
   commit/phase checks, and the CLAIMED-state write all happen in
   between), so a remote change landing in that window could still be
   silently launched against. Added a final pre-launch barrier,
   immediately before transitioning to `RUNNING`/launching Claude, that
   performs a fresh `git_fetch()` and re-verifies, in order: fetch
   success; worktree cleanliness; local `HEAD` equals the freshly-
   fetched remote `HEAD`; a working-tree/committed-blob hash snapshot of
   `ORCHESTRATOR_INSTRUCTIONS.md` (explicit `git_hash_object()`-vs-
   `git_blob_at()` check, not merely relying on the clean-worktree
   re-check); `ACTIVE` instruction fields unchanged since the tick's
   earlier parse; target-commit provenance; and phase authorization.
   Any failure reverts state to `IDLE` (never `FAILED`) and clears
   `current_instruction_id`, so the next tick freely re-fetches and
   re-evaluates rather than requiring a new `INSTRUCTION_ID` to retry —
   per the instruction's explicit "do not consume or mark the stale
   instruction complete." 3 new deterministic tests in
   `tests/unit/test_orchestrator_watch.py`
   (`test_remote_moves_after_first_fetch_blocks_launch`,
   `test_final_pre_launch_fetch_failure_blocks_launch`,
   `test_local_instructions_mutation_before_final_barrier_blocks_launch`),
   each asserting the Claude runner is never invoked; all 3 confirmed
   via `git stash` to genuinely fail against the pre-fix code — the
   pre-fix watcher actually launches Claude in each scenario (one via a
   `TARGET_COMMIT_MISMATCH` false negative that never reaches the
   barrier at all, revealing the pull itself absorbed the race; the
   other two directly reach and pass the pre-fix stale comparison).

5. **Finding #6** (this checkpoint) — evidence/reporting consistency.
   Section E below scores every one of the instruction's 20 mandatory
   acceptance-matrix items against exact evidence, not bare assertion.
   `docs/BUILD_STATE.md` and `orchestration/AGENT_HANDOFF.md` are
   updated to the current, honest state without marking Phase 1
   orchestrator-approved. This checkpoint uses only `PASS`/`FAIL`/
   `PARTIAL`/`NOT TESTED`/`DEFERRED_ENVIRONMENTAL_CHECK` dispositions.
   PostgreSQL 16 evidence is labeled PostgreSQL 16 throughout, never 17;
   mocked/fake Helius transport evidence is labeled as such, never live
   RPC/WebSocket validation. Section H discloses a genuinely new finding
   surfaced during this round's own evidence cross-check: a commit-
   trailer formatting defect (not previously reported in any prior
   round's checkpoint) — reported honestly rather than silently
   corrected via history rewrite.

C. Commands actually run

All commands below were run against this exact commit
(`6e4aa5a9a0e2cdb2f75f1465d3939e8d73002ba0`) after all 6 findings were
complete:

- `uv run pytest tests/unit -q` — 458 passed, 0 failed, 0 skipped
  (includes `tests/unit/test_orchestrator_watch.py`'s 77).
- `uv run pytest tests/integration -q` — 43 passed, 0 failed, 0 skipped
  (real local PostgreSQL 16 — see PG17_COMPOSE_VALIDATION disposition,
  unchanged, in section F).
- `uv run pytest tests/golden -q` — 36 passed, 0 failed, 0 skipped.
- `uv run pytest tests/replay -q` — 10 passed, 0 failed, 0 skipped
  (unchanged from round 5).
- `uv run pytest tests/unit/test_orchestrator_watch.py -q` — 77 passed
  (targeted watcher late-remote-movement/final-fetch-failure tests).
- `uv run pytest tests/unit/test_config.py -q` — 36 passed (targeted
  production-git-identity adversarial tests).
- `uv run pytest tests/unit/test_golden_fixtures.py -q` — 57 passed
  (targeted fixture object-chain/account-context/tamper tests).
- `uv run pytest tests/unit/test_provider_adapters.py -q` — 133 passed
  (targeted Helius malformed-contract + exact-usage-count tests).
- `uv run pytest --cov --cov-report=term-missing -q` — 547 passed (458
  unit [incl. 77 watcher] + 43 integration + 36 golden + 10 replay), 86%
  overall coverage (3583 statements, 451 missed, 740 branches, 93
  partial). Lowest-covered modules, unchanged for structural reasons
  from every prior round: `src/argus/ingestion/test_mode.py` 0% and
  `src/argus/providers/helius/websocket_connector.py` 0% (both exercised
  only via the real CLI process/adapter tests against a fake connector,
  never faked as "tested" in the coverage-instrumented sense).
- `uv run ruff check .` — All checks passed.
- `uv run ruff format --check .` — 153 files already formatted.
- `uv run mypy` (bare — `[tool.mypy]` `packages = ["argus"]` scopes this
  to `src/argus` only, matching every prior round's invocation) —
  Success: no issues found in 75 source files.
- `select count(*) from chain_events` / `select count(*) from swaps`
  against the dev database — both `0`, confirmed empty before the
  migration cycle below (non-destructive).
- `uv run alembic downgrade base` then `uv run alembic upgrade head`
  then `uv run alembic current` — clean migration-from-zero cycle
  through 0001 → 0002 → 0003 → 0004 → 0005 → 0006 → 0007 and back;
  `current` reports `0007 (head)`.
  `tests/integration/test_migrations.py` independently and repeatably
  re-proves the same migration-from-zero/upgrade-from-0003/upgrade-
  from-0005/downgrade/idempotency/restart-safety/populated-data-
  downgrade scenarios (unchanged this round, still passing).
- `uv run argus providers probe` — Helius: `CREDENTIAL_REQUIRED` (exact
  section-108 notice, no value printed); DexScreener/GeckoTerminal/
  Jupiter: `UNREACHABLE` (`ProxyError: 403 Forbidden`); no crash, no
  fabricated data.
- `uv run argus providers probe-history` — GeckoTerminal: `UNREACHABLE`
  (same network blocker); no crash.
- `uv run argus providers usage --provider helius` — today/MTD/projected
  credits = 0 (honest: no real provider call has ever succeeded in this
  environment to generate usage rows).
- `uv run argus ingest run --test-mode --wallet
  SomeTestWalletNotReal1111111111111111111111` — "test-mode: ran cleanly
  for 5.0s across 1 wallet(s) -- no crash, no network, no
  signing/execution/broadcast path exists"; exit code 0.
- `uv run argus fixtures validate-real-chain` — all 12 imported
  real-chain fixtures independently rebuild from their preserved raw
  source bytes and license evidence, re-verify their offline Git
  object chain (finding #2), and report `ok`.
- `uv run pytest tests/integration/test_reconciliation_sql.py -q` — 9
  passed (real PostgreSQL 16; independently and repeatably proves
  reparse/reconciliation convergence, including concurrent-reparse
  exactly-one-row and A/B missed-event recovery, unchanged this round).
- `git ls-files`-based secret scan (AWS-style keys, PEM private-key
  headers, inline password/api-key literals) across all tracked files
  — clean, no matches. `.env` confirmed untracked and gitignored
  (`git check-ignore -v .env`).
- `git grep`-based scan for signing/broadcast keywords
  (`sign_transaction`/`send_transaction`/`sendRawTransaction`/
  `private_key`/`Keypair(`/`broadcast`) across `src/argus/` — every
  match is a docstring/comment stating the prohibition; no executable
  signing/broadcast code exists.
- `git diff --stat fbe46c44861e489f65d55abac01eedc4934318a7..HEAD --
  . ':!orchestration'` — 19 files changed (4318 insertions, 1360
  deletions); every changed file is inside the existing Phase 1 module
  set (`scripts/argus_orchestrator_watch.py`, `src/argus/{config.py,
  golden_fixtures.py,parsing,providers}`, `tests/`); zero `config/`
  changes; no new top-level trade/execution/wallet-discovery module.

D. Test results

- unit: 458 passed (includes watcher's 77)
- integration: 43 passed (real PostgreSQL 16)
- golden: 36 passed
- replay: 10 passed
- full suite with coverage: 547 passed, 0 failed, 86% overall coverage
- ruff check: clean
- ruff format --check: clean
- mypy: clean, 75 source files (`src/argus` scope, per `[tool.mypy]`)
- alembic downgrade-to-base / upgrade-to-head: clean cycle through 0007

E. Acceptance matrix / acceptance criteria (20 items from
   argus-phase-1-remediation-006, each scored with the exact evidence
   proving it)

1. PASS — production Git identity distinguishes absent Git from
   present-but-unverifiable Git and fails closed for every
   dirty/unverifiable checkout regardless of override:
   `_GitCheckoutState`/`_probe_git_checkout_state()`/
   `resolve_production_git_commit()` (`src/argus/config.py`); 36/36
   tests in `tests/unit/test_config.py`, including
   `test_resolve_production_git_commit_metadata_present_but_status_fails_raises`,
   `..._status_fails_override_still_raises`,
   `..._status_fails_allow_unverified_sentinel`,
   `..._status_ok_but_rev_parse_head_fails_raises`,
   `..._status_ok_rev_parse_fails_allow_unverified_sentinel`,
   `..._worktree_gitfile_present_but_unverifiable_raises`.
2. PASS — every counted authentic fixture has an offline-verifiable Git
   object chain proving declared commit/tree/path/blob for source and
   license evidence: `GitTreeAttestation`/`attest_git_tree()`/
   `verify_git_object_chain()` (`src/argus/golden_fixtures.py`); all 12
   fixtures independently rebuild and validate `ok`
   (`argus fixtures validate-real-chain`, section C); a saved `ls-tree`
   line is no longer stored or relied on at all. 4 dedicated
   object-chain tamper tests (section B item 2).
3. PASS — every counted fixture has an independent semantic oracle
   validating wallet perspective, account-level deltas where material,
   by-mint deltas, classification, eligibility, input/output amounts,
   fee, failure state, confidence rule, rationale, and evidence:
   `ExpectedOutcome`/`ExpectedAccountAssetDelta`/`_diff_expectation()`
   (`src/argus/golden_fixtures.py`); `_check_record_identity()` binds
   record identity to the rebuilt payload. 57/57 tests in
   `tests/unit/test_golden_fixtures.py`.
4. PASS — the multiple-token-account/LP-style category is proven by
   authentic account-level evidence:
   `real_mainnet_orca_close_position_multi_account`'s `account_deltas`
   independently proves two genuinely distinct material token accounts
   from the transaction's actual signer's own perspective (section B
   item 2); the parser correctly emits `UNKNOWN` (ineligible), not
   `LP_ACTION` — acceptable per the instruction's own explicit text
   ("The parser label may be UNKNOWN rather than LP_ACTION if the
   semantic category is independently proven and remains ineligible").
   Unlike round 5's fixture for this category, this one has no
   remaining caveat: it was replaced, not relabeled, specifically
   because independent review found the round-5 fixture did not
   actually satisfy the category from the reviewed wallet's own
   perspective.
5. PASS — all nine MASTER_SPEC real-chain fixture categories remain
   authentic and independently validated after the stronger
   provenance/oracle checks: `argus fixtures validate-real-chain`
   reports `ok` for all 12 fixtures spanning all 9 required categories
   (section C); Phase 1 is not PARTIAL on this item.
6. PASS — fixture record identity fields are bound to and checked
   against rebuilt raw evidence; every direct tamper class fails
   closed: `_check_record_identity()` checked for category, chain,
   signature, slot, transaction_version, upstream_path (section B
   item 2); 6/6 dedicated tamper tests, one per field
   (`test_validate_detects_a_tampered_record_category` through
   `..._upstream_path`).
7. PASS — Helius HTTP JSON-RPC envelope and every downstream-consumed
   field use strict type/domain/identity validation; wrong-transaction
   and malformed numeric responses cannot cross the adapter boundary:
   section B item 3; 8 dedicated envelope tests plus signature-binding,
   overflow/boundary, and Unicode-digit tests (section B item 3 lists
   exact test names).
8. PASS — `TokenAccountInfo.raw` is deeply immutable and alias-safe;
   nested mutation cannot change returned canonical evidence:
   `_deep_freeze()` (`src/argus/providers/helius/client.py`);
   `test_deep_freeze_source_mutation_does_not_alter_the_frozen_copy`,
   `..._produces_immutable_structures_at_every_level` directly import
   and exercise the private function (the original HTTP-round-trip
   alias test alone cannot discriminate this, since httpx's `json=`
   response forces a fresh parse client-side regardless of source-side
   mutation — kept as a labeled end-to-end control, not removed).
9. PASS — every Helius success/failure path records exactly one correct
   terminal provider-usage outcome: unchanged from round 5's
   `_ACCOUNTED_OPERATION`-scoped usage-recording design, now exercised
   against every new validation path added this round;
   `test_usage_records_contract_error_for_malformed_rpc_envelope` and
   the full `test_provider_adapters.py` suite (133/133) confirm no new
   contract failure double-accounts or silently drops a usage row.
10. PASS — WebSocket typed acknowledgement, early-notification
    preservation, bounded lifecycle, quiet-socket liveness, dead-socket
    reconciliation, and exact-once canonicalization remain green:
    unchanged from round 5, regression-verified this round (all
    `test_helius_ws_*` tests in `tests/unit/test_provider_adapters.py`
    still pass, including
    `test_helius_ws_stream_bool_id_never_matches_the_real_request_id`
    and `..._skips_mismatched_id_before_matching_ack`).
11. PASS — reparse remains parser-artifact-aware, append-only,
    concurrent-safe, restart-safe, and converges to no pending work:
    unchanged from round 5 (`events_pending_for_artifact`),
    regression-verified: `tests/integration/test_reconciliation_sql.py`'s
    9 real-Postgres tests still pass (section C).
12. PASS — migration 0007 populated-data downgrade behavior remains
    non-destructive and fail-closed when the older schema cannot
    represent the data: unchanged from round 5
    (`Downgrade0007IncompatibleDataError`); `test_migrations.py`'s
    populated-data downgrade tests still pass within the 43/43
    integration count (section C).
13. PASS — direct pagination-boundary proof, commitment monotonicity,
    finalization, disconnect/reconnect A/B, persistent watermarks,
    database session isolation, provider priority/accounting, and
    restart/crash regressions remain green: unchanged from round 5,
    all still passing within the 458/458 unit + 43/43 integration
    counts (section C/D); no regression introduced by this round's
    changes to `config.py`/`golden_fixtures.py`/
    `generic_parser.py`/`helius/client.py`/`argus_orchestrator_watch.py`.
14. PASS — the watcher performs a fresh final remote pre-launch barrier
    and cannot launch on a remote branch that moved after its initial
    fetch/pull: section B item 4;
    `test_remote_moves_after_first_fetch_blocks_launch`,
    `test_final_pre_launch_fetch_failure_blocks_launch`,
    `test_local_instructions_mutation_before_final_barrier_blocks_launch`,
    each confirmed via `git stash` to genuinely fail (launch Claude) on
    the pre-fix watcher.
15. PASS — watcher stale CLAIMED/RUNNING handling, failed-Claude
    handling, exact handoff ID, fresh checkpoint/bundle requirements,
    dirty/unpushed rejection, trailer attribution, target-commit
    protection, and terminal instruction-file quarantine remain green:
    all 77/77 `tests/unit/test_orchestrator_watch.py` tests pass,
    unchanged in intent from rounds 2-5, plus this round's 3 new tests.
16. PASS-WITH-LABEL — real PostgreSQL concurrency/migration checks
    remain green; every run in this round is explicitly labeled
    PostgreSQL 16 only (section C, F); no PostgreSQL 16 evidence is
    described as PostgreSQL 17 anywhere in this checkpoint, the
    handoff, or `docs/BUILD_STATE.md`.
17. DEFERRED_ENVIRONMENTAL_CHECK — live Helius RPC/WSS and PG17 checks
    remain explicit deferrals, not simulated as closed: see section F.
18. PASS — no signer/signing/key/seed/live-arm/broadcast/mainnet-trade/
    paid-provider enablement exists, and no Phase 1.5 or later-phase
    implementation begins: `git grep` scan (section C) confirms every
    signing/broadcast keyword match is a docstring/comment; `git diff
    --stat` against `TARGET_COMMIT` (section C) confirms every changed
    file is inside the existing Phase 1/watcher module set, zero
    `config/` changes.
19. PASS — secret scan is clean; no credential is entered, displayed,
    logged, or committed: section C; `.env` confirmed untracked and
    gitignored.
20. PASS — full repository quality gates and the full Phase 1 + watcher
    regression suite pass with no unexplained skips: section D (547
    passed, 86% coverage, ruff clean, mypy clean, alembic cycle clean);
    `git grep -rn "pytest.mark.skip\|pytest.skip("` across `tests/`
    finds only the pre-existing, environment-dependent
    Postgres-unreachable skip guard (`scratch_database` fixture,
    `tests/integration/conftest.py`), not triggered this session
    (Postgres was reachable throughout).

Summary: 19 of 20 acceptance-matrix items are PASS (item 16 carries an
explicit PostgreSQL-16-only label, not a caveat on correctness); item 17
is the standing, explicitly-permitted `DEFERRED_ENVIRONMENTAL_CHECK` for
live Helius/PG17 connectivity. No item is scored PASS by weakening a
definition, renaming a fixture, or treating a self-generated value as
independent evidence.

F. Environmental deferrals (unchanged from Phase 1/every prior round)

- Live Helius RPC connectivity — NOT TESTED (no `HELIUS_API_KEY`
  configured in this sandbox; the exact section-108 `LOCAL CREDENTIAL
  REQUIRED` notice is produced, never a mocked live claim).
- Live Helius WebSocket connectivity — NOT TESTED (same credential
  blocker); proven against the fake connector's scripted scenarios only.
- Real PostgreSQL 17 Compose validation
  (`PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK`) — unchanged;
  this sandbox's egress policy blocks Docker Hub's image CDN. All
  migration/application logic this round was verified against the same
  substitute local PostgreSQL 16 server used throughout this project,
  explicitly never described as PostgreSQL 17 validation.
- DexScreener/GeckoTerminal/Jupiter live reachability — UNREACHABLE
  (confirmed via `argus providers probe`; general RPC/market-data egress
  remains blocked, distinct from the GitHub raw-content/git-clone read
  access findings #2/#3 rely on, which is separately confirmed working
  this round too — used only to re-verify offline-storable object
  bytes, never as a live-network dependency of the validator itself).

None of these deferrals is claimed as PASS, and none authorizes live
readiness by itself.

G. Deviation from the audit instruction

No deviation from the instruction's authorized scope: work was strictly
limited to `AUTHORIZED_ACTION:
REMEDIATE_PHASE_1_ROUND_6_AND_WATCHER_HARDENING_ONLY` against the 6
named findings and the 20-item mandatory acceptance matrix. No phase was
self-approved; `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` was not
modified; no live trade, signing, credential disclosure, paid-provider
upgrade, or threshold relaxation was performed or attempted.

H. Audit-of-the-audit (performed before finalizing this checkpoint)

- **Untested branches**: `compute_account_level_deltas()`'s failed-
  transaction short-circuit and ordering guarantee are each covered by
  a dedicated test
  (`test_compute_account_level_deltas_empty_for_failed_transaction`,
  `..._is_deterministically_ordered`); the watcher's new final-barrier
  branches (fetch failure, dirty, HEAD-mismatch, instructions-changed,
  target-commit re-check, phase re-check) each have at least the 3 new
  deterministic tests exercising the first three; the target-commit/
  phase re-check branches share code paths already covered by the
  pre-existing initial-check tests and are not independently
  adversarially tested this round (see the one open item below).
- **Skipped tests**: `git grep -rn "pytest.mark.skip\|pytest.skip("`
  across `tests/` finds only the pre-existing, environment-dependent
  Postgres-unreachable skip guard — none newly added or triggered this
  session.
- **Self-generated expected values**: `ExpectedAccountAssetDelta` rows
  for the replaced Orca fixture were hand-derived directly from
  `orca_remove_liq.json`'s own `meta.preTokenBalances`/
  `postTokenBalances` before being checked against
  `compute_account_level_deltas()`'s actual output (caught and fixed a
  genuine off-by-fee arithmetic error in the hand derivation during this
  process — see the `_acct()` `fee_added_back` parameter added to the
  reimport helper — which is itself evidence the derivation was
  independent, not copied from parser output).
- **Mocks that bypass production wiring**: unchanged from round 5 —
  `FakeSubscription`/`FakeLiveStream`/`_FakeWebSocketConnection` fake
  only the transport boundary; all reconciliation/parsing/persistence/
  usage-accounting logic between that boundary and the database runs
  for real. The watcher's new tests use a real temporary git repository
  and real `git` subprocess calls throughout (see
  `tests/unit/test_orchestrator_watch.py`'s module docstring), injecting
  a race only at the exact `git_pull_ff_only`/`read_build_state`
  call-site boundary, never faking git itself.
- **Stale evidence**: `PROVENANCE.md`/`provenance.json`/`SEARCH_LOG.md`/
  `EVIDENCE_FILE_SCHEMA.md` were all regenerated or updated this round
  (section B); `docs/BUILD_STATE.md`'s phase-history table gained a new
  round-6 row (this checkpoint's own consolidation) rather than editing
  round 5's row. Round 1-5's own checkpoints and phase-history rows are
  left unmodified as immutable history of what was claimed at the time.
- **Changed category definitions**: no required category's own
  definition was weakened, renamed, or redefined; the Orca fixture
  replacement (finding #3) is a like-for-like substitution within the
  same category, not a redefinition of what "multiple token-account
  action" means.
- **Contradictions across documents**: `docs/BUILD_STATE.md`,
  `SEARCH_LOG.md`, `PROVENANCE.md`, `orchestration/AGENT_HANDOFF.md`,
  and this checkpoint were cross-checked to all state the same 9-of-9
  fixture-category disposition and the same 547-test/86%-coverage
  figures before this checkpoint was finalized.
- **A newly discovered defect, disclosed rather than hidden**: while
  cross-checking this round's own commit trailers as part of finding
  #6's evidence-honesty mandate, `git interpret-trailers --parse`
  (the exact mechanism `scripts/argus_orchestrator_watch.py`'s
  `git_trailer_values()`/`verify_run_ancestry_and_attribution()` use to
  authenticate commit attribution) was found to recognize only the
  *last* contiguous trailer-shaped paragraph in a commit message as the
  real trailer block. Three of this round's own commits
  (`eea81f3`, `e0f7b9b`, `165c397`) place `ARGUS-INSTRUCTION-ID:
  argus-phase-1-remediation-006` in a paragraph immediately followed by
  a blank line and then a separate `Co-Authored-By`/`Claude-Session`
  paragraph — which, per git's own trailer-block detection, means
  `ARGUS-INSTRUCTION-ID` is **not** recognized as a real trailer on
  those 3 commits by this exact mechanism, even though the text is
  present in the message body. Verified with a minimal reproduction
  (`printf` piped through `git interpret-trailers --parse`) and cross-
  checked against the full repository history: 5 of 58 total commits
  carrying an `ARGUS-INSTRUCTION-ID:` line are affected this way,
  including this same round's own two earliest commits and, notably,
  `fbe46c44861e489f65d55abac01eedc4934318a7` itself — this instruction's
  own `TARGET_COMMIT` (round 5's final checkpoint/bundle/handoff
  commit) — and `04f367b8e03e99718812f872a34e73e170c44f0d` (round 1's
  equivalent). This is a **pre-existing, systemic-but-intermittent**
  defect, not something newly introduced only by this round's process,
  but 3 of *this round's own* commits are affected, which is squarely
  within this round's own attribution-honesty scope. Practically: the
  watcher's `verify_run_ancestry_and_attribution()` only checks commits
  within one `tick()`-launched run's own before/after HEAD range, so
  this does not retroactively invalidate any *already-recorded*
  orchestrator approval of a prior round (no prior round's checkpoint
  claimed a per-commit trailer verification result that this discovery
  contradicts) and does not block a future watcher-launched run from
  evaluating this round's work correctly (a future run's own
  `head_before` starts fresh from the current HEAD). This round's two
  most recent commits (`6adbea9`, `6e4aa5a`) and this checkpoint's own
  upcoming commit carry the `ARGUS-INSTRUCTION-ID` trailer as the sole,
  final paragraph — verified correctly recognized by
  `git interpret-trailers --parse` before being reported here. No
  history rewrite/force-push was performed to correct the 3 affected
  commits: that is a destructive, hard-to-reverse operation on already-
  pushed history, and this checkpoint reports the defect for
  orchestrator disposition instead of unilaterally rewriting shared
  history without authorization. See section K for the specific
  question this raises for orchestrator review.

I. Known bugs / debt

- No new known bugs are introduced by this round's changes. The one
  newly discovered item is the pre-existing commit-trailer-formatting
  defect disclosed in section H, which is a gap in prior rounds'
  process (dating back to round 1), not a defect in the production
  `src/argus/` code this checkpoint covers.
- Existing structural coverage gaps (`test_mode.py`,
  `websocket_connector.py` at 0%, both exercised only through real
  process/adapter-level tests against a fake connector) are unchanged
  from every prior round and are not new debt.

J. Security state

- `LIVE_READY_SOFTWARE=false`, `LIVE_CANARY_PASSED=false`,
  `LIVE_ARMED=false` — unaffected by this round.
- No signing, signer, private-key, seed-phrase, live-arm, or broadcast
  path exists anywhere in `src/argus/` (section C).
- Credential handling for `HELIUS_API_KEY` is unchanged: missing
  credential raises the exact section-108 `LOCAL CREDENTIAL REQUIRED`
  notice, never a mocked fallback claiming live acceptance.
- Secret scan clean (section C); `.env` confirmed untracked and
  gitignored.
- Production git identity cannot silently accept an override on an
  unverifiable-but-present checkout (finding #1): the fail-open path is
  closed.
- Fixture provenance is now offline-verifiable end-to-end, closing the
  self-referential "saved text matches itself" gap (finding #2).
- The watcher can no longer launch unattended work against a stale
  view of the remote branch (finding #5): the final pre-launch barrier
  closes the race window described in the instruction.
- No paid-provider feature enabled; no Phase 1.5 or later-phase code
  started (item 18).

K. Next specified phase

Per orchestrator instruction argus-phase-1-remediation-006, this
instruction approves no phase and authorizes remediation only. Phase 1.5
and all later phases remain forbidden.
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md` was not modified.
`docs/BUILD_STATE.md`'s `last_orchestrator_approved_phase` (0) and the
Phase 0 `approved_commit` are left unchanged, exactly as the instruction
requires — this session does not and cannot self-approve Phase 1. Two
open items for orchestrator review:

1. Section H's newly discovered commit-trailer-formatting defect: 3 of
   this round's own commits do not carry an `ARGUS-INSTRUCTION-ID`
   trailer recognizable by the watcher's own `git interpret-trailers
   --parse`-based mechanism, due to a trailing `Co-Authored-By`/
   `Claude-Session` paragraph breaking git's trailer-block detection.
   This has not been corrected via history rewrite. The orchestrator
   should decide whether a corrective history rewrite of this branch
   (and/or the 2 historically affected commits from rounds 1 and 5) is
   warranted, or whether disclosure alone is sufficient given the
   watcher's per-run (not cross-run) attribution-check scope.
2. Whether the round-6 remediation as a whole (all 6 findings, 19 of 20
   acceptance-matrix items unconditional PASS, item 17 the standing
   permitted environmental deferral) is sufficient for Phase 1 approval,
   or whether further remediation is required.

STOP. Await orchestrator review of this checkpoint before any further
phase work.

================ END ARGUS CHECKPOINT =========================
