# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0024-phase-3-remediation-4
UTC_TIMESTAMP: 2026-09-01T11:50:00Z
CURRENT_COMMIT: 135eede039a67843a30b11f93c3ac08508c84f19
CURRENT_PHASE: 3
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-3-remediation-004
CHECKPOINT_PATH: orchestration/checkpoints/phase_3_remediation_4.md
BUNDLE_PATH: orchestration/bundles/phase_3_remediation_4.txt
TEST_STATUS: 27/27 unit `test_phase3_wallet_qualification.py` passed (unchanged); 79/79 unit `test_orchestrator_watch.py` passed (unchanged); 36/36 integration `test_wallet_acquisition.py` passed (was 24/24, +12 new focused P3-R2-round-4 tests); 17/17 integration `test_phase3_wallet_qualification.py` passed (was 14/14, +3 new focused P3-R2a full-path tests); 17/17 integration `test_migrations.py` passed (unchanged, no new migration this round); 112/112 golden+replay+phase_1_5 passed (unchanged); 128/128 integration suite passed (was 113); full repository suite 792/792 passed (up from 777), 0 failed, 0 unexplained skipped; ruff clean; ruff format clean (221 files); mypy clean (112 source files); alembic head 0015 (unchanged); 12/12 real-chain fixtures ok; secret scan clean on this round's 5 changed files -- ALL RAW COMMAND OUTPUT embedded verbatim in the paired bundle
WORKING_TREE: clean (verified via `git status --porcelain` before this commit)
ORCHESTRATOR_REVIEW_REQUIRED: whether this fourth, consolidated remediation (checkpoint sections B-L) genuinely closes both named manifestations of `argus-phase-3-remediation-004`'s own seven-part justification table -- in particular whether `qualification_service.py`'s LIVE_ACQUISITION_WALK reconstruction is now genuinely bound to the verified run's own named evidence (not merely a richer persisted summary still trusted for the swap-selection query), whether the completed manifest/load validation genuinely closes all four demonstrated adversarial probes (missing-key default, PARTIAL/COMPLETE disagreement, COMPLETE-with-fault, null-derived-reference), and whether the unchanged `PHASE_3_CANDIDATE_SAMPLE_BLOCKED` sample-report disposition remains appropriate. This session does not and cannot apply Phase 3 approval itself.

## Work completed

Executed orchestrator instruction `argus-phase-3-remediation-004` in
full: independently verified all safety gates (single instruction-only
commit whose parent exactly matches `TARGET_COMMIT`
`fb2a3f7d2b75c526d06568ab3708ff85e1c1448d`; `AUTHORIZED_PHASE: 3` vs.
`docs/BUILD_STATE.md`'s `current_phase: 3` (never skip ahead); clean
worktree; local HEAD equal to freshly-fetched remote HEAD; Phase 3
awaiting review and not marked approved) before any code was touched,
then closed both named manifestations of the SAME P3-R2 requirement
named by the instruction's own seven-part justification table:

- **P3-R2a** (reconstruction not actually constrained to the verified
  run's evidence): `qualification_service.reconstruct_and_score_wallet`
  now loads the acquisition manifest FIRST for `LIVE_ACQUISITION_WALK`
  and restricts the swap query to exactly the manifest's own genuine
  (`PARSED`/`ALREADY_KNOWN_VERIFIED`) `derived_swap_id` set -- never
  every `Swap` row the wallet happens to have. A genuinely empty bound
  set still correctly falls through to the pre-existing zero-evidence
  `UNKNOWN` behavior. `STREAM_FORWARD_ONLY` is completely unchanged.
- **P3-R2b** (missing/null/conflicting manifest data still passed
  validation): `manifest_from_dict` now requires the `acquired_evidence`/
  `associated_token_accounts` keys to be explicitly present (an explicit
  empty array remains legitimate); every `PARSED`/`ALREADY_KNOWN_
  VERIFIED` entry must name a non-null, real-typed `derived_swap_id`/
  `parser_version`/`build_hash`; `wallet_walk_status` is reconciled
  against `wallet_walk.status` (and each account's own `status` against
  its own `walk.status`); a walk can no longer claim `COMPLETE` while
  also recording a transaction-fetch failure or an unsatisfied supplied
  boundary. `load_verified_acquisition_manifest` additionally verifies
  the manifest's own `wallet_address` against the caller's authoritative
  wallet row, and verifies the referenced swap's actual `parser_version`/
  `build_hash` match what the evidence entry claims. The producer's
  `ALREADY_KNOWN_VERIFIED` branch now records the pre-existing swap's
  real historical parser artifact instead of null metadata.

12 new focused integration tests in `tests/integration/test_wallet_
acquisition.py` (24 -> 36) and 3 new full producer-to-score-path
integration tests in `tests/integration/test_phase3_wallet_
qualification.py` (14 -> 17) cover every required category from the
instruction's own "Focused acceptance tests" list.

## Important findings

- No previously-closed finding was reopened or reworked, and no
  `HARDENING_BACKLOG` item was pulled into scope -- the instruction's own
  explicit narrow scope lock was followed throughout.
- No new migration was required this round (alembic head unchanged at
  `0015`) -- every change is software wiring within the existing
  `wallet_acquisition_runs.manifest` JSONB column and `qualification_
  service.py`'s query construction, per the instruction's own "No new
  schema is required unless the existing JSONB cannot represent the
  fields already specified."
- Fixing round 3's existing test fixtures (`_test_manifest`/
  `_add_closed_position_swaps` in `test_phase3_wallet_qualification.py`)
  to bind their manifests to the real evidence they actually insert was
  itself required by this round's own P3-R2a fix -- those fixtures
  previously relied on the exact "empty acquired_evidence still yields
  HIGH from directly-inserted swaps" shape the audit's probe 1/2 named as
  the defect. All 3 affected pre-existing tests were updated (never
  deleted or weakened) and continue to pass their original assertions.
- This sandbox's local PostgreSQL service was found stopped at the start
  of this round's validation (unrelated to any change made here, the
  same recurring environmental note as prior rounds). Restarted via
  `sudo service postgresql start`, non-destructive on the same local dev
  cluster used throughout this project.
- `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is unchanged -- still the
  orchestrator's `argus-phase-3-remediation-004` instruction, `STATUS:
  ACTIVE`. Phase 3 is NOT marked approved anywhere in this run's
  evidence; `last_orchestrator_approved_phase` is `2` (unchanged), never
  `3`.
- Both commits this run (the primary work commit and the follow-up
  commit-hash-fill-in commit) carry the sole final trailer paragraph
  `ARGUS-INSTRUCTION-ID: argus-phase-3-remediation-004`, with no
  paragraph after it, verified via `git interpret-trailers --parse`
  before push.

## Failures or limitations

- None new this round. Both manifestations named by
  `argus-phase-3-remediation-004`'s seven-part justification table are
  closed.
- `LIVE_HELIUS_RPC_VALIDATION`/`LIVE_HELIUS_WSS_VALIDATION`/`PG17_
  COMPOSE_VALIDATION`/`BQ_PUBLIC_DATASET_ACCESS` remain `DEFERRED_
  ENVIRONMENTAL_CHECK`, unchanged, not reopened this round.

## Deferred checks

- All items under "Failures or limitations" above.

## Exact next action requested from orchestrator

Independently re-audit this fourth remediation
(`orchestration/checkpoints/phase_3_remediation_4.md`,
`orchestration/bundles/phase_3_remediation_4.txt`) against
`argus-phase-3-remediation-004`'s own seven-part justification table. In
particular: whether `qualification_service.py`'s LIVE_ACQUISITION_WALK
reconstruction is now genuinely bound to the verified run's own named
derived-swap evidence at the actual reconstruction/scoring query, not
merely represented more richly in the persisted manifest; whether the
completed manifest/load validation genuinely closes every one of the
four demonstrated adversarial probes (missing-key silent default,
PARTIAL/COMPLETE status disagreement, COMPLETE co-occurring with a
recorded fault, a null genuine-outcome derived reference); and whether
the unchanged `PHASE_3_CANDIDATE_SAMPLE_BLOCKED` disposition remains
acceptable (already accepted by all four prior instructions as
non-blocking). Per this instruction's own explicit statement: "When
these two exact manifestations pass with regressions, approve Phase 3
and authorize immediate Phase 4; do not add optional hardening gates."
Only the orchestrator may apply that approval -- write the next `ACTIVE`
instruction into `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`
(`TARGET_COMMIT` pinned to the exact commit named in this handoff) to do
so, or to require further remediation. Phase 4 remains forbidden until
then. Until a new instruction exists, the watcher (if running) takes no
action beyond logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** unchanged from prior handoffs — if you
cloned/fetched this branch before 2026-08-30T22:35 UTC, re-clone or
`git fetch --all && git reset --hard origin/claude/argus-folder-setup-77ahrk`
rather than merging/rebasing the old (pre-rewrite) history.
