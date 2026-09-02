# ARGUS Orchestrator Instructions

OWNER: ARGUS ORCHESTRATOR. The implementation agent must not modify this file.
MASTER_SPEC.md remains authoritative. Execute only an ACTIVE instruction.

INSTRUCTION_ID: argus-phase-4-recovery-review-001
ISSUED_AT: 2026-09-02T04:16:00Z
TARGET_COMMIT: 29a49ff4aa2618ae016a6ed90cd8ba680310a95e
AUTHORIZED_ACTION: NONE
AUTHORIZED_PHASE: 4
APPROVES_PHASE: NONE
STATUS: NO_INSTRUCTION

## Disposition and immediate control state

AUDIT_DISPOSITION: FAIL_REMEDIATION_REQUIRED
IMPLEMENTATION_STATE: STOPPED_AFTER_RECOVERY_AUDIT

This document records a completed independent audit and failure root-cause review. It does not launch another repair. The human-approved one-build/one-remediation process is not reset by renaming a further attempt. The explicitly authorized recovery has now been audited; further implementation needs explicit recovery direction. Phase 4 is not approved. Phase 5 remains blocked. The phase field preserves context only; AUTHORIZED_ACTION NONE and STATUS NO_INSTRUCTION authorize no implementation.

Three recovery rows are CLOSED: P4-REC-01, P4-REC-04, P4-REC-05. Keep them closed. Two rows remain incomplete: P4-REC-02 and P4-REC-03. There is also a concrete current-submission checkpoint-format regression under the unchanged handoff contract. The consolidated findings and inert correction contract below include all material failures found in this audit; no optional enhancement is blocking.

Prior phase approvals, accepted replay substitution, the honest one-wallet Phase 3 sample limitation, and approved environmental deferrals remain unchanged. No live, signing, credential, paid-provider, threshold-relaxation, evidence-rewrite, or phase-skip authority is granted.

## Audit identity and authority

- Repository/branch: akeldgord/Quant / claude/argus-folder-setup-77ahrk.
- Audited remote handoff commit: 29a49ff4aa2618ae016a6ed90cd8ba680310a95e.
- Direct parent / implementation commit: f932ce1a61358fd5bbdcc4fe7fcf64ff777a35ac.
- Implementation base / recovery authorization: e8f78088dca01a0915345844eb64a1b99beec993; its parent is the previous failure-review commit 9aa8b8decf8cb17e1b3bb28e9e1ebd0b2083acda.
- Audited instruction: argus-phase-4-recovery-001, ACTIVE at submission, target 9aa8b8decf8cb17e1b3bb28e9e1ebd0b2083acda. Human authorization to proceed was explicitly supplied.
- Handoff: handoff-0028-phase-4-recovery; LAST_ORCHESTRATOR_INSTRUCTION_ID exactly argus-phase-4-recovery-001; CURRENT_COMMIT f932ce1a61358fd5bbdcc4fe7fcf64ff777a35ac, within the two-commit submission.
- Evidence: orchestration/checkpoints/phase_4_recovery.md and orchestration/bundles/phase_4_recovery.txt, newly added by this submission; exact checkpoint bytes embedded in the bundle.
- MASTER_SPEC v2.0 SHA256: 41f7242c288feec709b1ed72e62c74a1dc5e3b3cd9ad01e9b6e28373d9d14011.
- Recovery instruction blob unchanged by Claude: 8d287c05b99a1d0da3fd570b82e2c4faecba0069. MASTER_SPEC.md and orchestration/PROTOCOL.md unchanged. Both Claude commits have the exact terminal recovery trailer, with no following paragraph.
- No builder self-approval: BUILD_STATE retains last_orchestrator_approved_phase 3 and approved_commit efb8837f01ab6aaa451c6ee3263e4effa389c4e6.

Authority: canonical spec and approved human changes, frozen recovery matrix, unchanged protocol, then builder claims and implementation evidence. Review is bounded to the five recovery rows, their current changes, and direct safety/integrity/control-plane regressions. Previously closed R2/R3/R5/R7 and other closed Phase 4 behavior are not reopened.

## Independent work and environment

Fresh remote HEAD and pinned instruction/handoff reads preceded local checkout of the exact submission. Read the submitted diff, relevant MASTER_SPEC Phase 4 and checkpoint contracts, BUILD_STATE and decision-log changes, protocol, checkpoint/bundle, new and affected test sources, migration 0020/0021, production quote/temporal/report consumers, and their sibling callers. The earlier unchanged authority and closure records remain in force.

Auditor-executed checks:

| Command/check | Actual result |
|---|---|
| `uv run pytest tests/unit tests/golden tests/phase_1_5 -q` | 660 passed in 106.50s; exit 0. |
| `uv run ruff check .` | All checks passed; exit 0. |
| `uv run ruff format --check .` | 258 files already formatted; exit 0. Builder reports 257; not a functional gate discrepancy. |
| `uv run mypy src` | No issues in 128 source files; exit 0. |
| `uv run alembic heads` | One head, 0021; exit 0. This is graph validation, not a database upgrade. |
| `uv run argus fixtures validate-real-chain` | 12/12 real-chain fixtures OK; exit 0. |
| `uv run pytest tests/integration/test_replay_demo_isolation.py -k refuse_unless -q` | 2 passed, 6 intentionally deselected, 1.44s. Only safe refusal paths executed. |
| `uv run pytest tests/integration/test_shadow_quote_jobs_provider_remediation.py -q -x` | Setup blocked by MissingCredentialError for ARGUS_DB_ADMIN_PASSWORD; 1 setup error in 2.31s. No database/provider product failure inferred. No credential requested or entered. |
| Audit-owned production-path probe script | Exit 0 after asserting every reported pass/failure below. Real JupiterClient + httpx.MockTransport; real quote execution function with controlled session seam; real temporal/report SQL compiled/executed on SQLite where semantics apply; actual migration upgrade operations captured and its SQL applied to an in-memory predecessor-shaped table. No external HTTP or PostgreSQL claim. |
| Audit-owned correct-behavior regression tests | 6 failed in 1.78s against submitted code, as expected for the defects: two malformed amount cases, supplied 429 code, unsafe code value, checkpoint marker, and missing acceptance section. These are new auditor tests, not six failures in the builder's recorded suite. |
| Checkpoint/bundle production validators | Checkpoint rejected: missing standard end marker. A virtual marker-only repair then rejected for missing `acceptance criteria` section text. Exact checkpoint embedding independently confirmed. |
| `git diff --check e8f78088dca01a0915345844eb64a1b99beec993 HEAD` | Exit 2 solely for a new blank line at bundle EOF. HARDENING_BACKLOG, not blocking. |
| Local worktree | Clean after audit. No implementation, fixture, historical evidence, or credential file edited. |

Builder-reported, source-reviewed but NOT auditor-reexecuted PostgreSQL results: 911 repository tests and 128 focused tests, 42 warnings; 21 migration tests including four new populated-predecessor cases; PG16 substitute, not PG17. The bundle includes results and a generation-time dirty metadata snapshot before the hash-fill commit; final committed identity is separately verified. A green count is not proof that a test covers its claimed clause.

Audit scratch artifacts: argus_phase4_recovery_audit.py (production-path observations) and test_argus_recovery_contract.py (six correct-behavior failures). These are outside the repository and are not implementation deliverables. The exact relevant counterexamples and expected assertions are reproduced below so audit results do not depend on retaining scratch files. An initial probe run mistakenly treated the checkpoint validator's `(ok, reason)` return as an exception API; this audit-harness error was corrected, then the full probe rerun exited 0. No conclusion relies on that initial harness error.

## Frozen acceptance traceability — all 31 numbered conditions

PASS below means the stated clause is established by production inspection, meaningful test-source inspection and the noted independent probe. It does not assert auditor execution of unavailable PostgreSQL integration tests.

| Frozen condition | Evidence and observation | Status |
|---|---|---|
| REC-01.1 split-clock Token excluded | prospective._token_state_snapshot checks first_observed_at and created_at; actual helper probe T/T+1h unavailable; builder split-clock test drives scanner. | PASS |
| REC-01.2 equality Token allowed | Both clocks T returns available; scanner equality test. | PASS |
| REC-01.3 split-clock position excluded | WalletPosition.created_at <= cutoff in real context query; independent query returns zero for created T+1h. | PASS |
| REC-01.4 equality position included | Same independent query with created T returns one; builder scanner test checks amount 10. | PASS |
| REC-01.5 previous temporal regressions | Existing score/tier/market/cluster/single-history predicates untouched; 35-test source/result group inspected, offline regressions green. | PASS, DB rerun unavailable |
| REC-02.1 complete route SUCCESS | Real adapter/mock transport through execution seam returns SUCCESS. | PASS |
| REC-02.2 empty swapInfo not SUCCESS | Same production path returns NO_ROUTE; meaningful builder case. | PASS |
| REC-02.3 missing mint/amount not SUCCESS | Required nested fields checked and parameterized source inspected. | PASS |
| REC-02.4 wrong-type mint not SUCCESS | Real adapter path with numeric mint returns NO_ROUTE; builder cases include empty string. | PASS |
| REC-02.5 malformed/nonpositive raw amount classified non-success | Ordinary garbage/zero/negative/bool/float rejected, but superscript digit and 5000-digit string raise uncaught ValueError after HTTP instead of recording non-success. | FAIL, F-01 |
| REC-02.6 invalid route creates no shadow sample | Builder entry tests assert no ShadowPosition; non-success branch prevents creation. Crashing variants also create no fill, but fail terminal behavior under REC-02.5. | PASS for no-fill obligation; F-01 remains |
| REC-02.7 prior mint/impact/no-route gates | Existing checks unchanged; tests retained; prior closed classifications stay closed. | PASS, DB rerun unavailable |
| REC-03.1 400 known code/status preserved | Real adapter probe preserves status 400 and COULD_NOT_FIND_ANY_ROUTE with NO_ROUTE. | PASS |
| REC-03.2 429 supplied status/code preserved | Actual HTTP429 body with errorCode AUDIT_RATE_LIMIT retains only status. Builder fixture omits errorCode, so its assertion cannot prove the clause. | FAIL, F-02a |
| REC-03.3 unknown safe code preserved, no invented mapping | HTTP400 UNKNOWN_SAFE_CODE remains QUOTE_FAILED with exact safe code/status. | PASS |
| REC-03.4 scheduler drop evidence/no HTTP/timestamps | Actual PriorityScheduler capacity rejection retains controlled reason/priority; zero HTTP calls, null request/response clocks, terminal timestamp present. | PASS |
| REC-03.5 reload/replay safe evidence | Builder test re-fetches persisted terminal row; independent execution seam repeats without additional call or changed evidence. Full DB restart not auditor-run. | PASS for submitted scheduler path, DB limitation explicit |
| REC-03.6 secret/URL/body/header exclusion | Extraneous body/header fields excluded, but arbitrary URL with dummy key placed in short errorCode is persisted verbatim. Length/type check is not value sanitization. | FAIL, F-02b |
| REC-04.1 populated 0018 fixtures | Test sources seed success, no-route, HTTP429-shaped capacity miss and pending rows with parent entity chain before upgrade. | PASS by inspected fixture, DB rerun unavailable |
| REC-04.2 upgrade through 0020 | Actual upgrade now backfills before CHECK; independent execution of its SQL makes CHECK true; builder PG16 result inspected. | PASS for defect closure, DB rerun unavailable |
| REC-04.3 existing evidence unchanged | Actual UPDATE targets only new terminal_at field, copying responded_at; independent predecessor-shaped rows retain all old fields. | PASS |
| REC-04.4 legacy completions terminal | Backfilled terminal_at non-null for all represented completed classes, existing consumer terminal guards remain; no fake wall-clock values. | PASS |
| REC-04.5 completed rows no provider recalls | Inspected real-worker migration test processes only pending probe and exactly one provider call; production claim query excludes non-null terminal_at. | PASS, DB rerun unavailable |
| REC-04.6 pending runnable | Backfill leaves null responded_at/terminal_at pending row intact; real-worker builder test resolves it SUCCESS. | PASS, DB rerun unavailable |
| REC-04.7 repeat startup idempotent | Executing actual backfill twice changes zero additional rows; builder test also calls upgrade-to-head twice. | PASS |
| REC-04.8 graph and ownership | Single 0021 head, existing locks/generation logic unchanged; seven concurrency tests in combined 15-test builder group. | PASS, DB concurrency rerun unavailable |
| REC-05.1 LOW before end/HIGH after | Cutoff predicate applied before PostgreSQL DISTINCT ON; independently inspected builder production-report test and alternate NOT EXISTS oracle. | PASS |
| REC-05.2 later HIGH used | Companion builder test uses later cutoff, expects no LOW contribution; same bounded ordered query. | PASS |
| REC-05.3 multiple pre-end versions one wallet | DISTINCT ON preserved; builder three-version test asserts exactly one; no SQLite multi-version equivalence claim. | PASS |
| REC-05.4 future-only history excluded | Actual production data-quality helper on single-row SQLite fixture returns zero before created_at and one after. | PASS |
| REC-05.5 prior report regressions | Quote-asset grouping, shadow mark extrema and outcome-separation code untouched; meaningful retained tests and recorded 16-test group. | PASS, DB rerun unavailable |

The ordinary production monitor calls the bounded token/position helpers. Both entry and reverse probe workers call the same quote executor/validator and exception classifier. daily._build_data_quality passes end into the bounded history query. `_build_research`'s disclosed unbounded historical display remains out of this recovery's scope, not a new blocker.

## Consolidated findings

### F-01 — malformed nested amount can escape classification

Classification: SPEC_BLOCKING.

Requirement: frozen P4-REC-02 implementation clause requires malformed required fields to produce QUOTE_FAILED or the already-frozen non-success classification, never SUCCESS; condition 5 requires malformed/nonpositive amount rejection. The shared terminal worker must preserve its outcome rather than crash during parsing.

Proof/root cause: quote_jobs._is_positive_raw_amount calls `value.isdigit()` then `int(value)` without handling ValueError. Python considers `"\u00b2"` a digit string but cannot parse it as a base-10 integer. A 5000-character ASCII digit string also exceeds the current interpreter conversion guard. A real JupiterClient with mocked HTTP200 complete top-level quote and either value in nested swapInfo.inAmount reaches this code, raises ValueError, and never sets terminal_at. `_classify_quote` runs in the try/except's `else` block, so its exception is not caught by the provider-exception handler. Both inAmount and outAmount use this helper; both entry and reverse workers share the executor. A later stale-claim retry may issue another provider call. No actual external provider retry or data loss was alleged.

Expected closure: the amount validator must be total on external values. Reject non-ASCII/non-integer encodings and conversion failures as invalid route evidence without escaping. Do not disable Python's global conversion guard or loosen any trading threshold. Preserve valid positive integer representations; retain bool/float/zero/negative rejection. Invalid evidence must cause terminal non-success and zero created shadow position.

Prospective regressions: parameterize both nested amount fields with superscript-two and a 5000-digit string, plus existing normal/garbage/zero/negative/bool/float cases. Use real adapter/mock HTTP through each worker kind or their proven shared execution seam. Assert no exception, terminal non-success, no shadow position, preserved request/response timing, and repeated processing makes no new HTTP call. Named minimum: `test_malformed_nested_amount_is_terminal_non_success` and `test_malformed_nested_amount_replay_does_not_recall_provider`.

Why existing tests missed it: ASCII garbage has isdigit=False, so tests never reached int() with a value that passes isdigit but fails conversion. The exception path was not modeled in the pre-build matrix examples. This is a missing case within the frozen malformed-field obligation, not a new route-economics requirement.

### F-02 — terminal failure evidence is incomplete and insufficiently sanitized

Classification: SAFETY_OR_INTEGRITY_BLOCKING. One defect family with two required corrections; do not duplicate it under another classification.

Requirement: frozen P4-REC-03 requires supplied safe provider code/status preservation, including HTTP429 (condition 2), and prohibits arbitrary URLs/secrets/unsanitized data in persisted failure evidence (condition 6).

F-02a proof/root cause: `_classify_provider_exception` returns immediately on status 429 before parsing a supplied errorCode. HTTP429 with `{"errorCode":"AUDIT_RATE_LIMIT"}` returns PROVIDER_CAPACITY_MISS with only `{"http_status_code":429}`. The builder test supplies only `{"error":"Too Many Requests"}` and asserts status only while the matrix marks status/code preservation PASS. Missing source code must stay absent; the failure is dropping a code when it IS supplied.

F-02b proof/root cause: `_safe_provider_error_code` checks only string type, nonempty and length <=128. HTTP400 with short errorCode `https://invalid.example/?api_key=AUDIT_ONLY_FAKE_SECRET` passes that function unchanged and is assigned verbatim to probe.failure_evidence by the real execution seam. This string is an intentionally inert audit fixture, not an actual credential. The production risk is an external field's value being treated as safe merely because its key is allowlisted. The builder secret test places secrets only in ignored sibling fields and headers, not in the selected value itself.

Full affected surface: shared HTTPStatusError extraction/classification, `_safe_provider_error_code`, shared entry/reverse terminal persistence, later reload/report consumers of failure_evidence. Genuine scheduler-generated reason/priority values are controlled locally and were verified in this audit; no unrelated scheduler redesign is required.

Expected closure: extract bounded, value-validated provider identifiers before applying status-specific outcome selection; preserve safe supplied codes for 429 without changing the capacity outcome or inventing mappings. Use a conservative bounded identifier policy that excludes URLs, query assignments, control characters and body-like strings; unsafe values stay unavailable, not stored raw, truncated into misleading identifiers, or copied into another evidence field. Keep HTTP status even when code is absent/unsafe. Do not persist response bodies, request URLs or headers. No new provider endpoints or credentials are needed.

Prospective regressions: known no-route400, unknown safe400, safe-code429, codeless429, malformed code type, empty/overlong code, URL/control/body-shaped short code. Put inert secret/URL content inside errorCode itself as well as sibling fields/headers. Assert exact allowed stored fields, correct coarse outcomes, and fresh-session reload/replay preservation with zero repeated HTTP. Minimum names: `test_429_preserves_supplied_safe_provider_code`, `test_provider_code_rejects_arbitrary_url_and_dummy_secret`, `test_terminal_failure_evidence_reload_preserves_sanitized_fields`.

Why existing tests missed it: the 429 fixture lacked the field that the pass condition required preserving; the safety fixture only exercised key selection, not value sanitization. These are explicit pre-build conditions, not new safety standards imposed after implementation.

### F-03 — new checkpoint cannot pass the existing handoff validator

Classification: SPEC_BLOCKING.

Requirement: MASTER_SPEC section 104 and PROTOCOL section 5 require the standard terminal marker and a checkpoint covering acceptance criteria; the unchanged watcher mechanically enforces this. Recovery's handoff contract requires normal protocol artifacts.

Proof: `validate_checkpoint_content(actual_checkpoint)` returns `(False, "checkpoint is missing the standard end marker on its last line")`. Virtually appending the standard marker, without altering any repository file, returns `(False, "checkpoint missing a section covering 'acceptance criteria'")`. The file has a substantive acceptance matrix, but lacks the literal required section text; do not misstate this as absent technical analysis. The exact malformed checkpoint is embedded in the bundle. The real watcher therefore rejects this handoff regardless of the test count. This is a regression in a newly generated artifact, not reopening an earlier correctly formatted historical checkpoint.

Expected closure: generate the next authorized NEW checkpoint/bundle under new paths, with all normal identity/section fields, an explicit Acceptance criteria section mapping the frozen rows, and exact required end marker as the last nonblank line. Assert the return values of BOTH production validators, not merely call the functions or assume they raise. Preserve old committed evidence, including this failed submission. No watcher weakening or protocol edit is authorized or needed.

Prospective regressions: `test_submitted_checkpoint_passes_existing_validator`; complete post-generation checkpoint validation; matching bundle validation; negative missing-marker and missing-section cases remain rejected. A marker-only edit is insufficient. The acceptance matrix must report actual failures rather than universal PASS.

## Adversarial coverage and claim ledger

| Failure class | Independent coverage | Result |
|---|---|---|
| Temporal split clocks / equality | Real token helper and actual position SQL; report before/after single-history created time; PG query ordering inspected. | TESTED_PASS for targeted gaps; DB multi-version tests inspected. |
| Malformed external nested numbers | Normal, zero, negative, garbage, bool, float, Unicode non-integer digit, overlong numeric string. | TESTED_FAIL only conversion-escape family F-01. |
| External error status/code | Real adapter400 known/unknown and429 supplied-code through executor. | TESTED_FAIL F-02a;400 paths pass. |
| Unsafe values in selected fields | Inert URL/key string in short errorCode, not ignored sibling field. | TESTED_FAIL F-02b; no real secret exposure claimed. |
| Scheduler missing capacity / repeated processing | Actual scheduler rejection, no HTTP, null dispatch clocks, terminal guard, unchanged evidence. | TESTED_PASS; PostgreSQL reload source inspected. |
| Populated migration and repeat startup | Actual migration SQL on predecessor-shaped rows; all old fields compared; no second-run changes. Builder PG16 worker/upgrade tests inspected. | TESTED_PASS for SQL defect; auditor PG run BLOCKED by missing local environment. |
| Concurrency/ownership | Generation/locking production code unchanged; affected fixture maintenance inspected; existing recorded group. | INSPECTED; no new lock issue, no new PG-concurrency claim. |
| Control-plane freshness/format | Exact commit/trailer/diff checks, exact bundle embedding and production checkpoint validator. | Identity PASS; new artifact format TESTED_FAIL F-03. |
| Live/paid/credential boundaries | Changed source/config scope inspection; no live-provider or credential action performed. | INSPECTED, unchanged prohibition. |
| Unrelated optional route economics, phase5 models, live deployment | Excluded by frozen scope. | NOT_APPLICABLE. |

| Builder claim | Independent disposition |
|---|---|
| All five rows and all 31 conditions PASS | FALSE as a complete claim: REC-02.5, REC-03.2 and REC-03.6 fail; other clauses narrowed/confirmed above. |
| Real tested temporal/migration/report fixes | CONFIRMED code-level closure; builder PG16 commands not independently replayed here. REC-01/04/05 stay closed. |
| Sanitized failure evidence | NARROWER_THAN_CLAIMED: sibling-key exclusion works; selected short string value can be unsafe. |
| 911 tests passing | Builder-reported result, not contradicted by auditor's distinct six failing contract probes. Auditor independently ran 660 offline tests, all pass. |
| Worker concurrency 15/15 | Narrative conflates combined group: source/handoff distinguish 8 phase4 +7 concurrency =15. HARDENING_BACKLOG wording, not a block. |
| Handoff ready for audit/protocol compliant | Identity is auditable, but unchanged checkpoint validator rejects the new artifact. F-03. |
| Only necessary fake-route fixture maintenance | CONFIRMED: completing fake swapInfo fields and changing current replay evidence output path preserve scenario intent; prior evidence unchanged. |
| No future phase/self-approval/live activity | CONFIRMED by scoped diff/state inspection. |

## Completed Phase Failure Root-Cause Review

1. **Was the frozen gate unclear?** For F-02 and F-03, no: supplied429 code, sanitized values and existing checkpoint validators were explicit. F-01's malformed-input class was clear, but the architect's exact pre-build examples did not enumerate Python's isdigit/int mismatch or conversion-size guard. Architect process responsibility: an acceptance table needs runnable negative examples for parser failure paths, not only named categories. Do not claim the initial matrix was implementation-proof.
2. **Was a clear requirement implemented incorrectly?** Yes. The HTTP429 early return omits a stated field when supplied. A length check was substituted for sanitization. A newly generated checkpoint skipped an existing mechanical gate. The builder's self-audit treated nearby tests as complete clause proof. That supports a coverage/process diagnosis, not an unsupported claim about a particular model's general ability or intent.
3. **Did this audit introduce a new requirement?** No. The route cases test the already-required malformed-field non-success behavior; the error cases directly test numbered conditions2/6; the handoff gate predates this recovery. No deeper route attestation, fee normalization, new sample count, live provider validation or Phase5 behavior was promoted into a MUST. Optional formatting/count issues are not blockers.
4. **Why did tests miss it?** Amount fixtures bypassed int() failure;429 fixture omitted errorCode;secret fixture put unsafe content outside selected fields; the artifact validator was not asserted after generation. Before any approved resumption, these failures must exist as executable regression cases. Six auditor-owned correct-behavior tests already demonstrate the submitted failures; builder integration must cover terminal persistence/replay and both probe kinds, not just helper outputs.

No automatic next repair is authorized by this review. The orchestrator has completed the audit and review, not left an unperformed review on Claude. The precise remaining decision is whether the human authorizes one bounded follow-up for F-01/F-02/F-03, with all other rows locked closed. Until then there is no code work for Claude to execute and no Phase5 authorization.

## Inert correction contract for a future explicitly authorized recovery

This section is a fully consolidated proposal, NOT an ACTIVE instruction and NOT permission to code now.

Order if authorized:

1. Add failing real-adapter worker regressions for F-01/F-02 and artifact return-value tests for F-03. Preserve pre-fix failing output. Do not change closed-row expected results.
2. Make nested raw-amount validation reject conversion failures without escaping; verify no-fill terminal outcome and no provider recall on repeated processing.
3. Separate safe error-evidence extraction from status classification; preserve safe supplied429 code and reject unsafe selected values. Preserve controlled scheduler evidence and all established timing/ownership guards.
4. Run focused existing observation/provider/concurrency/migration/report/isolation groups and the full prior-phase suite; inspect every test-to-clause mapping. No new schema, provider or score changes are indicated by these failures.
5. Generate NEW checkpoint/bundle paths, validate their exact final bytes using existing production validators, then update handoff/state/decision log under a new authorized instruction ID. Do not rewrite this failed evidence or the earlier recovery artifacts.
6. Stop for independent audit. Do not self-approve Phase4 or Phase5.

Required commands remain `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`, `uv run alembic heads`, `uv run argus fixtures validate-real-chain`, plus the added targeted tests and explicit checkpoint/bundle validator assertions. Report environmental inability honestly; never enter/request credentials or fabricate execution evidence. A future ACTIVE instruction must pin the then-current branch HEAD and give the new immutable evidence paths/ID before any builder run.

## Environmental limitations and audit-of-audit

Unchanged deferred checks: LIVE_HELIUS_RPC_VALIDATION, LIVE_HELIUS_WSS_VALIDATION, PG17_COMPOSE_VALIDATION, BQ_PUBLIC_DATASET_ACCESS. Their earlier owners/closure procedures and live-readiness gates remain authoritative. PG17 still requires the real postgres:17 Compose run (`make bootstrap && make up` or approved equivalent), migration/regression evidence, and updated build-state/decision record on an authorized host. Live provider/access checks require the previously authorized environment and authentic saved evidence; this recovery authorizes no credential entry, new provider use or paid upgrade. Mock HTTP is not live-provider validation. No unavailable environment excuses the concrete code/control failures above.

Auditor-local PostgreSQL execution was unavailable because required local credentials were absent. This is recorded separately from product defects and does not reopen closed rows. The future independently executable DB verification is the existing focused migration/provider/report/observation/concurrency suite on an already authorized host, with no request to disclose credentials. No live-readiness approval is possible until prior environmental gates close.

Audit-of-audit completed: all31 numbered conditions accounted for; PASS scope and environment distinguished; every material claim confirmed, narrowed or rejected; complete known malformed-amount/error-evidence sibling paths searched; all blocking findings consolidated; existing threshold/phase/provenance requirements preserved; no unapproved implementation edit; next phase blocked. Final publication must refetch HEAD and abort if it differs from the audited target, then make exactly one instruction-only commit whose direct parent is this target. Verify resulting parent, changed-path set and exact instruction bytes after publication.

STOP. No implementation is authorized by this document.
