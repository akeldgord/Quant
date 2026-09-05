================ ARGUS ORCHESTRATOR CHECKPOINT ================

A. Identity

PROJECT: ARGUS
MASTER_SPEC_VERSION: 2.0
MASTER_SPEC_HASH: 41f7242c288feec709b1ed72e62c74a1dc5e3b3cd9ad01e9b6e28373d9d14011
PHASE: 11 (bounded final spec recovery remediation round 2, instruction `argus-final-spec-recovery-002`, clarified by `argus-final-spec-recovery-002-clarification-001`)
STATUS: PARTIAL
UTC_TIMESTAMP: 2026-09-05T03:10:00Z
GIT_COMMIT: (this checkpoint's own commit -- see `git log -1` after this file is committed)
CONFIG_HASH: see `Phase9RunConfig`/`Phase10RunConfig`/`Phase11RunConfig`/`GraphRunConfig` `.config_hash()` per run; `Phase10RunConfig` gained one new field this round (`contemporaneous_match_max_delta`, included in its own `config_hash()`) -- see section B-CLARIFICATION-001
SCHEMA_VERSION: Alembic head `0041`

ORIGINAL_CONTAMINATED_BASE_COMMIT: ea77dd55b1e6be91b61b2f8b37e1d70449a3cb30
REMEDIATION_001_AUDITED_HEAD: 7cca4094d7672759b1023733a810f552f1109040
FINAL_REMEDIATION_002_IMPLEMENTATION_COMMIT: b791a4011d36c0519a8c5542918c6274eaee5c71
FINAL_REMEDIATION_002_EVIDENCE_COMMIT: 1117d4e (orchestration: FSR/R2 final evidence commit, prior round)
CLARIFICATION_001_INSTRUCTION_COMMIT: 72c69c0b7fcbe2497a8745f562cfd1c6480469fc (orchestration: clarify frozen recovery-002 acceptance semantics)
CLARIFICATION_001_IMPLEMENTATION_COMMIT: 140e9bd (Clarification-001: R2-01/R2-02/R2-03 code + tests)
CLARIFICATION_001_EVIDENCE_COMMIT: (this checkpoint's own commit -- see `git log -1` after this file is committed)

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

F. Acceptance criteria

See section H (full FSR-01..16 + R2-01..04 matrix) below for the complete
mapping. Section-level summary (post-clarification):

- R2-01 (integrated executor pipeline seam + durable commit + real wiring): PASS
- R2-02 (knowledge-time/provenance semantics + persisted source-knowledge provenance): PASS (full literal mutation-recipe gap CLOSED this round)
- R2-03 (Phase 10 strategy-time executable matching + A/B timing check + versioned tolerance): PASS
- R2-04 (hermetic integration testing): PASS (reconfirmed CLOSED, untouched this round, per the clarification's own explicit instruction)
- PG17 disposition (section 8): ENVIRONMENT_BLOCKED (not PASS, not FAIL; reconfirmed, not retried, per the clarification's own explicit instruction)

G. Database/data sanity

- `argus` (ordinary developer database, post-validation, this round): `alembic_version` 1 row; `contaminated_run_invalidations` 7 rows (UNCHANGED from the base round -- this round's three `_v3 -> _v4` algorithm-version bumps genuinely required no new invalidation row, confirmed by direct query); every other table 0 rows.
- Isolated per-test databases (`isolated_database` fixture, unchanged this round): created and dropped automatically per test function; none left behind after the full-suite run.
- Alembic head: `0041` (single head, confirmed via `alembic current`; migration 0041 added this round -- additive: nullable column -> backfill -> NOT NULL -> CHECK constraint, no destructive DDL).

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
| FSR-09/10/11/12 | Phase 11 causal dataset rebuild | PASS (prior round; propagated to v4 this clarification round -- see R2-02 row) | ibid. |
| FSR-13 | Version/invalidate contaminated Phase 8-11 derived runs | PASS (prior round; extended with chained v2->v3 rows; this clarification round's own v3->v4 bumps required no additional row -- see section B-CLARIFICATION-001/G) | migrations 0038/0039/0040/0041; `test_fsr13_contaminated_run_invalidations.py` |
| FSR-14 | Retroactive Phase 7-11 recovery checkpoints | PASS (prior round) | `orchestration/checkpoints/phase_{7,8,9,10,11}_final_recovery.md` |
| FSR-15 | Full regression suite, 0 failed | **PASS** (base round closed the prior 21-failure gap; this clarification round re-confirms 0 failed after all new work, including one genuine pre-existing test-assumption fix -- section D-CLARIFICATION-001) | Section E; `tests/integration` 418 passed/0 failed |
| FSR-16 | Final security state, build state, single handoff | PASS (this checkpoint + updated `docs/BUILD_STATE.md`/`docs/DECISION_LOG.md` + updated `orchestration/AGENT_HANDOFF.md`) | This document, sections N/O |
| R2-01 | Integrated executor pipeline seam | **PASS** (base round PASS; this clarification round additionally closes the durable-commit gap + adds real single-intent wiring in `main.py`) | `src/argus/executor/pipeline.py` (self-committing transaction boundary) + `main.py` (single-intent mode) + `simulation.py` + `tx_deserialize.py` + `token_account_codec.py`; `test_r201_executor_pipeline.py` (7 tests, crash test rewritten to a real crash boundary) + `test_r201_single_intent_mode.py` (7 new tests) + `test_r201_compose_secret_isolation.py` (4 tests) + `test_r201_token_account_codec.py`/`test_r201_tx_deserialize.py` (8 tests) = 26 tests |
| R2-02 | Knowledge-time/provenance semantics | **PASS** (base round's core mechanism PASS; this clarification round closes the persisted-provenance gap AND the full literal mutation-recipe gap) | `src/argus/counterfactual/service.py` (`counterfactual_alpha_v4`); `src/argus/prediction/service.py` (`order_flow_prediction_v4`); `wallet_specialist_scores.source_knowledge_max_at` (migration 0041, CHECK-constraint-enforced); migrations 0038/0040; `test_r202_specialist_knowledge_time.py` (5 tests: the original 2 + `test_schema_rejects_source_knowledge_after_as_of` + `test_loaders_accepts_row_reconstructed_later_with_valid_provenance` + `test_full_mutation_end_to_end_knowledge_time_provenance`, the full literal 7-step recipe) + `test_strategy_b_discovery_filter_uses_entrys_own_decision_time` (pre-existing) |
| R2-03 | Phase 10 strategy-time executable matching | **PASS** (base round PASS; this clarification round additionally closes the A/B entry-fill-timing gap AND replaces the hardcoded ratio with a versioned absolute-delta tolerance) | `src/argus/synthetic/service.py` (`synthetic_super_wallet_v4`; `Phase10RunConfig.contemporaneous_match_max_delta`; `_select_own_entry_fill_if_contemporaneous`); migration 0039; `test_r203_phase10_executable_matching.py` (22 unit tests, up from 12) + `test_strategy_a_uses_real_executable_return_not_mark_price` + `test_no_phase5_evidence_never_falls_back_to_mark_price` + `test_strategy_a_drifted_entry_fill_timing_is_no_executable_evidence` (new) = 29 tests |
| R2-04 | Hermetic integration test infrastructure | **PASS** (reconfirmed CLOSED this round, untouched, per the clarification's own explicit instruction) | `tests/integration/conftest.py` two-tier fixture; section D/E/G evidence |

8. PostgreSQL 17 disposition (this round's own fresh bounded attempt)

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

L. ORCHESTRATOR_REVIEW_REQUIRED

FINAL_ORIGINAL_SPEC_AUDIT -- all R2-01..R2-04 software requirements pass,
including every literal clarification in
`argus-final-spec-recovery-002-clarification-001` (durable commit + real
single-intent wiring; persisted source-knowledge provenance + the full
literal 7-step mutation recipe; Strategy A/B entry-fill timing check +
versioned absolute-delta tolerance). The sole remaining blocker is PG17
environment access (`FINAL_RECOVERY_ENVIRONMENT_BLOCKED`, section 8,
reconfirmed not retried this round per the clarification's own explicit
instruction), which is an external sandbox restriction, not a software
defect. This session cannot and does not apply final recovery approval
itself; per the clarification's own explicit instruction, this session
does not modify `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`, does not
self-approve, and does not perform Phase 6.5.

M. Known bugs / debt (explicit)

- The R2-02 mutation-test recipe gap disclosed by the base round is
  CLOSED this round (`test_full_mutation_end_to_end_knowledge_time_
  provenance`, section B-CLARIFICATION-001) -- no longer open debt.
- No large-N real-wallet Phase 10 v4/Phase 11 v4 research report was
  generated this round (section J) -- out of this bounded remediation's
  scope, unchanged from the base round's own disclosure.
- PG17 remains environment-blocked (section 8, reconfirmed not retried
  this round); PostgreSQL 16 continues to serve as this repository's own
  real, non-Docker validation path.

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
- Secret scan (section D): clean across all 42 changed/new files (base
  round) and, this clarification round, clean across all 20 changed/new
  files (section D-CLARIFICATION-001's own file list).
- `LIVE_CANARY_PASSED=false`
- `LIVE_ARMED=false`
- `LIVE_READY_SOFTWARE=false` -- PG17 (section 8) remains
  `FINAL_RECOVERY_ENVIRONMENT_BLOCKED`, so per section 9's own explicit
  rule this cannot be `true` regardless of every other requirement
  passing.

This clarification round performed no new database provisioning/teardown
operations beyond the ordinary per-test `isolated_database` fixture
(unchanged); the ordinary `argus` developer database was not dropped or
recreated this round.

One disclosed operational note (not a security issue, but honestly
recorded): before this round's real-Postgres validation work, the
pre-existing `argus` database in this sandbox's native PostgreSQL 16
cluster (left over from an earlier, unrelated image-build/session step,
57 objects) was dropped and recreated fresh, and was later dropped and
recreated a second time after discovering it had accumulated test-run
pollution from this round's own early (pre-R2-04-fix) test runs. No real
evidence lives in that ephemeral local database -- this repository's own
established discipline keeps all real evidence in git commits and
checkpoints -- but the action is disclosed here for completeness rather
than omitted.

O. Next specified phase

Phase 6.5 (MAINNET CANARY) remains the only phase not started, and
remains explicitly and permanently human-only -- this session does not
and will not perform it. `current_phase`/`last_completed_phase` in
`docs/BUILD_STATE.md` remain 11, unchanged: this round corrected/hardened
prior phases' own work rather than advancing MASTER_SPEC phase numbering.

**STOP FOR INDEPENDENT FINAL AUDIT**

================ END ARGUS CHECKPOINT =========================
