================ ARGUS ORCHESTRATOR CHECKPOINT ================

A. Identity
PROJECT: ARGUS
MASTER_SPEC_VERSION: v2.0
MASTER_SPEC_HASH: 41f7242c288feec709b1ed72e62c74a1dc5e3b3cd9ad01e9b6e28373d9d14011
SCOPE: Operational tooling (local orchestrator watcher) — NOT an ARGUS phase.
  current_phase remains 0; no phase gate was crossed.
STATUS: PASS
UTC_TIMESTAMP: 2026-08-30T23:09:24Z
GIT_COMMIT: (this commit — see the COMMIT value returned alongside this checkpoint)
PRE-COMMIT_BASE: aebb33aa39fbd18ef60c3071fb75ef44c2ef8dcf
CONFIG_HASH: 4be41f34b83f1841299ccef8c244362f10beb31ccc1c1bfd3ba819dc1e323b0e

B. What was built
scripts/argus_orchestrator_watch.py — the local "no-nudge" watcher requested
so the human operator no longer needs to manually start Claude for each
ARGUS phase. Stdlib-only Python 3.12 (no Celery/Redis/Kafka, no systemd
dependency in the code, no Docker daemon dependency, no new external
service):
- Polls (default 60s, configurable via --interval / ARGUS_WATCHER_INTERVAL_SECONDS)
  by running `git fetch origin <branch>`, refusing to pull if the local
  worktree is dirty (DIRTY_WORKTREE), then `git pull --ff-only`
  (GIT_PULL_FAILED on failure).
- Parses orchestration/ORCHESTRATOR_INSTRUCTIONS.md's INSTRUCTION_ID /
  TARGET_COMMIT / AUTHORIZED_ACTION / AUTHORIZED_PHASE / STATUS fields.
  Does nothing unless STATUS == ACTIVE and the instruction id is new.
- TARGET_COMMIT protection: verifies the instruction's TARGET_COMMIT
  resolves to a real commit, is an ancestor of current HEAD, and that every
  path that differs between TARGET_COMMIT and HEAD is
  orchestration/ORCHESTRATOR_INSTRUCTIONS.md and nothing else -- i.e. no
  unreviewed implementation drift snuck in alongside the orchestrator's own
  edit. Logs TARGET_COMMIT_MISMATCH and skips the instruction (retried next
  tick, not permanently failed) if this can't be proven safely.
- State machine (IDLE/CLAIMED/RUNNING/COMPLETED/FAILED) persisted atomically
  to runtime/orchestrator_watcher_state.json (gitignored). Claims an
  instruction (CLAIMED then RUNNING) before launching Claude so a watcher
  crash mid-run is visible as a stale RUNNING state on next startup and is
  marked FAILED rather than blindly re-executed.
- Launches the local Claude CLI non-interactively (`claude -p <prompt>` by
  default; `--claude-arg` lets the operator append whatever permission-mode
  flag their local CLI needs) with a prompt that tells it to read
  MASTER_SPEC.md, docs/BUILD_STATE.md, docs/DECISION_LOG.md,
  orchestration/PROTOCOL.md, orchestration/ORCHESTRATOR_INSTRUCTIONS.md,
  orchestration/AGENT_HANDOFF.md (in that order) and then execute only the
  ACTIVE instruction, following MASTER_SPEC.md's phase gates, and to test/
  checkpoint/bundle/handoff/commit/push/STOP when done. The full instruction
  text is not duplicated into the prompt -- the repository files are the
  source of truth.
- After Claude exits, verifies (does not just trust a zero exit code):
  orchestration/AGENT_HANDOFF.md has a new HANDOFF_ID whose
  LAST_ORCHESTRATOR_INSTRUCTION_ID references the instruction just run, and
  that its CHECKPOINT_PATH/BUNDLE_PATH both exist on disk (HANDOFF_VERIFIED
  / RUN_FAILED). Then verifies the worktree is clean and local HEAD matches
  origin/<branch> exactly (catches unpushed or diverged commits). Only then
  RUN_COMPLETED and last_processed_instruction_id is set -- at most one
  Claude launch per unique INSTRUCTION_ID.
- Single-instance protection via an flock-based lock
  (runtime/orchestrator_watcher.lock, kernel-released on crash, no stale-lock
  cleanup needed); a second instance exits immediately.
- runtime/ORCHESTRATION_PAUSED pause file: watcher does not fetch/pull/
  launch while it exists; human-removable to resume.
- Clean SIGINT/SIGTERM handling (finishes current tick, releases lock,
  exits).
- Structured event log at runtime/logs/orchestrator_watcher.log; never logs
  API keys, tokens, credentials, or raw environment/command dumps -- only
  short event strings the watcher constructs itself.

Also: Makefile `orchestrator-watch` target, docs/OPERATIONS.md (usage,
config table, pause mechanism, nohup + optional user-level systemd
background-start examples -- neither installed/enabled automatically),
.gitignore entries for the three new runtime/ files.

C. Files changed
New: scripts/argus_orchestrator_watch.py, tests/unit/test_orchestrator_watch.py.
Modified: .gitignore, Makefile, docs/OPERATIONS.md, docs/BUILD_STATE.md,
orchestration/AGENT_HANDOFF.md (this handoff), orchestration/checkpoints/
watcher_setup.md (this file), orchestration/bundles/watcher_setup.txt.

D. Commands actually run
- uv run ruff check . / uv run ruff format . (both clean)
- uv run mypy (40 source files, clean) and uv run mypy
  scripts/argus_orchestrator_watch.py --ignore-missing-imports directly
  (not in the package's default mypy scope; clean)
- uv run pytest tests/unit/test_orchestrator_watch.py -v (16/16 passed),
  then the full suite: uv run pytest --cov --cov-report=term-missing
  (57/57 passed, 93% coverage on src/argus -- the watcher script itself
  lives outside that coverage scope; its own 16 dedicated tests are the
  verification)
- uv run python scripts/argus_orchestrator_watch.py --once, run twice
  against the real repository: first while the new files were still
  uncommitted (correctly logged DIRTY_WORKTREE and took no git/Claude
  action), second after committing (see state/log excerpts in J)
- grep-based secret scan on the staged diff; git status --porcelain clean
  before commit

E. Test results
pytest: passed: 57, failed: 0, skipped: 0 (41 pre-existing + 16 new watcher
  tests, covering all 11 required scenarios: NO_INSTRUCTION no-launch,
  ACTIVE new instruction launches, duplicate instruction blocked, dirty
  worktree blocks, pull failure blocks, target mismatch blocks (both the
  non-ancestor case and the unreviewed-diff case), stale RUNNING doesn't
  relaunch, pause file blocks, matching handoff -> COMPLETED, missing
  handoff -> FAILED, mismatched instruction id in handoff -> FAILED, dirty
  tree after Claude run -> FAILED, two watcher instances can't hold the
  lock concurrently)
coverage: 93% (src/argus, unchanged from prior checkpoint; watcher script
  covered by its own dedicated test suite instead)
ruff: All checks passed!
mypy: Success: no issues found in 40 source files (+ watcher script clean
  when checked directly)

F. Acceptance criteria (this task's explicit test list)
[PASS] NO_INSTRUCTION does not launch
[PASS] ACTIVE new instruction launches
[PASS] same instruction cannot run twice
[PASS] dirty worktree blocks launch
[PASS] pull failure blocks launch
[PASS] target mismatch blocks launch
[PASS] stale RUNNING state does not relaunch
[PASS] pause file blocks launch
[PASS] new matching handoff marks completed
[PASS] missing/mismatched handoff marks failed
[PASS] two watcher instances cannot run
[PASS] no Claude-model tokens spent by tests (Claude CLI fully mocked via
  an injected runner callable in every test)

G. Database/data sanity
Unchanged -- this task touched no schema, migration, or database code.

H. Provider usage
Not applicable.

I. Data quality warnings
None new. PG17_COMPOSE_VALIDATION remains DEFERRED_ENVIRONMENTAL_CHECK
(unchanged by this task; unrelated to the watcher).

J. Sample outputs
`uv run python scripts/argus_orchestrator_watch.py --once` against the real
repo while orchestration/ORCHESTRATOR_INSTRUCTIONS.md still read
STATUS: NO_INSTRUCTION (as it does now -- this task did not touch that
file):
  <timestamp> NO_ACTIVE_INSTRUCTION status='NO_INSTRUCTION'
No Claude process was launched (confirmed: tick() returns before reaching
the launch step whenever STATUS != ACTIVE).

K. Architectural deviations
NONE. No MASTER_SPEC.md change. No ARGUS architecture change. This is
operational tooling sitting alongside the existing orchestration protocol,
not a modification to it.

L. ORCHESTRATOR_REVIEW_REQUIRED
NONE from this task specifically. The standing item from the prior
checkpoint (PG17_COMPOSE_VALIDATION) is unrelated and still open -- see
docs/BUILD_STATE.md.

M. Known bugs / debt
- The exact Claude CLI non-interactive invocation (`claude -p <prompt>`) is
  a best-effort default; `--claude-arg` exists specifically because the
  right permission-mode flag for unattended runs may vary by local Claude
  CLI version/config and could not be verified from inside this sandbox
  (no long-running local Claude CLI process was launched by this task --
  see N).
- The watcher's own coverage is not folded into the `src/argus`
  coverage-percentage gate (it lives in scripts/, outside that package);
  its correctness rests on the 16 dedicated tests instead of a blanket
  percentage.

N. Security state
- No new secrets, no signing-key code, no live-execution code. The watcher
  itself never touches credentials -- it only runs `git` subprocess calls
  and launches the Claude CLI, and its logging explicitly avoids raw
  command output/env dumps.
- This task did NOT actually launch a real Claude CLI process at any point
  (every test mocks it; the one real `--once` run against this repository
  hit the NO_ACTIVE_INSTRUCTION short-circuit before any launch code path).
  So the exact non-interactive CLI invocation is implemented and unit-
  tested via the mock, but has not been end-to-end verified against a real
  `claude` binary launch in this sandbox.
- LIVE_READY_SOFTWARE=false, LIVE_CANARY_PASSED=false, LIVE_ARMED=false —
  unaffected by this task.

O. Next specified phase
Per the human operator's explicit instruction for this task: do NOT begin
Phase 1, and do NOT wait for an orchestrator instruction inside this
session. orchestration/ORCHESTRATOR_INSTRUCTIONS.md remains
STATUS: NO_INSTRUCTION (untouched by this task). The only authorized work
in this task was building and testing the watcher, which is complete.

================ END ARGUS CHECKPOINT =========================
