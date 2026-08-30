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
machine-readable fields near the top of the file:

```
INSTRUCTION_ID:
ISSUED_AT:
TARGET_COMMIT:
AUTHORIZED_ACTION:
AUTHORIZED_PHASE:
STATUS:
```

Allowed `STATUS` values:

- `NO_INSTRUCTION` — no instruction has been issued yet; nothing is authorized.
- `ACTIVE` — this instruction is currently in force.
- `SUPERSEDED` — a later instruction has replaced this one.

The implementation agent creates the file with the initial placeholder
(see `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` for the exact current
content) and **must not change this file after creating that placeholder**.
Only the orchestrator writes to it from that point forward.

## 5. Agent handoff contract (`AGENT_HANDOFF.md`)

`orchestration/AGENT_HANDOFF.md` must include these fields near the top:

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

## 8. End-of-work rule

Whenever authorized work is finished:

1. Run required tests.
2. Generate the normal ARGUS checkpoint (per MASTER_SPEC.md section 104).
3. Generate the normal review bundle (per MASTER_SPEC.md section 105,
   written to `runtime/reports/` as always).
4. Copy the committed versions into `orchestration/checkpoints/` and
   `orchestration/bundles/` under a phase-specific filename (never
   overwriting an already-committed historical entry).
5. Update `orchestration/AGENT_HANDOFF.md`.
6. Update `docs/BUILD_STATE.md`.
7. Commit.
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
