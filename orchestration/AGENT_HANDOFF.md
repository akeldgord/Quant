# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0019-phase-2-remediation-2
UTC_TIMESTAMP: 2026-09-01T02:53:11Z
CURRENT_COMMIT: PLACEHOLDER_FILLED_IN_SECOND_COMMIT
CURRENT_PHASE: 2
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-2-remediation-002
CHECKPOINT_PATH: orchestration/checkpoints/phase_2_remediation_2.md
BUNDLE_PATH: orchestration/bundles/phase_2_remediation_2.txt
TEST_STATUS: 523/523 unit passed (test_historical_acquisition.py 18/18, incl. 4 new remediation-002 tests); 71/71 integration passed (real PostgreSQL 16); 95/95 golden passed; 10/10 replay passed; 7/7 phase_1_5 passed; full repository suite 706/706 passed (up from 702), 0 failed, 0 unexplained skipped, 85% overall coverage; ruff clean; ruff format clean; mypy clean (98 source files); 12/12 real-chain fixtures ok; secret scan clean on this round's 3 changed files
WORKING_TREE: clean (verified via `git status --porcelain` before this commit)
ORCHESTRATOR_REVIEW_REQUIRED: whether the single named P2-R2 boundary defect is now genuinely closed with no regression (checkpoint sections B, E, D), which per this instruction's own explicit statement ("If this exact boundary defect is proven fixed with no regression, the next orchestrator audit should approve Phase 2 and authorize Phase 3 in the same cycle") would make Phase 2 approvable. This session does not and cannot apply that approval itself.

## Work completed

Executed orchestrator instruction `argus-phase-2-remediation-002` in
full: independently verified all safety gates (instruction-only commit
`438d24e854fba2396b4c1889cf2a55a543f84d8b` whose parent exactly matches
`TARGET_COMMIT` `c99341a9c767c006cfe96fa4948dd54a9efe712b` and changes
only `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`; `AUTHORIZED_PHASE: 2`
vs. `docs/BUILD_STATE.md`'s `current_phase: 2`; clean worktree; local
HEAD equal to freshly-fetched remote HEAD; Phase 2 awaiting
orchestrator review and not marked approved) before any code was
touched, then fixed and proved exactly the one named defect, nothing
else.

**The defect**: the round-1 re-audit found the historical acquisition
service's own test module described a "premature short/empty page"
scenario in its header, but its actual tests only proved that an
*ordinary* short final page and an ordinary empty history are treated
as complete -- never that a caller-supplied expected historical boundary
is respected when the walk truncates before reaching it, per the
frozen P2-R2 requirement.

**The fix**: `acquire_historical_transactions()`
(`src/argus/tokens/historical_acquisition.py`) gained an optional,
typed `expected_oldest_slot: int | None = None` parameter. With no
boundary supplied, behavior is exactly unchanged from round 1 (proven by
a dedicated regression test using the identical page shape that
otherwise reports `PARTIAL`). With a boundary supplied, an empty/short
"natural completion" page is trusted as genuinely `COMPLETE` only once
the walk has actually observed a signature at or before that slot; a
premature truncation before then reports `PARTIAL`, names the
unsatisfied boundary explicitly in `known_gaps`, and preserves every
signature/transaction already acquired -- never discarded. The service
itself makes this comparison; a caller-supplied `--partial` flag is
never the proof. Wired through a new `--expected-oldest-slot` option on
`argus discover acquire-and-run-archaeology` (real production CLI
surface, not a test-only argument -- confirmed via `--help` and a real
fail-closed run against this sandbox's missing `HELIUS_API_KEY`).

4 new frozen remediation-002 acceptance tests
(`tests/unit/test_historical_acquisition.py`, module total 14 -> 18):
premature short page before the boundary (`PARTIAL`, evidence
preserved, exact provider-call accounting), premature empty page after
one valid page (`PARTIAL`, same assertions), boundary satisfied
(`COMPLETE`), and the identical-page-shape no-boundary regression proof
(`COMPLETE`). Full per-item detail and every command actually run:
`orchestration/checkpoints/phase_2_remediation_2.md`.

Exactly 3 files touched this round (`src/argus/cli.py`,
`src/argus/tokens/historical_acquisition.py`,
`tests/unit/test_historical_acquisition.py`) -- none of the seven
findings the round-2 re-audit closed (P2-R1, P2-R3, P2-R4, P2-R5, P2-R6,
P2-R7, P2-R8) had their own implementation revisited; only their
regression tests were re-run, all passing unchanged.

## Important findings

- **This sandbox's local PostgreSQL service was found stopped partway
  through this round's validation run** (unrelated to any change made
  here -- `pg_lsclusters` showed the cluster `down`). Restarted via
  `sudo service postgresql start`, a non-destructive operation on the
  same local dev cluster used throughout this project; all Phase 2
  remediation-round-1 evidence was confirmed still queryable afterward,
  and the real-Postgres integration suite then ran and passed cleanly.
  Disclosed here rather than silently worked around.
- **The new `--expected-oldest-slot` CLI option was directly exercised
  against this sandbox's real missing-credential environment**: `argus
  discover acquire-and-run-archaeology --expected-oldest-slot 12345`
  with no `HELIUS_API_KEY` configured produces the exact section-108
  `LOCAL CREDENTIAL REQUIRED` notice and attempts no network call --
  the option reaches the real call site without disturbing the
  fail-closed live-credential path.
- `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is unchanged -- still the
  orchestrator's `argus-phase-2-remediation-002` instruction, `STATUS:
  ACTIVE`. Phase 2 is NOT marked approved anywhere in this run's
  evidence, per this instruction's own explicit requirement.
- Both commits this run (the primary work commit and the follow-up
  commit-hash-fill-in commit) carry the sole final trailer paragraph
  `ARGUS-INSTRUCTION-ID: argus-phase-2-remediation-002`, with no
  paragraph after it, verified via `git interpret-trailers --parse`
  before push.

## Failures or limitations

- None newly introduced by this round. All limitations disclosed in
  `orchestration/checkpoints/phase_2_remediation.md`
  (historical-evidence breadth for the demonstrated token still limited
  to its own creation transaction absent a live `HELIUS_API_KEY`; the
  Phase 1 `swaps.input_amount_raw`/`output_amount_raw` u64-widening
  scope decision) remain unchanged and are not revisited by this
  round's scope-locked instruction.
- `LIVE_HELIUS_RPC_VALIDATION`/`LIVE_HELIUS_WSS_VALIDATION`/`PG17_
  COMPOSE_VALIDATION`/`BQ_PUBLIC_DATASET_ACCESS` remain `DEFERRED_
  ENVIRONMENTAL_CHECK`, unchanged, not reopened this round.

## Deferred checks

- All items under "Failures or limitations" above.

## Exact next action requested from orchestrator

Review this round's evidence
(`orchestration/checkpoints/phase_2_remediation_2.md` and
`orchestration/bundles/phase_2_remediation_2.txt`) against instruction
`argus-phase-2-remediation-002`'s single named boundary defect and its 4
frozen acceptance-test items. Per this instruction's own explicit
statement, if the defect is proven fixed with no regression (which this
round's evidence reports), the next orchestrator audit should approve
Phase 2 and authorize Phase 3 in the same cycle -- but only the
orchestrator may apply that approval; write the next `ACTIVE`
instruction into `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`
(`TARGET_COMMIT` pinned to the exact commit named in this handoff) to do
so, or to require further remediation. Phase 3 remains forbidden until
then. Until a new instruction exists, the watcher (if running) takes no
action beyond logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** unchanged from prior handoffs — if you
cloned/fetched this branch before 2026-08-30T22:35 UTC, re-clone or
`git fetch --all && git reset --hard origin/claude/argus-folder-setup-77ahrk`
rather than merging/rebasing the old (pre-rewrite) history.
