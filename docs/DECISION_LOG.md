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

### 2026-08-30 — Watcher remediation: four defects found on independent audit
- requirement_id: `orchestration/PROTOCOL.md` sections 5 and 7 (agent handoff
  contract, target-commit protection), MASTER_SPEC.md section 103 (phase
  gating — "do not begin the next phase until explicit orchestrator
  approval")
- decision: Per human-operator instruction, independently re-audited
  `scripts/argus_orchestrator_watch.py` and its test suite from a fresh
  read of MASTER_SPEC.md / docs/BUILD_STATE.md / docs/DECISION_LOG.md /
  orchestration/PROTOCOL.md / orchestration/ORCHESTRATOR_INSTRUCTIONS.md /
  orchestration/AGENT_HANDOFF.md / the checkpoint+bundle evidence it
  names, rather than trusting the prior build's own account of itself.
  Substantiated and fixed four defects, each with a dedicated regression
  test proving the old code would have wrongly allowed the failure mode:
  - (A) `AUTHORIZED_PHASE` was parsed out of
    `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` but never validated
    anywhere — a malformed value, or one that skipped ahead of
    `docs/BUILD_STATE.md`'s `current_phase` (e.g. authorizing phase 2 while
    still on phase 0), would have reached Claude unchecked, with phase-gate
    enforcement resting entirely on the Claude prompt rather than the
    watcher. Added `verify_phase_authorization()`: rejects (logs
    `PHASE_AUTHORIZATION_INVALID`, does not launch) any `AUTHORIZED_PHASE`
    that isn't a non-negative integer no greater than `current_phase + 1`.
    This is what makes "Phase 1 must not be authorized" prematurely an
    enforced property of the watcher, not just of the prompt.
  - (B) The check that `AGENT_HANDOFF.md`'s `LAST_ORCHESTRATOR_INSTRUCTION_ID`
    refers to the instruction just run used substring containment (`in`)
    instead of exact equality — a stale or unrelated field value that
    merely *contained* the instruction id as a substring (e.g. id `"1"`
    inside a leftover `"instr-12"`) would have false-positive matched.
    Changed to exact string equality.
  - (C) `CHECKPOINT_PATH`/`BUNDLE_PATH` were verified only by
    `Path.exists()` — a pre-existing file at that path, left over from an
    earlier handoff and never touched by the current run, would pass. Now
    both paths must also appear in `git diff --name-only` between HEAD
    immediately before Claude was launched and HEAD after the run, proving
    the evidence was actually produced (or at least touched) by commits
    made during this run, not merely present on disk.
  - (D) Stale-state recovery on watcher restart only handled a `RUNNING`
    state (crash during the Claude subprocess). A crash between writing
    `CLAIMED` and writing `RUNNING` left the watcher silently wedged on
    that state forever — no `FAILED` transition, no log event, nothing
    visible to an operator or auditor. The restart check now treats both
    `RUNNING` and `CLAIMED` as stale, marking `FAILED` with a log event in
    either case.
  Also tightened the CLAUDE_PROMPT text and `orchestration/PROTOCOL.md`
  sections 5/7 to document these as mechanically-enforced requirements
  (exact instruction-id match, evidence-freshness, phase-authorization
  bound), not just implementation detail, so a future Claude run producing
  a real handoff complies with what the watcher actually checks.
- reason: The watcher is meant to gate whether Phase 1 (or any phase) work
  begins unattended; MASTER_SPEC.md section 103 and the phase-gate
  discipline throughout the spec require that no phase begin without
  explicit, verifiable orchestrator approval. A watcher that accepts a
  malformed phase authorization, a substring-matched instruction id, or a
  stale checkpoint/bundle as valid evidence would let exactly that kind of
  unaudited, unauthorized advancement slip through silently — the opposite
  of "fail closed."
- requested_by: human operator (relaying an independent audit performed by
  a separate reviewer, "ChatGPT" — the four defects were reproduced and
  substantiated independently from the code and this repository's own
  evidence before being fixed, not accepted on the audit's say-so alone)
- impact: `scripts/argus_orchestrator_watch.py` gained
  `verify_phase_authorization()` / `read_current_phase()`, a stricter
  `verify_handoff()` (exact id match + evidence-freshness check via a new
  `head_before` parameter), and a broadened stale-state restart check.
  6 new regression tests added
  (`tests/unit/test_orchestrator_watch.py`); all pass, and each was
  confirmed to fail under the pre-fix code by tracing the old logic (a
  skip-ahead/malformed AUTHORIZED_PHASE would have launched Claude; the
  substring-match handoff and stale-evidence cases would have reached
  `COMPLETED`; the stale-CLAIMED case would not have transitioned to
  `FAILED`). Full suite: 63/63 passed, ruff clean, mypy clean. No ARGUS
  architecture change; no MASTER_SPEC.md change.
  `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` was not modified — Phase 1
  remains unauthorized by this or any prior task.
- git_commit: a700ee11eb2af8ea4a433cbf8a6d807d6078b349

### 2026-08-31 — Watcher remediation round 2: orchestrator-requested hardening (argus-watcher-remediation-002)
- requirement_id: `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` instruction
  `argus-watcher-remediation-002` (pushed by the ARGUS ORCHESTRATOR via its
  now-working GitHub App access); `orchestration/PROTOCOL.md` sections 4, 5,
  7 (instruction-state contract, agent handoff contract, target-commit and
  phase-authorization protection); MASTER_SPEC.md section 103 (phase gating).
- decision: The orchestrator reviewed the prior remediation
  (`watcher_remediation.md`, commit `a700ee1`) and rejected it as
  insufficient: the four fixes were real, but the watcher was "not yet
  deterministic, restart-safe, idempotent, and fail-closed enough for
  unattended phase advancement." Rather than patch further on top of the
  same design, `scripts/argus_orchestrator_watch.py` and
  `tests/unit/test_orchestrator_watch.py` were substantially rewritten to
  close eight numbered categories of gaps:
  1. **Durable, fail-closed state handling.** `read_state_safe()` now
     distinguishes `OK`/`MISSING`/`INVALID` outcomes. A malformed/corrupt/
     schema-invalid state file is never silently treated as fresh IDLE —
     it fails closed (`STATE_INVALID`) and is left untouched on disk for
     forensic inspection. A *missing* state file with an `ACTIVE`
     instruction outstanding is not assumed to be a first execution: the
     watcher cross-checks `orchestration/AGENT_HANDOFF.md` (git-tracked,
     so it survives a local `runtime/` wipe) and either recognizes the
     instruction as already completed (`STATE_REBUILT_FROM_HANDOFF`, no
     relaunch) or fails closed (`STATE_MISSING_FAIL_CLOSED`, requiring a
     new `INSTRUCTION_ID`). This resolution is deliberately deferred until
     *after* the post-pull instruction is known (an earlier draft of this
     fix read the pre-pull local instructions file too early and would
     have missed instructions that only existed on the remote); every
     early-return before that point leaves a `MISSING` state file
     unwritten so the next tick can still resolve it correctly rather than
     having a premature fresh-IDLE write mask the loss. State writes now
     `fsync` the file and its parent directory.
  2. **A failed Claude process now always fails the run.** This was the
     literal bug the orchestrator called out: the prior `tick()` recorded
     `exit_code` but never branched on it before calling `verify_handoff()`
     — a nonzero exit (or timeout, or a launch-time `OSError` such as
     `FileNotFoundError`) could still be accepted as `COMPLETED` if
     handoff/evidence files happened to look valid. `tick()` now checks
     `exit_code != 0` immediately after the launch attempt and fails the
     run before any other verification runs, logging a diagnostic bounded
     to a few hundred characters (never raw env vars or unbounded output).
  3. **Evidence must be new, immutable, and structurally valid.**
     `CHECKPOINT_PATH`/`BUNDLE_PATH` are normalized and validated
     (repository-relative, inside the correct directory, correct
     extension, no `..`/absolute/symlink paths), must not have existed at
     the pre-launch `HEAD` (`git cat-file -e`), and must show as newly
     *added* — not modified — in `git diff --name-status` over the run's
     commit range. Their content is structurally validated
     (`validate_checkpoint_content()`/`validate_bundle_content()`): a
     one-line placeholder like `checkpoint\n` now fails. `AGENT_HANDOFF.md`
     is validated against the full 11-field schema from
     `orchestration/PROTOCOL.md` section 5 (previously only 4 of 11 fields
     were checked), rejecting duplicates, missing fields, and a reused
     `HANDOFF_ID`. `CURRENT_COMMIT` and the checkpoint's own `GIT_COMMIT`
     field must resolve to a commit actually created during the run.
  4. **Branch-movement and commit-attribution detection.** Local and remote
     `HEAD` are compared immediately before launch (not just after).
     Post-run `HEAD` must descend linearly from the pre-launch `HEAD` — a
     rewritten/force-pushed history or a merge commit anywhere in the
     run's range fails the run. Every commit in that range must carry the
     exact trailer `ARGUS-INSTRUCTION-ID: <instruction_id>`; a differently
     worded or merely similar (substring-matching) trailer does not count.
  5. **Mechanical self-authorization prevention.** The blob hash of
     `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is captured immediately
     before launch and re-checked (via `git hash-object` against the live
     working-tree file, so an uncommitted edit is caught too, not only a
     committed one) after Claude exits. Any difference — even one later
     committed and pushed by the implementation agent itself — fails the
     run outright, before any other evidence is considered. This is a
     necessary but not fully sufficient defense in a non-cryptographic,
     file-trust-based protocol: see the "known limitation" note below.
  6. **Explicit, sequence-based phase gating with Phase 1.5 support.** The
     prior integer/`current_phase + 1` rule could not represent the
     mandatory Phase 1.5 (or 6.5) gate and its own documentation was
     self-contradictory about when Phase 1 could begin. `PHASE_SEQUENCE`
     is now an explicit ordered tuple of string tokens (`"0", "1", "1.5",
     "2", ..., "6", "6.5", ..., "11"`), compared only by list position —
     never as floats. A new `APPROVES_PHASE` instruction field
     distinguishes same-phase remediation (`APPROVES_PHASE: NONE`,
     requires `AUTHORIZED_PHASE == current_phase`) from phase advancement
     (`APPROVES_PHASE == current_phase == last_completed_phase`,
     `awaiting_orchestrator_review == true`, and `AUTHORIZED_PHASE` must be
     the *immediate* successor in the sequence — no skipping a phase or
     sub-phase).
  7. **Strict instruction-field parsing.** Duplicate field lines, missing
     fields, an unknown `STATUS`, a malformed `ISSUED_AT` timestamp, a
     non-full-SHA `TARGET_COMMIT`, an empty/`NONE` `AUTHORIZED_ACTION`, and
     an invalid `AUTHORIZED_PHASE`/`APPROVES_PHASE` are all rejected for an
     `ACTIVE` instruction (the `NO_INSTRUCTION` placeholder keeps a
     deliberately lenient, explicitly-validated safe schema, since its
     `STATUS` alone already guarantees no launch can occur).
  8. **Conservative, ordered post-run verification**: process-exit success,
     then ancestry/attribution, then instructions-file integrity, then
     handoff/evidence completeness, then clean-worktree/pushed-HEAD
     equality — matching the order specified by the instruction, so an
     early, cheaper check can rule out a run before the more expensive
     evidence-content checks run.
  Also added: a defensive `try`/`except` around each `tick()` call inside
  `run_forever()` (an uncaught exception in one tick must not crash the
  whole watcher process; `--once` runs intentionally still let an exception
  propagate, since an operator is watching interactively) and 26 new/updated
  adversarial regression tests (see
  `tests/unit/test_orchestrator_watch.py`), covering every category listed
  in the instruction's "Mandatory adversarial regression tests" section,
  using structurally-valid fixture checkpoint/bundle content (not
  placeholders) and a commit helper that appends the required trailer.
  `orchestration/PROTOCOL.md` sections 4, 5, and 7 and `docs/OPERATIONS.md`
  were updated to describe the above as mechanically-enforced requirements.
- reason: MASTER_SPEC.md section 103 and this project's phase-gate
  discipline require that no phase begin without explicit, verifiable
  orchestrator approval, and the CORE-011 "truth outranks impressive P&L"
  principle requires the watcher's own claims about what it verified to be
  accurate rather than aspirational. A watcher that can mark a failed
  Claude run `COMPLETED`, accept stale or placeholder evidence, miss a
  rewritten/force-pushed branch, or silently reinitialize state after a
  local `runtime/` wipe is not safe to leave unattended for phase
  advancement, which is exactly the property this task was asked to
  establish.
- requested_by: ARGUS ORCHESTRATOR, via
  `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` instruction
  `argus-watcher-remediation-002` (`STATUS: ACTIVE`,
  `TARGET_COMMIT: 79287b573bd0cc106d26d5f2001f919b11d61625`,
  `AUTHORIZED_PHASE: 0`, `APPROVES_PHASE: NONE` — same-phase operational
  remediation, verified against `docs/BUILD_STATE.md` before this task
  began: `current_phase: 0`, `last_completed_phase: 0`,
  `awaiting_orchestrator_review: true`).
- impact: `scripts/argus_orchestrator_watch.py` substantially rewritten
  (new `PHASE_SEQUENCE`, `read_state_safe()`/`StateLoadResult`, strict
  instruction/handoff parsers with duplicate/schema rejection,
  `verify_run_ancestry_and_attribution()`,
  `verify_instructions_unchanged()`, `validate_checkpoint_content()`/
  `validate_bundle_content()`, evidence path normalization/validation, a
  rewritten `verify_phase_authorization()` and `verify_handoff()`, and a
  restructured `tick()` implementing the ordered verification sequence).
  `tests/unit/test_orchestrator_watch.py` rewritten with 51 tests (up from
  22), all passing; full suite 88 passed / 4 skipped (pre-existing,
  unrelated Postgres-integration skips), 93% coverage on `src/argus`
  (unchanged — the watcher lives outside that coverage scope and is
  verified by its own dedicated tests), ruff clean, mypy clean.
  `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` was not modified. Phase 1
  remains unauthorized by this task.
  **Known limitation, stated honestly rather than overclaimed**: this
  protocol is file-trust-based, not cryptographically signed. The
  blob-hash-unchanged check (#5 above) reliably catches an implementation
  agent that edits the live instructions file, and the target-commit
  diff-scope check independently catches a self-authored instruction whose
  `TARGET_COMMIT` points at the pre-launch `HEAD` while other files also
  changed in the same range. A maximally adversarial run that points a
  self-authored instruction's `TARGET_COMMIT` at its own freshly-created
  `HEAD` (making the ancestor-diff trivially empty) is not fully excluded
  by these mechanisms alone — closing that gap completely would require a
  cryptographic signing step outside this protocol's current design, which
  is out of scope for this instruction. Also unchanged from prior rounds:
  the watcher's real (non-mocked) Claude CLI launch path remains untested
  against an actual `claude` process in this sandbox, and
  `PG17_COMPOSE_VALIDATION` remains `DEFERRED_ENVIRONMENTAL_CHECK`
  (unrelated to this task).
- git_commit: (see the final hash-fill commit for this task's exact SHA)
