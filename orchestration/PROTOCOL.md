# ARGUS Orchestration Handoff Protocol

Shared protocol for how the IMPLEMENTATION AGENT and the ARGUS ORCHESTRATOR
communicate through this GitHub repository instead of requiring the human
operator to manually copy/paste large checkpoints and instructions between
them. The human operator remains in control at every step; this protocol
only removes the manual transport step.

This file may be created by the implementation agent. **After creation,
future material changes to this file require orchestrator approval** —
record any such change in `docs/DECISION_LOG.md` per MASTER_SPEC.md
section 109, the same as any other orchestrator-approved change.

This protocol is additive to MASTER_SPEC.md. It does not change ARGUS's
architecture, phases, or acceptance criteria — it only changes how phase
checkpoints and instructions are exchanged. Where anything here conflicts
with MASTER_SPEC.md, MASTER_SPEC.md governs.

---

## 1. Directory layout

```
orchestration/
├── PROTOCOL.md                   this file
├── AGENT_HANDOFF.md               implementation-agent-owned status file
├── ORCHESTRATOR_INSTRUCTIONS.md   orchestrator-owned instruction file
├── checkpoints/                   immutable per-phase checkpoint copies
└── bundles/                       immutable per-phase review-bundle copies
```

This directory is **tracked in Git** (unlike `runtime/`, which is
intentionally gitignored per MASTER_SPEC.md section 7/97) precisely because
its purpose is to be visible to the orchestrator through GitHub.

## 2. File ownership rules

| File / directory | Owner | Notes |
|---|---|---|
| `orchestration/PROTOCOL.md` | Implementation agent (creation); orchestrator (material changes thereafter) | This file. |
| `orchestration/AGENT_HANDOFF.md` | **Implementation agent** | Updated every time work is handed back to the orchestrator. The orchestrator treats it as the agent's current status message — an index, not a replacement for the full checkpoint. |
| `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` | **ARGUS ORCHESTRATOR** | The implementation agent creates only the initial placeholder (see `#4`) and **must not modify this file again**. The orchestrator writes instructions here through GitHub. |
| `orchestration/checkpoints/` | Implementation agent (write) | Immutable phase checkpoint copies, e.g. `phase_0_remediation.md`, `phase_1.md`. **Never overwrite an approved historical checkpoint** — add a new file instead. |
| `orchestration/bundles/` | Implementation agent (write) | The orchestrator review bundle associated with each checkpoint, e.g. `phase_0_remediation.txt`, `phase_1.txt`. Same immutability rule as checkpoints. |

## 3. Workflow

```
IMPLEMENTATION AGENT
        |
        | completes authorized work
        v
runs tests/checkpoint
        |
        v
commits + pushes code
        |
        v
writes checkpoint + review bundle
        |
        v
updates AGENT_HANDOFF.md
        |
        v
commits + pushes handoff
        |
        v
STOPS
        |
        |
ARGUS ORCHESTRATOR reads GitHub
        |
        v
audits implementation
        |
        v
writes ORCHESTRATOR_INSTRUCTIONS.md
        |
        v
commits instruction through GitHub
        |
        |
IMPLEMENTATION AGENT next session
        |
        v
git pull
        |
        v
reads ORCHESTRATOR_INSTRUCTIONS.md
        |
        v
executes only authorized work
```

The human operator remains in control (they still decide when a new
coding-agent session starts, and they still control credentials, capital,
and live arming per MASTER_SPEC.md section 1) but no longer needs to
transport large text blocks manually between the orchestrator and the
implementation agent.

## 4. Instruction-state contract (`ORCHESTRATOR_INSTRUCTIONS.md`)

`orchestration/ORCHESTRATOR_INSTRUCTIONS.md` must carry these
machine-readable fields near the top of the file, each present **exactly
once**:

```
INSTRUCTION_ID:
ISSUED_AT:
TARGET_COMMIT:
AUTHORIZED_ACTION:
AUTHORIZED_PHASE:
APPROVES_PHASE:
STATUS:
```

Allowed `STATUS` values:

- `NO_INSTRUCTION` — no instruction has been issued yet; nothing is authorized.
- `ACTIVE` — this instruction is currently in force.
- `SUPERSEDED` — a later instruction has replaced this one.

For an `ACTIVE` instruction, the watcher additionally requires: a duplicate
of any field is rejected outright; `ISSUED_AT` a **real, canonical UTC
timestamp** — parsed with an actual UTC datetime parser and required to
round-trip exactly to `YYYY-MM-DDTHH:MM:SSZ`, not merely shape-matched by a
regular expression (a regex alone would accept impossible values like month
`99` or day `30` in February); `TARGET_COMMIT` a full 40-character commit
SHA; `AUTHORIZED_ACTION` non-empty and not the literal `NONE`;
`AUTHORIZED_PHASE` a recognized entry in the canonical phase sequence
(`#7`); `APPROVES_PHASE` either the literal `NONE` or a recognized phase
entry.

The implementation agent creates the file with the initial placeholder
(see `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` for the exact current
content) and **must not change this file after creating that placeholder**.
Only the orchestrator writes to it from that point forward. This is
mechanically enforced, not just convention: the watcher records the blob
hash of this file's on-disk content immediately before launching Claude and
compares it again once Claude exits (via `git hash-object`, which reflects
an uncommitted edit too, not only a committed one). Any difference — even
one later committed and pushed by the implementation agent itself — is a
**terminal trust breach**, checked first and unconditionally, ahead of every
other verification: it moves the watcher into a permanent `QUARANTINED`
state (see `#7`), not an ordinary retryable `FAILED`.

## 5. Agent handoff contract (`AGENT_HANDOFF.md`)

`orchestration/AGENT_HANDOFF.md` must include these fields near the top,
each present **exactly once, non-empty**:

```
HANDOFF_ID:
UTC_TIMESTAMP:
CURRENT_COMMIT:
CURRENT_PHASE:
WORK_STATUS:
LAST_ORCHESTRATOR_INSTRUCTION_ID:
CHECKPOINT_PATH:
BUNDLE_PATH:
TEST_STATUS:
WORKING_TREE:
ORCHESTRATOR_REVIEW_REQUIRED:
```

followed by these concise sections:

```
## Work completed
## Important findings
## Failures or limitations
## Deferred checks
## Exact next action requested from orchestrator
```

This is an index/status file, not a replacement for the full checkpoint —
the full checkpoint lives in `orchestration/checkpoints/` (and, per the
existing MASTER_SPEC.md contract, in `runtime/reports/`).

**Contract enforced mechanically by `scripts/argus_orchestrator_watch.py`**
(not just convention — a run violating any of the following is marked
`FAILED`, not `COMPLETED`):

- Every field above must appear exactly once and non-empty. A duplicate or
  missing field fails the run. Every required section heading above must
  also literally appear in the file.
- `LAST_ORCHESTRATOR_INSTRUCTION_ID` must be **exactly** the instruction's
  `INSTRUCTION_ID` — no other text appended or reworded.
- `HANDOFF_ID` must differ from the value recorded immediately before this
  run started — a reused id fails the run.
- `UTC_TIMESTAMP` must be a real, canonical UTC timestamp (same rule as
  `ISSUED_AT` in `#4` — a real datetime parse with an exact round-trip, not
  a shape-only regex).
- `CURRENT_PHASE` must be a recognized entry in the canonical phase sequence
  (`#7`) and must **match this instruction's `AUTHORIZED_PHASE` exactly** —
  a handoff claiming a different phase than what was actually authorized
  fails the run.
- `WORKING_TREE` must state `clean`; the watcher additionally, and
  independently, confirms this mechanically via its own `git status`
  check — the field is not trusted on its own.
- `CURRENT_COMMIT`, and the `GIT_COMMIT` field inside the checkpoint file
  itself, must each resolve to a real commit created during this run (an
  implementation commit or a later documentation-only hash-fill commit in
  the same run is fine; anything that predates the run, or doesn't resolve
  at all, is not).
- `CHECKPOINT_PATH` and `BUNDLE_PATH` must be normalized, repository-relative
  paths inside `orchestration/checkpoints/` and `orchestration/bundles/`
  respectively, with the correct extension (`.md` / `.txt`); an absolute
  path, a `..` traversal segment, a symlink, or the wrong directory/extension
  fails the run.
- Both evidence paths must be **newly added** by this run's own commits —
  present at all at the pre-launch `HEAD`, or merely modified rather than
  added, fails the run as stale evidence. An existing checkpoint or bundle
  must never be overwritten.
- The checkpoint file must be nonempty, start and end with the standard
  ARGUS checkpoint markers, and identify PROJECT ARGUS, the authorized
  phase or operational scope, commands actually run, test results,
  acceptance criteria, deviations, known debt, and security state, plus a
  next-action/STOP statement. `STATUS` and `GIT_COMMIT` must each occur
  **exactly once** (a duplicate/contradictory value fails the run), and
  `GIT_COMMIT` must be a full 40-character commit SHA.
- The bundle file must be nonempty and must contain the checkpoint's
  **exact bytes verbatim** — not a paraphrase, and not a different,
  independently-valid checkpoint — plus the required review evidence. A
  one-line placeholder, or a bundle embedding a checkpoint that doesn't
  exactly match `CHECKPOINT_PATH`'s actual content, fails the run.

## 6. Session-start rule

Every future implementation-agent session **must** begin with:

```
git status
git pull --ff-only
git log -5 --oneline
```

and then read, **in this order**:

1. `MASTER_SPEC.md`
2. `docs/BUILD_STATE.md`
3. `docs/DECISION_LOG.md`
4. `orchestration/PROTOCOL.md`
5. `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`
6. `orchestration/AGENT_HANDOFF.md`

The agent must then determine whether an `ACTIVE` instruction exists in
`ORCHESTRATOR_INSTRUCTIONS.md`.

If `STATUS: NO_INSTRUCTION`, or the active instruction does not authorize
the work being considered: **STOP**. Do not infer permission from an older
chat session, from this protocol document itself, or from any other source.
Authorization comes only from an `ACTIVE` instruction in
`ORCHESTRATOR_INSTRUCTIONS.md` (or a direct, explicit instruction from the
human operator in the current session).

## 7. Target-commit protection

If an `ACTIVE` orchestrator instruction specifies `TARGET_COMMIT: <sha>` but
the repository `HEAD` at session start is materially different from that
expected state, the agent must **not** blindly execute the instruction.

Instead, report:

```
ORCHESTRATOR_REVIEW_REQUIRED:
TARGET_COMMIT_MISMATCH
```

and stop — **unless** the mismatch is only the orchestrator's own
instruction-file commit on top of `TARGET_COMMIT` (i.e. `HEAD` =
`TARGET_COMMIT` plus a commit that touches only
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md`), in which case the underlying
implementation commit is clearly still the intended target and work may
proceed. This check must be applied conservatively: when in doubt, treat it
as a mismatch and stop.

**Tightened provenance (round 3).** An `ACTIVE` instruction must be
introduced by **exactly one** instruction-only commit whose parent is
**exactly** `TARGET_COMMIT`. The watcher mechanically rejects:

- `TARGET_COMMIT` equal to the current `HEAD` (an instruction must target
  the commit immediately *preceding* its own instruction-only commit, never
  `HEAD` itself);
- more than one commit between `TARGET_COMMIT` and `HEAD`;
- a merge commit between `TARGET_COMMIT` and `HEAD`;
- any changed path other than the instructions file.

This closes a structural loophole where a run's own final self-authored
commit could otherwise look, on the *next* tick, indistinguishable from a
normal one-commit orchestrator edit. It does **not** by itself authenticate
who authored that one commit — this protocol is file-trust-based, not
cryptographically signed, and an unsigned Git commit cannot prove
authorship. What actually detects and blocks implementation-agent
self-authorship is the instructions-file blob-hash check in `#4` combined
with the `QUARANTINED` state below.

**Terminal trust-breach quarantine.** If the instructions-file blob-hash
check in `#4` fails for a run, the watcher does not mark that run an
ordinary retryable `FAILED`. It persists a distinct `QUARANTINED` state and,
from that point on, **every future tick refuses to evaluate or launch any
instruction at all** — regardless of a new `INSTRUCTION_ID`, a new
`TARGET_COMMIT`, or anything else that later appears in
`ORCHESTRATOR_INSTRUCTIONS.md` — until a human operator runs
`scripts/argus_orchestrator_watch.py --reset-quarantine` after manually
reviewing what happened (see `docs/OPERATIONS.md`). This is what makes "a
self-authored next instruction can launch on a later tick" mechanically
impossible rather than merely discouraged.

**Phase-authorization protection.** ARGUS phases form a canonical ordered
sequence, including the mandatory sub-phase gates, represented as exact
string tokens — never compared as floats/binary values:

```
0, 1, 1.5, 2, 3, 4, 5, 6, 6.5, 7, 8, 9, 10, 11
```

`AUTHORIZED_PHASE` and `APPROVES_PHASE` are never trusted blindly. The
watcher reads `current_phase`, `last_completed_phase`, and
`awaiting_orchestrator_review` from `docs/BUILD_STATE.md` (also as exact
string/boolean tokens) and enforces:

- **Same-phase remediation** (`APPROVES_PHASE: NONE`, as this instruction
  uses): allowed only when `AUTHORIZED_PHASE == current_phase`. This is the
  case for operational/tooling remediation that doesn't advance the phase.
- **Advancing to the immediate successor phase**: requires all of
  `APPROVES_PHASE == current_phase`, `last_completed_phase ==
  current_phase`, `awaiting_orchestrator_review == true`, and
  `AUTHORIZED_PHASE` equal to the *immediate* next entry after
  `current_phase` in the sequence above. No instruction may skip a phase or
  sub-phase — Phase 1.5 cannot be bypassed on the way from 1 to 2, for
  example.
- The implementation agent must never infer approval, or edit
  `last_orchestrator_approved_phase`/`approved_commit`
  in `docs/BUILD_STATE.md`, without a currently-`ACTIVE` orchestrator
  instruction whose `APPROVES_PHASE` says so explicitly.

This is what makes "Phase 1 must not be authorized while Phase 0 is still
awaiting orchestrator review" (or any phase/sub-phase skip) an enforced
property of the watcher itself, not merely something asked of the Claude
prompt.

**Branch-movement and commit-attribution protection.** Passing the checks
above is necessary but not sufficient — the watcher additionally verifies,
after Claude exits and before accepting any evidence:

- Local `HEAD` and `origin/<branch>` `HEAD` are captured and compared
  immediately before launch (not just after).
- Post-run `HEAD` must descend **linearly** from the pre-launch `HEAD`:
  rewritten ancestry, non-fast-forward movement, and any merge commit
  anywhere in the run's commit range are all rejected.
- Every commit in that range must carry exactly one **real, terminal Git
  trailer** (parsed with `git interpret-trailers`, i.e. an actual trailing
  `key: value` paragraph — not merely the same text occurring somewhere in
  ordinary commit-body prose) named `ARGUS-INSTRUCTION-ID` whose value
  exactly equals the ACTIVE instruction's `INSTRUCTION_ID`. A duplicate or
  conflicting trailer, extra text appended to the value, or no trailer at
  all are all rejected. This makes concurrent, unattributed branch movement
  during a run visible and rejected rather than silently accepted because
  local/remote `HEAD` happened to match again by the time the run finished.

**Git-command failures fail closed, never open.** Every safety-critical Git
read the watcher performs (`git status`, `git diff`, `git log`,
`git rev-list`, `git interpret-trailers`, …) is treated as an explicit
verification failure — never as "clean", "no drift", "no merges", or "no
commits to check" — if the underlying command itself fails (nonzero exit,
timeout, or unparseable output). A transient Git error must never be able
to make an unsafe condition look safe.

## 8. End-of-work rule

Whenever authorized work is finished:

1. Run required tests.
2. Generate the normal ARGUS checkpoint (per MASTER_SPEC.md section 104).
3. Generate the normal review bundle (per MASTER_SPEC.md section 105,
   written to `runtime/reports/` as always).
4. Copy the committed versions into `orchestration/checkpoints/` and
   `orchestration/bundles/` under a phase-specific filename, as **newly
   added** files (never overwriting or merely editing an already-committed
   historical entry).
5. Update `orchestration/AGENT_HANDOFF.md`.
6. Update `docs/BUILD_STATE.md`.
7. Commit. When running under the local watcher
   (`scripts/argus_orchestrator_watch.py`), every commit made during the run
   — including any documentation/hash-fill commit — must carry exactly one
   real, terminal Git trailer `ARGUS-INSTRUCTION-ID: <INSTRUCTION_ID>` (a
   trailing `key: value` paragraph, not merely that text appearing in
   ordinary body prose), or the watcher rejects the entire run regardless of
   anything else it produced.
8. Push.
9. Verify a clean working tree (`git status --porcelain` empty).
10. **STOP.**

Do not wait or poll for the orchestrator. Do not begin another phase. The
human/orchestrator starts the next implementation-agent session once new
instructions appear in `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`.

## 9. Relationship to the existing `runtime/reports/` contract

`runtime/reports/...` (MASTER_SPEC.md sections 105/106) remains the
canonical, always-generated local report location and is unaffected by this
protocol — it stays gitignored, generated fresh by
`argus checkpoint bundle --phase <N>` every time. The tracked
`orchestration/checkpoints/` and `orchestration/bundles/` copies exist
**only** to make specific, phase-gate versions of those same artifacts
available to the external orchestrator through GitHub. Do not change the
existing `runtime/reports/` contract to accommodate this protocol.

## 10. Secret safety

Before committing any checkpoint or bundle into `orchestration/`, verify it
does **not** contain: API keys, passwords, private keys, seed phrases,
environment dumps, authentication headers, or live-arm contents containing
sensitive material. Run the existing secret scan (the same grep-based scan
used for every other commit in this repository) before committing. If a
review bundle cannot safely be committed as-is, sanitize only the secret
value while preserving the useful evidence (e.g. replace a credential value
with `[REDACTED]`, never delete the surrounding diagnostic context).
