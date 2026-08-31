# ARGUS Build State

Machine-and-human-readable state for session recovery (MASTER_SPEC.md section 8).
Every new implementation session must read this file before doing anything else.

```yaml
current_phase: 1  # build work complete per this session; NOT yet orchestrator-approved
last_completed_phase: 1  # implementation-agent-reported complete; awaiting orchestrator review
last_orchestrator_approved_phase: 0  # unchanged -- only the orchestrator may advance this
approved_commit: 141af487fcfdff41d1597c19ea062139f5427f52  # unchanged -- Phase 0's approved commit
awaiting_orchestrator_review: true  # Phase 1 build work complete; see orchestration/checkpoints/phase_1.md

# PG17_COMPOSE_VALIDATION tracks whether `docker compose up postgres`
# (the actual postgres:17 image, per TECH-004 and compose.yaml) has been
# exercised end-to-end. It is DEFERRED, not PASS and not FAIL: functional
# correctness of the migration/application code was verified against a
# substitute PostgreSQL 16 server instead (see known_blockers below and
# docs/DECISION_LOG.md). Per explicit orchestrator instruction (2026-08-30):
# this deferral does NOT block starting Phase 1, but DOES block approving
# live readiness until it is closed out with a real postgres:17 run.
PG17_COMPOSE_VALIDATION: DEFERRED_ENVIRONMENTAL_CHECK

known_blockers:
  - "PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK. This
     implementation sandbox's egress policy blocks Docker Hub's image CDN
     (production.cloudfront.docker.com -> 403 at the proxy), so
     `docker compose up postgres` (the actual postgres:17 image) could not
     be pulled or exercised here. compose.yaml is unmodified and still
     targets postgres:17 as required by TECH-004 -- this is an environment
     limitation of this sandbox, not an architecture change. As a substitute,
     Phase 0 functional acceptance (migration-from-zero, DB roles,
     provider_usage grants, argus health, full pytest suite, missing-credential
     fail-closed behavior) was verified against the sandbox's
     locally-installed PostgreSQL 16 server, running the exact same Alembic
     migration and application code Compose would run against PostgreSQL 17.
     This PG16 run demonstrates the migration/application logic is correct;
     it does NOT demonstrate anything PostgreSQL-17-version-specific and
     must not be cited as PostgreSQL 17 validation. Closing this out requires
     running `make bootstrap && make up` (or equivalent) on a host with
     normal Docker Hub access and recording the result here and in
     docs/DECISION_LOG.md. See docs/DECISION_LOG.md for the full decision
     record. Per explicit orchestrator instruction, this deferred check does
     NOT block Phase 1, but IS required before live readiness can be
     approved."
```

## Phase history

| Phase | Status | Commit | Notes |
|-------|--------|--------|-------|
| 0 | ORCHESTRATOR-APPROVED (`argus-phase-1-001`, 2026-08-31) | b838558f7eae1eac8d3559c7826ab340d604d916, remediated at ca74d09b3f976a5726fe46c1a8ea59d7bbdd3ad7 (history rewritten 2026-08-30 to scrub inert dev-only placeholder credential strings — see docs/DECISION_LOG.md; these are the post-rewrite hashes) | Foundation scaffold: repo layout, uv env, Compose+Postgres, Alembic baseline + DB roles, config/spec hashing, clock abstraction, structured logging, CLI skeleton, FastAPI skeleton, health framework, provider_usage schema, checkpoint bundle framework. Remediated per orchestrator feedback: removed all hardcoded fallback DB passwords (migrations/versions/0001_*.py, compose.yaml, src/argus/db/connection.py) in favor of required env vars that fail closed via MissingCredentialError; corrected checkpoint STATUS to not claim an unconditional PASS while PG17-via-Docker-Compose remains untested (see PG17_COMPOSE_VALIDATION above). 41/41 tests pass, 93% coverage, ruff+mypy clean. Approved by the ARGUS ORCHESTRATOR at commit `141af487fcfdff41d1597c19ea062139f5427f52` as `PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`. See runtime/reports/checkpoint_phase_0.txt for the full checkpoint. |
| 1 | BUILD COMPLETE, AWAITING ORCHESTRATOR REVIEW (authorized by `argus-phase-1-001`, target `141af487fcfdff41d1597c19ea062139f5427f52`) | 28a88f74d28e70542050f5d5e8d9a9d139f26bb8 | Live chain data acquisition + deterministic canonical parsing: Helius RPC/WSS adapter, DexScreener/GeckoTerminal/Jupiter adapters (no signing), fast-path+truth-path reconciliation with per-wallet watermarks and DEGRADED gating, durable clock-anomaly detection wired into reconciliation, immutable `chain_events`/`swaps`/`clock_health_events` ledger, generic balance-delta swap parser (11 golden fixtures), P0-P6 priority scheduler, provider usage accounting with 70/85/95% warnings wired into every real adapter call, HTTP retry/backoff, provider capability/history/usage probe CLI. 204 tests passing, 91% coverage, ruff+mypy clean. STATUS `PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`: acceptance criteria 1-2 (live Solana RPC/WebSocket) NOT TESTED -- no `HELIUS_API_KEY` configured and no general internet egress in this sandbox; no end-to-end stream-manager orchestration loop exists yet (each piece is built and tested in isolation). See `orchestration/checkpoints/phase_1.md` for the full 27-item disposition and disclosed gaps. NOT yet orchestrator-approved -- only the orchestrator may advance `last_orchestrator_approved_phase`. |

## Operational tooling

- `scripts/argus_orchestrator_watch.py` (`make orchestrator-watch`) — local
  "no-nudge" watcher: polls `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` for
  a new `ACTIVE` instruction and, when one appears and passes the
  TARGET_COMMIT and phase-authorization checks, launches the local Claude
  CLI non-interactively to execute exactly that instruction under
  `orchestration/PROTOCOL.md`. Not running by default — the human operator
  starts it explicitly. See `docs/OPERATIONS.md` for usage.
  Evidence history:
  - `orchestration/checkpoints/watcher_setup.md` — original build/test record.
  - `orchestration/checkpoints/watcher_remediation.md` — a four-defect
    remediation pass (AUTHORIZED_PHASE was never validated; handoff
    instruction-id matching used substring containment instead of exact
    equality; checkpoint/bundle evidence was only checked for existence;
    a crash between CLAIMED and RUNNING was never recovered on restart).
  - `orchestration/checkpoints/watcher_remediation_2.md` — a second,
    orchestrator-requested remediation pass (instruction
    `argus-watcher-remediation-002`), rejecting the first pass as
    insufficient and requiring: strict fail-closed state handling
    (including a handoff-cross-check on state loss); a failed Claude
    process now always fails the run before any evidence is considered;
    evidence must be newly added, immutable, and structurally valid (not a
    placeholder); branch-movement/merge-commit/commit-attribution
    (`ARGUS-INSTRUCTION-ID:` trailer) verification; a blob-hash check that
    mechanically prevents the implementation agent from modifying
    `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` during a run; explicit
    string-sequence phase gating (`0, 1, 1.5, 2, ..., 6, 6.5, ..., 11`) via
    a new `APPROVES_PHASE` field; strict instruction-field parsing; and a
    conservative, ordered post-run verification sequence. 26 new/updated
    adversarial regression tests.
  - `orchestration/checkpoints/watcher_remediation_3.md` — a third,
    orchestrator-requested remediation pass (instruction
    `argus-watcher-remediation-003`), rejecting round 2 as still fail-open
    in several places and requiring: a terminal, non-retryable
    `QUARANTINED` state (with a manual `--reset-quarantine` recovery
    procedure) the moment the instructions file is found modified —
    checked first and unconditionally, closing a bypass where a
    self-authored next instruction could otherwise launch on a later tick;
    tightened `TARGET_COMMIT` provenance (exactly one instruction-only
    commit whose parent is exactly the target; no `TARGET_COMMIT == HEAD`;
    no multi-commit or merge gaps); every safety-critical Git read now
    fails closed (`None`/explicit-failure) rather than defaulting to
    empty/clean/absent on a command error; commit attribution via a real
    `git interpret-trailers`-parsed terminal trailer, not text anywhere in
    body prose; broadened launch-exception handling that never leaves a
    stale `RUNNING` state, with raw Claude subprocess output never logged
    at all (only whitelisted metadata); real canonical-UTC timestamp
    parsing (not shape-only regex) for both instructions and handoffs; and
    tightened evidence linkage (exact checkpoint-bytes embedding in the
    bundle, exactly-once/full-SHA checkpoint identity fields, handoff
    `CURRENT_PHASE` matching `AUTHORIZED_PHASE`, required section
    headings). 74 total watcher tests (up from 51). This is operational
    tooling, not ARGUS phase work — `current_phase` above is unaffected.

## Rules

- This file may be updated by the implementation agent to reflect actual build
  progress.
- `last_orchestrator_approved_phase` and `approved_commit` may ONLY be set to a
  new value after receiving **explicit** orchestrator approval for that phase.
  The implementation agent must never self-approve a phase here.
- Do not begin work on `current_phase + 1` while `awaiting_orchestrator_review`
  is `true` for the current phase.
