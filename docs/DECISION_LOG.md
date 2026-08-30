# ARGUS Decision Log

Append-only record of every orchestrator-approved material change to
MASTER_SPEC.md or to a decision the spec explicitly delegated to the
orchestrator (MASTER_SPEC.md section 109). Do not silently edit
MASTER_SPEC.md — record the change here instead, with the requesting
party and the git commit that implements it.

Entries are appended chronologically. Do not rewrite or delete prior entries.

## Format

```
### YYYY-MM-DD — <short title>
- requirement_id: <MASTER_SPEC section/ID this touches>
- decision: <what was decided>
- reason: <why>
- requested_by: <human operator | orchestrator>
- impact: <what changes as a result>
- git_commit: <commit sha implementing it>
```

## Entries

### 2026-08-30 — Phase 0 checkpoint STATUS discipline + deferred PG17 Docker validation
- requirement_id: section 104 (STANDARD ORCHESTRATOR CHECKPOINT, field F/STATUS),
  section 106 (CLEAN SOURCE REQUIREMENT), TECH-004 (PostgreSQL 17)
- decision: The original Phase 0 checkpoint reported `STATUS: PASS` while also
  reporting `[PARTIAL] Postgres starts`, which is an internally inconsistent
  checkpoint. Corrected going forward: Phase 0's PostgreSQL-17-via-Docker-Compose
  path is tracked as its own explicit state,
  `PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK`, recorded in
  docs/BUILD_STATE.md. The successful PostgreSQL 16 local run is retained as
  evidence the migration/application code is functionally correct, but is
  explicitly NOT represented as PostgreSQL 17 validation anywhere. Per
  explicit orchestrator instruction, this deferred check does not block
  starting Phase 1, but does block approving live readiness until closed out
  with a real `postgres:17` run. compose.yaml remains unchanged — still pins
  `postgres:17` per TECH-004; no architecture change was made.
- reason: This sandbox's egress policy blocks Docker Hub's image CDN
  (production.cloudfront.docker.com -> 403 at the proxy), so the postgres:17
  container image could not be pulled here. Claiming an unconditional
  checkpoint PASS while a stated acceptance criterion was PARTIAL violates
  the checkpoint contract; the orchestrator asked for this to be corrected
  rather than glossed over.
- requested_by: orchestrator
- impact: docs/BUILD_STATE.md now carries a `PG17_COMPOSE_VALIDATION` field
  and an updated `known_blockers` entry so this cannot be silently forgotten
  in a future session. The replacement Phase 0 checkpoint uses
  `STATUS: PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION` instead of an
  unconditional PASS.
- git_commit: (this commit — see git log for the remediation commit hash)

### 2026-08-30 — Remove hardcoded fallback database passwords
- requirement_id: SEC-005, section 108 (CREDENTIAL HANDLING), section 72
  (database privilege separation)
- decision: Removed all working hardcoded fallback DB role/admin passwords
  (e.g. literal strings like `"REDACTED_FORMER_DEV_PLACEHOLDER"`) from
  migrations/versions/0001_baseline_roles_and_provider_usage.py, compose.yaml,
  and src/argus/db/connection.py. Database role passwords (ingest, research,
  executor, admin) must now come from required environment variables
  (`ARGUS_DB_{INGEST,RESEARCH,EXECUTOR,ADMIN}_PASSWORD`, supplied via a local
  gitignored `.env` or the process environment). A missing required password
  now raises `argus.db.credentials.MissingCredentialError` with an explicit
  "LOCAL CREDENTIAL REQUIRED" message (section 108 format) rather than
  silently substituting a working default; compose.yaml uses Compose's
  `${VAR:?message}` required-variable syntax for the same reason.
  `.env.example` already contained empty placeholders only and needed no
  change. DB role separation and grants (argus_ingest/argus_research/
  argus_executor least-privilege table grants from migration 0001) are
  unchanged.
- reason: A repository must not contain any credential that would let it
  "just work" against a real database without the operator supplying real
  secrets, even a clearly-labeled dev-only one — that is a standing
  liability and inconsistent with SEC-005/section 108's "never commit ...
  credentials" and "fail rather than silently substitute" posture.
- requested_by: orchestrator
- impact: `uv run alembic upgrade head` and any DB connection now fail
  immediately and clearly if the relevant `ARGUS_DB_*_PASSWORD` variable is
  unset, instead of silently succeeding with a guessable password. New
  regression tests (tests/unit/test_db_credentials.py) assert both the
  fail-closed behavior and that no `dev_only`-style literal remains in the
  connection-resolution code path.
- git_commit: (this commit — see git log for the remediation commit hash)
