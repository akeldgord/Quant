# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0004-watcher-remediation
UTC_TIMESTAMP: 2026-08-30T23:29:16Z
CURRENT_COMMIT: a700ee11eb2af8ea4a433cbf8a6d807d6078b349
CURRENT_PHASE: 0
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: none (no instruction has been issued through GitHub yet — see orchestration/ORCHESTRATOR_INSTRUCTIONS.md, STATUS: NO_INSTRUCTION; this handoff is for operational tooling remediation the human operator authorized directly, not an ORCHESTRATOR_INSTRUCTIONS.md-authorized task)
CHECKPOINT_PATH: orchestration/checkpoints/watcher_remediation.md
BUNDLE_PATH: orchestration/bundles/watcher_remediation.txt
TEST_STATUS: 63/63 passed (57 pre-existing + 6 new remediation regression tests), 93% src/argus coverage (unchanged), ruff clean, mypy clean
WORKING_TREE: clean (verified via `git status --porcelain` before and after this commit)
ORCHESTRATOR_REVIEW_REQUIRED: none from this task; PG17_COMPOSE_VALIDATION (deferred, unrelated) still open — see docs/BUILD_STATE.md

## Work completed

1. **Phase 0 (Foundation)** built, tested, and remediated. See
   `orchestration/checkpoints/phase_0_remediation.md`.
2. **Orchestration protocol bootstrap + local watcher** (handoff-0003). See
   `orchestration/checkpoints/watcher_setup.md`.
3. **This handoff — watcher remediation**: per human-operator instruction
   relaying an independent audit, re-read the entire audit chain from
   scratch (MASTER_SPEC.md, docs/BUILD_STATE.md, docs/DECISION_LOG.md,
   orchestration/PROTOCOL.md, orchestration/ORCHESTRATOR_INSTRUCTIONS.md,
   this file, every checkpoint/bundle path it names, then the watcher
   implementation and tests line by line) and independently substantiated
   four real defects, fixing all four with dedicated regression tests. See
   `orchestration/checkpoints/watcher_remediation.md` and
   `docs/DECISION_LOG.md` (entry "Watcher remediation: four defects found
   on independent audit") for full detail. Summary of the four:
   - **(A)** `AUTHORIZED_PHASE` was parsed but never validated anywhere —
     a malformed or premature (skip-ahead) phase authorization would have
     reached Claude unchecked, relying entirely on the prompt for
     enforcement. Fixed: the watcher now rejects any `AUTHORIZED_PHASE`
     that isn't a non-negative integer ≤ `current_phase + 1` (read from
     `docs/BUILD_STATE.md`), logging `PHASE_AUTHORIZATION_INVALID`.
   - **(B)** The handoff instruction-id match used substring containment
     (`in`) instead of exact equality — a stale field value that merely
     *contained* the instruction id as a substring would false-positive
     match. Fixed: exact equality.
   - **(C)** `CHECKPOINT_PATH`/`BUNDLE_PATH` were checked only for
     existence — a pre-existing, untouched file at that path would pass.
     Fixed: both paths must now appear in the git diff between HEAD before
     Claude launched and HEAD after the run, proving the evidence was
     actually produced by this run.
   - **(D)** Restart recovery only treated a stale `RUNNING` state as a
     crash; a stale `CLAIMED` state (crash between claiming and actually
     launching) was silently ignored forever with no `FAILED` transition
     or log event. Fixed: both states are now treated as stale on restart.
   All four fixes are strictly more conservative/fail-closed than the
   prior behavior — none relax any existing check.

## Important findings

- All four defects were genuine and substantiated by tracing the exact
  pre-fix code path, not accepted on the audit's account alone — see
  `docs/DECISION_LOG.md` for the specific old-vs-new behavior per bug.
- `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is unchanged — still
  `STATUS: NO_INSTRUCTION`. This task did not authorize, and could not
  have authorized, any ARGUS phase.
- `PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK` is unchanged and
  unrelated — still open, see `docs/BUILD_STATE.md`.
- The watcher's real (non-mocked) Claude CLI launch path remains untested
  against an actual `claude` process in this sandbox — unchanged
  limitation, noted in the original `watcher_setup.md` checkpoint too.

## Failures or limitations

- None new. Same standing limitations as the prior handoff (Docker Hub CDN
  blocked in this sandbox; real Claude CLI launch unexercised).

## Deferred checks

- `PG17_COMPOSE_VALIDATION` (unchanged, unrelated — see
  `docs/DECISION_LOG.md`).
- First real (non-mocked) watcher-triggered Claude launch should still be
  observed by the operator.

## Exact next action requested from orchestrator

Unchanged from the prior handoff: review the Phase 0 evidence
(`orchestration/checkpoints/phase_0_remediation.md`) and the watcher
evidence (`orchestration/checkpoints/watcher_setup.md` +
`orchestration/checkpoints/watcher_remediation.md`), then write an
instruction into `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`
(`STATUS: ACTIVE`, `TARGET_COMMIT` pinned to the exact commit named in the
final handoff message for this task) to authorize the next piece of ARGUS
work. Until that instruction exists, the watcher (if running) takes no
action beyond logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** unchanged from prior handoffs — if you
cloned/fetched this branch before 2026-08-30T22:35 UTC, re-clone or
`git fetch --all && git reset --hard origin/claude/argus-folder-setup-77ahrk`
rather than merging/rebasing the old (pre-rewrite) history.
