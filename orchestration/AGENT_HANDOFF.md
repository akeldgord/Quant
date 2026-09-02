# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0031-phase-4-recovery-5
UTC_TIMESTAMP: 2026-09-02T16:45:00Z
CURRENT_COMMIT: a6922ac8df812f48a34ff637ddc17e45f3c5afab
CURRENT_PHASE: 4
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-4-recovery-005
WORKING_TREE: clean
CHECKPOINT_PATH: orchestration/checkpoints/phase_4_recovery_5.md
BUNDLE_PATH: orchestration/bundles/phase_4_recovery_5.txt
TEST_STATUS: 94/94 `tests/integration/test_phase4_recovery_3_matrix.py` (identical inventory to recovery-003, `--collect-only -q` cross-checked; 60 of the 94 cases -- TC-01/03/04 -- now additionally prove ASSERT-01's scoped-count stability, and TC-04's own 44 cases additionally prove ASSERT-02's captured-log absence); combined with recovery-002's own files 162/162; targeted regression re-run 128/128; full repository suite 1073/1073 passed, 0 failed, 0 skipped (`uv run pytest -q`, identical total to round 3 -- zero new test nodes); ruff clean; ruff format clean (264 files, after auto-reformatting this round's own edited test file); mypy clean (128 source files); alembic single head `0021` (unchanged -- no new migration); 12/12 real-chain fixtures ok; secret scan clean on this round's changed/new paths; both real production checkpoint/bundle validators explicitly invoked against the final hash-filled bytes and asserted `(True, '')` -- ALL RAW COMMAND OUTPUT embedded verbatim in the paired bundle
ORCHESTRATOR_REVIEW_REQUIRED: whether ASSERT-01 and ASSERT-02 -- the complete sealed blocking contract per this instruction's own text and `orchestration/AUDITOR_POLICY.md` -- are genuinely proven (checkpoint section B's required two-row matrix), whether F-01/F-02/F-03/COV-01 and every other previously-CLOSED finding remain genuinely untouched (`git diff --stat src/` empty, confirmed in checkpoint section F), whether the new checkpoint/bundle genuinely satisfy the production validators on independent re-inspection, and whether Phase 4 should now be approved and Phase 5 authorized, or further recovery required. This session does not and cannot apply Phase 4 approval itself.

## Work completed

Independently verified the safety gates for and executed orchestrator
instruction `argus-phase-4-recovery-005` in full: its `TARGET_COMMIT`
field value `c0b774f5deb9898bb6e1cfa4f364a1b458242610` (the commit that
added the new `orchestration/AUDITOR_POLICY.md`, NOT to be confused with
this instruction's own carrying commit `3250313c2e5a424ec4f438350ca63780
276224c2` -- see checkpoint section A's terminology note) confirmed to be
the sole instruction-only commit directly above it (an ancestor of HEAD
with only `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` differing);
`AUTHORIZED_PHASE: 4` <= `docs/BUILD_STATE.md`'s `current_phase: 4` + 1 --
not skipping ahead; clean worktree; local HEAD equal to a freshly-fetched
remote HEAD -- before any work began. Read `orchestration/AUDITOR_
POLICY.md` in full before implementation self-audit, per its own
mandatory requirement.

This instruction's own embedded audit confirmed F-01, F-02, F-03 and
COV-01 all genuinely CLOSED -- none reopened here. It sealed exactly two
remaining assertions as the complete blocking contract for this cycle:

1. **ASSERT-01 (unchanged scoped probe/position counts, SPEC_BLOCKING)**:
   `tests/integration/test_phase4_recovery_3_matrix.py`'s shared
   `_process_and_reprocess` helper (used by all of TC-01/03/04's 60
   non-SUCCESS cases) now also observes, at three points -- before first
   execution, after the committed terminal result, and after the
   fresh-session repeat -- the scoped `ShadowQuoteProbe` row count (by
   the claimed probe's own parent: `shadow_intent_id` for ENTRY_DELAY,
   `shadow_position_id` for REVERSE_EXECUTABLE, via a new
   `_scoped_probe_count` helper) and the seeded-wallet `ShadowPosition`
   count, asserting all three observations identical. Never applied to
   TC-02's own SUCCESS cases (per the row's own explicit exclusion).
   `_seed_and_claim_entry`/`_seed_and_claim_reverse` now additionally
   return the claimed probe's own `shadow_intent_id`/`shadow_position_id`
   so every TC-01/03/04 call site can supply the correct scope.
2. **ASSERT-02 (captured-log absence for unsafe TC-04 values,
   SPEC_BLOCKING)**: TC-04's own 44 cases now wrap both executor calls
   (first execution + fresh-session repeat, both already inside
   `_process_and_reprocess`) in `caplog.at_level(logging.DEBUG)` and
   assert that none of the four injected inert fake-secret sentinels, nor
   the case's own unsafe `errorCode` value (raw or escaped-`repr()` form,
   for nonempty string values), ever appear in the captured formatted log
   text. Direct source inspection (`grep` across `quote_jobs.py`, the
   Jupiter client, retry, and usage-recording modules) confirmed this
   call path emits zero log records today -- no production logger change
   was needed or made; the frozen test proves the existing, already-safe
   behavior.

**No file under `src/` is touched this round** (`git diff --stat src/` is
empty). The existing 94-case test inventory is byte-identical to
recovery-003's own (`--collect-only -q` cross-check) -- only in-place
assertion strengthening inside the shared helper and TC-04's own test
body, no new case families.

An accidental regeneration of round 3's own frozen `orchestration/
phase_4_recovery_3/evidence/replay_demo_results.json` was caught and
corrected mid-session: the targeted regression suite was initially run
BEFORE `scripts/argus_phase4_replay_demo.py`'s `EVIDENCE_DIR` was moved
to this round's own new `orchestration/phase_4_recovery_5/evidence`
path, so `test_replay_demo_isolation.py`'s own subprocess invocation
overwrote round 3's frozen file with fresh random UUIDs. Caught via
`git status --porcelain` before any staging, reverted with
`git checkout --`, and the move completed before any further
evidence-generating command ran -- round 3's frozen evidence is confirmed
byte-for-byte unmodified in the final diff. This exact category of
mistake has now recurred across rounds; disclosed explicitly in checkpoint
section J as a process note for future rounds.

## Important findings

- ASSERT-01 and ASSERT-02 are CLOSED -- see `orchestration/checkpoints/
  phase_4_recovery_5.md` section B for the required two-row acceptance
  matrix (production/test evidence location, exact check run, actual
  result, pass condition, PASS/FAIL for each).
- F-01, F-02, F-03, COV-01, P4-REC-01/04/05 and every other
  previously-CLOSED finding remain genuinely untouched -- section E/H of
  the new checkpoint confirms `git diff --stat src/` is empty and every
  frozen finding's own regression suite still passes unmodified.
- `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is unchanged -- still the
  orchestrator's `argus-phase-4-recovery-005` instruction. Phase 4 is NOT
  marked approved anywhere in this session's evidence;
  `last_orchestrator_approved_phase` is `3` (unchanged), never `4`.
- Both commits this session carry the sole final trailer paragraph
  `ARGUS-INSTRUCTION-ID: argus-phase-4-recovery-005`, with no paragraph
  after it, verified via `git interpret-trailers --parse` before push.

## Failures or limitations

- None. Both ASSERT-01 and ASSERT-02 passed on their first run against
  the already-correct, unmodified production code.
- `git diff --check` continues to flag trailing whitespace inside raw
  captured pytest-output evidence `.txt` files -- explicitly classified
  HARDENING_BACKLOG (unchanged from prior rounds), never a phase blocker.
- `LIVE_HELIUS_RPC_VALIDATION`/`LIVE_HELIUS_WSS_VALIDATION`/`PG17_
  COMPOSE_VALIDATION`/`BQ_PUBLIC_DATASET_ACCESS` remain `DEFERRED_
  ENVIRONMENTAL_CHECK`, unchanged, not reopened this round.

## Deferred checks

- All items under "Failures or limitations" above.

## Exact next action requested from orchestrator

Per this instruction's own "Mandatory next-audit behavior" section: audit
only ASSERT-01, ASSERT-02, and the twelve frozen regression/evidence
checks listed in the instruction, per `orchestration/AUDITOR_POLICY.md`'s
own audit-stopping rule. Do not discover another ordinary blocking test
outside this sealed contract. If all pass, the instruction's own text
directs approving Phase 4 and freezing/authorizing the immediate next
phase in the same cycle unless MASTER_SPEC or a genuine human-authority
boundary requires input. Only the orchestrator may apply Phase 4 approval
-- write the next `ACTIVE` instruction into `orchestration/
ORCHESTRATOR_INSTRUCTIONS.md` (`TARGET_COMMIT` pinned to the exact commit
named in this handoff) to do so, or to require further recovery. Phase 5
remains forbidden until then. Until a new instruction exists, the watcher
(if running) takes no action beyond logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** unchanged from prior handoffs — if you
cloned/fetched this branch before 2026-08-30T22:35 UTC, re-clone or
`git fetch --all && git reset --hard origin/claude/argus-folder-setup-77ahrk`
rather than merging/rebasing the old (pre-rewrite) history.
