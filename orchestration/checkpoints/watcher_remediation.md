================ ARGUS ORCHESTRATOR CHECKPOINT ================

A. Identity
PROJECT: ARGUS
MASTER_SPEC_VERSION: v2.0
MASTER_SPEC_HASH: 41f7242c288feec709b1ed72e62c74a1dc5e3b3cd9ad01e9b6e28373d9d14011
SCOPE: Operational tooling remediation (local orchestrator watcher) — NOT
  an ARGUS phase. current_phase remains 0; no phase gate was crossed;
  orchestration/ORCHESTRATOR_INSTRUCTIONS.md was not modified.
STATUS: PASS
UTC_TIMESTAMP: 2026-08-30T23:29:16Z
GIT_COMMIT: (this commit — see the COMMIT value returned alongside this checkpoint)
PRE-COMMIT_BASE: cb52571ce1bb55ff410cc314568a7d20647f4470
CONFIG_HASH: 4be41f34b83f1841299ccef8c244362f10beb31ccc1c1bfd3ba819dc1e323b0e

B. What was built

Per human-operator instruction relaying an independent audit (performed by
a separate reviewer referred to as "ChatGPT"), the watcher and its tests
were re-read from scratch — not trusted from the prior build's own
account — starting with MASTER_SPEC.md, docs/BUILD_STATE.md,
docs/DECISION_LOG.md, orchestration/PROTOCOL.md,
orchestration/ORCHESTRATOR_INSTRUCTIONS.md, orchestration/AGENT_HANDOFF.md,
every checkpoint/bundle path AGENT_HANDOFF.md names, then
scripts/argus_orchestrator_watch.py and tests/unit/test_orchestrator_watch.py
line by line. Four defects were independently substantiated (each
reproduced by tracing the exact old code path, not merely asserted) and
fixed. Full detail and reasoning: docs/DECISION_LOG.md, entry "Watcher
remediation: four defects found on independent audit".

(A) AUTHORIZED_PHASE parsed but never validated. tick() read
`instructions.authorized_phase` into InstructionFields but no code path
ever checked it against anything — phase-gate enforcement rested entirely
on the Claude prompt text ("Follow all phase gates in MASTER_SPEC.md"),
not on the watcher. A malformed value (e.g. "one") or a value that skipped
ahead of docs/BUILD_STATE.md's current_phase (e.g. AUTHORIZED_PHASE: 2
while current_phase: 0) would have reached Claude unchecked. Fix: added
read_current_phase() (parses `current_phase:` from docs/BUILD_STATE.md)
and verify_phase_authorization(), which requires AUTHORIZED_PHASE to be a
non-negative integer no greater than current_phase + 1. A failing check
logs PHASE_AUTHORIZATION_INVALID and does not launch Claude. This is what
makes "Phase 1 must not be authorized" (while current_phase is still 0) an
enforced property of the watcher itself.

(B) Handoff instruction-id match used substring containment. The original
check was `if instruction_id not in last_instruction`, i.e. Python's `in`
operator on the LAST_ORCHESTRATOR_INSTRUCTION_ID string. A stale or
unrelated field value that merely *contained* the new instruction id as a
substring (e.g. id "instr-1" is a substring of a leftover "instr-12")
would false-positive match. Fix: changed to exact string equality
(`last_instruction != instruction_id` after stripping).

(C) Checkpoint/bundle evidence checked only for existence. verify_handoff()
originally only called `.exists()` on CHECKPOINT_PATH/BUNDLE_PATH — a file
left over from an earlier handoff, at the same path, untouched by the
current run, would pass. Fix: verify_handoff() now takes a `head_before`
parameter (HEAD captured immediately before Claude was launched) and
additionally requires both paths to appear in
`git diff --name-only head_before HEAD` — i.e. to actually be part of the
commits made during this run. If HEAD did not move at all during the run,
the check fails immediately ("no new commits were made during this run")
rather than accepting stale evidence by default.

(D) Restart recovery only handled a stale RUNNING state. The top-of-tick
check that detects a crashed prior run and marks it FAILED (rather than
blindly re-executing) originally only matched `current_status == "RUNNING"`.
A crash between the CLAIMED write and the RUNNING write left the state
file at CLAIMED, which the later duplicate-instruction guard silently
skipped forever with no FAILED transition and no log event — invisible to
an operator or auditor. Fix: the stale-state check now matches
`current_status in {"RUNNING", "CLAIMED"}`, logging RUN_FAILED with the
specific stale status in either case.

Also: CLAUDE_PROMPT and orchestration/PROTOCOL.md sections 5 and 7 were
updated to document these as mechanically-enforced requirements (exact
instruction-id match, evidence must be part of the run's own commits,
AUTHORIZED_PHASE bound by current_phase + 1), so a real future Claude run
producing a handoff is told what the watcher actually checks rather than
discovering it by failing.

C. Files changed
Modified: scripts/argus_orchestrator_watch.py, tests/unit/test_orchestrator_watch.py,
orchestration/PROTOCOL.md, docs/OPERATIONS.md, docs/DECISION_LOG.md,
docs/BUILD_STATE.md. New: orchestration/checkpoints/watcher_remediation.md
(this file), orchestration/bundles/watcher_remediation.txt,
orchestration/AGENT_HANDOFF.md (updated in place, per its single-current-
status-file convention).

D. Commands actually run
- Independent re-read of the full audit chain (files listed in B above),
  via the Read tool, from a fresh `git pull --ff-only` at session start.
- uv run ruff check . / uv run ruff format . (both clean)
- uv run mypy scripts/argus_orchestrator_watch.py --ignore-missing-imports
  and uv run mypy (full package) — both clean
- uv run pytest tests/unit/test_orchestrator_watch.py -v, run twice: once
  immediately after the BUILD_STATE.md test-fixture update (16/16 passed,
  pre-existing tests only), once after adding the 6 new remediation tests
  (22/22 passed)
- uv run pytest --cov --cov-report=term-missing (full suite): 63/63 passed,
  93% coverage on src/argus (unchanged)
- uv run python scripts/argus_orchestrator_watch.py --once against the
  real repository (STATUS: NO_INSTRUCTION unchanged) — correctly logged
  DIRTY_WORKTREE while the fix was still uncommitted, took no git/Claude
  action
- grep-based secret scan on the staged diff; git status --porcelain clean
  before commit; git fetch + SHA comparison against origin after push

E. Test results
pytest: passed: 63, failed: 0, skipped: 0 (57 pre-existing + 6 new
  remediation regression tests: phase skip-ahead blocked, malformed
  AUTHORIZED_PHASE blocked, same-or-next-phase still allowed [negative
  control], substring-false-positive handoff id now correctly FAILED,
  stale pre-existing checkpoint/bundle now correctly FAILED, stale CLAIMED
  state on restart now correctly FAILED)
coverage: 93% (src/argus, unchanged — the watcher lives outside that
  coverage scope and is verified by its own 22 dedicated tests instead)
ruff: All checks passed!
mypy: Success: no issues found in 40 source files (+ watcher script clean
  when checked directly)

F. Acceptance criteria (this task)
[PASS] Bug A (AUTHORIZED_PHASE unvalidated) substantiated and fixed, with
  both a positive (skip-ahead blocked) and negative-control (same/next
  phase still allowed) regression test
[PASS] Bug B (substring instruction-id match) substantiated and fixed,
  with a regression test proving the specific false-positive case
[PASS] Bug C (stale checkpoint/bundle accepted by existence check alone)
  substantiated and fixed, with a regression test using a pre-existing,
  untouched file at the evidence path
[PASS] Bug D (stale CLAIMED state not recovered on restart) substantiated
  and fixed, with a regression test
[PASS] Adversarial categories from the task explicitly covered across the
  full 22-test watcher suite: stale checkpoint/bundle data (new), target-
  commit mismatch (pre-existing, 2 tests), branch/head movement (covered
  by the unreviewed-diff target-commit test + the new no-new-commits
  evidence check), malformed or missing evidence (new AUTHORIZED_PHASE
  tests + pre-existing missing-handoff test), incomplete checkpoint
  bundles (new stale-evidence test), duplicate/replayed state
  (pre-existing same-instruction test), restart during a transition (new
  CLAIMED test + pre-existing RUNNING test), failed audit/remediation
  state (FAILED status never auto-retried, pre-existing + new tests all
  assert this), ACTIVE instruction handling (pre-existing + new phase
  tests), conditions where Phase 1 must NOT be authorized (new
  AUTHORIZED_PHASE skip-ahead test is a direct instance of this)
[PASS] All new tests confirmed to be real regressions, not vacuous: traced
  against the pre-fix code path for each (see docs/DECISION_LOG.md impact
  section for the specific old-vs-new behavior per bug)
[PASS] orchestration/ORCHESTRATOR_INSTRUCTIONS.md not modified
[PASS] Phase 1 not self-authorized

G. Database/data sanity
Unchanged — this task touched no schema, migration, or database code.

H. Provider usage
Not applicable.

I. Data quality warnings
None new. PG17_COMPOSE_VALIDATION remains DEFERRED_ENVIRONMENTAL_CHECK
(unchanged by this task; unrelated).

J. Sample outputs
Regression test names and what each proves (see
tests/unit/test_orchestrator_watch.py for full bodies):
  test_authorized_phase_skip_ahead_blocks_launch      -> Bug A, positive
  test_authorized_phase_malformed_blocks_launch        -> Bug A, positive
  test_authorized_phase_same_or_next_is_allowed        -> Bug A, negative control
  test_handoff_substring_false_positive_now_fails      -> Bug B
  test_stale_preexisting_checkpoint_bundle_marks_failed -> Bug C
  test_claimed_state_restart_marks_failed              -> Bug D

`uv run python scripts/argus_orchestrator_watch.py --once` against the
real repo (STATUS: NO_INSTRUCTION unchanged throughout this task):
  <timestamp> DIRTY_WORKTREE local worktree has uncommitted changes; not pulling
(logged while the fix itself was still uncommitted -- expected and correct;
no Claude process was launched)

K. Architectural deviations
NONE. No MASTER_SPEC.md change. No ARGUS architecture change.

L. ORCHESTRATOR_REVIEW_REQUIRED
NONE from this task specifically. Standing items unchanged and unrelated:
PG17_COMPOSE_VALIDATION (see docs/BUILD_STATE.md); the general outstanding
ask for the orchestrator to review Phase 0 evidence and write the first
real instruction into orchestration/ORCHESTRATOR_INSTRUCTIONS.md.

M. Known bugs / debt
- The watcher's Claude CLI invocation itself (`claude -p <prompt>`) still
  has not been exercised against a real `claude` process in this sandbox —
  unchanged limitation from the original build, unrelated to this
  remediation (every test and the real `--once` runs here either mock it
  or never reach the launch step).
- verify_phase_authorization()'s "no more than one phase ahead" rule
  assumes strictly sequential phase numbering (0, 1, 2, ...) as
  MASTER_SPEC.md defines; it does not attempt to validate sub-phases like
  "1.5" (MASTER_SPEC.md Phase 1.5) since AUTHORIZED_PHASE is defined as an
  integer field in the existing protocol contract. If a future instruction
  needs to authorize a sub-phase, that's a protocol-contract question for
  the orchestrator, not something this fix silently guesses at.

N. Security state
- No new secrets, no signing-key code, no live-execution code touched.
- The watcher's credential-avoidance logging posture is unchanged (still
  never logs raw command output, env vars, or credentials).
- LIVE_READY_SOFTWARE=false, LIVE_CANARY_PASSED=false, LIVE_ARMED=false —
  unaffected.
- The four fixes are all in the direction of stricter, more conservative,
  more fail-closed behavior — none relax any prior check.

O. Next specified phase
Per the human operator's explicit instruction: do NOT begin Phase 1, and
do NOT self-authorize it. orchestration/ORCHESTRATOR_INSTRUCTIONS.md
remains STATUS: NO_INSTRUCTION (untouched by this task). Phase 1 has not
been authorized by this session, and no independent audit visible to this
session has legitimately authorized it either.

================ END ARGUS CHECKPOINT =========================
