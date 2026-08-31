# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0006-watcher-remediation-3
UTC_TIMESTAMP: 2026-08-31T04:00:00Z
CURRENT_COMMIT: 50e6d91b9cfeb40be14cf43a0b9f0b2c7582bd74
CURRENT_PHASE: 0
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-watcher-remediation-003
CHECKPOINT_PATH: orchestration/checkpoints/watcher_remediation_3.md
BUNDLE_PATH: orchestration/bundles/watcher_remediation_3.txt
TEST_STATUS: watcher suite 74/74 passed; full suite 111 passed, 4 skipped (pre-existing, unrelated Postgres-integration skips); ruff clean; mypy clean
WORKING_TREE: clean (verified via `git status --porcelain` before and after this commit)
ORCHESTRATOR_REVIEW_REQUIRED: none from this task; PG17_COMPOSE_VALIDATION (deferred, unrelated) still open — see docs/BUILD_STATE.md

## Work completed

Executed orchestrator instruction `argus-watcher-remediation-003` in full.
The orchestrator reviewed watcher remediation round 2
(`orchestration/checkpoints/watcher_remediation_2.md`, commit `34930bf`)
and rejected it with six concrete, reproducible defect categories. Each
was independently traced against round 2's actual code before being
fixed, not accepted on the audit's account alone:

1. **A self-authored next instruction could still launch on a later
   tick.** Round 2's blob-hash check correctly failed the *originating*
   run, but only as an ordinary `FAILED` — a self-authored instruction
   whose `TARGET_COMMIT` pointed at the immediately preceding legitimate
   implementation commit, with a diff touching only the instructions
   file, would structurally pass round 2's target-commit check on the
   *next* tick, since a new `INSTRUCTION_ID` isn't blocked by the
   "already attempted" guard. Fixed with two independent layers: (a) a
   detected instructions-file modification is now a terminal,
   non-retryable `QUARANTINED` state — checked first and unconditionally
   in `tick()`, ahead of every other verification, so it can never be
   pre-empted by another check failing first — from which no future
   instruction of any ID or target is ever evaluated again until a human
   runs the new `--reset-quarantine` CLI flag after manual review; (b)
   `verify_target_commit()` independently tightened to require exactly
   one instruction-only commit whose parent is exactly `TARGET_COMMIT`,
   rejecting `TARGET_COMMIT == HEAD`, multiple commits, and merge commits
   between them.
2. **Safety-critical Git command errors failed open.** Several helpers
   returned an empty/`False` default on a failed subprocess call, read by
   callers as "no unexpected paths" / "no commits" / "no merges" /
   "clean". All now return `None` on any command failure, and every
   caller treats `None` as an explicit verification failure.
3. **Commit-message attribution accepted the trailer text anywhere in
   body prose.** Replaced with `git interpret-trailers`-based parsing,
   requiring exactly one parsed terminal trailer with the exact key and
   value.
4. **Launch failures and diagnostics were not fully safe.** The except
   clause is now broadened to catch any ordinary exception and persist
   `FAILED` in the same `tick()` call, unconditionally (including under
   `--once`, since `tick()` itself now guarantees this, not an outer
   wrapper). Raw Claude subprocess stdout/stderr is no longer logged at
   all; only whitelisted metadata is logged, and every log detail is
   sanitized against control characters/newlines.
5. **Timestamp validation was shape-only.** Replaced with a real
   `datetime.strptime` parse with an exact-round-trip requirement,
   applied to both instruction `ISSUED_AT` and (newly) handoff
   `UTC_TIMESTAMP`.
6. **Evidence linkage was too weak.** The bundle must now contain the
   checkpoint's exact bytes verbatim; checkpoint `STATUS`/`GIT_COMMIT`
   must each occur exactly once and `GIT_COMMIT` must be a full SHA;
   handoff `CURRENT_PHASE` must match the instruction's
   `AUTHORIZED_PHASE` exactly; handoff `WORKING_TREE` must state `clean`;
   every required section heading must be present.

Full per-defect detail: `orchestration/checkpoints/watcher_remediation_3.md`
and `docs/DECISION_LOG.md` (entry "Watcher remediation round 3: close the
self-authorization bypass and fail-open Git-error gaps
(argus-watcher-remediation-003)"). `orchestration/PROTOCOL.md` (sections 4,
5, 7) and `docs/OPERATIONS.md` (including a new "Terminal trust-breach
quarantine" recovery procedure) were updated accordingly. Test suite grew
from 51 to 74 tests, covering all 26 mandatory adversarial categories.

## Important findings

- Defect 1 (self-authored instruction bypass) was independently re-derived
  by tracing round 2's actual `tick()` flow, not accepted only on the
  orchestrator's account: the "already attempted" duplicate-instruction
  guard only ever applies to a *previously seen* `INSTRUCTION_ID`, so a
  freshly-appearing self-authored id was never blocked by it — confirming
  the bypass was real before writing the fix.
- `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is unchanged — still the
  orchestrator's `argus-watcher-remediation-003` instruction, `STATUS:
  ACTIVE`. This task did not authorize, and could not have authorized,
  any ARGUS phase.
- `PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK` is unchanged
  and unrelated — still open, see `docs/BUILD_STATE.md`.

## Failures or limitations

- **Known, honestly-stated limitation, narrowed from round 2 but not
  eliminated**: this protocol is file-trust-based, not cryptographically
  signed. The `QUARANTINED` mechanism now reliably prevents a
  self-authored instruction from ever being evaluated again once the
  originating run's instructions-file tampering is detected (in the same
  tick, checked first). What remains inherently unprovable without
  signing is *who* authored any given commit the watcher does accept as
  legitimate — a real human orchestrator's commit and a hypothetical
  adversarial one that never touches the instructions file and carries a
  correctly-formed trailer are indistinguishable to this protocol by
  design. Closing that fully would require cryptographic signing outside
  this protocol's current design, explicitly out of scope for this
  instruction.
- The watcher's real (non-mocked) Claude CLI launch path remains untested
  against an actual `claude` process in this sandbox — unchanged
  limitation from every prior round.
- `validate_checkpoint_content()`/`validate_bundle_content()` remain
  deliberately simple substring/marker-based structural checks, not a
  full document grammar.

## Deferred checks

- `PG17_COMPOSE_VALIDATION` (unchanged, unrelated — see
  `docs/DECISION_LOG.md`).
- First real (non-mocked) watcher-triggered Claude launch should still be
  observed by the operator.
- Full cryptographic closure of the remaining file-trust attribution gap
  (see "Failures or limitations" above) — a protocol-design question for
  the orchestrator, out of scope for this instruction.

## Exact next action requested from orchestrator

Review this remediation's evidence
(`orchestration/checkpoints/watcher_remediation_3.md` and
`orchestration/bundles/watcher_remediation_3.txt`) against the 6 defect
categories and 22 mandatory adversarial test categories (26 test
functions) in instruction `argus-watcher-remediation-003`. If accepted,
write the next `ACTIVE` instruction into
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md` (`TARGET_COMMIT` pinned to
the exact commit named in the final handoff message for this task) to
authorize the next piece of ARGUS or operational-tooling work. Until that
instruction exists, the watcher (if running) takes no action beyond
logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** unchanged from prior handoffs — if you
cloned/fetched this branch before 2026-08-30T22:35 UTC, re-clone or
`git fetch --all && git reset --hard origin/claude/argus-folder-setup-77ahrk`
rather than merging/rebasing the old (pre-rewrite) history.
