# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0005-watcher-remediation-2
UTC_TIMESTAMP: 2026-08-31T02:52:00Z
CURRENT_COMMIT: 7a46af842d705736ea6284eeccb9c3d8d76c89c1
CURRENT_PHASE: 0
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-watcher-remediation-002
CHECKPOINT_PATH: orchestration/checkpoints/watcher_remediation_2.md
BUNDLE_PATH: orchestration/bundles/watcher_remediation_2.txt
TEST_STATUS: watcher suite 51/51 passed; full suite 88 passed, 4 skipped (pre-existing, unrelated Postgres-integration skips); ruff clean; mypy clean
WORKING_TREE: clean (verified via `git status --porcelain` before and after this commit)
ORCHESTRATOR_REVIEW_REQUIRED: none from this task; PG17_COMPOSE_VALIDATION (deferred, unrelated) still open — see docs/BUILD_STATE.md

## Work completed

Executed orchestrator instruction `argus-watcher-remediation-002` in full.
The orchestrator had reviewed the prior watcher remediation
(`orchestration/checkpoints/watcher_remediation.md`, commit `a700ee1`) and
rejected it as insufficient for unattended phase advancement: the four
fixes it contained were real, but the watcher was "not yet deterministic,
restart-safe, idempotent, and fail-closed enough." This task substantially
rewrote `scripts/argus_orchestrator_watch.py` and
`tests/unit/test_orchestrator_watch.py` to close all 8 numbered
requirement categories in that instruction:

1. **Durable, fail-closed state handling.** A malformed/corrupt/
   schema-invalid state file now fails closed (`STATE_INVALID`) without
   being rewritten. A missing state file with an `ACTIVE` instruction
   outstanding is cross-checked against `orchestration/AGENT_HANDOFF.md`
   (git-tracked, survives a local `runtime/` wipe) rather than assumed to
   be a first execution — it either recognizes the instruction as already
   completed (`STATE_REBUILT_FROM_HANDOFF`) or fails closed
   (`STATE_MISSING_FAIL_CLOSED`, requiring a new `INSTRUCTION_ID`). State
   writes now `fsync` the file and its parent directory.
2. **A failed Claude process now always fails the run.** This was the
   literal originally-reported bug: `tick()` recorded `exit_code` but never
   branched on it before verifying the handoff, so a nonzero exit, a
   timeout, or a launch-time `OSError` could still be accepted as
   `COMPLETED` if evidence files happened to look valid. Fixed: the run is
   failed immediately on a non-zero/`None` exit code, before any other
   verification runs.
3. **Evidence must be new, immutable, and structurally valid.**
   `CHECKPOINT_PATH`/`BUNDLE_PATH` are normalized/validated
   (repository-relative, correct directory/extension, no
   traversal/absolute/symlink paths), must not have existed at the
   pre-launch `HEAD`, must be newly *added* (not modified), and their
   content is now structurally validated — a one-line placeholder fails.
   `AGENT_HANDOFF.md` is validated against the full 11-field schema
   (previously only 4 of 11 fields were checked).
4. **Branch-movement and commit-attribution detection.** Local/remote
   `HEAD` compared immediately before launch; post-run `HEAD` must descend
   linearly (no rewritten ancestry, no merge commits); every commit in the
   run's range must carry the exact trailer
   `ARGUS-INSTRUCTION-ID: argus-watcher-remediation-002` — a
   substring-matching or reworded trailer is rejected.
5. **Mechanical self-authorization prevention.** The blob hash of
   `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is compared before/after
   the run (via `git hash-object` against the live file, catching an
   uncommitted edit too); any difference fails the run outright.
6. **Explicit, sequence-based phase gating with Phase 1.5 support.** A new
   `PHASE_SEQUENCE` (`"0", "1", "1.5", "2", ..., "6", "6.5", ..., "11"`,
   string tokens, never floats) and a new `APPROVES_PHASE` instruction
   field distinguish same-phase remediation from phase advancement, with
   no skipping a phase or sub-phase.
7. **Strict instruction-field parsing.** Duplicate/missing/malformed
   fields are rejected for an `ACTIVE` instruction.
8. **Conservative, ordered post-run verification**: process-exit success,
   then ancestry/attribution, then instructions-file integrity, then
   handoff/evidence completeness, then clean-worktree/pushed-HEAD equality.

Also added a defensive `try`/`except` around each `tick()` call inside
`run_forever()` so one bad tick cannot crash the whole watcher process.
`orchestration/PROTOCOL.md` (sections 4, 5, 7) and `docs/OPERATIONS.md`
were updated to document all of the above as mechanically-enforced
requirements. Full per-category detail:
`orchestration/checkpoints/watcher_remediation_2.md` and
`docs/DECISION_LOG.md` (entry "Watcher remediation round 2:
orchestrator-requested hardening (argus-watcher-remediation-002)").

## Important findings

- Section 2 (failed Claude process accepted as COMPLETED) was independently
  re-derived from the code, not accepted only on the orchestrator's
  say-so: `tick()` did in fact capture `exit_code` but never checked it
  before calling `verify_handoff()`. This is now fixed and covered by
  `test_nonzero_exit_with_valid_handoff_is_failed`, which constructs
  exactly that scenario (valid handoff + evidence, exit_code=1) and proves
  the run is `FAILED`.
- `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is unchanged — still the
  orchestrator's `argus-watcher-remediation-002` instruction, `STATUS:
  ACTIVE`. This task did not authorize, and could not have authorized, any
  ARGUS phase.
- `PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK` is unchanged and
  unrelated — still open, see `docs/BUILD_STATE.md`.

## Failures or limitations

- **Known, honestly-stated limitation on self-authorization prevention**
  (requirement section 5): this protocol is file-trust-based, not
  cryptographically signed. The blob-hash-unchanged check reliably catches
  an implementation agent that edits the live instructions file (committed
  or not), and the target-commit diff-scope check independently catches a
  self-authored instruction whose `TARGET_COMMIT` points at the pre-launch
  `HEAD` while other files also changed in the same range — the realistic
  case, and the one `test_self_authored_instruction_cannot_launch`
  exercises. A maximally adversarial run that points a self-authored
  instruction's `TARGET_COMMIT` at its own freshly-created `HEAD` is not
  fully excluded by these mechanisms alone; closing that completely would
  require a cryptographic signing step outside this protocol's current
  file-trust design. This is stated here explicitly rather than
  overclaimed, per CORE-011.
- The watcher's real (non-mocked) Claude CLI launch path remains untested
  against an actual `claude` process in this sandbox — unchanged
  limitation from every prior round.
- `validate_checkpoint_content()`/`validate_bundle_content()` are
  deliberately simple substring/marker-based structural checks, not a full
  document grammar — sufficient to reject a placeholder or wildly
  malformed document, not a rigorous schema.

## Deferred checks

- `PG17_COMPOSE_VALIDATION` (unchanged, unrelated — see
  `docs/DECISION_LOG.md`).
- First real (non-mocked) watcher-triggered Claude launch should still be
  observed by the operator.
- Full cryptographic closure of the self-authorization-prevention gap
  (see "Failures or limitations" above) — a protocol-design question for
  the orchestrator, out of scope for this instruction.

## Exact next action requested from orchestrator

Review this remediation's evidence
(`orchestration/checkpoints/watcher_remediation_2.md` and
`orchestration/bundles/watcher_remediation_2.txt`) against the 8 numbered
requirement sections and 26 mandatory adversarial test categories in
instruction `argus-watcher-remediation-002`. If accepted, write the next
`ACTIVE` instruction into `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`
(`TARGET_COMMIT` pinned to the exact commit named in the final handoff
message for this task) to authorize the next piece of ARGUS or
operational-tooling work. Until that instruction exists, the watcher (if
running) takes no action beyond logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** unchanged from prior handoffs — if you
cloned/fetched this branch before 2026-08-30T22:35 UTC, re-clone or
`git fetch --all && git reset --hard origin/claude/argus-folder-setup-77ahrk`
rather than merging/rebasing the old (pre-rewrite) history.
