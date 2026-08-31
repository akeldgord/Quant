# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0014-phase-1-5
UTC_TIMESTAMP: 2026-08-31T21:28:18Z
CURRENT_COMMIT: f334f70908e9744940571f7caffd29c515eb0dac
CURRENT_PHASE: 1.5
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-1-5-001
CHECKPOINT_PATH: orchestration/checkpoints/phase_1_5.md
BUNDLE_PATH: orchestration/bundles/phase_1_5.txt
TEST_STATUS: 4 new Phase 1.5 tests passed, 0 failed; full repository suite 551/551 passed, 0 failed, 0 unexplained skipped (real PostgreSQL 16); ruff clean; mypy clean
WORKING_TREE: clean (verified via `git status --porcelain` before this commit)
ORCHESTRATOR_REVIEW_REQUIRED: (1) whether `HISTORICAL_DATA_PATH = PASS_WITH_LIMITATIONS` is an acceptable disposition to authorize Phase 2, or whether the two named limitations (Test A's unproven data-acquisition breadth beyond 1 recovered buyer; Test B's disclosed 43% parser `UNKNOWN` rate on real lending/yield-position activity) require further spike work first -- see checkpoint sections G and N. (2) Whether closing `LIVE_HELIUS_RPC_VALIDATION`/`LIVE_HELIUS_WSS_VALIDATION` (a real credential) or the newly-named `BQ_PUBLIC_DATASET_ACCESS` (a GCP project/credential) should be prioritized before Phase 2, since Test A's core limitation traces directly to both being closed.

## Work completed

Executed orchestrator instruction `argus-phase-1-5-001` in full. This
instruction did two things: (1) recorded the orchestrator's independent
approval of Phase 1 (`PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION` at
commit `2fbc566af74832bc6523648f60ba8cb60d98eb31`) and granted a
one-time waiver for round 6's disclosed commit-trailer-formatting
defect; (2) authorized the Phase 1.5 historical-data feasibility spike.

1. **Phase 1 approval recorded.** `docs/BUILD_STATE.md`'s
   `last_orchestrator_approved_phase` is now `1` and `approved_commit`
   is `2fbc566af74832bc6523648f60ba8cb60d98eb31`, per this instruction's
   explicit direction (section 6 of its "Mandatory session start") --
   this is the orchestrator's own recorded approval, not a
   self-approval.
2. **Both required Phase 1.5 inputs established automatically**, from
   already-reachable free/public sources only (no
   `BOOTSTRAP_TOKEN_INPUT_REQUIRED`): a verified historical token
   (`5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump`, a real pump.fun
   token, from its own creation transaction) and a verified candidate
   wallet (`JAMESC37CTVoFEt7TAEcqBjdjAfAWZiPR1YdWotAFjeQ`, 14 real
   transactions spanning ~1 year across 4 DeFi protocols). Discovery
   method: since general Solana RPC egress is proxy-blocked, BigQuery
   requires a GCP credential this sandbox lacks, and GitHub's
   open-ended search API is rejected as session-scoped, both inputs
   were found by systematically indexing the full embedded
   test-transaction corpora (183 files total) of two GitHub
   repositories already used and license-vetted by this project
   (`0xjeffro/tx-parser`, `quellen-sol/ingestooor`) by fee-payer wallet
   and token mint.
3. **Test A (early-buyer reconstruction):** recovered exactly 1 real
   buyer -- the token creator's own initial dev-buy, bundled into the
   creation transaction itself. Genuine and non-fabricated, but far
   short of a usable buyer cohort: no further buyer discovery is
   possible without a live RPC/indexed-dataset credential this sandbox
   lacks.
4. **Test B (wallet-history reconstruction):** run through the
   existing, unmodified Phase 1 generic parser
   (`argus.parsing.generic_parser`). Found a genuine, disclosed 43%
   `UNKNOWN` classification rate on this wallet's real lending/yield-
   position activity -- the parser has no dedicated position-lifecycle
   classification distinct from plain transfers, a concrete
   completeness gap, not a data-availability gap (the underlying
   balance-delta arithmetic was independently proven correct
   regardless -- see Test C).
5. **Test C (cross-validation):** 28 real transactions independently
   cross-validated -- 28 agreements, 0 disagreements -- via a
   from-scratch recomputation of each wallet's raw balance deltas
   written directly against raw evidence, never calling into
   `argus.parsing`, compared against `compute_account_level_deltas()`'s
   actual output. Exceeds the required minimum of 20 without
   decomposing any single record into artificial sub-claims.
6. **Test D (cost/scaling):** measured this spike's own entirely-
   offline cost (0 RPC calls, 0 provider credits, ~926KB raw evidence,
   ~6ms processing) and produced an explicitly theoretical,
   clearly-labeled linear-extrapolation scaling estimate to 100/1,000
   wallets, declining to fabricate a dollar/credit figure since no
   per-call Helius price table exists anywhere in this repository.
7. **Conclusion:** `HISTORICAL_DATA_PATH = PASS_WITH_LIMITATIONS`.

Full per-test detail, the complete 14-item required-contract
disposition, and every command actually run:
`orchestration/checkpoints/phase_1_5.md`.

## Important findings

- Both source repositories used for this spike are protocol/instruction
  **parser test suites**, not historical-data archives -- their
  fixtures exist to exercise distinct code paths for their own
  maintainers, not to capture one wallet's or token's continuous
  history. The two multi-transaction wallets used here were found by
  systematically indexing all 183 embedded transactions across both
  repositories by fee-payer wallet and token mint, not because either
  repository intentionally documents a wallet history -- disclosed
  directly in checkpoint section H, not presented as a designed
  dataset.
- No two files in either repository's full corpus share a non-major
  token mint (checked directly across 8 distinct pump.fun-labeled
  fixtures) -- confirming no GitHub-embedded multi-buyer-per-token
  dataset exists in the sources reachable from this sandbox.
- BigQuery (`bigquery.googleapis.com`) is reachable at the network/
  proxy layer -- unlike every general Solana RPC/market-data host
  tested (all proxy-denied with HTTP 403) -- but requires a GCP
  project + credential this sandbox does not have and this
  implementation agent may not create or enter. This is a newly
  identified, previously-untracked environmental deferral
  (`BQ_PUBLIC_DATASET_ACCESS`), distinct from the existing
  `LIVE_HELIUS_RPC_VALIDATION`/`PG17_COMPOSE_VALIDATION` items.
- `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is unchanged -- still
  the orchestrator's `argus-phase-1-5-001` instruction,
  `STATUS: ACTIVE`. `last_orchestrator_approved_phase` remains `1`
  (recording the orchestrator's own Phase 1 approval, per this
  instruction's explicit direction) and is **not** advanced to `1.5` --
  this task did not and could not self-approve Phase 1.5.
- All new commits this run carry the sole final trailer paragraph
  `ARGUS-INSTRUCTION-ID: argus-phase-1-5-001`, verified via
  `git interpret-trailers --parse` before each push (per this
  instruction's explicit disposition on round 6's disclosed
  commit-trailer defect).
- No `src/argus` production code was changed; no schema migration was
  created; no existing golden/real-chain fixture was touched --
  confirmed via `git diff --stat -- tests/golden` against the pre-spike
  commit.

## Failures or limitations

- **Test A's early-buyer recovery is severely incomplete** (1 of an
  unknown, likely much larger, cohort) -- an environmental/credential
  limitation (no live RPC or indexed-dataset access), not a claim that
  the RPC-signature-enumeration architecture itself is unsound. Not
  claimed as PASS; carried forward explicitly as the primary limitation
  behind `PASS_WITH_LIMITATIONS`.
- **Test B's 43% `UNKNOWN` classification rate on real lending/yield-
  position activity** is a genuine, measured parser-completeness gap,
  disclosed in `HARDENING_BACKLOG` (checkpoint section K), not adopted
  as a new Phase 1.5 blocking criterion per the instruction's own
  "no moving goalposts" policy.
- **Test D's scaling estimate is explicitly theoretical**, not
  empirically measured (this spike made zero live RPC calls); no
  dollar/credit cost is offered at all, since no per-call price table
  exists in this repository.
- `LIVE_HELIUS_RPC_VALIDATION`/`LIVE_HELIUS_WSS_VALIDATION`/
  `PG17_COMPOSE_VALIDATION` remain `DEFERRED_ENVIRONMENTAL_CHECK`,
  unchanged, re-confirmed once this session per the instruction's "do
  not repeatedly probe" rule.
- New this session: `BQ_PUBLIC_DATASET_ACCESS = DEFERRED_ENVIRONMENTAL_CHECK`
  (see Important findings above).

## Deferred checks

- Live Solana RPC/WebSocket connectivity against a real `HELIUS_API_KEY`.
- `PG17_COMPOSE_VALIDATION` (unchanged, unrelated).
- `BQ_PUBLIC_DATASET_ACCESS` (new this session -- requires an
  operator-supplied `BIGQUERY_PROJECT_ID`/service-account credential,
  never entered by the implementation agent).
- The two `PASS_WITH_LIMITATIONS` limitations themselves (see
  `ORCHESTRATOR_REVIEW_REQUIRED` above).

## Exact next action requested from orchestrator

Review this spike's evidence (`orchestration/checkpoints/phase_1_5.md`
and `orchestration/bundles/phase_1_5.txt`) against instruction
`argus-phase-1-5-001`'s required contract, and resolve the two open
items in `ORCHESTRATOR_REVIEW_REQUIRED` above. If Phase 1.5 is accepted,
write the next `ACTIVE` instruction into
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md` (`TARGET_COMMIT` pinned to
the exact commit named in this handoff) to authorize Phase 2 or further
Phase 1.5 work. Phase 2 remains forbidden until then. Until a new
instruction exists, the watcher (if running) takes no action beyond
logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** unchanged from prior handoffs — if you
cloned/fetched this branch before 2026-08-30T22:35 UTC, re-clone or
`git fetch --all && git reset --hard origin/claude/argus-folder-setup-77ahrk`
rather than merging/rebasing the old (pre-rewrite) history.
