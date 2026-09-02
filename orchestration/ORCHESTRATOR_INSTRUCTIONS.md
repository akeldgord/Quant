# ARGUS Orchestrator Instructions

OWNER: ARGUS ORCHESTRATOR. The implementation agent must not edit this file.
MASTER_SPEC.md remains authoritative. orchestration/AUDITOR_POLICY.md is mandatory audit governance and must be read before implementation self-audit and later independent audit.

INSTRUCTION_ID: argus-phase-4-recovery-005
ISSUED_AT: 2026-09-02T16:51:00Z
TARGET_COMMIT: c0b774f5deb9898bb6e1cfa4f364a1b458242610
AUTHORIZED_ACTION: PHASE_4_COMPLETE_TWO_SEALED_ASSERTIONS
AUTHORIZED_PHASE: 4
APPROVES_PHASE: NONE
STATUS: ACTIVE

## Decision

Resume Phase 4 immediately. The prior recovery-004 instruction is superseded only because the human-approved auditor-governance policy was committed on top of it. No product requirement has changed.

All Phase 4 production fixes and all 94 previously frozen parameter cases remain CLOSED. Phase 5 remains blocked only until the two sealed assertions below are implemented and handed back for audit.

This instruction is the complete SEALED Acceptance Contract for this cycle. After implementation begins, the auditor may not add another blocking test, proof requirement, evidence obligation, or acceptance row. Any legitimate newly noticed issue outside ASSERT-01/ASSERT-02 must be handled under orchestration/AUDITOR_POLICY.md as NEXT_PHASE_CARRYFORWARD or HARDENING_BACKLOG unless it is a demonstrated emergency safety/integrity defect.

## SEALED ACCEPTANCE CONTRACT

### ASSERT-01 — unchanged scoped probe/position counts

Classification if failed: SPEC_BLOCKING.

Required behavior/evidence:
- In the existing Phase 4 recovery matrix helper, observe test-owned scoped database counts before first execution, after the committed terminal result, and after fresh-session repeat.
- For TC-01, TC-03, and TC-04 non-success cases, the same scoped ShadowQuoteProbe count and seeded-wallet ShadowPosition count must remain unchanged across all three observations.
- Preserve the existing selected-row snapshot equality and exactly-one-provider-call/replay behavior.
- Do not apply this no-new-position oracle to TC-02 success cases.
- No production-code/schema change is authorized for this row.

Exact implementation/test method:
- Reuse tests/integration/test_phase4_recovery_3_matrix.py and its existing 94-case inventory.
- Pass the seeded wallet id into the shared process/reprocess helper for TC-01/03/04.
- For entry probes, count ShadowQuoteProbe rows scoped by shadow_intent_id and ShadowPosition rows scoped by seeded wallet.
- For reverse probes, count ShadowQuoteProbe rows scoped by shadow_position_id and ShadowPosition rows scoped by seeded wallet.
- Use persisted fixture state for initial expected counts; do not use unrelated table-wide counts.

PASS condition:
- The existing 94-case inventory remains unchanged.
- Every applicable TC-01/03/04 case executes without assertion failure.
- before_counts == after_first_counts == after_repeat_counts for both scoped counts.
- Existing selected-row persistence/reload assertions still pass.
- Provider transport call count remains exactly one after repeat.

### ASSERT-02 — captured-log absence for unsafe TC-04 values

Classification if failed: SPEC_BLOCKING.

Required behavior/evidence:
- Add real pytest caplog or equivalent logging capture around both executor calls for all existing TC-04 cases.
- Capture DEBUG and above through first execution, reload, and repeat.
- Assert existing inert unsafe sentinels and nonempty unsafe string code values, including escaped control/newline representations where applicable, are absent from captured formatted log messages/arguments.
- Keep exact status-only failure_evidence assertions and reload/idempotency behavior.
- Do not require the entire log to be empty; safe method/status/timing metadata may exist.
- No real credential may be injected, read, logged, or disclosed.
- No production logger change is authorized unless the frozen test demonstrates an actual failure; if current production passes, make test/evidence changes only.

Exact implementation/test method:
- Reuse tests/integration/test_phase4_recovery_3_matrix.py and its existing 44 TC-04 cases.
- Use only the already-existing fake literals/unsafe-code fixtures.
- For empty-string/non-string unsafe values, retain exact evidence assertions and avoid generic substring checks that would create false positives.

PASS condition:
- All existing TC-04 cases pass with real captured-log assertions.
- Injected unsafe fake values are absent from formatted captured logs.
- Existing persisted evidence, classification, fresh-session reload, and one-provider-call assertions continue to pass.

## Required regression/evidence checks

These are part of the sealed contract; no additional blocking checks may be invented later:

1. `uv run pytest tests/integration/test_phase4_recovery_3_matrix.py --collect-only -q` -> exactly the same 94-case inventory.
2. `uv run pytest tests/integration/test_phase4_recovery_3_matrix.py tests/integration/test_phase4_recovery_2.py tests/unit/test_phase4_recovery_2_contract.py -q` -> PASS, subject only to already-documented environmental setup limitations.
3. Existing affected Phase 4 integration regression group from recovery-004 -> PASS, subject only to already-documented environmental setup limitations.
4. `uv run pytest -q` -> PASS, subject only to already-documented environmental setup limitations.
5. `uv run ruff check .` -> PASS.
6. `uv run ruff format --check .` -> PASS.
7. `uv run mypy src` -> PASS.
8. `uv run alembic heads` -> exactly one head.
9. `uv run argus fixtures validate-real-chain` -> authentic fixture validation PASS.
10. Production checkpoint validator -> `(True, '')`.
11. Production bundle validator -> `(True, '')` and bundle contains exact final checkpoint bytes.
12. Final working tree clean; every Claude commit has the exact terminal trailer required below.

Existing environmental deferrals remain exactly as already recorded. Lack of auditor credentials is not permission to request, enter, or disclose credentials and is not a new failure if the corresponding builder evidence is truthful and the limitation remains documented.

## Builder self-audit before handoff

Before READY_FOR_AUDIT, Claude must produce a two-row acceptance matrix containing ASSERT-01 and ASSERT-02 with:
- production/test evidence location;
- exact test/check run;
- actual result;
- pass condition;
- PASS/FAIL.

Both rows must be PASS. A matching label or aggregate green count without the actual assertions is insufficient because that proof requirement is frozen here before implementation.

Do not add more case families. Do not expand fuzzing. Do not redesign production code. Do not touch previously closed production findings unless one of these two frozen tests directly demonstrates a regression.

## Allowed files

- tests/integration/test_phase4_recovery_3_matrix.py
- new orchestration/checkpoints/phase_4_recovery_5.md
- new orchestration/bundles/phase_4_recovery_5.txt
- new orchestration/phase_4_recovery_5/evidence/ as needed for fresh evidence
- docs/BUILD_STATE.md only as protocol permits
- append-only docs/DECISION_LOG.md only as protocol permits
- orchestration/AGENT_HANDOFF.md
- scripts/argus_phase4_replay_demo.py only if needed to redirect evidence output to the new recovery-5 evidence directory before running commands that generate evidence; no other replay-script change

Do not modify MASTER_SPEC.md, orchestration/AUDITOR_POLICY.md, orchestration/PROTOCOL.md, watcher code, src/, migrations/, config, historical checkpoint/bundle/evidence files, scores, thresholds, or live/safety authority.

## Handoff contract

Create new checkpoint/bundle artifacts; never overwrite historical evidence. The checkpoint must include the standard markers and required project/status/commit/commands/results/acceptance/deviations/debt/security/STOP sections. Explicitly state that ASSERT-01 and ASSERT-02 are the complete sealed blocking contract for this cycle.

AGENT_HANDOFF.md must contain exactly:
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-4-recovery-005
CURRENT_PHASE: 4
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
WORKING_TREE: clean
and valid fresh checkpoint/bundle paths for this run.

Every Claude commit for this instruction must end with exactly:
ARGUS-INSTRUCTION-ID: argus-phase-4-recovery-005
and nothing after it.

STOP after committing and pushing implementation/evidence/handoff. Do not begin Phase 5 and do not self-approve Phase 4.

## Mandatory next-audit behavior

The independent auditor must read orchestration/AUDITOR_POLICY.md first and audit only ASSERT-01, ASSERT-02, and the twelve frozen regression/evidence checks above. If all pass, Phase 4 passes. The auditor must not discover another ordinary blocking test afterward.

If a new real issue is noticed that is not a failure of this sealed contract, record it as NEXT_PHASE_CARRYFORWARD and roll it into the next phase acceptance review. Only a concrete emergency safety/integrity defect may interrupt this rule.

On Phase 4 PASS, approve Phase 4 and freeze/authorize the immediate next phase in the same orchestration cycle unless MASTER_SPEC or a genuine human-authority boundary requires input.
