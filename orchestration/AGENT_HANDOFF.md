# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0022-phase-3-remediation-2
UTC_TIMESTAMP: 2026-09-01T08:15:00Z
CURRENT_COMMIT: PLACEHOLDER_FILLED_IN_SECOND_COMMIT
CURRENT_PHASE: 3
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-3-remediation-002
CHECKPOINT_PATH: orchestration/checkpoints/phase_3_remediation_2.md
BUNDLE_PATH: orchestration/bundles/phase_3_remediation_2.txt
TEST_STATUS: 27/27 unit `test_phase3_wallet_qualification.py` passed (was 23/23, +4 new P3-R3/P3-R5 tests); 79/79 unit `test_orchestrator_watch.py` passed; 22/22 new focused tests for this instruction passed; 14/14 integration `test_phase3_wallet_qualification.py` passed (was 7/7, +7 new: 1 P3-R1/P3-R2, 6 P3-R6b); 6/6 new integration `test_wallet_acquisition.py` passed; 17/17 integration `test_migrations.py` passed (was 13/13, +4 new P3-R6a tests); 112/112 golden+replay+phase_1_5 passed; 95/95 integration suite passed (was 78); full repository suite 759/759 passed (up from 738), 0 failed, 0 unexplained skipped; ruff clean; ruff format clean (219 files); mypy clean (112 source files); alembic head 0015; 12/12 real-chain fixtures ok; secret scan clean on this round's 20 changed files; populated-0010-preservation/already-0011-upgrade/zero-to-head/safe-repeat-upgrade migration tests all pass -- ALL RAW COMMAND OUTPUT (not narrative claims) embedded verbatim in the paired bundle, per this instruction's own E1 requirement
WORKING_TREE: clean (verified via `git status --porcelain` before this commit)
ORCHESTRATOR_REVIEW_REQUIRED: whether this second remediation (checkpoint sections B-S) genuinely closes every finding named by `argus-phase-3-remediation-002`'s frozen requirement-to-evidence matrix and seven-part justification table -- in particular the P3-R6a migration data-loss regression, the P3-R1/P3-R2/P3-R3/P3-R5/P3-R6b continuations, and whether the E1 raw-evidence requirement is now genuinely satisfied (not narrative claims) -- and whether the unchanged `PHASE_3_CANDIDATE_SAMPLE_BLOCKED` sample-report disposition remains appropriate. This session does not and cannot apply Phase 3 approval itself.

## Work completed

Executed orchestrator instruction `argus-phase-3-remediation-002` in
full: independently verified all safety gates (single instruction-only
commit `9389b7cc98d1202f480ccb00cb2d88f686ea0283` whose parent exactly
matches `TARGET_COMMIT` `3fb7d5675bf4b6c1c497dad08eb319a0e349d188` and
changes only `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`;
`AUTHORIZED_PHASE: 3` vs. `docs/BUILD_STATE.md`'s `current_phase: 3`
(never skip ahead); clean worktree; local HEAD equal to
freshly-fetched remote HEAD; Phase 3 awaiting review and not marked
approved) before any code was touched, then closed every finding named
by the instruction's own frozen requirement-to-evidence matrix, in the
instruction's own mandatory order:

- **P3-R6a** (migration 0011 destructively deleted all Phase 3 decision
  history): removed the 4 `DELETE`/1 `UPDATE` statements from 0011's
  `upgrade()` (amended in place, explicit narrow change-control
  authorization -- still UNAPPROVED); made the 3 new provenance columns
  nullable; new migration `0012` widens the same columns for a database
  (this sandbox's own dev DB) already stamped 0011 under its original
  destructive form.
- **P3-R1/P3-R2 continued**: one shared `_filter_swaps_by_as_of()` step
  now feeds history assessment, position reconstruction, and scoring
  identically, persisting future-timestamp exclusions with an explicit
  reason; a real `run_wallet_acquisition`/`load_verified_acquisition_
  manifest` path (new `acquisition.py`, new `wallet_acquisition_runs`
  table) replaces the CLI's arbitrary-JSON-file acceptance entirely.
- **P3-R3/P3-R5 continued**: an immutable `swap_id` final sort tie-break;
  currency-valued aggregates gated to `None` on mixed quote assets;
  `max_drawdown` gated to `None` (never a crash) on any unknown
  `final_exit_at`, with `round_trip_index` as a stable same-token tie-
  break.
- **P3-R6b continued**: `Numeric(20,15)` score storage plus explicit
  in-service quantization to that exact precision before any consumer
  sees the value; a new `history_id` FK binding score identity to the
  exact acquisition/history manifest that justified it; score, history,
  AND position idempotency searches rewritten from "latest row" to "full
  scoped-content match" (the position case was found during this round's
  own adversarial test-writing -- same bug class, not separately named);
  tier lifecycle now computes the FROM-state as "the tier as of `now`,"
  never the wallet's global-latest tier, with an exact-replay guard.
- **E1**: this handoff's paired bundle
  (`orchestration/bundles/phase_3_remediation_2.txt`) embeds the raw
  stdout and exit status of every required command verbatim, not a
  narrative PASS-count claim.

## Important findings

- **One additional real defect was found and fixed via this round's own
  adversarial test-writing, not separately named in the instruction's own
  finding list but covered by its own acceptance-criteria text
  ("identical invocation writes no duplicate score/position/tier row")**:
  the `wallet_positions` write path had the identical "latest row by
  `created_at` only" idempotency-search defect the instruction explicitly
  named for scores and history rows. An out-of-order replay (a later,
  complete `now` persisted before an earlier, partial `now` is replayed)
  could leave the single latest row holding content for a DIFFERENT
  `now`, causing a spurious duplicate row on a subsequent exact re-replay.
  Fixed identically to the score/history searches (full scoped-content
  match across all candidate rows), proven by
  `test_p3r6b_position_full_match_search_prevents_duplicate_on_out_of_
  order_replay`.
- Migration `0011`'s original committed form (from round 1) genuinely
  deleted this sandbox's own disposable local dev database's Phase 3
  decision rows earlier in this session, before this round's fix landed
  -- disclosed explicitly in the migration file, checkpoint section C,
  and `docs/DECISION_LOG.md`. No other environment was affected; no
  recomputation is claimed to restore the original beliefs.
- `NUMERIC(20,15)` still rounds a value with more than 15 fractional
  digits on Postgres storage; Python's default Decimal division context
  can produce up to 28 significant digits. Rather than leave the
  in-memory "returned" value unrounded while the DB silently rounds on
  storage (which would make "stored/returned/tier-used exactly" false
  for a sufficiently deep score), the service now explicitly quantizes
  to the column's own 15-fractional-digit precision immediately after
  computing the score, before any consumer sees it.
- `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is unchanged -- still the
  orchestrator's `argus-phase-3-remediation-002` instruction, `STATUS:
  ACTIVE`. Phase 3 is NOT marked approved anywhere in this run's
  evidence; `last_orchestrator_approved_phase` is `2` (unchanged), never
  `3`.
- Both commits this run (the primary work commit and the follow-up
  commit-hash-fill-in commit) carry the sole final trailer paragraph
  `ARGUS-INSTRUCTION-ID: argus-phase-3-remediation-002`, with no
  paragraph after it, verified via `git interpret-trailers --parse`
  before push.

## Failures or limitations

- None new this round. Every finding named by
  `argus-phase-3-remediation-002`'s frozen requirement-to-evidence
  matrix is closed; no `HARDENING_BACKLOG` item from either round was
  pulled into scope.
- `LIVE_HELIUS_RPC_VALIDATION`/`LIVE_HELIUS_WSS_VALIDATION`/`PG17_
  COMPOSE_VALIDATION`/`BQ_PUBLIC_DATASET_ACCESS` remain `DEFERRED_
  ENVIRONMENTAL_CHECK`, unchanged, not reopened this round.

## Deferred checks

- All items under "Failures or limitations" above.

## Exact next action requested from orchestrator

Independently re-audit this second remediation
(`orchestration/checkpoints/phase_3_remediation_2.md`,
`orchestration/bundles/phase_3_remediation_2.txt`) against every finding
named by `argus-phase-3-remediation-002`'s own frozen requirement-to-
evidence matrix and seven-part justification table. In particular:
whether the P3-R6a migration fix genuinely preserves prior decision
history through both a fresh install and this sandbox's own
already-0011-stamped case; whether the P3-R1/P3-R2/P3-R3/P3-R5/P3-R6b
continuations genuinely close each remaining defect; whether the E1
raw-command-evidence requirement is now genuinely satisfied (raw stdout
plus exit status, not narrative pass counts); and whether the unchanged
`PHASE_3_CANDIDATE_SAMPLE_BLOCKED` disposition remains acceptable (both
prior instructions already accepted it as non-blocking). Only the
orchestrator may apply Phase 3 approval; write the next `ACTIVE`
instruction into `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`
(`TARGET_COMMIT` pinned to the exact commit named in this handoff) to do
so, or to require further remediation. Phase 4 remains forbidden until
then. Until a new instruction exists, the watcher (if running) takes no
action beyond logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** unchanged from prior handoffs — if you
cloned/fetched this branch before 2026-08-30T22:35 UTC, re-clone or
`git fetch --all && git reset --hard origin/claude/argus-folder-setup-77ahrk`
rather than merging/rebasing the old (pre-rewrite) history.
