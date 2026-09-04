# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0041-final-spec-recovery-002
UTC_TIMESTAMP: 2026-09-04T23:45:00Z
CURRENT_COMMIT: b791a4011d36c0519a8c5542918c6274eaee5c71
CURRENT_PHASE: 11
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-final-spec-recovery-002
WORKING_TREE: clean
CHECKPOINT_PATH: orchestration/checkpoints/final_spec_recovery.md
BUNDLE_PATH: orchestration/bundles/final_spec_recovery.txt
TEST_STATUS: R2-01 focused 19 passed; R2-02 focused 2 passed; R2-03 focused 18 passed; tests/unit+tests/golden+tests/replay (1316 tests) 0 failed; tests/integration run twice from a fresh isolated-database template with no manual cleanup between runs, 414 passed/0 failed both times, no test data written to the ordinary developer `argus` database. ruff check/ruff format --check/mypy clean (228 source files). Secret scan clean across all 42 changed/new files. Single Alembic head (0040). Real-chain fixtures 12/12 ok. PostgreSQL 17 remains FINAL_RECOVERY_ENVIRONMENT_BLOCKED (fresh bounded attempt this round: Docker daemon now starts, but registry pull and PGDG apt host are both independently policy-blocked with genuine 403 denials) -- LIVE_READY_SOFTWARE=false.
ORCHESTRATOR_REVIEW_REQUIRED: FINAL_RECOVERY_ENVIRONMENT_BLOCKED -- every R2-01..R2-04 software requirement passes; the sole remaining blocker is PostgreSQL 17 environment access (section 8 of the instruction), an external sandbox restriction rather than a software defect. One additional disclosed (not blocking) gap: the R2-02 mutation-test recipe's full literal section-4.3 combined form was not built as one end-to-end test, only at the Phase-9-mechanism level plus one pre-existing Strategy-B decision-level regression test -- see checkpoint section D/M.

## Work completed

Executed the complete bounded `argus-final-spec-recovery-002` remediation
(R2-01 through R2-04), responding to an independent audit of the round-1
recovery (`TARGET_COMMIT` `7cca4094d7672759b1023733a810f552f1109040`) that
confirmed four specific root causes.

**R2-01**: one integrated executor pipeline seam
(`argus.executor.pipeline.execute_intent_pipeline`) chaining an
already-authorized execution intent through singleton fencing ->
risk/safety preconditions -> the legal state machine -> a Jupiter
unsigned order -> a REAL `UnsignedTransactionShape` deserialized from
actual transaction bytes via genuine chain simulation
(`argus.executor.simulation`'s real `getMultipleAccounts` +
`simulateTransaction`, never trusting the provider's own quote, plus an
offline SPL Token account decoder) -> mandatory `attest_transaction(...)
.all_passed` before signing -> an injected `Signer` -> an injected
submission seam called exactly once per idempotency fingerprint ->
durable signature + `SUBMITTED` persistence BEFORE confirmation polling
-> `reconcile_submitted_fill` -> restart-safe (never resubmits once a
signature is persisted) -> idempotent on terminal states. Stays inert by
default (capital zero, `LIVE_ARMED=false`, `LIVE_CANARY_PASSED=false`
throughout every test); every dependency in every R2-01 test is a
caller-scripted fake, never a real key or RPC call. 19 focused tests
cover all 7 required named scenarios plus AST/import-boundary and
deployment/permission isolation.

**R2-02**: fixed the knowledge-time leak in Phase 9's specialist-score
computation -- added `DirectionalEdge.created_at <= cutoff` and
`ExpectedConfirmationEvent.created_at <= cutoff` filters to
`_compute_and_persist_specialist_scores`
(`src/argus/counterfactual/service.py`), reusing the existing
`known_by_cutoff` invariant's full contract rather than a new mechanism.
`ALGORITHM_VERSION` bumped to `counterfactual_alpha_v3`, propagated to
`order_flow_prediction_v3` (Phase 11 consumes Phase 9's scores);
additive `contaminated_run_invalidations` rows (migrations 0038/0040)
chain after FSR-13's own original rows, never replacing them. 2 dedicated
mechanism-level tests plus one pre-existing Strategy-B decision-level
regression test satisfy the instruction's own named scenarios. Disclosed
gap: the full literal section-4.3 combined mutation-test recipe (a single
test tracing byte-equivalent decision inputs across a full rebuild) was
not built as one combined test.

**R2-03**: Phase 10's forbidden fixed 5-minute
`PRIMARY_EXECUTABLE_HORIZON` replaced with real contemporaneous matching
on both sides of a trade (`src/argus/synthetic/service.py`):
`_select_contemporaneous_reverse_outcome` (exit side, unchanged from the
first attempt at this fix) and a new `_select_contemporaneous_entry_probe`
(entry side, Strategy C/D's confirmation-anchored entries only) --
discovered and fixed during this round's own careful re-review: the first
attempt correctly fixed WHICH `WalletOpportunity` to look up
(`_entry_lookup_at`, using the leader's real entry time) but still
silently priced Strategy C/D's entry from the leader's own realized fill,
never actually matching real `ENTRY_DELAY` evidence to the follower's own
confirmation delay as the instruction explicitly requires. Also fixed a
second, independent bug in the same family: hold-duration matching for
the exit side now uses one consistent reference frame (the leader's real
entry time) instead of mixing it with the follower's confirmation time.
`argus.copyability.loaders.WalletOpportunity`/`OpportunityReverseOutcome`
gained two additive fields (`entry_delay_probes`, `reverse_quote`) with
no existing Phase 5 M1-M6 consumer behavior change;
`compute_executable_return`'s own mint/quantity validation is reused,
unmodified, as the safety net against a substituted entry that acquired a
different quantity than a reverse probe was sized for.
`ALGORITHM_VERSION` bumped to `synthetic_super_wallet_v3` (migration
0039). 18 focused tests cover all 8 named required scenarios.

**R2-04**: `tests/integration/conftest.py`'s `isolated_database` fixture
redesigned as a two-tier system -- a session-scoped migrated template
database plus a function-scoped clone via Postgres's own `CREATE
DATABASE ... TEMPLATE`, giving every TEST FUNCTION (confirmed necessary,
not merely every module, via direct experiment: several production
queries intentionally scan every matching row in a table) its own real,
independent database. Every integration test file that persists real
domain data now opts in, closing FSR-15's prior 21-failure cross-test-
pollution gap, including `test_r201_executor_pipeline.py` (whose own
fixtures rely on `solders.pubkey.Pubkey.new_unique()`, a deterministic
per-process counter, so re-running that file in a fresh process
regenerated identical "unique" mints and collided with a prior run's
leftover row). A second, genuinely independent pre-existing bug was
found and fixed: `rich.console.Console.print()`'s default word-wrapping
corrupted long CLI `--as-of`/report JSON output
(`src/argus/cli.py`, `soft_wrap=True` on all 8 call sites) -- invisible
in every prior round because Postgres was never reachable for a real
CLI-report integration test until this round's native-PostgreSQL-16
discovery.

## Security-state confirmation

- Phase 6.5 (MAINNET CANARY) has NOT run and was not attempted.
- No mainnet transaction was signed or broadcast -- every R2-01 pipeline
  test uses exclusively caller-scripted fakes.
- No real operator key/seed was accessed, read, printed, logged, or
  exposed.
- No funded wallet was created; no arm file was created or modified.
- No capital default was changed from zero; `LIVE_ARMED=false` and
  `LIVE_CANARY_PASSED=false` throughout.
- No paid provider was enabled.
- No secret was requested; the only credentials touched were this
  repository's own pre-existing, previously-scrubbed dev-only `.env`
  literals, used solely to configure a local ephemeral non-Docker
  PostgreSQL 16 cluster's own role passwords -- never transmitted or
  modified.
- Secret scan: clean across all 42 changed/new files.
- `LIVE_CANARY_PASSED=false`
- `LIVE_ARMED=false`
- `LIVE_READY_SOFTWARE=false` (PostgreSQL 17 remains environment-blocked;
  per the instruction's own rule this cannot be `true` regardless of
  every other requirement passing).

Full itemized evidence: checkpoint section N.

## Deferred / open items (explicitly disclosed, not hidden)

- PostgreSQL 17 validation remains blocked in this sandbox -- this
  round's fresh bounded attempt confirmed the Docker daemon itself now
  starts, but both the Docker registry pull and the PGDG apt host are
  independently policy-blocked (genuine `403 Forbidden` denials,
  confirmed non-retryable). Needs either a sandbox with unblocked
  registry/PGDG egress, or an operator-run `make up && make test` against
  the repository's own `compose.yaml` with a real PostgreSQL 17 image.
- The R2-02 mutation-test recipe's full literal section-4.3 combined form
  (one test tracing byte-equivalent decision inputs across a full Phase
  9->10/11 rebuild under a fresh algorithm/config identity) was not
  built -- only the Phase-9-mechanism-level tests plus one pre-existing
  Strategy-B decision-level regression test.
- No large-N real-wallet Phase 10 v3/Phase 11 v3 research report was
  generated this round (out of this bounded remediation's own scope).

## Exact next action requested from orchestrator

Per `orchestration/AUDITOR_POLICY.md`: audit this bounded
`argus-final-spec-recovery-002` remediation (R2-01 through R2-04) against
`orchestration/checkpoints/final_spec_recovery.md` and
`orchestration/bundles/final_spec_recovery.txt`. If satisfied that every
non-environment requirement is genuinely met, only the orchestrator/human
operator may apply final recovery approval -- write the next `ACTIVE`
instruction into `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`
(`TARGET_COMMIT` pinned to this handoff's own `CURRENT_COMMIT`) to do so,
to authorize PostgreSQL 17 validation and/or the R2-02 mutation-recipe
gap as a follow-up scope, or to require further remediation. This session
does not and cannot apply final recovery approval itself. Until a new
instruction exists, the watcher (if running) takes no action beyond
logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** if you cloned/fetched this branch
before this handoff's own `UTC_TIMESTAMP`, re-fetch to pick up this
round's commits.
