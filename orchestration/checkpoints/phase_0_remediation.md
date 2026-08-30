================ ARGUS ORCHESTRATOR CHECKPOINT ================

[PROVENANCE NOTE, added after this checkpoint was first written: on
2026-08-30 the human operator had git history rewritten (git-filter-repo)
to scrub four inert dev-only password placeholder strings that had been
present in earlier commits, before making this repository public. That
rewrite changed every commit hash on this branch. GIT_COMMIT below has been
updated to the new hash; see docs/DECISION_LOG.md, entry "Git history
rewrite to scrub inert dev-only password literals", for the full record
and the old->new hash mapping. No other content in this checkpoint was
altered except the incidental redaction noted at "B.1" below.]

A. Identity
PROJECT: ARGUS
MASTER_SPEC_VERSION: v2.0
MASTER_SPEC_HASH: 41f7242c288feec709b1ed72e62c74a1dc5e3b3cd9ad01e9b6e28373d9d14011
PHASE: 0 (Foundation)
STATUS: PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION
UTC_TIMESTAMP: 2026-08-30T22:06:17Z
GIT_COMMIT: db0716924df42db64028116b0dfc1e7f53a93ce7 (post-rewrite hash; original was a4bfc01bd4cde04b0942cca2fcc4bf7c9e17e1eb)
CONFIG_HASH: 4be41f34b83f1841299ccef8c244362f10beb31ccc1c1bfd3ba819dc1e323b0e
SCHEMA_VERSION: 0.1.0-phase0

This replaces the prior Phase 0 checkpoint (commit 2ad092d), which incorrectly
reported STATUS: PASS while also reporting [PARTIAL] Postgres starts — an
internally inconsistent checkpoint. This checkpoint corrects that and reports
the remediation completed per explicit orchestrator instruction.

B. What was built
Phase 0 build (unchanged from the prior checkpoint): repository scaffold per
section 7, MASTER_SPEC.md saved verbatim, docs/ARCHITECTURE.md/BUILD_STATE.md/
DECISION_LOG.md (+ stubs), uv-managed Python 3.12 env, compose.yaml (Postgres
17 + api services), Alembic baseline migration 0001 (least-privilege
argus_ingest/argus_research/argus_executor roles + provider_usage table),
config.py/clock.py/logging.py, db/ package, health.py, cli.py, api/main.py,
checkpoint.py, config/*.yaml, Makefile + scripts/.

Remediation completed this round (originally commits d93d803, a4bfc01; see
provenance note above for post-history-rewrite hashes), per orchestrator
instruction:
1. Removed every working hardcoded fallback DB password (one clearly-labeled
   dev-only placeholder literal per role) from migrations/versions/0001_*.py,
   compose.yaml, and src/argus/db/connection.py. Added src/argus/db/credentials.py:
   database role/admin passwords now come strictly from required environment
   variables (ARGUS_DB_{INGEST,RESEARCH,EXECUTOR,ADMIN}_PASSWORD); a missing
   one raises MissingCredentialError with a "LOCAL CREDENTIAL REQUIRED"
   message (section 108 format) instead of silently substituting a working
   default. compose.yaml uses Compose's ${VAR:?message} required-variable
   syntax for the admin password. .env.example already contained empty
   placeholders only. scripts/bootstrap.sh now stops after creating .env and
   tells the operator to fill in real password values, rather than
   proceeding into a migration that would previously have silently
   succeeded with a guessable password.
2. Recorded PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK explicitly
   in docs/BUILD_STATE.md (as a top-level field, not buried in prose) and in
   docs/DECISION_LOG.md, so this cannot be forgotten in a future session.
   compose.yaml is unchanged and still pins postgres:17 (TECH-004) — nothing
   about the target architecture changed.
3. Added tests/unit/test_db_credentials.py: fail-closed behavior for every
   DB role (parametrized) and for the admin connection, plus a regression
   guard asserting no "dev_only"-style literal exists anywhere in
   src/argus/db/connection.py.

C. Files changed
git diff --stat be09468..HEAD: 98 files changed, 7990 insertions(+), 1
deletion(-). Since the prior checkpoint (2ad092d..a4bfc01): 10 files touched
in the remediation commit (2 new: src/argus/db/credentials.py,
tests/unit/test_db_credentials.py; 8 modified: README.md, compose.yaml,
docs/ARCHITECTURE.md, docs/BUILD_STATE.md, docs/DECISION_LOG.md,
migrations/versions/0001_*.py, scripts/bootstrap.sh,
src/argus/db/connection.py) plus one docs-only follow-up commit
(BUILD_STATE.md, DECISION_LOG.md hash backfill). Full listing in
runtime/reports/orchestrator_bundle_phase_0.txt (gitignored local artifact).

D. Commands actually run (this remediation round)
- Edited: src/argus/db/credentials.py (new), src/argus/db/connection.py,
  migrations/versions/0001_baseline_roles_and_provider_usage.py,
  compose.yaml, scripts/bootstrap.sh, README.md, docs/ARCHITECTURE.md,
  docs/BUILD_STATE.md, docs/DECISION_LOG.md, tests/unit/test_db_credentials.py
- uv run ruff check . / uv run ruff format . / uv run ruff format --check .
- uv run mypy
- service postgresql start (local PG16 substitute; had stopped between
  sessions and was restarted)
- Migration-from-zero, run twice: once with all required credentials
  present (succeeded), once with ARGUS_DB_INGEST_PASSWORD deliberately
  unset (failed immediately with MissingCredentialError, exit code 1 — no
  partial role/table creation occurred), then re-migrated cleanly
- uv run pytest --cov --cov-report=term-missing (run after edits; 41/41
  passed)
- uv run pytest tests/integration/test_db_roles.py
  tests/integration/test_provider_usage_model.py -v (role-privilege tests,
  explicitly re-verified)
- grep-based secret scan across tracked file types
- grep-based scan for any remaining "dev_only" literal outside the
  regression-guard test itself
- git status --porcelain (clean after each commit) / git add -A / git commit
  (x2: remediation + doc hash backfill) / git push

E. Test results
pytest: passed: 41, failed: 0, skipped: 0 (up from 29 — added
  tests/unit/test_db_credentials.py, 12 tests)
coverage: 93% overall (442 statements, 21 missed); src/argus/db/connection.py
  and src/argus/db/credentials.py both 100%; all modules >= 80%
ruff: All checks passed! (check + format --check clean)
mypy: Success: no issues found in 40 source files

F. Acceptance criteria (Phase 0)
[PASS] fresh repo bootstrap works (uv sync + uv python install 3.12
  verified; scripts/bootstrap.sh now explicitly stops for the operator to
  fill in real DB passwords before proceeding — this is intentional
  fail-closed behavior, not a defect)
[DEFERRED] Postgres starts via `docker compose up -d postgres` —
  PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK (see docs/BUILD_STATE.md
  and docs/DECISION_LOG.md). Docker Hub's image CDN is blocked by this
  sandbox's egress policy (403 at the proxy), so the actual postgres:17
  image could not be pulled here. This is NOT represented as PASS or as
  PostgreSQL 17 validation. A local PostgreSQL 16 server was substituted
  to functionally validate the identical migration/application code (PASS
  for that substitute path only). compose.yaml is untouched, still pins
  postgres:17 per TECH-004. Per explicit orchestrator instruction, this
  deferred check does not block Phase 1 but does block live-readiness
  approval.
[PASS] migration from zero works (re-verified this round, including a
  deliberate missing-credential failure case that correctly aborted
  before creating any role/table, followed by a clean re-run)
[PASS] tests run (41/41 passed)
[PASS] Ruff runs
[PASS] mypy runs
[PASS] config hash generated (unchanged: 4be41f34... — no config/*.yaml
  files were touched by this remediation)
[PASS] MASTER_SPEC hash generated (unchanged: 41f7242c...; MASTER_SPEC.md
  was not touched)
[PASS] DB roles exist (re-verified: tests/integration/test_db_roles.py x3 +
  tests/integration/test_provider_usage_model.py, all passing against a
  freshly-migrated database)
[PASS] no secrets committed — additionally, no hardcoded *working* fallback
  credential of any kind remains anywhere in the repository (this round's
  specific remediation target); grep scan for both secret patterns and
  "dev_only"-style literals is clean; git status --porcelain clean after
  every commit
[PASS] runtime directories ignored (unchanged)
[PASS] BUILD_STATE works (now additionally carries an explicit
  PG17_COMPOSE_VALIDATION field so the deferral cannot be silently dropped)

G. Database/data sanity
Unchanged from the prior checkpoint: provider_usage table with the full
17-column section-14 schema, 0 rows (no provider adapters exist yet). 3
application-facing roles (argus_ingest, argus_research, argus_executor),
each now created with a password sourced from a required env var rather
than a hardcoded literal. No other tables exist yet (expected for Phase 0).

H. Provider usage
Not applicable — no provider adapters exist yet (Phase 1+).

I. Data quality warnings
- PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK (see F above and
  docs/BUILD_STATE.md / docs/DECISION_LOG.md for the full record). This is
  the only open item from this checkpoint's perspective; it is explicitly
  not being represented as resolved.
- No hardcoded credential fallback of any kind remains in the repository;
  .env (local, gitignored) continues to hold this sandbox's own disposable
  dev-only password values, supplied as the required environment variables
  — this is the intended mechanism, not a code-level fallback, and .env
  itself was never committed.

J. Sample outputs
`uv run argus health` (unchanged from prior checkpoint's shape):
  Postgres: OK
  Clock: OK
  config_hash: 4be41f34b83f1841299ccef8c244362f10beb31ccc1c1bfd3ba819dc1e323b0e
  master_spec_hash: 41f7242c288feec709b1ed72e62c74a1dc5e3b3cd9ad01e9b6e28373d9d14011
  LIVE_READY_SOFTWARE: false
  LIVE_CANARY_PASSED: false
  LIVE_ARMED: false

Missing-credential failure (deliberately triggered this round, ARGUS_DB_INGEST_PASSWORD unset):
  argus.db.credentials.MissingCredentialError: LOCAL CREDENTIAL REQUIRED:
  ARGUS_DB_INGEST_PASSWORD
  Place it locally in your .env file (gitignored; see .env.example) or
  process environment before running migrations or connecting to Postgres.
  DO NOT paste its value into chat. No fallback password exists — this is
  intentional (MASTER_SPEC.md SEC-005).
  (alembic exit code 1; no partial role/table creation occurred)

K. Architectural deviations
NONE. compose.yaml still targets postgres:17 (TECH-004); the PostgreSQL 16
substitute used for sandbox verification is explicitly tracked as a deferred
environmental check, not an architecture change.

L. ORCHESTRATOR_REVIEW_REQUIRED
- PG17_COMPOSE_VALIDATION remains DEFERRED_ENVIRONMENTAL_CHECK. Per your
  instruction this does not block Phase 1, but closing it out (running
  `make bootstrap && make up` against real postgres:17 on a host with normal
  Docker Hub access, then recording the result in docs/BUILD_STATE.md and
  docs/DECISION_LOG.md) is required before live readiness can be approved.
  No other review items are outstanding from this remediation.

M. Known bugs / debt
None beyond the deferred PG17 validation in I/L above. Coverage gaps are
limited to the same handful of defensive/unreachable branches noted in the
prior checkpoint (api/main.py engine-unavailable fallback paths,
checkpoint.py missing-file fallback branches, cli.py --console-logs/__main__
guard, config.py edge-case merge branches, db/session.py dispose_all,
clock.py first-tick branch); none are safety-relevant since no
live-execution, risk, or custody code exists yet.

N. Security state
- Secret scan: clean. Additionally: zero hardcoded working fallback
  credentials remain anywhere in the repository (this round's remediation
  target), verified by grep scan and by an automated regression test
  (tests/unit/test_db_credentials.py::test_no_hardcoded_dev_only_password_fallback_exists).
- Key isolation: not applicable yet — no signing key/executor exists.
- Live readiness: LIVE_READY_SOFTWARE=false, LIVE_CANARY_PASSED=false,
  LIVE_ARMED=false (hardcoded; no code path can set any to true).
- Arming: no arm file/mechanism exists. risk.default.yaml pins all capital
  limits to 0.
- DB privilege separation (section 72): unchanged and re-verified —
  argus_ingest can write provider_usage, argus_research can only read it
  (automated test asserts the research-role write is rejected by
  Postgres), argus_executor has no table grants yet. All three roles are
  now created with passwords sourced from required environment variables
  rather than any hardcoded value.

O. Next specified phase
PHASE 1 — PROVIDERS, IMMUTABLE INGESTION, LIVE RECONCILIATION.
DO NOT BEGIN IT. Per this remediation round, the deferred PG17 Docker
validation does not block starting Phase 1 once explicitly approved — but
Phase 1 has not been started, and this checkpoint does not constitute that
approval.

================ END ARGUS CHECKPOINT =========================
