# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0023-phase-3-remediation-3
UTC_TIMESTAMP: 2026-09-01T09:58:00Z
CURRENT_COMMIT: PLACEHOLDER_FILLED_IN_SECOND_COMMIT
CURRENT_PHASE: 3
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-3-remediation-003
CHECKPOINT_PATH: orchestration/checkpoints/phase_3_remediation_3.md
BUNDLE_PATH: orchestration/bundles/phase_3_remediation_3.txt
TEST_STATUS: 27/27 unit `test_phase3_wallet_qualification.py` passed (unchanged); 79/79 unit `test_orchestrator_watch.py` passed (unchanged); 24/24 integration `test_wallet_acquisition.py` passed (was 6/6, +18 new focused P3-R2-round-3 tests); 14/14 integration `test_phase3_wallet_qualification.py` passed (unchanged); 17/17 integration `test_migrations.py` passed (unchanged, no new migration this round); 112/112 golden+replay+phase_1_5 passed (unchanged); 113/113 integration suite passed (was 95); full repository suite 777/777 passed (up from 759), 0 failed, 0 unexplained skipped; ruff clean; ruff format clean (220 files); mypy clean (112 source files); alembic head 0015 (unchanged); 12/12 real-chain fixtures ok; secret scan clean on this round's 7 changed files; migration-preservation regression tests re-run and passing -- ALL RAW COMMAND OUTPUT embedded verbatim in the paired bundle
WORKING_TREE: clean (verified via `git status --porcelain` before this commit)
ORCHESTRATOR_REVIEW_REQUIRED: whether this third, narrowly-scoped remediation (checkpoint sections B-M) genuinely closes the one remaining P3-R2 blocker named by `argus-phase-3-remediation-003`'s "Remaining blocker" section -- in particular whether the acquired-evidence binding is now exact and independently re-verified on load (not merely a richer summary), whether the fail-closed manifest decoding genuinely closes the reproduced `bool("false")` defect, and whether every non-HIGH-blessing gap scenario is honestly represented -- and whether the unchanged `PHASE_3_CANDIDATE_SAMPLE_BLOCKED` sample-report disposition remains appropriate. This session does not and cannot apply Phase 3 approval itself.

## Work completed

Executed orchestrator instruction `argus-phase-3-remediation-003` in
full: independently verified all safety gates (single instruction-only
commit `67c49a562af01e98a5797bc2010fe5c5e6216fa8` whose parent exactly
matches `TARGET_COMMIT` `ad21304a2f9fedd3c11a39a8d840ce577e0afe58` and
changes only `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`;
`AUTHORIZED_PHASE: 3` vs. `docs/BUILD_STATE.md`'s `current_phase: 3`
(never skip ahead); clean worktree; local HEAD equal to
freshly-fetched remote HEAD; Phase 3 awaiting review and not marked
approved) before any code was touched, then closed the one remaining
P3-R2 blocker named by the instruction's own "Remaining blocker" section,
in both of its directly related manifestations:

- **Manifestation 1** (persisted manifest was only a summary assertion):
  `AcquisitionManifest` now carries its own bound `run_id`/`wallet_id`/
  `wallet_address`/`observation_cutoff`/`algorithm_version` identity, a
  new `WalkStats` type for the wallet-address walk and every associated-
  token-account walk (status/known_gaps/pages_fetched/signatures_seen/
  transaction_fetch_failures/expected_oldest_slot/boundary_satisfied),
  and a new `acquired_evidence` tuple naming the exact signature/slot/
  chain_event_id/payload_hash/parser_outcome/parser_version/build_hash/
  derived_swap_id for every signature the run touched.
  `load_verified_acquisition_manifest` now independently re-verifies
  every genuine-evidence entry against the real, current
  `chain_events`/`swaps` rows before ever returning the manifest.
- **Manifestation 2** (`bool("false")` truthiness bug): `manifest_from_
  dict` now requires a genuine `isinstance(..., bool)` JSON boolean for
  `token_accounts_enumerated`, validates every status/outcome literal,
  and rejects duplicate account/evidence identities outright, raising a
  new `ManifestDecodeError` rather than coercing anything malformed.
- A parse exception, a payload-hash mismatch against a pre-existing
  event, a per-transaction fetch failure, and an already-known event
  with no derived swap evidence are all now explicit, honestly-named
  gaps that cap history completeness below HIGH -- never "blessed" by a
  successful walk or mere event existence, closing the exact scenario
  the audit named.
- `run_wallet_acquisition` also verifies each enumerated token account's
  on-chain `owner` genuinely matches the wallet being acquired, excluding
  any mismatch from coverage entirely (its transactions never walked or
  persisted).
- `expected_oldest_slot`/`boundary_satisfied` are now threaded as real
  typed data end-to-end (`historical_acquisition.AcquisitionResult` ->
  `WalkStats`), with a matching `--expected-oldest-slot` CLI option on
  `argus wallets acquire-history`.

18 new focused integration tests in `tests/integration/test_wallet_
acquisition.py` (6 -> 24) cover every required category from the
instruction's own "Required focused tests" list.

## Important findings

- No previously-closed finding was reopened or reworked, and no
  `HARDENING_BACKLOG` item was pulled into scope -- the instruction's own
  explicit narrow scope lock was followed throughout.
- No new migration was required this round (alembic head unchanged at
  `0015`) -- every change is software wiring within the existing
  `wallet_acquisition_runs.manifest` JSONB column, per the instruction's
  own "minimal append-only schema/model/CLI wiring needed for it."
- This sandbox's local PostgreSQL service was found stopped at the start
  of this round's validation (unrelated to any change made here, the
  same recurring environmental note as prior rounds). Restarted via
  `sudo service postgresql start`, non-destructive on the same local dev
  cluster used throughout this project.
- `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is unchanged -- still the
  orchestrator's `argus-phase-3-remediation-003` instruction, `STATUS:
  ACTIVE`. Phase 3 is NOT marked approved anywhere in this run's
  evidence; `last_orchestrator_approved_phase` is `2` (unchanged), never
  `3`.
- Both commits this run (the primary work commit and the follow-up
  commit-hash-fill-in commit) carry the sole final trailer paragraph
  `ARGUS-INSTRUCTION-ID: argus-phase-3-remediation-003`, with no
  paragraph after it, verified via `git interpret-trailers --parse`
  before push.

## Failures or limitations

- None new this round. The one finding named by `argus-phase-3-
  remediation-003`'s "Remaining blocker" section is closed in both of
  its manifestations.
- `LIVE_HELIUS_RPC_VALIDATION`/`LIVE_HELIUS_WSS_VALIDATION`/`PG17_
  COMPOSE_VALIDATION`/`BQ_PUBLIC_DATASET_ACCESS` remain `DEFERRED_
  ENVIRONMENTAL_CHECK`, unchanged, not reopened this round.

## Deferred checks

- All items under "Failures or limitations" above.

## Exact next action requested from orchestrator

Independently re-audit this third remediation
(`orchestration/checkpoints/phase_3_remediation_3.md`,
`orchestration/bundles/phase_3_remediation_3.txt`) against
`argus-phase-3-remediation-003`'s own "Remaining blocker" section and
its seven-part justification table. In particular: whether the acquired-
evidence binding is now genuinely exact and independently re-verified on
load (not merely a richer persisted summary still trusted at face
value); whether the fail-closed manifest decoding genuinely closes the
reproduced `bool("false")` defect and every other malformed-input case;
whether every non-HIGH-blessing gap scenario (parse failure, fetch
failure, unverified pre-existing event, payload-hash mismatch, account-
owner mismatch) is honestly represented and actually caps completeness;
and whether the unchanged `PHASE_3_CANDIDATE_SAMPLE_BLOCKED` disposition
remains acceptable (already accepted by all three prior instructions as
non-blocking). Only the orchestrator may apply Phase 3 approval; write
the next `ACTIVE` instruction into
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md` (`TARGET_COMMIT` pinned to
the exact commit named in this handoff) to do so, or to require further
remediation. Phase 4 remains forbidden until then. Until a new
instruction exists, the watcher (if running) takes no action beyond
logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** unchanged from prior handoffs — if you
cloned/fetched this branch before 2026-08-30T22:35 UTC, re-clone or
`git fetch --all && git reset --hard origin/claude/argus-folder-setup-77ahrk`
rather than merging/rebasing the old (pre-rewrite) history.
