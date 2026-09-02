# ARGUS Orchestrator Instructions

OWNER: ARGUS ORCHESTRATOR. Claude must not edit this file.
MASTER_SPEC.md remains authoritative. Read orchestration/AUDITOR_POLICY.md before acting.

INSTRUCTION_ID: argus-phase-6-001
ISSUED_AT: 2026-09-02T23:29:00Z
TARGET_COMMIT: 43bb62f9247e8e8b3a663e98c8ed70ba956e4960
AUTHORIZED_ACTION: BUILD_PHASE_6_HARDENED_ISOLATED_EXECUTOR_SOFTWARE_ONLY
AUTHORIZED_PHASE: 6
APPROVES_PHASE: 5
STATUS: ACTIVE

## Decision

Phase 5 is APPROVED as PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION at audited remote HEAD 43bb62f9247e8e8b3a663e98c8ed70ba956e4960.

The Phase 5 remediation was audited against the same sealed phase-5-v1 contract, P5-01 through P5-14, digest d2291c823715a51e9c3aa92b8a758c2b703c57b88f03cb2d0637a5bbe2c294b5. The seven previously identified failures F5-01 through F5-07 are closed by the submitted production changes and required tests/evidence. The additional long-horizon dict.get/default-evaluation regression was discovered and fixed within the authorized remediation and has direct regression coverage. No new current-phase criterion is added. Database-backed execution remains an honest environmental deferral; it is carried forward below rather than used to move the Phase 5 finish line.

Phase 6 is now authorized. This is SOFTWARE-ONLY construction of the hardened isolated executor and its fail-closed safety machinery. It does NOT authorize a live wallet, real signing key, seed/private-key access, live arm file creation/modification, funded wallet, mainnet transaction, canary, strategy live trade, paid-provider upgrade, or capital allocation. Phase 6 must finish with LIVE_CANARY_PASSED=false and LIVE_ARMED=false. Software readiness may be reported only to the degree actually proven.

## Acceptance-contract seal

CONTRACT_ID: phase-6-v1
SEAL_RULE: The numbered P6 criteria below are the complete ordinary blocking contract for this implementation. Once implementation begins, no new ordinary requirement/test/proof may be added to Phase 6. A later-discovered legitimate issue outside this contract is NEXT_PHASE_CARRYFORWARD unless it demonstrates an immediate catastrophic safety/integrity defect under AUDITOR_POLICY.md. HARDENING_BACKLOG never blocks. The builder must self-audit every row before handoff.

Authoritative scope: MASTER_SPEC.md sections 65-84, especially 67-84. Sections 62-64 are research concepts and are not pulled into this executor build. Existing Phase 0-5 behavior must not regress.

### Frozen Phase 6 acceptance matrix

| ID | Frozen requirement | Required evidence/test | Pass condition |
|---|---|---|---|
| P6-01 | Live defaults and authority fail closed. Repository defaults for max single trade, total exposure and daily loss are exactly zero; absent/malformed/expired/hash-mismatched arm state disables live execution. Implementation agent never creates/modifies the external arm file. | Unit tests for missing/malformed/expired arm, git/build/risk/strategy hash mismatch, zero default capital. Static/config inspection. | Every case returns live-disabled/rejected with explicit reason; no fallback enables execution. |
| P6-02 | Executor key isolation boundary exists in architecture. Only executor process interface may request signing; research/CLI/report paths cannot read key material. No repository secret or test real credential. | Dependency/interface tests using inert fake signer; grep/secret scan; tests proving research/copyability paths have no signer/key dependency. | Fake signer only; no real key access; unauthorized components cannot invoke key loading/signing. |
| P6-03 | Database least-privilege executor role is additive and explicit. Executor cannot rewrite historical wallet scores/research evidence; research/ingest do not gain signing/execution mutation privileges. | Migration/role tests and privilege assertions; upgrade from existing Phase 5 schema. | Required executor tables/actions work under intended role; forbidden writes are denied. Environmental DB execution may be explicitly deferred only if infrastructure is unavailable. |
| P6-04 | Singleton/fencing protection prevents two active executors controlling the strategy universe. Loss/failure of ownership disarms/refuses further execution. | Concurrency test with two executor instances using DB advisory lock or robust lease/fencing token; ownership-loss test. | Exactly one owner; second refuses start; lost ownership blocks subsequent state-changing execution. |
| P6-05 | Persisted execution-intent model/state machine implements CREATED, VALIDATING, REJECTED, ORDER_REQUESTED, ORDER_READY, ATTESTING, SIGNED, SUBMITTED, CONFIRMED, FAILED, UNKNOWN with immutable/audited transactional transitions. | State-transition unit/integration matrix including legal/illegal transitions and restart reload. | Legal transitions persist once; illegal transitions fail closed without state corruption; audit history retained. |
| P6-06 | Idempotency fingerprint and locking make replay/restart unable to execute an intent twice. Ambiguous submitted transaction becomes UNKNOWN before any retry; no blind retry. | Duplicate-intent concurrent insert/dispatch test; crash-after-submit/restart test; replay test. | One semantic intent/dispatch maximum; ambiguous submit reloads UNKNOWN and requires reconciliation rather than resubmission. |
| P6-07 | Transaction attestation occurs before signing and verifies expected signer/wallet, input mint, output mint, intended amount, user-controlled asset outflows, bounded fees/tips/rent, simulation where available, simulated balance changes, and rejects unexplained authority/account behavior. | Table-driven fake unsigned-transaction fixtures: one valid inert fixture plus one failure fixture for every attestation dimension. Signer spy/sentinel. | Signer is never called for any failed/unknown attestation; valid inert fixture reaches signing seam only, never network submission. |
| P6-08 | Actual-fill accounting treats confirmed chain balance deltas as canonical and separately persists quoted, simulated and actual input/output plus network fee, priority fee, tip and rent/account costs. | Deterministic fixture tests with quote != simulated != actual; partial/missing evidence cases. | Confirmed chain-derived values win; provenance retained; missing values explicit, never fabricated from quote. |
| P6-09 | No automatic slippage escalation. Any retry stays within frozen/operator-approved ceiling; unsafe execution is abandoned/rejected. | Tests for quote/order failure at ceiling, repeated retry request, and lower allowed retry. | Code never increases approved ceiling automatically and never loops escalation. |
| P6-10 | Independent live-risk validation rechecks all MASTER_SPEC section 81 items before any signing/submission seam: software readiness, canary status, arm validity, approved hashes, wallet eligibility, signal freshness, token/mint/safety, liquidity, leader movement, quote impact/slippage, position/aggregate/daily-loss limits, duplicate/conflicting intent, scale-in prohibition, wallet balance, quote freshness, chain freshness, clock health and stream/reconciliation health. | Table-driven gate test with all-safe synthetic baseline and each gate individually FAIL and UNKNOWN/stale where applicable. | Every single failed/unknown mandatory gate rejects with stable reason code before signer/submission; no current Phase 6 test may set real live authorization. |
| P6-11 | One-open-position-per-mint default and ALLOW_AUTOMATIC_SCALE_IN=false are enforced. Multiple wallet signals may affect confidence but cannot create additional automatic buys. | Existing-position/same-mint duplicate-signal tests, including concurrent intents. | Second automatic buy is rejected/no dispatch. |
| P6-12 | Independent risk exits are represented and enforceable for maximum position loss, liquidity collapse, token-risk-state change, maximum daily loss, maximum aggregate exposure and operator emergency exit, without depending on source-wallet behavior. | Pure/state-machine tests for each exit trigger with fake positions. | Each trigger creates deterministic risk-exit/rejection behavior and audited reason without needing leader sell evidence. No live dispatch. |
| P6-13 | Token-safety and pre-entry sellability evidence are fail-closed inputs. Unknown dangerous mechanics or missing/unsafe reverse executability cannot become auto-live eligible. | Tests for mint/freeze/Token-2022/transfer-fee/unsupported behavior/concentration/liquidity/mutability UNKNOWN/unsafe states and reverse-route absent/excessive-impact/stale cases. | Unsafe/UNKNOWN required safety evidence blocks execution; screen is not described as guarantee. |
| P6-14 | Host suspend/resume or major clock/scheduling discontinuity auto-disarms new entries and requires the complete section 83 reconciliation sequence before readiness can recover. | Deterministic fake-clock tests: discontinuity -> disarm; partial recovery of each required dimension; full healthy recovery. | No new entry until clock, streams, tracked-wallet watermarks, positions, executor balance, provider health and open orders/intents are reconciled healthy. |
| P6-15 | Restart/crash acceptance behavior is preserved across collector ingest, stream gap recovery, shadow worker, executor post-submit, DB loss/recovery and time discontinuity. Phase 0-5 restart/idempotency tests remain green. | Execute existing restart/replay suites plus new executor kill-after-submit/restart and DB-loss recovery tests. | No duplicate canonical event/shadow trade/executor buy; missed event recovered once; DB loss fails closed; time discontinuity disables entries. Environmental DB cases may be deferred only with exact limitation and substitute structural evidence. |
| P6-16 | Phase 6 cannot accidentally perform live network execution. Provider submission and signer calls are guarded by explicit inert sentinels in normal test/CLI paths; credentials/secrets do not appear in logs/evidence. | Tests monkeypatch submission and signer with raising sentinels while running Phase 6 report/readiness/dry-run paths; fake secret-shaped value log scan. | Zero submission/signing calls unless a specifically isolated fake-signing unit test invokes only the fake seam; fake secret absent from outputs/logs. |
| P6-17 | Phase 6 disposition and operational artifacts are honest. No claim of live readiness beyond evidence; canary remains false; armed remains false; no capital values invented. | Checkpoint/build-state assertions and report schema tests. | Final checkpoint explicitly records LIVE_CANARY_PASSED=false and LIVE_ARMED=false. If software criteria pass, it may state LIVE_READY_SOFTWARE=true only if all software-only requirements are actually proven; environmental deferrals remain named. |
| P6-18 | Prior-phase regression and schema integrity. Existing Phase 0-5 tests, migrations, checkpoint/bundle validators, fixtures, ruff, format and mypy remain valid. | Full pytest; named Phase 5 regression suite; alembic single-head/upgrade tests; fixture validation; ruff; format; mypy; checkpoint/bundle validators. | No new non-environmental regression. Historical evidence remains immutable. |

### Carryforward from Phase 5

CF5-DB: The Phase 5 DB-backed copyability/readiness integration paths were not executed in the builder/auditor sandbox because PostgreSQL was unavailable. During Phase 6, if a real authorized local/test PostgreSQL environment is available without requesting credentials or paid/new infrastructure, execute those already-written Phase 5 integration tests and record results. If the same environmental limitation persists, preserve the deferral honestly. This carryforward does not retroactively reopen Phase 5 and does not authorize requesting/disclosing credentials.

## Implementation constraints

- Build only software, migrations, tests, docs and inert/fake fixtures needed for P6-01..P6-18.
- Do not create, read, request, print or persist any real seed phrase/private key/signing key.
- Do not create/fund a wallet. Do not create or modify `/var/lib/argus/live_arm.json` or any equivalent external arm file.
- Do not submit a mainnet transaction, initiate the human canary, or make a strategy live trade.
- Do not change zero live-capital defaults or define operator capital.
- Do not use or upgrade paid providers.
- Do not weaken Phase 5 readiness >=90, A/S, qualification >=85, copyability >=75 or other frozen thresholds.
- Do not implement Phase 6.5/7+ research as a hidden prerequisite.
- Additive migrations only; preserve historical migrations/evidence.
- Use Decimal/raw integer semantics for monetary/token quantities; no float substitution in execution/risk accounting.
- Every legitimate bug discovered while implementing this sealed scope gets a regression test. A bug directly caused by authorized implementation may be fixed within this build without expanding the acceptance contract; disclose it.

## Required evidence and handoff

Create new immutable evidence only:
- orchestration/checkpoints/phase_6.md
- orchestration/bundles/phase_6.txt
- orchestration/phase_6/evidence/ as needed

Checkpoint must map every P6-01..P6-18 row to implementation evidence, exact tests actually run, result, pass condition and any environmental deferral. Include CF5-DB disposition separately. Preserve all prior evidence bytes.

Run the complete relevant test matrix, full repository regression suite, ruff check, ruff format --check, mypy src, alembic heads/migration checks, authentic fixture validation, secret scan, and production checkpoint/bundle validators. Do not claim an environmental test passed if it skipped or could not run.

Update docs/BUILD_STATE.md and append docs/DECISION_LOG.md. Update AGENT_HANDOFF.md with a new HANDOFF_ID, CURRENT_PHASE: 6, WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION, LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-6-001, clean worktree, exact new checkpoint/bundle paths, and actual commit from this run.

Every Claude commit for this run must end with exactly:
ARGUS-INSTRUCTION-ID: argus-phase-6-001
and nothing after that trailer.

Synchronize first, verify this instruction is exactly one instruction-only commit whose parent equals TARGET_COMMIT, implement, self-audit the sealed matrix, commit/push, verify remote HEAD and STOP. Do not self-approve Phase 6 or begin Phase 6.5.
