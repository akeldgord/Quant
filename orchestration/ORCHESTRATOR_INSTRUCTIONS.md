# ARGUS Orchestrator Instructions

OWNER: ARGUS ORCHESTRATOR. The implementation agent must not modify this file.
MASTER_SPEC.md remains authoritative. Execute only this ACTIVE instruction.

INSTRUCTION_ID: argus-phase-4-recovery-002
ISSUED_AT: 2026-09-02T13:07:46Z
TARGET_COMMIT: 055e3a2141983d4b8a7b01e91e177588dddaea6b
AUTHORIZED_ACTION: PHASE_4_ROOT_CAUSE_RECOVERY
AUTHORIZED_PHASE: 4
APPROVES_PHASE: NONE
STATUS: ACTIVE

## Authority, scope and disposition

The human explicitly approved the process correction: complete root-cause review, freeze a recovery contract and continue automatically within existing authority; do not require another human restart solely because a phase failed. This supersedes the idle human-approval STOP in argus-phase-4-recovery-review-001. It does not waive any implementation gate, grant live authority, reset attempt history or approve Phase 4.

The prior completed audit/review is preserved at commit 055e3a2141983d4b8a7b01e91e177588dddaea6b, path orchestration/ORCHESTRATOR_INSTRUCTIONS.md. Its audited implementation/handoff target was 29a49ff4aa2618ae016a6ed90cd8ba680310a95e. Current HEAD adds only that review instruction to the audited implementation. This contract uses the established findings; it does not claim a new implementation audit.

Implement ONLY F-01, F-02 and F-03 from that review, as frozen below. Phase 4 remains FAIL_REMEDIATION_REQUIRED until independent re-audit; Phase 5 remains blocked. No additional ordinary remediation round is being issued. History remains: initial Phase 4 build, ordinary remediation-001, previously issued remediation-002, root-cause review-001, human-authorized recovery-001, recovery-review-001, this recovery-002. Do not hide or reset these attempts.

Closed findings remain CLOSED: P4-REC-01 (time cutoffs), P4-REC-04 (populated migration compatibility), P4-REC-05 (report-end history), earlier R2/R3/R5/R7 and all other independently closed findings. Exercise existing regression tests; do not redesign or re-open them. Classifications are only SPEC_BLOCKING, SAFETY_OR_INTEGRITY_BLOCKING and HARDENING_BACKLOG. Hardening never blocks. Do not promote SHOULD/MAY to MUST.

## Completed root-cause review and process correction

1. Frozen gate clarity: malformed required amounts already had to produce terminal non-success, but the architect's examples missed Python isdigit/int conversion failures. Supplied safe HTTP429 codes, value sanitization, and checkpoint validators were explicit. Freeze executable negative cases before changing code.
2. Implementation failure: an unguarded conversion escaped; HTTP429 returned before extracting code; a type/length check substituted for sanitization; the builder did not assert final artifact-validator results. Fix these shared paths, not unrelated architecture.
3. No moving goalposts: all three failures derive from P4-REC-02, P4-REC-03 or existing MASTER_SPEC section 104 / PROTOCOL section 5. No route economics, fee normalization, new sample target, live-provider validation or Phase 5 feature is added.
4. Tests missed the defects because ASCII garbage never entered failing int(), the 429 fixture omitted errorCode, unsafe values were only in ignored sibling keys/headers, and generated checkpoint bytes were not mechanically checked. New regressions must exercise those exact failure branches and demonstrate pre-fix failure before implementation.

The review is complete, so Claude now has authorized bounded work. If this recovery fails, the orchestrator must review the remaining legitimate defects and root causes before another recovery contract. A repeat failure is not permission for blind patches, changed acceptance thresholds, or reopening unrelated closed rows. Within delegated safe scope, the orchestrator should publish the supported recovery in the same run; stop for human input only for a real authority/strategy decision or when no evidence-backed safe recovery can be specified. Tool permission denials must be reported and never bypassed.

## Frozen implementation decisions

### F-01 — SPEC_BLOCKING: total nested raw-amount validation

Source: P4-REC-02 malformed-field non-success obligation, condition 5, and shared terminal/replay behavior. Known surface: src/argus/shadow/quote_jobs.py, _is_positive_raw_amount, _is_structurally_valid_route_entry, _classify_quote, _execute_and_record_probe; nested swapInfo.inAmount and outAmount; entry and reverse probes.

At the audited target, superscript-two ("\u00b2") passes isdigit() but int() raises ValueError. A 5000-digit ASCII string exceeds the default Python conversion guard. _classify_quote executes in the provider try/except's else block; the error escapes and no terminal record is written.

Keep bool rejected before the int branch; real positive ints remain accepted. For strings require nonempty ASCII decimal digits, then convert inside a ValueError/OverflowError guard and return false on failure or nonpositive value. Preserve normal positive numeric representations, including leading zeroes. Do not alter Python's global conversion limit, add a trading threshold, coerce floats, or catch unrelated errors as success. These invalid route fields use the existing NO_ROUTE classification from the structural-route validator. The shared worker must persist that terminal non-success, retain actual request/response timing, create no shadow position and make no repeated provider request when processed again. Do not add new schema or change ownership/timing guards.

### F-02 — SAFETY_OR_INTEGRITY_BLOCKING: preserve only safe supplied error evidence

Source: P4-REC-03 conditions 2 and 6. Known surface: quote_jobs._safe_provider_error_code, _classify_provider_exception and shared entry/reverse failure_evidence persistence.

Extract safe evidence before HTTP status outcome selection. Keep only http_status_code plus provider_error_code when actually supplied and valid. Choose the following bounded identifier grammar for the provider code: ASCII full-match [A-Za-z][A-Za-z0-9_]{0,127}. Preserve valid unknown identifiers verbatim; do not invent their meaning. Empty, wrong-type, overlong, URL/query/assignment/control/body-like values remain unavailable. Do not truncate, transform, log or copy a rejected value into another evidence field; do not persist the body, request URL or headers. This is a format policy for identifiers, not a claim to detect every possible secret hidden in arbitrary text.

HTTP429 always remains PROVIDER_CAPACITY_MISS, even when code is absent, malformed or equals the known no-route identifier. Preserve a supplied valid code with its status. Other status responses retain the already-established known no-route-code mapping; unknown/missing/unsafe codes remain QUOTE_FAILED with status. Invalid/non-object JSON yields status only and the appropriate status-derived outcome; parsing failure must not erase HTTP429 capacity classification. Preserve the already-closed controlled RequestDropped reason/priority path. No provider endpoints, schema, score or credential changes are required.

### F-03 — SPEC_BLOCKING: validate the exact final handoff artifacts

Source: MASTER_SPEC section 104 and orchestration/PROTOCOL.md section 5. Existing implementation: scripts/argus_orchestrator_watch.py, validate_checkpoint_content and validate_bundle_content, both returning (ok, reason).

Create NEW paths:
- orchestration/checkpoints/phase_4_recovery_2.md
- orchestration/bundles/phase_4_recovery_2.txt
- any newly generated replay evidence: orchestration/phase_4_recovery_2/evidence/

Do not overwrite any prior checkpoint, bundle or replay evidence. If the existing replay demonstration is run, route its new output to the new evidence directory before execution; changing only that output destination and its corresponding test expectation is allowed. Do not run cleanup against any existing database/history. Preserve the accepted disposable scratch replay isolation.

Checkpoint first line: ================ ARGUS ORCHESTRATOR CHECKPOINT ================
Checkpoint last nonblank line: ================ END ARGUS CHECKPOINT =========================

Include PROJECT: ARGUS, authorized phase 4, exactly one STATUS field and one GIT_COMMIT field containing a full actual commit SHA created during this run. Include explicit sections Commands actually run, Test results, Acceptance criteria, Deviations, Known bugs/debt, Security state and Next action/STOP. Include the matrix below row by row with implementation path/symbol, test node, actual result and limitation. Missing proof is FAIL/BLOCKED, never inferred PASS. The bundle must embed the final checkpoint exactly and contain raw command output, code diff/identity and limitations.

After final hash-fill changes, assert BOTH existing validator return values. Calling the functions without asserting ok is not validation. Additionally assert the complete checkpoint text is contained in the bundle (no paraphrase or stale embedded version). Preserve the existing negative-validator tests. Do not edit or weaken the watcher, protocol, master spec or previous evidence.

## Atomic acceptance matrix — frozen before implementation

All rows use deterministic mocked transport and controlled test state, not live providers. Cover entry and reverse worker kinds through their production caller or prove and exercise their common execution seam. Expected outcomes below derive from the frozen contract, not the implementation. Add tests in tests/integration/test_phase4_recovery_2.py for worker/persistence rows and tests/unit/test_phase4_recovery_2_contract.py for parser/artifact rows, using repository fixtures.

| ID | Setup and action | Required pass condition / evidence |
|---|---|---|
| AM-01 | Real JupiterClient + MockTransport HTTP200 valid top-level quote, one valid route, one nested field set to "\u00b2"; parameterize inAmount/outAmount and entry/reverse. Process via worker. | No exception; NO_ROUTE; terminal_at set; real dispatch/response clocks present and ordered; no new ShadowPosition. Pre-fix escapes ValueError. |
| AM-02 | Same four combinations with "1" repeated 5000 times under the existing interpreter default conversion guard. | Same terminal NO_ROUTE/no-fill assertions. Do not disable/change global conversion guard. Pre-fix raises ValueError. |
| AM-03 | Fresh-session reload of each AM-01/02 terminal record, then process again. | Same identity/outcome/timing; zero additional HTTP and zero additional shadow positions; no duplicate terminal evidence. |
| AM-04 | Parameterize either nested amount with "1", "001", integer 1; normal complete route. Also empty/ASCII garbage/"0"/0/"-1"/-1/True/1.5/None/non-ASCII digits. | Valid positive cases retain SUCCESS; invalid cases terminal NO_ROUTE and no fill. Both nested fields use total validator; existing top-level mint/impact gates stay green. |
| AM-05 | Real-adapter HTTP429 body {"errorCode":"AUDIT_RATE_LIMIT"}, both worker kinds. | PROVIDER_CAPACITY_MISS; persisted evidence exactly {"http_status_code":429,"provider_error_code":"AUDIT_RATE_LIMIT"}. Pre-fix loses code. |
| AM-06 | HTTP429 with absent errorCode, invalid JSON, non-object JSON, or unsafe/wrong-type code. | PROVIDER_CAPACITY_MISS; status 429 retained; no invented provider_error_code. |
| AM-07 | HTTP400 known COULD_NOT_FIND_ANY_ROUTE; HTTP400 UNKNOWN_SAFE_CODE; HTTP429 with known no-route code. | Respectively NO_ROUTE, QUOTE_FAILED, PROVIDER_CAPACITY_MISS; exact supplied valid code/status retained. No invented unknown mapping. |
| AM-08 | errorCode values URL with inert api_key query, "api_key=AUDIT_ONLY_FAKE_SECRET", embedded newline/control, JSON-body-shaped string, empty string, 129 ASCII letters, bool, integer, dict/list. Put inert secret/header fields in ignored siblings too. Test 400 and 429. | provider_error_code absent; only status persisted; 400 QUOTE_FAILED / 429 PROVIDER_CAPACITY_MISS. Rejected strings and body/header/URL absent from persisted evidence and any new logs. Use fake literals only. Pre-fix short unsafe strings survive. |
| AM-09 | Valid identifier boundary: 1 and 128 ASCII characters, plus unknown identifier with digits/underscore; test 400/429. | Exact code preserved, appropriate unchanged coarse outcome; 129 rejected. No trimming or normalization. |
| AM-10 | Fresh-session reload + repeated processing after AM-05/07/08; parameterize both worker kinds. | Exact sanitized evidence survives reload; zero additional HTTP, no new fill/duplicate row or changed terminal clocks. |
| AM-11 | Existing real PriorityScheduler rejection path. | Controlled drop reason/priority preserved, zero HTTP, requested_at/responded_at null, terminal timestamp present, replay unchanged. Existing passing test may supply proof; do not redesign. |
| AM-12 | After all generation/hash-fill steps read NEW checkpoint and bundle exact UTF-8 contents. Call production validators, inspect (ok, reason), check exact embedding. | Both ok are true with empty reasons, complete matrix included, exact valid first/last markers; checkpoint and handoff commits resolve to this run. Record validation output. |
| AM-13 | Negative artifact fixtures: missing end marker; marker present but acceptance-criteria section missing; mismatched embedded checkpoint. | Existing validators return false for each; no production validator edits. Existing failing recovery checkpoint remains untouched. |
| AM-14 | Run focused prior observation/provider/phase4/concurrency/migration/report/isolation suites plus full prior-phase regression and static checks below. | No new product regression; legitimate environment limits reported separately. Previously closed rows stay closed unless a concrete change-induced regression is proven. |
| AM-15 | Inspect final diff, trailers, fresh remote SHA, new paths and handoff. | Only authorized surfaces changed; exact new instruction ID, new handoff ID, clean/pushed state; all previous evidence unchanged; no Phase4 self-approval/Phase5 work or live action. |

## Ordered execution and self-audit

1. Follow PROTOCOL session-start/read order. Verify clean worktree and freshly fetched remote HEAD. The instruction commit must be the sole instruction-only commit directly above TARGET_COMMIT. Reject mismatched parent or extra file changes. Read preserved review at TARGET_COMMIT for detailed proof; all current obligations are frozen here.
2. Add named regressions mapped to AM-01 through AM-13. Run the applicable counterexamples against pre-fix production code and retain honest failing output; do not use xfail to disguise missing closure. Existing correct cases need not fail.
3. Implement only F-01 shared validation and F-02 shared extraction/classification. No schema changes, new providers, live network or score changes. Run targeted tests, including actual persisted reload/replay on the already-authorized test environment.
4. Run the acceptance commands. Use only previously authorized disposable test databases with existing test setup. Do not enter/disclose credentials, create paid accounts, access live wallet signing, or run destructive operations against persistent evidence.
5. Create the new checkpoint/bundle and update docs/BUILD_STATE.md, docs/DECISION_LOG.md and orchestration/AGENT_HANDOFF.md truthfully. Preserve approved phase 3/approved commit and current phase 4 until independent approval. Do not rewrite failed historical evidence.
6. Validate final artifact bytes, field counts, instruction ID and terminal trailers after hash-fill. Commit/push with exact terminal trailer ARGUS-INSTRUCTION-ID: argus-phase-4-recovery-002 and nothing after it on every Claude commit.
7. Stop for independent audit. No builder self-approval. Handoff LAST_ORCHESTRATOR_INSTRUCTION_ID must be exactly argus-phase-4-recovery-002; CHECKPOINT_PATH and BUNDLE_PATH exactly as above; new HANDOFF_ID; phase 4; actual commit from this run; WORKING_TREE clean; WORK_STATUS AWAITING_ORCHESTRATOR_INSTRUCTION.

## Acceptance commands and proof

Run from repository root:
- uv run pytest tests/unit/test_phase4_recovery_2_contract.py tests/integration/test_phase4_recovery_2.py -q
- uv run pytest tests/integration/test_shadow_phase4_remediation_observation.py tests/integration/test_shadow_quote_jobs_provider_remediation.py tests/integration/test_shadow_phase4.py tests/integration/test_shadow_phase4_concurrency_remediation.py tests/integration/test_migrations.py tests/integration/test_daily_report_remediation.py tests/integration/test_replay_demo_isolation.py -q
- uv run pytest -q
- uv run ruff check .
- uv run ruff format --check .
- uv run mypy src
- uv run alembic heads
- uv run argus fixtures validate-real-chain
- Existing checkpoint/bundle validators with explicit ok/reason assertions on final files; inspect exact bytes after hash-fill.
- Existing secret-scan procedure on changed files/new evidence, without printing any discovered secret.
- git diff --check; git status --porcelain; verify changed-path list and git log commit messages/trailers.

Record actual command outputs, counts, exit codes, skips and environment. No fabricated PASS, silent skip or aggregate count substituted for a matrix row. alembic heads is graph evidence, not a database-upgrade claim. Keep prior approved environmental deferrals LIVE_HELIUS_RPC_VALIDATION, LIVE_HELIUS_WSS_VALIDATION, PG17_COMPOSE_VALIDATION and BQ_PUBLIC_DATASET_ACCESS unchanged; PG16 substitute stays accepted where previously accepted. Unavailable local DB setup is an explicit environment limitation, not permission for credentials/new infrastructure. Existing ordinary integration tests still need honest evidence from an already authorized environment; do not relabel a missing product fix as environmental deferral.

## Safety boundaries and next orchestration action

No mainnet trading, canary, signing/private keys/seeds, credential entry/disclosure, new paid/provider use, live arming, threshold relaxation, strategy change, destructive production migration, history deletion, evidence rewrite or phase skip. Mock quotes do not prove live readiness. The accepted replay-only path and honest one-wallet Phase3 limitation stay accepted.

On a matching handoff, the orchestrator independently audits this frozen matrix and affected safety/integrity regressions. If PASS, authorize immediate Phase5 only if the master gate permits, with its acceptance matrix frozen first. If FAIL, complete the root-cause review and issue a safe bounded recovery within delegated authority; escalate only an actual authority decision or inability to specify a supported safe path. Neither green builder tests nor this process rule authorizes later phases automatically without independent acceptance.

Claude: execute this bounded recovery, submit its exact evidence, then STOP for independent audit.
