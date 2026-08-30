# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0002-history-rewrite
UTC_TIMESTAMP: 2026-08-30T22:35:00Z
CURRENT_COMMIT: (this commit — see `git log -1` / the COMMIT value returned alongside this handoff)
CURRENT_PHASE: 0
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: none (no instruction has been issued through GitHub yet — see orchestration/ORCHESTRATOR_INSTRUCTIONS.md, STATUS: NO_INSTRUCTION)
CHECKPOINT_PATH: orchestration/checkpoints/phase_0_remediation.md
BUNDLE_PATH: orchestration/bundles/phase_0_remediation.txt
TEST_STATUS: 41/41 passed, 93% coverage, ruff clean, mypy clean (re-verified after the history rewrite below; no application code behavior changed, only one now-redundant test assertion was removed)
WORKING_TREE: clean (verified via `git status --porcelain` before and after this commit)
ORCHESTRATOR_REVIEW_REQUIRED: PG17_COMPOSE_VALIDATION (deferred — see below); first instruction on how to proceed (Phase 1, further remediation, or something else)

## Work completed

1. **Phase 0 (Foundation)** built and tested per MASTER_SPEC.md's Phase 0
   BUILD/TEST/ACCEPTANCE list.
2. **Phase 0 remediation**, per orchestrator instruction: removed every
   hardcoded fallback database password from the codebase in favor of
   required environment variables that fail closed with a clear
   `MissingCredentialError`; corrected the checkpoint's `STATUS` field so it
   no longer claims an unconditional PASS while
   PostgreSQL-17-via-Docker-Compose remains unverified in this sandbox.
3. **Orchestration protocol bootstrap**: created `orchestration/`
   (`PROTOCOL.md`, this file, the orchestrator-owned
   `ORCHESTRATOR_INSTRUCTIONS.md` placeholder, `checkpoints/`, `bundles/`),
   and copied the Phase 0 (remediated) checkpoint and review bundle into it.
4. **Git history rewrite** (this round), per explicit human-operator
   request before making the repository public: a full-history scan
   (`git log --all -p`) found that four literal dev-only DB password
   fallback strings — removed from the working tree by step 2 above — were
   still present in earlier commits' history. These were never real
   credentials (only ever used against an ephemeral local Postgres inside
   this disposable sandbox), but the human operator asked for history to be
   rewritten to remove them rather than merely document them, given the
   repository is about to become public. `git-filter-repo` was used to
   scrub the four exact strings from every blob and commit message in
   history, then the branch was force-pushed. **This changed every commit
   hash on this branch.** Full details, the reasoning, and the old→new hash
   mapping are in `docs/DECISION_LOG.md`, entry "Git history rewrite to
   scrub inert dev-only password literals". All commit-hash references in
   this repository's own tracked files (`docs/BUILD_STATE.md`,
   `docs/DECISION_LOG.md`, `orchestration/checkpoints/`,
   `orchestration/bundles/`) were updated to match. No application code or
   ARGUS architecture changed as part of this.

## Important findings

- The full Phase 0 (remediated) findings are in
  `orchestration/checkpoints/phase_0_remediation.md` — read that file for
  the complete picture (it now carries a provenance note at the top
  explaining the post-rewrite hash it references). Summary: Phase 0
  acceptance criteria all PASS except one explicitly tracked deferral (next
  bullet).
- `PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK`
  (`docs/BUILD_STATE.md`): this implementation sandbox's egress policy
  blocks Docker Hub's image CDN, so `docker compose up postgres` (the real
  `postgres:17` image pinned in `compose.yaml`) has never actually been
  pulled or run. All Phase 0 functional verification was instead run
  against a substitute local PostgreSQL 16 server. Recorded as a deferral,
  not a pass.
- No hardcoded working credential of any kind remains anywhere in the
  repository's current tracked files, **and** a full-history re-scan after
  the rewrite confirms zero occurrences of the four scrubbed literal
  strings anywhere in git history (all branches, all commits).
- Before making this repository public: also confirmed no API keys,
  private keys/seed phrases, `.env` files, live wallet info, tokens/
  cookies, `/var/lib/argus/secrets/` file content, or personal data exist
  anywhere in git history — see `docs/DECISION_LOG.md` for the scope of
  what was checked.

## Failures or limitations

- `docker compose up -d postgres` cannot be exercised in this sandbox
  (Docker Hub CDN blocked at the egress proxy — 403). See
  `docs/BUILD_STATE.md` `known_blockers` for the full detail.

## Deferred checks

- `PG17_COMPOSE_VALIDATION`: run `make bootstrap && make up` (or
  equivalent) against the real `postgres:17` image on a host with normal
  Docker Hub access, and record the result in `docs/BUILD_STATE.md` and
  `docs/DECISION_LOG.md`. Required before live-readiness can be approved;
  not required to start Phase 1 (per explicit prior orchestrator
  instruction).

## Exact next action requested from orchestrator

1. Review `orchestration/checkpoints/phase_0_remediation.md` and
   `orchestration/bundles/phase_0_remediation.txt` (or the equivalent
   `docs/BUILD_STATE.md` / `docs/DECISION_LOG.md` entries) through GitHub.
2. Write an instruction into `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`
   (currently `STATUS: NO_INSTRUCTION`) authorizing the next piece of work —
   e.g. Phase 1, closing out `PG17_COMPOSE_VALIDATION`, or something else —
   with a `TARGET_COMMIT` pinned to the commit this handoff was pushed at.
3. Until an `ACTIVE` instruction exists, the implementation agent will not
   begin further ARGUS phase work (per `orchestration/PROTOCOL.md` section 6).

**Note on this branch's history:** if you (or any tool) cloned or fetched
this branch before 2026-08-30T22:35 UTC, your local copy has the
pre-rewrite commit hashes and will diverge from `origin`. Re-clone or
`git fetch --all && git reset --hard origin/claude/argus-folder-setup-77ahrk`
rather than trying to merge/rebase the old history onto the new.
