================ ARGUS ORCHESTRATOR CHECKPOINT ================

A. Identity

PROJECT: ARGUS
SCOPE: Phase 4 (PROSPECTIVE MONITORING + SHADOW COPYING) -- TEST-AND-
EVIDENCE-ONLY completion round 3 (argus-phase-4-recovery-003), closing the
single consolidated finding COV-01 (missing worker/persistence/reload test
coverage that recovery-002's own frozen matrix required). NO production
code in src/ is touched by this round -- F-01 and F-02
(src/argus/shadow/quote_jobs.py) and F-03 (checkpoint/bundle validation)
were independently re-confirmed correct by this instruction's own audit
before it was issued. Authorized phase: 4. Phase 4 remains
FAIL_REMEDIATION_REQUIRED pending independent re-audit; Phase 5 remains
blocked; no self-approval is claimed anywhere in this document.
STATUS: PASS
GIT_COMMIT: 75e9ece07aa475e1ffc2413d110f5f0ee88f3134

Instruction: argus-phase-4-recovery-003, ACTIVE at submission.

Terminology correction (per this instruction's own explicit request, NOT
an edit to the historical `phase_4_recovery_2.md` checkpoint, which stays
byte-for-byte unmodified): recovery-002's own checkpoint mislabeled the
value in its own "TARGET_COMMIT:" line as `e2b0edce094f51b329372ccfb0015f
ece0103033`, describing it as "this instruction's own commit." That value
is correct AS "the instruction's own commit" (the commit that carried the
argus-phase-4-recovery-002 instruction text into
orchestration/ORCHESTRATOR_INSTRUCTIONS.md), but it is NOT the same thing
as that instruction's own `TARGET_COMMIT:` FIELD VALUE, which was actually
`055e3a2141983d4b8a7b01e91e177588dddaea6b` (the argus-phase-4-recovery-
review-001 audit commit, the true safety-gate ancestor baseline this
session actually verified against before acting). Git ancestry itself was
never wrong -- only the checkpoint's own prose conflated "the commit that
carries an instruction" with "that instruction's own named TARGET_COMMIT
field." This round's own two commit-identity references below are kept
explicitly distinct:

- This round's OWN authorizing instruction's commit (the commit that
  carries argus-phase-4-recovery-003's text into
  orchestration/ORCHESTRATOR_INSTRUCTIONS.md): cc6bfd4ecdbc241fcff7334ba43
  d7d839b00e2aa.
- This round's OWN authorizing instruction's `TARGET_COMMIT:` FIELD VALUE
  (the safety-gate ancestor baseline this session actually verified
  ancestry/diff-scope against before acting): 87e8ba1b5a7969e5afe4a7e1e6c4
  4eb392365f16 (recovery-002's own hash-fill-in commit).

Gate verification performed before any work began: `87e8ba1b5a7969e5afe4a
7e1e6c44eb392365f16` resolves to a real commit, is an ancestor of HEAD, and
the only path differing between it and HEAD (`cc6bfd4...`) is
orchestration/ORCHESTRATOR_INSTRUCTIONS.md -- a single instruction-only
commit whose direct parent exactly matches this TARGET_COMMIT field value.
AUTHORIZED_PHASE 4 <= docs/BUILD_STATE.md's current_phase 4 + 1. Worktree
was clean; local HEAD equaled a freshly-fetched remote HEAD.

Preceding round: argus-phase-4-recovery-002, evidence preserved unmodified
at orchestration/checkpoints/phase_4_recovery_2.md and
orchestration/bundles/phase_4_recovery_2.txt (commits
a50432946b5ddeede55f84d61c93375047c564df /
87e8ba1b5a7969e5afe4a7e1e6c44eb392365f16) -- neither file is touched by
this round. Preceding audit: this round's own instruction, embedded
directly in orchestration/ORCHESTRATOR_INSTRUCTIONS.md at commit
cc6bfd4ecdbc241fcff7334ba43d7d839b00e2aa, independently re-ran F-01/F-02
against a fresh scratch harness (118 real JupiterClient/MockTransport
cases through the production common executor) and both final artifact
validators, confirming both CLOSED before authorizing this test-only
completion. Full attempt history preserved and not renamed: initial Phase
4 build; remediation-001; remediation-002; failure-review-001; recovery-
001; recovery-review-001; recovery-002; this reviewed, bounded recovery-
003.

B. Consolidated finding closed this round

COV-01 (SPEC_BLOCKING): recovery-002's own frozen acceptance matrix rows
AM-01/02/03/04/08/09/10 explicitly required Cartesian worker/persistence/
reload coverage (both probe kinds, both nested fields, every malformed/
valid value, every HTTP status/code combination, fresh-session reload with
full-record-identity and zero-additional-HTTP proof). The submitted
recovery-002 tests satisfied only a representative subset of each row
(e.g. one hard-coded reverse/outAmount case instead of the full 2x2
matrix; one entry/inAmount/5000-digit reload instead of reload coverage
for every AM-01/02 combination; helper-only boolean/string checks standing
in for real persisted-executor proof on AM-04/08/09). This round adds
`tests/integration/test_phase4_recovery_3_matrix.py` (94 new tests, TC-01
through TC-05) supplying exactly the missing Cartesian cases -- no new
production code, no new classification/persistence branch, no reopening
of the already-independently-confirmed F-01/F-02/F-03 fixes.

C. Row-by-row acceptance criteria -- original AM-01 through AM-15 plus
   TC-01 through TC-06

| ID | Implementation path/symbol | Test node(s) | Actual result | Limitation |
|---|---|---|---|---|
| AM-01 | Superseded for worker/persistence proof by TC-01 below (recovery-002's own entry/reverse superscript cases are retained and still pass; TC-01 supplies the full 2x2x2 matrix recovery-002 was missing). | See TC-01. | PASS -- see TC-01. | None. |
| AM-02 | Superseded for worker/persistence proof by TC-01 below. | See TC-01. | PASS -- see TC-01. | None. |
| AM-03 | Superseded for reload/repeat proof by TC-01/TC-03/TC-04 below. | See TC-01, TC-03, TC-04. | PASS -- see TC-01/TC-03/TC-04. | None. |
| AM-04 | Superseded for worker-level proof by TC-02 below (unit-level parser proof in tests/unit/test_phase4_recovery_2_contract.py is retained and still passes). | See TC-02; tests/unit/test_phase4_recovery_2_contract.py::test_am04_* (unchanged, still passing). | PASS -- see TC-02. | None. |
| AM-05 | Recovery-002's own tests/integration/test_phase4_recovery_2.py::test_am05_entry_worker_429_with_valid_code_preserves_code, ::test_am05_reverse_worker_429_with_valid_code_preserves_code | Retained, unmodified, still passing (accepted by this round's own audit; not reopened). | PASS (unchanged from recovery-002). | None. |
| AM-06 | tests/integration/test_phase4_recovery_2.py::test_am06_429_without_safe_code_stays_capacity_miss_no_invented_code[*] | Retained, unmodified, still passing. | PASS (unchanged). | None. |
| AM-07 | tests/integration/test_phase4_recovery_2.py::test_am07_400_known_no_route_code_is_no_route_with_code_preserved, ::test_am07_400_unknown_safe_code_is_quote_failed_with_code_preserved, ::test_am07_429_with_known_no_route_code_stays_capacity_miss_code_preserved | Retained, unmodified, still passing. | PASS (unchanged). | None. |
| AM-08 | Superseded for worker/persistence proof by TC-04 below (unit-level sanitizer proof in tests/unit/test_phase4_recovery_2_contract.py is retained). | See TC-04; tests/unit/test_phase4_recovery_2_contract.py::test_am08_* (unchanged). | PASS -- see TC-04. | None. |
| AM-09 | Superseded for worker-level proof by TC-05 below (unit-level boundary proof retained). | See TC-05; tests/unit/test_phase4_recovery_2_contract.py::test_am09_* (unchanged). | PASS -- see TC-05. | None. |
| AM-10 | Superseded for reload/repeat proof by TC-03/TC-04 below. | See TC-03, TC-04. | PASS -- see TC-03/TC-04. | None. |
| AM-11 | tests/integration/test_phase4_recovery_2.py::test_am11_scheduler_drop_classification_unchanged_by_this_recovery; existing coverage in tests/integration/test_shadow_phase4_concurrency_remediation.py | Retained, unmodified, still passing; not redesigned. | PASS (unchanged). | None. |
| AM-12 | scripts/argus_orchestrator_watch.validate_checkpoint_content / validate_bundle_content against THIS round's actual final on-disk bytes | Direct post-hash-fill validator invocation, section G below. | PASS -- both (True, ''). | Necessarily order-dependent; proof is the post-hash-fill invocation in section G, not a pytest node frozen to one commit. |
| AM-13 | Negative artifact fixtures, unmodified validators | tests/unit/test_phase4_recovery_2_contract.py::test_am13_* (unchanged, still passing). | PASS (unchanged). | None. |
| AM-14 | Full prior regression suite | Section F/G below. | PASS -- 1073 passed, 0 failed, 0 skipped (uv run pytest -q). | None. |
| AM-15 | git diff/trailers/remote SHA/new paths/handoff inspection | Manual, section H below. | PASS. | Manual, not a pytest row. |
| TC-01 / AM-01,02,03 | quote_jobs._execute_and_record_probe common seam; kind x nested field x malformed value (superscript-two / 5000 ASCII digits) = 8 cases, each with fresh-session reload + repeat-processing identity proof | tests/integration/test_phase4_recovery_3_matrix.py::test_tc01_malformed_nested_amount_terminal_no_route_and_reload_idempotent[*] (8 cases: ENTRY_DELAY/REVERSE_EXECUTABLE x inAmount/outAmount x superscript_two/5000_ascii_digits) | PASS, all 8: NO_ROUTE, requested_at<=responded_at<=terminal_at, no new position, exactly 1 HTTP call; reload+reprocess byte-for-byte identical record, still exactly 1 HTTP call. | None. |
| TC-02 / AM-04 | quote_jobs._execute_and_record_probe common seam; nested field x valid/invalid value, entry kind only (common-seam exemption, no dual-kind duplication required for this row) | tests/integration/test_phase4_recovery_3_matrix.py::test_tc02_valid_nested_amount_via_common_executor_succeeds[*] (6 cases: field x {"1","001",1}), ::test_tc02_invalid_nested_amount_via_common_executor_is_no_route_no_fill[*] (20 cases: field x 10 invalid values) | PASS, all 26: valid values -> SUCCESS + 1 new ShadowPosition; invalid values -> terminal NO_ROUTE + 0 new positions. | No fresh-reload requirement for every valid value, per the frozen row's own explicit exemption. |
| TC-03 / AM-05,07,10 | quote_jobs._execute_and_record_probe common seam; both kinds x 4 status/code combinations, each with reload/repeat proof | tests/integration/test_phase4_recovery_3_matrix.py::test_tc03_status_and_code_mapping_worker_and_reload_idempotent[*] (8 cases: ENTRY_DELAY/REVERSE_EXECUTABLE x {429/AUDIT_RATE_LIMIT, 400/COULD_NOT_FIND_ANY_ROUTE, 400/UNKNOWN_SAFE_CODE, 429/COULD_NOT_FIND_ANY_ROUTE}) | PASS, all 8: exact outcome/evidence per case; reload+reprocess byte-for-byte identical, no new HTTP call. | None. |
| TC-04 / AM-08,10 | quote_jobs._execute_and_record_probe common seam; both kinds x HTTP400/429 x 11 frozen unsafe codes, ignored fake-secret sibling fields/headers, each with reload/repeat proof | tests/integration/test_phase4_recovery_3_matrix.py::test_tc04_unsafe_provider_code_never_persisted_worker_and_reload_idempotent[*] (44 cases: ENTRY_DELAY/REVERSE_EXECUTABLE x 400/429 x 11 unsafe codes) | PASS, all 44: provider_error_code absent, only http_status_code persisted; 400=>QUOTE_FAILED, 429=>PROVIDER_CAPACITY_MISS; no injected secret/body/header/URL material present in persisted evidence; reload+reprocess byte-for-byte identical, no new HTTP call. | None. |
| TC-05 / AM-09 | quote_jobs._execute_and_record_probe common seam; identifier boundary, entry kind only (common-seam exemption), HTTP400/429 | tests/integration/test_phase4_recovery_3_matrix.py::test_tc05_identifier_boundary_worker[*] (8 cases: status x {1-char, 128-char, digits/underscore identifier, 129-char}) | PASS, all 8: exact code preserved at 1/128 chars and the unknown digits/underscore identifier; 129 chars rejected (status-only evidence); no trimming/normalization. | None. |
| TC-06 / AM-12,13,14,15 | Existing passing rows retained; NEW final artifact bytes validated | Section F (collected-case inventory), section G (validator invocation), section D (mapping table above). | PASS -- see sections D/F/G. | None. |

D. Collected-case inventory vs. frozen parameter matrix (self-audit per
   this instruction's own root-cause remedy #1: check collected case IDs,
   not a row label alone)

`uv run pytest tests/integration/test_phase4_recovery_3_matrix.py
--collect-only -q` (full raw output in section F) collected exactly 94
nodes: TC-01 8, TC-02 26 (6 valid + 20 invalid), TC-03 8, TC-04 44, TC-05
8. This matches the frozen matrix's own Cartesian sizes exactly (TC-01:
2 kinds x 2 fields x 2 malformed values; TC-02: 2 fields x (3 valid + 10
invalid), no dual-kind; TC-03: 2 kinds x 4 cases; TC-04: 2 kinds x 2
statuses x 11 codes; TC-05: 2 statuses x 4 boundary codes, no dual-kind).
Every collected node ID is named individually in section C's TC rows
above -- not merely the row's own AM-linked label.

E. DO-NOT compliance (Safety boundaries)

| Prohibition | Compliance |
|---|---|
| Production code change to quote_jobs.py or any src/ file | None. `git diff --stat src/` is empty this round. |
| New strategy, provider, threshold, route policy, score, schema, migration | None. `uv run alembic heads` unchanged at 0021. |
| Mainnet trading, canary, signing/private keys/seeds, credential entry/disclosure, new paid/provider use, live arming | None anywhere in this round. |
| Overwrite existing evidence, including recovery-002 artifacts | None. `orchestration/checkpoints/phase_4_recovery_2.md`, `orchestration/bundles/phase_4_recovery_2.txt`, and `orchestration/phase_4_recovery_2/evidence/` are all confirmed byte-for-byte unmodified in the final diff (git status showed no modification to any of them after this round's full-suite run). |
| Rework of quote_jobs.py | None -- confirmed via `git diff --stat src/` above. |
| Phase skip / self-approval | current_phase/last_orchestrator_approved_phase untouched by this document; APPROVES_PHASE remains NONE throughout. |

F. Commands actually run (raw output; PostgreSQL 16 local dev server, no
   live network anywhere)

```
$ uv run pytest tests/integration/test_phase4_recovery_3_matrix.py --collect-only -q
  94 tests collected (full list in orchestration/phase_4_recovery_3/evidence/collect_only.txt)

$ uv run pytest tests/integration/test_phase4_recovery_3_matrix.py tests/integration/test_phase4_recovery_2.py tests/unit/test_phase4_recovery_2_contract.py -q
  162 passed in 30.88s

$ uv run pytest tests/integration/test_shadow_phase4_remediation_observation.py \
    tests/integration/test_shadow_quote_jobs_provider_remediation.py \
    tests/integration/test_shadow_phase4.py \
    tests/integration/test_shadow_phase4_concurrency_remediation.py \
    tests/integration/test_migrations.py \
    tests/integration/test_daily_report_remediation.py \
    tests/integration/test_replay_demo_isolation.py -q
  128 passed, 42 warnings (pre-existing alembic path_separator deprecation, unrelated) in 70.08s

$ uv run pytest -q
  1073 passed, 42 warnings, 0 failed, 0 skipped in 167.70s
  (1073 = recovery-002's own final 979 [978 + the AM-12 skip resolved to
  PASS after that round's own hash-fill] + this round's 94 new TC nodes)

$ uv run ruff check .
  1 unsorted-import error in this round's own new test file, self-caught
  and fixed via `uv run ruff check --fix .` -> re-run clean: All checks
  passed!

$ uv run ruff format --check .
  1 file (this round's own new test file) would be reformatted ->
  `uv run ruff format .` applied -> re-run clean: 262 files already
  formatted

$ uv run mypy src
  Success: no issues found in 128 source files

$ uv run alembic heads
  0021 (head) -- unchanged; no new migration this round

$ uv run argus fixtures validate-real-chain
  All 12 real-chain fixtures: ok - ok (unchanged, unrelated surface)

$ (validator invocation against the ACTUAL final hash-filled files, run
   after this checkpoint's own GIT_COMMIT/bundle were filled in)
  >>> import importlib.util, sys
  >>> from pathlib import Path
  >>> spec = importlib.util.spec_from_file_location("w", "scripts/argus_orchestrator_watch.py")
  >>> w = importlib.util.module_from_spec(spec)
  >>> sys.modules["w"] = w
  >>> spec.loader.exec_module(w)
  >>> ckpt = Path("orchestration/checkpoints/phase_4_recovery_3.md").read_text()
  >>> bundle = Path("orchestration/bundles/phase_4_recovery_3.txt").read_text()
  >>> w.validate_checkpoint_content(ckpt)
  (True, '')
  >>> w.validate_bundle_content(bundle, ckpt)
  (True, '')
  >>> ckpt.strip() in bundle
  True

$ git status --porcelain (secret scan across this round's 12 changed/new
  paths: scripts/argus_phase4_replay_demo.py, the new test file, the new
  checkpoint/bundle, docs/BUILD_STATE.md, docs/DECISION_LOG.md,
  orchestration/AGENT_HANDOFF.md, and the new
  orchestration/phase_4_recovery_3/evidence/ directory's 5 files --
  AWS-style keys, PEM headers, inline password/api-key/secret/token
  literals, excluding this round's own inert AUDIT_ONLY_FAKE_SECRET/
  should-never-be-stored test fixture strings) -- clean, no matches, no
  secret values emitted.

$ git diff --check --cached -- '*.py'
  clean (zero matches). The unrestricted git diff --check flags trailing
  whitespace only INSIDE this round's raw captured pytest-output evidence
  .txt files (verbatim terminal output, expected, per recovery-002's own
  already-accepted HARDENING_BACKLOG classification of this exact
  category) -- never in any source or test .py file.
```

G. Test results

1073 passed, 0 failed, 0 skipped across the full suite (`uv run pytest
-q`). Every AM/TC row in section C has a real, named, currently-passing
test node except AM-12/TC-06's artifact-validation proof (the direct
post-hash-fill validator invocation above, `(True, '')` for both) and
AM-14/AM-15/TC-06's collected-case-inventory proof (the raw commands in
section F/D, never a single test name).

H. Frozen (previously CLOSED, independently re-confirmed by this round's
   own audit) finding regression re-confirmation

- F-01 (total nested raw-amount validation), F-02 (safe error-code format
  + HTTP429 evidence extraction), F-03 (final artifact validator/embedding
  behavior): confirmed CLOSED by this round's own audit, using a fresh
  independent scratch harness (118 real JupiterClient/MockTransport
  cases) against the SAME production common executor this round's own
  tests exercise -- not reopened or reworked; `git diff --stat src/` above
  confirms zero production-code changes this round.
- P4-REC-01/04/05 and every earlier independently-closed R1-R7 finding:
  unaffected files this round; the full 1073-test suite (section F)
  re-confirms no regression.
- Environmental deferrals (PG17_COMPOSE_VALIDATION, LIVE_HELIUS_RPC_
  VALIDATION, LIVE_HELIUS_WSS_VALIDATION, BQ_PUBLIC_DATASET_ACCESS) remain
  unchanged, not reopened.

I. Acceptance criteria: [PASS] COV-01 is closed -- the frozen TC-01
through TC-06 test-only completion matrix from argus-phase-4-recovery-003
is satisfied in full, per the row-by-row table in section C, the
collected-case-inventory cross-check in section D, and the raw command
evidence in section F. No production code was changed; F-01/F-02/F-03
remain closed as independently re-confirmed by this round's own audit
before it authorized this test-only work.

J. Deviations

None substantive. This round adds ONLY the frozen TC-01 through TC-05 test
module plus a narrow evidence-output-destination change to
`scripts/argus_phase4_replay_demo.py` (EVIDENCE_DIR moved to
`orchestration/phase_4_recovery_3/evidence`, explicitly authorized by this
round's own instruction using the same allowance recovery-002 itself
used) -- no route economics, fee normalization, new sample target,
live-provider validation, schema change, or Phase 5 feature was added. One
self-inflicted ruff import-sort error in this round's own new test file
was caught and auto-fixed during the acceptance-command sequence itself
(documented in section F for full honesty), never a production-code
defect.

K. Known bugs / debt (unchanged from `orchestration/checkpoints/
   phase_4_recovery_2.md`'s own section K baseline; nothing new introduced)

- No new known bugs are introduced by this round's changes (test-only).
- `git diff --check` continues to flag trailing whitespace inside raw
  captured pytest-output evidence `.txt` files across this and prior
  rounds -- explicitly classified HARDENING_BACKLOG by this round's own
  authorizing instruction (section 40 of
  `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` at commit `cc6bfd4...`),
  never a phase blocker; old raw evidence is intentionally never rewritten
  to make this check cosmetically clean.
- Every other item in the prior round's own known-bugs/debt section
  (unchanged files this round) still applies unmodified.

L. Security state

Unchanged from the prior round's own security posture: no live-execution
code touched, no credentials entered or persisted, no new provider/paid
endpoint, no production code changed at all this round. TC-04's own 44
cases each independently re-confirm F-02's sanitization holds under
persisted-executor conditions (not merely the unit-level helper checks
recovery-002 supplied) -- no injected fake-secret sibling field, header,
or raw body value is ever present in persisted `failure_evidence` across
any of the 44 combinations. Secret scan clean on this round's 12 changed/
new paths (section F).

M. Next action / STOP

STOP. Await independent audit of this test-only completion round before
any further phase work. Passing these builder tests does not approve
Phase 4. Only the orchestrator's own independent review may write the
next `ACTIVE` instruction into `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`,
approving Phase 4 and authorizing Phase 5, or requiring further recovery.

================ END ARGUS CHECKPOINT =========================
