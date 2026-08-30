# ARGUS Build State

Machine-and-human-readable state for session recovery (MASTER_SPEC.md section 8).
Every new implementation session must read this file before doing anything else.

```yaml
current_phase: 0
last_completed_phase: 0  # implementation-agent build+test+acceptance complete; NOT orchestrator-approved
last_orchestrator_approved_phase: null
approved_commit: null
awaiting_orchestrator_review: true
known_blockers:
  - "This implementation sandbox's egress policy blocks Docker Hub's image
     CDN (production.cloudfront.docker.com -> 403), so `docker compose up
     postgres` (postgres:17 image) could not be pulled/verified here.
     compose.yaml is unmodified and still targets postgres:17 as required by
     TECH-004. Phase 0 acceptance (migration-from-zero, DB roles, provider_usage
     grants, argus health, full pytest suite) was instead verified against the
     sandbox's locally-installed PostgreSQL 16 server, using the exact same
     Alembic migration and application code that Compose would run against
     PostgreSQL 17. This is a sandbox verification substitution only, not a
     spec or architecture change -- record any further action in
     docs/DECISION_LOG.md. On a normal host with unrestricted Docker Hub
     access, `make bootstrap && make up` runs against real Postgres 17 with
     no code changes needed."
```

## Phase history

| Phase | Status | Commit | Notes |
|-------|--------|--------|-------|
| 0 | BUILT — awaiting orchestrator review | 2ad092deb248136d443e4384b9c11dfc17f58135 | Foundation scaffold: repo layout, uv env, Compose+Postgres, Alembic baseline + DB roles, config/spec hashing, clock abstraction, structured logging, CLI skeleton, FastAPI skeleton, health framework, provider_usage schema, checkpoint bundle framework. 29/29 tests pass, 93% coverage, ruff+mypy clean. See runtime/reports/checkpoint_phase_0.txt for the full checkpoint. |

## Rules

- This file may be updated by the implementation agent to reflect actual build
  progress.
- `last_orchestrator_approved_phase` and `approved_commit` may ONLY be set to a
  new value after receiving **explicit** orchestrator approval for that phase.
  The implementation agent must never self-approve a phase here.
- Do not begin work on `current_phase + 1` while `awaiting_orchestrator_review`
  is `true` for the current phase.
