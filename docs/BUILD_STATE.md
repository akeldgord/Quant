# ARGUS Build State

Machine-and-human-readable state for session recovery (MASTER_SPEC.md section 8).
Every new implementation session must read this file before doing anything else.

```yaml
current_phase: 0
last_completed_phase: 0  # implementation-agent build+test+acceptance complete; NOT orchestrator-approved
last_orchestrator_approved_phase: null
approved_commit: null
awaiting_orchestrator_review: true

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
| 0 | BUILT — remediated, awaiting orchestrator review | b838558f7eae1eac8d3559c7826ab340d604d916, remediated at ca74d09b3f976a5726fe46c1a8ea59d7bbdd3ad7 (history rewritten 2026-08-30 to scrub inert dev-only placeholder credential strings — see docs/DECISION_LOG.md; these are the post-rewrite hashes) | Foundation scaffold: repo layout, uv env, Compose+Postgres, Alembic baseline + DB roles, config/spec hashing, clock abstraction, structured logging, CLI skeleton, FastAPI skeleton, health framework, provider_usage schema, checkpoint bundle framework. Remediated per orchestrator feedback: removed all hardcoded fallback DB passwords (migrations/versions/0001_*.py, compose.yaml, src/argus/db/connection.py) in favor of required env vars that fail closed via MissingCredentialError; corrected checkpoint STATUS to not claim an unconditional PASS while PG17-via-Docker-Compose remains untested (see PG17_COMPOSE_VALIDATION above). 41/41 tests pass, 93% coverage, ruff+mypy clean. See runtime/reports/checkpoint_phase_0.txt for the full checkpoint. |

## Operational tooling

- `scripts/argus_orchestrator_watch.py` (`make orchestrator-watch`) — local
  "no-nudge" watcher: polls `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` for
  a new `ACTIVE` instruction and, when one appears and passes the
  TARGET_COMMIT check, launches the local Claude CLI non-interactively to
  execute exactly that instruction under `orchestration/PROTOCOL.md`. Not
  running by default — the human operator starts it explicitly. See
  `docs/OPERATIONS.md` for usage and `orchestration/checkpoints/
  watcher_setup.md` for the build/test record. This is operational tooling,
  not ARGUS phase work — `current_phase` above is unaffected.

## Rules

- This file may be updated by the implementation agent to reflect actual build
  progress.
- `last_orchestrator_approved_phase` and `approved_commit` may ONLY be set to a
  new value after receiving **explicit** orchestrator approval for that phase.
  The implementation agent must never self-approve a phase here.
- Do not begin work on `current_phase + 1` while `awaiting_orchestrator_review`
  is `true` for the current phase.
