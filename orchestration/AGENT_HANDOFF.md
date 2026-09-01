# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0021-phase-3-remediation
UTC_TIMESTAMP: 2026-09-01T05:58:00Z
CURRENT_COMMIT: PLACEHOLDER_FILLED_IN_SECOND_COMMIT
CURRENT_PHASE: 3
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-3-remediation-001
CHECKPOINT_PATH: orchestration/checkpoints/phase_3_remediation.md
BUNDLE_PATH: orchestration/bundles/phase_3_remediation.txt
TEST_STATUS: 23/23 unit `test_phase3_wallet_qualification.py` passed (was 12/12, +11 new remediation tests); 548/548 unit suite passed; 7/7 integration `test_phase3_wallet_qualification.py` passed (was 3/3, +4 new remediation tests, real PostgreSQL 16); 13/13 integration `test_migrations.py` passed (7 head-revision assertions mechanically updated `"0010"` -> `"0011"`); 112/112 golden+replay+phase_1_5 passed; 78/78 integration suite passed (was 74); full repository suite 738/738 passed (up from 721), 0 failed, 0 unexplained skipped; ruff clean; ruff format clean (211 files); mypy clean (110 source files); 12/12 real-chain fixtures ok; secret scan clean on this run's changed files; migration-from-zero/upgrade-from-0010/downgrade-then-reupgrade clean through 0011
WORKING_TREE: clean (verified via `git status --porcelain` before this commit)
ORCHESTRATOR_REVIEW_REQUIRED: whether this remediation (checkpoint sections B-U) genuinely closes all 7 frozen findings (P3-R1 through P3-R7) from independent audit `argus-phase-3-audit-001` and satisfies all 9 required prospective acceptance-test categories, and whether the unchanged `PHASE_3_CANDIDATE_SAMPLE_BLOCKED` sample-report disposition (accepted by this instruction, not reopened) remains appropriate. This session does not and cannot apply Phase 3 approval itself.

## Work completed

Executed orchestrator instruction `argus-phase-3-remediation-001` in full:
independently verified all safety gates (instruction-only commit
`da09d4f4d68d3120e865ffec5b5470d6b2ec86c0` whose parent exactly matches
`TARGET_COMMIT` `69a8de622b1977f92999ca680fcb8d851ba78c9f` and changes only
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md`; `AUTHORIZED_PHASE: 3` vs.
`docs/BUILD_STATE.md`'s `current_phase: 3` (never skip ahead); clean
worktree; local HEAD equal to freshly-fetched remote HEAD; Phase 3 awaiting
review and not marked approved) before any code was touched, then closed
all 7 frozen findings:

- **P3-R1** (point-in-time firewall absent in production): every evidence
  query in `reconstruct_and_score_wallet` is now bounded to `<= now`
  (swaps, discovery events, early buyers, cluster links); position
  reconstruction independently excludes a malformed/future-dated
  `block_time` rather than clamping it to full recency credit.
- **P3-R2** (history completeness caller-asserted): a new structured
  `AcquisitionManifest`/`TokenAccountCoverage` replaces the free-text
  `--acquisition-status` CLI flag; HIGH now requires both a complete
  wallet-address walk and complete (or genuinely-enumerated-empty)
  associated-token-account coverage.
- **P3-R3** (ledger not round-trip- or quote-safe): `position_
  reconstruction.py` rewritten with a `has_activity`-gated state machine
  emitting one position per independently-closed round trip; an
  incompatible-quote-asset leg is excluded from quantity/cost math and
  forces LOW confidence, never invented-conversion-summed.
- **P3-R4** (recency-window metrics schema-only): all 5 windows
  (LIFETIME/180D/90D/30D/7D) are now computed and persisted every run from
  the same bounded, contamination-filtered manifest; an empty window is
  explicit zero/null, never a LIFETIME copy.
- **P3-R5** (lottery/drawdown/usable-outcome metrics wrong): lottery
  contribution now divides by estimated net lifetime P&L; drawdown ordered
  by `final_exit_at`; `distinct_tokens` counts only closed usable outcomes.
- **P3-R6** (score/tier/identity disagreement): the cluster-uncertainty
  penalty is folded via `dataclasses.replace` into ONE canonical
  `ScoringResult` before both persistence and tier evaluation; the
  `current_tier is None`-forces-DISCOVERED special case is removed,
  closing an exact-replay-non-idempotency bug; `_score_equal` expanded to
  full semantic decision identity.
- **P3-R7** (checkpoint missing terminal marker): this fresh, correctly
  terminated checkpoint/bundle; the historical malformed `phase_3.md`/
  `.txt` preserved unmodified as evidence; 2 new regression tests prove
  the pre-existing, unmodified validator already correctly rejects it.

**All 9 required prospective acceptance-test categories pass** (11 new
unit tests, 4 new integration tests against real Postgres). See checkpoint
sections B-I.

**PHASE_3_CANDIDATE_SAMPLE_BLOCKED disposition unchanged** — this
instruction's own explicit acceptance of that result, not reopened. See
checkpoint section J.

## Important findings

- **One real, non-financial defect was found and fixed via this run's own
  required-test-writing, before any evidence was recorded**: the new
  round-trip state machine in `position_reconstruction.py` used the
  nullable `first_entry_at`/`final_exit_at` timestamp fields as
  control-flow sentinels for "has this round trip started/closed" —
  silently dropping every position whenever `block_time` was legitimately
  `None` (a gap the integration-test fixtures had never previously
  exercised, since they never set `block_time`). Fixed by adding an
  explicit `has_activity: bool` field decoupled from the nullable
  timestamp data, and by adding `block_time` to the shared integration
  test helper that had been silently omitting it.
- Migration `0011` deliberately clears the 4 derived Phase 3 decision
  tables (never raw evidence) since their pre-remediation rows reflect
  buggy computation this remediation replaces — disclosed explicitly in
  the migration file, checkpoint section Q, and `docs/DECISION_LOG.md`.
- This sandbox's local PostgreSQL service was found stopped at the start
  of this round's validation (unrelated to any change made here).
  Restarted via `sudo service postgresql start`, non-destructive on the
  same local dev cluster used throughout this project.
- `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is unchanged — still the
  orchestrator's `argus-phase-3-remediation-001` instruction, `STATUS:
  ACTIVE`. Phase 3 is NOT marked approved anywhere in this run's evidence;
  `last_orchestrator_approved_phase` is `2` (unchanged), never `3`.
- Both commits this run (the primary work commit and the follow-up
  commit-hash-fill-in commit) carry the sole final trailer paragraph
  `ARGUS-INSTRUCTION-ID: argus-phase-3-remediation-001`, with no paragraph
  after it, verified via `git interpret-trailers --parse` before push.

## Failures or limitations

- None new this round. All 7 frozen findings are closed; no `HARDENING_
  BACKLOG` item was pulled into scope (automated cluster-link discovery,
  DB-enforced canonical wallet ordering, automatic RETIRED assignment,
  additional cluster signals, broader metric-snapshot deduplication beyond
  the exact frozen replay requirements all remain explicitly out of scope,
  per this instruction).
- `LIVE_HELIUS_RPC_VALIDATION`/`LIVE_HELIUS_WSS_VALIDATION`/`PG17_
  COMPOSE_VALIDATION`/`BQ_PUBLIC_DATASET_ACCESS` remain `DEFERRED_
  ENVIRONMENTAL_CHECK`, unchanged, not reopened this round.

## Deferred checks

- All items under "Failures or limitations" above.

## Exact next action requested from orchestrator

Independently re-audit this remediation
(`orchestration/checkpoints/phase_3_remediation.md`,
`orchestration/bundles/phase_3_remediation.txt`) against the 7 frozen
findings and 9 required prospective acceptance-test categories from
`argus-phase-3-remediation-001`. In particular: whether the P3-R1..P3-R7
fixes and their proof tests genuinely close each finding, and whether the
unchanged `PHASE_3_CANDIDATE_SAMPLE_BLOCKED` disposition remains
acceptable (this instruction already accepted it as non-blocking). Only
the orchestrator may apply Phase 3 approval; write the next `ACTIVE`
instruction into `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`
(`TARGET_COMMIT` pinned to the exact commit named in this handoff) to do
so, or to require further remediation. Phase 4 remains forbidden until
then. Until a new instruction exists, the watcher (if running) takes no
action beyond logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** unchanged from prior handoffs — if you
cloned/fetched this branch before 2026-08-30T22:35 UTC, re-clone or
`git fetch --all && git reset --hard origin/claude/argus-folder-setup-77ahrk`
rather than merging/rebasing the old (pre-rewrite) history.
