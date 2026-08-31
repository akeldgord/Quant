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
- git_commit: 34930bfa78cd7f667527b40f7d006c923c7c9ba6

### 2026-08-31 — Watcher remediation round 3: close the self-authorization bypass and fail-open Git-error gaps (argus-watcher-remediation-003)
- requirement_id: `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` instruction
  `argus-watcher-remediation-003`; `orchestration/PROTOCOL.md` sections 4,
  5, 7; MASTER_SPEC.md section 103 (phase gating).
- decision: The orchestrator rejected watcher remediation round 2
  (`watcher_remediation_2.md`, commit `34930bf`), identifying six defect
  categories with concrete reproduction steps rather than general
  dissatisfaction. Each was independently traced against round 2's actual
  code before being fixed, not accepted on the audit's account alone:
  1. **A self-authored next instruction could still launch on a later
     tick.** Round 2's blob-hash check correctly failed the *originating*
     run, but only as an ordinary `FAILED` — and a self-authored
     instruction whose `TARGET_COMMIT` pointed at the immediately preceding
     (legitimate) implementation commit, with a diff touching only the
     instructions file, would structurally pass round 2's target-commit
     check on the *next* tick, since a new `INSTRUCTION_ID` isn't blocked
     by the "already attempted" guard that only applies to a *previously
     seen* id. Fixed with two independent layers: (a) a detected
     instructions-file modification is now a terminal, non-retryable
     `QUARANTINED` state — checked first and unconditionally in `tick()`,
     ahead of every other verification, so it can never be pre-empted by
     another check failing first — from which **no** future instruction of
     any ID or target is ever evaluated again until a human runs the new
     `--reset-quarantine` CLI flag after manual review; (b)
     `verify_target_commit()` independently tightened to require exactly
     one instruction-only commit whose parent is exactly `TARGET_COMMIT`,
     rejecting `TARGET_COMMIT == HEAD`, multiple commits, and merge commits
     between them. Neither layer claims to cryptographically authenticate
     *who* authored a commit — this file-trust protocol cannot do that
     without signing, which is explicitly out of scope and documented
     honestly rather than overclaimed (see "Known bugs / debt" in
     `orchestration/checkpoints/watcher_remediation_3.md`).
  2. **Safety-critical Git command errors failed open.** `git_changed_paths()`,
     `git_commits_in_range()`, the merge-enumeration check, and
     `is_worktree_dirty()` all returned an empty/`False` default on a
     failed subprocess call, which their callers then read as "no unexpected
     paths" / "no commits" / "no merges" / "clean" respectively. All four
     (and the new commit-message/trailer reads) now return `None` on any
     command failure, and every caller treats `None` as an explicit
     verification failure — never as an empty/clean/absent default.
  3. **Commit-message attribution accepted the trailer text anywhere in
     body prose.** The round-2 check matched any full line equal to
     `ARGUS-INSTRUCTION-ID: <id>`, which a prose paragraph could satisfy
     without forming a real trailer. Replaced with
     `git interpret-trailers --parse`-based parsing, requiring exactly one
     parsed terminal trailer with that exact key and value; a duplicate,
     conflicting, or prose-embedded (non-trailer-positioned) mention is
     now rejected.
  4. **Launch failures and diagnostics were not fully safe.** Only
     `subprocess.TimeoutExpired` and `OSError` were caught immediately; an
     arbitrary `Exception` from the launch wrapper could leave state
     `RUNNING` until a later tick (or forever, under `--once`, since
     `main()` adds no exception handling of its own around `tick()`). The
     except clause is now broadened to catch any ordinary exception and
     persist `FAILED` in the same `tick()` call, unconditionally. Separately,
     raw Claude subprocess stdout/stderr is no longer read into any log
     detail at all (truncation bounds length but is not credential
     redaction — a secret in the first 300 characters would still leak);
     only whitelisted metadata (exit code, timeout duration, exception
     *class name*) is logged, and every log detail is now sanitized
     (control characters and newlines stripped) so process output cannot
     forge a fake log line.
  5. **Timestamp validation was shape-only.** A regex accepted impossible
     values like month `99` or Feb 30. Replaced with
     `parse_canonical_utc_timestamp()`, a real `datetime.strptime` parse
     with an exact-round-trip requirement, applied to both instruction
     `ISSUED_AT` and (newly) handoff `UTC_TIMESTAMP`.
  6. **Evidence linkage was too weak.** The bundle validator only checked
     for a few keywords, not that it contained the *actual* checkpoint
     named by the handoff — a bundle embedding a different, independently
     valid checkpoint would have passed. `validate_bundle_content()` now
     requires the checkpoint's exact bytes verbatim as a substring.
     Additionally: checkpoint `STATUS` and `GIT_COMMIT` must each occur
     exactly once (a duplicate/contradictory value now fails); checkpoint
     `GIT_COMMIT` must be a full 40-character SHA; handoff `CURRENT_PHASE`
     must be a recognized phase token that matches the instruction's
     `AUTHORIZED_PHASE` exactly; handoff `WORKING_TREE` must state `clean`
     (cross-checked independently by the watcher's own `git status`); and
     every required `AGENT_HANDOFF.md` section heading from
     `orchestration/PROTOCOL.md` section 5 must literally be present.
  Also added 26 new/updated adversarial regression tests covering every
  category in the instruction's "Mandatory adversarial regression tests"
  list, including direct unit-level tests against `verify_target_commit()`,
  `verify_run_ancestry_and_attribution()`, and `verify_handoff()` with a
  narrowly-injected failing Git command (via a monkeypatched `_run_git`)
  around an otherwise-real temporary repository, per the instruction's own
  guidance on testing the fail-open-Git-error category precisely.
  `orchestration/PROTOCOL.md` sections 4, 5, and 7 and `docs/OPERATIONS.md`
  (including a new "Terminal trust-breach quarantine" recovery procedure)
  were updated accordingly.
- reason: MASTER_SPEC.md section 103's phase-gate discipline requires that
  no phase begin without explicit, verifiable orchestrator approval, and a
  watcher that can be made to auto-launch a self-authored instruction on a
  later tick -- or that treats a failed Git command as evidence of safety
  rather than as "unknown, therefore unsafe" -- does not actually provide
  that guarantee, regardless of how many individual checks it appears to
  pass. CORE-011 ("truth outranks impressive P&L") is why the remaining
  file-trust limitation is documented honestly rather than claimed away.
- requested_by: ARGUS ORCHESTRATOR, via
  `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` instruction
  `argus-watcher-remediation-003` (`STATUS: ACTIVE`,
  `TARGET_COMMIT: 34930bfa78cd7f667527b40f7d006c923c7c9ba6`,
  `AUTHORIZED_PHASE: 0`, `APPROVES_PHASE: NONE` — same-phase operational
  remediation, verified against `docs/BUILD_STATE.md` before this task
  began: `current_phase: 0`, `last_completed_phase: 0`,
  `awaiting_orchestrator_review: true`).
- impact: `scripts/argus_orchestrator_watch.py` substantially rewritten
  (new `QUARANTINED` state and `--reset-quarantine` CLI flag,
  `parse_canonical_utc_timestamp()`, fail-closed Git helpers
  (`git_commits_in_range`, `git_changed_paths`, `git_merges_in_range`,
  `git_status_porcelain`/`is_worktree_dirty` all `Optional`-returning),
  `git_trailer_values()` via `git interpret-trailers`, a tightened
  `verify_target_commit()`, a rewritten `verify_run_ancestry_and_attribution()`,
  tightened `validate_checkpoint_content()`/`validate_bundle_content()`, an
  expanded `verify_handoff()`, and a restructured `tick()` that checks
  instructions-file integrity first and unconditionally). Test suite grew
  from 51 to 74 tests, all passing; full repository suite 111 passed / 4
  skipped (pre-existing, unrelated Postgres-integration skips), 93%
  coverage on `src/argus` (unchanged), ruff clean, mypy clean.
  `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` was not modified. Phase 1
  remains unauthorized by this task.
- git_commit: 141af487fcfdff41d1597c19ea062139f5427f52 (this entry's own docs
  commit; the code commit it documents is 50e6d91b9cfeb40be14cf43a0b9f0b2c7582bd74
  — noted here as a drive-by fix, found while adding the Phase 1 entry
  below; this placeholder was never filled in during round 3 itself)

### 2026-08-31 — Phase 1: live chain data acquisition and deterministic canonical parsing (argus-phase-1-001)

- summary: Implemented Phase 1 in full per orchestrator instruction
  `argus-phase-1-001` (`APPROVES_PHASE: 0`, `AUTHORIZED_PHASE: 1`):
  Helius standard RPC/WebSocket adapter, DexScreener/GeckoTerminal/Jupiter
  adapters (quote/order-construction only, no signing), fast-path/truth-
  path reconciliation with per-wallet watermarks and `DEGRADED` gating,
  immutable `chain_events`/`swaps`/`wallet_stream_state` ledger, a new
  `clock_health_events` table with durable clock-anomaly detection wired
  into reconciliation gating, a deterministic generic balance-delta swap
  parser (all 7 classifications, 11 golden fixtures), a central P0–P6
  priority scheduler, provider usage/cost accounting with 70/85/95%
  warnings wired into every real adapter call, HTTP retry/backoff, and
  provider capability/history/usage probe CLI commands. Three real
  defects were found and fixed before or during this task, each with a
  regression test:
  1. **`TOKEN_CREATE` misclassification.** The original parser heuristic
     (`set(positives) & new_accounts`) misclassified an ordinary
     first-time "buy a token never held before" swap as `TOKEN_CREATE`,
     because a newly-seen mint with a nonzero received amount also
     satisfies "new account in positives". Fixed to require the new
     account's delta be exactly zero — only a pure
     empty-account-creation-plus-rent-payment pattern counts as
     `TOKEN_CREATE` now; a real swap into a new mint correctly falls
     through to `SWAP_SIMPLE`/`SWAP_COMPLEX`.
  2. **Provider-probe throttle silently `None`.** `_throttle()` queried
     `providers.<name>.conservative_rate_limit_per_sec`, but
     `config/providers.yaml` is merged *flat* by
     `argus.config.load_config` (top-level `helius:`, `dexscreener:`, ...
     keys), not nested under a `providers:` namespace. Every probe's
     `configured_throttle_per_sec` printed `None` as a result. Found by
     actually running `uv run argus providers probe` and noticing the
     field was always empty, not merely inferred from reading the code.
     Fixed and regression-tested; confirmed live post-fix
     (Helius=5.0/DexScreener=2.0/GeckoTerminal=1.0/Jupiter=2.0).
  3. **Adapter contract-validation gap.** Helius's `_rpc()` indexed
     `data["result"]` directly, which would raise an uncaught `KeyError`
     (not a deliberate, typed rejection) on a response missing both
     `result` and `error` — found while assessing acceptance criterion 14
     ("adapter contract validation rejects malformed provider
     responses") against the actual code rather than assuming it already
     held. Fixed to raise a typed `HeliusRpcError` naming the malformed
     response explicitly.
  Additionally implemented, beyond what a first pass had covered, after
  a self-assessment against the instruction's full 27-item acceptance
  list surfaced two real gaps that were architecture-scoped (not
  environmental) and squarely within Phase 1's own stated deliverables:
  durable clock-health/anomaly persistence wired into reconciliation's
  live-entry-eligibility gating (criterion 10), and HTTP retry/backoff
  with a configurable policy (criterion 15) wired into every provider
  adapter. Both were built, tested (unit + integration against real
  Postgres), and confirmed live in this sandbox before being reported as
  passing, rather than reported as gaps and left unbuilt.
- reason: CORE-011 ("truth outranks impressive P&L") and MASTER_SPEC.md
  section 17/19's explicit requirement that clock anomalies and transient
  provider failures be handled deterministically, not assumed away. A
  self-assessment against the instruction's own 27-item checklist — not
  just against what had already been built — is what surfaced the clock-
  anomaly and retry/backoff gaps; reporting them as `FAIL`/`NOT TESTED`
  without attempting to close them (when nothing about them was
  environmentally blocked) would have understated what Phase 1 actually
  requires. Acceptance criteria 1–2 (live Solana RPC/WebSocket) remain
  honestly `NOT TESTED` because they genuinely are blocked by this
  sandbox's missing `HELIUS_API_KEY` and lack of general internet egress
  (confirmed live via `argus providers probe`), exactly analogous to
  Phase 0's `PG17_COMPOSE_VALIDATION` deferral — not a gap this task could
  close by writing more code.
- requested_by: ARGUS ORCHESTRATOR, via
  `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` instruction
  `argus-phase-1-001` (`STATUS: ACTIVE`,
  `TARGET_COMMIT: 141af487fcfdff41d1597c19ea062139f5427f52`,
  `AUTHORIZED_PHASE: 1`, `APPROVES_PHASE: 0` — Phase 0 approval + Phase 1
  authorization in one instruction; verified against
  `docs/BUILD_STATE.md` before this task began per the instruction's own
  mandatory session-start steps).
- impact: New modules: `src/argus/domain/{chain_events,clock_health,swaps,
  wallet_stream_state}.py`, `src/argus/ingestion/*.py`,
  `src/argus/parsing/generic_parser.py`, `src/argus/providers/{credentials,
  probes,retry,scheduler,usage}.py`,
  `src/argus/providers/{dexscreener,geckoterminal,helius,jupiter}/client.py`,
  migration `0002` (chain_events, swaps, wallet_stream_state,
  clock_health_events + least-privilege grants). 61 new tests across
  `tests/unit`, `tests/integration`, `tests/golden`. Full suite: 204
  passed, 91% coverage, ruff clean, mypy clean. `orchestration/checkpoints/phase_1.md`
  and `orchestration/bundles/phase_1.txt` record the full 27-item
  PASS/FAIL/NOT TESTED disposition, including two honestly-disclosed,
  unclosed gaps that are architecture-scoped rather than environmental:
  no end-to-end stream-manager orchestration loop exists yet tying the
  WebSocket stream, reconciliation, and scheduler into one
  continuously-running process, and `StreamingUsageRecord`/
  `record_streaming()` has no live invocation site as a direct
  consequence. `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` was not
  modified; `docs/BUILD_STATE.md`'s `last_orchestrator_approved_phase`
  remains `0` — this task did not and could not self-approve Phase 1.
- git_commit: 28a88f74d28e70542050f5d5e8d9a9d139f26bb8 (code), docs commit
  SHA to follow (this entry is part of that docs commit and therefore
  cannot cite its own SHA in advance — see the handoff for the exact
  final commit).
