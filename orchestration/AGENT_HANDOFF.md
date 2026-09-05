# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0043-final-spec-recovery-002-clarification-002
UTC_TIMESTAMP: 2026-09-05T06:09:13Z
CURRENT_COMMIT: (this handoff's own commit -- see `git log -1`)
CURRENT_PHASE: 11
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-final-spec-recovery-002-clarification-002
WORKING_TREE: clean
CHECKPOINT_PATH: orchestration/checkpoints/final_spec_recovery.md
BUNDLE_PATH: orchestration/bundles/final_spec_recovery.txt
TEST_STATUS: R2-01 focused (canary authorization/evidence, 3 files) 38 passed; R2-02/R2-03 combined focused (shared Phase 9/10/11 fixture files) 51 passed; tests/unit+tests/golden+tests/replay 1354 passed; tests/integration (fresh isolated-database template) 426 passed; full suite from repo root (includes tests/phase_1_5) 1787 passed/0 failed, reconciled (1354+426+7=1787). Both new loader/matching-logic fixes were verified to FAIL against a deliberately-reverted pre-fix copy before being confirmed to pass against the real fix. ruff check/ruff format --check clean (467 files); `uv run mypy` (bare, `packages = ["argus"]` scope per `pyproject.toml`) clean (230 source files). Secret scan clean across all 14 changed/new files this round. Single Alembic head (0042, purely additive). PostgreSQL 17 remains FINAL_RECOVERY_ENVIRONMENT_BLOCKED -- reconfirmed, NOT retried this round (environment has not materially changed), per the clarification instruction's own explicit AUTHORIZED_ACTION -- LIVE_READY_SOFTWARE=false.
ORCHESTRATOR_REVIEW_REQUIRED: FINAL_ORIGINAL_SPEC_AUDIT -- all R2-01..R2-04 software requirements pass, including every literal clarification in BOTH `argus-final-spec-recovery-002-clarification-001` and `argus-final-spec-recovery-002-clarification-002` (see checkpoint sections B-CLARIFICATION-001/B-CLARIFICATION-002 for the full description of each fix). `argus-final-spec-recovery-002-clarification-002` is explicitly marked "the final clarification" of the already-frozen contract. The sole remaining blocker is PostgreSQL 17 environment access (section 8/8-CLARIFICATION-002 of the checkpoint), an external sandbox restriction rather than a software defect. No further gaps are disclosed this round: every item this clarification named is CLOSED.

## Work completed this round (`argus-final-spec-recovery-002-clarification-002`)

A second independent audit found the same three R2-01/R2-02/R2-03 items
(all previously marked PASS, including after clarification-001) still not
fully satisfying their own already-frozen wording, and issued three
further literal clarifications, explicitly marked "the final
clarification" of the already-frozen contract. R2-04/FSR-02/05/06/07/10/
11 were reconfirmed CLOSED/PASS (untouched); PG17 was reconfirmed
`FINAL_RECOVERY_ENVIRONMENT_BLOCKED` (not retried -- environment has not
materially changed, per the clarification's own explicit
`AUTHORIZED_ACTION`).

**R2-01 clarification (human-canary execution mode)**: the frozen
contract requires a future Phase 6.5 human canary to be executable
WITHOUT another code change, while `canary_passed` must remain
impossible for ORDINARY live operation before Phase 6.5 succeeds. At the
target commit, `build_live_risk_inputs_from_params_file` hardcoded
`canary_passed=False` unconditionally, making the very first canary
structurally impossible to ever attempt. New `src/argus/executor/
canary.py` (`validate_canary_authorization_file`) mirrors
`argus.executor.arm`'s own architecture: a NEW, separate external
authorization artifact, read-only, fails closed, bound to BOTH the
running build/config identity AND the specific `intent_id` being
authorized. New `phase65_canary_results` table (migration 0042, purely
additive) is the ONLY mechanism that can ever construct
`canary_passed=True` for ORDINARY execution -- written only after a
genuine on-chain `CONFIRMED` success under a validated canary
authorization. `main.py`'s `run_single_intent_if_configured` gained a new
`ARGUS_EXECUTOR_CANARY_AUTHORIZATION_PATH`-gated branch: absent
(repository default), `canary_passed` is read from the persisted
evidence table (`False` until a genuine canary has ever succeeded under
this exact identity); present, the authorization file is validated first
(fail-closed before the DB) and, only if valid, authorizes exactly one
attempt through the SAME `execute_intent_pipeline` every other path uses
-- every existing risk gate, identity check, arm validation, fencing,
attestation, signer isolation, and capital limit still applies unchanged.
19 new tests across 3 files (`test_r201_canary_authorization.py`,
+5 in `test_r201_single_intent_mode.py`, `test_r201_canary_evidence.py`).

**R2-02 clarification (entry-specialist source-evidence knowledge
time)**: the frozen contract requires entry-specialist provenance to
track the knowledge time of the actual SOURCE evidence used, never a
newly-created derived estimate's own write time.
`_compute_and_persist_counterfactual_alpha` previously forwarded
`CounterfactualAlphaEstimate.created_at` -- a DERIVED row's own physical
write time -- into `WalletSpecialistScore.source_knowledge_max_at` for
the entry contribution. Separately, Phase 9's two market-state loaders
enforced no knowledge-time (`created_at`) bound at all -- `load_nearest_
token_market_snapshot`'s own "nearest" selection had no upper bound on
either `observed_at` or `created_at`, so a later-backfilled snapshot with
an old `observed_at` could win the selection and silently contaminate a
historical reconstruction. Fixed: both loaders now require
`observed_at <= cutoff` AND `created_at <= cutoff`;
`_token_features_at`/`_forward_return_for_token` return the ACTUAL
snapshot row(s) used alongside their result, and the MAX of their real
`created_at` values is folded into each residual's entry -- never the
persisted estimate row's own `created_at`. `ALGORITHM_VERSION` bumped
`counterfactual_alpha_v4` -> `_v5` (no schema change; no durable v4 row
ever existed, so no additional invalidation row was seeded). New
`tests/integration/test_r202_entry_specialist_knowledge_time.py` (2
tests) extends the existing seven-step mutation recipe (the EXIT-
dimension test, left unmodified) to the ENTRY-SPECIALIST market-evidence
path specifically -- verified to FAIL against a deliberately-reverted
pre-fix copy of the loader before being confirmed to pass.

**R2-03 clarification (A/B entry timing vs strategy trigger)**: the
frozen contract requires Strategy A/B's entry timing to compare the
ACTUAL evidence time to the STRATEGY's own entry trigger time.
Clarification-001's own fix still compared the wrong two quantities: the
matching `ENTRY_DELAY` probe's real elapsed time against its OWN
configured target delay, never against `matched.entry.at` (the strategy's
own trigger). A fill could perfectly match its own configured target
delay while landing far from the actual strategy trigger, and would
previously have been silently accepted. Fixed:
`_select_own_entry_fill_if_contemporaneous` now takes `strategy_entry_at`,
derives the actual executable-entry-evidence timestamp from existing
Phase 4/5 timing evidence, and compares THAT to the strategy trigger --
the same versioned `Phase10RunConfig.contemporaneous_match_max_delta`
tolerance clarification-001 introduced. `ALGORITHM_VERSION` bumped
`synthetic_super_wallet_v4` -> `_v5` (same no-additional-invalidation
reasoning). `tests/unit/test_r203_phase10_executable_matching.py`
extended (24 tests, up from 22: 3 updated + 4 new) -- verified to FAIL
against a deliberately-reverted pre-fix copy before being confirmed to
pass.

No unnecessary version bumps: both `_v4 -> _v5` bumps above are genuine
algorithm-semantics changes, not cosmetic -- each is accompanied by the
explicit, documented determination that no durable non-test-database row
was ever computed under the superseded semantics this recovery round, so
no additional `contaminated_run_invalidations` row was seeded beyond the
ones prior rounds already added -- confirmed via a direct query of the
ordinary `argus` database (still 7 rows, unchanged).

## Base + clarification-001 work (prior handoffs, unaffected structurally this round)

Executed the complete bounded `argus-final-spec-recovery-002` remediation
(R2-01 through R2-04) and its clarification-001 round -- see the
checkpoint's own sections B/B-CLARIFICATION-001 for the full description:
the integrated executor pipeline seam + durable commit + real
single-intent wiring, persisted source-knowledge provenance + the full
7-step mutation recipe (EXIT dimension), Strategy A/B entry-fill timing
check + versioned absolute-delta tolerance, and the R2-04 hermetic
two-tier `isolated_database` test fixture (reconfirmed CLOSED, untouched
this round).

## Security-state confirmation

- Phase 6.5 (MAINNET CANARY) has NOT run and was not attempted.
- No mainnet transaction was signed or broadcast -- every test uses
  exclusively caller-scripted fakes or direct DB fixtures.
- No real operator key/seed was accessed, read, printed, logged, or
  exposed.
- No funded wallet was created; no arm file was created or modified.
- No real human Phase 6.5 canary authorization was ever created; every
  `CanaryAuthorizationResult`/authorization-file test uses synthetic,
  test-only identity/expiry values. `phase65_canary_results` received
  zero real rows this round.
- No capital default was changed from zero; `LIVE_ARMED=false` and
  `LIVE_CANARY_PASSED=false` throughout.
- No paid provider was enabled.
- No secret was requested; no credentials were used this round beyond
  the same pre-existing, previously-scrubbed dev-only `.env` literals the
  base round already disclosed, used solely to configure the same local
  ephemeral non-Docker PostgreSQL 16 cluster.
- Secret scan: clean across all 14 changed/new files this round.
- `LIVE_CANARY_PASSED=false`
- `LIVE_ARMED=false`
- `LIVE_READY_SOFTWARE=false` (PostgreSQL 17 remains environment-blocked,
  reconfirmed not retried this round per the clarification's own explicit
  instruction).
- This round did not modify `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`,
  did not self-approve, and did not perform Phase 6.5.

Full itemized evidence: checkpoint section N.

## Deferred / open items (explicitly disclosed, not hidden)

- PostgreSQL 17 validation remains blocked in this sandbox (unchanged
  disposition; not retried this round per the clarification's own
  explicit instruction). Needs either a sandbox with unblocked
  registry/PGDG egress, or an operator-run `make up && make test` against
  the repository's own `compose.yaml` with a real PostgreSQL 17 image.
- No large-N real-wallet Phase 10 v5/Phase 11 v4 research report was
  generated this round (out of this bounded remediation's own scope,
  unchanged from every prior round's own disclosure).

No other gaps are disclosed: every item this clarification-002 round
named is CLOSED, and the instruction itself is explicitly marked "the
final clarification" of the already-frozen contract.

## Exact next action requested from orchestrator

Per `orchestration/AUDITOR_POLICY.md`: audit this clarification round
(`argus-final-spec-recovery-002-clarification-002`) against
`orchestration/checkpoints/final_spec_recovery.md` and
`orchestration/bundles/final_spec_recovery.txt`. If satisfied that every
non-environment requirement is genuinely met, only the orchestrator/human
operator may apply final recovery approval -- write the next `ACTIVE`
instruction into `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`
(`TARGET_COMMIT` pinned to this handoff's own `CURRENT_COMMIT`) to do so,
to authorize PostgreSQL 17 validation as a follow-up scope, or to require
further remediation. This session does not and cannot apply final
recovery approval itself. Until a new instruction exists, the watcher (if
running) takes no action beyond logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** if you cloned/fetched this branch
before this handoff's own `UTC_TIMESTAMP`, re-fetch to pick up this
round's commits.
