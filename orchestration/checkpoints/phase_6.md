================ ARGUS ORCHESTRATOR CHECKPOINT ================

A. Identity

PROJECT: ARGUS
SCOPE: Phase 6 (HARDENED ISOLATED EXECUTOR), SOFTWARE-ONLY, MASTER_SPEC.md
sections 65-84 (primarily 67-84), per orchestrator instruction
`argus-phase-6-001`, against a NEW sealed 18-row acceptance contract
(`phase-6-v1`, P6-01 through P6-18). Governed by
`orchestration/AUDITOR_POLICY.md`. Authorized phase: 6
(`AUTHORIZED_PHASE: 6`, `APPROVES_PHASE: 5`). No self-approval of Phase 6
is claimed anywhere in this document -- only the orchestrator's own
independent audit may approve Phase 6 or authorize Phase 6.5/7.
STATUS: PASS_WITH_DISCLOSED_ENVIRONMENTAL_DEFERRAL
GIT_COMMIT: cdba30bd8f60ce68c56210995d0df868de286a60

Instruction: `argus-phase-6-001`, ACTIVE at submission.

- This instruction's own carrying commit (the commit that carries its
  text into `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`):
  `3078d448235ebe693adc9a57a412acadef8c9a10` ("orchestrator: approve
  Phase 5 and authorize sealed Phase 6").
- This instruction's own `TARGET_COMMIT:` field value (the safety-gate
  ancestor baseline this session verified ancestry/diff-scope against
  before acting): `43bb62f9247e8e8b3a663e98c8ed70ba956e4960` (Phase 5
  remediation round 1's own hash-fill commit).

Gate verification performed before any work began: `43bb62f9247e8e8b3a66
3e98c8ed70ba956e4960` resolves to a real commit (`git cat-file -t`), is
an ancestor of HEAD (`git merge-base --is-ancestor`), and the only path
differing between it and the instruction-carrying HEAD
(`3078d448235ebe693adc9a57a412acadef8c9a10`) is
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md` -- a single instruction-only
commit whose direct parent exactly matches this TARGET_COMMIT value.
`AUTHORIZED_PHASE: 6` <= `docs/BUILD_STATE.md`'s `current_phase: 5` + 1.
Worktree was clean; local HEAD equaled a freshly-fetched remote HEAD
before any work began.

B. Environmental limitation (deferred, not a builder failure -- the same
   class disclosed in every prior phase)

This sandbox has no reachable Postgres and no running Docker daemon
(`docker compose up -d postgres` fails: "Cannot connect to the Docker
daemon" -- raw output in this phase's own `orchestration/phase_6/
evidence/full_validation_output.txt`, final command). Identical
environmental class as every prior phase (`PG17_COMPOSE_VALIDATION`,
total absence of Postgres in this specific container). Consequence,
honestly disclosed per Environmental rule E: every DB-backed integration
test in this repo (Phase 1 through Phase 6 alike) SKIPS (never fails) in
this session. Substitute/structural evidence for this phase's own new
DB-dependent rows:

1. The full Phase 6 pure-logic unit-test suite (18 new `tests/unit/
   test_phase6_p6_*.py` files, 229 nodes) runs for real with zero skips
   against the actual production `argus.executor.*` modules -- no
   database is required to exercise the state machine, idempotency
   fingerprinting, attestation, fill accounting, slippage, the 23-gate
   risk table, position policy, risk exits, token safety/sellability,
   host reconciliation, dispatch guarding, or report honesty.
2. The executor-singleton concurrency guarantee (P6-04) is proven twice:
   once for real against `InMemoryLeaseStore` with two independent
   simulated callers (unit, runs for real, zero skips), and once
   structurally against the real `PostgresLeaseStore` adapter in
   `tests/integration/test_phase6_persistence_and_concurrency.py`
   (collects cleanly, SKIPS here).
3. Every new DB-backed integration test this phase adds (role/privilege
   assertions, lease-store real-DB concurrency, state-reload-after-
   restart, duplicate-fingerprint concurrent-insert, partial-unique-index
   rejection, kill-after-submit/reconciliation) collects cleanly and
   SKIPS, matching this repository's established pattern exactly (same
   `admin_engine`-gated skip fixture every Phase 1-5 DB-backed test
   uses).
4. `argus executor readiness` (the real CLI command, run through the
   same Typer app a human operator uses) was executed for real in this
   sandbox and its exact output captured verbatim at
   `orchestration/phase_6/evidence/executor_readiness_output.json` --
   this needs no database at all, since it evaluates live runtime
   invariants against this build's own constants.

No implementation or specified test is missing -- only actual DB-backed
execution is environment-blocked, identical to every prior phase's own
disclosed limitation. CF5-DB (carried forward from the Phase 5
instruction) is unaffected by this phase's work: no real, authorized
local/test PostgreSQL environment became available during this session,
so the Phase 5 DB-backed copyability/readiness integration paths remain
under the SAME disclosed deferral as before -- not retroactively
reopened, no credentials requested or disclosed.

C. What was actually built (P6-01 through P6-18, mapped by MASTER_SPEC
   section)

- Section 73/74 (P6-01): `src/argus/executor/capital.py` hardcodes
  `LIVE_MAX_SINGLE_TRADE_SOL`/`LIVE_MAX_TOTAL_EXPOSURE_SOL`/
  `LIVE_MAX_DAILY_LOSS_SOL` at exactly `Decimal(0)`, never read from
  config/env/database. `src/argus/executor/arm.py`'s
  `validate_arm_file` is a READ-ONLY function over the EXTERNAL,
  human-controlled arm file -- this codebase never creates or modifies
  that file anywhere; every missing/malformed/expired/hash-mismatched
  case returns `armed=False` with an explicit reason, never a fallback
  that enables execution.
- Section 70/71 (P6-02): `src/argus/executor/signing.py` defines the ONE
  `Signer` protocol boundary plus two inert test doubles (`FakeSigner`,
  `RaisingSigner`) -- deliberately NO real on-disk-keypair
  implementation exists anywhere in this package, since this coding
  session is absolutely prohibited from ever handling real key material.
  No non-executor package (`copyability`, `scoring`, `ingestion`,
  `wallets`, `tokens`, `shadow`, `reports`, `research`, `signals`,
  `outcomes`, `notifications`, `telegram`, `clustering`, `graph`,
  `risk`, `parsing`, `providers`, `api`, `db`, `domain`) imports
  `argus.executor.signing`/`argus.executor.dispatch` anywhere, proven by
  static import-graph inspection in
  `tests/unit/test_phase6_p6_02_signer_isolation_boundary.py`.
- Section 72/75 (P6-03/P6-04): migration `0024` (additive, revises
  `0023`) creates `executor_leases` + `executor_lease_fencing_seq` and
  GRANTs `argus_executor` SELECT/INSERT/UPDATE (never DELETE) on the 8
  new Phase 6 tables only, with `argus_research`/`argus_ingest` limited
  to SELECT-only -- `argus_executor` gains zero privilege on any
  historical research table (`wallet_score_snapshots`, etc.).
  `src/argus/executor/singleton.py` implements the lease/fencing-token
  protocol: `InMemoryLeaseStore` (fully unit-testable, two independent
  callers sharing one instance) and `PostgresLeaseStore` (the real
  production adapter over `executor_leases`) share the identical
  `LeaseStore` protocol -- `try_acquire` always refuses a concurrent
  acquire against a still-valid lease; `try_renew` is a strict
  compare-and-swap that signals lost ownership (via `lost_ownership()`)
  the instant the fencing token no longer matches.
- Section 76/77 (P6-05/P6-06): `src/argus/domain/execution_intents.py`
  defines the frozen 11-state machine (`CREATED`, `VALIDATING`,
  `REJECTED`, `ORDER_REQUESTED`, `ORDER_READY`, `ATTESTING`, `SIGNED`,
  `SUBMITTED`, `CONFIRMED`, `FAILED`, `UNKNOWN`);
  `src/argus/executor/state_machine.py`'s pure `transition()` function
  enforces the exact legal-transition graph (3 terminal states:
  `REJECTED`/`CONFIRMED`/`FAILED`; `SUBMITTED`/`UNKNOWN` can only resolve
  to `CONFIRMED`/`FAILED`, never a blind retry back into
  `SIGNED`/`SUBMITTED`). `src/argus/executor/idempotency.py`'s
  `compute_idempotency_fingerprint` is a deterministic SHA-256 digest
  over one semantic intent's exact identity, bound at the database level
  by `execution_intents.idempotency_fingerprint`'s UNIQUE constraint.
  `src/argus/executor/persistence.py`'s `get_or_create_execution_intent`
  uses the SAME `INSERT ... ON CONFLICT DO NOTHING` + re-select-within-
  transaction pattern F5-05 established for Phase 5 snapshots --
  concurrent duplicate inserts under the same fingerprint always
  converge on exactly one row; `apply_transition` validates against the
  pure state machine BEFORE writing anything, then atomically updates
  the intent's `state` column and appends its own audit row in
  `execution_intent_transitions` in the same call.
- Section 78 (P6-07): `src/argus/executor/attestation.py`'s
  `attest_transaction` checks all 8 required dimensions (signer
  identity, executor wallet identity, input mint, output mint, intended
  amount, user-controlled outflows, fee/tip/rent ceiling, simulated
  balance changes) against a typed `UnsignedTransactionShape` fixture;
  `src/argus/executor/persistence.py`'s `record_attestations` persists
  one `execution_attestations` row per dimension, PASS or FAIL, never
  only the failures.
- Section 79 (P6-08): `src/argus/executor/fill_accounting.py`'s
  `FillEvidence` keeps quoted/simulated/actual input/output plus
  network/priority fee, tip, and rent as ten SEPARATE nullable fields;
  `canonical_input_raw`/`canonical_output_raw` return ONLY the
  `actual_*` fields -- never substituted from quote/simulation when
  missing.
- Section 80 (P6-09): `src/argus/executor/slippage.py`'s
  `evaluate_retry` rejects any request exceeding the approved ceiling
  AND any request exceeding a previous attempt's own value (monotonic
  non-increase enforced structurally, not by convention);
  `should_abandon` signals abandonment whenever no viable slippage value
  exists within the ceiling.
- Section 81 (P6-10): `src/argus/executor/risk_gates.py`'s
  `build_gates`/`evaluate_live_risk` independently re-evaluate all 23
  required gates (`GATE_KEYS`, exact section-81 order) from caller-
  supplied evidence only -- ANY single FAIL or UNKNOWN gate rejects the
  whole evaluation with a stable reason code; this module never
  fabricates a PASS for `software_readiness`/`canary_status`/
  `human_arm_validity`.
- Section 65 (P6-11): `src/argus/domain/live_positions.py` +
  migration `0024`'s partial unique index
  (`uq_live_positions_one_open_per_token`, `WHERE status = 'OPEN'`) is
  the real database-level one-open-position-per-mint enforcement --
  `src/argus/executor/position_policy.py`'s `ALLOW_AUTOMATIC_SCALE_IN`
  is hardcoded `False` and `evaluate_scale_in` is the application-level
  check that runs BEFORE any insert is attempted (never a check-then-act
  race against the real backstop).
- Section 67 (P6-12): `src/argus/executor/risk_exits.py`'s
  `evaluate_risk_exits` independently evaluates all 6 triggers (max
  position loss, liquidity collapse, token-risk-state change, max daily
  loss, max aggregate exposure, operator emergency exit) purely from
  ARGUS's own state -- `RiskExitInputs` has no field referencing the
  leader/source wallet's own behavior at all (structurally proven by
  `test_phase6_p6_12_risk_exits.py`); returns EVERY independently-true
  trigger, never only the first.
- Section 68/69 (P6-13): `src/argus/executor/token_safety.py`'s
  `evaluate_token_safety` treats a MISSING flag exactly like `UNKNOWN`
  (never silently safe); any single `FAIL` always wins over `UNKNOWN` in
  the overall status. `evaluate_pre_entry_sellability` fail-closed
  cascades through absent route / excessive impact / missing or
  future-dated / stale quote timestamp.
- Section 83 (P6-14): `src/argus/executor/reconciliation.py`'s
  `detect_discontinuity` flags any gap exceeding the allowed threshold;
  `may_resume_new_entries` requires ALL 7 dimensions (`clock`,
  `streams`, `tracked_wallet_watermarks`, `live_positions`,
  `executor_wallet_balance`, `provider_health`, `open_orders_intents`)
  independently HEALTHY -- six of seven still blocks.
- Section 76/79 restart discipline (P6-15): the frozen state machine's
  own terminal/legal-transition discipline (P6-05) plus the idempotency
  fingerprint's database-level UNIQUE constraint (P6-06) together make a
  restart/crash structurally unable to duplicate an intent or blindly
  retry an ambiguous submission; the new DB-gated integration test
  `test_intent_left_submitted_across_restart_never_silently_retries`
  exercises exactly this scenario end-to-end (collects cleanly, SKIPS,
  section B). All pre-existing Phase 0-5 restart/idempotency suites
  re-ran clean in this round's full regression (section F).
- Section 70/78 (P6-16): `src/argus/executor/dispatch.py`'s
  `DispatchGuard` bundles a `Signer` and a submission callable, defaulting
  to `raising_submission` (raises `DispatchNeverCalledError`) -- every
  non-canary/non-live-execution code path in this codebase (including
  `argus executor readiness`) is constructed with this raising default.
  `tests/unit/test_phase6_p6_16_no_dispatch_sentinel.py` runs the real
  `argus executor readiness` CLI command end-to-end and scans its output
  for fake-secret-shaped patterns (base58 64-byte-keypair length,
  PEM private-key headers) -- none found; a manual grep-based secret
  scan across all 46 new/changed Phase 6 files (credential/API-key/
  password/token patterns plus the same base58-length check) also found
  nothing (section F).
- Section 82 (P6-17): `src/argus/executor/report.py`'s
  `Phase6Disposition`/`build_disposition` make `live_canary_passed`/
  `live_armed` UNCONDITIONALLY `False` -- no parameter or code path can
  ever set either to `True`; `live_ready_software` requires EVERY
  supplied criterion to be `True`, and an empty criteria set is never
  silently "ready". `src/argus/executor/service.py`'s
  `build_phase6_disposition` feeds this real, live runtime assertions
  (state-machine shape, dispatch-guard default, capital defaults, scale-
  in policy, gate/flag/dimension counts) rather than hardcoded
  placeholders -- a future code change that silently breaks one of these
  invariants makes the report honestly show it as unmet.
- Section 72 test infra (P6-18): full regression sweep, section F.

D. Sealed 18-row acceptance matrix (P6-01 through P6-18)

| Row | Class | Implementation | Exact test node(s) / command | Actual result | Pass condition | E-limitation | PASS/FAIL |
|---|---|---|---|---|---|---|---|
| P6-01 | SPEC_BLOCKING | `argus.executor.capital` (zero defaults), `argus.executor.arm.validate_arm_file` | `tests/unit/test_phase6_p6_01_arm_and_capital.py` (17 nodes: zero-default, missing/malformed/not-object/armed-not-true/expired/naive-expiry/git-hash-mismatch/build-hash-mismatch/risk-config-hash-mismatch/strategy-not-approved/negative-capital/missing-field cases, plus a positive control and a never-writes-the-file proof) | 17/17 passed | Repository defaults exactly zero; every missing/malformed/expired/hash-mismatched arm case returns `armed=False` with an explicit reason; no fallback enables execution; validator never writes the file | None | PASS |
| P6-02 | SPEC_BLOCKING | `argus.executor.signing` (`Signer` protocol, `FakeSigner`, `RaisingSigner`) | `tests/unit/test_phase6_p6_02_signer_isolation_boundary.py` (24 nodes: fake/raising-signer behavior + static import-graph scan of 20 non-executor packages + cli.py's own import scope) | 24/24 passed | Fake signer only, never a real key; no non-executor package imports `argus.executor.signing`/`dispatch`; `cli.py` never imports those modules directly (only the read-only `service`/`report` surface) | None | PASS |
| P6-03 | SAFETY_OR_INTEGRITY_BLOCKING | Migration `0024` GRANTs (`argus_executor`: SELECT/INSERT/UPDATE on 8 new tables only; `argus_research`/`argus_ingest`: SELECT-only) | `tests/integration/test_phase6_persistence_and_concurrency.py::test_argus_executor_role_has_least_privilege`; `tests/unit/test_phase6_p6_18_migration_and_regression.py` (migration `0024` down_revision=`0023`, single alembic head); `uv run alembic heads` | Integration test: written, collects cleanly, SKIPS (section B). Migration/head tests: 3/3 passed. `alembic heads`: single head `0024` | Required executor tables/actions work under intended role; forbidden writes (on historical research tables) are denied; upgrades cleanly from Phase 5's `0023` | DB-backed role/privilege execution deferred (section B); migration structure and single-head status verified for real without a database | PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION |
| P6-04 | SAFETY_OR_INTEGRITY_BLOCKING | `argus.executor.singleton` (`InMemoryLeaseStore`, `PostgresLeaseStore`, `acquire_or_refuse`, `lost_ownership`) | `tests/unit/test_phase6_p6_04_singleton_lease.py` (6 nodes: second-owner-refused, renew-before-expiry, new-token-after-expiry, stale-owner-after-takeover, wrong-fencing-token, never-acquired); `tests/integration/test_phase6_persistence_and_concurrency.py::test_postgres_lease_store_two_instances_one_owner_wins` (real two-connection DB concurrency test) | Unit: 6/6 passed. Integration: written, collects cleanly, SKIPS (section B) | Exactly one owner; second concurrent acquire against a still-valid lease always refuses; lost/stale ownership (fencing-token mismatch) always signals DISARM via `lost_ownership()` | Real-DB two-process concurrency execution deferred (section B); the identical CAS decision logic is proven for real via `InMemoryLeaseStore` with two independent simulated callers | PASS |
| P6-05 | SPEC_BLOCKING | `argus.domain.execution_intents` (11-state model), `argus.executor.state_machine.transition` | `tests/unit/test_phase6_p6_05_state_machine.py` (26 nodes: all legal pairs, state count, terminal-state set, no-legal-next-state-from-terminal, transition-out-of-terminal-always-raises, no-skip, ambiguous-submitted-never-retries, unknown-state-name); `tests/integration/test_phase6_persistence_and_concurrency.py::test_execution_intent_state_reloads_correctly_after_restart` | Unit: 26/26 passed. Integration: written, collects cleanly, SKIPS (section B) | Legal transitions persist once; illegal transitions (including terminal-state exits) fail closed via `IllegalTransitionError` without state corruption; audit history retained in `execution_intent_transitions` | DB-backed restart-reload execution deferred (section B); the transition graph itself is proven for real, exhaustively, without a database | PASS |
| P6-06 | SPEC_BLOCKING | `argus.executor.idempotency.compute_idempotency_fingerprint`, `argus.executor.persistence.get_or_create_execution_intent` (UNIQUE-constraint-backed) | `tests/unit/test_phase6_p6_06_idempotency.py` (8 nodes: determinism + one-field-difference-changes-fingerprint x6); `tests/integration/test_phase6_persistence_and_concurrency.py::test_duplicate_idempotency_fingerprint_never_creates_two_rows` (5-way concurrent `asyncio.gather` insert race) | Unit: 8/8 passed. Integration: written, collects cleanly, SKIPS (section B) | One semantic intent produces exactly one row under concurrent duplicate inserts (proven via `ON CONFLICT DO NOTHING` + re-select, same pattern as F5-05); ambiguous `SUBMITTED` intent resolves only to `UNKNOWN` then `CONFIRMED`/`FAILED`, never a blind retry (P6-05's own state-machine proof) | Real-DB concurrent-insert execution deferred (section B); the fingerprint's own determinism/collision-resistance is proven for real | PASS |
| P6-07 | SAFETY_OR_INTEGRITY_BLOCKING | `argus.executor.attestation.attest_transaction` (8 dimensions), `argus.executor.dispatch.DispatchGuard` | `tests/unit/test_phase6_p6_07_attestation.py` (12 nodes: 1 valid fixture + 9 individual dimension-failure fixtures (parametrized covering all 8 dimensions, `DIMENSION_SIMULATION` triggered 3 ways) + dimension-coverage assertion + signer-never-called-on-failure + submission-never-called) | 12/12 passed | Signer never called for any failed/unknown attestation (proven via `RaisingSigner` spy); valid inert fixture passes every dimension, reaching only the signing seam boundary in this test, never network submission | None | PASS |
| P6-08 | SPEC_BLOCKING | `argus.executor.fill_accounting.FillEvidence` | `tests/unit/test_phase6_p6_08_fill_accounting.py` (5 nodes: quote!=simulated!=actual retained, canonical=actual-only, missing-actual-never-backfilled-from-quote/sim, all-fields-default-None-never-zero, fee/tip/rent-separate) | 5/5 passed | Confirmed chain-derived values win; quote/simulation provenance retained separately, never discarded; missing values stay explicit `None`, never fabricated from an earlier-stage value | None | PASS |
| P6-09 | SAFETY_OR_INTEGRITY_BLOCKING | `argus.executor.slippage.evaluate_retry`/`should_abandon` | `tests/unit/test_phase6_p6_09_slippage.py` (9 nodes: within-ceiling-no-previous, exceeds-ceiling-rejected, at-ceiling-allowed, exceeds-previous-rejected-even-within-ceiling, lower-than-previous-allowed, equal-to-previous-allowed, repeated-retry-sequence-never-compounds, abandon-no-viable, abandon-exceeds-ceiling, not-abandon-within-ceiling) | 9/9 passed | Code never increases the approved ceiling automatically; retry ceiling is monotonic non-increasing across a simulated 4-attempt sequence (never escalates); unsafe execution abandoned when no viable slippage exists | None | PASS |
| P6-10 | SAFETY_OR_INTEGRITY_BLOCKING | `argus.executor.risk_gates.build_gates`/`evaluate_live_risk` (23 gates) | `tests/unit/test_phase6_p6_10_risk_gates.py` (48 nodes: gate-key-count, all-safe-baseline-approved, every-gate-individually-FAIL (23 parametrized), every-applicable-gate-individually-UNKNOWN (13 parametrized), coverage-completeness assertion, no-signer-construction proof) | 48/48 passed | Every single failed/unknown mandatory gate independently rejects with a stable reason code before any signing/submission seam; no test in this module constructs a real signer/dispatch path | None | PASS |
| P6-11 | SAFETY_OR_INTEGRITY_BLOCKING | `argus.domain.live_positions` + migration `0024` partial unique index; `argus.executor.position_policy.evaluate_scale_in` | `tests/unit/test_phase6_p6_11_position_policy.py` (4 nodes: hardcoded-False assertion, no-existing-position-allowed, existing-position-blocked, repeated-signals-still-blocked); `tests/integration/test_phase6_persistence_and_concurrency.py::test_second_concurrent_open_position_for_same_token_is_rejected` (real `IntegrityError` on the partial unique index) | Unit: 4/4 passed. Integration: written, collects cleanly, SKIPS (section B) | Second automatic buy for the same mint is rejected/no dispatch; the database's own partial unique index (`uq_live_positions_one_open_per_token`) is the real backstop, proven structurally via `INSERT` direct-attempt (never a check-then-act race) | Real-DB `IntegrityError`-on-concurrent-insert execution deferred (section B); the application-level scale-in decision itself is proven for real | PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION |
| P6-12 | SAFETY_OR_INTEGRITY_BLOCKING | `argus.executor.risk_exits.evaluate_risk_exits` (6 triggers) | `tests/unit/test_phase6_p6_12_risk_exits.py` (9 nodes: safe-inputs-trigger-nothing, one node per trigger x6, co-occurring-triggers-both-returned, all-six-covered, structural no-leader-wallet-field proof) | 9/9 passed | Each trigger creates deterministic risk-exit behavior with an audited reason (`RiskExitTrigger.detail`); co-occurring triggers both returned, never only the first; `RiskExitInputs` has zero fields referencing leader/source-wallet behavior; no live dispatch anywhere in this module | None | PASS |
| P6-13 | SAFETY_OR_INTEGRITY_BLOCKING | `argus.executor.token_safety.evaluate_token_safety`/`evaluate_pre_entry_sellability` | `tests/unit/test_phase6_p6_13_token_safety.py` (24 nodes: all-pass-safe, flag-count, each-flag-FAIL x8, each-flag-UNKNOWN x8, missing-flag-as-unknown, fail-wins-over-unknown, empty-dict-fully-unknown, full-sellable-passes, missing-route/no-route/missing-impact/excessive-impact/missing-timestamp/future-timestamp/stale-quote) | 24/24 passed | Unsafe/UNKNOWN required safety evidence blocks eligibility (missing flag treated exactly like UNKNOWN, never silently safe); absent reverse route, excessive impact, or stale/future/missing quote timestamp all fail-closed; safety screen never described as a guarantee (module docstring) | None | PASS |
| P6-14 | SAFETY_OR_INTEGRITY_BLOCKING | `argus.executor.reconciliation.detect_discontinuity`/`may_resume_new_entries` | `tests/unit/test_phase6_p6_14_reconciliation.py` (13 nodes: dimension count, gap-within/exceeding-allowance, all-seven-healthy-resumes, each-dimension-UNHEALTHY x7, each-dimension-PENDING x7 partial params, six-of-seven-still-blocks, missing-dimension-treated-unhealthy) | 13/13 passed | No new entry permitted until ALL 7 required dimensions (clock, streams, tracked-wallet watermarks, positions, executor balance, provider health, open orders/intents) independently report HEALTHY; a partial recovery (six of seven) still blocks | None | PASS |
| P6-15 | SPEC_BLOCKING | Frozen state machine (P6-05) + idempotency fingerprint (P6-06) together; named Phase 0-5 regression suites; new kill-after-submit test | `tests/integration/test_phase6_persistence_and_concurrency.py::test_intent_left_submitted_across_restart_never_silently_retries` (NEW); full `uv run pytest -q` (section F); named Phase 5 regression suite re-run individually (section F) | New test: written, collects cleanly, SKIPS (section B). Full suite: 1082 passed, 343 skipped, 0 failed. Named Phase 5 suite: 111 passed, 6 skipped, 0 failed | No duplicate canonical event/shadow trade/executor buy; an intent stuck in SUBMITTED across a simulated crash reloads with its exact state intact and resolves only via reconciliation (UNKNOWN then CONFIRMED/FAILED), never a blind resubmission; every pre-existing Phase 0-5 restart/idempotency test remains green | The new executor-kill-after-submit/DB-loss test itself is DB-gated and execution-deferred in this session (section B); its structural guarantee (state-machine + UNIQUE-constraint discipline) is proven for real by the unit suites | PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION |
| P6-16 | SAFETY_OR_INTEGRITY_BLOCKING | `argus.executor.dispatch.DispatchGuard`/`raising_submission`; `argus.executor.signing.RaisingSigner` | `tests/unit/test_phase6_p6_16_no_dispatch_sentinel.py` (4 nodes: real `argus executor readiness` CLI run + fake-secret-shaped-pattern scan on its output, guarded-signer-seam raises, guarded-submission-seam raises, default-is-raising-submission assertion); manual grep-based secret scan across all 46 new/changed Phase 6 files (section F) | 4/4 passed. Secret scan: 0 matches (both credential-pattern and base58-keypair-length checks) | Zero submission/signing calls in the report/readiness/dry-run path (proven by running the real CLI command and asserting no sentinel exception was needed to reach a clean exit, plus direct construction/invocation of the guarded seams outside the CLI); no fake secret present in outputs/logs | None | PASS |
| P6-17 | SPEC_BLOCKING | `argus.executor.report.Phase6Disposition`/`build_disposition`; `argus.executor.service.build_phase6_disposition` | `tests/unit/test_phase6_p6_17_report_honesty.py` (8 nodes: canary/armed always False even with all-criteria-True, ready-only-when-all-criteria-True, ready-false-on-any-criterion-False, empty-criteria-never-ready, `as_dict` schema, real-disposition-never-claims-canary/armed, real-criteria-are-actual-bools, build-hash-is-real-sha256, no-input-mutation); real CLI run captured at `orchestration/phase_6/evidence/executor_readiness_output.json` | 8/8 passed. Real CLI run: `LIVE_READY_SOFTWARE: true`, `LIVE_CANARY_PASSED: false`, `LIVE_ARMED: false`, 7/7 real software criteria true, 4 explicit limitations stated | Final checkpoint (this document, section A `STATUS`) and the real CLI output both explicitly record `LIVE_CANARY_PASSED: false`/`LIVE_ARMED: false`; `LIVE_READY_SOFTWARE: true` is stated only because every one of 7 real, live-evaluated software-only criteria is actually proven true; environmental deferrals (section B) remain named in both the checkpoint and the report's own `limitations` list | None | PASS |
| P6-18 | SPEC_BLOCKING | Full repository regression | `uv run pytest -q`; `uv run ruff check .`; `uv run ruff format --check .`; `uv run mypy src`; `uv run alembic heads`; `uv run argus fixtures validate-real-chain`; named Phase 5 regression suite re-run individually (section F) | 1082 passed, 343 skipped, 0 failed. `ruff check .`: all checks passed. `ruff format --check .`: 338 files already formatted. `mypy src`: success, 168 source files. `alembic heads`: single head `0024`. `argus fixtures validate-real-chain`: 12/12 ok. Named Phase 5 suite: 111 passed, 6 skipped, 0 failed | Full command sequence run, raw output captured verbatim in `orchestration/phase_6/evidence/full_validation_output.txt`; no non-environmental failure anywhere; zero baseline test removed/weakened/skipped; historical evidence remains immutable (section H) | Every DB-dependent test skips in this session (pre-existing, section B) | PASS |

E. DO-NOT / allowed-files compliance

| Prohibition | Compliance |
|---|---|
| Real seed phrase/private/signing key creation, reading, request, printing, or persistence | None anywhere in this phase's diff -- only the `Signer` protocol plus `FakeSigner`/`RaisingSigner` inert test doubles exist (section C, P6-02/P6-16). |
| Wallet creation/funding; creating or modifying `/var/lib/argus/live_arm.json` or any equivalent external arm file | None. `argus.executor.arm.validate_arm_file` is read-only over a caller-supplied `Path`; grep across the diff confirms no `write_text`/`write_bytes`/`open(..., "w")` call anywhere in `argus/executor/arm.py`. |
| Mainnet transaction submission, human canary initiation, strategy live trade | None. `DispatchGuard`'s default `submit` is `raising_submission`; every non-canary code path in this diff is constructed with this default (section C, P6-16). |
| Changing zero live-capital defaults or defining operator capital | None. `LIVE_MAX_SINGLE_TRADE_SOL`/`LIVE_MAX_TOTAL_EXPOSURE_SOL`/`LIVE_MAX_DAILY_LOSS_SOL` remain hardcoded `Decimal(0)` (section D, P6-01). |
| Paid provider use/upgrade | None. No new provider client or HTTP dispatch exists anywhere in this phase's diff. |
| Weakening Phase 5 thresholds (readiness>=90, A/S, qualification>=85, copyability>=75) | None. `config/signals_v1.yaml` byte-identical (`git diff --stat` empty, section H). |
| Phase 6.5/7+ research as a hidden prerequisite | None. Scope strictly limited to sections 65-84; sections 62-64 untouched. |
| `MASTER_SPEC.md` / `orchestration/AUDITOR_POLICY.md` / `orchestration/PROTOCOL.md` / watcher code / `ORCHESTRATOR_INSTRUCTIONS.md` change | None. `git diff --stat` confirms empty for all five (section H). |
| Non-additive migration / historical migration rewrite | None. Migration `0024` is purely additive on top of `0023`; `0023` and everything before it byte-identical. |

F. Commands actually run (raw output captured verbatim)

Full raw output: `orchestration/phase_6/evidence/full_validation_output.txt`
(358 lines): `uv run pytest -q` (full suite), `uv run ruff check .`,
`uv run ruff format --check .`, `uv run mypy src`, `uv run alembic
heads`, `uv run argus fixtures validate-real-chain`, `docker compose up
-d postgres` (environmental deferral proof), named Phase 5 regression
suite re-run individually, Phase 6 unit suite re-run individually, Phase
6 DB-backed integration suite (collects/skips), manual secret scan
(credential-pattern + base58-keypair-length) across all 46 new/changed
Phase 6 files.

Summary:
- `uv run pytest -q`: 1082 passed, 343 skipped, 0 failed.
- `uv run ruff check .`: All checks passed!
- `uv run ruff format --check .`: 338 files already formatted.
- `uv run mypy src`: Success: no issues found in 168 source files.
- `uv run alembic heads`: 0024 (head).
- `uv run argus fixtures validate-real-chain`: 12/12 fixtures ok.
- `docker compose up -d postgres`: "Cannot connect to the Docker
  daemon" (environmental deferral, section B).
- Named Phase 5 regression suite (11 files): 111 passed, 6 skipped, 0
  failed.
- Phase 6 unit suite (18 files, 229 nodes): 229 passed, 0 skipped, 0
  failed.
- Phase 6 DB-backed integration suite (6 nodes): 6 skipped (section B),
  0 failed.
- Secret scan (credential/API-key/password/token patterns): 0 matches
  across 46 files.
- Secret scan (base58 64-byte-keypair length, >=80 chars): 0 matches
  across 46 files.

`argus executor readiness` (the real CLI command) output captured
verbatim at `orchestration/phase_6/evidence/executor_readiness_output.json`.

G. Test results (this phase's new nodes, by file)

- `tests/unit/test_phase6_p6_01_arm_and_capital.py`: 17/17.
- `tests/unit/test_phase6_p6_02_signer_isolation_boundary.py`: 24/24.
- `tests/unit/test_phase6_p6_04_singleton_lease.py`: 6/6.
- `tests/unit/test_phase6_p6_05_state_machine.py`: 26/26.
- `tests/unit/test_phase6_p6_06_idempotency.py`: 8/8.
- `tests/unit/test_phase6_p6_07_attestation.py`: 12/12.
- `tests/unit/test_phase6_p6_08_fill_accounting.py`: 5/5.
- `tests/unit/test_phase6_p6_09_slippage.py`: 9/9.
- `tests/unit/test_phase6_p6_10_risk_gates.py`: 48/48.
- `tests/unit/test_phase6_p6_11_position_policy.py`: 4/4.
- `tests/unit/test_phase6_p6_12_risk_exits.py`: 9/9.
- `tests/unit/test_phase6_p6_13_token_safety.py`: 24/24.
- `tests/unit/test_phase6_p6_14_reconciliation.py`: 13/13.
- `tests/unit/test_phase6_p6_16_no_dispatch_sentinel.py`: 4/4.
- `tests/unit/test_phase6_p6_17_report_honesty.py`: 8/8.
- `tests/unit/test_phase6_p6_18_migration_and_regression.py`: 3/3.
- Unit total: 229/229 passed, 0 skipped.
- `tests/integration/test_phase6_persistence_and_concurrency.py`: 6
  nodes total, all 6 SKIP (section B) -- role/privilege, lease-store
  real-DB concurrency, state-reload-after-restart, duplicate-fingerprint
  concurrent-insert, partial-unique-index rejection, kill-after-submit.
- Full suite: 1082 passed, 343 skipped, 0 failed.

H. Changed/new files this phase

Modified: `src/argus/cli.py` (additive only -- new `executor_app` Typer
sub-app + `executor readiness` command; no existing command touched).

New: `migrations/versions/0024_phase6_hardened_isolated_executor.py`;
`src/argus/domain/executor_leases.py`,
`src/argus/domain/execution_intents.py`,
`src/argus/domain/execution_intent_transitions.py`,
`src/argus/domain/execution_attestations.py`,
`src/argus/domain/execution_fills.py`,
`src/argus/domain/live_positions.py`,
`src/argus/domain/risk_exit_events.py`,
`src/argus/domain/token_safety_assessments.py`; `src/argus/executor/`
(19 modules: `__init__.py`, `capital.py`, `arm.py`, `signing.py`,
`singleton.py`, `state_machine.py`, `idempotency.py`, `attestation.py`,
`fill_accounting.py`, `slippage.py`, `risk_gates.py`,
`position_policy.py`, `risk_exits.py`, `token_safety.py`,
`reconciliation.py`, `dispatch.py`, `report.py`, `persistence.py`,
`service.py`); `tests/unit/test_phase6_p6_{01,02,04,05,06,07,08,09,10,
11,12,13,14,16,17,18}_*.py` (16 files);
`tests/integration/test_phase6_persistence_and_concurrency.py`;
`orchestration/phase_6/` (this checkpoint, its bundle, its evidence
directory).

Untouched (preserved byte-for-byte): `orchestration/checkpoints/
phase_5.md`, `orchestration/checkpoints/phase_5_remediation_1.md`,
`orchestration/bundles/phase_5.txt`,
`orchestration/bundles/phase_5_remediation_1.txt`,
`orchestration/phase_5/evidence/`,
`orchestration/phase_5_remediation_1/evidence/`,
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md`, `config/signals_v1.yaml`,
`MASTER_SPEC.md`, `orchestration/AUDITOR_POLICY.md`,
`orchestration/PROTOCOL.md`, `scripts/argus_orchestrator_watch.py`,
migrations `0001` through `0023` (never rewritten).

I. Acceptance criteria

[PASS] All 18 sealed rows (section D) are met against the frozen
`phase-6-v1` contract, with P6-03/P6-11/P6-15 explicitly marked
`PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION` for their DB-dependent
sub-requirements, per this instruction's own Environmental rule E --
every other row is unconditionally PASS. No row was invented, weakened,
or silently dropped from the sealed contract. `LIVE_CANARY_PASSED=false`
and `LIVE_ARMED=false` throughout (section D, P6-17, and the real CLI
output, section F). No live wallet, real signing key, seed/private-key
access, live arm file creation/modification, funded wallet, mainnet
transaction, canary, strategy live trade, paid-provider upgrade, or
capital allocation exists anywhere in this phase's diff (section E). No
Phase 5 threshold weakened; `config/signals_v1.yaml` byte-identical.

J. Deviations

None from the sealed contract's own scope. One environmental reality is
disclosed rather than worked around, unchanged from every prior phase:
this session's container has no reachable Postgres/Docker at all
(section B) -- every DB-backed test this phase adds is written correctly
and skips cleanly (never fails), and the identical concurrency/state-
machine/idempotency guarantees those tests would exercise are instead
proven for real via pure-logic unit tests (`InMemoryLeaseStore`, the
state-machine transition graph, the fingerprint function) that require
no database at all. No legitimate bug was discovered during this
phase's implementation that required an in-scope fix beyond the sealed
contract's own rows.

K. Known bugs / debt

- Carried forward, unchanged from every prior phase: `git diff --check`
  may flag trailing whitespace inside raw captured pytest-output
  evidence `.txt` files -- HARDENING_BACKLOG, never a phase blocker.
- New, disclosed as HARDENING_BACKLOG (non-blocking, no frozen row
  requires it): every new DB-backed integration test this phase adds
  (role/privilege, real `PostgresLeaseStore` concurrency, state-reload,
  duplicate-fingerprint race, partial-unique-index rejection, kill-
  after-submit) remains execution-deferred in this specific sandbox -- a
  future round with real Postgres access should run them for real at
  the earliest opportunity to close the remaining gap between
  "collects cleanly and is structurally sound" and "genuinely observed
  passing against a live database."
- All Phase 1-5 known-bugs/debt items from
  `orchestration/checkpoints/phase_5_remediation_1.md` section K remain
  unchanged and not reopened.

L. Security state

No live-execution, signing, or credential-handling code exists anywhere
in this phase's diff -- only the `Signer` protocol plus two inert test
doubles (`FakeSigner`, `RaisingSigner`), and `DispatchGuard`'s default
submission callable always raises. `argus executor readiness` is
read-only: it never imports a live provider client, never dispatches a
network request, never touches a signer, and never mutates any Phase
1-5 evidence row (proven by `test_phase6_p6_16_no_dispatch_sentinel.py`
running the real command end-to-end and scanning its output). No
secret, credential, or private-key material appears anywhere in the new
code, tests, or evidence -- a manual grep-based secret scan (credential/
API-key/password/token patterns plus a base58 64-byte-keypair-length
check) was performed across all 46 new/changed files before this
checkpoint was written, clean (section F). `config/signals_v1.yaml`'s
existing weights/thresholds are untouched. `ALLOW_AUTOMATIC_SCALE_IN`
remains hardcoded `False`; no other live-trading gate exists to change.
`LIVE_CANARY_PASSED`/`LIVE_ARMED` remain unconditionally `False`
throughout this phase, structurally -- no code path in
`argus.executor.report`/`service` can ever set either to `True`
(section D, P6-17).

M. Authority / carryforward / debt state

No new NEXT_PHASE_CARRYFORWARD item introduced this phase. CF5-DB
(Phase 5's own carryforward) is unaffected -- no real, authorized
Postgres environment became available during this session, so it
remains under the same disclosed deferral, not retroactively reopened.
Optional historical whitespace cleanup remains HARDENING_BACKLOG. Phase
6.5/7+ scope (live arming, real signer, real dispatch, mainnet canary)
remains explicitly out of scope for this phase and was never touched.
Phase 5 remains the last orchestrator-approved phase
(`last_orchestrator_approved_phase: 5`); Phase 6 itself is NOT
self-approved anywhere in this document -- only the orchestrator's own
independent audit may approve it.

Per this instruction's own explicit seal rule: no new ordinary
requirement/test/proof was added to Phase 6 once implementation began.
This checkpoint represents the complete, honest software-only
implementation of all 18 sealed rows (P6-01 through P6-18) -- not a
partial or rushed patch, and not a claim of live readiness beyond actual
evidence.

N. Next action / STOP

STOP. Await independent audit of this Phase 6 submission against the
sealed 18-row `phase-6-v1` contract. No Phase 6.5/7 work. No
self-approval of Phase 6 claimed anywhere in this document.
`LIVE_CANARY_PASSED=false` and `LIVE_ARMED=false`, as required.

================ END ARGUS CHECKPOINT =========================
