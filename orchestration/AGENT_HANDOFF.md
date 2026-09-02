# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0028-phase-4-recovery
UTC_TIMESTAMP: 2026-09-02T04:10:00Z
CURRENT_COMMIT: f932ce1a61358fd5bbdcc4fe7fcf64ff777a35ac
CURRENT_PHASE: 4
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-4-recovery-001
CHECKPOINT_PATH: orchestration/checkpoints/phase_4_recovery.md
BUNDLE_PATH: orchestration/bundles/phase_4_recovery.txt
TEST_STATUS: 35/35 integration `test_shadow_phase4_remediation_observation.py` (4 new P4-REC-01 tests); 33/33 integration `test_shadow_quote_jobs_provider_remediation.py` (8 new parametrize cases + 1 new dedicated test, P4-REC-02/03); 8/8 integration `test_shadow_phase4.py` (unchanged pass count, `_quote()` fixture `swapInfo` completed per P4-REC-02); 7/7 integration `test_shadow_phase4_concurrency_remediation.py` (unchanged pass count, same fixture completion); 21/21 integration `test_migrations.py` (4 new P4-REC-04 tests; all 9 hardcoded head-revision assertions updated `0020`->`0021`); 16/16 integration `test_daily_report_remediation.py` (4 new P4-REC-05 tests); 8/8 integration `test_replay_demo_isolation.py` (unchanged pass count, same fixture completion, `EVIDENCE_DIR` moved); full repository suite 911/911 passed, 0 failed, 0 unexplained skipped (`uv run pytest -q`, re-verified after a migration downgrade/upgrade round-trip); ruff clean; ruff format clean (257 files); mypy clean (128 source files); alembic single head `0021` (was `0020`), downgrade-0018/upgrade-head round-trip clean through 0019/0020/0021; 12/12 real-chain fixtures ok; secret scan clean on all 16 changed/new files plus the new evidence directory -- ALL RAW COMMAND OUTPUT embedded verbatim in the paired bundle
WORKING_TREE: clean (verified via `git status --porcelain` before this commit)
ORCHESTRATOR_REVIEW_REQUIRED: whether this recovery round genuinely closes all 5 frozen findings (P4-REC-01 through P4-REC-05, i.e. `argus-phase-4-failure-review-001`'s own R1-T, R4-V, R4-E, R4-M, R6-T) against that review's own root-cause diagnosis, whether every one of the 31 numbered required pass conditions across the 5 findings is genuinely satisfied (checkpoint section B maps each to its own executed test), whether every other previously-CLOSED finding (P4-R2, P4-R3, P4-R5 worker ownership, P4-R7, round 2's own continued findings) remains genuinely untouched and still passes, and whether Phase 4 should now be approved and Phase 5 authorized, or further recovery/remediation required. This session does not and cannot apply Phase 4 approval itself.

## Work completed

Executed orchestrator instruction `argus-phase-4-recovery-001` in full:
independently verified all safety gates (single instruction-only commit
whose parent exactly matches `TARGET_COMMIT`
`9aa8b8decf8cb17e1b3bb28e9e1ebd0b2083acda`; `AUTHORIZED_PHASE: 4` vs.
`docs/BUILD_STATE.md`'s `current_phase: 4` at the time -- not skipping
ahead; clean worktree; local HEAD equal to freshly-fetched remote HEAD)
before any code was touched, then closed exactly the 5 findings the
independent root-cause review `argus-phase-4-failure-review-001` froze
as SPEC_BLOCKING after finding remediation round 2 only PARTIALLY
sufficient -- while explicitly NOT reopening any other previously-CLOSED
finding (P4-R2, P4-R3, P4-R5 worker ownership, P4-R7, and every
already-closed round-2 continued finding):

1. **P4-REC-01 (token/position creation-time cutoffs)**:
   `_token_state_snapshot`/`_position_size_context`
   (`src/argus/shadow/prospective.py`) now also bound
   `Token.created_at`/`WalletPosition.created_at` to the knowledge
   cutoff, not just `first_observed_at`/`first_entry_at` -- a row
   backdated to an effective time at or before cutoff but not actually
   PERSISTED until after cutoff was, before this fix, still treated as
   known at cutoff. The single already-passing monitor caller uses these
   bounded paths with no mutable-current fallback.
2. **P4-REC-02 (structural quote-route validation)**:
   `_is_structurally_valid_route_entry`
   (`src/argus/shadow/quote_jobs.py`) now validates the route entry's own
   nested `swapInfo` fields -- genuinely present, correctly-typed,
   positive `inputMint`/`outputMint`/`inAmount`/`outAmount` -- not merely
   that `swapInfo` is a dict; `swapInfo={}` or a `swapInfo` missing/
   mistyping any of those four fields previously still counted as
   SUCCESS route evidence. Malformed/wrong-type/missing/non-positive
   fields now correctly classify as `QUOTE_FAILED`/`NO_ROUTE`, never
   SUCCESS, and never create a `ShadowPosition`.
3. **P4-REC-03 (preserve sanitized terminal failure evidence)**: a new
   nullable `shadow_quote_probes.failure_evidence` JSONB column
   (migration `0021`) is now populated by `_classify_provider_exception`
   (which now returns `(outcome, failure_evidence)` instead of `outcome`
   alone) with a small, bounded, already-sanitized set of keys --
   `http_status_code`, `provider_error_code` (length-capped real string
   only), `scheduler_drop_reason`/`scheduler_priority_class` -- never the
   raw response body, headers, or request URL.
4. **P4-REC-04 (populated predecessor migration compatibility, most
   severe)**: migration `0020`'s own
   `CHECK (responded_at IS NULL OR terminal_at IS NOT NULL)` constraint
   was validated against every existing row the instant it was created,
   with no backfill step -- on a real populated database, every
   pre-existing row with a real provider response already recorded had
   no `terminal_at` value yet (that column did not exist before this
   migration), so the constraint would fail the migration outright.
   Fixed by amending the still-UNAPPROVED `0020` migration in place
   (same narrow-change-control precedent as Phase 3's `0011`/`0012`) to
   backfill `terminal_at = responded_at` for exactly the rows where
   `responded_at IS NOT NULL AND terminal_at IS NULL`, BEFORE the CHECK
   constraint is created -- `responded_at` is itself the truthful,
   deterministically-derived terminal moment for these legacy rows,
   since every prior code version performed its terminal write in the
   same atomic transaction immediately after computing it. Proven
   against a REAL populated database (schema created at predecessor
   revision `0018` with completed-success/completed-error/completed-
   capacity-miss/pending fixture rows, then upgraded through head), not
   merely a fresh empty schema.
5. **P4-REC-05 (report-end-bounded latest history)**:
   `_latest_history_id_per_wallet_subquery`
   (`src/argus/reports/daily.py`) now accepts an optional `cutoff`
   parameter that bounds candidate rows to `created_at <= cutoff` before
   the existing per-wallet `DISTINCT ON` deduplication runs (unchanged);
   `_build_data_quality` now passes its own `end` as that cutoff, so a
   history row created after an earlier report's own `end` can no
   longer count as "current" in that earlier report merely because it
   is the globally-latest row by the time the query happens to run.
   `_build_research`'s own unbounded historical-backtest use is
   unchanged (out of this recovery's frozen scope).

**No genuinely new safety/integrity defect outside these 5 rows was
discovered.** The only work beyond each finding's own literal fix was
completing the `swapInfo` payload in 4 pre-existing fake test fixtures
(`test_shadow_phase4.py`, `test_shadow_phase4_concurrency_remediation.py`,
`test_shadow_phase4_remediation_observation.py`,
`scripts/argus_phase4_replay_demo.py`'s own fake quote) whose SUCCESS-
path scenarios stopped representing a genuine SUCCESS route once
P4-REC-02's validator was deepened -- required fixture maintenance to
keep already-passing behavior passing under a legitimately deepened
contract, disclosed explicitly rather than silently absorbed (checkpoint
section B, P4-REC-02 row, and section I).

An unintended side effect was caught and corrected mid-session:
`test_replay_demo_isolation.py`'s own real subprocess invocation of
`scripts/argus_phase4_replay_demo.py` regenerated round 2's frozen
`orchestration/phase_4_remediation_2/evidence/replay_demo_results.json`
with fresh random UUIDs while `EVIDENCE_DIR` still pointed at that path.
Caught via `git status --porcelain` before any commit, reverted with
`git checkout --`, and `EVIDENCE_DIR` fixed to point at
`orchestration/phase_4_recovery/evidence` so this cannot recur --
round 2's frozen evidence file is confirmed byte-for-byte unmodified in
the final diff (checkpoint section E).

## Important findings

- All 5 frozen findings from `argus-phase-4-failure-review-001` are
  FIXED -- see `orchestration/checkpoints/phase_4_recovery.md` section B
  for the row-by-row acceptance matrix mapping every one of the
  instruction's own 31 numbered required pass conditions to its own
  executed test, and section C for DO-NOT scope-boundary compliance.
- P4-R2/P4-R3/P4-R5 worker ownership/P4-R7 and every already-closed
  round-2 continued finding (confirmed CLOSED by prior rounds) were NOT
  touched except for the 4 fake-fixture `swapInfo` completions required
  by P4-REC-02's own deepened contract -- section D of the new
  checkpoint confirms every frozen finding's own regression tests still
  pass unmodified.
- `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is unchanged -- still the
  orchestrator's `argus-phase-4-recovery-001` instruction. Phase 4 is
  NOT marked approved anywhere in this session's evidence;
  `last_orchestrator_approved_phase` is `3` (unchanged), never `4`.
- Both commits this session (the primary work commit and the follow-up
  commit-hash-fill-in commit) carry the sole final trailer paragraph
  `ARGUS-INSTRUCTION-ID: argus-phase-4-recovery-001`, with no paragraph
  after it, verified via `git interpret-trailers --parse` before push.

## Failures or limitations

- None. All 5 frozen findings are closed with real, tested fixes against
  real Postgres, each adversarially re-verified (P4-REC-02's own
  counterexample: the pre-existing fake fixtures' incomplete `swapInfo`
  genuinely flipped from SUCCESS to NO_ROUTE under the deepened
  validator before being updated, proving the fix changes real
  behavior, not merely a synthetic test written to already agree with
  it).
- `LIVE_HELIUS_RPC_VALIDATION`/`LIVE_HELIUS_WSS_VALIDATION`/`PG17_
  COMPOSE_VALIDATION`/`BQ_PUBLIC_DATASET_ACCESS` remain `DEFERRED_
  ENVIRONMENTAL_CHECK`, unchanged, not reopened this round. No live
  Jupiter/DexScreener network access remains an explicit, disclosed
  constraint of this sandbox (every P4-REC-02/03 real-adapter test uses
  `httpx.MockTransport`, never a live endpoint).
- `_build_research`'s own `historical_backtest.mfe_mae_by_quote_asset`
  use of `_latest_history_id_per_wallet_subquery` remains unbounded
  (`cutoff=None`) -- explicitly out of P4-REC-05's frozen scope (the
  instruction names `_build_data_quality` specifically), disclosed in
  checkpoint section J rather than left ambiguous.

## Deferred checks

- All items under "Failures or limitations" above.

## Exact next action requested from orchestrator

Independently audit this recovery round
(`orchestration/checkpoints/phase_4_recovery.md`,
`orchestration/bundles/phase_4_recovery.txt`) against
`argus-phase-4-failure-review-001`'s own 5 frozen findings and required
numbered pass conditions. In particular: whether each finding's required
test scenarios (named verbatim in
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md`'s per-finding sections) are
genuinely satisfied by the new/extended test files, whether the fake-
fixture `swapInfo` completions are correctly scoped test maintenance and
not scope expansion, whether every other previously-CLOSED finding
remains genuinely untouched and still passes, and whether every original
frozen acceptance gate plus every prior round's own added regression
proof still holds with no regression. Only the orchestrator may apply
Phase 4 approval -- write the next `ACTIVE` instruction into
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md` (`TARGET_COMMIT` pinned to
the exact commit named in this handoff) to do so, or to require further
recovery/remediation. Phase 5 remains forbidden until then. Until a new
instruction exists, the watcher (if running) takes no action beyond
logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** unchanged from prior handoffs — if you
cloned/fetched this branch before 2026-08-30T22:35 UTC, re-clone or
`git fetch --all && git reset --hard origin/claude/argus-folder-setup-77ahrk`
rather than merging/rebasing the old (pre-rewrite) history.
