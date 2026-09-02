# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0029-phase-4-recovery-2
UTC_TIMESTAMP: 2026-09-02T13:45:00Z
CURRENT_COMMIT: a50432946b5ddeede55f84d61c93375047c564df
CURRENT_PHASE: 4
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-4-recovery-002
CHECKPOINT_PATH: orchestration/checkpoints/phase_4_recovery_2.md
BUNDLE_PATH: orchestration/bundles/phase_4_recovery_2.txt
TEST_STATUS: 52/52 new `tests/unit/test_phase4_recovery_2_contract.py` (51 passed + 1 order-dependent skip pre-hash-fill, resolved to 52/52 by the direct post-hash-fill validator invocation in the checkpoint's own section F); 16/16 new `tests/integration/test_phase4_recovery_2.py`; targeted regression re-run (`test_shadow_phase4_remediation_observation.py`/`test_shadow_quote_jobs_provider_remediation.py`/`test_shadow_phase4.py`/`test_shadow_phase4_concurrency_remediation.py`/`test_migrations.py`/`test_daily_report_remediation.py`/`test_replay_demo_isolation.py`) 128/128; full repository suite 978/978 passed, 0 failed, 1 explained order-dependent skip (`uv run pytest -q`); ruff clean; ruff format clean (260 files, after auto-reformatting this round's own 2 new test files); mypy clean (128 source files); alembic single head `0021` (unchanged -- no new migration needed); 12/12 real-chain fixtures ok; secret scan clean on all 9 changed/new files plus the new evidence directory; both real production checkpoint/bundle validators (`validate_checkpoint_content`/`validate_bundle_content`) explicitly invoked against the final hash-filled bytes and asserted `(True, '')` -- ALL RAW COMMAND OUTPUT embedded verbatim in the paired bundle
WORKING_TREE: clean (verified via `git status --porcelain` before this commit)
ORCHESTRATOR_REVIEW_REQUIRED: whether this round genuinely closes F-01, F-02 and F-03 exactly as frozen by `argus-phase-4-recovery-review-001` (checkpoint section B maps each to its own named regression test and raw pre-fix/post-fix evidence), whether P4-REC-01/04/05 and every other previously-CLOSED finding remain genuinely untouched and still pass, whether the new checkpoint/bundle genuinely satisfy the production validators on independent re-inspection (not merely this session's own self-reported invocation), and whether Phase 4 should now be approved and Phase 5 authorized, or further recovery/remediation required. This session does not and cannot apply Phase 4 approval itself.

## Work completed

Independently verified the safety gates for and executed orchestrator
instruction `argus-phase-4-recovery-002` in full: `TARGET_COMMIT`
`e2b0edce094f51b329372ccfb0015fece0103033` confirmed to be the sole
instruction-only commit directly above the prior
`argus-phase-4-recovery-review-001` audit (an ancestor of HEAD with only
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md` differing between them);
`AUTHORIZED_PHASE: 4` <= `docs/BUILD_STATE.md`'s `current_phase: 4` + 1 --
not skipping ahead; clean worktree; local HEAD equal to a freshly-fetched
remote HEAD -- before any code was touched. Then closed exactly the 3
findings (F-01, F-02, F-03) the independent audit
`argus-phase-4-recovery-review-001` froze after finding recovery round 1
only PARTIALLY sufficient on P4-REC-02/P4-REC-03, plus a checkpoint-format
regression -- while explicitly NOT reopening P4-REC-01/04/05 or any other
previously-CLOSED finding:

1. **F-01 (`src/argus/shadow/quote_jobs._is_positive_raw_amount`,
   SPEC_BLOCKING)**: `str.isdigit()` alone accepted non-ASCII Unicode
   "digit" characters (e.g. superscript-two `"²"`) that `int()` cannot
   parse, and Python's own global integer-string-conversion length guard
   raised `ValueError` for an excessively long all-ASCII digit string --
   both previously escaped uncaught out of `_classify_quote`'s `else`
   branch inside `_execute_and_record_probe` (NOT covered by that
   function's provider `try/except`), crashing the whole probe-processing
   call instead of recording an honest terminal `NO_ROUTE`. Fixed by
   requiring `value.isascii() and value.isdigit()` before ever calling
   `int()`, then wrapping that conversion in a `ValueError`/`OverflowError`
   guard. Python's own conversion-length limit is left completely
   untouched (never raised via `sys.set_int_max_str_digits`), proven by an
   explicit regression asserting the limit is still the Python default
   (4300) after this fix.
2. **F-02 (`_safe_provider_error_code`/`_classify_provider_exception`,
   SAFETY_OR_INTEGRITY_BLOCKING)**: the sanitizer previously checked only
   type/length, letting an unsafe-shaped string (a URL with an embedded
   fake API key, a bare `key=value` query fragment, embedded control
   characters, JSON-body-shaped text) that fit the length bound through
   verbatim; separately, the HTTP 429 branch returned immediately without
   ever inspecting the response body, silently dropping a genuinely-
   supplied safe `errorCode` on 429 alone. Fixed by replacing the
   sanitizer with a bounded ASCII identifier grammar
   (`^[A-Za-z][A-Za-z0-9_]{0,127}$`, a full-match regex), and by
   restructuring `_classify_provider_exception` to parse the response body
   and extract a sanitized code BEFORE branching on status code, so a
   JSON-parse failure can never erase the 429 capacity classification and
   a genuinely-supplied safe code now survives on 429 exactly like every
   other status; 429 itself remains always `PROVIDER_CAPACITY_MISS`
   regardless of code presence/validity.
3. **F-03 (checkpoint/bundle artifact validation, SPEC_BLOCKING)**: the
   round-1 checkpoint (`orchestration/checkpoints/phase_4_recovery.md`,
   left byte-for-byte unmodified) was never actually run through this
   project's own production `validate_checkpoint_content`/
   `validate_bundle_content` functions -- it is missing the required end
   marker entirely and has no section containing the literal (case-
   insensitive) required phrase "acceptance criteria". This round's own
   checkpoint/bundle were mechanically validated against BOTH real,
   unmodified production validators after hash-fill, with the actual
   `(ok, reason)` tuples (both `(True, '')`) recorded verbatim in the
   checkpoint's own commands-run section -- calling the functions without
   asserting `ok` is explicitly not validation.

Two new focused test files, following the frozen instruction's own file
split: `tests/unit/test_phase4_recovery_2_contract.py` (52 tests -- the
pure parser/artifact rows AM-01/02/04/08/09/12/13, no database) and
`tests/integration/test_phase4_recovery_2.py` (16 tests -- the worker/
persistence rows AM-01/03/05/06/07/10/11, real `JupiterClient`+
`httpx.MockTransport`+the real claim/execute/record seam, covering both
entry AND reverse probe kinds). Every counterexample was run FIRST against
the unmodified pre-fix code and its honest failing output preserved (never
`xfail`) in `orchestration/phase_4_recovery_2/evidence/
pre_fix_unit_contract_red.txt` (15 failed, 36 passed) and `.../
pre_fix_integration_worker_red.txt` (7 failed, 9 passed) before either fix
was implemented.

An unintended side effect was caught and corrected mid-session (same
category of issue as the prior round, now permanently structural): the
full-suite run's own `test_replay_demo_isolation.py` regenerated round 1's
frozen `orchestration/phase_4_recovery/evidence/replay_demo_results.json`
while `EVIDENCE_DIR` still pointed there. Caught via `git status
--porcelain` before staging, reverted with `git checkout --`, and
`EVIDENCE_DIR` moved to `orchestration/phase_4_recovery_2/evidence` per
F-03's own explicit "route new output to the new evidence directory"
allowance -- round 1's frozen evidence file is confirmed byte-for-byte
unmodified in the final diff.

## Important findings

- All 3 frozen findings (F-01, F-02, F-03) from
  `argus-phase-4-recovery-review-001` are FIXED -- see
  `orchestration/checkpoints/phase_4_recovery_2.md` section B for the
  row-by-row matrix mapping every one of AM-01 through AM-15 to its own
  named, currently-passing test (or, for AM-12/14/15, the raw command
  evidence proving it).
- P4-REC-01/04/05 and every other previously-CLOSED finding (confirmed
  CLOSED by prior rounds) were NOT touched -- section H of the new
  checkpoint confirms every frozen finding's own regression suite still
  passes unmodified.
- `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is unchanged -- still the
  orchestrator's `argus-phase-4-recovery-002` instruction. Phase 4 is NOT
  marked approved anywhere in this session's evidence;
  `last_orchestrator_approved_phase` is `3` (unchanged), never `4`.
- Both commits this session (the primary work commit and the follow-up
  commit-hash-fill-in commit) carry the sole final trailer paragraph
  `ARGUS-INSTRUCTION-ID: argus-phase-4-recovery-002`, with no paragraph
  after it, verified via `git interpret-trailers --parse` before push.

## Failures or limitations

- None. All 3 frozen findings are closed with real, tested fixes,
  adversarially re-verified with counterexamples run against the pre-fix
  code first and their honest failing output preserved.
- F-02's provider-error-code sanitization remains an explicit format
  policy (a bounded ASCII identifier grammar), not a claim to detect every
  possible secret hidden in arbitrary text -- this is the frozen
  instruction's own stated scope limit for F-02, disclosed rather than
  silently absorbed.
- `LIVE_HELIUS_RPC_VALIDATION`/`LIVE_HELIUS_WSS_VALIDATION`/`PG17_
  COMPOSE_VALIDATION`/`BQ_PUBLIC_DATASET_ACCESS` remain `DEFERRED_
  ENVIRONMENTAL_CHECK`, unchanged, not reopened this round.
- `_build_research`'s own unbounded `historical_backtest` use of
  `_latest_history_id_per_wallet_subquery` (`cutoff=None`) remains
  unchanged -- out of scope for both P4-REC-05 and this round.

## Deferred checks

- All items under "Failures or limitations" above.

## Exact next action requested from orchestrator

Independently audit this recovery round
(`orchestration/checkpoints/phase_4_recovery_2.md`,
`orchestration/bundles/phase_4_recovery_2.txt`) against
`argus-phase-4-recovery-review-001`'s own F-01/F-02/F-03 frozen findings
and the AM-01 through AM-15 atomic acceptance matrix. In particular:
whether each finding's required regression scenarios are genuinely
satisfied by the new test files, whether P4-REC-01/04/05 and every other
previously-CLOSED finding remain genuinely untouched and still pass,
whether the new checkpoint/bundle genuinely pass the production validators
on independent re-inspection, and whether every original frozen acceptance
gate plus every prior round's own added regression proof still holds with
no regression. Only the orchestrator may apply Phase 4 approval -- write
the next `ACTIVE` instruction into
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md` (`TARGET_COMMIT` pinned to
the exact commit named in this handoff) to do so, or to require further
recovery/remediation. Phase 5 remains forbidden until then. Until a new
instruction exists, the watcher (if running) takes no action beyond
logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** unchanged from prior handoffs — if you
cloned/fetched this branch before 2026-08-30T22:35 UTC, re-clone or
`git fetch --all && git reset --hard origin/claude/argus-folder-setup-77ahrk`
rather than merging/rebasing the old (pre-rewrite) history.
