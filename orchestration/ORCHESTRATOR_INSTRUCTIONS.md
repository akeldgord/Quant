# ARGUS Orchestrator Instructions

OWNER: ARGUS ORCHESTRATOR. The implementation agent must not edit this file.

INSTRUCTION_ID: argus-phase-4-recovery-004
ISSUED_AT: 2026-09-02T16:11:13Z
TARGET_COMMIT: 410a6c0136a5930dedaa3c03615e08aa63312032
AUTHORIZED_ACTION: PHASE_4_COMPLETE_SHARED_TEST_ASSERTIONS
AUTHORIZED_PHASE: 4
APPROVES_PHASE: NONE
STATUS: ACTIVE

## Decision

Disposition: FAIL_REMEDIATION_REQUIRED. Only the two assertion gaps below remain in COV-01. All 94 frozen parameter cases are now present. Their production paths, amount/error classifications, persisted field snapshots, fresh-engine reload, and repeated-call HTTP guard have meaningful coverage. Do not add new case families or rework production code.

F-01/F-02/F-03, P4-REC-01/04/05 and all previously closed Phase 4 production findings remain CLOSED. No production defect was demonstrated in this submission. Phase 5 remains blocked solely pending completion of the already-frozen test/evidence obligations. The user has delegated automatic safe recovery after a completed root-cause review; this ACTIVE instruction is that continuation, not another human-approval pause.

## Pinned audit and evidence

Repo/branch: akeldgord/Quant, claude/argus-folder-setup-77ahrk.
Audit target: 410a6c0136a5930dedaa3c03615e08aa63312032.
Implementation parent: 75e9ece07aa475e1ffc2413d110f5f0ee88f3134.
Authorizing instruction: argus-phase-4-recovery-003 at cc6bfd4ecdbc241fcff7334ba43d7d839b00e2aa; its target was 87e8ba1b5a7969e5afe4a7e1e6c44eb392365f16.
Handoff: handoff-0030-phase-4-recovery-3, exact matching instruction ID.
Checkpoint/bundle: orchestration/checkpoints/phase_4_recovery_3.md and orchestration/bundles/phase_4_recovery_3.txt.
MASTER_SPEC v2.0 SHA256: 41f7242c288feec709b1ed72e62c74a1dc5e3b3cd9ad01e9b6e28373d9d14011, unchanged.

Independent audit results at the pinned target:

- Git parent chain, both terminal instruction trailers, clean worktree and authorized 12-file diff verified. src/, migrations/, config, MASTER_SPEC and PROTOCOL have no changes. Replay script changes only its evidence destination. Previous checkpoints/bundles/evidence are untouched.
- `uv run pytest tests/integration/test_phase4_recovery_3_matrix.py --collect-only -q`: 94 collected. Source parameter sets independently confirm TC-01=8, TC-02=26, TC-03=8, TC-04=44, TC-05=8. This closes the missing-case inventory gap; do not expand it.
- Source inspection confirms real JupiterClient/MockTransport, production common executor, actual persisted probe reload using a fresh engine, open client across repeat, expected outcomes derived from the frozen constants, and meaningful same-field/one-HTTP assertions.
- `uv run pytest tests/unit tests/golden tests/phase_1_5 -q`: 712 passed.
- Fresh integration run stopped at fixture setup because the auditor environment lacks ARGUS_DB_ADMIN_PASSWORD. This is an environmental limitation, not a test-body failure; no credentials requested or entered. Builder raw evidence reports 162 combined tests passed, 128 focused regression tests passed and 1073 full-suite tests passed with 42 warnings. Those are builder results, not an independent PostgreSQL execution claim.
- Both final production checkpoint/bundle validators returned `(True, '')`, and exact complete checkpoint embedding passed independently.
- Ruff check passed; formatter 263 files already formatted; mypy 128 source files passed; alembic single head 0021; authentic fixtures 12/12; Python diff whitespace check clean. No new source regression found.

### Traceability / claim review

| Frozen obligation | Independent result |
|---|---|
| TC-01/02/03/04/05 input/status/kind inventory | PASS: all 94 nodes and values are present; accepted common-seam exemptions retained. |
| TC-01/03/04 persisted identity/clocks/evidence and no second HTTP | PASS for the fields actually checked by `_snapshot` and `_process_and_reprocess`; no claim that every model column was compared. |
| TC-01/03/04 unchanged scoped probe/position counts | FAIL: shared helper never queries probe count; TC-03/04 never query position count. TC-01's existing position count check is accepted. |
| TC-04 unsafe evidence rejection | PASS: exact status-only failure_evidence and injected-value absence are checked across all 44 cases. |
| TC-04 captured-log absence | FAIL: no caplog/log-capture assertion exists. Evidence serialization is not a log test. No actual production log leak is alleged. |
| TC-06 artifact format, embedding, identity, scope | PASS; old evidence preserved. Entire-matrix PASS claim is narrower than stated because of the two missing assertions. |
| Full PostgreSQL execution in auditor environment | DEFERRED environmental check; builder logs inspected, local setup unavailable. This does not excuse missing assertions. |

Adversarial review is bounded to the frozen coverage: malformed amounts, boundaries, safe/unsafe code shapes and HTTP precedence are covered; reload and duplicate dispatch are covered; duplicate-row/fill and log-output assertions are not. Concurrency, earlier temporal/migration/stream behavior and real-provider environmental checks are unchanged and not reopened. Raw-output whitespace is HARDENING_BACKLOG and never blocks.

## COV-01 remaining scope — SPEC_BLOCKING

Source: recovery-003 TC-01 requires unchanged row/position counts; TC-03 and TC-04 explicitly inherit TC-01's count assertions; TC-04 explicitly requires absence from captured logs. These requirements were frozen before the 94 tests were written. There is no new payload, safety threshold or product rule.

Observed source at target, tests/integration/test_phase4_recovery_3_matrix.py:

- `_process_and_reprocess` (around lines 176-234) compares `_snapshot` dictionaries and `handler.calls` only. `_snapshot` does not count rows. Neither function can detect an extra probe or position that leaves the selected probe unchanged.
- `test_tc03_status_and_code_mapping_worker_and_reload_idempotent` discards `_wallet_id` and checks only outcome/evidence after the shared helper.
- `test_tc04_unsafe_provider_code_never_persisted_worker_and_reload_idempotent` does the same and checks `str(snapshot_after['failure_evidence'])`. It does not capture or inspect logs. No `caplog` or other logging capture exists in this module.

Required change: complete these assertions in the EXISTING shared test helper and TC-04. Keep the 94-case inventory; do not write another parallel matrix or change src/.

## Completed root-cause review

1. Gate clarity: the assertions were explicit, but the architect's prior process correction emphasized Cartesian case counts more than assertion completeness. Correct that process by using the two assertion rows below and checking the helper body, not issuing a longer case list.
2. Implementation failure: the builder added all input combinations but reused a helper that observes only one row; it also substituted evidence serialization for logging capture. The problem is test-oracle completeness, not a newly demonstrated production defect.
3. Goalposts: no new requirement. Count and captured-log checks are verbatim obligations of the previously frozen TC rows. No optional fuzzing, full-model-column equality, new concurrency test or Phase 5 condition is added.
4. Why green tests missed it: extra rows and log output are outside the current assertions. The correction is to observe those two outputs explicitly across the existing cases. New assertions may pass immediately against current correct production code; never manufacture a failing product test or patch production to create red/green evidence.

Attempt history remains visible: initial Phase 4 build, remediation-001, remediation-002, failure-review-001, recovery-001, recovery-review-001, recovery-002, recovery-003, this reviewed recovery-004. This is not a reset of the one-ordinary-remediation limit.

Seven-part no-moving-goalposts justification: (1) source is recovery-003 at cc6bfd4..., TC-01/03/04; (2) failure is directly visible in the exact shared helper/test sources above; (3) existing assertions and parameters remain unchanged in meaning; (4) another bounded pass is needed only to complete mandatory test oracles; (5) earlier green suites could not observe extra rows/logs; (6) scope is two shared test assertions and new evidence, production closed; (7) the completed review plus the user's continuing safe-build authority permits immediate recovery, not live/paid/credential/destructive/strategy actions.

## Frozen completion matrix and exact implementation directions

Use the existing module tests/integration/test_phase4_recovery_3_matrix.py. Keep its 94 parameter cases and reuse its real adapter, common executor and fresh-session helper.

| ID | Required implementation and pass condition |
|---|---|
| ASSERT-01 / TC-01,03,04 | Extend the shared helper to observe scoped database counts before first execution, after its committed result, and after fresh-session repeat. Compare the SAME scope at all three points. For every failure case, probe-row count and wallet-position count must stay unchanged, in addition to existing selected-row snapshot equality and exactly one transport call. The TC-01/03/04 cases all return non-success; do not apply a no-new-position oracle to TC-02 success. |
| ASSERT-02 / TC-04 | Add pytest caplog (or equivalent actual logging capture) around both executor calls for all 44 existing TC-04 cases. Capture DEBUG and above. Assert injected fake sibling/header values, nonempty unsafe code strings and their escaped representations are absent from captured formatted log messages/arguments. Retain exact status-only evidence and fresh-reload checks. Do not assert that the entire log is empty: safe HTTP method/status/timing messages are allowed. |

ASSERT-01 implementation order:

1. Pass the seeded wallet_id from TC-01/03/04 into `_process_and_reprocess`; stop discarding it in TC-03/04. Read the selected persisted probe's shadow_intent_id or shadow_position_id, and verify it belongs to that seeded wallet before taking counts. This gives the count queries the correct test-owned scope. Process the same probe_id as today; do not broadly process unrelated due work.
2. For an entry probe, count ShadowQuoteProbe rows with that shadow_intent_id and count ShadowPosition rows for the seeded wallet. For a reverse probe, count ShadowQuoteProbe rows with that shadow_position_id and count ShadowPosition rows for the seeded wallet. Use `select(func.count())` on these scopes; never a table-wide production count. The expected initial counts come from persisted fixture state, not hard-coded totals for unrelated rows.
3. Capture the two counts before `_execute_and_record_probe`. In fresh sessions, capture after the first execution and after repeat. Assert `before_counts == after_first_counts == after_repeat_counts`. Preserve the existing real first execution, snapshot checks, fresh engine and one-HTTP assertion. Retain the required non-null ordered request/response/terminal clocks on terminal non-success cases; putting the already-existing TC-01 clock assertion in the common helper is acceptable.
4. Do not delete rows, reset counters or clean up between snapshots. Existing cleanup runs only in the test's finally block after assertions. No schema/product changes.

ASSERT-02 implementation order:

1. Add the caplog fixture to TC-04 and enable DEBUG capture before calling the shared helper. Keep capture active through first execution, reload and repeat; clear before the case, not before assertions. No production logger change is needed.
2. Inspect actual captured records/messages, including formatted arguments, for the existing inert test sentinels (`sk-live-should-never-be-stored`, `apiKey=SECRET`, `trace-should-not-be-stored-either`, `should-never-be-stored`, `AUDIT_ONLY_FAKE_SECRET`) and nonempty string unsafe-code values, including JSON-escaped newline/control forms. Empty string is NOT an absence sentinel; skip that literal when testing substring absence. For non-string unsafe values, retain the exact status-only evidence assertion rather than treating generic strings like `True` or `123` as secrets in unrelated safe log metadata.
3. This remains the existing bounded identifier-format policy, not a new arbitrary-secret detector. Use only fake literals already in fixtures. Never inject a real credential or collect/disclose real provider headers.

Self-audit before handoff: point ASSERT-01 to the actual SQL count queries and three-way assertions, and ASSERT-02 to actual logging-capture assertions. A matching row label or test count is not sufficient. Do not claim byte-for-byte equality of the complete model when comparing only the named frozen snapshot fields.

## Allowed scope and evidence

Allowed files: the existing test module above; new orchestration/checkpoints/phase_4_recovery_4.md; new orchestration/bundles/phase_4_recovery_4.txt; new orchestration/phase_4_recovery_4/evidence/; docs/BUILD_STATE.md; append-only docs/DECISION_LOG.md; orchestration/AGENT_HANDOFF.md. Before regression commands invoke replay generation, change ONLY scripts/argus_phase4_replay_demo.py EVIDENCE_DIR to the new phase_4_recovery_4/evidence directory. No other replay-script change. Preserve every prior checkpoint, bundle and evidence byte. Do not run first and restore overwritten historical evidence afterward.

Keep src/, migrations/, config, MASTER_SPEC.md, PROTOCOL.md, watcher scripts and old test assertions unchanged except for the specific shared-helper/capture completion above. Do not add further production repairs, alter scores, relax thresholds, enter/disclose credentials, use paid/new providers, arm live execution, access signing keys or mutate persistent evidence. Existing disposable test setup only.

Commands:

- `uv run pytest tests/integration/test_phase4_recovery_3_matrix.py --collect-only -q` (same 94-case inventory).
- `uv run pytest tests/integration/test_phase4_recovery_3_matrix.py tests/integration/test_phase4_recovery_2.py tests/unit/test_phase4_recovery_2_contract.py -q`.
- `uv run pytest tests/integration/test_shadow_phase4_remediation_observation.py tests/integration/test_shadow_quote_jobs_provider_remediation.py tests/integration/test_shadow_phase4.py tests/integration/test_shadow_phase4_concurrency_remediation.py tests/integration/test_migrations.py tests/integration/test_daily_report_remediation.py tests/integration/test_replay_demo_isolation.py -q`.
- `uv run pytest -q`; `uv run ruff check .`; `uv run ruff format --check .`; `uv run mypy src`; `uv run alembic heads`; `uv run argus fixtures validate-real-chain`.
- Existing secret-scan procedure and final git diff/status/trailer checks. Report legitimate environment limits distinctly; raw-evidence whitespace remains nonblocking.

The new checkpoint must contain exact existing first/last markers, PROJECT: ARGUS, phase 4, one STATUS and one actual full GIT_COMMIT from this run, Commands actually run, Test results, Acceptance criteria, Deviations, Known bugs/debt, Security state and Next action/STOP. Map ASSERT-01/02 to the actual assertions and inherited TC rows; carry accepted rows forward without claiming new independent runs. Preserve existing environmental deferrals: PG17_COMPOSE_VALIDATION, LIVE_HELIUS_RPC_VALIDATION, LIVE_HELIUS_WSS_VALIDATION, BQ_PUBLIC_DATASET_ACCESS. None permits live use.

Bundle complete final checkpoint bytes with raw command output and identity/diff. AFTER final generation/hash-fill, assert both existing production validators return `(True, '')` and complete checkpoint text occurs in bundle. Do not edit validators or historical evidence.

Every Claude commit must end with exactly `ARGUS-INSTRUCTION-ID: argus-phase-4-recovery-004` and nothing after it. New handoff ID; LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-4-recovery-004; CURRENT_PHASE: 4; WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION; WORKING_TREE: clean; exact new checkpoint/bundle paths; actual commit from this run. Keep approved phase 3 and approved commit efb8837f01ab6aaa451c6ee3263e4effa389c4e6 until independent approval. Verify this instruction is one instruction-only commit whose direct parent equals TARGET_COMMIT, synchronize first, commit/push, verify remote and STOP. No self-approval or Phase 5 work.

Next orchestrator audit is limited to ASSERT-01/02 and directly affected regressions. Once these frozen obligations are proven, stop digging for optional test improvements. Approve Phase 4 with the existing environmental limitations and freeze/authorize immediate Phase 5 if the master gate permits. Any further legitimate failure requires a new actual root-cause review, not blind repetition; supported safe recovery follows automatically within delegated authority. Human input is reserved for real authority/strategy decisions. Never bypass tooling denials or claim the builder has started merely because an instruction was published.
