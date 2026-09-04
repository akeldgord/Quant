# ARGUS Orchestrator Instructions

**OWNER: ARGUS ORCHESTRATOR.** The implementation agent must not modify this file. Execute only the ACTIVE instruction below. `MASTER_SPEC.md` v2.0 remains authoritative. This instruction is a bounded second remediation after the required Phase Failure Root-Cause Review of `argus-final-spec-recovery-001`.

---

INSTRUCTION_ID: argus-final-spec-recovery-002
ISSUED_AT: 2026-09-04T21:35:00Z
TARGET_COMMIT: 7cca4094d7672759b1023733a810f552f1109040
AUTHORIZED_ACTION: EXECUTE_BOUNDED_FINAL_RECOVERY_REMEDIATION_FOR_FOUR_CONFIRMED_ROOT_CAUSES_ONLY
AUTHORIZED_PHASE: 11
APPROVES_PHASE: NONE
STATUS: ACTIVE

# 1. Decision and scope lock

The independent final audit of `argus-final-spec-recovery-001` at `TARGET_COMMIT` found that the first recovery did substantial valid work but did **not** satisfy the sealed final-recovery contract. The human operator has authorized a second, narrowly bounded remediation after completion of the required Phase Failure Root-Cause Review.

Do **not** reopen already-proven work for redesign. The following items are treated as CLOSED unless your changes create a concrete regression:

- FSR-02 core confirmed-chain actual-fill reconstruction/restart behavior;
- FSR-05 Phase 7 forward-information implementation;
- FSR-06 Phase 8 convergence cutoff/outcome-comparison implementation;
- FSR-07 Phase 9 four-family predation implementation;
- FSR-10 Phase 11 right-censoring;
- FSR-11 purged + embargoed temporal splitting.

This remediation exists only to fix:

1. **R2-01 / FSR-01:** missing integrated canary-capable executor path;
2. **R2-02 / FSR-04 + FSR-09:** knowledge-time leakage from later-created/backfilled specialist/derived rows in Phase 10/11;
3. **R2-03 / FSR-08:** Phase 10 evaluates arbitrary strategy exits using a fixed 5-minute executable probe rather than executable evidence contemporaneous with the strategy's actual entry/exit trigger times;
4. **R2-04 / FSR-15 + FSR-16:** non-hermetic integration tests plus incorrect final evidence/handoff/provenance packaging.

FSR-03 PostgreSQL 17 remains an external environment validation requirement. Make **one bounded attempt** to run it if the environment has changed. Do not waste the session retrying the same blocked Docker/PGDG path. If still externally blocked, preserve `FINAL_RECOVERY_ENVIRONMENT_BLOCKED` with exact evidence. PostgreSQL 16 is never a substitute PASS.

Phase 6.5 remains forbidden. This instruction does **not** authorize a mainnet canary, live arming, capital, paid-provider use, a funded wallet, use/readout of a real operator key, or any real transaction signing/broadcast.

# 2. Required written justification for remediation round > 1

This section satisfies the project's mandatory seven-part no-moving-goalposts test.

## R2-01 — integrated executor path

1. **Exact blocker:** real signer, broadcaster, confirmation reconciler, and executor process exist separately, but no production executor path progresses one execution intent through attestation -> signing -> submission -> persisted signature/state -> confirmation reconciliation. `argus.executor.main` currently performs startup/readiness only and exits.
2. **Classification:** SPEC_BLOCKING.
3. **Frozen requirement:** FSR-01 required proof #4 and its explicit PASS condition: the executor must be capable of hosting Phase 6.5 later **without new executor plumbing**.
4. **Concrete consequence:** a human-authorized canary would still require new implementation work to connect the components, so original-spec software canary-readiness is false.
5. **Why not caught before implementation:** this is a defect in the first recovery's implementation of FSR-01; the pre-recovery audit could only identify the missing signer/submission boundary, not inspect code that did not yet exist.
6. **Why not backlog/deferred:** this is the exact central FSR-01 acceptance proof, not optional hardening.
7. **No backlog promotion:** no new live feature, strategy, UI, provider, or safety gate is being added; only the frozen end-to-end executor seam is being completed.

## R2-02 — knowledge-time leakage

1. **Exact blocker:** Phase 10/11 historical-decision code recomputes Phase 9 at historical `as_of=T` during the current run, persists specialist rows with `created_at=computed_at` (later than T), then loaders select by `as_of=T` without enforcing source/knowledge-time provenance. Tests cover later `as_of` rows but not later-created/backfilled rows for the same historical cutoff.
2. **Classification:** SAFETY_OR_INTEGRITY_BLOCKING and SPEC_BLOCKING.
3. **Frozen requirement:** FSR-04 explicitly distinguishes event time, observation time, record creation/knowledge time, and research cutoff; it explicitly forbids a later-created classification leaking backward merely because underlying events are old. FSR-09 requires Phase 11 features known at the observation time.
4. **Concrete consequence:** Phase 10 strategy classification and Phase 11 features can use information reconstructed/recorded later while being presented as available at an earlier decision time, invalidating causal research claims.
5. **Why not caught before implementation:** the first recovery added the per-decision-time recomputation path; only post-build tracing showed that persistence `created_at=now` and loaders keyed only on historical `as_of` left a second leakage path.
6. **Why not backlog/deferred:** causal point-in-time truth is a core integrity requirement and was explicitly frozen in FSR-04/09.
7. **No backlog promotion:** this does not require new research features; it repairs the timestamp/provenance semantics of already-authorized derived features.

## R2-03 — wrong Phase 10 executable time

1. **Exact blocker:** Phase 10's primary result uses `PRIMARY_EXECUTABLE_HORIZON = "5m"` for every matched trade, even when the strategy's actual exit trigger occurs at a different time; C/D/E may also enter at a decision time different from the original source wallet's fill.
2. **Classification:** SAFETY_OR_INTEGRITY_BLOCKING and SPEC_BLOCKING.
3. **Frozen requirement:** FSR-08 requires contemporaneous executable quote/reverse-quote/shadow-fill evidence for the strategy's **entry and exit** decision times and forbids mark-price fallback.
4. **Concrete consequence:** a trade exiting one hour after entry can be scored using the five-minute sell quote, so reported executable return is not the return of the strategy being tested.
5. **Why not caught before implementation:** the first recovery correctly replaced the mark-price primary field with real executable data, but the post-build audit traced the specific horizon selection and discovered it was real data from the wrong time.
6. **Why not backlog/deferred:** using the correct strategy entry/exit execution evidence is the central FSR-08 acceptance condition.
7. **No backlog promotion:** no new strategy or data source is required; the existing Phase 4/5 quote-probe evidence must be matched correctly or the trade must be reported as lacking executable evidence.

## R2-04 — full-suite/evidence contract

1. **Exact blocker:** 21 integration tests remain failing due shared-database cross-test pollution; final FSR files/handoff do not use the exact required paths/status; the final checkpoint did not STOP; the final recovery commit did not have the ARGUS instruction trailer as its terminal paragraph.
2. **Classification:** SPEC_BLOCKING.
3. **Frozen requirement:** FSR-15 requires `0 failed`; FSR-16 requires exact final evidence paths/handoff fields/STOP and terminal commit trailer discipline.
4. **Concrete consequence:** the repository cannot demonstrate a deterministic clean full-suite run or a trustworthy final control-plane handoff.
5. **Why not caught before implementation:** these are defects in the first recovery's final testing/evidence implementation and only exist after that recovery ran.
6. **Why not backlog/deferred:** literal FSR-15/16 pass criteria were not met.
7. **No backlog promotion:** fix only test isolation and exact recovery evidence/provenance; do not expand test scope or redesign production queries merely to make tests convenient.

# 3. R2-01 — complete one integrated executor pipeline

## 3.1 Required architecture

Reuse the existing modules. Do not create a second state machine, second signer, second submission client, or second confirmation parser.

Add one production executor orchestration seam inside `argus.executor` (name is your implementation choice, but it must be a real callable used by the executor process) that can execute **one already-authorized execution intent** through the existing sequence:

1. load/create the canonical execution intent and acquire/validate singleton fencing;
2. run the existing risk/safety preconditions required by Phase 6 for the provided typed intent;
3. move through the existing legal state-machine transitions;
4. obtain/accept the existing Jupiter unsigned transaction/order result through the existing provider abstraction;
5. deserialize/construct the `UnsignedTransactionShape` needed by `attest_transaction` from the actual unsigned transaction/order evidence used for execution — do not allow a caller to assert a passing shape unrelated to the transaction bytes being signed;
6. require `attest_transaction(...).all_passed` before the signer can be invoked;
7. invoke the injected `Signer` seam;
8. invoke the injected submission seam exactly once for a new idempotency fingerprint;
9. persist the returned transaction signature and `SUBMITTED` state before confirmation polling;
10. invoke/reuse `reconcile_submitted_fill` for confirmed-chain outcome reconstruction;
11. on restart, if the signature was already persisted, reconcile that same signature and **never blindly resubmit**;
12. terminal confirmed/failed intents remain idempotent.

The production executor process must be able to host this seam. It may remain inert by default and MUST remain impossible to run live under repository defaults because capital limits are zero and Phase 6.5 has not authorized an arm state. However, a later human canary may require only operator configuration/credentials/arm authorization — **not another code change connecting signer/submission/reconciliation**.

Do not add an automatic copy-signal trading daemon merely to satisfy this item. A single-intent executor command/mode or equivalent executor-only entry is sufficient if it exercises the real production plumbing and stays behind the existing executor identity and human gates.

## 3.2 Isolation and security

- `api`, research packages, ordinary CLI analytical commands, ingestion, and shadow workers must not import/resolve `FileKeypairSigner` or `SolanaSubmissionClient`.
- Only the executor deployment identity receives the secret mount/path.
- No Docker socket, privileged mode, host root mount, or equivalent bypass.
- No secret bytes in logs, DB, exceptions, reports, checkpoints, tests, fixtures, or Git.
- Wrong/missing key config fails closed before any live-capable dispatch.
- Default capital remains exactly zero.
- `LIVE_ARMED=false` and `LIVE_CANARY_PASSED=false` throughout this remediation.

## 3.3 Mandatory R2-01 tests

At minimum add focused tests proving:

- `executor_e2e_safe_synthetic_intent`: ephemeral test key/fake signer + fake unsigned transaction + fake submission + fake confirmed-chain provider; intent traverses attestation -> signing -> one submission -> persisted signature -> confirmation -> one canonical fill;
- `attestation_failure_never_signs_or_submits`;
- `signing_failure_never_submits`;
- `submission_response_persisted_before_confirmation`;
- `crash_after_submission_restart_reconciles_same_signature_without_second_submit`;
- `terminal_restart_noop`;
- `missing_or_bad_operator_key_fails_closed`;
- AST/import boundary still proves non-executor code cannot import live-capable modules;
- deployment/permission test proves API/research service cannot read the synthetic executor-secret path under the intended container/OS model as far as the available environment permits; if container runtime is unavailable, keep the structural/compose permission test and identify the runtime check under FSR-03 rather than pretending it ran.

A unit test that manually advances states without invoking the integrated executor seam does **not** satisfy this item.

# 4. R2-02 — fix knowledge-time semantics once, then use it everywhere needed

The repaired system must distinguish **historical reconstruction cutoff** from **when a derived row was physically written**.

Do not solve this by either of these incorrect shortcuts:

- selecting derived rows only by `as_of=T` while ignoring when their contributing evidence became known;
- rejecting every historical reconstruction solely because the derived row itself was physically persisted today.

## 4.1 Required semantic model

For any derived specialist/classification used at decision time `T`, the system must be able to prove that **all contributing source evidence** was knowable by `T`.

Implement one explicit reusable provenance/knowledge-time mechanism. The exact schema is your choice, but the persisted/reconstructed derived result must carry enough machine-checkable information to distinguish:

- `as_of` / economic decision cutoff T;
- physical derived-row `created_at` / reconstruction time;
- maximum contributing source knowledge time (or equivalent evidence-manifest proof) used to construct that result;
- algorithm/config version.

A historical replay computed today may be used as a reconstruction of state at T **only if** every contributing raw/intermediate source record itself satisfies the canonical knowledge rule at T and the derived record explicitly proves that fact. Merely setting `as_of=T` is never sufficient.

Prefer reusing the existing evidence-manifest / `known_by_cutoff` architecture. Do not duplicate five separate ad hoc timestamp rules.

## 4.2 Phase 9/10/11 application

- Phase 9 computations at historical T must source only rows whose event/effective and creation/knowledge times are <= T.
- Any persisted backfilled `WalletSpecialistScore` intended for historical replay must retain explicit provenance that its source evidence was eligible by T.
- Phase 10 `load_specialist_scores_as_of` must reject any score that cannot prove eligibility at that exact strategy decision time.
- Phase 11 `load_discovery_effect_size_by_wallet` must reject any score that cannot prove eligibility at the observation time.
- Do the same for any other Phase 10/11 derived specialist/classification row on the actual affected path.
- Do not alter already-correct FSR-10/11 label/split behavior except for necessary version/provenance plumbing.

## 4.3 Mandatory mutation tests

The key test that was missing must now exist:

1. seed source evidence E1 known by T;
2. build the Phase 9 specialist/classification reconstruction for T;
3. capture canonical Phase 10 decision and Phase 11 feature values at T;
4. append a **new source row after T whose economic/effective time is backdated to <= T but whose `created_at`/knowledge time is > T**;
5. rebuild the historical reconstruction for the same T under a fresh algorithm/config identity if needed to defeat idempotent cache reuse;
6. assert byte-equivalent semantic Phase 10 decision inputs and Phase 11 feature inputs/results;
7. assert the new row becomes visible only at a later legitimate cutoff >= its knowledge time.

Also add a test where a `WalletSpecialistScore` row itself is physically created after T with `as_of=T`; prove that the loader cannot accept it merely because `as_of` matches unless its source-knowledge provenance proves eligibility.

# 5. R2-03 — Phase 10 must price the strategy that actually ran

The current fixed `PRIMARY_EXECUTABLE_HORIZON="5m"` selection is forbidden as a universal Phase 10 primary return.

## 5.1 Correct matching rule

For each `MatchedTrade`, primary executable performance must be derived from executable evidence contemporaneous with **that strategy's own entry trigger and exit trigger**.

Use existing Phase 4/5 `shadow_quote_probes` and shadow fill/position evidence. Do not query today's Jupiter for historical prices and do not create synthetic historical quotes.

### Entry side

- Strategy A/B source-entry: the original shadow entry fill may be used only when its actual entry timing is the strategy entry timing represented by the trigger.
- Strategy C/D confirmation-entry: do **not** reuse the leader's earlier source fill as the strategy entry. Match an eligible `ENTRY_DELAY` probe/fill to the confirmation trigger time within a deterministic configured tolerance. If no eligible contemporaneous entry evidence exists, the trade is `FAILURE_NO_EXECUTABLE_EVIDENCE`/insufficient — never backfilled from the earlier leader price.
- Strategy E convergence-entry: there may be no wallet-specific shadow intent. Unless existing Phase 4/5 evidence can be deterministically matched to the convergence decision time and intended notional without inventing a quote, report no executable evidence. Do not manufacture a value merely to keep Strategy E populated.

### Exit side

- Match an eligible `REVERSE_EXECUTABLE` probe whose **actual terminal/response timing** is contemporaneous with `matched.exit.at` within the configured staleness/tolerance.
- Use `actual_elapsed_seconds_from_first_seen` and/or expose the probe's actual timestamps in the loader so matching is based on actual observation timing, not just label text.
- Do **not** select by hardcoded `5m`, `30m`, `1h`, etc. unless that probe's actual timing is the deterministic best valid match for the strategy's actual exit time.
- If no contemporaneous reverse probe exists, report `FAILURE_NO_EXECUTABLE_EVIDENCE` rather than substituting a different-horizon quote or the mark price.
- Explicit terminal quote failures (`NO_ROUTE`, `INSUFFICIENT_LIQUIDITY`, `PRICE_IMPACT_EXCESSIVE`, `QUOTE_FAILED`, `TOKEN_RESTRICTED`) that match the strategy exit time remain genuine failed executable outcomes.

### Return construction

The primary trade return must be computed from the matched strategy-entry executable amount and matched strategy-exit executable amount, with recorded quote fees/impact/cost evidence where available. Keep mark return in separate descriptive fields only.

The final trade record must persist enough provenance to audit:

- matched entry evidence ID/kind/actual time;
- matched exit evidence ID/kind/actual time;
- strategy trigger entry/exit times;
- timing deltas/tolerance outcome;
- executable failure class or missing-evidence reason.

## 5.2 Mandatory R2-03 tests

At minimum:

- **one-hour-exit trap:** source entry at 12:00, successful 5m reverse quote with return X, successful 1h reverse quote with different return Y, strategy exits ~1h; primary return must be Y, never X;
- **no-exit-time-evidence:** only 5m probe exists but strategy exits 1h; primary return must be missing/failure, not 5m;
- **confirmation-entry trap:** leader fill at 12:00 differs from eligible entry-delay executable evidence near confirmation at 12:03; Strategy C/D must use the confirmation-time entry evidence, never the leader fill;
- **confirmation-entry-no-evidence:** no eligible entry probe near confirmation -> no executable result;
- unsellable matching exit probe remains a failed executable outcome;
- fixed-haircut mark fields cannot enter primary executable return;
- future-created/backfilled specialist classification cannot alter Strategy B/D decision at historical T (R2-02 regression);
- deterministic A-E behavior with insufficient executable samples allowed as a valid result.

If correcting this causes most/all strategy results to become `INSUFFICIENT_EXECUTABLE_SAMPLE`, that is an acceptable research result. Do not loosen timing tolerance or substitute mark prices to rescue sample size.

# 6. Versioning after newly discovered contamination

The independent audit establishes that `synthetic_super_wallet_v2` and `order_flow_prediction_v2` are not safe to present as current corrected results.

Do not delete or rewrite them.

Add additive invalidation/supersession entries:

- `PHASE_10_SYNTHETIC`: invalidate/supersede `synthetic_super_wallet_v2` -> corrected new version (normally `synthetic_super_wallet_v3`);
- `PHASE_11_PREDICTION`: invalidate/supersede `order_flow_prediction_v2` -> corrected new version (normally `order_flow_prediction_v3`).

Reasons must explicitly name:

- Phase 10 wrong strategy-time executable matching + specialist knowledge-time issue;
- Phase 11 specialist knowledge-time issue.

Do not invalidate Phase 8 v2 or Phase 9 v2 unless your bounded remediation discovers a concrete regression caused by your own changes. Do not retune models/thresholds/strategies.

Re-run corrected Phase 10 and Phase 11 only under their new algorithm versions. Old v1/v2 rows remain queryable for audit but excluded from default current reports.

# 7. R2-04 — make integration testing hermetic

The first recovery's remaining 21 failures came from cross-test pollution in a shared long-lived dev database. Fix the test infrastructure, not production semantics/assertions.

Preferred architecture: a central integration-test fixture in `tests/integration/conftest.py` (or equivalent shared mechanism) that gives each integration test module a unique clean database, migrates it to head, configures all roles/connections for that module to use it, and drops it after the module. An equivalently strong per-test isolated database/schema design is acceptable.

Requirements:

- full `tests/integration` must be reproducible from a dirty developer cluster and from a clean cluster;
- one test module's rows cannot be visible to another module unless an explicit cross-module fixture says so;
- do not weaken production queries to filter on test-only IDs merely to hide pollution;
- do not weaken assertions;
- do not add broad truncate/delete behavior that could ever run against non-test databases without a hard test-database guard;
- parallel execution, if supported, must still use unique namespaces/databases;
- test database names must be unmistakably test-only and randomized/unique.

Mandatory proof on PostgreSQL 16 if that remains the available local server:

1. run the full integration suite once from a fresh test namespace: 0 failed;
2. run it a second time without manually cleaning the cluster between runs: 0 failed;
3. run the previously failing 21-test subset after the first full run: 0 failed;
4. verify no test data was written to the ordinary developer `argus` database.

Then run full unit/golden/replay and quality checks.

# 8. PostgreSQL 17 disposition

Attempt genuine PostgreSQL 17 once using the repository's canonical path or another genuine PG17 instance available in the environment.

If it works, run the FSR-03 matrix on PG17 and record exact commands/results.

If Docker daemon/PGDG access is still externally blocked:

- do not repeatedly retry;
- retain exact disposition `FINAL_RECOVERY_ENVIRONMENT_BLOCKED`;
- list every PG17-required test not executed;
- do not claim `LIVE_READY_SOFTWARE=true`;
- do not call PG16 a substitute PASS;
- complete every non-PG17 item in this remediation anyway.

# 9. Exact final evidence contract — no naming deviations

Create/replace the exact files required by the original sealed FSR-16 contract:

- `orchestration/checkpoints/final_spec_recovery.md`
- `orchestration/bundles/final_spec_recovery.txt`

Do not substitute `fsr15_16_*`, `final_recovery_v2_*`, or another filename in the final handoff.

`final_spec_recovery.md` must:

- begin with `================ ARGUS ORCHESTRATOR CHECKPOINT ================`;
- end with `================ END ARGUS CHECKPOINT =========================`;
- name original contaminated base `ea77dd55b1e6be91b61b2f8b37e1d70449a3cb30`;
- name remediation-001 audited head `7cca4094d7672759b1023733a810f552f1109040`;
- name final remediation-002 implementation/evidence commits;
- include MASTER_SPEC hash;
- include a final matrix mapping FSR-01..FSR-16 and R2-01..R2-04 to exact code/tests/evidence and PASS/FAIL/ENVIRONMENT_BLOCKED;
- include exact test commands and counts, including failed/skipped counts;
- include PG17 status/evidence;
- include Phase 10 v3 and Phase 11 v3 sample/report results or honest insufficient-sample results;
- list all invalidated algorithm versions (v1 and newly invalidated v2 where applicable);
- record security state: Phase 6.5 not run, no mainnet signature/broadcast, no real key accessed, no arm file modified, capital defaults zero, no paid provider, no funded wallet;
- state `LIVE_CANARY_PASSED=false` and `LIVE_ARMED=false`;
- set `LIVE_READY_SOFTWARE=true` only if every non-environment software requirement passes **and** PG17 has passed; if PG17 remains blocked, it must be false/blocked;
- finish with an explicit `STOP FOR INDEPENDENT FINAL AUDIT` before the end marker.

`orchestration/bundles/final_spec_recovery.txt` must be the matching machine-readable/review bundle, not a prose placeholder.

Update `docs/BUILD_STATE.md` by appending the remediation-002 status; do not rewrite historical claims. Update `docs/DECISION_LOG.md` with this root-cause remediation and exact final status.

Replace `orchestration/AGENT_HANDOFF.md` with exactly one final handoff containing:

- new HANDOFF_ID;
- `CURRENT_PHASE: 11`;
- `WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION`;
- `LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-final-spec-recovery-002`;
- `CHECKPOINT_PATH: orchestration/checkpoints/final_spec_recovery.md`;
- `BUNDLE_PATH: orchestration/bundles/final_spec_recovery.txt`;
- actual test status;
- `WORKING_TREE: clean`;
- `ORCHESTRATOR_REVIEW_REQUIRED: FINAL_ORIGINAL_SPEC_AUDIT` only if all FSR/R2 requirements including PG17 pass; otherwise, if PG17 is the sole remaining blocker, `ORCHESTRATOR_REVIEW_REQUIRED: FINAL_RECOVERY_ENVIRONMENT_BLOCKED`; if any software/test blocker remains, name it explicitly and do not claim completion.

# 10. Required final test matrix

Before handoff, run all possible checks in this environment:

1. focused R2-01 executor integration tests;
2. focused R2-02 point-in-time/backfill mutation tests;
3. focused R2-03 strategy-time executable-evidence tests;
4. full `tests/unit`;
5. full `tests/golden`;
6. full `tests/replay`;
7. full `tests/integration` twice under isolated test DB infrastructure;
8. authentic real-chain fixture validation;
9. Alembic single-head;
10. zero -> head migration on the available DB; PG17 specifically only counts if genuine PG17;
11. required downgrade/re-upgrade migration test(s);
12. `ruff check`;
13. `ruff format --check`;
14. `mypy` canonical source scope;
15. secret scan;
16. checkpoint/bundle validators;
17. dependency/lock consistency.

For every check, record exact command and counts. `0 failed` is mandatory for all tests that actually run. No unexplained skip relevant to R2-01..R2-04 is allowed.

# 11. Commit/provenance rules for this remediation

Do not rewrite/rebase/force-push prior history just to repair old trailer defects.

Every **new Claude implementation commit under this instruction** must end with exactly one final paragraph:

`ARGUS-INSTRUCTION-ID: argus-final-spec-recovery-002`

Nothing may follow it. If you include `Co-Authored-By` or a Claude session URL, place those paragraphs **before** the ARGUS trailer. Verify every new commit with:

`git log -1 --format=%B | git interpret-trailers --parse`

and verify the parsed terminal trailer is exactly the instruction ID above.

Do not modify `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`.

# 12. Mandatory start and stop behavior

Before implementation:

1. `git status --porcelain` must be clean;
2. `git pull --ff-only`;
3. verify remote HEAD is the instruction-only commit containing this instruction;
4. verify that commit's direct parent is exactly `TARGET_COMMIT` `7cca4094d7672759b1023733a810f552f1109040`;
5. verify the instruction commit changes only `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`;
6. read `MASTER_SPEC.md`, `docs/BUILD_STATE.md`, `docs/DECISION_LOG.md`, `orchestration/PROTOCOL.md`, `orchestration/AUDITOR_POLICY.md`, this instruction, and `orchestration/AGENT_HANDOFF.md`;
7. build a local R2 acceptance matrix before changing code.

Then implement the entire bounded remediation in one batch. Do not stop between R2-01..R2-04.

At the end, push final evidence/handoff, verify local/remote HEAD equality and clean worktree, then **STOP FOR INDEPENDENT FINAL AUDIT**. Do not self-approve. Do not perform Phase 6.5.