# ARGUS Orchestrator Instructions

OWNER: ARGUS ORCHESTRATOR. The implementation agent must not modify this file.
MASTER_SPEC.md remains authoritative. Execute only this ACTIVE instruction.

INSTRUCTION_ID: argus-phase-4-recovery-003
ISSUED_AT: 2026-09-02T14:22:09Z
TARGET_COMMIT: 87e8ba1b5a7969e5afe4a7e1e6c44eb392365f16
AUTHORIZED_ACTION: PHASE_4_TEST_AND_EVIDENCE_COMPLETION
AUTHORIZED_PHASE: 4
APPROVES_PHASE: NONE
STATUS: ACTIVE

## Decision and authority

Phase 4 is not yet approved. This is a TEST-AND-EVIDENCE-ONLY recovery, not another production-code repair. The production fixes for F-01 and F-02, and F-03's final checkpoint/bundle format and embedding, pass the independent checks described below. Keep them closed. The remaining SPEC_BLOCKING finding is missing execution/persistence coverage expressly required by recovery-002's frozen acceptance matrix, with broader PASS claims than the supplied tests prove.

The completed root-cause review below authorizes immediate safe continuation under the user's updated autonomous-recovery instruction. Do not wait for another human approval. Phase 5 and every live action remain blocked. No new strategy, provider, threshold, route policy, score, schema, migration or production-code change is authorized.

Preserve the complete attempt history: initial Phase 4 build; remediation-001; remediation-002; failure-review-001; recovery-001; recovery-review-001; recovery-002; this reviewed, bounded recovery-003. Do not rename these as a fresh initial build or reset the ordinary remediation count. One ordinary remediation remains the default maximum; subsequent work requires an actual completed review, not a repeated patch packet.

## Pinned independent audit

Audited remote HEAD: 87e8ba1b5a7969e5afe4a7e1e6c44eb392365f16.
Implementation parent: a50432946b5ddeede55f84d61c93375047c564df.
Active instruction at submission: e2b0edce094f51b329372ccfb0015fece0103033, ID argus-phase-4-recovery-002.
Handoff: handoff-0029-phase-4-recovery-2.
Evidence: orchestration/checkpoints/phase_4_recovery_2.md and orchestration/bundles/phase_4_recovery_2.txt.

The git chain is correct: 055e3a2141983d4b8a7b01e91e177588dddaea6b -> e2b0edce094f51b329372ccfb0015fece0103033 -> a50432946b5ddeede55f84d61c93375047c564df -> 87e8ba1b5a7969e5afe4a7e1e6c44eb392365f16. Both Claude commits have the exact terminal recovery-002 trailer. The instruction was unchanged and the final diff does not alter earlier checkpoint/bundle/evidence files. Worktree was clean.

Fresh independent results on this exact target:

- `uv run pytest tests/unit tests/golden tests/phase_1_5 -q`: 712 passed.
- `uv run pytest tests/unit/test_phase4_recovery_2_contract.py -q`: 52 passed, including the now-present final artifacts (not skipped).
- Independent scratch harness: 118 real JupiterClient/MockTransport cases exercised the production common executor with controlled session objects, plus repeated-call terminal guards. Both worker kinds, both malformed nested fields, superscript/5000-digit/ordinary invalid values, positive representations through the reverse common seam, HTTP400/429 safe/unsafe codes and identifier boundaries passed. These are NOT PostgreSQL persistence or restart results. Entry/reverse callers at quote_jobs.py invoke the same executor; no new classification or persistence branch was introduced by this diff.
- Both final production artifact validators returned `(True, '')`; complete checkpoint bytes are embedded in the bundle. This closes the earlier artifact-format/validation defect.
- Ruff check passed; formatter reported 261 files already formatted; mypy passed for 128 source files; alembic head 0021; authentic fixture validation passed 12/12.
- Fresh integration attempt stopped in fixture setup: missing ARGUS_DB_ADMIN_PASSWORD in the auditor environment. No credential was requested, entered or disclosed. This is an environmental limitation, NOT a product test failure. Builder evidence reports 978 passed/1 pre-artifact skip and 67 passed/1 pre-artifact skip; those counts are builder evidence, not an independent PostgreSQL rerun.
- `git diff --check` reported whitespace in preserved raw pytest output and a bundle trailing blank line. This is HARDENING_BACKLOG, not a phase blocker. Do not rewrite old raw evidence to make this check cosmetically clean.

Closed, not to be reworked: F-01 total amount parsing; F-02 safe error-code format and HTTP429 evidence; F-03 final artifact validator/embedding behavior; P4-REC-01/04/05; all earlier independently closed R1-R7 findings. No production defect was demonstrated in this recovery's fixes. Environmental validations remain deferred as previously recorded, including PG17_COMPOSE_VALIDATION, LIVE_HELIUS_RPC_VALIDATION, LIVE_HELIUS_WSS_VALIDATION and BQ_PUBLIC_DATASET_ACCESS. No live-provider validation is added here.

## One consolidated remaining finding: COV-01 — SPEC_BLOCKING

Frozen source: recovery-002's matrix AM-01/02/03/04/08/09/10 and ordered steps 2, 3 and 5. That instruction explicitly required worker/persistence tests, actual reload/replay, and truthful row-by-row proof; it explicitly allowed exercising the proven common execution seam. Helper-only tests and one representative reload do not satisfy the stated case matrix.

Concrete gaps in the submitted test sources:

| Frozen row | Supplied proof | Missing required proof |
|---|---|---|
| AM-01 | Entry superscript case parameterizes both fields; reverse superscript case hard-codes outAmount. | Reverse/inAmount case with terminal clocks and no-new-position assertions. |
| AM-02 | Unit helper rejects 5000 digits; AM-03 integration uses entry/inAmount. | Remaining kind/field combinations through the production executor, terminal/no-fill behavior. The helper itself cannot prove the checkpoint's claimed terminal NO_ROUTE. |
| AM-03 | One entry/inAmount/5000-digit reload checks outcome, terminal_at and HTTP count. | Reload/repeat for the AM-01/02 matrix, retaining identity and all request/response/terminal clocks, position count and terminal-record count. |
| AM-04 | Parser validity matrix and structural-mint helper checks. | Valid/invalid nested amounts through real-adapter/common-executor processing with the frozen SUCCESS/NO_ROUTE and no-fill assertions. |
| AM-08 | Unsafe-code helper tests; one unsafe URL HTTP429 integration case. | Frozen unsafe values at HTTP400 and HTTP429 through executor persistence; ignored fake body/header/URL material absent from evidence and captured logs. |
| AM-09 | Identifier boundary helper tests only. | HTTP400/429 worker outcomes and exact retained code at 1/128 characters, digits/underscore, and rejected 129 characters. |
| AM-10 | One entry/429/AUDIT_RATE_LIMIT reload. | Reload/repeat after the AM-05/07/08 cases for both kinds, all terminal clocks/identity, no additional requests/fills/rows. |

AM-05/06/07 behavior, AM-11 existing scheduler behavior, AM-12/13 final and negative validators, and unchanged authorized-scope checks are accepted. Preserve them; reuse existing tests. AM-14's environmental caveat stays separate. Do not call the entire frozen matrix PASS until COV-01 is closed.

The recovery-002 checkpoint also describes its instruction commit e2b0ed... as TARGET_COMMIT; the actual recovery-002 TARGET_COMMIT was 055e3a2.... Git ancestry itself is correct. In NEW records distinguish the instruction commit from its TARGET_COMMIT and describe this prior wording error; do not edit the historical checkpoint. This is a documentation correction, not a new runtime blocker.

## Completed Phase Failure Root-Cause Review

1. **Was the frozen gate unclear?** The required Cartesian cases, HTTP statuses and fresh-session assertions were explicit before implementation. The architect nevertheless allowed a multi-case row to look complete when a single helper test was linked to it. Correct the instruction-generation/self-audit process by using the executable parameter inventory below and checking collected case IDs, not a row label alone. No product behavior is being added.
2. **Was clear behavior implemented incorrectly?** No new production defect was found. The implementation agent supplied narrower tests and overclaimed their coverage. Finish the existing test contract; do not perturb working production logic. Reuse the common executor already permitted by the old contract to keep this small.
3. **Did the audit add a requirement?** No. Every gap above quotes a recovery-002 case or pass condition. Do not add other payload fuzzing, economic constraints, live validation, new database semantics, or Phase 5 features. Earlier closed findings stay closed.
4. **Why did tests miss this?** Green helper tests checked booleans/strings, not persistence; representative entry-only restart tests did not cover the explicitly required matrix. The self-audit treated the existence of an AM-named node as proof of all its cases. The remedy is a single parameterized executor/reload harness, collected case inventory, assertions on the complete record snapshot, and accurate limitations. New coverage may already pass on current production code; do not manufacture red output or alter code merely to produce a failing test.

This review supports a bounded safe recovery without human input. It does not support another production patch.

### Seven-part no-moving-goalposts justification

1. Prior frozen authority: recovery-002 at e2b0edce094f51b329372ccfb0015fece0103033, AM rows identified above.
2. Pinned failure evidence: the exact test nodes and parameterization gaps in a504329.../87e8ba1...; no hypothetical new defect.
3. Unchanged acceptance: same values, statuses, kinds, terminal timing, no-fill, sanitized evidence and reload behavior; no extra product threshold.
4. Why another bounded pass: production is fixed but mandatory test/evidence deliverables are incomplete; ordinary remediation is not silently restarted.
5. Why earlier tests missed it: helper/representative coverage substituted for the frozen matrix; full suite green does not prove absent test cases.
6. Consolidated scope and exit: only COV-01, test harness and new evidence; all prior closed production findings remain closed; stop at the new handoff.
7. Authority and process: user's automatic safe-recovery policy authorizes this completed-review continuation. No funds, paid data, credentials, live activation, strategy change or destructive evidence operation is involved. A later failure requires another actual root-cause review; no blind repetition or expanded criteria.

## Frozen test-only completion matrix

Use `tests/integration/test_phase4_recovery_3_matrix.py` for the missing worker/reload coverage. You may import/reuse existing recovery-002 test helpers or add test-only helpers. Production callers or the unchanged `_execute_and_record_probe` common seam are both acceptable, as already frozen. Use the real JupiterClient with MockTransport, existing disposable PostgreSQL fixture/session setup, and persisted ShadowQuoteProbe records for both kinds. Do not replace the classifier/executor with a mock. Target probes by ID to avoid unrelated due probes changing counts.

| ID / source | Exact setup and assertions |
|---|---|
| TC-01 / AM-01,02,03 | Parameterize kind ENTRY_DELAY/REVERSE_EXECUTABLE x nested inAmount/outAmount x malformed value superscript-two (`"²"`)/5000 ASCII `1` characters: 8 cases. Valid top-level quote and otherwise valid route. Each result is NO_ROUTE with requested_at <= responded_at <= terminal_at, no new position and one HTTP request. Persist, close session, reload in a fresh session, repeat processing of that probe, and reload again. Assert identical probe ID, outcome, requested_at, responded_at, terminal_at, evidence, and row/position counts; no second HTTP request. Never change the interpreter conversion guard. |
| TC-02 / AM-04 | Exercise each nested field with valid `"1"`, `"001"`, integer 1 and invalid `""`, `"garbage"`, `"0"`, 0, `"-1"`, -1, True, 1.5, None and a non-ASCII decimal digit. Use the proven common executor. Valid values retain SUCCESS; invalid values become terminal NO_ROUTE and create no fill. Existing mint/impact tests remain green. This row does not add a fresh-reload requirement for every valid value. |
| TC-03 / AM-05,07,10 | Both kinds: 429/AUDIT_RATE_LIMIT; 400/COULD_NOT_FIND_ANY_ROUTE; 400/UNKNOWN_SAFE_CODE; 429/COULD_NOT_FIND_ANY_ROUTE. Outcomes respectively capacity miss, NO_ROUTE, QUOTE_FAILED, capacity miss. Evidence contains only exact status and exact supplied safe code. Fresh persisted reload/repeat uses TC-01's identity/clocks/counts/no-request assertions. |
| TC-04 / AM-08,10 | Both kinds x HTTP400/429 x each frozen unsafe code: inert URL with api_key query, bare `api_key=AUDIT_ONLY_FAKE_SECRET`, embedded newline, embedded control character, JSON-body-shaped string, empty string, 129 ASCII letters, bool, integer, dict, list. Add ignored sibling fake-secret fields and fake headers to the response. Only http_status_code is persisted; no raw error body/code/header/URL in evidence or new captured logs. 400 => QUOTE_FAILED, 429 => PROVIDER_CAPACITY_MISS. Fresh persisted reload/repeat uses TC-01's complete unchanged-record/no-request/count assertions. Use inert literals only. |
| TC-05 / AM-09 | HTTP400/429 with safe code `A`, 128 ASCII letters, and an unknown identifier containing digits/underscore; also 129 ASCII letters. Exercise common executor. Exact safe code survives with appropriate coarse outcome; 129 rejected with only status. No trimming/normalization. Shared sanitizer is a format policy, not arbitrary-secret detection. |
| TC-06 / AM-12,13,14,15 | Retain existing passing tests for accepted rows and run required regressions. Validate NEW final artifact bytes with BOTH `(ok, reason)` assertions and exact embedding after hash-fill. Record collected case IDs and observed results for TC-01..05, and map all original AM rows to actual tests. Missing cases are FAIL/BLOCKED, not PASS. Preserve all old evidence, instruction ownership and correct git identity. |

For TC-02 and TC-05, common-seam coverage need not be duplicated per kind after TC-01/03/04 prove both callers share it; the old contract expressly allowed this. This is not permission to omit the explicit both-kind reload matrix in TC-01/03/04. Tests should use one helper to capture before/after immutable record fields and scoped row counts, not many almost-identical tests. Keep the provider open during repeat processing and count transport calls, so accidental re-execution cannot be hidden by a closed-client exception.

## Allowed files, evidence and execution

Allowed: new test module above; minimal test-only helper changes if needed; new `orchestration/checkpoints/phase_4_recovery_3.md`; new `orchestration/bundles/phase_4_recovery_3.txt`; new `orchestration/phase_4_recovery_3/evidence/`; docs/BUILD_STATE.md, append-only docs/DECISION_LOG.md and orchestration/AGENT_HANDOFF.md. Keep src/, migrations/, config, MASTER_SPEC.md, PROTOCOL.md and both watcher scripts unchanged. No rework of quote_jobs.py. Do not overwrite any existing evidence, including recovery-002 artifacts. The accepted replay demonstration need not be separately regenerated for this test-only completion. However, the existing full/regression suite invokes that generator as a subprocess. BEFORE those commands, change ONLY its EVIDENCE_DIR destination in `scripts/argus_phase4_replay_demo.py` to the new `orchestration/phase_4_recovery_3/evidence` directory, just as recovery-002 was explicitly allowed to move its artifact destination. This narrow evidence-output change is authorized; no replay lifecycle, provider or database-isolation behavior change is allowed. Do not run the full suite first and repair overwritten historical evidence afterward.

1. Synchronize, verify clean worktree, follow PROTOCOL read order. Verify this instruction's commit changes only orchestration/ORCHESTRATOR_INSTRUCTIONS.md and has direct parent TARGET_COMMIT above. Use the actual instruction field, not the instruction commit, when recording TARGET_COMMIT.
2. Add tests for TC-01..05. Collect their IDs and compare against the frozen parameter inventory BEFORE claiming completeness. Run them against current production code unchanged. New tests may immediately pass; record that truthfully. If a frozen expectation genuinely fails, keep the failing test/evidence and report it; no production fix is authorized under this test-only instruction.
3. Use only the already-authorized disposable test environment and existing local test setup. No credential entry/disclosure, new provider, paid service, signing, live trade, persistent-history cleanup or production database mutation.
4. Run:
   - `uv run pytest tests/integration/test_phase4_recovery_3_matrix.py --collect-only -q`
   - `uv run pytest tests/integration/test_phase4_recovery_3_matrix.py tests/integration/test_phase4_recovery_2.py tests/unit/test_phase4_recovery_2_contract.py -q`
   - `uv run pytest tests/integration/test_shadow_phase4_remediation_observation.py tests/integration/test_shadow_quote_jobs_provider_remediation.py tests/integration/test_shadow_phase4.py tests/integration/test_shadow_phase4_concurrency_remediation.py tests/integration/test_migrations.py tests/integration/test_daily_report_remediation.py tests/integration/test_replay_demo_isolation.py -q`
   - `uv run pytest -q`
   - `uv run ruff check .`
   - `uv run ruff format --check .`
   - `uv run mypy src`
   - `uv run alembic heads`
   - `uv run argus fixtures validate-real-chain`
   - Existing secret-scan/checkpoint validation workflow, git diff/status/trailer/identity checks. Never print real secrets. Report raw-log whitespace separately; don't alter preserved evidence to erase it.
5. Create the NEW checkpoint with exact protocol first/last markers, PROJECT: ARGUS, phase 4, exactly one STATUS and one actual full GIT_COMMIT from this run. Include Commands actually run, Test results, Acceptance criteria, Deviations, Known bugs/debt, Security state, Next action/STOP. Map original AM-01..15 plus TC-01..06 to implementation/seam, collected node IDs, actual result and honest limitation. Distinguish independent prior audit results, builder results and unavailable environments. Preserve earlier overclaims as history and correct them only in new records.
6. Bundle exact final checkpoint bytes with raw test/collection results, final diff and identity. After all generation/hash-fill steps assert both existing production validators return `(True, '')` and the full checkpoint text is present in the bundle. Do not weaken validators. An artifact test skipped before generation is not final proof; run it on final files.
7. Keep approved phase 3 / approved commit efb8837f01ab6aaa451c6ee3263e4effa389c4e6 until independent Phase 4 approval. Handoff must use a new HANDOFF_ID, LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-4-recovery-003, CURRENT_PHASE: 4, WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION, WORKING_TREE: clean, and the new checkpoint/bundle paths. Every Claude commit must end with exactly `ARGUS-INSTRUCTION-ID: argus-phase-4-recovery-003` and nothing after it. Push, verify fresh remote commit and clean worktree, then STOP. Do not self-approve or begin Phase 5.

## Next independent decision

Audit only COV-01 and affected regressions. Do not reopen the proven production fixes or add optional test cases. If the frozen coverage is complete and green, approve Phase 4 with the existing environmental limitations, then freeze Phase 5's complete acceptance matrix and authorize that immediate next phase in the same run unless MASTER_SPEC has a genuine human gate. If a new mandatory failure appears, complete a real root-cause review and issue only an evidence-backed safe recovery within delegated authority. Pause for human input only for actual authority/strategy decisions, or when no safe supported continuation exists. Report tool permission failures and never bypass them. An instruction publication is not proof that Claude has started; confirm start only from subsequent repository evidence.
