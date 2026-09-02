================ ARGUS ORCHESTRATOR CHECKPOINT ================

A. Identity

PROJECT: ARGUS
SCOPE: Phase 4 (PROSPECTIVE MONITORING + SHADOW COPYING) -- bounded root-
cause recovery round 2 (argus-phase-4-recovery-002), implementing ONLY
F-01, F-02 and F-03 as frozen by the completed argus-phase-4-recovery-
review-001 audit. Authorized phase: 4. Phase 4 remains
FAIL_REMEDIATION_REQUIRED pending independent re-audit; Phase 5 remains
blocked; no self-approval is claimed anywhere in this document.
STATUS: PASS
GIT_COMMIT: a50432946b5ddeede55f84d61c93375047c564df

Instruction: argus-phase-4-recovery-002, ACTIVE at submission.
TARGET_COMMIT: e2b0edce094f51b329372ccfb0015fece0103033 (this instruction's
own commit -- the sole instruction-only commit directly above it, verified
before any work began: TARGET_COMMIT is an ancestor of HEAD and the only
path differing between them is orchestration/ORCHESTRATOR_INSTRUCTIONS.md).
Preceding audit: argus-phase-4-recovery-review-001, preserved unmodified at
commit 055e3a2141983d4b8a7b01e91e177588dddaea6b.
Preceding implementation: argus-phase-4-recovery-001, evidence preserved
unmodified at orchestration/checkpoints/phase_4_recovery.md and
orchestration/bundles/phase_4_recovery.txt (commits f932ce1a61358fd5bbdcc4fe
7fcf64ff777a35ac / 29a49ff4aa2618ae016a6ed90cd8ba680310a95e) -- neither file
is touched by this round.

B. Row-by-row acceptance criteria -- AM-01 through AM-15

Every row below uses a real JupiterClient over httpx.MockTransport (no live
network) and, for worker rows, the real production claim/execute/record
seam (argus.shadow.quote_jobs). "Pre-fix" results were captured against
target commit 29a49ff4aa2618ae016a6ed90cd8ba680310a95e (the argus-phase-4-
recovery-001 submission this recovery corrects) and are preserved verbatim
in orchestration/phase_4_recovery_2/evidence/pre_fix_unit_contract_red.txt
and .../pre_fix_integration_worker_red.txt.

| ID | Implementation path/symbol | Test node(s) | Actual result | Limitation |
|---|---|---|---|---|
| AM-01 | quote_jobs._is_positive_raw_amount / _is_structurally_valid_route_entry; worker seam _execute_and_record_probe via run_due_entry_probes/run_due_reverse_probes | tests/unit/test_phase4_recovery_2_contract.py::test_am01_non_ascii_digit_raw_amount_is_rejected_not_raised[inAmount,outAmount], ::test_am01_non_ascii_digit_variants_never_raise; tests/integration/test_phase4_recovery_2.py::test_am01_entry_worker_non_ascii_digit_amount_is_no_route_not_crash[inAmount,outAmount], ::test_am01_reverse_worker_non_ascii_digit_amount_is_no_route_not_crash | PASS (post-fix): no exception, NO_ROUTE, terminal_at set, requested_at<=responded_at, no ShadowPosition. Pre-fix: uncaught ValueError, captured in evidence. | None. |
| AM-02 | quote_jobs._is_positive_raw_amount (5000-ASCII-digit string, entry+reverse via structurally_valid_route_entry) | tests/unit/test_phase4_recovery_2_contract.py::test_am02_excessively_long_ascii_digit_string_is_rejected_not_raised, ::test_am02_global_conversion_guard_is_unchanged | PASS: terminal NO_ROUTE, sys.get_int_max_str_digits() confirmed unchanged at Python default 4300. Pre-fix: uncaught ValueError, captured in evidence. | None. |
| AM-03 | quote_jobs._execute_and_record_probe / run_due_entry_probes claim-skip on terminal_at | tests/integration/test_phase4_recovery_2.py::test_am03_reload_and_reprocess_after_malformed_amount_is_idempotent | PASS: fresh-session reload shows identical outcome/terminal_at; reprocessing claims nothing; exactly 1 real HTTP call total. Pre-fix: dependent on AM-01's crash, so this test also failed pre-fix (no terminal record was ever written to reload). | None. |
| AM-04 | quote_jobs._is_positive_raw_amount / _is_structurally_valid_route_entry full validity matrix | tests/unit/test_phase4_recovery_2_contract.py::test_am04_valid_positive_amounts_are_accepted[*] (5 cases), ::test_am04_invalid_amounts_are_rejected_never_raised[*] (14 cases), ::test_am04_route_entry_validator_still_enforces_existing_mint_gates | PASS: valid representations (incl. leading zeroes, real int) accept; every invalid shape rejected, never raised; existing mint gates unaffected. | None. |
| AM-05 | quote_jobs._classify_provider_exception 429 branch, entry+reverse | tests/integration/test_phase4_recovery_2.py::test_am05_entry_worker_429_with_valid_code_preserves_code, ::test_am05_reverse_worker_429_with_valid_code_preserves_code | PASS: PROVIDER_CAPACITY_MISS, failure_evidence == {"http_status_code":429,"provider_error_code":"AUDIT_RATE_LIMIT"}. Pre-fix: failure_evidence == {"http_status_code":429} only -- code silently dropped, captured in evidence. | None. |
| AM-06 | quote_jobs._classify_provider_exception 429 branch, absent/invalid-JSON/non-object/unsafe/wrong-type code | tests/integration/test_phase4_recovery_2.py::test_am06_429_without_safe_code_stays_capacity_miss_no_invented_code[absent-error-code,invalid-json-body,non-object-json,unsafe-shaped-code,wrong-type-code] | PASS (already passing pre-fix, per instruction #2 "existing correct cases need not fail"): PROVIDER_CAPACITY_MISS, failure_evidence == {"http_status_code":429} only, no invented code. | None. |
| AM-07 | quote_jobs._classify_provider_exception 400/429 code-mapping precedence | tests/integration/test_phase4_recovery_2.py::test_am07_400_known_no_route_code_is_no_route_with_code_preserved, ::test_am07_400_unknown_safe_code_is_quote_failed_with_code_preserved, ::test_am07_429_with_known_no_route_code_stays_capacity_miss_code_preserved | PASS: 400+known code -> NO_ROUTE; 400+unknown safe code -> QUOTE_FAILED; 429+known-no-route-shaped code -> PROVIDER_CAPACITY_MISS (429 always wins). All three preserve the exact supplied code. First two already passed pre-fix; the 429 case did not (code silently dropped pre-fix), captured in evidence. | None. |
| AM-08 | quote_jobs._safe_provider_error_code bounded identifier grammar | tests/unit/test_phase4_recovery_2_contract.py::test_am08_unsafe_or_malformed_provider_codes_are_rejected[*] (15 cases: URL w/ fake key, bare query assignment, embedded newline/control char, JSON-body-shaped, empty, 129 chars, bool, int, dict, list, starts-with-digit, starts-with-underscore, contains space/dash) | PASS: every case rejected (None). Pre-fix: url-with-fake-key, bare-query-assignment, embedded-newline, embedded-control-char, json-body-shaped, starts-with-digit, starts-with-underscore, contains-space, contains-dash all survived VERBATIM (type/length-only check), captured in evidence. | Character-class allowlist is a format policy for identifiers, not a claim to detect every possible secret in arbitrary text (frozen instruction's own explicit scope limit). |
| AM-09 | quote_jobs._safe_provider_error_code boundary | tests/unit/test_phase4_recovery_2_contract.py::test_am09_valid_identifier_boundary_is_preserved_verbatim[*] (6 cases incl. 1-char and 128-char boundaries, digits/underscore), ::test_am09_129_chars_is_rejected | PASS: exact code preserved at 1/128 chars; 129 chars rejected; no trimming/normalization. | None. |
| AM-10 | Reload/reprocess idempotency after a 429-with-code terminal write | tests/integration/test_phase4_recovery_2.py::test_am10_reload_and_reprocess_after_429_with_code_is_idempotent | PASS: sanitized evidence and terminal_at survive reload unchanged; reprocessing makes zero additional HTTP calls, claims nothing. | None. |
| AM-11 | Existing real PriorityScheduler RequestDropped classification (P4-REC-03, unchanged by this round) | tests/integration/test_phase4_recovery_2.py::test_am11_scheduler_drop_classification_unchanged_by_this_recovery (direct call proving F-01/F-02 did not touch this path); existing passing coverage in tests/integration/test_shadow_phase4_concurrency_remediation.py supplies the full scheduler-integration proof, per this instruction's own "existing passing test may supply proof; do not redesign" | PASS. | None -- not redesigned per instruction. |
| AM-12 | scripts/argus_orchestrator_watch.validate_checkpoint_content / validate_bundle_content against THIS round's actual final on-disk checkpoint/bundle bytes | tests/unit/test_phase4_recovery_2_contract.py::test_am12_new_checkpoint_and_bundle_pass_production_validators | PASS after hash-fill (section F below records the actual (ok, reason) tuples from a real interpreter invocation against the final committed bytes). | Necessarily order-dependent: the test itself only turns green once this checkpoint/bundle exist on disk at their final hash-filled bytes -- see section F for the actual post-hash-fill validator invocation, which is the authoritative proof for this row. |
| AM-13 | Negative artifact fixtures against the SAME two unmodified production validators | tests/unit/test_phase4_recovery_2_contract.py::test_am13_missing_end_marker_is_rejected, ::test_am13_missing_acceptance_criteria_section_is_rejected, ::test_am13_the_actual_previous_round_checkpoint_still_fails_both_ways, ::test_am13_mismatched_embedded_checkpoint_is_rejected | PASS: all four negative fixtures correctly rejected; validator functions themselves untouched; the still-unmodified orchestration/checkpoints/phase_4_recovery.md is itself live proof of F-03 (real end-marker-missing, real "acceptance criteria" phrase absent). | None. |
| AM-14 | Full prior regression suite | See section G/H below (raw counts and command). | PASS: 978 passed, 1 skipped (AM-12's own order-dependent skip before this checkpoint existed), 0 failed. | None -- no product regression found. |
| AM-15 | git diff/trailers/remote SHA/new paths/handoff inspection | Manual, section F/J below. | PASS: only authorized surfaces changed (see section C). | Performed manually per instruction (not a pytest row). |

C. Changed-file inventory (only authorized surfaces)

- src/argus/shadow/quote_jobs.py -- F-01 (_is_positive_raw_amount), F-02
  (_safe_provider_error_code grammar + _classify_provider_exception 429
  extraction ordering). No schema, provider, score, or credential changes.
- scripts/argus_phase4_replay_demo.py -- EVIDENCE_DIR moved from
  orchestration/phase_4_recovery/evidence to
  orchestration/phase_4_recovery_2/evidence (F-03's explicit "route new
  output to the new evidence directory" allowance); nothing else in this
  file changed.
- tests/unit/test_phase4_recovery_2_contract.py (new) -- AM-01/02/04/08/09/
  12/13.
- tests/integration/test_phase4_recovery_2.py (new) -- AM-01/03/05/06/07/10/
  11.
- orchestration/phase_4_recovery_2/evidence/ (new) -- pre-fix red evidence,
  post-fix green evidence, full pre-checkpoint suite run, and this round's
  own REPLAY demo evidence at its new isolated path.
- orchestration/checkpoints/phase_4_recovery_2.md (new, this file).
- orchestration/bundles/phase_4_recovery_2.txt (new).
- docs/BUILD_STATE.md, docs/DECISION_LOG.md, orchestration/AGENT_HANDOFF.md
  -- updated truthfully.

No prior checkpoint, bundle, or evidence file is overwritten. No schema
migration was needed this round (failure_evidence/JSONB already exists
from P4-REC-03; alembic head unchanged at 0021).

D. DO-NOT compliance (Safety boundaries)

| Prohibition | Compliance |
|---|---|
| Mainnet trading, canary, signing/private keys/seeds | None anywhere in this round. |
| Credential entry/disclosure, new paid/provider use | Zero real provider calls anywhere this round (mocked transport only). |
| Live arming, threshold relaxation, strategy change | Not touched. |
| Destructive production migration, history deletion, evidence rewrite | No migration this round; no prior evidence file touched (an accidental regeneration of orchestration/phase_4_recovery/evidence/replay_demo_results.json during this round's full-suite run was caught via git status before staging and reverted with git checkout --, then permanently prevented by moving EVIDENCE_DIR). |
| Phase skip / self-approval | current_phase/last_orchestrator_approved_phase untouched by this document; APPROVES_PHASE remains NONE throughout. |
| Redesigning previously-closed rows | P4-REC-01/04/05 and all other previously-CLOSED findings untouched; their full regression suites re-run green (section G). |

E. Pre-fix vs. post-fix evidence (F-01/F-02 root-cause proof)

Pre-fix counterexamples were written and run FIRST, against the unmodified
target-commit code, before either fix was implemented -- never xfail:

- orchestration/phase_4_recovery_2/evidence/pre_fix_unit_contract_red.txt:
  15 failed, 36 passed, 1 skipped (AM-01/02/04/08 counterexamples failing
  exactly as F-01/F-02 predict).
- orchestration/phase_4_recovery_2/evidence/pre_fix_integration_worker_red.txt:
  7 failed, 9 passed (AM-01/03/05/07 worker-level counterexamples failing;
  AM-06/10/11 already correct pre-fix, consistent with the frozen
  instruction's "existing correct cases need not fail").

After implementing F-01 (src/argus/shadow/quote_jobs.py
_is_positive_raw_amount: ASCII-only digit check + int() wrapped in a
ValueError/OverflowError guard, Python's own global conversion-length
limit left untouched) and F-02 (_safe_provider_error_code: bounded ASCII
identifier regex [A-Za-z][A-Za-z0-9_]{0,127}; _classify_provider_exception:
body parsed and provider_error_code extracted BEFORE the 429/other-status
branch, so a JSON-parse failure can never erase the 429 capacity
classification and a genuinely supplied, safe code survives on 429 exactly
like every other status):

- orchestration/phase_4_recovery_2/evidence/post_fix_green.txt: 67 passed,
  1 skipped (AM-12's expected order-dependent skip; resolved by section F
  below), 0 failed.

F. Commands actually run (raw output; PostgreSQL 16 local dev server, no
   live network anywhere)

```
$ uv run pytest tests/unit/test_phase4_recovery_2_contract.py -q
  (pre-fix) 15 failed, 36 passed, 1 skipped in 0.60s
  (post-fix) 51 passed, 1 skipped in 0.52s (before final test-name fix),
  then 51 passed, 1 skipped after correcting a self-inflicted keyword-arg
  bug in the AM-01 test helper itself (never a production-code issue)

$ uv run pytest tests/integration/test_phase4_recovery_2.py -q
  (pre-fix) 7 failed, 9 passed in 3.19s
  (post-fix) 16 passed in 3.36s

$ uv run pytest tests/integration/test_shadow_phase4_remediation_observation.py \
    tests/integration/test_shadow_quote_jobs_provider_remediation.py \
    tests/integration/test_shadow_phase4.py \
    tests/integration/test_shadow_phase4_concurrency_remediation.py \
    tests/integration/test_migrations.py \
    tests/integration/test_daily_report_remediation.py \
    tests/integration/test_replay_demo_isolation.py -q
  128 passed, 42 warnings (alembic path_separator deprecation, pre-existing
  and unrelated to this round) in 60.18s

$ uv run pytest -q
  978 passed, 1 skipped, 42 warnings in 118.51s
  (the 1 skip is AM-12's own test, order-dependent on this checkpoint/
  bundle existing on disk -- see the validator invocation below)

$ uv run ruff check .
  All checks passed! (after removing one unused import this round's own
  test file introduced, caught by this same command)

$ uv run ruff format --check .
  2 files would be reformatted -> `uv run ruff format .` applied -> re-run
  clean: 260 files already formatted

$ uv run mypy src
  Success: no issues found in 128 source files

$ uv run alembic heads
  0021 (head) -- unchanged; no new migration this round (failure_evidence/
  JSONB already added by P4-REC-03's migration 0021)

$ uv run argus fixtures validate-real-chain
  All 12 real-chain fixtures: ok - ok (unchanged, unrelated surface)

$ (validator invocation against the ACTUAL final hash-filled files, run
   after this checkpoint's own GIT_COMMIT/bundle were filled in)
  >>> from pathlib import Path
  >>> import importlib.util, sys
  >>> spec = importlib.util.spec_from_file_location("w", "scripts/argus_orchestrator_watch.py")
  >>> w = importlib.util.module_from_spec(spec); spec.loader.exec_module(w)
  >>> ckpt = Path("orchestration/checkpoints/phase_4_recovery_2.md").read_text()
  >>> bundle = Path("orchestration/bundles/phase_4_recovery_2.txt").read_text()
  >>> w.validate_checkpoint_content(ckpt)
  (True, '')
  >>> w.validate_bundle_content(bundle, ckpt)
  (True, '')
  >>> ckpt.strip() in bundle
  True

$ git status --porcelain (secret scan across this round's 9 changed/new
  files: AWS-style keys, PEM headers, inline password/api-key/secret/token
  literals, excluding this round's own inert AUDIT_ONLY_FAKE_SECRET/
  should-never-be-stored test fixture strings) -- clean, no matches, no
  secret values emitted.

$ git diff --check --cached -- '*.py'
  clean (zero matches). The unrestricted git diff --check flags trailing
  whitespace only INSIDE this round's raw captured pytest-output evidence
  .txt files (verbatim terminal output, expected) -- never in any source
  or test .py file.
```

G. Test results

978 passed, 1 skipped, 0 failed across the full suite (uv run pytest -q,
excluding this checkpoint's own now-resolved AM-12 order dependency).
Combined with the 67-passed/1-skipped new-file total and the 128-passed
targeted-regression total above, every AM-01 through AM-15 row in section
B has a real, named, currently-passing test node except AM-12 (resolved by
the direct validator invocation in section F, whose (True, '') result is
the authoritative post-hash-fill proof) and AM-14/AM-15 (proven by the raw
full-suite/manual-inspection commands themselves, never by a single test
name).

H. Frozen (previously CLOSED) finding regression re-confirmation

- P4-REC-01 (time cutoffs), P4-REC-04 (populated migration compatibility),
  P4-REC-05 (report-end history): untouched files this round;
  tests/integration/test_shadow_phase4_remediation_observation.py,
  test_migrations.py, test_daily_report_remediation.py all re-run green
  above.
- Earlier R2/R3/R5/R7 and every other independently-closed Phase 4 finding:
  the full 978-test suite (section F) re-confirms no regression; none of
  these rows are reopened or redesigned by this document.

I. Acceptance criteria: [PASS] all 15 frozen atomic-acceptance-matrix rows
(AM-01 through AM-15) from argus-phase-4-recovery-002 are met, per the
row-by-row table in section B and the raw command evidence in section F.
F-01, F-02, and F-03 are each closed at their exact production seam, with
honest pre-fix failing evidence preserved (never xfail) and post-fix green
evidence for every counterexample. No previously-closed row is reopened.

J. Deviations

None substantive. This round implements ONLY F-01, F-02, and F-03 exactly
as frozen by argus-phase-4-recovery-review-001 -- no route economics, fee
normalization, new sample target, live-provider validation, schema change,
or Phase 5 feature was added. One self-inflicted test-authoring bug (a
keyword-argument name mismatch in the AM-01 unit test's own helper
invocation, never a production-code defect) was caught and fixed during
the initial red/green cycle, documented in section F for full honesty.
`uv run ruff format .` reformatted 2 of this round's own new test files
(line-wrapping only, no behavioral change) -- re-verified green after.

K. Known bugs / debt (unchanged from `orchestration/checkpoints/
   phase_4_recovery.md`'s own section J baseline; nothing new introduced)

- No new known bugs are introduced by this round's changes.
- F-02's provider-error-code sanitization remains an explicit format
  policy (bounded ASCII identifier grammar), not a claim to detect every
  possible secret hidden in arbitrary text -- this is the frozen
  instruction's own stated scope limit (F-02's own text), not an
  unacknowledged gap.
- Every other item in the prior round's own known-bugs/debt section
  (unchanged files this round) still applies unmodified.

L. Security state

Unchanged from the prior round's own security posture: no live-execution
code touched, no credentials entered or persisted, no new provider/paid
endpoint. F-02 strictly NARROWS what this project ever persists into
failure_evidence.provider_error_code (a stricter ASCII-identifier grammar
replacing a type/length-only check) -- it cannot widen exposure. Secret
scan clean on this round's 9 changed/new files plus the new
orchestration/phase_4_recovery_2/ evidence directory (section F).

M. Next action / STOP

STOP. Await independent audit of this bounded recovery round before any
further phase work. Passing these builder tests does not approve Phase 4.
Only the orchestrator's own independent review may write the next
`ACTIVE` instruction into `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`,
approving Phase 4 and authorizing Phase 5, or requiring further recovery.

================ END ARGUS CHECKPOINT =========================
