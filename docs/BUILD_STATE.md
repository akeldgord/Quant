# ARGUS Build State

Machine-and-human-readable state for session recovery (MASTER_SPEC.md section 8).
Every new implementation session must read this file before doing anything else.

```yaml
current_phase: 1.5  # Phase 1.5 remediation round 2 complete (implementation-agent-reported); NOT yet orchestrator-approved
last_completed_phase: 1.5  # implementation-agent-reported complete (HISTORICAL_DATA_PATH = PASS_WITH_LIMITATIONS, program-and-discriminator semantic gate fixed); awaiting orchestrator review
last_orchestrator_approved_phase: 1  # MUST stay 1 until a later instruction explicitly approves Phase 1.5 (argus-phase-1-5-remediation-002's own explicit requirement -- this remediation approves no phase)
approved_commit: 2fbc566af74832bc6523648f60ba8cb60d98eb31  # Phase 1's orchestrator-approved implementation commit -- unchanged until Phase 1.5 is itself approved
awaiting_orchestrator_review: true  # Phase 1.5 remediation round 2 complete; see orchestration/checkpoints/phase_1_5_remediation_2.md

# PG17_COMPOSE_VALIDATION tracks whether `docker compose up postgres`
# (the actual postgres:17 image, per TECH-004 and compose.yaml) has been
# exercised end-to-end. It is DEFERRED, not PASS and not FAIL: functional
# correctness of the migration/application code was verified against a
# substitute PostgreSQL 16 server instead (see known_blockers below and
# docs/DECISION_LOG.md). Per explicit orchestrator instruction (2026-08-30):
# this deferral does NOT block starting Phase 1, but DOES block approving
# live readiness until it is closed out with a real postgres:17 run.
PG17_COMPOSE_VALIDATION: DEFERRED_ENVIRONMENTAL_CHECK

known_blockers:
  - "PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK. This
     implementation sandbox's egress policy blocks Docker Hub's image CDN
     (production.cloudfront.docker.com -> 403 at the proxy), so
     `docker compose up postgres` (the actual postgres:17 image) could not
     be pulled or exercised here. compose.yaml is unmodified and still
     targets postgres:17 as required by TECH-004 -- this is an environment
     limitation of this sandbox, not an architecture change. As a substitute,
     Phase 0 functional acceptance (migration-from-zero, DB roles,
     provider_usage grants, argus health, full pytest suite, missing-credential
     fail-closed behavior) was verified against the sandbox's
     locally-installed PostgreSQL 16 server, running the exact same Alembic
     migration and application code Compose would run against PostgreSQL 17.
     This PG16 run demonstrates the migration/application logic is correct;
     it does NOT demonstrate anything PostgreSQL-17-version-specific and
     must not be cited as PostgreSQL 17 validation. Closing this out requires
     running `make bootstrap && make up` (or equivalent) on a host with
     normal Docker Hub access and recording the result here and in
     docs/DECISION_LOG.md. See docs/DECISION_LOG.md for the full decision
     record. Per explicit orchestrator instruction, this deferred check does
     NOT block Phase 1, but IS required before live readiness can be
     approved."
  - "REALCHAIN_GOLDEN_FIXTURES = 9_OF_9_CATEGORIES_ONE_WITH_CAVEAT (round
     5, findings #1/#2/#3/#4 -- see below for how this improved on round
     4's honestly-reported 6/9). Round 2 imported 4 real fixtures from
     solana-labs/explorer (MIT); round 3 imported 6 more from
     0xjeffro/tx-parser (MPL-2.0); together these evidenced 6 of 9
     required categories: 'simple transfer' (both perspectives),
     SOL-to-token swap, token-to-SOL swap, token-to-USDC swap, multi-hop
     swap, and partial sell. Round 5 finding #4 fixed the parser's
     ambiguous-multi-asset handling, which as a side effect makes
     `real_mainnet_dca_close_dual_asset_transfer_in` (imported in round
     3, excluded from category count by round 4's correction below)
     resolve to `UNKNOWN`, ineligible -- satisfying category 7,
     'ambiguous multi-asset transaction', with no new fixture needed.
     Round 5 finding #3 searched three named candidate repositories and
     imported two more real fixtures: `real_mainnet_failed_nft_sale`
     (milktoastlab/SolanaNFTBot, MIT -- a genuine failed on-chain Magic
     Eden sale, `meta.err` set, extracted from its TypeScript-module
     wrapper via a new deterministic `extract_ts_const_export_default`
     transform step), satisfying category 9, 'failed on-chain
     transaction', cleanly; and
     `real_mainnet_orca_increase_liquidity_multi_asset_outflow`
     (quellen-sol/ingestooor, GPL-3.0 -- a genuine Orca Whirlpool
     increaseLiquidity call), mapped to category 8, 'multiple
     token-account/LP-style action', **with an explicit caveat**: the
     parser's own `LP_ACTION` label does not fire for this specific
     transaction (only one non-SOL asset is directly signer-owned; the
     LP position is held by a program-derived vault account instead), so
     it resolves via the ambiguous-multi-asset-outflow branch to
     `UNKNOWN` instead -- the substantive requirement (a real
     multi-token-account liquidity transaction, correctly never a
     confident single-asset trade) is satisfied, the specific label is
     not. **All 9 of 9 round-1-required categories now have real-chain
     evidence**, 8 without caveat and 1 (LP action) with the caveat above
     -- see tests/golden/fixtures/real/SEARCH_LOG.md's 'Round 5' section
     for the full search log, candidate-repository evaluation, and
     license-compatibility reasoning (including for GPL-3.0, reused here
     as one immutable verbatim data file, not linked code). Round 2/3/4's
     own checkpoints and phase-history rows below are left unmodified as
     immutable history of what was claimed at the time.
     ROUND 6 UPDATE: independent re-review (round 6 finding #3) found the
     round-5 LP/multiple-account fixture
     (real_mainnet_orca_increase_liquidity_multi_asset_outflow) had only
     one material non-SOL token account from the reviewed wallet's own
     perspective -- it did not actually satisfy the category. Per the
     round-6 instruction's explicit 'source a better fixture; do not
     relabel it', it was replaced (same upstream repo/commit, different
     wallet perspective:
     real_mainnet_orca_close_position_multi_account, wallet
     JC8m5y9D7atuzD7mToWN8VVrtxyxCXQ3SFWMHFiLZagN, the transaction's
     actual signer) with a fixture independently proven, via a new
     account-level delta oracle (compute_account_level_deltas /
     ExpectedAccountAssetDelta), to have two genuinely distinct material
     token accounts. All 9 of 9 required categories still have real-chain
     evidence, with NO remaining label caveat on this category (the
     parser correctly still emits UNKNOWN/ineligible for it, which the
     round-6 instruction explicitly accepts for this category as long as
     the underlying multi-account evidence is independently proven -- see
     orchestration/checkpoints/phase_1_remediation_6.md section E item 4
     and tests/golden/fixtures/real/SEARCH_LOG.md's 'Round 6' section).
     Round 6 also closed a gap where fixture provenance's saved
     `git ls-tree` line only proved self-consistency, not an actual
     offline-verifiable commit->tree->blob object chain (finding #2) --
     see golden_fixtures.py's GitTreeAttestation/verify_git_object_chain."
```

## Phase history

| Phase | Status | Commit | Notes |
|-------|--------|--------|-------|
| 0 | ORCHESTRATOR-APPROVED (`argus-phase-1-001`, 2026-08-31) | b838558f7eae1eac8d3559c7826ab340d604d916, remediated at ca74d09b3f976a5726fe46c1a8ea59d7bbdd3ad7 (history rewritten 2026-08-30 to scrub inert dev-only placeholder credential strings — see docs/DECISION_LOG.md; these are the post-rewrite hashes) | Foundation scaffold: repo layout, uv env, Compose+Postgres, Alembic baseline + DB roles, config/spec hashing, clock abstraction, structured logging, CLI skeleton, FastAPI skeleton, health framework, provider_usage schema, checkpoint bundle framework. Remediated per orchestrator feedback: removed all hardcoded fallback DB passwords (migrations/versions/0001_*.py, compose.yaml, src/argus/db/connection.py) in favor of required env vars that fail closed via MissingCredentialError; corrected checkpoint STATUS to not claim an unconditional PASS while PG17-via-Docker-Compose remains untested (see PG17_COMPOSE_VALIDATION above). 41/41 tests pass, 93% coverage, ruff+mypy clean. Approved by the ARGUS ORCHESTRATOR at commit `141af487fcfdff41d1597c19ea062139f5427f52` as `PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`. See runtime/reports/checkpoint_phase_0.txt for the full checkpoint. |
| 1 | BUILD COMPLETE, AWAITING ORCHESTRATOR REVIEW (authorized by `argus-phase-1-001`, target `141af487fcfdff41d1597c19ea062139f5427f52`) | 28a88f74d28e70542050f5d5e8d9a9d139f26bb8 | Live chain data acquisition + deterministic canonical parsing: Helius RPC/WSS adapter, DexScreener/GeckoTerminal/Jupiter adapters (no signing), fast-path+truth-path reconciliation with per-wallet watermarks and DEGRADED gating, durable clock-anomaly detection wired into reconciliation, immutable `chain_events`/`swaps`/`clock_health_events` ledger, generic balance-delta swap parser (11 golden fixtures), P0-P6 priority scheduler, provider usage accounting with 70/85/95% warnings wired into every real adapter call, HTTP retry/backoff, provider capability/history/usage probe CLI. 204 tests passing, 91% coverage, ruff+mypy clean. STATUS `PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`: acceptance criteria 1-2 (live Solana RPC/WebSocket) NOT TESTED -- no `HELIUS_API_KEY` configured and no general internet egress in this sandbox; no end-to-end stream-manager orchestration loop exists yet (each piece is built and tested in isolation). See `orchestration/checkpoints/phase_1.md` for the full 27-item disposition and disclosed gaps. NOT yet orchestrator-approved -- only the orchestrator may advance `last_orchestrator_approved_phase`. **Superseded by the remediation row below** -- an independent orchestrator audit (`argus-phase-1-remediation-001`) rejected this self-assessment as overstated; this row is kept unmodified as immutable history. |
| 1 (remediation round 1) | BUILD COMPLETE, AWAITING ORCHESTRATOR REVIEW (authorized by `argus-phase-1-remediation-001`, target `32c2898ab8c278c2f75f4a2f40fedd9d35b24b08`) | 83bb38497ac3af1402f38dabee6858e00ce2e9fb | Remediated all 10 audit findings from `argus-phase-1-remediation-001`: production `IngestionManager`/`argus ingest run` composing the WebSocket stream, reconciliation, and clock monitor into real runtime behavior; bounded cursor-based truth-path pagination that never silently truncates a gap; an auditable append-only commitment-observation model (replacing the dead `confirmed_at`/`finalized_at` columns) with regression/conflict rejection; parsing wired end-to-end into `swaps` persistence via a real `SqlSwapRecorder`; typed provider-contract validation replacing bare `isinstance(dict)` checks; usage accounting that survives transport exhaustion and is wired into the manager's real streaming code path; a dispatch-count-bounded scheduler starvation guarantee; 6 real `tests/replay` tests (was 0 collected). 260 tests passing, 84% coverage, ruff+mypy clean, alembic downgrade-to-base/upgrade-to-head clean. STATUS `PARTIAL_NOT_TESTED_REALCHAIN_FIXTURES`: 25 of 26 mandatory acceptance criteria PASS; criterion 15 (authenticated real-chain golden fixtures) is honestly NOT TESTED/blocked -- this sandbox has no general internet egress and no already-available safe source of authentic transaction data, per the instruction's own explicit fallback for this exact case. See `orchestration/checkpoints/phase_1_remediation_1.md` for the full 26-item disposition. NOT yet orchestrator-approved -- only the orchestrator may advance `last_orchestrator_approved_phase`. **Superseded by the remediation round 2 row below** -- an independent orchestrator audit (`argus-phase-1-remediation-002`) rejected round 1 as still insufficient; this row is kept unmodified as immutable history. |
| 1 (remediation round 2) | BUILD COMPLETE, AWAITING ORCHESTRATOR REVIEW (authorized by `argus-phase-1-remediation-002`, target `04f367b8e03e99718812f872a34e73e170c44f0d`) | e44b5885b8aa02105e13051af4045e23e17b084c | Remediated all 12 audit findings from `argus-phase-1-remediation-002`: session-per-operation unit-of-work (no `AsyncSession` shared across concurrent tasks); explicit subscription-acknowledgement lifecycle with three independent recovery dimensions (stream/reconciliation/clock) so no single dimension can restore OK alone; structured task supervision (`IngestionManagerFailure`, fail-closed on any child-task death); finalization sweep wired into a real manager background loop; deterministic atomic commitment derivation (monotonic `sequence` column, `pg_advisory_xact_lock` serialization, full-same-level-state conflict validation, `commitment_observation_rejections` audit table); mechanical append-only enforcement at the database role layer; typed canonical provider response models (`argus.providers.models`) replacing provider-shaped dicts; usage records exactly one terminal outcome decided after decode/validation (including a visible signal on recorder failure); durable versioned `parse_attempts` ledger + `argus ingest reparse`; pagination continuity/ordering validation; a cancelled scheduler submission can never execute; and 4 genuine real-chain golden fixtures (of 9 required categories) sourced via this sandbox's working GitHub read access, imported through a new offline `argus fixtures import-real-chain`/`validate-real-chain` tool. 327 tests passing, 85% coverage, ruff+mypy clean, alembic downgrade-to-base/upgrade-to-head clean through migration 0005. STATUS `PARTIAL_REALCHAIN_FIXTURES_4_OF_9_CATEGORIES`: 26 of 27 mandatory acceptance criteria PASS; criterion 21 (real-chain golden fixtures) is honestly PARTIAL -- 4 of 9 required categories now genuinely real-chain evidenced, the remaining 8 (every DEX-swap-shaped category) are NOT TESTED since no repository searched embeds real swap-transaction bytes. See `orchestration/checkpoints/phase_1_remediation_2.md` for the full 27-item disposition and `tests/golden/fixtures/real/SEARCH_LOG.md` for the search log. NOT yet orchestrator-approved -- only the orchestrator may advance `last_orchestrator_approved_phase`. **Superseded by the remediation round 3 row below** -- an independent orchestrator audit (`argus-phase-1-remediation-003`) rejected round 2 as still insufficient; this row is kept unmodified as immutable history. |
| 1 (remediation round 3) | BUILD COMPLETE, AWAITING ORCHESTRATOR REVIEW (authorized by `argus-phase-1-remediation-003`, target `87a0e2efe329512a78f81331da24a85adf62bbbe`) | 81dd46cbfa3a46dd97c2f59a92ec62a42ab4fda9 | Remediated all 6 audit findings from `argus-phase-1-remediation-003`: evidence-bearing pagination boundary verification (a persisted boundary must be directly observed in the provider's own address-history sequence, never inferred from an empty/short page alone); every Helius RPC method's full nested contract validation now runs inside its single accounted usage operation (no malformed result can leave an "ok" usage row); streaming usage-recorder failures emit a visible `usage_recorder_failed` structured warning instead of disappearing via `contextlib.suppress`; `parse_attempts` durably records build/config/MASTER_SPEC/git identity (4 new NOT NULL CHECK-constrained columns, migration 0006, backed by a new `argus.config.git_commit_sha()` and `argus.parsing.generic_parser.PARSER_BUILD_HASH`); `sweep_finalization()` returns a typed `FinalizationSweepResult` distinguishing a genuine zero-promotion sweep from a provider/malformed-response/per-event-append failure, surfaced by the manager's own background loop; and 6 more genuine real-chain golden fixtures (of 9 required categories, now 7/9 total) sourced from `0xjeffro/tx-parser` (MPL-2.0). New `tests/integration/test_migrations.py` (6 tests) independently re-proves migration-from-zero/upgrade-from-0003/upgrade-from-0005/downgrade/idempotency/restart-safety against a disposable scratch database. 371 tests passing, 86% coverage, ruff+mypy clean, alembic downgrade-to-base/upgrade-to-head clean through migration 0006. STATUS `PARTIAL_REALCHAIN_FIXTURES_7_OF_9_CATEGORIES`: 17 of 18 mandatory acceptance criteria PASS; criterion 1 (real-chain golden fixtures) is honestly PARTIAL -- 7 of 9 required categories now genuinely real-chain evidenced, the remaining 2 ('multiple token-account/LP-style action', a genuinely failed transaction) are NOT TESTED since no repository searched (across either round) embeds either. See `orchestration/checkpoints/phase_1_remediation_3.md` for the full 18-item disposition and `tests/golden/fixtures/real/SEARCH_LOG.md` for the search log. NOT yet orchestrator-approved -- only the orchestrator may advance `last_orchestrator_approved_phase`. **Superseded by the remediation round 4 row below** -- an independent orchestrator audit (`argus-phase-1-remediation-004`) rejected round 3's 17/18 self-scoring as overstating fixture coverage and several runtime acceptance claims; this row is kept unmodified as immutable history. |
| 1 (remediation round 4) | BUILD COMPLETE, AWAITING ORCHESTRATOR REVIEW (authorized by `argus-phase-1-remediation-004`, target `a589e15c29937b140ae96bdfc2d75de62a9109c2`) | 9d51dcfbcf1c303da120d771cecda940ab51cf25 | Remediated all 8 audit findings from `argus-phase-1-remediation-004`: corrected real-chain fixture coverage from round 3's overstated 7/9 to the genuine 6/9 (`real_mainnet_ambiguous_multi_asset` renamed to `real_mainnet_dca_close_dual_asset_transfer_in` and excluded from the ambiguous category -- the parser resolves it decisively to TRANSFER_IN, not UNKNOWN); rebuilt real-chain fixture provenance to preserve exact upstream bytes (content-addressed `sources/` directory keyed by git blob SHA-1, an ordered hashed transform manifest, and independent offline rebuild-and-verify for all 10 fixtures); decoupled golden `expected_classification`/`expected_confidence` (now required, independently-asserted arguments) from the parser's own `observed_classification`/`observed_confidence`; deepened Helius contract validation (bool-as-int slot/blockTime/decimals rejection, `TokenAccountInfo` canonical model, non-object-transaction/missing-nested-field rejection) and fixed WebSocket ack matching (exact JSON-RPC id/version match, bounded connect/send/ack timeouts); made reparse selection and `swaps` versioning parser-artifact-aware (`parser_version` + `build_hash`, migration 0007, 6 new real-Postgres tests); removed the false historical-version `--parser-version` CLI flag in favor of an honest current-artifact-only design; made production git identity fail closed on a dirty/unverifiable checkout (`resolve_production_git_commit()`); and made a missing finalization source a typed `ok=False` misconfiguration instead of a false clean sweep. 420 tests passing, 86% coverage, ruff+mypy clean, alembic downgrade-to-base/upgrade-to-head clean through migration 0007. STATUS `PARTIAL_REALCHAIN_FIXTURES_6_OF_9_CATEGORIES`: 19 of 20 mandatory acceptance criteria PASS; criterion 5 (genuine ambiguous-transaction / failed-transaction fixtures) is honestly NOT TESTED/PARTIAL -- neither has been sourced in any round to date. See `orchestration/checkpoints/phase_1_remediation_4.md` for the full 20-item disposition and `tests/golden/fixtures/real/SEARCH_LOG.md` for the search log. NOT yet orchestrator-approved -- only the orchestrator may advance `last_orchestrator_approved_phase`. **Superseded by the remediation round 5 row below** -- an independent orchestrator audit (`argus-phase-1-remediation-005`) rejected round 4 outright (`FAIL_REMEDIATION_REQUIRED`) on 9 findings; this row is kept unmodified as immutable history. |
| 1 (remediation round 5) | BUILD COMPLETE, AWAITING ORCHESTRATOR REVIEW (authorized by `argus-phase-1-remediation-005`, target `2f436ae775c6185f820f59bc8dbef61ce0a95160`) | 6c7f4df1cce181dd54383b6dbb09f6be27df4471 | Remediated all 9 audit findings from `argus-phase-1-remediation-005` (which rejected round 4 outright, not merely PARTIAL, on 9 findings): replaced golden fixtures' flat `expected_classification`/`expected_confidence`/license strings with a typed, independently-reviewed `ExpectedOutcome` (wallet perspective, every asset delta, expected input/output, network fee, failed-tx status, confidence rule, reviewer method/rationale/evidence) and real `git ls-tree`-backed `GitTreeAttestation`/`LicenseEvidence` cryptographically binding upstream repo/commit/path/blob/license, folded into one `evidence_chain_hash` so any single-field edit is detectable offline; sourced real-chain fixtures for all 9 of 9 round-1-required categories (up from 6/9) -- a genuine failed on-chain transaction (`real_mainnet_failed_nft_sale`, via a new deterministic `extract_ts_const_export_default` transform step unlocking TypeScript-wrapped upstream sources) and a genuine multi-token-account Orca Whirlpool liquidity transaction (`real_mainnet_orca_increase_liquidity_multi_asset_outflow`, with an explicit documented caveat: it resolves via the ambiguous-multi-asset-outflow branch, not the `LP_ACTION` label), plus the previously-imported DCA-close fixture now genuinely satisfying the ambiguous-multi-asset category as a side effect of the parser fix below; made the generic parser fail-closed for ambiguous/NFT/LP/multi-hop assets (`SWAP_COMPLEX` no longer copy-eligible, decimals-zero legs never eligible, 2+ same-direction assets with no offsetting leg is `UNKNOWN` not a confident guess, new public `compute_asset_deltas()`); deepened Helius HTTP contract validation (strict-nonnegative-int slot/balance/fee fields, full accountKeys/preTokenBalances/postTokenBalances validation, `get_token_accounts` ownership cross-check and bounded decimals, immutable `TokenAccountInfo.raw`); fixed a WebSocket ack type-equality bug (`"id": true` could match request id 1 under Python's `==`), added early-notification buffering (a message arriving before the ack is preserved and replayed, never discarded), added a transport-level ping/pong liveness probe so a quiet-but-healthy connection is no longer reconnected on every receive-timeout, and bounded the close/cleanup path; fixed production git-identity override precedence (dirty/HEAD is now checked before an override is ever trusted, closing a spoofing path); and made migration 0007's downgrade fail closed with a precise reason when incompatible multi-build `swaps` data exists, rather than an opaque Postgres constraint violation, proven against a genuinely populated scratch database. 490 tests passing (up from 420), 87% coverage, ruff+mypy clean, alembic downgrade-to-base/upgrade-to-head clean through migration 0007 including new populated-data downgrade tests. STATUS `REALCHAIN_FIXTURES_9_OF_9_CATEGORIES_ONE_WITH_CAVEAT`: see `orchestration/checkpoints/phase_1_remediation_5.md` for the full acceptance-matrix disposition and `tests/golden/fixtures/real/SEARCH_LOG.md` for the complete search log. NOT yet orchestrator-approved -- only the orchestrator may advance `last_orchestrator_approved_phase`. **Superseded by the remediation round 6 row below** -- an independent orchestrator audit (`argus-phase-1-remediation-006`) rejected round 5 as `FAIL_REMEDIATION_REQUIRED` on 6 findings; this row is kept unmodified as immutable history. |
| 1 (remediation round 6) | BUILD COMPLETE, AWAITING ORCHESTRATOR REVIEW (authorized by `argus-phase-1-remediation-006`, target `fbe46c44861e489f65d55abac01eedc4934318a7`) | 6e4aa5a9a0e2cdb2f75f1465d3939e8d73002ba0 | Remediated all 6 audit findings from `argus-phase-1-remediation-006` (which rejected round 5 as `FAIL_REMEDIATION_REQUIRED`): production Git identity now distinguishes absent-Git from present-but-unverifiable-Git via an explicit `_GitCheckoutState` enum, closing a fail-open path where any `git status`/`rev-parse` failure on a genuinely present checkout was misread as "no checkout" and could accept an arbitrary override; fixture provenance now preserves a genuine offline-verifiable Git object chain (`GitTreeAttestation`/`attest_git_tree()`/`verify_git_object_chain()`, raw commit/tree object bytes, independently recomputed via git's own content-addressing) replacing round 5's self-referential saved `ls-tree` line; the golden oracle now preserves account-level deltas before by-mint aggregation (`compute_account_level_deltas()`/`ExpectedAccountAssetDelta`) and binds/checks record identity fields (category, chain, signature, slot, transaction_version, upstream_path) against the rebuilt payload rather than trusting them as inputs; the round-5 LP/multiple-account fixture was replaced (not relabeled) with `real_mainnet_orca_close_position_multi_account`, independently proven via account-level evidence to have two genuinely distinct material token accounts (see the ROUND 6 UPDATE note above); Helius HTTP validation deepened further (JSON-RPC envelope validation, `get_transaction` signature-identity binding, strict u64 numeric domains, ASCII-bounded raw-amount-string validation, `get_signature_statuses` required-key checks, deep alias-safe `_deep_freeze()` immutability replacing a shallow `MappingProxyType`); and the unattended watcher's pre-launch remote-freshness race is closed with a fresh final barrier (re-fetch + re-verify clean worktree, HEAD==remote, instruction-file hash-vs-committed-blob, instruction fields, target-commit, and phase authorization immediately before launch), reverting to `IDLE` (never consuming the instruction as `FAILED`) on any barrier failure. 547 tests passing (up from 490), 86% coverage, ruff+mypy clean, alembic downgrade-to-base/upgrade-to-head clean through migration 0007. STATUS: 19 of 20 mandatory acceptance-matrix items unconditional PASS, item 17 the standing permitted `DEFERRED_ENVIRONMENTAL_CHECK` for live Helius/PG17 connectivity -- see `orchestration/checkpoints/phase_1_remediation_6.md` section E for the full disposition. This round's own evidence cross-check (finding #6) also surfaced and honestly disclosed a pre-existing, previously-unreported commit-trailer-formatting defect (a trailing `Co-Authored-By`/`Claude-Session` paragraph breaks `git interpret-trailers`' recognition of an earlier `ARGUS-INSTRUCTION-ID:` paragraph as a real trailer on 3 of this round's own commits and 2 historical commits dating to rounds 1 and 5) -- see checkpoint section H; not corrected via history rewrite, reported for orchestrator disposition instead. **Phase 1 is now ORCHESTRATOR APPROVED** (`PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`) at this exact commit, per instruction `argus-phase-1-5-001` (`APPROVES_PHASE: 1`, independently audited, not the implementation agent's own PASS claim) -- see the row below for what that instruction authorized next; `docs/DECISION_LOG.md` records the approval decision. |
| 1.5 | BUILD COMPLETE, AWAITING ORCHESTRATOR REVIEW (authorized by `argus-phase-1-5-001`, target `2fbc566af74832bc6523648f60ba8cb60d98eb31`, `APPROVES_PHASE: 1`) | f334f70908e9744940571f7caffd29c515eb0dac | Phase 1.5 historical-data feasibility spike: established both required inputs automatically from already-reachable free/public sources (no `BOOTSTRAP_TOKEN_INPUT_REQUIRED`) -- a real pump.fun token (`5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump`, from its own creation transaction) and a real candidate wallet (`JAMESC37CTVoFEt7TAEcqBjdjAfAWZiPR1YdWotAFjeQ`, 14 real transactions spanning ~1 year across 4 protocols), both sourced from GitHub repositories already used and license-vetted by this project (`0xjeffro/tx-parser`, `quellen-sol/ingestooor`) since this session's proxy rejects GitHub's open-ended search API and general Solana RPC/BigQuery-credentialed egress is blocked/unavailable. Test A (early-buyer reconstruction) recovered exactly 1 real buyer (the token creator's own bundled dev-buy) -- honest, non-fabricated, but severely incomplete since no further buyer discovery is possible without a live RPC or indexed-dataset credential this sandbox lacks. Test B (wallet history) reconstructed the 14 real transactions via the unmodified existing Phase 1 parser, finding a genuine, disclosed 43% `UNKNOWN` classification rate on real lending/yield-position activity (a parser-completeness gap, not a data gap). Test C cross-validated 28 real transactions (the token tx + 14 candidate-wallet + 13 supplementary-wallet transactions from the same source) via an independent, from-scratch raw-evidence recomputation against `compute_account_level_deltas()`'s actual output: 28/28 agreements, 0 disagreements. Test D measured this spike's own offline cost (0 RPC calls, 0 credits, ~1MB evidence, sub-10ms processing) and gave an explicitly-labeled, theoretical linear-extrapolation scaling estimate (~501 RPC calls/wallet assumption -> ~50,100 for 100 wallets, ~501,000 for 1,000), declining to fabricate a dollar/credit cost with no documented per-call price table in this repository. `HISTORICAL_DATA_PATH = PASS_WITH_LIMITATIONS`, with both limitations (unproven acquisition breadth; the 43% classification gap) carried forward explicitly, not smoothed over; `FAIL` was considered and rejected since a genuine (if minimal) result was recovered and the downstream interpretation architecture is positively proven correct. 551 tests passing (up from 547), ruff+mypy clean. No schema migration, no Phase 2 work, no credential entered/disclosed. See `orchestration/checkpoints/phase_1_5.md` for the full 14-item disposition and `orchestration/phase_1_5/evidence/PROVENANCE.md` for complete evidence citations. `last_orchestrator_approved_phase` remains `1` (only the orchestrator may advance it to `1.5`) -- this instruction's own explicit requirement. **Superseded by the remediation round 1 row below** -- an independent orchestrator audit (`argus-phase-1-5-remediation-001`) rejected this submission as `FAIL_REMEDIATION_REQUIRED` on one SPEC_BLOCKING/SAFETY_OR_INTEGRITY_BLOCKING finding; this row is kept unmodified as immutable history. |
| 1.5 (remediation round 1) | BUILD COMPLETE, AWAITING ORCHESTRATOR REVIEW (authorized by `argus-phase-1-5-remediation-001`, target `b68e37393370c7f9f3eb8860fecdaaa3f9c28696`, `APPROVES_PHASE: NONE`) | 3aa61b4d220c3211e4dca1ca46b18b1ab510376e | Remediated the one SPEC_BLOCKING/SAFETY_OR_INTEGRITY_BLOCKING finding from `argus-phase-1-5-remediation-001`: two authentic non-trade transactions (a real Solend `Withdraw Obligation Collateral and Redeem Reserve Collateral`, a real xStep `Stake`) were reported `SWAP_SIMPLE`/`is_copy_eligible=true` solely because each has a clean one-negative/one-positive balance shape -- confirmed via `git stash` that the pre-fix parser genuinely returned `is_copy_eligible=True` for the real Solend transaction. Added a deterministic **positive semantic proof gate** to `src/argus/parsing/generic_parser.py`: a new, centrally versioned `_SUPPORTED_SWAP_PROGRAM_IDS` registry of 4 program IDs (Jupiter Aggregator V6, Raydium Liquidity Pool V4, Orca Whirlpool, pump.fun), each independently cross-checked against this project's own already-hand-reviewed permanent golden-fixture evidence before being added; `ParsedTransaction.is_copy_eligible` now additionally requires positive instruction-level evidence (`matched_swap_program_id is not None`) that the transaction's own top-level or inner instructions actually invoked a registered trade venue -- a narrow allowlist/proof gate, not a Solend/xStep denylist, so any other unsupported program (present or future) correctly stays research-only rather than requiring a new denylist entry. `PARSER_VERSION` bumped to `generic_balance_delta_v2` (observable eligibility output changed for real evidence). Both named false positives are now ineligible; all 4 permanent golden real-chain fixtures already marked eligible before this round remain eligible (independently re-verified against the new gate, not merely re-asserted). Reran the Phase 1.5 analysis under the corrected parser: delta-arithmetic agreement (28/28) is now reported separately from semantic eligibility validation (4/28 copy-eligible, each with its cited program) so the two claims are never conflated; `HISTORICAL_DATA_PATH = PASS_WITH_LIMITATIONS` unchanged, now resting on a corrected foundation. 8 new golden-fixture tests plus 2 new Phase 1.5 tests (10 new; 563 total, up from 553 before the fix's own delta -- see checkpoint for the exact breakdown), ruff+mypy clean, no schema change, no credential entered/disclosed. See `orchestration/checkpoints/phase_1_5_remediation_1.md` for the full 14-item disposition. `last_orchestrator_approved_phase` remains `1` -- this remediation approves no phase. **Superseded by the remediation round 2 row below** -- an independent orchestrator audit (`argus-phase-1-5-remediation-002`) rejected round 1's gate as still insufficient (program identity mistaken for swap-instruction identity); this row is kept unmodified as immutable history. |
| 1.5 (remediation round 2) | BUILD COMPLETE, AWAITING ORCHESTRATOR REVIEW (authorized by `argus-phase-1-5-remediation-002`, target `5d85848ab5bff397a192a0868ffcf1077b691706`, `APPROVES_PHASE: NONE`) | f4ed7893849128257b3b5e62f44b93b779ee50c8 | Remediated the one SPEC_BLOCKING/SAFETY_OR_INTEGRITY_BLOCKING finding from `argus-phase-1-5-remediation-002` (`P15-R2-001`): round 1's gate proved only that *some* instruction invoked an allowlisted program, never that the matched instruction was itself a swap -- reproduced directly against `TARGET_COMMIT`'s real code (all 6 representative adversarial probes genuinely returned `is_copy_eligible=True` pre-fix, including the instruction's own Orca/Raydium/pump.fun + non-swap-log audit probe). Replaced `_SUPPORTED_SWAP_PROGRAM_IDS` with a **program-AND-instruction-discriminator registry** (`_SWAP_INSTRUCTION_REGISTRY`) binding the resolved program ID, the SAME instruction's own decoded `data`, and an exact registered discriminator to one canonical instruction object; added a strict, local, bounded base58 decoder (`_decode_base58_strict`, fixed alphabet, canonical round-trip validation, no new dependency); extended `ParsedTransaction` with `matched_semantic_label`/`matched_discriminator_hex` (all three fields now required for `is_copy_eligible`). All 4 registry pairs (Jupiter V6 `shared_accounts_route`, Raydium LP V4 `swap_base_in`, Orca Whirlpool `swap`, pump.fun `buy`) independently derived by decoding each cited authentic fixture's own raw instruction data -- never from memory or documentation; the real Orca `DecreaseLiquidity`/`CollectFees`/`ClosePosition` non-swap discriminators (from `real_mainnet_orca_close_position_multi_account.json`) are proven absent from the registry. Honest disclosure: `suppl_13_titan_swap_with_fees_2.json`, eligible under round 1's program-only check, correctly becomes ineligible under round 2 -- its actual Raydium invocation's discriminator (`0x10`) is not the registered `swap_base_in` (`0x09`); the instruction explicitly permits this ("failing closed is required"). Added all T1-T11 required tests (T1 missing data, T2 non-swap discriminator including the authentic Orca bytes verbatim, T3 program/discriminator mismatch, T4 log-text-cannot-grant-eligibility, T5 Solend/xStep extended to assert no semantic match at all, T6 fixed independent oracle against every registry pair, T7 altered-evidence-fails-closed, T8 malformed-base58, T9 regression sweep, T10 deterministic reparse, T11 a hand-written Phase 1.5 oracle that does not import the production registry). `PARSER_VERSION` bumped to `generic_balance_delta_v3`. 613 tests passing (up from 563: golden 95 (was 46), phase_1_5 7 (was 6)), ruff+mypy clean, no schema change, no credential entered/disclosed. See `orchestration/checkpoints/phase_1_5_remediation_2.md` for the full 14-item disposition. `last_orchestrator_approved_phase` remains `1` -- this remediation approves no phase. |

## Operational tooling

- `scripts/argus_orchestrator_watch.py` (`make orchestrator-watch`) — local
  "no-nudge" watcher: polls `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` for
  a new `ACTIVE` instruction and, when one appears and passes the
  TARGET_COMMIT and phase-authorization checks, launches the local Claude
  CLI non-interactively to execute exactly that instruction under
  `orchestration/PROTOCOL.md`. Not running by default — the human operator
  starts it explicitly. See `docs/OPERATIONS.md` for usage.
  Evidence history:
  - `orchestration/checkpoints/watcher_setup.md` — original build/test record.
  - `orchestration/checkpoints/watcher_remediation.md` — a four-defect
    remediation pass (AUTHORIZED_PHASE was never validated; handoff
    instruction-id matching used substring containment instead of exact
    equality; checkpoint/bundle evidence was only checked for existence;
    a crash between CLAIMED and RUNNING was never recovered on restart).
  - `orchestration/checkpoints/watcher_remediation_2.md` — a second,
    orchestrator-requested remediation pass (instruction
    `argus-watcher-remediation-002`), rejecting the first pass as
    insufficient and requiring: strict fail-closed state handling
    (including a handoff-cross-check on state loss); a failed Claude
    process now always fails the run before any evidence is considered;
    evidence must be newly added, immutable, and structurally valid (not a
    placeholder); branch-movement/merge-commit/commit-attribution
    (`ARGUS-INSTRUCTION-ID:` trailer) verification; a blob-hash check that
    mechanically prevents the implementation agent from modifying
    `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` during a run; explicit
    string-sequence phase gating (`0, 1, 1.5, 2, ..., 6, 6.5, ..., 11`) via
    a new `APPROVES_PHASE` field; strict instruction-field parsing; and a
    conservative, ordered post-run verification sequence. 26 new/updated
    adversarial regression tests.
  - `orchestration/checkpoints/watcher_remediation_3.md` — a third,
    orchestrator-requested remediation pass (instruction
    `argus-watcher-remediation-003`), rejecting round 2 as still fail-open
    in several places and requiring: a terminal, non-retryable
    `QUARANTINED` state (with a manual `--reset-quarantine` recovery
    procedure) the moment the instructions file is found modified —
    checked first and unconditionally, closing a bypass where a
    self-authored next instruction could otherwise launch on a later tick;
    tightened `TARGET_COMMIT` provenance (exactly one instruction-only
    commit whose parent is exactly the target; no `TARGET_COMMIT == HEAD`;
    no multi-commit or merge gaps); every safety-critical Git read now
    fails closed (`None`/explicit-failure) rather than defaulting to
    empty/clean/absent on a command error; commit attribution via a real
    `git interpret-trailers`-parsed terminal trailer, not text anywhere in
    body prose; broadened launch-exception handling that never leaves a
    stale `RUNNING` state, with raw Claude subprocess output never logged
    at all (only whitelisted metadata); real canonical-UTC timestamp
    parsing (not shape-only regex) for both instructions and handoffs; and
    tightened evidence linkage (exact checkpoint-bytes embedding in the
    bundle, exactly-once/full-SHA checkpoint identity fields, handoff
    `CURRENT_PHASE` matching `AUTHORIZED_PHASE`, required section
    headings). 74 total watcher tests (up from 51). This is operational
    tooling, not ARGUS phase work — `current_phase` above is unaffected.
  - Phase 1 remediation round 6 (instruction
    `argus-phase-1-remediation-006`, finding #5) added a final, fresh
    pre-launch remote-freshness barrier: `tick()`'s old
    `head_before`/`git_remote_head()` comparison read only the locally
    cached `origin/{branch}` ref set by the tick's early fetch, stale by
    however long instruction/target-commit/phase validation took. A new
    barrier performs a fresh fetch immediately before transitioning to
    `RUNNING`/launching Claude and re-verifies fetch success, worktree
    cleanliness, HEAD==freshly-fetched-remote-HEAD, an explicit
    working-tree-hash-vs-committed-blob snapshot of
    `ORCHESTRATOR_INSTRUCTIONS.md`, unchanged instruction fields,
    target-commit provenance, and phase authorization; any failure
    reverts to `IDLE` (never `FAILED`) without consuming the instruction,
    so the next tick freely re-evaluates. 77 total watcher tests (up
    from 74), including 3 new deterministic tests confirmed via `git
    stash` to genuinely launch Claude against the pre-fix watcher. This
    is operational tooling, not ARGUS phase work — `current_phase` above
    is unaffected.

## Rules

- This file may be updated by the implementation agent to reflect actual build
  progress.
- `last_orchestrator_approved_phase` and `approved_commit` may ONLY be set to a
  new value after receiving **explicit** orchestrator approval for that phase.
  The implementation agent must never self-approve a phase here.
- Do not begin work on `current_phase + 1` while `awaiting_orchestrator_review`
  is `true` for the current phase.
