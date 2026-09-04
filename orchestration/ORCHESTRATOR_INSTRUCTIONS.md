# ARGUS Orchestrator Instructions

**OWNER: ARGUS ORCHESTRATOR.** The implementation agent must not modify this
file. Execute only the ACTIVE instruction below. `MASTER_SPEC.md` v2.0 remains
the authoritative original implementation contract except where this instruction
explicitly freezes a recovery interpretation needed to repair the completed
build. Read `orchestration/AUDITOR_POLICY.md` before acting.

---

INSTRUCTION_ID: argus-final-spec-recovery-001
ISSUED_AT: 2026-09-04T16:34:00Z
TARGET_COMMIT: ea77dd55b1e6be91b61b2f8b37e1d70449a3cb30
AUTHORIZED_ACTION: EXECUTE_ONE_BATCHED_FINAL_ORIGINAL_SPEC_RECOVERY_ACROSS_PHASES_6_TO_11_ONLY
AUTHORIZED_PHASE: 11
APPROVES_PHASE: NONE
STATUS: ACTIVE

## Authority and decision

The human operator explicitly authorized one final batched recovery after an
independent end-to-end audit of final build commit
`ea77dd55b1e6be91b61b2f8b37e1d70449a3cb30` against the original frozen
`MASTER_SPEC.md` v2.0.

This is **not** authorization for Phase 6.5, a mainnet canary, live arming,
capital allocation, a real funded wallet, real-key access by the coding agent,
paid-provider use, or a strategy live trade. Phase 6.5 remains human-only and
must remain unperformed. Final required state after this recovery is:

- `LIVE_CANARY_PASSED = false`
- `LIVE_ARMED = false`
- `LIVE_READY_SOFTWARE = true` **only if every software/environment item in this
  sealed recovery contract that is required for canary readiness actually
  passes**; otherwise it must remain false/partial with the exact blocker named.

The repository's post-orchestrator Phase 7-11 work is preserved as historical
implementation evidence. Do not rewrite Git history or delete raw/research
observations. Repair derived logic additively and version the corrected outputs.

## Recovery contract seal — no moving goalposts

`RECOVERY_CONTRACT_ID: final-original-spec-recovery-v1`

The numbered requirements `FSR-01` through `FSR-16` below are the complete
ordinary blocking contract for this recovery. The builder must implement and
self-audit the entire matrix in one batch. After implementation starts, no new
ordinary acceptance criterion may be added. A newly discovered issue is blocking
only if it is:

1. a direct violation of `FSR-01..FSR-16` or the cited original
   `MASTER_SPEC.md` requirement, or
2. an immediate catastrophic safety/integrity defect.

Everything else is `HARDENING_BACKLOG` and must not delay final audit.

This is deliberately one recovery job, not six reopened phase loops. Do not
pause after each repaired phase. Implement the whole sealed contract, run the
full acceptance matrix, produce one final handoff, then STOP.

---

# A. Phase 6: finish genuine software canary-readiness without performing canary

## FSR-01 — Production-capable isolated executor process and signer boundary

**Original authority:** MASTER_SPEC Phase 6; sections 70-78, especially OS-level
key isolation, executor singleton, state machine, idempotency, transaction
attestation, and local signing interface.

The current software-only skeleton is insufficient to claim original-spec
`LIVE_READY_SOFTWARE=true`. Complete the production-capable executor boundary:

- provide a distinct executor process/service entry point, separate from
  research/API processes;
- provide a production-capable local signer adapter that can load signing
  material **only at runtime inside the executor identity from an external,
  operator-controlled path**;
- research/API/CLI analytical processes must have no permission/path to load or
  invoke that signer;
- provide a production-capable transaction submission/confirmation adapter
  suitable for the existing Solana/Jupiter architecture;
- keep all repository/default risk limits at zero;
- never create, request, read, display, log, commit, or use the operator's real
  signing key during this recovery;
- never create or modify the human arm file;
- never submit a real mainnet transaction.

Testing must use only synthetic/unfunded ephemeral key material or an inert fake
signer inside an isolated test fixture. The test key must never be persisted in
Git or checkpoint output.

**Required proof:**

1. executor process starts in an inert/dry-run test mode with fake transport and
   isolated fake signer;
2. API/research process cannot read the synthetic executor-secret path under the
   same OS/container permission model intended for production;
3. API/research code cannot resolve/invoke the production signer dependency;
4. executor can progress a fully safe synthetic intent through attestation ->
   simulated signing seam -> synthetic submission -> synthetic confirmation
   without any external network;
5. wrong/missing external key configuration fails closed before execution;
6. `compose.yaml` or the canonical deployment configuration contains a distinct
   executor service/process with least privilege; Docker socket/root-equivalent
   access must not defeat the intended secret boundary.

PASS only if the architecture is actually capable of hosting the human-authorized
Phase 6.5 canary later without new executor plumbing. The canary itself remains
forbidden here.

## FSR-02 — End-to-end confirmation reconciliation and actual-fill reconstruction

**Original authority:** sections 76-84 and Phase 6 mandatory acceptance:
`actual fill reconstructed from chain`, crash-after-submit reconciliation, no
blind retry.

Wire the current execution state machine to a real production-capable confirmed-
transaction reconciliation path. After a transaction signature is confirmed,
reconstruct canonical fill accounting from chain transaction/balance evidence,
not from the Jupiter quote.

Persist distinctly:

- quoted input/output;
- simulated input/output;
- actual input/output reconstructed from chain deltas;
- network fee;
- priority fee;
- tip;
- rent/account costs where observable;
- evidence reference / transaction signature / slot / confirmation state.

Confirmed chain evidence wins over quote/simulation. Missing evidence is NULL or
explicitly unresolved, never copied from the quote as a substitute.

**Required tests:**

- deterministic confirmed-transaction fixture where quoted != simulated !=
  actual and the actual chain delta wins;
- fee/tip/rent accounting fixture;
- ambiguous/missing transaction evidence -> `UNKNOWN`/unresolved, no fabricated
  fill;
- crash after synthetic submission before confirmation -> restart reconciles the
  same intent and never submits twice;
- confirmation already durable -> restart idempotently leaves one canonical
  confirmed execution/fill.

## FSR-03 — Close the real database/environment validation required before canary

**Original authority:** TECH-004 PostgreSQL 17, Phase 6 acceptance, and the
project's standing `PG17_COMPOSE_VALIDATION` deferral.

Run the completed recovery on a real PostgreSQL 17 instance via the repository's
canonical Docker Compose path or an equivalent genuine PostgreSQL 17 environment.
Do not call PostgreSQL 16 a substitute PASS.

Required environment validation:

- zero -> current Alembic head upgrade on PostgreSQL 17;
- repository role/privilege tests;
- Phase 5/6 DB-backed integration tests previously skipped for environment;
- execution singleton/fencing tests against the real DB;
- execution state-machine/idempotency/restart tests against the real DB;
- full DB-backed research persistence tests for corrected Phases 7-11 where
  applicable;
- downgrade/re-upgrade tests wherever repository convention requires them.

If the implementation sandbox still cannot access/run PostgreSQL 17 for a
purely external reason, complete all other recovery work and checkpoint exactly:

`FINAL_RECOVERY_ENVIRONMENT_BLOCKED`

with the exact failed command/error and list of tests not executed. Do **not**
claim final recovery PASS or `LIVE_READY_SOFTWARE=true`. Do not request secrets
or enable paid infrastructure to work around the environment.

---

# B. One reusable point-in-time firewall for Phases 7-11

## FSR-04 — Canonical knowledge-cutoff invariant

**Original authority:** CORE-001, CORE-003, CORE-004, sections 44, 85-101.

Implement one reusable point-in-time/knowledge-cutoff rule and use it throughout
corrected Phase 7-11 loaders/features/derived research. For a decision,
observation, classification, feature, edge, or report at time `T`, data may be
used only if it was genuinely knowable by ARGUS at or before `T`.

At minimum distinguish:

- economic/event time;
- ARGUS observation/first-seen time where available;
- record creation/knowledge time;
- requested research cutoff.

A later-created classification, score, cluster link, specialist label, market
snapshot, graph state, or derived record must never leak backward merely because
its underlying event occurred earlier.

Apply the invariant at minimum to:

- Phase 8 cluster/independence links;
- Phase 9 specialist/predation inputs;
- Phase 10 discovery/exit specialist classifications and convergence state;
- Phase 11 wallet-specialist features, graph state, tier state and token-state
  features;
- all corrected report `--as-of`/cutoff paths.

**Mandatory invariance tests:** build a result/featureset at cutoff `T`, append
future-only rows for every affected record family, rebuild the same cutoff, and
assert byte-equivalent canonical inputs/results (excluding non-semantic run IDs
or creation timestamps). Also assert the future row becomes visible only when a
later cutoff legitimately includes it.

---

# C. Phase 7-9 missing original-spec research outputs

## FSR-05 — Phase 7 forward information after leader must be real, versioned data

**Original authority:** Phase 7 report requires `forward information after
leader`.

The field may no longer be universally hardcoded NULL. For each Phase 7
leader->follower edge, compute a versioned forward-information-after-leader
summary from **existing Phase 4/5 point-in-time follower/executable outcome
records tied to the leader observations that created that edge**. Use executable
outcomes as primary when available. Do not manufacture values when no eligible
Phase 4/5 evidence exists.

Minimum stored/reported edge fields:

- eligible lead observations;
- observations with executable forward-outcome evidence;
- mean or otherwise canonical aggregate of the existing versioned Phase 5
  forward-information value over those eligible leader observations;
- sample count;
- missing-data reason/confidence when insufficient.

Do not invent causal interpretation. Missing evidence remains missing.

**Required tests:** fixture with eligible Phase 5 forward-information evidence
produces a deterministic non-null value; same edge without eligible evidence is
explicitly missing; future Phase 5 records beyond cutoff do not alter an earlier
edge report.

## FSR-06 — Phase 8 point-in-time convergence and required outcome comparisons

**Original authority:** Phase 8 requires effective independent-actor count,
expected overlap, empirical overlap probabilities, surprisal, calibration,
expected-confirmation windows, dog-that-didn't-bark events, and outcome
comparisons for ordinary overlap, high-surprisal overlap, rapid confirmation and
failed confirmation.

Fix the known cluster-link cutoff leak under FSR-04. Then implement the missing
outcome-comparison layer using only outcome evidence valid under the research
cutoff.

For each of the four original Phase 8 classes report at minimum:

- sample count;
- executable-outcome count;
- mean and median executable return where available;
- executable win rate where available;
- no-route/unsellable/missing-outcome rate;
- mark-return summary separately for descriptive use only.

Do not collapse these into an arbitrary 0-100 score. If executable evidence is
insufficient, report `INSUFFICIENT_EXECUTABLE_SAMPLE` rather than substituting
mark return.

**Required tests:** deterministic fixture containing all four classes with known
outcomes; correct class assignment and comparison statistics; cluster link
created after cutoff cannot change an earlier result; future outcome beyond
cutoff cannot be used early.

## FSR-07 — Complete Phase 9 predation inputs and counterfactual integrity

**Original authority:** Phase 9 counterfactual alpha + specialists; sections
58-61 where implemented by the current architecture.

The predation score must no longer silently omit price-impact evidence while
still presenting itself as complete. The corrected version must incorporate the
existing intended evidence families used by the current Phase 9 design:

- follower influx;
- price impact;
- leader-exit timing;
- repeated-pattern evidence.

Price impact must come from contemporaneous executable quote/market-impact
observations where they exist; do not infer it from a later chart. Missing price
impact must lower confidence or make the predation result explicitly partial —
never silently behave as zero/safe.

All matched-token controls, residual alpha and specialist classifications must
obey FSR-04 point-in-time cutoffs.

**Required tests:** one fixture per predation input changed independently and a
combined fixture; missing price-impact evidence is explicit; matched controls
exist at the same eligible historical time; future specialist/cluster evidence
cannot alter an earlier Phase 9 classification.

---

# D. Phase 10: replace backtest-theater outputs with original executable-return test

## FSR-08 — Synthetic Super-Wallet strategies use executable outcomes after realistic costs

**Original authority:** Phase 10 requires strategies A-E and comparison of
`executable return`, drawdown, win rate, profit factor, capital utilization and
failure rate after realistic costs.

The current nearest-historical-price + fixed `cost_bps` haircut is not an
acceptable primary Phase 10 executable result. Preserve it only as a separately
labeled descriptive mark/sensitivity metric if useful.

For each strategy A-E:

- specialist/convergence state must be the state known **as of that strategy
  decision time**, never the final run-cutoff classification;
- entry and exit primary performance must use contemporaneous executable quote /
  reverse-quote / shadow-fill evidence from the existing Phase 4/5 data model;
- explicit no-route, insufficient-liquidity, excessive-impact and quote-failure
  observations remain failures/missing executable outcomes — never dropped;
- realistic recorded fees/impact/costs must flow from actual quote/outcome
  evidence where available;
- if a strategy lacks enough executable observations, mark
  `INSUFFICIENT_EXECUTABLE_SAMPLE`; do not silently fall back to mark prices.

Required comparison outputs exactly retain the original Phase 10 dimensions:

- executable return;
- drawdown;
- win rate;
- profit factor;
- capital utilization;
- failure rate.

Do not automatically enable any winning strategy live.

**Required tests:** each of A-E on deterministic point-in-time fixtures; future
specialist reclassification cannot change a historical strategy decision;
quote != later mark price fixture proves executable result is used; unsellable
exit remains a failed executable outcome; fixed-haircut mark proxy cannot enter
the primary executable-return field.

---

# E. Phase 11: rebuild the dataset so every feature and label is causal

## FSR-09 — Feature timestamps: no future specialist or future market snapshot leakage

**Original authority:** CORE-001, SANITY-001/002, Phase 11 strict temporal
validation.

Correct Phase 11 feature construction so every feature is known at the
observation timestamp.

Specifically:

- `discovery_specialist_score`/related specialist features must be an as-of
  value known by the observation time, not a value computed once at final run
  cutoff and reused backward;
- token momentum/state must use the latest eligible snapshot **at or before** the
  observation time; a nearest snapshot after the observation is forbidden;
- graph/cluster/tier/wallet score inputs must satisfy FSR-04;
- any required feature without eligible pre-observation evidence is missing and
  handled under the existing family-specific missing-data rule; never use a
  future row to avoid missingness.

**Required tests:** future specialist-score mutation invariance; future-nearest
snapshot trap where a closer post-observation price must be ignored in favor of
an older pre-observation snapshot; no eligible pre-observation snapshot ->
feature missing, not future-filled.

## FSR-10 — Right-censor incomplete forward labels

**Original authority:** Phase 11 targets 5m/15m/30m/1h and CORE-001 truth.

For observation time `t`, horizon `H`, and dataset/knowledge cutoff `C`, a
negative label is valid only when the full label interval is observable:

`t + H <= C`

If `t + H > C`, the row is **right-censored for that horizon** and must be
excluded from that horizon's supervised evaluation/training or carry an explicit
censored state that is never treated as `False`.

Absence of an elite-wallet entry in an incomplete future window is not a
negative.

**Required tests:** positive within horizon, true negative with fully observed
window, event just after horizon, and observation whose horizon crosses cutoff;
the last must be censored/excluded, never `False`.

## FSR-11 — Purged + embargoed temporal validation

**Original authority:** Phase 11 `Use strict temporal validation`; section 101
prohibits random splits of overlapping temporal labels.

Replace simple chronological 70/30 splitting with a deterministic purged and
embargoed split for every horizon `H`.

For a split boundary `S`:

- training rows must have their complete label window end on or before `S`;
- rows whose label interval crosses `S` are purged from training;
- test rows must begin only after an embargo of at least `H` after `S`;
- no row may occur in both sets;
- no training label may depend on an event inside the test/embargo region;
- split metadata must persist boundary, horizon, purged count, embargo duration,
  train/test ranges and sample counts.

A stricter deterministic embargo is allowed; a weaker one is not.

**Required tests:** boundary-crossing label is purged; row inside embargo absent
from test; earliest test row satisfies embargo; mutation of test-period events
cannot alter training features/labels; class/sample sufficiency is evaluated
after purge/embargo, not before.

## FSR-12 — Phase 11 evaluation must be regenerated only from the corrected causal dataset

Keep the original four baselines and three model families unless a code change is
strictly required to consume corrected inputs. Do not tune them to recover a
preferred metric.

Re-run 5m/15m/30m/1h evaluation on the corrected causal dataset. Preserve the
existing `INSUFFICIENT_SAMPLE` behavior. Metrics from contaminated runs may not
be presented as current results.

Required report fields include dataset version, cutoff, feature-version IDs,
label version, split/purge/embargo metadata, model family, horizon, train/test
counts, class balance and existing evaluation metrics.

---

# F. Preserve history, invalidate contaminated derived runs, and reconstruct audit trail

## FSR-13 — Version and invalidate contaminated Phase 8-11 derived results without deleting them

**Original authority:** CORE-002 raw observations immutable, CORE-004
reproducibility, section 98 version everything.

Do not delete or rewrite raw/provider/chain evidence. Do not rewrite historical
Git commits/checkpoints. Add a deterministic invalidation/supersession mechanism
for derived Phase 8-11 runs produced by the known-leaky algorithms at or before
`TARGET_COMMIT`.

The corrected pipeline must:

- assign new algorithm/data-version identifiers to corrected Phase 8-11
  outputs;
- mark old affected derived runs as `INVALID_FOR_EVALUATION`, `SUPERSEDED`, or an
  equivalent explicit persisted state/reason;
- default current reports/model comparisons to corrected valid versions;
- keep archived invalidated runs queryable for audit;
- never silently relabel the old metrics as corrected.

**Required tests:** old run remains in DB but is excluded from default current
report; corrected version is selected; explicit archival query can retrieve the
old invalid run and reason; raw inputs are unchanged.

## FSR-14 — Truthful retroactive Phase 7-11 checkpoint/bundle reconstruction

**Original authority:** MASTER_SPEC sections 103-105.

Because the human explicitly allowed Claude to finish Phases 7-11 without the
normal orchestrator stops, do **not** fabricate that the historical per-phase
STOP/audit sequence occurred. Instead create new immutable post-build recovery
records, clearly labeled:

`RETROACTIVE_POST_BUILD_RECOVERY_CHECKPOINT — NOT A CONTEMPORANEOUS PHASE STOP`

Create at minimum:

- `orchestration/checkpoints/phase_7_final_recovery.md`
- `orchestration/bundles/phase_7_final_recovery.txt`
- `orchestration/checkpoints/phase_8_final_recovery.md`
- `orchestration/bundles/phase_8_final_recovery.txt`
- `orchestration/checkpoints/phase_9_final_recovery.md`
- `orchestration/bundles/phase_9_final_recovery.txt`
- `orchestration/checkpoints/phase_10_final_recovery.md`
- `orchestration/bundles/phase_10_final_recovery.txt`
- `orchestration/checkpoints/phase_11_final_recovery.md`
- `orchestration/bundles/phase_11_final_recovery.txt`

Each must map the original phase's build/report/acceptance requirements to the
**corrected** implementation and actual tests run, disclose the historical
leak/omission that was repaired, and preserve environmental limitations.

Do not overwrite existing historical checkpoint/bundle files.

---

# G. Final acceptance, tests, and handoff

## FSR-15 — Full repository regression and environment matrix

Before claiming recovery PASS run, at minimum:

1. full unit suite;
2. full integration suite with genuine PostgreSQL 17 per FSR-03;
3. all golden and replay suites;
4. Phase 1.5 and previously accepted phase-specific suites;
5. every new FSR-01..FSR-13 focused test;
6. Alembic single-head check and zero->head migration on PostgreSQL 17;
7. downgrade/re-upgrade tests required by repository convention;
8. `ruff check`;
9. `ruff format --check`;
10. `mypy` over the canonical source scope;
11. authentic real-chain fixture validation;
12. secret scan;
13. checkpoint/bundle validators;
14. dependency/lock consistency.

Final full-suite condition:

- `0 failed`;
- no unexplained skip of a test relevant to FSR-01..FSR-13;
- any remaining skip must be individually categorized as intentionally
  platform/inapplicable and not required by this contract;
- no PostgreSQL-17-required test may be counted as PASS if it did not execute on
  PostgreSQL 17.

Also run an explicit original-spec recovery acceptance matrix command/script or
produce a machine-readable table mapping `FSR-01..FSR-16 -> test/evidence ->
PASS/FAIL/NOT_TESTED`.

## FSR-16 — Final security state, build state, and single handoff

At recovery completion:

- Phase 6.5 has not run;
- no mainnet transaction was signed or broadcast;
- no real operator key/seed was accessed or exposed;
- no funded wallet was created;
- no arm file was created/modified;
- no capital defaults were changed from zero;
- no paid provider was enabled;
- no strategy was armed live;
- historical raw evidence was not deleted/rewritten.

Create new final evidence:

- `orchestration/checkpoints/final_spec_recovery.md`
- `orchestration/bundles/final_spec_recovery.txt`

The final checkpoint must begin/end with the standard ARGUS markers and contain:

- exact TARGET_COMMIT and final commit;
- original MASTER_SPEC hash;
- FSR-01..FSR-16 matrix;
- exact commands actually run;
- full test counts, failures, skips, coverage;
- PostgreSQL 17 evidence;
- corrected Phase 7-11 sample outputs;
- list of invalidated/superseded old derived versions;
- environmental limitations;
- security state;
- `LIVE_READY_SOFTWARE`, `LIVE_CANARY_PASSED`, `LIVE_ARMED`;
- explicit statement that Phase 6.5 was not executed;
- STOP for independent final audit.

Update `docs/BUILD_STATE.md` honestly. Do **not** claim orchestrator approval of
Phases 6-11. Add a recovery status field/comment that the final original-spec
recovery is implementation-complete and awaiting independent final audit.
Preserve historical phase rows as history; append rather than falsify old claims.

Append `docs/DECISION_LOG.md` with this human-approved recovery contract and the
repaired research-integrity issues.

Replace `orchestration/AGENT_HANDOFF.md` with one final matching handoff:

- new `HANDOFF_ID`;
- `CURRENT_PHASE: 11`;
- `WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION`;
- `LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-final-spec-recovery-001`;
- `CHECKPOINT_PATH: orchestration/checkpoints/final_spec_recovery.md`;
- `BUNDLE_PATH: orchestration/bundles/final_spec_recovery.txt`;
- actual full test status;
- clean working tree;
- `ORCHESTRATOR_REVIEW_REQUIRED: FINAL_ORIGINAL_SPEC_AUDIT` or, if FSR-03 is the
  sole external blocker, `ORCHESTRATOR_REVIEW_REQUIRED: FINAL_RECOVERY_ENVIRONMENT_BLOCKED`.

Every implementation-agent commit in this recovery run must end with exactly one
real terminal trailer:

`ARGUS-INSTRUCTION-ID: argus-final-spec-recovery-001`

with no paragraph after it.

---

# Efficiency and scope lock

- This is one batched recovery. Do not stop after Phase 6, 7, 8, 9 or 10.
- Do not rewrite working components just for style.
- Reuse the existing Phase 0-11 architecture and data model wherever possible.
- Prefer one shared point-in-time utility over five unrelated cutoff fixes.
- Prefer additive migrations/versioning over destructive edits.
- Do not add new model families, neural networks, thresholds, strategies or
  provider dependencies.
- Do not tune metrics/thresholds to make results look better after leakage is
  removed.
- Poor/negative/insufficient research results are valid outcomes.
- If corrected results collapse, record that honestly; do not rescue them by
  changing the frozen hypotheses or evaluation rules.
- Do not spend time on UI/frontend/mobile/microservices or unrelated hardening.
- A bug introduced by this authorized recovery may be fixed with a direct
  regression test without creating a new acceptance criterion.

# Mandatory session start

Before changing code:

1. `git status --porcelain`
2. `git pull --ff-only`
3. `git log -5 --oneline`
4. verify remote branch HEAD equals this instruction-only commit and that its
   direct parent is exactly `TARGET_COMMIT`;
5. verify the instruction commit changes only
   `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`;
6. read in order: `MASTER_SPEC.md`, `docs/BUILD_STATE.md`,
   `docs/DECISION_LOG.md`, `orchestration/PROTOCOL.md`,
   `orchestration/AUDITOR_POLICY.md`, this file, `orchestration/AGENT_HANDOFF.md`;
7. build a local acceptance matrix for `FSR-01..FSR-16` before implementation.

On any target/provenance mismatch, fail closed and STOP for orchestrator review.

# Prohibitions preserved

This instruction does **not** authorize Phase 6.5, mainnet canary, live arming,
capital, threshold relaxation, paid-provider use, credential disclosure, real
operator key/seed access, funded-wallet creation, live signing/broadcast, phase
skip, evidence deletion, history rewrite, or automatic live enablement.

Implement the entire sealed recovery, self-audit `FSR-01..FSR-16`, push the
final handoff/evidence, verify local/remote HEAD equality and clean worktree, then
STOP for one independent final audit.
