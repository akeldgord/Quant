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
- git_commit: ca74d09b3f976a5726fe46c1a8ea59d7bbdd3ad7 (hash as of the history rewrite recorded below; original pre-rewrite hash was d93d8036e81256cb3b51218b4a0fa7f6a9b78a11)

### 2026-08-30 — Remove hardcoded fallback database passwords
- requirement_id: SEC-005, section 108 (CREDENTIAL HANDLING), section 72
  (database privilege separation)
- decision: Removed all working hardcoded fallback DB role/admin passwords
  (one clearly-labeled dev-only placeholder literal per role) from
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
- git_commit: ca74d09b3f976a5726fe46c1a8ea59d7bbdd3ad7 (hash as of the history rewrite recorded below; original pre-rewrite hash was d93d8036e81256cb3b51218b4a0fa7f6a9b78a11)

### 2026-08-30 — Git history rewrite to scrub inert dev-only password literals
- requirement_id: SEC-005, section 108 (CREDENTIAL HANDLING)
- decision: Before making this repository public, the human operator asked
  Claude to confirm no secrets existed anywhere in git history (not just the
  working tree). A full-history scan (`git log --all -p` across every file
  ever committed) found that the four literal dev-only DB password fallback
  strings removed from the working tree by the "Remove hardcoded fallback
  database passwords" entry above were still present in history: visible in
  the blob at the pre-remediation commit (originally `2ad092d`) and in the
  `-` side of the remediation commit's diff (originally `d93d803`). These
  strings were never real credentials — they were only ever used, as a
  hardcoded fallback, against an ephemeral local Postgres instance inside a
  disposable implementation-sandbox container, never against any real or
  production database. The human operator explicitly chose, when offered the
  choice, to rewrite history to purge them rather than leave them in place
  with documentation. `git-filter-repo` was used with `--replace-text` and
  `--replace-message` to replace the four exact literal per-role placeholder
  strings (deliberately not reproduced here, to avoid reintroducing them
  into history via this very entry) with the placeholder text
  `REDACTED_FORMER_DEV_PLACEHOLDER` across every blob and commit message in
  history, then the branch was force-pushed. This rewrote every commit's
  hash on `claude/argus-folder-setup-77ahrk`; the mapping from old to new
  hashes is: `be09468`→`be09468` (root commit, unchanged — contained none of
  the scrubbed strings), `2ad092d`→`b838558`, `386532e`→`cc82081`,
  `d93d803`→`ca74d09`, `a4bfc01`→`db07169`, `37699d7`→`966fd7a`. All
  commit-hash references in `docs/BUILD_STATE.md`, this file, and
  `orchestration/AGENT_HANDOFF.md` / `orchestration/checkpoints/` /
  `orchestration/bundles/` were updated to the new hashes as part of this
  same change. A handful of *current* files that had legitimately quoted one
  of the four strings in prose (documenting what had been removed, not an
  active secret) were collaterally rewritten to the placeholder text too;
  those were cleaned up by hand in the same commit
  (`tests/unit/test_db_credentials.py`'s now-redundant assertion was
  removed; prose in this file and in the `orchestration/` checkpoint/bundle
  copies was reworded).
- reason: The literal request was to confirm nothing sensitive exists in git
  history before making the repository public, and — once one real (if
  low-risk) finding surfaced — to actually remove it rather than merely
  document it, since the repository was about to become publicly readable.
- requested_by: human operator
- impact: A full re-scan of `git log --all -p` after the rewrite finds zero
  occurrences of the four original literal strings anywhere in history. No
  application code or architecture changed — this was a git-history-only
  operation plus documentation/test cleanup. All commit hashes referenced
  anywhere in this repository's own tracked files were updated to match.
- git_commit: 966fd7a3d3ccfedc02f2ff18678fae48f0ddab36 (pre-cleanup rewrite tip; see the follow-up commit that includes this DECISION_LOG entry itself for the final hash)
