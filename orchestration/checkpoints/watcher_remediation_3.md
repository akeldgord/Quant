================ ARGUS ORCHESTRATOR CHECKPOINT ================

A. Identity
PROJECT: ARGUS
MASTER_SPEC_VERSION: v2.0
SCOPE: Operational tooling remediation (local orchestrator watcher),
  instruction_id=argus-watcher-remediation-003 — NOT an ARGUS phase.
  current_phase remains 0; no phase gate was crossed;
  orchestration/ORCHESTRATOR_INSTRUCTIONS.md was not modified.
STATUS: PASS
UTC_TIMESTAMP: 2026-08-31T04:00:00Z
GIT_COMMIT: 50e6d91b9cfeb40be14cf43a0b9f0b2c7582bd74
TARGET_COMMIT: 34930bfa78cd7f667527b40f7d006c923c7c9ba6
AUTHORIZED_PHASE: 0
APPROVES_PHASE: NONE

B. What was built

Per orchestrator instruction argus-watcher-remediation-003 (pushed via
GitHub, commit 0aea514), watcher remediation round 2
(orchestration/checkpoints/watcher_remediation_2.md, commit 34930bf) was
rejected: "Many requested protections are real and useful, but several
fail-open and replay paths remain." The orchestrator gave six defect
categories with concrete reproduction steps. Each was independently traced
against round 2's actual code before being fixed. Full reasoning:
docs/DECISION_LOG.md, entry "Watcher remediation round 3: close the
self-authorization bypass and fail-open Git-error gaps
(argus-watcher-remediation-003)". Summary:

1. A self-authored next instruction could still launch on a later tick.
   Round 2's blob-hash check correctly failed the ORIGINATING run, but only
   as an ordinary FAILED -- a self-authored instruction whose TARGET_COMMIT
   pointed at the immediately preceding legitimate implementation commit,
   with a diff touching only the instructions file, would structurally
   pass round 2's target-commit check on the NEXT tick (a new
   INSTRUCTION_ID isn't blocked by the "already attempted" guard). Fixed
   with two independent layers:
   (a) A detected instructions-file modification is now a terminal,
       non-retryable QUARANTINED state -- checked first and
       unconditionally in tick(), before the exit-code check and every
       other verification, so it can never be pre-empted by another check
       failing first. From QUARANTINED, no future instruction of any ID or
       target is ever evaluated again until a human runs the new
       `--reset-quarantine` CLI flag after manual review.
   (b) verify_target_commit() independently tightened to require exactly
       one instruction-only commit whose parent is exactly TARGET_COMMIT,
       rejecting TARGET_COMMIT == HEAD, multiple commits, and merge
       commits between them.
   Neither layer claims to cryptographically authenticate WHO authored a
   commit -- this file-trust protocol cannot do that without signing,
   which is explicitly out of scope (see section M).
2. Safety-critical Git command errors failed open. git_changed_paths(),
   git_commits_in_range(), the merge-enumeration check, and
   is_worktree_dirty() all returned an empty/False default on a failed
   subprocess call, read by callers as "no unexpected paths" / "no
   commits" / "no merges" / "clean". All now return None on any command
   failure, and every caller treats None as an explicit verification
   failure -- never as an empty/clean/absent default.
3. Commit-message attribution accepted the trailer text anywhere in body
   prose. Replaced with git-interpret-trailers-based parsing, requiring
   exactly one parsed terminal trailer with the exact key and value; a
   duplicate, conflicting, or prose-embedded mention is now rejected.
4. Launch failures and diagnostics were not fully safe. The except clause
   is now broadened to catch any ordinary exception and persist FAILED in
   the same tick() call, unconditionally (including under --once, since
   tick() itself -- not an outer wrapper -- now guarantees this). Raw
   Claude subprocess stdout/stderr is no longer read into any log detail
   at all; only whitelisted metadata (exit code, timeout duration,
   exception class name) is logged, and every log detail is sanitized
   (control characters/newlines stripped).
5. Timestamp validation was shape-only. Replaced with
   parse_canonical_utc_timestamp(), a real datetime.strptime parse with an
   exact-round-trip requirement, applied to both instruction ISSUED_AT and
   (newly) handoff UTC_TIMESTAMP.
6. Evidence linkage was too weak. validate_bundle_content() now requires
   the checkpoint's exact bytes verbatim as a substring (not just a few
   keywords). checkpoint STATUS/GIT_COMMIT must each occur exactly once;
   GIT_COMMIT must be a full 40-character SHA; handoff CURRENT_PHASE must
   match the instruction's AUTHORIZED_PHASE exactly; handoff WORKING_TREE
   must state "clean" (independently cross-checked by the watcher's own
   git status); every required AGENT_HANDOFF.md section heading must be
   present.

Added 26 new/updated adversarial regression tests covering every category
in the instruction's "Mandatory adversarial regression tests" list,
including direct unit-level tests against verify_target_commit(),
verify_run_ancestry_and_attribution(), and verify_handoff() with a
narrowly-injected failing Git command (monkeypatched _run_git) around an
otherwise-real temporary repository, per the instruction's own guidance.

orchestration/PROTOCOL.md sections 4, 5, and 7 and docs/OPERATIONS.md
(including a new "Terminal trust-breach quarantine" recovery procedure)
were updated to describe the above as mechanically-enforced requirements.

C. Files changed
Modified: scripts/argus_orchestrator_watch.py,
tests/unit/test_orchestrator_watch.py, orchestration/PROTOCOL.md,
docs/OPERATIONS.md, docs/DECISION_LOG.md, docs/BUILD_STATE.md.
New (this task): orchestration/checkpoints/watcher_remediation_3.md (this
file), orchestration/bundles/watcher_remediation_3.txt,
orchestration/AGENT_HANDOFF.md (updated in place).
Not modified: orchestration/ORCHESTRATOR_INSTRUCTIONS.md (verified via
`git hash-object` before and after this task; orchestrator-owned).

D. Commands actually run
- Full re-read of the ACTIVE instruction (orchestration/ORCHESTRATOR_INSTRUCTIONS.md,
  instruction_id=argus-watcher-remediation-003) plus MASTER_SPEC.md,
  docs/BUILD_STATE.md, docs/DECISION_LOG.md, orchestration/PROTOCOL.md,
  orchestration/AGENT_HANDOFF.md, and the round-2 watcher_remediation_2.md
  checkpoint, before writing any code.
- Pre-execution safety verification:
  `git merge-base --is-ancestor 34930bfa78cd7f667527b40f7d006c923c7c9ba6 HEAD`
  (OK: ancestor); `git diff --name-only 34930bfa... HEAD` (only
  orchestration/ORCHESTRATOR_INSTRUCTIONS.md differed); manual check of
  docs/BUILD_STATE.md's current_phase/last_completed_phase/
  awaiting_orchestrator_review against the instruction's AUTHORIZED_PHASE: 0 /
  APPROVES_PHASE: NONE (same-phase remediation case; valid).
- Verified `git interpret-trailers --parse` behavior empirically (proper
  trailer vs. prose-embedded text vs. duplicate trailers vs. extra value
  text) before relying on it, and Python `datetime.strptime` round-trip
  behavior on impossible-but-shape-matching timestamps, before writing the
  corresponding checks.
- uv run pytest tests/unit/test_orchestrator_watch.py -v -- 74/74 passed
- uv run pytest --cov --cov-report=term-missing -- 111 passed, 4 skipped
  (pre-existing, unrelated Postgres-integration skips), 93% coverage on
  src/argus (unchanged -- the watcher lives outside that coverage scope
  and is verified by its own 74 dedicated tests)
- uv run ruff check . -- All checks passed!
- uv run ruff format --check . -- 80 files already formatted
- uv run mypy -- Success: no issues found in 40 source files
- uv run mypy scripts/argus_orchestrator_watch.py --ignore-missing-imports
  -- Success: no issues found in 1 source file
- uv run python scripts/argus_orchestrator_watch.py --once against the
  real repository while implementation changes were still uncommitted --
  correctly logged DIRTY_WORKTREE and took no git/Claude action
- uv run python scripts/argus_orchestrator_watch.py --reset-quarantine
  against the real (non-QUARANTINED) repository state -- correctly refused
  with exit code 1 and "no QUARANTINED state found; nothing to reset",
  making no state change
- grep-based secret scan on the staged diff -- no matches beyond a
  deliberately fake test credential used to prove it is never logged
  (test_claude_output_never_appears_in_log); git status --porcelain clean
  before and after commit

E. Test results
pytest (watcher suite): 74 passed, 0 failed, 0 skipped (up from 51 in the
  rejected round-2 remediation -- 26+ new/updated adversarial tests
  covering every category in the instruction's mandatory list, plus all
  retained useful tests from round 2)
pytest (full suite): 111 passed, 4 skipped (pre-existing, unrelated
  Postgres-integration skips -- Postgres is not reachable in this sandbox)
coverage: 93% (src/argus, unchanged)
ruff: All checks passed!
ruff format --check: 80 files already formatted
mypy: Success: no issues found in 40 source files (+ watcher script clean
  when checked directly)

F. Acceptance criteria (this task)
[PASS] Defect 1 (self-authored next instruction could launch on a later
  tick) closed via QUARANTINED terminal state (checked first,
  unconditionally) + tightened target-commit provenance; regression tests
  test_self_authored_instruction_triggers_quarantine_and_blocks_forever,
  test_target_commit_equal_to_head_is_rejected,
  test_target_commit_multiple_commits_between_is_rejected,
  test_target_commit_single_commit_atop_target_is_accepted
[PASS] Defect 2 (Git command errors fail open) closed via Optional-
  returning fail-closed helpers; regression tests
  test_failed_commit_log_read_fails_attribution,
  test_failed_merge_enumeration_fails_attribution,
  test_failed_git_status_never_counts_as_clean,
  test_failed_git_diff_never_counts_as_no_drift,
  test_failed_run_range_enumeration_fails_handoff
[PASS] Defect 3 (trailer text-anywhere-in-prose accepted) closed via
  git-interpret-trailers-based parsing; regression tests
  test_trailer_in_ordinary_prose_is_not_recognized,
  test_duplicate_conflicting_trailers_rejected,
  test_single_exact_trailer_is_accepted,
  test_extra_value_text_on_trailer_rejected
[PASS] Defect 4 (launch failures/diagnostics not fully safe) closed via
  broadened exception handling + no-stdout/stderr-logging; regression
  tests test_launch_runtime_error_persists_failed_immediately,
  test_claude_output_never_appears_in_log
[PASS] Defect 5 (shape-only timestamp validation) closed via real UTC
  parser; regression tests test_instruction_impossible_timestamp_rejected
  (3 cases), test_handoff_impossible_timestamp_rejected,
  test_canonical_utc_timestamp_parser
[PASS] Defect 6 (weak evidence linkage) closed via exact checkpoint
  embedding + exactly-once/full-SHA identity fields + CURRENT_PHASE match
  + required headings; regression tests
  test_bundle_with_different_checkpoint_rejected,
  test_bundle_with_exact_checkpoint_is_accepted,
  test_handoff_missing_section_heading_rejected,
  test_checkpoint_duplicate_contradictory_status_rejected,
  test_checkpoint_git_commit_not_full_sha_rejected,
  test_checkpoint_duplicate_git_commit_rejected,
  test_checkpoint_contradictory_status_rejected_end_to_end
[PASS] All 26 mandatory adversarial regression test categories from the
  instruction are covered (see orchestration/bundles/watcher_remediation_3.txt
  for the explicit test-name-to-category mapping)
[PASS] orchestration/ORCHESTRATOR_INSTRUCTIONS.md not modified
[PASS] Phase 1 not self-authorized; docs/BUILD_STATE.md
  last_orchestrator_approved_phase/approved_commit untouched
[PASS] Every commit for this task carries exactly one valid terminal
  trailer ARGUS-INSTRUCTION-ID: argus-watcher-remediation-003

G. Database/data sanity
Unchanged -- this task touched no schema, migration, or database code.

H. Provider usage
Not applicable.

I. Data quality warnings
None new. PG17_COMPOSE_VALIDATION remains DEFERRED_ENVIRONMENTAL_CHECK
(unchanged by this task; unrelated).

J. Sample outputs
See orchestration/bundles/watcher_remediation_3.txt for the full list of
new/updated test names mapped to the instruction's 26 mandatory adversarial
categories, and for the real watcher `--once`/`--reset-quarantine` log
lines captured during this task.

K. Architectural deviations
NONE. No MASTER_SPEC.md change. No ARGUS architecture change. This is
operational tooling for the orchestration protocol, not ARGUS itself.

L. ORCHESTRATOR_REVIEW_REQUIRED
NONE from this task specifically. Standing items unchanged and unrelated:
PG17_COMPOSE_VALIDATION (see docs/BUILD_STATE.md); the watcher's real
(non-mocked) Claude CLI launch path remains unexercised against an actual
`claude` process in this sandbox.

M. Known bugs / debt
- Known limitation, unchanged in kind from round 2 but narrowed in scope:
  this protocol is file-trust-based, not cryptographically signed. The
  QUARANTINED mechanism now reliably prevents a self-authored instruction
  from ever being evaluated again once the originating run's instructions-
  file tampering is detected (which happens in the SAME tick, checked
  first). What remains inherently unprovable without signing is WHO
  authored any given commit that the watcher does accept as legitimate --
  a real human orchestrator's commit and a hypothetical adversarial one
  that never touches the instructions file and carries a correctly-formed
  trailer are indistinguishable to this protocol by design. Closing that
  would require cryptographic signing outside this protocol's current
  design, explicitly out of scope for this instruction. Stated here
  honestly per CORE-011 rather than overclaiming complete prevention.
- The watcher's real (non-mocked) Claude CLI invocation itself
  (`claude -p <prompt>`) still has not been exercised against a real
  `claude` process in this sandbox -- unchanged limitation from every
  prior round; every test and the real `--once` runs here either mock it
  or never reach the launch step.
- validate_checkpoint_content()/validate_bundle_content() remain
  deliberately simple substring/marker-based structural checks (not a full
  grammar) -- sufficient to reject a placeholder, contradictory duplicate
  field, or mismatched bundle, but not a rigorous document schema.

N. Security state
- No new secrets, no signing-key code, no live-execution code touched.
- Strengthened: raw Claude subprocess stdout/stderr is now never logged at
  all (previously bounded/truncated, which is not credential redaction);
  every log detail is now sanitized against control characters and
  newlines so process output cannot forge a fake log line.
- LIVE_READY_SOFTWARE=false, LIVE_CANARY_PASSED=false, LIVE_ARMED=false --
  unaffected.
- All changes in this task are in the direction of stricter, more
  conservative, more fail-closed behavior -- none relax any prior check.

O. Next specified phase
Per orchestrator instruction argus-watcher-remediation-003: do NOT begin
Phase 1, do NOT modify orchestration/ORCHESTRATOR_INSTRUCTIONS.md, do NOT
self-authorize anything, and do NOT perform or authorize any live trade,
mainnet canary, credential entry, paid-provider upgrade, live arming,
threshold relaxation, or phase skip. Phase 1 remains unauthorized by this
session. STOP. Await further orchestrator review/instruction.

================ END ARGUS CHECKPOINT =========================
