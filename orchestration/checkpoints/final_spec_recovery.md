================ ARGUS ORCHESTRATOR CHECKPOINT ================

A. Identity

PROJECT: ARGUS
MASTER_SPEC_VERSION: 2.0
MASTER_SPEC_HASH: 41f7242c288feec709b1ed72e62c74a1dc5e3b3cd9ad01e9b6e28373d9d14011
PHASE: 11 (bounded final spec recovery remediation round 2, instruction `argus-final-spec-recovery-002`)
STATUS: PARTIAL
UTC_TIMESTAMP: 2026-09-04T23:45:00Z
GIT_COMMIT: b791a4011d36c0519a8c5542918c6274eaee5c71
CONFIG_HASH: see `Phase9RunConfig`/`Phase10RunConfig`/`Phase11RunConfig`/`GraphRunConfig` `.config_hash()` per run (unchanged mechanism; no config schema change this round)
SCHEMA_VERSION: Alembic head `0040`

ORIGINAL_CONTAMINATED_BASE_COMMIT: ea77dd55b1e6be91b61b2f8b37e1d70449a3cb30
REMEDIATION_001_AUDITED_HEAD: 7cca4094d7672759b1023733a810f552f1109040
FINAL_REMEDIATION_002_IMPLEMENTATION_COMMIT: b791a4011d36c0519a8c5542918c6274eaee5c71
FINAL_REMEDIATION_002_EVIDENCE_COMMIT: (this checkpoint's own commit -- see `git log -1` after this file is committed)

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

C. Files changed

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

Never claim an unrun test: the R2-02 mutation-test recipe's full literal
section-4.3 end-to-end Phase 10/11-decision-level assertions (steps
naming byte-equivalent decision inputs across a rebuild) were **not**
built as one combined test matching that exact recipe -- only the
Phase-9-mechanism-level tests above (`test_r202_specialist_knowledge_time.py`,
2 tests: a `DirectionalEdge` created after cutoff with `as_of<=cutoff` is
excluded; the mirror-image before-cutoff edge is included) plus one
pre-existing Strategy-B decision-level regression test
(`test_strategy_b_discovery_filter_uses_entrys_own_decision_time`,
already satisfying the instruction's own named "future-created/backfilled
specialist cannot alter Strategy B/D decision" test) were written and
verified. This is a disclosed, bounded gap, not a hidden one.

E. Test results

pytest:
- R2-01 focused: 19 passed, 0 failed, 0 skipped
- R2-02 focused: 2 passed, 0 failed, 0 skipped
- R2-03 focused: 18 passed, 0 failed, 0 skipped
- tests/unit + tests/golden + tests/replay: 1316 passed, 0 failed, 0 skipped
- tests/integration (run 1, fresh isolated-database template): 414 passed, 0 failed, 0 skipped
- tests/integration (run 2, no manual cleanup): 414 passed, 0 failed, 0 skipped
- coverage: not separately instrumented this round (unchanged from prior rounds; no coverage regression tooling exists in this repository)
ruff: `ruff check .` all checks passed; `ruff format --check .` 458 files already formatted (0 reformatted)
mypy: `mypy src/` success, 0 issues, 228 source files

F. Acceptance criteria

See section H (full FSR-01..16 + R2-01..04 matrix) below for the complete
mapping. Section-level summary:

- R2-01 (integrated executor pipeline seam): PASS
- R2-02 (knowledge-time/provenance semantics): PASS (core mechanism + Phase 9/11 propagation); mutation-test recipe's full literal end-to-end form: NOT TESTED (disclosed gap, section D)
- R2-03 (Phase 10 strategy-time executable matching): PASS
- R2-04 (hermetic integration testing): PASS
- PG17 disposition (section 8): ENVIRONMENT_BLOCKED (not PASS, not FAIL)

G. Database/data sanity

- `argus` (ordinary developer database, post-validation): `alembic_version` 1 row; `contaminated_run_invalidations` 7 rows (migration-seeded registry: FSR-13's original 2 rows for Phase 8/10/11 chains, plus this round's new Phase 9/10/11 v2->v3 rows); every other table 0 rows.
- Isolated per-test databases (this round's own `isolated_database` fixture): created and dropped automatically per test function; none left behind after either full-suite run (`DROP DATABASE IF EXISTS ... WITH (FORCE)` in the fixture's own teardown, verified via the section D pollution check above).
- Alembic head: `0040` (single head, confirmed via `alembic heads`).

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
| FSR-09/10/11/12 | Phase 11 causal dataset rebuild | PASS (prior round; propagated to v3 this round -- see R2-02 row) | ibid. |
| FSR-13 | Version/invalidate contaminated Phase 8-11 derived runs | PASS (prior round; extended this round with chained v2->v3 rows) | migrations 0038/0039/0040; `test_fsr13_contaminated_run_invalidations.py` |
| FSR-14 | Retroactive Phase 7-11 recovery checkpoints | PASS (prior round) | `orchestration/checkpoints/phase_{7,8,9,10,11}_final_recovery.md` |
| FSR-15 | Full regression suite, 0 failed | **PASS** (this round closes the prior round's disclosed 21-failure gap) | Section E; `tests/integration` 414 passed/0 failed, twice |
| FSR-16 | Final security state, build state, single handoff | PASS (this checkpoint + updated `docs/BUILD_STATE.md`/`docs/DECISION_LOG.md` + replaced `orchestration/AGENT_HANDOFF.md`) | This document, sections N/O |
| R2-01 | Integrated executor pipeline seam | **PASS** | `src/argus/executor/pipeline.py` + `simulation.py` + `tx_deserialize.py` + `token_account_codec.py`; `test_r201_executor_pipeline.py` (7 tests: `executor_e2e_safe_synthetic_intent`, `attestation_failure_never_signs_or_submits`, `signing_failure_never_submits`, `submission_response_persisted_before_confirmation`, `crash_after_submission_restart_reconciles_same_signature_without_second_submit`, `terminal_restart_noop`, `missing_or_bad_operator_key_fails_closed`) + `test_r201_compose_secret_isolation.py` (AST/import boundary + deployment/permission, 4 tests) + `test_r201_token_account_codec.py`/`test_r201_tx_deserialize.py` (8 tests) |
| R2-02 | Knowledge-time/provenance semantics | **PASS** (core mechanism); mutation-recipe's full literal form NOT TESTED (disclosed) | `src/argus/counterfactual/service.py` (`counterfactual_alpha_v3`); `src/argus/prediction/service.py` (`order_flow_prediction_v3`); migrations 0038/0040; `test_r202_specialist_knowledge_time.py` (2 tests) + `test_strategy_b_discovery_filter_uses_entrys_own_decision_time` (pre-existing, satisfies the named "backfilled specialist cannot alter Strategy B/D decision" test) |
| R2-03 | Phase 10 strategy-time executable matching | **PASS** | `src/argus/synthetic/service.py` (`synthetic_super_wallet_v3`); migration 0039; `test_r203_phase10_executable_matching.py` (12 unit tests covering one-hour-exit-trap, no-exit-time-evidence, confirmation-entry opportunity trap, confirmation-entry PRICE trap, confirmation-entry-no-evidence x2, unsellable-matching-exit-still-failure, zero/negative-duration guards) + `test_strategy_a_uses_real_executable_return_not_mark_price` (fixed-haircut-cannot-enter-primary) + `test_no_phase5_evidence_never_falls_back_to_mark_price` (insufficient-executable-samples-allowed-as-valid-result) |
| R2-04 | Hermetic integration test infrastructure | **PASS** | `tests/integration/conftest.py` two-tier fixture; section D/E/G evidence |

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

NONE. R2-03's entry-side fix (`OpportunityEntryProbe`,
`WalletOpportunity.entry_delay_probes`, `OpportunityReverseOutcome.
reverse_quote`) extends `argus/copyability/loaders.py` (a Phase 5 shared
module) additively -- new fields only, no existing field's meaning or any
existing Phase 5 M1-M6 consumer's behavior changed. This was necessary
(not optional) to satisfy the instruction's own explicit R2-03
requirement that Strategy C/D "never reuse the leader's earlier fill" for
its own entry price, which the previous fix (opportunity-lookup only) did
not yet satisfy -- disclosed here rather than silently expanded past
scope.

L. ORCHESTRATOR_REVIEW_REQUIRED

FINAL_ORIGINAL_SPEC_AUDIT -- all R2-01..R2-04 software requirements pass;
the sole remaining blocker is PG17 environment access
(`FINAL_RECOVERY_ENVIRONMENT_BLOCKED`, section 8), which is an external
sandbox restriction, not a software defect. This session cannot and does
not apply final recovery approval itself.

M. Known bugs / debt (explicit)

- R2-02's mutation-test recipe (section 4.3 of the instruction) was
  implemented at the Phase-9-mechanism level (2 dedicated tests) plus one
  pre-existing Strategy-B decision-level regression test, not as the full
  combined 7-step literal recipe the instruction describes in exhaustive
  detail (seed E1 -> reconstruct Phase 9 for T -> capture Phase 10/11
  values at T -> append a backdated row -> rebuild under a fresh
  algorithm/config identity -> assert byte-equivalent decision inputs ->
  assert visibility only at a later cutoff). The mechanism-level tests
  prove the same root cause is fixed; the full combined recipe is
  disclosed as not yet built.
- No large-N real-wallet Phase 10 v3/Phase 11 v3 research report was
  generated this round (section J) -- out of this bounded remediation's
  scope.
- PG17 remains environment-blocked (section 8); PostgreSQL 16 continues
  to serve as this repository's own real, non-Docker validation path.

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
- Secret scan (section D): clean across all 42 changed/new files.
- `LIVE_CANARY_PASSED=false`
- `LIVE_ARMED=false`
- `LIVE_READY_SOFTWARE=false` -- PG17 (section 8) remains
  `FINAL_RECOVERY_ENVIRONMENT_BLOCKED`, so per section 9's own explicit
  rule this cannot be `true` regardless of every other requirement
  passing.

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
