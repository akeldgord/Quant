================ ARGUS ORCHESTRATOR CHECKPOINT ================

A. Identity

PROJECT: ARGUS
MASTER_SPEC_VERSION: 2.0
MASTER_SPEC_HASH: 41f7242c288feec709b1ed72e62c74a1dc5e3b3cd9ad01e9b6e28373d9d14011
PHASE: 11 (bounded final spec recovery remediation round 2, instruction `argus-final-spec-recovery-002`, clarified by `argus-final-spec-recovery-002-clarification-001` and `argus-final-spec-recovery-002-clarification-002`)
STATUS: PARTIAL
UTC_TIMESTAMP: 2026-09-05T06:09:13Z
GIT_COMMIT: (this checkpoint's own commit -- see `git log -1` after this file is committed)
CONFIG_HASH: see `Phase9RunConfig`/`Phase10RunConfig`/`Phase11RunConfig`/`GraphRunConfig` `.config_hash()` per run; `Phase10RunConfig`'s `contemporaneous_match_max_delta` (added clarification-001) is unchanged in shape this round -- see section B-CLARIFICATION-001
SCHEMA_VERSION: Alembic head `0042`

ORIGINAL_CONTAMINATED_BASE_COMMIT: ea77dd55b1e6be91b61b2f8b37e1d70449a3cb30
REMEDIATION_001_AUDITED_HEAD: 7cca4094d7672759b1023733a810f552f1109040
FINAL_REMEDIATION_002_IMPLEMENTATION_COMMIT: b791a4011d36c0519a8c5542918c6274eaee5c71
FINAL_REMEDIATION_002_EVIDENCE_COMMIT: 1117d4e (orchestration: FSR/R2 final evidence commit, prior round)
CLARIFICATION_001_INSTRUCTION_COMMIT: 72c69c0b7fcbe2497a8745f562cfd1c6480469fc (orchestration: clarify frozen recovery-002 acceptance semantics)
CLARIFICATION_001_IMPLEMENTATION_COMMIT: 140e9bd (Clarification-001: R2-01/R2-02/R2-03 code + tests)
CLARIFICATION_001_EVIDENCE_COMMIT: 8214099 (Clarification-001 final evidence: checkpoint, bundle, BUILD_STATE/DECISION_LOG, handoff)
CLARIFICATION_002_INSTRUCTION_COMMIT: 12e57a55da6a291d2e80e16c8725c0e6f54ae8e5 (orchestration: final clarification of frozen recovery acceptance)
CLARIFICATION_002_IMPLEMENTATION_COMMIT: 563ea11 (Clarification-002: R2-01 human-canary execution mode, R2-02 entry-specialist source-evidence knowledge time, R2-03 A/B strategy-trigger timing)
CLARIFICATION_002_EVIDENCE_COMMIT: (this checkpoint's own commit -- see `git log -1` after this file is committed)

B. What was built

Bounded remediation of the four root causes named in
`argus-final-spec-recovery-002` (R2-01..R2-04), per section 2's own
written justification:

- **R2-01**: one integrated executor pipeline seam
  (`src/argus/executor/pipeline.py`) chaining an already-authorized
  `ExecutionIntent` through singleton fencing -> risk/safety
  preconditions -> legal state-machine transitions -> a Jupiter unsigned
  order -> a REAL `UnsignedTransactionShape`, deserialized from actual
  transaction bytes via genuine chain simulation
  (`src/argus/executor/simulation.py`'s `SolanaTransactionSimulationClient`:
  real `getMultipleAccounts` + `simulateTransaction`, never trusting the
  provider's own quote) and an offline SPL Token account decoder
  (`src/argus/executor/token_account_codec.py`,
  `src/argus/executor/tx_deserialize.py`) -> `attest_transaction(...)
  .all_passed` required before signing -> an injected `Signer` -> an
  injected submission seam called exactly once per idempotency
  fingerprint -> durable signature + `SUBMITTED` persistence BEFORE
  confirmation polling -> `reconcile_submitted_fill` -> restart-safe
  (never resubmits once a signature is persisted) -> idempotent on
  terminal states. Stays inert by default: capital zero,
  `LIVE_ARMED=false`, `LIVE_CANARY_PASSED=false` throughout every test.
  Strict isolation preserved: no non-executor package imports
  `FileKeypairSigner`/`SolanaSubmissionClient` (existing AST boundary
  test, unaffected); only the executor deployment identity gets secret
  mounts (existing Compose `profiles: ["executor"]` gating, unaffected);
  no secret bytes anywhere in this round's new code or tests.

- **R2-02**: fixed the knowledge-time/provenance leak in Phase 9's
  specialist-score computation
  (`_compute_and_persist_specialist_scores`,
  `src/argus/counterfactual/service.py`) -- added
  `DirectionalEdge.created_at <= cutoff` and
  `ExpectedConfirmationEvent.created_at <= cutoff` filters alongside the
  existing `effective_at`/`as_of` bound (the existing
  `known_by_cutoff(*, created_at, effective_at, cutoff)` helper's own
  full contract, previously only half-applied at this call site).
  `ALGORITHM_VERSION` bumped `counterfactual_alpha_v2` ->
  `counterfactual_alpha_v3`; propagated to Phase 11
  (`order_flow_prediction_v2` -> `_v3`, `src/argus/prediction/service.py`)
  since its own dataset consumes Phase 9's specialist scores. Additive
  `contaminated_run_invalidations` rows (migrations `0038`/`0040`,
  `status="INVALID_FOR_EVALUATION"`) chain after FSR-13's own original
  v1->v2 rows for Phase 9/11 -- never delete/rewrite, never collapse to
  one-row-per-phase (`tests/integration/test_fsr13_contaminated_run_invalidations.py`
  updated to assert both chained rows independently).

- **R2-03**: Phase 10's forbidden universal
  `PRIMARY_EXECUTABLE_HORIZON="5m"` replaced with contemporaneous
  matching on BOTH sides of a trade
  (`src/argus/synthetic/service.py`):
  - Exit side: `_select_contemporaneous_reverse_outcome` picks whichever
    REAL `REVERSE_EXECUTABLE` probe's actual observed elapsed time
    (never its nominal label) is closest to the trade's own actual hold
    duration, within a `[0.5x, 2x]` contemporaneous band -- `None` (never
    a distant substitute) outside that band.
  - Entry side (Strategy C/D confirmation-anchored entries only):
    `_select_contemporaneous_entry_probe` picks whichever REAL
    `ENTRY_DELAY` probe's actual elapsed time is closest to the
    follower's own actual confirmation delay (same band), and the return
    is recomputed via `compute_executable_return` against THAT
    substituted entry -- never the leader's own realized fill
    (`opportunity.entry_fill`). `compute_executable_return`'s own
    mint/quantity validation is the safety net: since Phase 4 only ever
    sized a `REVERSE_EXECUTABLE` probe against the leader's own real fill
    quantity, a substituted entry that acquired a different quantity is
    honestly rejected as `FAILED`/`UNAVAILABLE`, never silently combined.
  - Hold-duration matching now uses one consistent reference frame (the
    leader's own real entry time, `_entry_lookup_at`) for BOTH the exit
    probe's own `actual_elapsed_seconds_from_first_seen` and the trade's
    own hold-duration computation -- previously the exit side compared a
    confirmation-relative duration against a leader-relative probe
    timestamp for Strategy C/D, a second, independent bug in the same
    family.
  - `argus/copyability/loaders.py`: additive `WalletOpportunity.
    entry_delay_probes` (every known-by-cutoff `ENTRY_DELAY` probe for a
    shadow intent, not only the one that became the real position) and
    `OpportunityReverseOutcome.reverse_quote` (the raw quote a
    precomputed result was built from, needed to recompute against a
    substituted entry) -- both additive; no existing Phase 5 M1-M6
    consumer reads either field, so this is not a behavior change for
    Phase 5 itself.
  - `ALGORITHM_VERSION` bumped to `synthetic_super_wallet_v3` (migration
    `0039`, chained after FSR-13's own v2 row).

- **R2-04**: `tests/integration/conftest.py`'s `isolated_database`
  fixture redesigned as a two-tier system -- one session-scoped
  `_migrated_template_database` (a single `alembic upgrade head` run for
  the whole session) and a function-scoped `isolated_database` that
  clones it per test via Postgres's own `CREATE DATABASE ... TEMPLATE`
  (a fast filesystem-level copy, no second migration run). Per-TEST (not
  per-module) isolation was required, not merely per-module, because
  several production queries in this codebase intentionally scan ALL
  matching rows in a table (Strategy A/B/C/D/E's own entry/exit loaders,
  `compute_and_persist_directional_edges`, etc.) -- confirmed empirically
  by running each originally-failing test alone (passed) vs. its whole
  module together (failed). Every integration test file that persists
  real domain data (not only the originally-named 21) now opts in via
  `pytestmark = pytest.mark.usefixtures("isolated_database")`, including
  `test_r201_executor_pipeline.py` (found during this round: its fixture
  relies on `solders.pubkey.Pubkey.new_unique()`, a deterministic
  per-process counter rather than a random generator, so re-running that
  file in a fresh process regenerated the SAME "unique" mints and
  collided with a leftover row from an earlier un-isolated run).

  A second, genuinely independent pre-existing bug was found and fixed
  during this round's first-ever real (Postgres-backed) execution of the
  full `tests/integration` suite: `rich.console.Console.print()`
  word-wraps text at console width by default, corrupting any CLI
  `--as-of`/report JSON output long enough to wrap -- silently breaking
  parsing of every long JSON report from `argus`'s own CLI. Fixed via
  `soft_wrap=True` on all 8 `console.print(json.dumps(...))` call sites
  in `src/argus/cli.py`. This was invisible in every prior remediation
  round because Postgres was never reachable for a real CLI-report
  integration test until this round's native-PostgreSQL-16 discovery
  (see PG17 disposition below).

B-CLARIFICATION-001. What was built (this round, `argus-final-spec-recovery-002-clarification-001`)

An independent audit found the prior round's R2-01/R2-02/R2-03 items (all
marked PASS above) not yet proven against their own already-frozen
wording, and issued three literal clarifications. R2-04 was reconfirmed
CLOSED/PASS (untouched); PG17 was reconfirmed
`FINAL_RECOVERY_ENVIRONMENT_BLOCKED` (not retried, per the instruction's
own explicit `AUTHORIZED_ACTION`).

- **R2-01 clarification (durable commit + real wiring)**: two defects in
  the previously-PASSing pipeline seam.
  1. `execute_intent_pipeline` (`src/argus/executor/pipeline.py`) now owns
     its own transaction boundary on every return path (`await
     session.commit()`), replacing an internal `session.flush()` that
     left the signature+`SUBMITTED` row visible only inside a still-open
     transaction a real process crash could roll back. Callers must no
     longer wrap it in their own `session.begin()` (SQLAlchemy raises
     `InvalidRequestError` if they do; verified empirically). The crash
     test (`test_r201_executor_pipeline.py`'s
     `crash_after_submission_restart_reconciles_same_signature_without_
     second_submit`) was rewritten to simulate a REAL crash boundary: a
     `_CrashingConfirmationProvider` raises immediately after the durable
     commit; a brand-new `verify_session` (a second, independent DB
     connection) confirms `STATE_SUBMITTED`+the fill row are visible
     BEFORE the simulated crash unwinds; a full restart with a fresh
     engine/sessionmaker and scripted-to-raise quote/simulation/signer
     callables reconciles the SAME signature without a second submission
     (`len(submit.calls) == 1`).
  2. `src/argus/executor/main.py` gained a narrow, config-gated
     "single-intent mode" (`ARGUS_EXECUTOR_SINGLE_INTENT_ID`/
     `ARGUS_EXECUTOR_INTENT_PARAMS_PATH` env vars) that actually invokes
     `execute_intent_pipeline()` with real production-capable adapters
     (`HeliusRpcClient`, `SolanaTransactionSimulationClient`,
     `JupiterClient`, `FileKeypairSigner`) -- closing the gap where
     `main`'s production identity had no real code path to the pipeline
     at all. Stays impossible to dispatch under repository defaults:
     `LiveRiskInputs.canary_passed` can never be constructed `True`
     anywhere in this codebase (no persisted Phase 6.5 canary-passed
     record exists), and `arm_result.armed` requires an external,
     human-authored, hash/expiry-validated arm file -- both hard risk
     gates `evaluate_live_risk`/`build_gates` already enforce, unchanged.
     Defense-in-depth: `_LIVE_RISK_INPUTS_REAL_ONLY_FIELDS` names every
     identity/arm/canary field that must always come from real,
     structurally-computed values, never an operator's params JSON, even
     if that file names those keys (a dedicated spoofing test proves
     they are silently ignored, not merged).
  - `src/argus/executor/confirmation.py`: deleted a redundant hand-written
    `SignatureStatus` Protocol (was causing a `list`-invariance mypy
    failure against the real `HeliusRpcClient`); typed directly against
    the shared `SignatureStatusInfo`.
  - Tests: `tests/unit/test_r201_single_intent_mode.py` (7 tests, new).

- **R2-02 clarification (persisted source-knowledge provenance)**: the
  prior round's `created_at <= cutoff` filters on `DirectionalEdge`/
  `ExpectedConfirmationEvent` were only "the source-selection half" --
  they say nothing about whether a RECONSTRUCTED score row's OWN
  eligibility (checked by consumers via `as_of == T`) is safe when the
  row was reconstructed at any later physical time (legitimate) but from
  sources not all knowable by `T` (not legitimate). Added
  `wallet_specialist_scores.source_knowledge_max_at` (migration `0041`,
  additive: nullable -> backfilled with each row's own `as_of` -> NOT
  NULL -> `CHECK (source_knowledge_max_at <= as_of)`) -- the MAX
  `created_at`/knowledge-time among every source row that actually
  contributed to a score, computed across all four specialist dimensions
  in `_compute_and_persist_specialist_scores`
  (`src/argus/counterfactual/service.py`), including a genuine
  independent pre-existing bug found and fixed in the same pass:
  `load_latest_exit_skill` (`src/argus/counterfactual/loaders.py`) was
  filtering exit-skill snapshots by `as_of <= cutoff` alone, missing the
  `created_at <= cutoff` half of `known_by_cutoff` that its own sibling
  consumer (`wallet_fingerprint_at`) already applied correctly to the
  SAME table. `load_specialist_scores_as_of`
  (`src/argus/synthetic/loaders.py`) and
  `load_discovery_effect_size_by_wallet`
  (`src/argus/prediction/loaders.py`) now additionally require
  `source_knowledge_max_at <= decision_time` -- never accepting a row
  solely because `as_of` matches. The new `CHECK` constraint makes the
  literal contaminated shape (a row claiming `as_of=T` with sources only
  knowable after `T`) structurally impossible to persist at all, a
  stronger guarantee than a read-side filter alone (proved directly via
  `test_schema_rejects_source_knowledge_after_as_of`, expecting
  `IntegrityError`). The mirror-image control
  (`test_loaders_accepts_row_reconstructed_later_with_valid_provenance`)
  proves a row physically written 30 days after `T` with valid
  provenance is still accepted -- "historical reconstruction performed
  later is allowed when its sources prove they were known by T" is never
  weakened to "the score row must have been created before T".
  `test_full_mutation_end_to_end_knowledge_time_provenance`
  (`tests/integration/test_r202_specialist_knowledge_time.py`) implements
  the full literal section-4.3 7-step recipe end-to-end against a real
  evidence source with genuine `<=`-based (not exact-equality) point-in-
  time re-selection (`wallet_score_snapshots`, reused unchanged by BOTH
  Phase 9's exit-specialist dimension and Phase 11's own wallet
  fingerprint feature): seed E1 known by T; reconstruct Phase 9 for T;
  capture the Phase 10 decision input
  (`load_specialist_scores_as_of`)/Phase 11 feature
  (`wallet_fingerprint_at`) at T; append E2 (effective before T, only
  knowable after T); rebuild Phase 9 for T again under a fresh invocation
  (a distinct `computed_at`); prove T's own decision input/feature remain
  BYTE-IDENTICAL; move the cutoff forward past E2's own knowledge time
  and prove it can then legitimately (and differently) affect the
  result. `ALGORITHM_VERSION` bumped `counterfactual_alpha_v3` -> `_v4`
  and `order_flow_prediction_v3` -> `_v4` -- genuine schema/algorithm
  evolution (no durable v3 row was ever computed under the old semantics
  in this recovery round), so no additional
  `contaminated_run_invalidations` entry was seeded beyond the existing
  v1->v2/v2->v3 rows (documented, not silently omitted).

- **R2-03 clarification (A/B actual-timing check + versioned tolerance)**:
  two more literal requirements not yet applied.
  1. Strategy A/B's entry price previously reused
     `opportunity.entry_fill` (the ONE realized fill Phase 4's real
     runtime happened to resolve, at whichever single configured delay)
     UNCONDITIONALLY -- "the original shadow entry fill may be used only
     when its actual entry timing is the strategy entry timing
     represented by the trigger" was not checked at all. New
     `_select_own_entry_fill_if_contemporaneous`
     (`src/argus/synthetic/service.py`) validates that the matching
     `ENTRY_DELAY` probe's REAL observed elapsed time did not drift, by
     more than the configured tolerance, from its own configured target
     delay (`entry_target_seconds`) before Strategy A/B's non-
     confirmation path trusts the loader's precomputed
     `reverse_outcome.result` -- a drifted or timing-unverifiable fill is
     honestly `FAILURE_NO_EXECUTABLE_EVIDENCE`, never a mark-price or
     distant-fill substitute
     (`test_strategy_a_drifted_entry_fill_timing_is_no_executable_evidence`,
     a real DB-backed fixture with a "0s"-labeled ENTRY_DELAY probe that
     did not actually terminate until 2 hours later).
  2. The `[0.5x, 2.0x]` multiplicative contemporaneous-matching band was
     hardcoded and unversioned. Replaced by
     `Phase10RunConfig.contemporaneous_match_max_delta` (an explicit
     `timedelta`, included in `config_hash()`) -- eligibility is now the
     ABSOLUTE delta between a candidate's real observed timing and the
     timing the trigger represents, `<=` the configured tolerance, with a
     deterministic `(distance, target_label)` tiebreak (never dependent
     on dict/DB iteration order). Governs all three contemporaneous
     decisions: `_select_contemporaneous_reverse_outcome`,
     `_select_contemporaneous_entry_probe`, and
     `_select_own_entry_fill_if_contemporaneous`. Not tuned to improve
     Phase 10's own backtest performance -- a principled 2-minute default
     (`argus.cli`), chosen for realistic operational jitter tolerance,
     never against this round's own results.
     `ALGORITHM_VERSION` bumped `synthetic_super_wallet_v3` -> `_v4` (no
     durable v3 row existed, so no additional invalidation entry was
     seeded, same reasoning as R2-02 above).
  - Tests: `tests/unit/test_r203_phase10_executable_matching.py` extended
    (22 tests, up from 12: absolute-delta boundary tests, deterministic-
    tiebreak tests for both selectors, 6 new `_select_own_entry_fill_if_
    contemporaneous` tests, a `config_hash()` versioning test);
    `tests/integration/test_phase10_synthetic_persistence_and_report.py`'s
    shared `_seed_shadow_fill_and_quote` fixture now also seeds a
    matching "0s" `ENTRY_DELAY` probe (previously only the
    `REVERSE_EXECUTABLE` probe was seeded, which would have made every
    existing Strategy A/B fixture fail the new gate) plus one new
    dedicated drift-rejection test.

No unnecessary version bumps: the three `_v3 -> _v4` bumps above are
genuine algorithm-semantics changes (source-knowledge provenance gating;
absolute-delta tolerance + A/B entry-fill timing gate), not cosmetic --
each is accompanied by the explicit, documented determination (in this
checkpoint and in the affected modules' own `ALGORITHM_VERSION` comments)
that no durable non-test-database row was ever computed under the
superseded semantics this recovery round, so no additional
`contaminated_run_invalidations` row was seeded for any of them beyond
the ones the prior `argus-final-spec-recovery-002` round already added
(migrations 0038/0039/0040) -- confirmed via a direct query of the
ordinary `argus` database (section G).

B-CLARIFICATION-002. What was built (this round, `argus-final-spec-recovery-002-clarification-002`)

A second independent audit found the same three R2-01/R2-02/R2-03 items
(all previously marked PASS above, including after Clarification-001)
still not fully satisfying their own already-frozen wording, and issued
three further literal clarifications, explicitly marked "the final
clarification" of the already-frozen contract. R2-04/FSR-02/05/06/07/10/
11 were reconfirmed CLOSED/PASS (untouched); PG17 was reconfirmed
`FINAL_RECOVERY_ENVIRONMENT_BLOCKED` (not retried, per the instruction's
own explicit `AUTHORIZED_ACTION`, since the environment has not
materially changed).

- **R2-01 clarification (human-canary execution mode)**: the frozen
  contract requires a future Phase 6.5 human canary to be executable
  WITHOUT another code change, while `canary_passed` must remain
  impossible for ORDINARY live operation before Phase 6.5 succeeds. At
  the target commit, `build_live_risk_inputs_from_params_file` hardcoded
  `canary_passed=False` unconditionally -- making the very first canary
  structurally impossible to ever attempt, not merely gated. Added:
  - `src/argus/executor/canary.py`: `validate_canary_authorization_file`
    -- a NEW, separate external authorization artifact (never the
    operator's single-intent params JSON, which can never supply
    `canary_passed`; never the existing arm file, which has no
    per-intent binding), mirroring `argus.executor.arm`'s own
    architecture exactly: read-only, fails closed on any problem, bound
    to BOTH the running build/config identity (`ApprovedIdentity`) AND
    the SPECIFIC `intent_id` being authorized (an authorization can
    never be silently reused for a different, later intent), with an
    explicit expiry.
  - `migrations/versions/0042_phase65_canary_result_evidence.py` +
    `src/argus/domain/phase65_canary_results.py`: an additive, new
    `phase65_canary_results` table -- the ONLY mechanism that can ever
    construct `canary_passed=True` for ORDINARY (non-canary-attempt)
    execution. A row is written ONLY after a genuine on-chain `CONFIRMED`
    success (`PipelineOutcome.status == "SUBMITTED_RESOLVED"` AND
    `outcome.intent.state == STATE_CONFIRMED` -- `SUBMITTED_RESOLVED`
    alone is insufficient, since `ReconciliationOutcome.resolved=True`
    also covers a resolved-but-FAILED on-chain transaction) for an intent
    run under a validated canary authorization -- never on
    rejection/failure/unresolved outcomes, and never through any other
    code path. `argus_executor` gets SELECT+INSERT only (no UPDATE --
    genuinely append-only/one-time-write).
  - `src/argus/executor/persistence.py`: `record_canary_result` (writes
    the evidence row) and `load_passed_canary_result_for_identity` (the
    read path ordinary execution consumes -- scoped to the EXACT running
    build/config identity; a pass recorded under a different identity
    never counts).
  - `src/argus/executor/main.py`: a new
    `ARGUS_EXECUTOR_CANARY_AUTHORIZATION_PATH` env var gates a canary-
    attempt branch in `run_single_intent_if_configured` -- when absent
    (repository default), `canary_passed` is read from the persisted
    evidence table (`False` until a genuine canary has ever succeeded
    under this exact identity); when present, the authorization file is
    validated FIRST (fail-closed before touching the DB) and, only if
    valid, `canary_passed=True` is constructed for that one attempt.
    Every other existing risk gate, build/config identity check, arm
    validation, singleton fencing, transaction attestation, signer
    isolation, and capital/size limit still applies unchanged to the
    canary-attempt path -- it reaches the exact same
    `execute_intent_pipeline`. On success only, the evidence row is
    recorded via `record_canary_result` after the pipeline call.
  - Tests: `tests/unit/test_r201_canary_authorization.py` (13 tests, the
    authorization-file validator in isolation), `tests/unit/
    test_r201_single_intent_mode.py` (+5 new tests: no-prior-canary-PASS
    rejection, valid-canary-authorization-still-subject-to-other-gates,
    missing/expired/wrong-intent authorization each fails closed before
    the DB is ever touched), `tests/integration/
    test_r201_canary_evidence.py` (6 new tests: evidence persists and is
    identity-scoped; a second record for the same intent is rejected
    -- migration 0042's own UNIQUE constraint; a genuine `CONFIRMED`
    pipeline outcome satisfies `main.py`'s exact success-gating condition
    and round-trips through the persistence functions; an attestation
    rejection and a submitted-but-unresolved outcome each never satisfy
    that gate).

- **R2-02 clarification (entry-specialist source-evidence knowledge
  time)**: the frozen contract requires entry-specialist provenance to
  track the knowledge time of the actual SOURCE evidence used, never a
  newly-created derived estimate's own write time.
  `_compute_and_persist_counterfactual_alpha`
  (`src/argus/counterfactual/service.py`) previously forwarded
  `CounterfactualAlphaEstimate.created_at` -- the physical creation time
  of a DERIVED row written during THIS replay -- into
  `WalletSpecialistScore.source_knowledge_max_at` for the entry
  contribution. Separately, the two Phase 9 market-state loaders
  (`load_token_market_snapshot_at_or_before`/
  `load_nearest_token_market_snapshot`,
  `src/argus/counterfactual/loaders.py`) enforced no `created_at`
  (knowledge-time) bound at all -- `load_nearest_token_market_snapshot`'s
  own "nearest" selection had no upper bound on either `observed_at` or
  `created_at`, so a later-backfilled `TokenMarketSnapshot` with an old
  `observed_at` could win the selection and silently contaminate a
  historical reconstruction. Fixed:
  - Both loaders now additionally require `observed_at <= cutoff` AND
    `created_at <= cutoff` (the same `known_by_cutoff` (M1) discipline
    every other Phase 9 source query already applies) before a row is
    ever a candidate.
  - `_token_features_at`/`_forward_return_for_token`
    (`src/argus/counterfactual/service.py`) now return the ACTUAL
    `TokenMarketSnapshot` row(s) they used alongside their result (the
    matching-feature snapshot; the entry+horizon forward-return
    snapshots), and `_compute_and_persist_counterfactual_alpha` folds the
    MAX of those real `created_at` values into each residual's entry in
    `entry_alpha_by_wallet_horizon` -- never the persisted estimate row's
    own `created_at`.
  - Two downstream call sites of the same loaders
    (`src/argus/prediction/loaders.py`'s `compute_raw_features`,
    `src/argus/synthetic/service.py`'s `_mark_prices_and_return`) were
    threaded with the correct cutoff (`entered_at` for the per-
    observation Phase 11 feature reconstruction; the run's own `cutoff`
    for Phase 10's descriptive-only mark-price path) so neither loses the
    new fail-closed behavior.
  - `ALGORITHM_VERSION` bumped `counterfactual_alpha_v4` -> `_v5` (no
    schema change required -- `source_knowledge_max_at` already exists,
    migration 0041 -- and no durable v4 row was ever computed under the
    superseded semantics this recovery round, so no additional
    `contaminated_run_invalidations` entry was seeded).
  - Tests: `tests/integration/test_r202_entry_specialist_knowledge_time.py`
    (NEW file, 2 tests) -- extends the existing seven-step mutation
    recipe (`test_r202_specialist_knowledge_time.py`'s own, EXIT-dimension
    only, left unmodified) to the ENTRY-SPECIALIST MARKET-EVIDENCE PATH
    specifically: seeds a matched wallet/control-token pair with real
    `TokenMarketSnapshot` evidence (E1) known by T; reconstructs Phase 9
    at T; captures the Phase 10 specialist decision input
    (`load_specialist_scores_as_of`) and the Phase 11 specialist-derived
    feature (`load_discovery_effect_size_by_wallet`, confirmed
    untouched by this entry-only mutation) at T; appends E2 (an
    additional wallet-token snapshot whose `observed_at` lands exactly on
    the forward-return horizon target -- closer than E1's, so it would
    WIN the nearest-snapshot selection if leaked -- but whose `created_at`
    is strictly after T, carrying a price that would double the wallet's
    forward return if it leaked); rebuilds Phase 9 at T again under a
    fresh `computed_at`; proves BOTH the persisted `WalletSpecialistScore`
    row AND a LIVE, unpersisted call to `_forward_return_for_token` at
    cutoff=T remain semantically unchanged (the live call is the genuine
    proof -- `get_or_create_wallet_specialist_score`'s own get-or-create
    idempotency means the persisted row alone cannot distinguish a fixed
    implementation from a buggy one at the SAME `as_of`, mirroring the
    sibling exit-dimension test's own reliance on `load_latest_exit_skill`
    as its live-call proof); moves the cutoff to T2 (past E2's own
    knowledge time) and proves the SAME live call now legitimately
    resolves to E2's value, with `source_knowledge_max_at == E2.created_at`.
    A second, narrower unit-style test
    (`test_entry_specialist_nearest_snapshot_ignores_future_knowledge_row_directly`)
    proves the identical loader-level contract directly, without any
    Phase 9 orchestration. Both tests were verified to FAIL against a
    deliberately-reverted (pre-fix) copy of the loader before being
    confirmed to pass against the real fix, proving they are genuine
    regression tests, not vacuously true.

- **R2-03 clarification (A/B entry timing vs strategy trigger)**: the
  frozen contract requires Strategy A/B's entry timing to compare the
  ACTUAL evidence time to the STRATEGY's own entry trigger time.
  Clarification-001's own fix
  (`_select_own_entry_fill_if_contemporaneous`,
  `src/argus/synthetic/service.py`) still compared the wrong two
  quantities: the matching `ENTRY_DELAY` probe's real elapsed time
  against its OWN configured target delay (`entry_target_seconds`) -- a
  purely internal consistency check proving only that the fill executed
  near its own probe's target, never that it is contemporaneous with
  `matched.entry.at` (the strategy's own entry trigger). A fill could
  perfectly match its own configured target delay while landing far from
  the actual strategy trigger, and would previously have been silently
  accepted. Fixed: the function now takes `strategy_entry_at` (i.e.
  `matched.entry.at`), derives the actual executable-entry-evidence
  timestamp from existing Phase 4/5 timing evidence
  (`opportunity.first_seen_at + actual_elapsed_seconds_from_first_seen`),
  and compares THAT to `strategy_entry_at` -- `abs(actual_entry_evidence_at
  - strategy_entry_at) <= max_delta_seconds`, the same versioned
  `Phase10RunConfig.contemporaneous_match_max_delta` tolerance
  Clarification-001 introduced. `ALGORITHM_VERSION` bumped
  `synthetic_super_wallet_v4` -> `_v5` (same no-additional-invalidation
  reasoning as R2-02 above -- no schema change, no durable v4 row ever
  computed under the superseded semantics). Deterministic nearest/
  tiebreak coverage for "more than one eligible real entry observation"
  is intentionally NOT duplicated in this function: Strategy A/B's own
  entry price deliberately stays bound to the ONE realized
  `opportunity.entry_fill` (never substituting a DIFFERENT `ENTRY_DELAY`
  probe's own hypothetical fill, which would silently change the
  reported trade's actual bought quantity/mint for a strategy whose
  entire premise is "the same wallet's REAL realized buy" -- and would
  require recomputing `compute_executable_return` against a different
  `reverse_quote` basis, a materially different design this clarification
  does not require); the existing tiebreak test for the sibling
  confirmation-entry function
  (`test_entry_probe_tiebreak_is_deterministic_by_target_label`,
  `_select_contemporaneous_entry_probe`, unaffected) already covers that
  requirement for the family. Tests:
  `tests/unit/test_r203_phase10_executable_matching.py` extended: the 3
  existing `test_own_entry_fill_*` tests updated for the new
  `strategy_entry_at` parameter; +4 new tests (within-tolerance-of-
  strategy-trigger eligible; far-from-trigger ineligible even when
  near-its-own-target; the exact perfectly-matches-own-target-but-far-
  from-trigger scenario the clarification names; no-mark-price-fallback
  when nothing qualifies). Verified to FAIL against a deliberately-
  reverted (pre-fix) copy of the function before being confirmed to pass
  against the real fix.

One consideration explicitly disclosed, not silently omitted: `docs/
BUILD_STATE.md`/`docs/DECISION_LOG.md` and this checkpoint are the only
files this round modifies outside `src`/`tests`/`migrations` --
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md` was read but never modified,
per the instruction's own explicit "Do not modify this file."

C. Files changed (base round, `argus-final-spec-recovery-002`)

```
git diff --stat 7cca409..b791a40 -- . ':!orchestration/ORCHESTRATOR_INSTRUCTIONS.md'
```
42 files changed, 3326 insertions(+), 51 deletions(-)

```
git diff --name-status 7cca409..b791a40 -- . ':!orchestration/ORCHESTRATOR_INSTRUCTIONS.md'
```
```
A	migrations/versions/0038_r2_02_phase9_specialist_knowledge_time.py
A	migrations/versions/0039_r2_03_phase10_executable_matching.py
A	migrations/versions/0040_r2_02_phase11_specialist_propagation.py
M	src/argus/cli.py
M	src/argus/copyability/loaders.py
M	src/argus/counterfactual/service.py
A	src/argus/executor/pipeline.py
A	src/argus/executor/simulation.py
A	src/argus/executor/token_account_codec.py
A	src/argus/executor/tx_deserialize.py
M	src/argus/prediction/service.py
M	src/argus/synthetic/loaders.py
M	src/argus/synthetic/service.py
M	tests/integration/conftest.py
M	tests/integration/test_daily_report.py
M	tests/integration/test_daily_report_remediation.py
M	tests/integration/test_fsr02_confirmation.py
M	tests/integration/test_fsr13_contaminated_run_invalidations.py
M	tests/integration/test_phase10_synthetic_persistence_and_report.py
M	tests/integration/test_phase11_prediction_persistence_and_report.py
M	tests/integration/test_phase1_schema.py
M	tests/integration/test_phase2_discovery.py
M	tests/integration/test_phase3_wallet_qualification.py
M	tests/integration/test_phase4_recovery_2.py
M	tests/integration/test_phase5_persistence_and_report.py
M	tests/integration/test_phase6_persistence_and_concurrency.py
M	tests/integration/test_phase7_graph_persistence_and_report.py
M	tests/integration/test_phase8_convergence_persistence_and_report.py
M	tests/integration/test_phase9_counterfactual_persistence_and_report.py
M	tests/integration/test_provider_usage_model.py
A	tests/integration/test_r201_executor_pipeline.py
A	tests/integration/test_r202_specialist_knowledge_time.py
M	tests/integration/test_reconciliation_sql.py
M	tests/integration/test_shadow_phase4.py
M	tests/integration/test_shadow_phase4_concurrency_remediation.py
M	tests/integration/test_shadow_phase4_remediation_observation.py
M	tests/integration/test_shadow_quote_jobs_provider_remediation.py
M	tests/integration/test_wallet_acquisition.py
A	tests/unit/test_r201_compose_secret_isolation.py
A	tests/unit/test_r201_token_account_codec.py
A	tests/unit/test_r201_tx_deserialize.py
A	tests/unit/test_r203_phase10_executable_matching.py
```

C-CLARIFICATION-001. Files changed (this round, `argus-final-spec-recovery-002-clarification-001`)

```
git diff --stat 1117d4e -- . ':!orchestration/ORCHESTRATOR_INSTRUCTIONS.md'
```
18 files changed, 1506 insertions(+), 192 deletions(-), plus 2 new untracked files (below)

```
git diff --name-status 1117d4e -- . ':!orchestration/ORCHESTRATOR_INSTRUCTIONS.md'
```
```
M	src/argus/cli.py
M	src/argus/counterfactual/loaders.py
M	src/argus/counterfactual/persistence.py
M	src/argus/counterfactual/service.py
M	src/argus/domain/wallet_specialist_scores.py
M	src/argus/executor/confirmation.py
M	src/argus/executor/main.py
M	src/argus/executor/pipeline.py
M	src/argus/prediction/loaders.py
M	src/argus/prediction/service.py
M	src/argus/synthetic/loaders.py
M	src/argus/synthetic/service.py
M	tests/integration/test_fsr13_contaminated_run_invalidations.py
M	tests/integration/test_phase10_synthetic_persistence_and_report.py
M	tests/integration/test_phase11_prediction_persistence_and_report.py
M	tests/integration/test_r201_executor_pipeline.py
M	tests/integration/test_r202_specialist_knowledge_time.py
M	tests/unit/test_r203_phase10_executable_matching.py
```
Plus 2 new files (untracked before this round's own commit):
```
A	migrations/versions/0041_r2_02_specialist_score_source_knowledge_provenance.py
A	tests/unit/test_r201_single_intent_mode.py
```

C-CLARIFICATION-002. Files changed (this round, `argus-final-spec-recovery-002-clarification-002`)

```
git diff --stat 8214099 -- . ':!orchestration/ORCHESTRATOR_INSTRUCTIONS.md'
```
8 files changed, 714 insertions(+), 130 deletions(-), plus 6 new untracked files (below)

```
git diff --name-status 8214099 -- . ':!orchestration/ORCHESTRATOR_INSTRUCTIONS.md'
```
```
M	src/argus/counterfactual/loaders.py
M	src/argus/counterfactual/service.py
M	src/argus/executor/main.py
M	src/argus/executor/persistence.py
M	src/argus/prediction/loaders.py
M	src/argus/synthetic/service.py
M	tests/unit/test_r201_single_intent_mode.py
M	tests/unit/test_r203_phase10_executable_matching.py
```
Plus 6 new files (untracked before this round's own commit):
```
A	migrations/versions/0042_phase65_canary_result_evidence.py
A	src/argus/domain/phase65_canary_results.py
A	src/argus/executor/canary.py
A	tests/integration/test_r201_canary_evidence.py
A	tests/integration/test_r202_entry_specialist_knowledge_time.py
A	tests/unit/test_r201_canary_authorization.py
```

D. Commands actually run (exact, in order of relevance)

- `uv run pytest tests/integration/test_r201_executor_pipeline.py tests/unit/test_r201_token_account_codec.py tests/unit/test_r201_tx_deserialize.py tests/unit/test_r201_compose_secret_isolation.py -q` -> `19 passed`
- `uv run pytest tests/integration/test_r202_specialist_knowledge_time.py -q` -> `2 passed`
- `uv run pytest tests/unit/test_r203_phase10_executable_matching.py tests/integration/test_phase10_synthetic_persistence_and_report.py -q` -> `18 passed`
- `uv run pytest tests/unit tests/golden tests/replay -q` -> `1316 passed`
- `uv run pytest tests/integration -q` (fresh isolated-database template, run 1 of 2) -> `414 passed`
- `uv run pytest tests/integration -q` (run 2 of 2, no manual cleanup between runs) -> `414 passed`
- `uv run ruff check .` -> `All checks passed!`
- `uv run ruff format --check .` -> `458 files already formatted`
- `uv run mypy src/` -> `Success: no issues found in 228 source files`
- `uv run alembic heads` -> `0040 (head)` (single head)
- `uv run argus fixtures validate-real-chain` -> `12/12 ok`
- `uv lock --check` -> `Resolved 64 packages` (no changes; lockfile consistent)
- Secret scan: `grep -InE "AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(api[_-]?key|secret|password|token)[\"']?\s*[:=]\s*[\"'][A-Za-z0-9/+_=-]{12,}[\"']"` across all 42 changed/new files this round -> no matches (clean), matching this project's own established changed-file secret-scan convention.
- Post-run DB-pollution check (`SELECT count(*) FROM <table>` for every `public` table in the ordinary `argus` database via the admin connection, after both fresh integration runs) -> every table empty except `alembic_version` (1 row, expected) and `contaminated_run_invalidations` (7 rows -- the migration-seeded FSR-13/R2-02/R2-03 registry itself, not test-run data): **no test data was written to the ordinary developer `argus` database.**

D-CLARIFICATION-001. Commands actually run this round (`argus-final-spec-recovery-002-clarification-001`)

- `uv run pytest tests/integration/test_r201_executor_pipeline.py tests/unit/test_r201_token_account_codec.py tests/unit/test_r201_tx_deserialize.py tests/unit/test_r201_compose_secret_isolation.py tests/unit/test_r201_single_intent_mode.py -q` -> `26 passed`
- `uv run pytest tests/integration/test_r202_specialist_knowledge_time.py -q` -> `5 passed`
- `uv run pytest tests/unit/test_r203_phase10_executable_matching.py tests/integration/test_phase10_synthetic_persistence_and_report.py -q` -> `29 passed`
- `uv run pytest tests/unit tests/golden tests/replay -q` -> `1333 passed`
- `uv run pytest tests/integration -q` -> `418 passed` (one genuine pre-existing-test-assumption failure found and fixed mid-round: `test_registry_names_all_four_contaminated_phases_with_reason` compared a fixed historical migration-0040 value against the LIVE `ALGORITHM_VERSION` import, which broke once this round's own v3->v4 bump landed -- corrected to the literal historical value `"order_flow_prediction_v3"`, since `superseded_by_algorithm_version` records what a row was ACTUALLY superseded by at migration-write time, never "whatever the current version happens to be" going forward)
- `uv run ruff check .` -> `All checks passed!`
- `uv run ruff format --check .` -> `461 files already formatted`
- `uv run mypy src/` -> `Success: no issues found in 228 source files`
- `uv run alembic upgrade head` -> applied `0040 -> 0041` cleanly; `uv run alembic current` -> `0041 (head)`
- `SELECT count(*) FROM contaminated_run_invalidations` (ordinary `argus` database, post-validation) -> `7` (unchanged from the base round -- this round's three `_v3 -> _v4` bumps genuinely required no new invalidation row; every other table verified empty)
- `sha256sum MASTER_SPEC.md` -> `41f7242c288feec709b1ed72e62c74a1dc5e3b3cd9ad01e9b6e28373d9d14011` (unchanged)

Historical note (base round, now superseded): the R2-02 mutation-test
recipe's full literal section-4.3 end-to-end Phase 10/11-decision-level
assertions were **not** built as one combined test in THIS base round --
only the Phase-9-mechanism-level tests above (2 tests) plus one
pre-existing Strategy-B decision-level regression test were written. This
gap is CLOSED by Clarification-001 (section B-CLARIFICATION-001 above):
`test_full_mutation_end_to_end_knowledge_time_provenance` now implements
the full literal 7-step recipe end-to-end.

D-CLARIFICATION-002. Commands actually run this round (`argus-final-spec-recovery-002-clarification-002`)

- `uv run pytest tests/integration/test_r201_executor_pipeline.py tests/integration/test_r201_canary_evidence.py tests/unit/test_r201_single_intent_mode.py tests/unit/test_r201_canary_authorization.py -q` -> `38 passed`
- `uv run pytest tests/unit/test_r203_phase10_executable_matching.py tests/integration/test_phase10_synthetic_persistence_and_report.py tests/integration/test_phase9_counterfactual_persistence_and_report.py tests/integration/test_r202_specialist_knowledge_time.py tests/integration/test_r202_entry_specialist_knowledge_time.py tests/integration/test_phase11_prediction_persistence_and_report.py -q` -> `51 passed`
- `uv run pytest tests/unit tests/golden tests/replay -q` -> `1354 passed`
- `uv run pytest tests/integration -q` (fresh isolated-database template) -> `426 passed`
- `uv run pytest -q` (full suite from repo root -- includes `tests/phase_1_5`, 7 tests, not covered by the two split invocations above) -> `1787 passed` (`1354 + 426 + 7 = 1787`, reconciled)
- `uv run ruff check .` -> `All checks passed!`
- `uv run ruff format --check .` -> `467 files already formatted` (461 + 6 new files this round)
- `uv run mypy` (bare, per `Makefile`'s own `typecheck` target -- scopes to `packages = ["argus"]`, i.e. `src/argus` only, per `pyproject.toml`'s `[tool.mypy]`) -> `Success: no issues found in 230 source files` (228 + 2 new src files this round: `canary.py`, `phase65_canary_results.py`)
- `uv run alembic upgrade head` -> applied `0041 -> 0042` cleanly; `uv run alembic current`/`uv run alembic heads` -> `0042 (head)` (single head)
- `uv run argus fixtures validate-real-chain` -> `12/12 ok` (unchanged, unaffected by this round)
- `uv lock --check` -> `Resolved 64 packages` (no changes; lockfile consistent)
- Secret scan: grep-based credential-pattern scan (AWS-style keys, PEM/OpenSSH private-key headers, `password`/`api_key`/`secret`= literals) plus a base58 keypair-length scan (64-88 char base58-alphabet runs), across the full diff of all 8 changed files and the raw content of all 6 new files this round -> the only matches were `helius_api_key="fake-helius-key"` (a test fixture stand-in, clearly fake per its own name, in `tests/unit/test_r201_single_intent_mode.py`) -- clean, matching this project's own established changed-file secret-scan convention.
- `SELECT count(*) FROM contaminated_run_invalidations` (ordinary `argus` database) -> `7` (unchanged -- this round's two `_v4 -> _v5` bumps genuinely required no new invalidation row, same reasoning as clarification-001's own `_v3 -> _v4` bumps)
- `sha256sum MASTER_SPEC.md` -> `41f7242c288feec709b1ed72e62c74a1dc5e3b3cd9ad01e9b6e28373d9d14011` (unchanged)
- Regression-proof discipline for both new loader/matching-logic fixes (R2-02, R2-03): each fix was temporarily reverted to its pre-fix form and the new tests were re-run, confirming they FAIL against the bug and PASS against the real fix -- proving the new tests are genuine regression tests, not vacuously true assertions. The reverted copies were restored and re-verified clean (`ruff`/`mypy`) before this evidence was written.

E. Test results

pytest (base round, `argus-final-spec-recovery-002`):
- R2-01 focused: 19 passed, 0 failed, 0 skipped
- R2-02 focused: 2 passed, 0 failed, 0 skipped
- R2-03 focused: 18 passed, 0 failed, 0 skipped
- tests/unit + tests/golden + tests/replay: 1316 passed, 0 failed, 0 skipped
- tests/integration (run 1, fresh isolated-database template): 414 passed, 0 failed, 0 skipped
- tests/integration (run 2, no manual cleanup): 414 passed, 0 failed, 0 skipped
- coverage: not separately instrumented this round (unchanged from prior rounds; no coverage regression tooling exists in this repository)
ruff: `ruff check .` all checks passed; `ruff format --check .` 458 files already formatted (0 reformatted)
mypy: `mypy src/` success, 0 issues, 228 source files

pytest (this round, `argus-final-spec-recovery-002-clarification-001`):
- R2-01 focused (+ 7 new single-intent-mode tests): 26 passed, 0 failed, 0 skipped
- R2-02 focused (+ 3 new tests: schema-rejection, loader-acceptance, full 7-step mutation): 5 passed, 0 failed, 0 skipped
- R2-03 focused (+ 10 new tests: absolute-delta boundaries, deterministic tiebreaks, own-entry-fill gating x6, config-hash versioning, 1 new integration drift test): 29 passed, 0 failed, 0 skipped
- tests/unit + tests/golden + tests/replay: 1333 passed, 0 failed, 0 skipped
- tests/integration (single full run, fresh isolated-database template): 418 passed, 0 failed, 0 skipped (one genuine pre-existing test-assumption bug found and fixed mid-round -- see section D-CLARIFICATION-001)
ruff: `ruff check .` all checks passed; `ruff format --check .` 461 files already formatted (0 reformatted)
mypy: `mypy src/` success, 0 issues, 228 source files

pytest (this round, `argus-final-spec-recovery-002-clarification-002`):
- R2-01 focused (canary authorization/evidence, +19 net new tests across 3 files): 38 passed, 0 failed, 0 skipped
- R2-02/R2-03 combined focused (entry-specialist knowledge-time + A/B strategy-trigger timing, sharing the same Phase 9/10/11 fixture files): 51 passed, 0 failed, 0 skipped
- tests/unit + tests/golden + tests/replay: 1354 passed, 0 failed, 0 skipped
- tests/integration (single full run, fresh isolated-database template): 426 passed, 0 failed, 0 skipped
- Full suite from repo root (`uv run pytest -q`, includes `tests/phase_1_5`'s 7 tests not covered by the two split invocations above): 1787 passed, 0 failed, 0 skipped
ruff: `ruff check .` all checks passed; `ruff format --check .` 467 files already formatted (0 reformatted)
mypy: `uv run mypy` (bare, `packages = ["argus"]` scope) success, 0 issues, 230 source files

F. Acceptance criteria

See section H (full FSR-01..16 + R2-01..04 matrix) below for the complete
mapping. Section-level summary (post-clarification-002, the final
clarification round):

- R2-01 (integrated executor pipeline seam + durable commit + real wiring + human-canary execution mode): PASS
- R2-02 (knowledge-time/provenance semantics + persisted source-knowledge provenance + entry-specialist source-evidence knowledge time): PASS (every disclosed gap CLOSED)
- R2-03 (Phase 10 strategy-time executable matching + A/B timing check + versioned tolerance + strategy-trigger comparison basis): PASS
- R2-04 (hermetic integration testing): PASS (reconfirmed CLOSED, untouched across both clarification rounds)
- PG17 disposition (section 8): ENVIRONMENT_BLOCKED (not PASS, not FAIL; reconfirmed, not retried this round -- environment has not materially changed, per the clarification's own explicit instruction)

G. Database/data sanity

- `argus` (ordinary developer database, post-validation, this round): `alembic_version` 1 row; `contaminated_run_invalidations` 7 rows (UNCHANGED from every prior round -- this round's two `_v4 -> _v5` algorithm-version bumps genuinely required no new invalidation row, confirmed by direct query). Five other tables (`chain_events`/`swaps`/`commitment_observations`/`parse_attempts`/`wallet_stream_state`) carry a small number of rows (4/4/4/4/1) pre-dating this round -- real Phase 1 development-era CLI/ingest artifacts from earlier in this project's lifetime, not test-run pollution: every test this round (and this repository's entire `tests/integration` suite) exclusively uses the per-test `isolated_database` fixture, never the ordinary `argus` database's write path; `argus fixtures validate-real-chain` (the one CLI command run directly against this database this round) is a pure filesystem/hash-check with no DB access at all (verified by reading its implementation). No new pollution was introduced by this round's own work.
- Isolated per-test databases (`isolated_database` fixture, unchanged this round): created and dropped automatically per test function; none left behind after the full-suite run.
- Alembic head: `0042` (single head, confirmed via `alembic current`/`alembic heads`; migration 0042 added this round -- purely additive: a brand-new `phase65_canary_results` table, no changes to any existing table/column/grant).

H. Full FSR-01..16 + R2-01..04 matrix

| Item | Description | Status | Evidence |
|---|---|---|---|
| FSR-01 | Production-capable executor process boundary | PASS (prior round, unaffected this round) | `orchestration/checkpoints/fsr15_16_final_recovery_acceptance_matrix.md` |
| FSR-02 | Real chain-based fill reconciliation | PASS (prior round, unaffected this round) | ibid. |
| FSR-03 | PostgreSQL 17 environment validation | **ENVIRONMENT_BLOCKED** | See section 8 below (fresh bounded attempt this round, same disposition) |
| FSR-04 | Canonical knowledge-cutoff invariant | PASS (prior round) | `argus.copyability.identity.known_by_cutoff` |
| FSR-05 | Phase 7 forward-information-after-leader | PASS (prior round) | ibid. |
| FSR-06 | Phase 8 point-in-time convergence + outcome comparisons | PASS (prior round) | ibid. |
| FSR-07 | Phase 9 predation inputs complete | PASS (prior round) | ibid. |
| FSR-08 | Phase 10 executable-return backtest | PASS (prior round; R2-03 this round fixes a defect discovered IN this mechanism -- see R2-03 row) | ibid. |
| FSR-09/10/11/12 | Phase 11 causal dataset rebuild | PASS (prior round; propagated to v4 by clarification-001, unaffected by clarification-002's v4->v5 bumps -- Phase 11 does not consume `counterfactual_alpha`/`synthetic_super_wallet` version strings directly) | ibid. |
| FSR-13 | Version/invalidate contaminated Phase 8-11 derived runs | PASS (prior round; extended with chained v2->v3 rows; both clarification rounds' own v3->v4 and v4->v5 bumps required no additional row -- see section B-CLARIFICATION-002/G) | migrations 0038/0039/0040/0041/0042; `test_fsr13_contaminated_run_invalidations.py` |
| FSR-14 | Retroactive Phase 7-11 recovery checkpoints | PASS (prior round) | `orchestration/checkpoints/phase_{7,8,9,10,11}_final_recovery.md` |
| FSR-15 | Full regression suite, 0 failed | **PASS** (base round closed the prior 21-failure gap; clarification-001 re-confirmed 0 failed with one genuine pre-existing test-assumption fix; clarification-002 re-confirms 0 failed again after all new work -- section D-CLARIFICATION-002) | Section E; full suite from repo root 1787 passed/0 failed |
| FSR-16 | Final security state, build state, single handoff | PASS (this checkpoint + updated `docs/BUILD_STATE.md`/`docs/DECISION_LOG.md` + updated `orchestration/AGENT_HANDOFF.md`) | This document, sections N/O |
| R2-01 | Integrated executor pipeline seam | **PASS** (base round PASS; clarification-001 closed the durable-commit gap + added real single-intent wiring; clarification-002 additionally adds the human-canary execution mode -- the ONLY way `canary_passed=True` can ever be constructed) | `src/argus/executor/pipeline.py` (self-committing transaction boundary) + `main.py` (single-intent mode + canary-attempt branch) + `canary.py` (NEW: authorization-file validator) + `phase65_canary_results.py`/migration 0042 (NEW: canary-evidence table) + `persistence.py` (`record_canary_result`/`load_passed_canary_result_for_identity`); `test_r201_executor_pipeline.py` (7) + `test_r201_single_intent_mode.py` (12) + `test_r201_canary_authorization.py` (13, NEW) + `test_r201_canary_evidence.py` (6, NEW) + `test_r201_compose_secret_isolation.py` (4) + `test_r201_token_account_codec.py`/`test_r201_tx_deserialize.py` (8) = 38 tests currently combined-run |
| R2-02 | Knowledge-time/provenance semantics | **PASS** (base round's core mechanism PASS; clarification-001 closed the persisted-provenance gap and the full literal mutation-recipe gap for the EXIT dimension; clarification-002 closes the same gap for the ENTRY-SPECIALIST market-evidence path specifically) | `src/argus/counterfactual/service.py` (`counterfactual_alpha_v5`); `src/argus/counterfactual/loaders.py` (both Phase 9 market-state loaders now enforce `created_at`/`observed_at` <= cutoff); `wallet_specialist_scores.source_knowledge_max_at` (migration 0041, unchanged); migrations 0038/0040; `test_r202_specialist_knowledge_time.py` (5, EXIT-dimension mutation recipe, untouched) + `test_r202_entry_specialist_knowledge_time.py` (2, NEW: ENTRY-dimension mutation recipe + direct loader proof, each verified to fail against a reverted pre-fix copy) |
| R2-03 | Phase 10 strategy-time executable matching | **PASS** (base round PASS; clarification-001 closed the A/B entry-fill-timing gap and replaced the hardcoded ratio with a versioned absolute-delta tolerance; clarification-002 fixes the comparison basis itself -- actual evidence timestamp vs. the STRATEGY's own trigger time, never the fill's own configured target delay) | `src/argus/synthetic/service.py` (`synthetic_super_wallet_v5`; `_select_own_entry_fill_if_contemporaneous` now takes `strategy_entry_at`); `test_r203_phase10_executable_matching.py` (24 unit tests, up from 22, 3 updated + 4 new, verified to fail against a reverted pre-fix copy) + `test_phase10_synthetic_persistence_and_report.py` (7, unaffected) = 51 tests currently combined-run with the R2-02 files above |
| R2-04 | Hermetic integration test infrastructure | **PASS** (reconfirmed CLOSED across both clarification rounds, untouched) | `tests/integration/conftest.py` two-tier fixture; section D/E/G evidence |

8-CLARIFICATION-002. PostgreSQL 17 disposition (this round)

Not retried this round, per the clarification instruction's own explicit
`AUTHORIZED_ACTION` ("must NOT be retried unless the environment has
materially changed"): this sandbox's egress policy has not changed since
the immediately-prior round's fresh bounded attempt (section 8 below).
Disposition remains `FINAL_RECOVERY_ENVIRONMENT_BLOCKED`, unchanged.
PostgreSQL 16 (native `postgresql-16` apt package) continues to serve as
this repository's own real, non-Docker validation path for every test in
this round. `LIVE_READY_SOFTWARE` remains `false`.

8. PostgreSQL 17 disposition (prior round's own fresh bounded attempt, unretried this round)

Attempted exactly once via two independent genuine paths, per the
instruction's own "canonical path or another genuine PG17 instance"
wording:

- `timeout 25 docker pull postgres:17-alpine` -> the Docker daemon itself
  now starts and is reachable in this sandbox (`docker ps` succeeds,
  unlike the prior round's finding) -- but the registry pull fails with
  an explicit `403 Forbidden` from `production.cloudfront.docker.com`
  (Docker Hub's own CDN), a genuine egress-policy denial, not a
  connection failure.
- `curl -sS -o /dev/null -w "%{http_code}\n" https://apt.postgresql.org/pub/repos/apt/`
  -> `CONNECT tunnel failed, response 403` -- the PGDG apt host is
  independently policy-blocked by the same egress proxy.

Per `/root/.ccr/README.md`'s own explicit guidance, an organization
policy denial is never retried. Disposition: `FINAL_RECOVERY_ENVIRONMENT_BLOCKED`
(unchanged from the prior round's finding, though the SPECIFIC blocking
mechanism differs: this round confirms the Docker daemon itself is no
longer the blocker -- registry/package-host egress policy is). Every
PG17-required test in FSR-03's own matrix remains not executed on genuine
PostgreSQL 17. PostgreSQL 16 (native `postgresql-16` apt package, used
for every real Postgres-backed test this whole round) is explicitly never
claimed as a substitute PASS. `LIVE_READY_SOFTWARE` is therefore `false`
per section 9's own requirement (PG17 did not pass).

I. Data quality warnings

None beyond what prior rounds already disclosed (`orchestration/checkpoints/
fsr15_16_final_recovery_acceptance_matrix.md`). This round touched no
ingestion/provider code.

J. Sample outputs

`uv run argus fixtures validate-real-chain` (unchanged 12/12 real-chain
fixtures, unaffected by this round -- included only as this round's own
required-test-matrix item 8 evidence):
```
real_mainnet_dca_close_dual_asset_transfer_in: ok - ok
real_mainnet_failed_nft_sale: ok - ok
real_mainnet_multi_hop_swap: ok - ok
real_mainnet_orca_close_position_multi_account: ok - ok
real_mainnet_partial_sell: ok - ok
real_mainnet_sol_to_token_swap: ok - ok
real_mainnet_sol_transfer_multi: ok - ok
real_mainnet_sol_transfer_received: ok - ok
real_mainnet_sol_transfer_single: ok - ok
real_mainnet_token_to_sol_swap: ok - ok
real_mainnet_token_to_usdc_swap: ok - ok
real_mainnet_usdc_transfer: ok - ok
```

Phase 10/11 v3 sample result: this round's own fixture-driven integration
tests (`test_strategy_a_uses_real_executable_return_not_mark_price`,
`test_strategy_b_discovery_filter_uses_entrys_own_decision_time`, the 12
`test_r203_phase10_executable_matching.py` unit tests) exercise the v3
matching logic directly and pass; no large-N real-wallet Phase 10/11 v3
research report was generated this round (out of this bounded
remediation's own scope -- the four R2-01..04 code fixes plus their
required tests, not a fresh research run). Re-running Phase 10/11 under
the new `_v3` algorithm versions against real historical evidence, if
desired, is future work for whoever holds `ORCHESTRATOR_REVIEW_REQUIRED`
next.

K. Architectural deviations

NONE (base round). R2-03's entry-side fix (`OpportunityEntryProbe`,
`WalletOpportunity.entry_delay_probes`, `OpportunityReverseOutcome.
reverse_quote`) extends `argus/copyability/loaders.py` (a Phase 5 shared
module) additively -- new fields only, no existing field's meaning or any
existing Phase 5 M1-M6 consumer's behavior changed. This was necessary
(not optional) to satisfy the instruction's own explicit R2-03
requirement that Strategy C/D "never reuse the leader's earlier fill" for
its own entry price, which the previous fix (opportunity-lookup only) did
not yet satisfy -- disclosed here rather than silently expanded past
scope.

K-CLARIFICATION-001. Architectural deviations (this round)

NONE beyond what the clarification itself explicitly required and named:
- `wallet_specialist_scores.source_knowledge_max_at` (migration 0041) is
  additive (nullable -> backfilled -> NOT NULL -> CHECK), never
  destructive; two existing test files
  (`test_phase10_synthetic_persistence_and_report.py`,
  `test_phase11_prediction_persistence_and_report.py`) needed a one-field
  addition to their own direct `WalletSpecialistScore(...)` constructions
  to satisfy the new NOT NULL column.
- `Phase10RunConfig.contemporaneous_match_max_delta` is an additive new
  field, included in `config_hash()` as the clarification's own section
  4.2 explicitly requires ("must be VERSIONED CONFIGURATION").
- The shared `_seed_shadow_fill_and_quote` integration-test fixture
  (`test_phase10_synthetic_persistence_and_report.py`) needed a new
  `ENTRY_DELAY` probe seeded alongside its existing `REVERSE_EXECUTABLE`
  probe -- without it, EVERY existing Strategy A/B fixture using that
  helper would have failed the new section-4.1 timing gate (no timing
  evidence at all is honestly `FAILURE_NO_EXECUTABLE_EVIDENCE`, not a
  silent pass). This is the new gate working as intended on
  under-specified fixtures, not a design deviation.
- One genuine pre-existing test bug, unrelated to this round's own code
  changes, was found and fixed:
  `test_registry_names_all_four_contaminated_phases_with_reason`
  (`test_fsr13_contaminated_run_invalidations.py`) compared a fixed
  historical migration-0040 value against the LIVE `ALGORITHM_VERSION`
  import, an implicit assumption that broke once this round's own
  `order_flow_prediction_v3 -> v4` bump landed -- corrected to the
  literal historical value the migration actually recorded (see section
  D-CLARIFICATION-001).

K-CLARIFICATION-002. Architectural deviations (this round)

NONE beyond what the clarification itself explicitly required and named:
- `phase65_canary_results` (migration 0042) is a brand-new, additive
  table -- no change to any existing table/column/grant. Its
  least-privilege grant (`argus_executor`: SELECT+INSERT only, no UPDATE)
  is intentionally tighter than migration 0024's own blanket
  SELECT/INSERT/UPDATE pattern, since this table is genuinely
  append-only/one-time-write by design (an intent is terminal once
  `CONFIRMED`), not a stylistic inconsistency.
- `src/argus/executor/canary.py` is a wholly new, small module mirroring
  `argus.executor.arm`'s own existing architecture (the clarification's
  own explicit instruction: "use the existing human authorization/arm/
  control-plane architecture where possible") -- not a new pattern.
- No existing risk gate, build/config identity check, arm validation,
  singleton-fencing, transaction-attestation, signer-isolation, or
  capital/size-limit code path was weakened, bypassed, or made
  conditional on the new canary-attempt branch -- the canary-attempt path
  reaches the exact same `execute_intent_pipeline` every other path does.
- No real canary was run or authorized this round (the clarification's
  own explicit instruction: "No real canary is authorized or run in this
  remediation") -- every test uses a synthetic, test-only
  `CanaryAuthorizationResult`/authorization file.

L. ORCHESTRATOR_REVIEW_REQUIRED

FINAL_ORIGINAL_SPEC_AUDIT -- all R2-01..R2-04 software requirements pass,
including every literal clarification in BOTH
`argus-final-spec-recovery-002-clarification-001` (durable commit + real
single-intent wiring; persisted source-knowledge provenance + the full
literal 7-step mutation recipe; Strategy A/B entry-fill timing check +
versioned absolute-delta tolerance) AND
`argus-final-spec-recovery-002-clarification-002`, explicitly marked "the
final clarification" of the already-frozen contract (human-canary
execution mode -- the only way `canary_passed=True` can ever be
constructed, and only under explicit human Phase 6.5 authorization
evidence; entry-specialist source-evidence knowledge time, closing the
one remaining mutation-recipe hole in the ENTRY-SPECIALIST market-
evidence path; Strategy A/B entry timing compared against the actual
strategy trigger time, not a fill's own configured target delay). The
sole remaining blocker is PG17 environment access
(`FINAL_RECOVERY_ENVIRONMENT_BLOCKED`, section 8/8-CLARIFICATION-002,
reconfirmed not retried this round -- the environment has not materially
changed, per the clarification's own explicit instruction), which is an
external sandbox restriction, not a software defect. This session cannot
and does not apply final recovery approval itself; per the
clarification's own explicit instruction, this session does not modify
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md`, does not self-approve, and
does not perform Phase 6.5.

M. Known bugs / debt (explicit)

- The R2-02 mutation-test recipe gap disclosed by the base round was
  CLOSED for the EXIT dimension by clarification-001
  (`test_full_mutation_end_to_end_knowledge_time_provenance`) and is now
  ALSO closed for the ENTRY-SPECIALIST market-evidence path by
  clarification-002
  (`test_entry_specialist_market_evidence_mutation_end_to_end`, section
  B-CLARIFICATION-002) -- no longer open debt in either dimension.
- No large-N real-wallet Phase 10 v5/Phase 11 v4 research report was
  generated this round (section J) -- out of this bounded remediation's
  scope, unchanged from every prior round's own disclosure.
- PG17 remains environment-blocked (section 8/8-CLARIFICATION-002,
  reconfirmed not retried this round); PostgreSQL 16 continues to serve
  as this repository's own real, non-Docker validation path.
- No gaps remain disclosed by this clarification-002 round: every item
  the instruction named is CLOSED, and the instruction itself is
  explicitly marked "the final clarification" of the already-frozen
  contract -- no further clarification is expected.

N. Security state

- Phase 6.5 (MAINNET CANARY) has NOT run and was not attempted.
- No mainnet transaction was signed or broadcast; every R2-01 pipeline
  test uses a caller-scripted fake `Signer`/submission callable
  (`FakeSigner`, `RaisingSigner`, `_RecordingSubmit`), never a real key or
  real RPC call.
- No real operator key/seed was accessed, read, printed, logged, or
  exposed.
- No funded wallet was created; no arm file was created or modified.
- No capital default was changed from zero; `LIVE_ARMED=false` and
  `LIVE_CANARY_PASSED=false` throughout every test this round.
- No paid provider was enabled.
- No secret was requested; the only credentials used were this
  repository's own pre-existing, previously-scrubbed-into-history dev-only
  `.env` literals (`argus_admin_dev_only` etc.), used solely to configure
  a local, ephemeral, non-Docker PostgreSQL 16 cluster's own role
  passwords to match -- never transmitted anywhere, never modified.
- No real human Phase 6.5 canary authorization was ever created; every
  `CanaryAuthorizationResult`/authorization-file test uses synthetic,
  test-only identity/expiry values. `phase65_canary_results` (migration
  0042) received zero real rows this round -- only test-database rows,
  dropped with each isolated per-test database.
- Secret scan (section D): clean across all 42 changed/new files (base
  round), clean across all 20 changed/new files (clarification-001,
  section D-CLARIFICATION-001), and clean across all 14 changed/new files
  this round (clarification-002, section D-CLARIFICATION-002) -- the
  only match anywhere was a test fixture stand-in string
  (`helius_api_key="fake-helius-key"`), clearly fake per its own name.
- `LIVE_CANARY_PASSED=false`
- `LIVE_ARMED=false`
- `LIVE_READY_SOFTWARE=false` -- PG17 (section 8/8-CLARIFICATION-002)
  remains `FINAL_RECOVERY_ENVIRONMENT_BLOCKED`, so per section 9's own
  explicit rule this cannot be `true` regardless of every other
  requirement passing.

This clarification round performed no new database provisioning/teardown
operations beyond the ordinary per-test `isolated_database` fixture
(unchanged); the ordinary `argus` developer database was not dropped or
recreated this round. A direct query confirmed no new pollution was
introduced by this round's own work (section G) -- the small number of
rows present in five Phase 1 tables pre-date this round and are real
development-era artifacts, not test-run residue.

One disclosed operational note (not a security issue, but honestly
recorded, carried forward unchanged from the prior clarification round):
before that round's real-Postgres validation work, the pre-existing
`argus` database in this sandbox's native PostgreSQL 16 cluster was
dropped and recreated fresh after discovering test-run pollution from
early (pre-R2-04-fix) test runs. No real evidence lives in that ephemeral
local database -- this repository's own established discipline keeps all
real evidence in git commits and checkpoints.

O. Next specified phase

Phase 6.5 (MAINNET CANARY) remains the only phase not started, and
remains explicitly and permanently human-only -- this session does not
and will not perform it. `current_phase`/`last_completed_phase` in
`docs/BUILD_STATE.md` remain 11, unchanged: this round corrected/hardened
prior phases' own work rather than advancing MASTER_SPEC phase numbering.

**STOP FOR INDEPENDENT FINAL AUDIT**

================ END ARGUS CHECKPOINT =========================
