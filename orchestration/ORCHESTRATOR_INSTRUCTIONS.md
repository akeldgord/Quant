# ARGUS Orchestrator Instructions

**OWNER: ARGUS ORCHESTRATOR.** The implementation agent must not modify this
file. Execute only the ACTIVE instruction below. MASTER_SPEC.md remains
authoritative except for the explicit operational-protocol decisions stated
here.

---

INSTRUCTION_ID: argus-watcher-remediation-002
ISSUED_AT: 2026-08-31T02:07:44Z
TARGET_COMMIT: 79287b573bd0cc106d26d5f2001f919b11d61625
AUTHORIZED_ACTION: REMEDIATE_ORCHESTRATION_WATCHER_ONLY
AUTHORIZED_PHASE: 0
APPROVES_PHASE: NONE
STATUS: ACTIVE

## Independent audit disposition

- Phase 0 remains acceptable as
  `PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`.
- `PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK` remains open and
  must be completed against real PostgreSQL 17 before live readiness.
- Watcher remediation at TARGET_COMMIT is REJECTED. The four reported fixes
  are real, but the watcher is not yet deterministic, restart-safe,
  idempotent, and fail-closed enough for unattended phase advancement.
- Phase 1 is NOT authorized by this instruction.
- Do not change `last_orchestrator_approved_phase`, `approved_commit`, or
  begin any Phase 1 implementation.

## Scope

Remediate only the GitHub orchestration protocol, local watcher, its tests,
and directly related operational documentation/evidence. Do not change
MASTER_SPEC.md or ARGUS application architecture. Allowed implementation
files are limited to:

- `scripts/argus_orchestrator_watch.py`
- `tests/unit/test_orchestrator_watch.py`
- `orchestration/PROTOCOL.md`
- `docs/OPERATIONS.md`
- `docs/DECISION_LOG.md`
- the operational-tooling note in `docs/BUILD_STATE.md`
- a new checkpoint, bundle, and `orchestration/AGENT_HANDOFF.md`

If a required safety fix cannot be made inside that scope, stop with
`STATUS: PARTIAL` and request orchestrator review. Do not broaden scope
silently.

## Required remediation

### 1. Durable replay protection and invalid-state fail-closed behavior

The current `read_state()` converts a missing, unreadable, or malformed
state file into a fresh `IDLE` state. If an old instruction remains ACTIVE,
that can replay an already claimed or completed instruction.

Implement explicit state outcomes. At minimum:

- A malformed, unreadable, schema-invalid, or unknown-status state file must
  produce a visible `STATE_INVALID`/equivalent failure and must not launch
  Claude.
- When an ACTIVE instruction exists, an unexpectedly missing state file must
  fail closed rather than assume first execution.
- State initialization may occur only in a clearly safe condition such as
  `STATUS: NO_INSTRUCTION`.
- Cross-check the current handoff so loss of local state cannot replay an
  instruction already recorded as completed/handed off.
- Validate field types and `current_status` against `VALID_STATUSES`.
- Preserve atomic writes; add appropriate flush/fsync durability for the
  state file and parent directory.
- Never auto-retry a CLAIMED, RUNNING, FAILED, ambiguous, or previously
  handed-off instruction. A retry requires a new `INSTRUCTION_ID`.

### 2. Failed Claude process must fail the run

The current code records a nonzero exit code or timeout, then can still mark
the run COMPLETED if handoff files exist.

- A nonzero Claude exit, timeout, `FileNotFoundError`, or other launch
  exception must mark the run FAILED before success verification.
- Do not accept a handoff as COMPLETED after a failed Claude process.
- Log a bounded diagnostic without dumping environment variables,
  credentials, or unbounded raw subprocess output.

### 3. Evidence must be new, immutable, and structurally valid

The current diff-membership check still accepts an old checkpoint/bundle
that was lightly edited, and it accepts empty or malformed new files.

Require all of the following:

- `CHECKPOINT_PATH` and `BUNDLE_PATH` are normalized repository-relative
  paths inside `orchestration/checkpoints/` and
  `orchestration/bundles/`, respectively; reject absolute paths, `..`,
  symlinks, wrong directories, and wrong extensions.
- Both evidence paths must be newly added during this run, not merely
  modified. An evidence path present at pre-launch HEAD is stale and must
  fail.
- Do not overwrite any prior checkpoint or bundle.
- The checkpoint must be nonempty, begin and end with the standard ARGUS
  checkpoint markers, identify PROJECT ARGUS, identify the authorized
  phase or explicit operational-remediation scope, contain STATUS,
  GIT_COMMIT, commands actually run, test results, acceptance criteria,
  deviations, known debt, security state, and the next-action/STOP statement.
- The bundle must be nonempty, contain the checkpoint, and contain the
  required review sections/evidence. A one-line placeholder must fail.
- Validate `AGENT_HANDOFF.md` as a complete schema, not only four fields.
  Require every field in PROTOCOL section 5 exactly once. Reject duplicates,
  missing fields, unresolved/foreign CURRENT_COMMIT values, a reused
  HANDOFF_ID, and an inexact instruction-ID match.
- `CURRENT_COMMIT` and checkpoint `GIT_COMMIT` must resolve to commits
  created during this run (they may be an implementation commit that is an
  ancestor of a final documentation-only hash-fill commit).

### 4. Detect branch movement and unattributed commits

The final local-equals-remote check is not enough. Claude can pull a
concurrent unreviewed commit during its run and still finish with local and
remote equal.

Mechanically enforce:

- Capture local HEAD, remote branch HEAD, instruction-file blob/content hash,
  and handoff ID immediately before launch. Local and remote HEAD must match.
- Post-run HEAD must descend linearly from pre-launch HEAD. Reject rewritten
  ancestry, non-fast-forward movement, and merge commits in the run range.
- Every commit after pre-launch HEAD must carry the exact trailer
  `ARGUS-INSTRUCTION-ID: argus-watcher-remediation-002` for this run.
  Implement this generically using the current instruction ID, not a
  hardcoded remediation ID.
- Reject any post-launch commit in the range without the exact trailer. This
  makes concurrent/unattributed branch movement visible.
- Continue requiring the final clean worktree and exact local/remote HEAD
  equality.

### 5. Mechanically prevent implementation-agent self-authorization

The implementation agent owns handoffs, not instructions.

- The bytes/blob of `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` after the
  run must exactly equal the pre-launch version.
- Any implementation-agent modification of that file during a run must mark
  the run FAILED, even if it was later committed and pushed.
- Add this prohibition explicitly to `CLAUDE_PROMPT` and PROTOCOL.md.
- Add a regression test where the simulated Claude run implements work,
  writes a new ACTIVE next-phase instruction, commits, and pushes it. The
  watcher must reject the run and must not later launch that self-authored
  instruction.

### 6. Make phase gating explicit and support Phase 1.5

The integer/current+1 rule is incomplete and its current prose is
contradictory. It permits Phase 1 while BUILD_STATE still says Phase 0 is
awaiting review, and it cannot represent the mandatory Phase 1.5 gate.

Update the protocol and watcher to use the canonical ordered phase sequence:

`0, 1, 1.5, 2, 3, 4, 5, 6, 6.5, 7, 8, 9, 10, 11`

Use normalized strings or another exact representation; do not use binary
floating-point ordering.

Add and enforce the structured `APPROVES_PHASE` field:

- Same-phase remediation: `AUTHORIZED_PHASE` may equal `current_phase`
  and `APPROVES_PHASE` must be `NONE`.
- Advancing to the immediate successor requires
  `APPROVES_PHASE == current_phase`, `last_completed_phase ==
  current_phase`, and `awaiting_orchestrator_review == true`.
- No instruction may skip a phase or sub-phase.
- Claude must never infer approval or change approval fields without an
  ACTIVE orchestrator instruction.
- This current instruction is same-phase operational remediation:
  `AUTHORIZED_PHASE: 0`, `APPROVES_PHASE: NONE`.
- Update PROTOCOL.md wording so it accurately describes the enforced rule.

### 7. Strict instruction parsing

For an ACTIVE instruction, require every structured field exactly once.
Reject duplicates, missing/empty required fields, unknown status values,
malformed UTC timestamp, non-full TARGET_COMMIT SHA, empty/NONE
AUTHORIZED_ACTION, invalid phase identifiers, and invalid APPROVES_PHASE.
Do not silently accept the first of duplicate contradictory fields.

Preserve `NO_INSTRUCTION` placeholder support with an explicitly validated
safe schema.

### 8. Conservative verification order

After Claude returns, verify in this order:

1. process exit success,
2. pre/post ancestry and commit attribution,
3. instruction file unchanged,
4. complete handoff and new evidence structure,
5. clean worktree and exact pushed remote HEAD.

Any failed check must persist FAILED, log the reason, and never mark the
instruction processed or auto-retry it.

## Mandatory adversarial regression tests

Keep all existing useful tests and add tests proving at least:

1. missing state + ACTIVE instruction does not launch;
2. corrupt JSON state does not launch;
3. invalid state schema/status does not launch;
4. a completed/handoff-recorded instruction cannot replay after state loss;
5. nonzero Claude exit with otherwise valid handoff/evidence is FAILED;
6. timeout and launch exception are FAILED;
7. modified pre-existing checkpoint/bundle is rejected;
8. empty/malformed newly added checkpoint is rejected;
9. empty/malformed newly added bundle is rejected;
10. missing and duplicate handoff fields are rejected;
11. foreign/absolute/path-traversal/symlink evidence paths are rejected;
12. post-run HEAD not descending from pre-launch HEAD is rejected;
13. a merge commit in the run range is rejected;
14. a concurrent commit without the exact instruction trailer is rejected;
15. a run commit with the wrong/substr-matching trailer is rejected;
16. an implementation-agent change to ORCHESTRATOR_INSTRUCTIONS is rejected;
17. a self-authored next-phase instruction cannot launch;
18. duplicate instruction fields are rejected;
19. malformed timestamp/full-SHA/action are rejected;
20. Phase 1 is blocked while Phase 0 is incomplete or lacks explicit
    `APPROVES_PHASE: 0`;
21. Phase 1 is allowed only with the exact predecessor approval and completed
    state;
22. Phase 1.5 is accepted only as the immediate successor of completed
    Phase 1 with `APPROVES_PHASE: 1`;
23. Phase 2 is blocked directly from Phase 1;
24. stale CLAIMED and RUNNING remain fail-closed;
25. dirty worktree and unpushed/diverged commits remain blocked;
26. a valid same-phase remediation run still completes as a negative control.

Use real temporary git repositories for git behavior. The Claude process
must remain mocked in unit tests. Ensure successful fake handoffs use
realistic, structurally valid checkpoint/bundle content; a placeholder such
as `checkpoint\n` must no longer count as success.

## Validation and handoff

Run and record exact results for:

- `uv run pytest tests/unit/test_orchestrator_watch.py -v`
- `uv run pytest --cov --cov-report=term-missing`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy`
- `uv run mypy scripts/argus_orchestrator_watch.py --ignore-missing-imports`

Create new immutable evidence paths:

- `orchestration/checkpoints/watcher_remediation_2.md`
- `orchestration/bundles/watcher_remediation_2.txt`

Update `orchestration/AGENT_HANDOFF.md` with:

- a new unique HANDOFF_ID;
- `LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-watcher-remediation-002`
  exactly;
- the two new evidence paths above;
- honest failures, limitations, and deferred checks;
- Phase 1 still blocked;
- the real Claude CLI launch path and PG17 validation called out separately.

Every commit created for this run, including documentation/hash-fill commits,
must include this exact commit-message trailer:

`ARGUS-INSTRUCTION-ID: argus-watcher-remediation-002`

Commit and push to `claude/argus-folder-setup-77ahrk`. Verify the remote
branch equals local HEAD and the working tree is clean. Then STOP. Do not
begin Phase 1 and do not modify this instruction file.
