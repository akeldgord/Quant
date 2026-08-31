# ARGUS Build State

Machine-and-human-readable state for session recovery (MASTER_SPEC.md section 8).
Every new implementation session must read this file before doing anything else.

```yaml
current_phase: 1  # remediation round 3 complete per this session; NOT yet orchestrator-approved
last_completed_phase: 1  # implementation-agent-reported complete (remediation round 3); awaiting orchestrator review
last_orchestrator_approved_phase: 0  # unchanged -- only the orchestrator may advance this
approved_commit: 141af487fcfdff41d1597c19ea062139f5427f52  # unchanged -- Phase 0's approved commit
awaiting_orchestrator_review: true  # Phase 1 remediation round 3 complete; see orchestration/checkpoints/phase_1_remediation_3.md

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
  - "REALCHAIN_GOLDEN_FIXTURES = PARTIAL_7_OF_9_CATEGORIES. Orchestrator
     instruction argus-phase-1-remediation-002 (finding #12) required
     authentic captured real-chain golden transaction fixtures, sourced
     via this sandbox's read-only GitHub access (general RPC/market-data
     egress remains confirmed blocked -- re-verified directly via
     `argus providers probe`, distinct from the GitHub git-clone path
     which does work). Round 2 imported 4 real fixtures from
     solana-labs/explorer (MIT), covering the 'simple transfer' required
     category from both perspectives plus two additional real data
     points. Round 3 (argus-phase-1-remediation-003, finding #1) searched
     DEX/AMM program repositories (Raydium, Orca/Whirlpools, Phoenix,
     OpenBook, Meteora) and several general-purpose Solana
     transaction-parser repositories, and imported 6 more real fixtures
     from 0xjeffro/tx-parser (MPL-2.0), covering SOL-to-token swap,
     token-to-SOL swap, token-to-USDC swap, multi-hop swap, partial sell,
     and an ambiguous multi-asset transaction -- 7 of 9 round-1-required
     categories now genuinely real-chain evidenced. The remaining 2
     ('multiple token-account / LP-style action', and a genuinely failed
     on-chain transaction) remain honestly NOT TESTED -- no repository
     checked across either round embeds either; see
     tests/golden/fixtures/real/SEARCH_LOG.md for the full search log
     (across both rounds) and
     orchestration/checkpoints/phase_1_remediation_3.md section E item 1
     for the disposition. Closing this out fully requires either an
     environment with real RPC egress to capture one directly, or a
     not-yet-checked repository that happens to embed either."
```

## Phase history

| Phase | Status | Commit | Notes |
|-------|--------|--------|-------|
| 0 | ORCHESTRATOR-APPROVED (`argus-phase-1-001`, 2026-08-31) | b838558f7eae1eac8d3559c7826ab340d604d916, remediated at ca74d09b3f976a5726fe46c1a8ea59d7bbdd3ad7 (history rewritten 2026-08-30 to scrub inert dev-only placeholder credential strings — see docs/DECISION_LOG.md; these are the post-rewrite hashes) | Foundation scaffold: repo layout, uv env, Compose+Postgres, Alembic baseline + DB roles, config/spec hashing, clock abstraction, structured logging, CLI skeleton, FastAPI skeleton, health framework, provider_usage schema, checkpoint bundle framework. Remediated per orchestrator feedback: removed all hardcoded fallback DB passwords (migrations/versions/0001_*.py, compose.yaml, src/argus/db/connection.py) in favor of required env vars that fail closed via MissingCredentialError; corrected checkpoint STATUS to not claim an unconditional PASS while PG17-via-Docker-Compose remains untested (see PG17_COMPOSE_VALIDATION above). 41/41 tests pass, 93% coverage, ruff+mypy clean. Approved by the ARGUS ORCHESTRATOR at commit `141af487fcfdff41d1597c19ea062139f5427f52` as `PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`. See runtime/reports/checkpoint_phase_0.txt for the full checkpoint. |
| 1 | BUILD COMPLETE, AWAITING ORCHESTRATOR REVIEW (authorized by `argus-phase-1-001`, target `141af487fcfdff41d1597c19ea062139f5427f52`) | 28a88f74d28e70542050f5d5e8d9a9d139f26bb8 | Live chain data acquisition + deterministic canonical parsing: Helius RPC/WSS adapter, DexScreener/GeckoTerminal/Jupiter adapters (no signing), fast-path+truth-path reconciliation with per-wallet watermarks and DEGRADED gating, durable clock-anomaly detection wired into reconciliation, immutable `chain_events`/`swaps`/`clock_health_events` ledger, generic balance-delta swap parser (11 golden fixtures), P0-P6 priority scheduler, provider usage accounting with 70/85/95% warnings wired into every real adapter call, HTTP retry/backoff, provider capability/history/usage probe CLI. 204 tests passing, 91% coverage, ruff+mypy clean. STATUS `PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`: acceptance criteria 1-2 (live Solana RPC/WebSocket) NOT TESTED -- no `HELIUS_API_KEY` configured and no general internet egress in this sandbox; no end-to-end stream-manager orchestration loop exists yet (each piece is built and tested in isolation). See `orchestration/checkpoints/phase_1.md` for the full 27-item disposition and disclosed gaps. NOT yet orchestrator-approved -- only the orchestrator may advance `last_orchestrator_approved_phase`. **Superseded by the remediation row below** -- an independent orchestrator audit (`argus-phase-1-remediation-001`) rejected this self-assessment as overstated; this row is kept unmodified as immutable history. |
| 1 (remediation round 1) | BUILD COMPLETE, AWAITING ORCHESTRATOR REVIEW (authorized by `argus-phase-1-remediation-001`, target `32c2898ab8c278c2f75f4a2f40fedd9d35b24b08`) | 83bb38497ac3af1402f38dabee6858e00ce2e9fb | Remediated all 10 audit findings from `argus-phase-1-remediation-001`: production `IngestionManager`/`argus ingest run` composing the WebSocket stream, reconciliation, and clock monitor into real runtime behavior; bounded cursor-based truth-path pagination that never silently truncates a gap; an auditable append-only commitment-observation model (replacing the dead `confirmed_at`/`finalized_at` columns) with regression/conflict rejection; parsing wired end-to-end into `swaps` persistence via a real `SqlSwapRecorder`; typed provider-contract validation replacing bare `isinstance(dict)` checks; usage accounting that survives transport exhaustion and is wired into the manager's real streaming code path; a dispatch-count-bounded scheduler starvation guarantee; 6 real `tests/replay` tests (was 0 collected). 260 tests passing, 84% coverage, ruff+mypy clean, alembic downgrade-to-base/upgrade-to-head clean. STATUS `PARTIAL_NOT_TESTED_REALCHAIN_FIXTURES`: 25 of 26 mandatory acceptance criteria PASS; criterion 15 (authenticated real-chain golden fixtures) is honestly NOT TESTED/blocked -- this sandbox has no general internet egress and no already-available safe source of authentic transaction data, per the instruction's own explicit fallback for this exact case. See `orchestration/checkpoints/phase_1_remediation_1.md` for the full 26-item disposition. NOT yet orchestrator-approved -- only the orchestrator may advance `last_orchestrator_approved_phase`. **Superseded by the remediation round 2 row below** -- an independent orchestrator audit (`argus-phase-1-remediation-002`) rejected round 1 as still insufficient; this row is kept unmodified as immutable history. |
| 1 (remediation round 2) | BUILD COMPLETE, AWAITING ORCHESTRATOR REVIEW (authorized by `argus-phase-1-remediation-002`, target `04f367b8e03e99718812f872a34e73e170c44f0d`) | e44b5885b8aa02105e13051af4045e23e17b084c | Remediated all 12 audit findings from `argus-phase-1-remediation-002`: session-per-operation unit-of-work (no `AsyncSession` shared across concurrent tasks); explicit subscription-acknowledgement lifecycle with three independent recovery dimensions (stream/reconciliation/clock) so no single dimension can restore OK alone; structured task supervision (`IngestionManagerFailure`, fail-closed on any child-task death); finalization sweep wired into a real manager background loop; deterministic atomic commitment derivation (monotonic `sequence` column, `pg_advisory_xact_lock` serialization, full-same-level-state conflict validation, `commitment_observation_rejections` audit table); mechanical append-only enforcement at the database role layer; typed canonical provider response models (`argus.providers.models`) replacing provider-shaped dicts; usage records exactly one terminal outcome decided after decode/validation (including a visible signal on recorder failure); durable versioned `parse_attempts` ledger + `argus ingest reparse`; pagination continuity/ordering validation; a cancelled scheduler submission can never execute; and 4 genuine real-chain golden fixtures (of 9 required categories) sourced via this sandbox's working GitHub read access, imported through a new offline `argus fixtures import-real-chain`/`validate-real-chain` tool. 327 tests passing, 85% coverage, ruff+mypy clean, alembic downgrade-to-base/upgrade-to-head clean through migration 0005. STATUS `PARTIAL_REALCHAIN_FIXTURES_4_OF_9_CATEGORIES`: 26 of 27 mandatory acceptance criteria PASS; criterion 21 (real-chain golden fixtures) is honestly PARTIAL -- 4 of 9 required categories now genuinely real-chain evidenced, the remaining 8 (every DEX-swap-shaped category) are NOT TESTED since no repository searched embeds real swap-transaction bytes. See `orchestration/checkpoints/phase_1_remediation_2.md` for the full 27-item disposition and `tests/golden/fixtures/real/SEARCH_LOG.md` for the search log. NOT yet orchestrator-approved -- only the orchestrator may advance `last_orchestrator_approved_phase`. **Superseded by the remediation round 3 row below** -- an independent orchestrator audit (`argus-phase-1-remediation-003`) rejected round 2 as still insufficient; this row is kept unmodified as immutable history. |
| 1 (remediation round 3) | BUILD COMPLETE, AWAITING ORCHESTRATOR REVIEW (authorized by `argus-phase-1-remediation-003`, target `87a0e2efe329512a78f81331da24a85adf62bbbe`) | 81dd46cbfa3a46dd97c2f59a92ec62a42ab4fda9 | Remediated all 6 audit findings from `argus-phase-1-remediation-003`: evidence-bearing pagination boundary verification (a persisted boundary must be directly observed in the provider's own address-history sequence, never inferred from an empty/short page alone); every Helius RPC method's full nested contract validation now runs inside its single accounted usage operation (no malformed result can leave an "ok" usage row); streaming usage-recorder failures emit a visible `usage_recorder_failed` structured warning instead of disappearing via `contextlib.suppress`; `parse_attempts` durably records build/config/MASTER_SPEC/git identity (4 new NOT NULL CHECK-constrained columns, migration 0006, backed by a new `argus.config.git_commit_sha()` and `argus.parsing.generic_parser.PARSER_BUILD_HASH`); `sweep_finalization()` returns a typed `FinalizationSweepResult` distinguishing a genuine zero-promotion sweep from a provider/malformed-response/per-event-append failure, surfaced by the manager's own background loop; and 6 more genuine real-chain golden fixtures (of 9 required categories, now 7/9 total) sourced from `0xjeffro/tx-parser` (MPL-2.0). New `tests/integration/test_migrations.py` (6 tests) independently re-proves migration-from-zero/upgrade-from-0003/upgrade-from-0005/downgrade/idempotency/restart-safety against a disposable scratch database. 371 tests passing, 86% coverage, ruff+mypy clean, alembic downgrade-to-base/upgrade-to-head clean through migration 0006. STATUS `PARTIAL_REALCHAIN_FIXTURES_7_OF_9_CATEGORIES`: 17 of 18 mandatory acceptance criteria PASS; criterion 1 (real-chain golden fixtures) is honestly PARTIAL -- 7 of 9 required categories now genuinely real-chain evidenced, the remaining 2 ('multiple token-account/LP-style action', a genuinely failed transaction) are NOT TESTED since no repository searched (across either round) embeds either. See `orchestration/checkpoints/phase_1_remediation_3.md` for the full 18-item disposition and `tests/golden/fixtures/real/SEARCH_LOG.md` for the search log. NOT yet orchestrator-approved -- only the orchestrator may advance `last_orchestrator_approved_phase`. |

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
