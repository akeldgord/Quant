================ ARGUS ORCHESTRATOR CHECKPOINT ================

A. Identity

PROJECT: ARGUS
SCOPE: Phase 4 (PROSPECTIVE MONITORING + SHADOW COPYING) -- SEALED
two-assertion completion round (argus-phase-4-recovery-005), per
orchestration/AUDITOR_POLICY.md. TEST-ONLY: no production code in src/ is
touched. ASSERT-01 and ASSERT-02 are the complete sealed blocking
contract for this cycle, per that instruction's own explicit statement.
Authorized phase: 4. Phase 4 remains FAIL_REMEDIATION_REQUIRED pending
independent audit against exactly these two frozen assertions; Phase 5
remains blocked; no self-approval is claimed anywhere in this document.
STATUS: PASS
GIT_COMMIT: PLACEHOLDER_FILLED_IN_SECOND_COMMIT

Instruction: argus-phase-4-recovery-005, ACTIVE at submission.

Per this instruction's own explicit TARGET_COMMIT field (not to be
confused with the commit that merely carries the instruction text --
see the terminology correction recorded in
orchestration/checkpoints/phase_4_recovery_3.md section A, left
byte-for-byte unmodified):

- This round's OWN authorizing instruction's carrying commit (the commit
  that carries argus-phase-4-recovery-005's text into
  orchestration/ORCHESTRATOR_INSTRUCTIONS.md): 3250313c2e5a424ec4f438350c
  a63780276224c2.
- This round's OWN authorizing instruction's `TARGET_COMMIT:` FIELD VALUE
  (the safety-gate ancestor baseline this session actually verified
  ancestry/diff-scope against before acting):
  c0b774f5deb9898bb6e1cfa4f364a1b458242610 (the commit that added
  orchestration/AUDITOR_POLICY.md).

Gate verification performed before any work began: `c0b774f5deb9898bb6e1c
fa4f364a1b458242610` resolves to a real commit, is an ancestor of HEAD,
and the only path differing between it and HEAD (`3250313...`) is
orchestration/ORCHESTRATOR_INSTRUCTIONS.md -- a single instruction-only
commit whose direct parent exactly matches this TARGET_COMMIT field
value. AUTHORIZED_PHASE 4 <= docs/BUILD_STATE.md's current_phase 4 + 1.
Worktree was clean; local HEAD equaled a freshly-fetched remote HEAD.
orchestration/AUDITOR_POLICY.md was read in full before implementation
self-audit, per its own mandatory requirement.

Preceding rounds: argus-phase-4-recovery-003 (checkpoint/bundle/evidence
preserved unmodified at orchestration/checkpoints/phase_4_recovery_3.md /
orchestration/bundles/phase_4_recovery_3.txt / orchestration/
phase_4_recovery_3/evidence/, commits 75e9ece07aa475e1ffc2413d110f5f0ee88
f3134 / 410a6c0136a5930dedaa3c03615e08aa63312032), and an intervening
recovery-004 instruction (commit 78b70d151217a84227d8c0363340ffed50149457,
orchestration/ORCHESTRATOR_INSTRUCTIONS.md-only) that was superseded by
this instruction before any implementation work began on it -- this
session never executed recovery-004; no evidence exists for it and none
is claimed. Full attempt history preserved and not renamed: initial Phase
4 build; remediation-001; remediation-002; failure-review-001; recovery-
001; recovery-review-001; recovery-002; recovery-003; recovery-004
(superseded, unexecuted); this reviewed, sealed recovery-005.

B. Builder self-audit -- required two-row ASSERT matrix (per instruction
   section "Builder self-audit before handoff")

| Row | Production/test evidence location | Exact test/check run | Actual result | Pass condition | PASS/FAIL |
|---|---|---|---|---|---|
| ASSERT-01 | tests/integration/test_phase4_recovery_3_matrix.py `_process_and_reprocess` (shared by TC-01/03/04, 60 of the 94 total cases: 8+8+44), `_scoped_probe_count`, `_position_count` | `uv run pytest tests/integration/test_phase4_recovery_3_matrix.py -q` | 94 passed, 0 failed. For every TC-01/03/04 case, `before_probe_count == after_first_probe_count == after_repeat_probe_count` (scoped by the claimed probe's own `shadow_intent_id`/`shadow_position_id`) and `before_position_count == after_first_position_count == after_repeat_position_count` (scoped by the seeded wallet) -- all asserted inline inside `_process_and_reprocess`, which raises `AssertionError` on any mismatch; none raised. TC-02's own SUCCESS cases never call this helper (unchanged from recovery-003) -- the oracle is never applied to them, per the frozen row's own explicit exclusion. | `before_counts == after_first_counts == after_repeat_counts` for both scoped counts, on every applicable TC-01/03/04 case, with the existing 94-case inventory unchanged and provider transport call count exactly one after repeat (already-existing assertion, re-verified unmodified). | PASS |
| ASSERT-02 | tests/integration/test_phase4_recovery_3_matrix.py `test_tc04_unsafe_provider_code_never_persisted_worker_and_reload_idempotent` (all 44 TC-04 cases), `caplog.at_level(logging.DEBUG)` wrapping both executor calls | `uv run pytest tests/integration/test_phase4_recovery_3_matrix.py -q` (TC-04 subset: 44/94 cases) | 44/44 passed. For every case, `caplog.text` (DEBUG and above, captured around both the first execution and the fresh-session repeat inside `_process_and_reprocess`) never contains any of the four injected inert fake-secret sentinels, nor (when the case's own `unsafe_code` is a nonempty string) that value in either raw or `repr()`-escaped form. Root-caused: `src/argus/shadow/quote_jobs.py`, the Jupiter provider adapter, and the retry/usage-recording modules contain zero `logging`/`getLogger` calls on this code path (confirmed by direct source inspection, section F) -- no production logger change was needed or made; the frozen test proves the existing (already-silent) behavior. | Existing TC-04 cases pass with real captured-log assertions; injected unsafe fake values absent from formatted captured logs; existing persisted-evidence/classification/reload/one-provider-call assertions continue to pass. | PASS |

Both rows PASS.

C. Row-by-row acceptance criteria -- unchanged original AM-01 through
   AM-15 plus TC-01 through TC-06

Unchanged from `orchestration/checkpoints/phase_4_recovery_3.md` section C
in every respect except TC-01/03/04 (now additionally covered by
ASSERT-01) and TC-04 (now additionally covered by ASSERT-02); see that
checkpoint (preserved byte-for-byte) for the complete original mapping,
not reproduced here per the sealed contract's own "do not add case
families" instruction.

D. Collected-case-inventory cross-check

`uv run pytest tests/integration/test_phase4_recovery_3_matrix.py
--collect-only -q` collects exactly 94 nodes -- byte-identical to
recovery-003's own frozen inventory (raw output in
orchestration/phase_4_recovery_5/evidence/collect_only.txt). No case
family was added or removed; only in-place assertion strengthening inside
the existing test bodies/shared helper.

E. DO-NOT / allowed-files compliance

| Prohibition | Compliance |
|---|---|
| Production code change to quote_jobs.py or any src/ file | None. `git diff --stat src/` is empty this round (section F). |
| New case families, expanded fuzzing, production-code redesign | None. Same 94-case inventory (section D); only `_process_and_reprocess` and TC-04's own test body were edited, no new parametrize entries. |
| Touch previously-closed production findings absent a demonstrated regression | None demonstrated; none touched. |
| Overwrite existing evidence, including recovery-002/003 artifacts | None. `orchestration/checkpoints/phase_4_recovery_3.md`, `orchestration/bundles/phase_4_recovery_3.txt`, and `orchestration/phase_4_recovery_3/evidence/` are confirmed byte-for-byte unmodified (an accidental regeneration of round 3's frozen replay-demo evidence during this round's own targeted-regression run, caused by moving `EVIDENCE_DIR` too late in the command sequence, was caught via `git status` before staging and reverted with `git checkout --`; the move was then redone before any further evidence-generating command ran). |
| Modify MASTER_SPEC.md, orchestration/AUDITOR_POLICY.md, orchestration/PROTOCOL.md, watcher code, migrations/, config | None. `git diff --stat` confirms empty for all of these this round. |
| Phase skip / self-approval | current_phase/last_orchestrator_approved_phase untouched by this document; APPROVES_PHASE remains NONE throughout. |

F. Commands actually run (raw output; PostgreSQL 16 local dev server, no
   live network anywhere)

```
$ uv run pytest tests/integration/test_phase4_recovery_3_matrix.py --collect-only -q
  94 tests collected (identical to recovery-003's own inventory; full list
  in orchestration/phase_4_recovery_5/evidence/collect_only.txt)

$ uv run pytest tests/integration/test_phase4_recovery_3_matrix.py tests/integration/test_phase4_recovery_2.py tests/unit/test_phase4_recovery_2_contract.py -q
  162 passed in 24.63s

$ uv run pytest tests/integration/test_shadow_phase4_remediation_observation.py \
    tests/integration/test_shadow_quote_jobs_provider_remediation.py \
    tests/integration/test_shadow_phase4.py \
    tests/integration/test_shadow_phase4_concurrency_remediation.py \
    tests/integration/test_migrations.py \
    tests/integration/test_daily_report_remediation.py \
    tests/integration/test_replay_demo_isolation.py -q
  128 passed, 42 warnings (pre-existing alembic path_separator deprecation,
  unrelated) in 54.09s

$ uv run pytest -q
  1073 passed, 42 warnings, 0 failed, 0 skipped in 139.53s (identical
  total to recovery-003's own final count -- this round added zero new
  test nodes, only strengthened existing ones)

$ uv run ruff check .
  All checks passed!

$ uv run ruff format --check .
  1 file (this round's own edited test file) would be reformatted ->
  `uv run ruff format .` applied -> re-run clean: 264 files already
  formatted; re-ran the 94-case matrix afterward to confirm still green

$ uv run mypy src
  Success: no issues found in 128 source files

$ uv run alembic heads
  0021 (head) -- unchanged; no new migration this round

$ uv run argus fixtures validate-real-chain
  All 12 real-chain fixtures: ok - ok (unchanged, unrelated surface)

$ grep -n "logging\|logger" src/argus/shadow/quote_jobs.py src/argus/providers/jupiter/client.py src/argus/providers/retry.py src/argus/providers/usage.py
  (no matches in quote_jobs.py/retry.py/usage.py; docs/BUILD_STATE-adjacent
  src/argus/logging.py itself is unrelated to this call path) -- confirms
  ASSERT-02's own root cause: this call path emits zero log records today,
  so the frozen test proves existing (already-safe) behavior, and no
  production logger change was needed or made.

$ (validator invocation against the ACTUAL final hash-filled files, run
   after this checkpoint's own GIT_COMMIT/bundle were filled in)
  >>> import importlib.util, sys
  >>> from pathlib import Path
  >>> spec = importlib.util.spec_from_file_location("w", "scripts/argus_orchestrator_watch.py")
  >>> w = importlib.util.module_from_spec(spec)
  >>> sys.modules["w"] = w
  >>> spec.loader.exec_module(w)
  >>> ckpt = Path("orchestration/checkpoints/phase_4_recovery_5.md").read_text()
  >>> bundle = Path("orchestration/bundles/phase_4_recovery_5.txt").read_text()
  >>> w.validate_checkpoint_content(ckpt)
  (True, '')
  >>> w.validate_bundle_content(bundle, ckpt)
  (True, '')
  >>> ckpt.strip() in bundle
  True

$ git status --porcelain (secret scan across this round's changed/new
  paths: scripts/argus_phase4_replay_demo.py,
  tests/integration/test_phase4_recovery_3_matrix.py, the new checkpoint/
  bundle, docs/BUILD_STATE.md, docs/DECISION_LOG.md,
  orchestration/AGENT_HANDOFF.md, and the new
  orchestration/phase_4_recovery_5/evidence/ directory's files --
  AWS-style keys, PEM headers, inline password/api-key/secret/token
  literals, excluding this round's own inert AUDIT_ONLY_FAKE_SECRET/
  should-never-be-stored test fixture strings) -- clean, no matches, no
  secret values emitted.

$ git diff --check --cached -- '*.py'
  clean (zero matches). The unrestricted git diff --check continues to
  flag trailing whitespace only inside raw captured pytest-output evidence
  .txt files (verbatim terminal output, expected, per recovery-002's own
  already-accepted HARDENING_BACKLOG classification) -- never in any
  source or test .py file.

$ git diff --stat src/ migrations/ config/ MASTER_SPEC.md orchestration/PROTOCOL.md scripts/argus_orchestrator_watch.py orchestration/AUDITOR_POLICY.md
  (empty output -- confirms zero changes to any prohibited path)
```

G. Test results

1073 passed, 0 failed, 0 skipped across the full suite (`uv run pytest
-q`) -- identical total to recovery-003's own final count, since this
round adds zero new test nodes and only strengthens the assertions
inside existing ones. The 94-case `test_phase4_recovery_3_matrix.py`
inventory itself is unchanged (section D).

H. Frozen (previously CLOSED, independently re-confirmed by this
   instruction's own embedded audit) finding regression re-confirmation

- F-01, F-02, F-03, COV-01: confirmed CLOSED by this instruction's own
  text ("All Phase 4 production fixes and all 94 previously frozen
  parameter cases remain CLOSED") -- not reopened or reworked;
  `git diff --stat src/` above confirms zero production-code changes this
  round.
- P4-REC-01/04/05 and every other independently-closed finding:
  unaffected files this round; the full 1073-test suite (section F)
  re-confirms no regression.
- Environmental deferrals (PG17_COMPOSE_VALIDATION, LIVE_HELIUS_RPC_
  VALIDATION, LIVE_HELIUS_WSS_VALIDATION, BQ_PUBLIC_DATASET_ACCESS) remain
  unchanged, not reopened.

I. Acceptance criteria: [PASS] Both ASSERT-01 and ASSERT-02, the complete
sealed blocking contract for this cycle per the instruction's own explicit
statement, are met -- see section B's required two-row matrix. All twelve
required regression/evidence checks in the instruction's own list pass
(sections F/G). No production code was changed; F-01/F-02/F-03/COV-01
remain closed as independently re-confirmed by this instruction's own
embedded audit before it authorized this sealed test-only work.

J. Deviations

None from the sealed contract. One process deviation is disclosed rather
than hidden: this round's own command sequence initially ran the targeted
regression suite (which invokes `scripts/argus_phase4_replay_demo.py` as
a subprocess via `test_replay_demo_isolation.py`) BEFORE moving
`EVIDENCE_DIR` to the new `orchestration/phase_4_recovery_5/evidence`
path, accidentally regenerating round 3's own frozen
`orchestration/phase_4_recovery_3/evidence/replay_demo_results.json` with
fresh random UUIDs. Caught via `git status --porcelain` before any
staging/commit, reverted with `git checkout --`, and the `EVIDENCE_DIR`
move was completed before any further evidence-generating command ran --
round 3's frozen evidence file is confirmed byte-for-byte unmodified in
the final diff (section E). This exact category of mistake (moving
`EVIDENCE_DIR` too late in the sequence) recurred from a prior round;
future rounds should perform this move as literally the first step after
gate verification, before any test command runs.

K. Known bugs / debt (unchanged from `orchestration/checkpoints/
   phase_4_recovery_3.md`'s own section K baseline; nothing new
   introduced)

- No new known bugs are introduced by this round's changes (test-only).
- `git diff --check` continues to flag trailing whitespace inside raw
  captured pytest-output evidence `.txt` files -- explicitly classified
  HARDENING_BACKLOG, never a phase blocker.
- Every other item in the prior round's own known-bugs/debt section
  (unchanged files this round) still applies unmodified.

L. Security state

Unchanged from the prior round's own security posture: no live-execution
code touched, no credentials entered or persisted, no new provider/paid
endpoint, no production code changed at all this round. ASSERT-02's own
44 cases each independently re-confirm, at the logging layer this time
(not merely the persisted-evidence layer TC-04 already covered in
recovery-003), that no injected fake-secret sentinel or unsafe error-code
value is ever observable -- not just never persisted, but never even
transiently logged. Secret scan clean on this round's changed/new paths
(section F).

M. Next action / STOP

STOP. Await independent audit of this sealed two-assertion completion
round, bounded to exactly ASSERT-01, ASSERT-02, and the twelve frozen
regression/evidence checks, per orchestration/AUDITOR_POLICY.md section 7
("stopping rule") and this instruction's own "Mandatory next-audit
behavior" section. Passing these builder tests does not approve Phase 4.
Only the orchestrator's own independent review may write the next
`ACTIVE` instruction into `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`,
approving Phase 4 and authorizing Phase 5, or requiring further recovery.

================ END ARGUS CHECKPOINT =========================
