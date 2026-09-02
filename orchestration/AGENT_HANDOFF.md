# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0030-phase-4-recovery-3
UTC_TIMESTAMP: 2026-09-02T15:35:00Z
CURRENT_COMMIT: PLACEHOLDER_FILLED_IN_SECOND_COMMIT
CURRENT_PHASE: 4
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-4-recovery-003
CHECKPOINT_PATH: orchestration/checkpoints/phase_4_recovery_3.md
BUNDLE_PATH: orchestration/bundles/phase_4_recovery_3.txt
TEST_STATUS: 94/94 new `tests/integration/test_phase4_recovery_3_matrix.py` (TC-01 8, TC-02 26, TC-03 8, TC-04 44, TC-05 8 -- collected-case count cross-checked against the frozen Cartesian sizes); combined with recovery-002's own files 162/162 (`test_phase4_recovery_3_matrix.py` + `test_phase4_recovery_2.py` + `test_phase4_recovery_2_contract.py`); targeted regression re-run 128/128; full repository suite 1073/1073 passed, 0 failed, 0 skipped (`uv run pytest -q`); ruff clean (1 self-inflicted import-sort issue in this round's own new file caught and fixed); ruff format clean (262 files); mypy clean (128 source files); alembic single head `0021` (unchanged -- no new migration); 12/12 real-chain fixtures ok; secret scan clean on this round's 3 changed/new paths; both real production checkpoint/bundle validators explicitly invoked against the final hash-filled bytes and asserted `(True, '')` -- ALL RAW COMMAND OUTPUT embedded verbatim in the paired bundle
WORKING_TREE: clean (verified via `git status --porcelain` before this commit)
ORCHESTRATOR_REVIEW_REQUIRED: whether this round's 94 new tests genuinely close COV-01 exactly as frozen (checkpoint section C/D maps every TC row to its own collected node IDs and cross-checks the Cartesian count), whether F-01/F-02/F-03 and P4-REC-01/04/05 remain genuinely untouched (checkpoint section E confirms `git diff --stat src/` is empty), whether the new checkpoint/bundle genuinely satisfy the production validators on independent re-inspection, and whether Phase 4 should now be approved and Phase 5 authorized, or further recovery/remediation required. This session does not and cannot apply Phase 4 approval itself.

## Work completed

Independently verified the safety gates for and executed orchestrator
instruction `argus-phase-4-recovery-003` in full: its `TARGET_COMMIT`
field value `87e8ba1b5a7969e5afe4a7e1e6c44eb392365f16` confirmed to be the
sole instruction-only commit directly above it (an ancestor of HEAD with
only `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` differing between them);
`AUTHORIZED_PHASE: 4` <= `docs/BUILD_STATE.md`'s `current_phase: 4` + 1 --
not skipping ahead; clean worktree; local HEAD equal to a freshly-fetched
remote HEAD -- before any work began.

This instruction embeds its own completed independent audit of
`argus-phase-4-recovery-002`: a fresh scratch harness (118 real
`JupiterClient`/`httpx.MockTransport` cases through the SAME production
common executor) re-confirmed F-01, F-02 and F-03 genuinely CLOSED --
no production defect was found or is being reopened here. The audit then
found recovery-002's own submitted tests satisfied only a representative
subset of that round's own frozen acceptance matrix (AM-01/02/03/04/08/
09/10 explicitly required full Cartesian worker/persistence/reload
coverage; the submission supplied helper-only checks or one representative
case per row instead). This is TEST-AND-EVIDENCE-ONLY work: **no file
under `src/` is touched this round** (`git diff --stat src/` is empty).

Added `tests/integration/test_phase4_recovery_3_matrix.py` (94 new tests,
TC-01 through TC-05), using the real `_execute_and_record_probe` common
executor seam recovery-002's own instruction already permitted calling
directly:

1. **TC-01** (AM-01/02/03, 8 cases): both probe kinds x both nested
   fields x {non-ASCII superscript-two, 5000-ASCII-digit string}. Each
   case: real persisted terminal `NO_ROUTE`, `requested_at<=responded_at
   <=terminal_at`, zero new `ShadowPosition`, exactly one HTTP call, PLUS
   a fresh-session reload and repeat-processing pass proving the complete
   persisted record is byte-for-byte unchanged and no second HTTP request
   occurs.
2. **TC-02** (AM-04, 26 cases): nested field x {3 valid, 10 invalid}
   representations, entry kind only (the frozen row's own common-seam
   exemption). Valid representations reach real `SUCCESS` with a genuine
   new `ShadowPosition`; every invalid shape reaches terminal `NO_ROUTE`
   with zero new positions.
3. **TC-03** (AM-05/07/10, 8 cases): both kinds x 4 status/code
   combinations, each with the same reload/repeat identity proof as TC-01.
4. **TC-04** (AM-08/10, 44 cases): both kinds x HTTP400/429 x 11 frozen
   unsafe-code shapes, each response also carrying ignored fake-secret
   sibling fields/headers -- `provider_error_code` absent in every case,
   only `http_status_code` persisted, no injected secret material present
   in persisted evidence, plus the same reload/repeat identity proof.
5. **TC-05** (AM-09, 8 cases): HTTP400/429 x identifier boundary, entry
   kind only (common-seam exemption) -- exact code preserved at/under the
   128-char boundary, 129 chars rejected.

A collected-case-inventory cross-check (`--collect-only -q`, 94 nodes)
confirms every row's own frozen Cartesian size was actually met, not
merely an AM-linked test node's existence -- the exact self-audit remedy
the instruction's own root-cause review required.

`scripts/argus_phase4_replay_demo.py`'s `EVIDENCE_DIR` was moved to
`orchestration/phase_4_recovery_3/evidence` BEFORE running the full/
regression suite (never after), the same narrow evidence-destination-only
allowance recovery-002 itself used -- round 2's frozen evidence file is
confirmed byte-for-byte unmodified in the final diff.

A documentation-only terminology correction was made in this round's OWN
new checkpoint (section A), distinguishing an instruction's own carrying
commit from that instruction's own `TARGET_COMMIT` field value --
recovery-002's own checkpoint conflated the two in its prose (though its
actual git-ancestry safety-gate verification was always correct). The
historical `orchestration/checkpoints/phase_4_recovery_2.md` file itself
is left byte-for-byte unmodified, per this round's own instruction's
explicit "do not edit the historical checkpoint" directive.

## Important findings

- COV-01 is CLOSED -- see `orchestration/checkpoints/phase_4_recovery_3.md`
  section C for the row-by-row matrix mapping every original AM row plus
  TC-01 through TC-06 to its own currently-passing test node(s), and
  section D for the collected-case-inventory cross-check.
- F-01, F-02, F-03, P4-REC-01/04/05 and every other previously-CLOSED
  finding remain genuinely untouched -- section E of the new checkpoint
  confirms `git diff --stat src/` is empty and every frozen finding's own
  regression suite still passes unmodified.
- `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is unchanged -- still the
  orchestrator's `argus-phase-4-recovery-003` instruction. Phase 4 is NOT
  marked approved anywhere in this session's evidence;
  `last_orchestrator_approved_phase` is `3` (unchanged), never `4`.
- Both commits this session carry the sole final trailer paragraph
  `ARGUS-INSTRUCTION-ID: argus-phase-4-recovery-003`, with no paragraph
  after it, verified via `git interpret-trailers --parse` before push.

## Failures or limitations

- None. All 94 new tests passed on their first run against the already-
  correct, unmodified production code -- consistent with the instruction's
  own expectation ("new coverage may already pass on current production
  code; do not manufacture red output or alter code merely to produce a
  failing test").
- `git diff --check` continues to flag trailing whitespace inside raw
  captured pytest-output evidence `.txt` files -- explicitly classified
  HARDENING_BACKLOG by this round's own authorizing instruction, never a
  phase blocker; old raw evidence is intentionally never rewritten to
  make this check cosmetically clean.
- `LIVE_HELIUS_RPC_VALIDATION`/`LIVE_HELIUS_WSS_VALIDATION`/`PG17_
  COMPOSE_VALIDATION`/`BQ_PUBLIC_DATASET_ACCESS` remain `DEFERRED_
  ENVIRONMENTAL_CHECK`, unchanged, not reopened this round.

## Deferred checks

- All items under "Failures or limitations" above.

## Exact next action requested from orchestrator

Audit only COV-01 and affected regressions, per this round's own
instruction's "Next independent decision" section. Do not reopen the
already-independently-confirmed F-01/F-02/F-03 production fixes or add
optional test cases. If the frozen coverage is complete and green,
consider approving Phase 4 with the existing environmental limitations and
freezing Phase 5's own acceptance matrix, per that same instruction's own
explicit next-step guidance. If a new mandatory failure appears, complete
a real root-cause review and issue only an evidence-backed safe recovery.
Only the orchestrator may apply Phase 4 approval -- write the next
`ACTIVE` instruction into `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`
(`TARGET_COMMIT` pinned to the exact commit named in this handoff) to do
so, or to require further recovery/remediation. Phase 5 remains forbidden
until then. Until a new instruction exists, the watcher (if running) takes
no action beyond logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** unchanged from prior handoffs — if you
cloned/fetched this branch before 2026-08-30T22:35 UTC, re-clone or
`git fetch --all && git reset --hard origin/claude/argus-folder-setup-77ahrk`
rather than merging/rebasing the old (pre-rewrite) history.
