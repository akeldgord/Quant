# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0020-phase-3
UTC_TIMESTAMP: 2026-09-01T04:41:00Z
CURRENT_COMMIT: f2e69423c1f93beb657ccc0bc415828ac2de046b
CURRENT_PHASE: 3
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-3-001
CHECKPOINT_PATH: orchestration/checkpoints/phase_3.md
BUNDLE_PATH: orchestration/bundles/phase_3.txt
TEST_STATUS: 535/535 unit passed (test_phase3_wallet_qualification.py 12/12 new); 74/74 integration passed (real PostgreSQL 16, incl. test_phase3_wallet_qualification.py 3/3 new); 112/112 golden+replay+phase_1_5 passed; full repository suite 721/721 passed (up from 706), 0 failed, 0 unexplained skipped; ruff clean; ruff format clean; mypy clean (110 source files); 12/12 real-chain fixtures ok; secret scan clean on this run's changed files; migration-from-zero/upgrade-from-0009/downgrade-then-reupgrade clean through 0010
WORKING_TREE: clean (verified via `git status --porcelain` before this commit)
ORCHESTRATOR_REVIEW_REQUIRED: whether the Phase 3 build (checkpoint sections B-N) satisfies MASTER_SPEC Phase 3's frozen 8-item acceptance disposition and the 9 required test categories, and whether the honest `PHASE_3_CANDIDATE_SAMPLE_BLOCKED` five-wallet sample report (checkpoint section D, `orchestration/phase_3/SAMPLE_REPORT.md`) is an acceptable disposition of that requirement given this sandbox's unchanged live-provider-access limitation. This session does not and cannot apply Phase 3 approval itself.

## Work completed

Executed orchestrator instruction `argus-phase-3-001` in full:
independently verified all safety gates (instruction-only commit
`c4adf963ed3a0cae815867b6cc97b6aa5b47f48a` whose parent exactly matches
`TARGET_COMMIT` `a13ba2ab8729a08de3c571b7b12c32cc3f14c56b` and changes
only `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`; `AUTHORIZED_PHASE: 3`
vs. `docs/BUILD_STATE.md`'s `current_phase: 2` (never skip ahead --
`AUTHORIZED_PHASE <= current_phase + 1`); clean worktree; local HEAD
equal to freshly-fetched remote HEAD; Phase 2 awaiting orchestrator
review and not marked approved) before any code was touched, then built
the full Phase 3 scope: wallet history reconstruction/completeness,
Decimal-exact V1 weighted-average-cost position reconstruction, position
confidence, the structural discovery-contamination firewall, the frozen
V1 qualification-score weights/sample-size gate with deterministic
shrinkage, lottery-dominance flagging, recency decay, initial wallet-
cluster-link evidence consumption, and the full tier lifecycle -- all
wired through a real `argus wallets reconstruct-and-score` CLI command.

**Schema**: migration `0010_phase3_wallet_reconstruction_and_
qualification.py` -- 6 new tables (`wallet_history_quality`,
`wallet_positions`, `wallet_metrics_snapshots`, `wallet_score_snapshots`,
`wallet_tier_history`, `wallet_cluster_links`) plus `wallets.current_
tier`, least-privilege role grants throughout. See checkpoint section C.

**Discovery-contamination firewall (phase-blocking)**: `score_wallet()`
computes `qualification_score` from a separately-filtered position set
that structurally never contains a discovery-contaminated token, and
`descriptive_score` from an independent full pass -- proven byte-
identical/measurably-different at both the pure-function and real-
Postgres-service level. See checkpoint section E.

**All 9 required test categories pass** (12 unit + 3 integration tests
against real Postgres). See checkpoint sections F-J.

**Five-wallet sample report**: `orchestration/phase_3/SAMPLE_REPORT.md`
honestly reports `PHASE_3_CANDIDATE_SAMPLE_BLOCKED` -- only 1 genuine
candidate wallet exists in this sandbox from already-authorized
authentic evidence, with zero real `swaps` evidence for it
(`history_completeness=UNKNOWN`, `qualification_score=descriptive_
score=50.00`, the honest neutral prior). The frozen thresholds were not
loosened and no wallet history was fabricated to reach 5. See checkpoint
section D.

## Important findings

- **Two real financial-logic defects were found and fixed via this run's
  own required-test-writing, before any evidence was recorded** (not
  caught by an external audit): (1) the descriptive score's median-based
  `selection_skill` formula was, by design, robust to a single extreme
  contaminated winner, defeating the required-test-1 fixture's premise
  -- fixed by using the plain arithmetic mean for the descriptive-only
  pass (qualification keeps the outlier-resistant median); (2) a
  completeness-only sample-gate failure (LOW/UNKNOWN completeness on an
  otherwise-large sample) produced zero shrinkage, since `position_
  fraction`/`token_fraction` were each already capped at 1 -- fixed by
  adding an explicit `completeness_fraction` term to the shrinkage
  product. See checkpoint section K for the full defect-to-fix mapping.
- **A third, non-financial defect was found while re-running the full
  repository suite**: two pre-existing Phase 2 integration-test helpers
  (`_cleanup_wallets()`/`_cleanup_token()` in `tests/integration/
  test_phase2_discovery.py`) did not know about the 6 new Phase 3 child
  tables, causing a foreign-key violation when a real wallet/token this
  run's own sample-report demonstration had also fed through `argus
  wallets reconstruct-and-score` needed cleanup. Fixed by extending both
  helpers; the real-evidence demonstration was re-run a second time,
  after all validation, so the final DB state reflects it -- the
  identical resolution pattern Phase 2's own checkpoint documented for
  the same class of collision.
- **This sandbox's local PostgreSQL service was found stopped twice
  during this run's validation** (unrelated to any change made here).
  Restarted via `sudo service postgresql start` both times, non-
  destructive on the same local dev cluster used throughout this
  project.
- `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is unchanged -- still the
  orchestrator's `argus-phase-3-001` instruction, `STATUS: ACTIVE`.
  Phase 3 is NOT marked approved anywhere in this run's evidence, per
  this instruction's own explicit requirement; `last_orchestrator_
  approved_phase` is `2` (this instruction's own Phase 2 approval),
  never `3`.
- Both commits this run (the primary work commit and the follow-up
  commit-hash-fill-in commit) carry the sole final trailer paragraph
  `ARGUS-INSTRUCTION-ID: argus-phase-3-001`, with no paragraph after it,
  verified via `git interpret-trailers --parse` before push.

## Failures or limitations

- The five-wallet sample report is `PHASE_3_CANDIDATE_SAMPLE_BLOCKED`
  (see above and checkpoint section D) -- a direct consequence of this
  sandbox's unchanged live-provider-access limitation, not a Phase 3
  code defect.
- `WalletMetricsSnapshot` persists only the `LIFETIME` recency/metrics
  window per service call; the `180D`/`90D`/`30D`/`7D` windows are
  schema-ready but not wired in this phase, since no real evidence
  exists yet to populate them meaningfully (checkpoint section L).
- Wallet-cluster-link *detection* (from raw evidence such as common
  funding or synchronized activity) is not built this phase -- only
  *consumption* of already-persisted links, per this instruction's own
  "implement only the initial Phase 3 clustering necessary" scope limit
  (checkpoint section L).
- `LIVE_HELIUS_RPC_VALIDATION`/`LIVE_HELIUS_WSS_VALIDATION`/`PG17_
  COMPOSE_VALIDATION`/`BQ_PUBLIC_DATASET_ACCESS` remain `DEFERRED_
  ENVIRONMENTAL_CHECK`, unchanged, not reopened this round.

## Deferred checks

- All items under "Failures or limitations" above.

## Exact next action requested from orchestrator

Review this run's evidence (`orchestration/checkpoints/phase_3.md`,
`orchestration/bundles/phase_3.txt`, and `orchestration/phase_3/
SAMPLE_REPORT.md`) against instruction `argus-phase-3-001`'s frozen
13-item build surface, 8-item acceptance disposition, and 9 required
test categories. In particular: whether the honest `PHASE_3_CANDIDATE_
SAMPLE_BLOCKED` disposition (1 genuine candidate found, not 5, per the
instruction's own explicit fallback for this exact case) is acceptable
for Phase 3 approval, or whether it requires further evidence-sourcing
work before Phase 3 can be approved. Only the orchestrator may apply
that approval; write the next `ACTIVE` instruction into
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md` (`TARGET_COMMIT` pinned to
the exact commit named in this handoff) to do so, or to require further
remediation. Phase 4 remains forbidden until then. Until a new
instruction exists, the watcher (if running) takes no action beyond
logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** unchanged from prior handoffs — if you
cloned/fetched this branch before 2026-08-30T22:35 UTC, re-clone or
`git fetch --all && git reset --hard origin/claude/argus-folder-setup-77ahrk`
rather than merging/rebasing the old (pre-rewrite) history.
