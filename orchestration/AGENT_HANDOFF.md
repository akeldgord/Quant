# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0003-watcher-setup
UTC_TIMESTAMP: 2026-08-30T23:09:24Z
CURRENT_COMMIT: 9df37f9e8e77bf538dcb99c08d16fa96827229b7
CURRENT_PHASE: 0
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: none (no instruction has been issued through GitHub yet — see orchestration/ORCHESTRATOR_INSTRUCTIONS.md, STATUS: NO_INSTRUCTION; this handoff is for operational tooling work the human operator authorized directly, not an ORCHESTRATOR_INSTRUCTIONS.md-authorized task)
CHECKPOINT_PATH: orchestration/checkpoints/watcher_setup.md
BUNDLE_PATH: orchestration/bundles/watcher_setup.txt
TEST_STATUS: 57/57 passed (41 pre-existing + 16 new), 93% src/argus coverage (unchanged), ruff clean, mypy clean
WORKING_TREE: clean (verified via `git status --porcelain` before and after this commit)
ORCHESTRATOR_REVIEW_REQUIRED: none from this task; PG17_COMPOSE_VALIDATION (deferred, unrelated to this task) still open — see docs/BUILD_STATE.md

## Work completed

1. **Phase 0 (Foundation)** built, tested, and remediated (hardcoded DB
   password fallbacks removed; git history scrubbed of the inert dev-only
   placeholder strings before the repository was made public). See
   `orchestration/checkpoints/phase_0_remediation.md`.
2. **Orchestration protocol bootstrap**: `orchestration/PROTOCOL.md`,
   `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` (orchestrator-owned
   placeholder, `STATUS: NO_INSTRUCTION` — still untouched), this file, and
   `checkpoints/` / `bundles/`.
3. **This handoff — local "no-nudge" orchestrator watcher**
   (`scripts/argus_orchestrator_watch.py` + `make orchestrator-watch` +
   `docs/OPERATIONS.md`), built per explicit human-operator instruction so
   they no longer need to manually start Claude for each ARGUS phase. Full
   build/test record in `orchestration/checkpoints/watcher_setup.md`.
   Summary: polls this repo, verifies TARGET_COMMIT safety, launches the
   Claude CLI non-interactively only on a new `ACTIVE` instruction,
   verifies the resulting handoff and push before marking a run
   `COMPLETED`, never auto-retries a failed or crashed run. 16 new tests
   cover every required scenario; the Claude CLI is fully mocked in all of
   them (no Claude-model tokens spent by the test suite).

## Important findings

- The watcher was **not** used to authorize or perform any ARGUS phase
  work — `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is still
  `STATUS: NO_INSTRUCTION`, exactly as it was before this task, per the
  human operator's explicit instruction not to begin Phase 1 or wait for an
  orchestrator instruction in this session.
- The watcher's Claude CLI invocation (`claude -p <prompt>`, extensible via
  `--claude-arg`) has not been end-to-end exercised against a real `claude`
  process in this sandbox — every test and the one real `--once` run here
  either mock it or never reach the launch step (because
  `ORCHESTRATOR_INSTRUCTIONS.md` had no `ACTIVE` instruction to act on).
  The operator should watch the first real run closely.
- `PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK` is unchanged and
  unrelated to this task — still open, see `docs/BUILD_STATE.md`.

## Failures or limitations

- None new. The standing `docker compose up -d postgres` limitation (Docker
  Hub CDN blocked in this sandbox) is unchanged and unrelated to this task.

## Deferred checks

- `PG17_COMPOSE_VALIDATION` (unchanged, unrelated to this task — see prior
  handoffs and `docs/DECISION_LOG.md`).
- First real (non-mocked) watcher-triggered Claude launch should be
  observed by the operator to confirm the CLI invocation is correct for
  their installed Claude CLI version.

## Exact next action requested from orchestrator

None from the orchestrator for this task specifically — it was authorized
and scoped directly by the human operator, not by an
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md` entry. The orchestrator's
outstanding action from the prior handoff still applies: review
`orchestration/checkpoints/phase_0_remediation.md` and write an instruction
into `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` (`STATUS: ACTIVE`,
`TARGET_COMMIT` pinned to current HEAD) to authorize the next piece of
ARGUS work. Once that instruction exists, the watcher (if the operator has
started it) will pick it up automatically — no further manual Claude
session start should be necessary.

**Note on this branch's history:** unchanged from the prior handoff — if
you cloned/fetched this branch before 2026-08-30T22:35 UTC, re-clone or
`git fetch --all && git reset --hard origin/claude/argus-folder-setup-77ahrk`
rather than merging/rebasing the old history.
