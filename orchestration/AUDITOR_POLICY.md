# ARGUS Auditor Policy

OWNER: ARGUS ORCHESTRATOR / INDEPENDENT AUDITOR
STATUS: ACTIVE
EFFECTIVE_FROM: 2026-09-02
REQUESTED_BY: human operator

This file is the mandatory audit-governance contract for Project ARGUS. It is additive to MASTER_SPEC.md and may not relax any MASTER_SPEC safety or authority boundary. Every future ARGUS orchestrator/auditor must read this file before freezing an implementation instruction and again before issuing an audit disposition.

## 1. Core rule: acceptance contracts are sealed before implementation

Before Claude begins any new phase, remediation, or recovery, the architect must create a complete Acceptance Contract inside the ACTIVE orchestrator instruction. The contract must enumerate every blocking requirement the later audit is allowed to enforce for that implementation cycle.

Every blocking row must have a stable criterion ID and must state, before implementation starts:

- required behavior;
- implementation evidence expected;
- exact test or verification method;
- exact pass condition;
- allowed environmental limitation, if any;
- whether the row is SPEC_BLOCKING or SAFETY_OR_INTEGRITY_BLOCKING if it fails.

The architect must self-audit the Acceptance Contract for completeness before publishing the instruction. Once the instruction commit exists and implementation begins, the Acceptance Contract is SEALED.

## 2. Auditor authority after seal

After implementation starts, the auditor has only these valid outcomes for a reviewed item:

1. PASS — the sealed criterion is proven.
2. FAIL_EXISTING_CRITERION — a numbered sealed criterion is not met. Every SPEC_BLOCKING finding MUST cite at least one exact frozen criterion ID. No criterion ID means it cannot block as a spec failure.
3. NEW_SAFETY_OR_INTEGRITY_DEFECT — a newly discovered concrete defect creates a credible immediate safety/integrity risk. This requires a reproducible counterexample or direct evidence of unsafe behavior; missing proof, missing test coverage, auditor preference, or a stronger desired oracle is not sufficient.
4. NEXT_PHASE_CARRYFORWARD — a legitimate issue discovered after seal that was not required by the frozen contract and is not an emergency safety/integrity defect.
5. HARDENING_BACKLOG — optional improvement, maintainability issue, extra defense, nicer evidence, or nonblocking test expansion.

The auditor MUST NOT create a new blocking acceptance criterion, required test, proof standard, matrix row, or evidence obligation after implementation has started.

## 3. Missing evidence rule

"Insufficient proof" may block the current cycle only when the sealed Acceptance Contract already specified that exact proof/test/evidence obligation.

If the auditor thinks another reasonable check would be valuable but that check was not frozen, the auditor records it as NEXT_PHASE_CARRYFORWARD or HARDENING_BACKLOG. The current phase is not failed for that omission.

The architect owns pre-freeze completeness. An architect omission is not retroactively converted into a builder failure.

## 4. Carryforward rule

A real problem found after seal that does not violate an existing frozen criterion must be recorded as NEXT_PHASE_CARRYFORWARD and rolled into the next phase/recovery acceptance-contract review.

Before freezing the next contract, the architect must consume every open NEXT_PHASE_CARRYFORWARD item and do exactly one of:

- include it as a numbered frozen criterion in the next Acceptance Contract;
- document why it is already covered by an existing frozen criterion;
- document why it is HARDENING_BACKLOG rather than blocking work;
- document why MASTER_SPEC places it in a later explicit phase.

Carryforward does not block approval of the current phase.

## 5. Emergency stop is narrow

A post-seal issue may block without an existing criterion ID only as NEW_SAFETY_OR_INTEGRITY_DEFECT, and only for a demonstrated immediate safety/integrity condition such as:

- credential/private-key/seed exposure;
- unauthorized live/mainnet/canary action;
- destructive or corrupting persistent-data behavior;
- unauthorized capital/spending action;
- clear execution-safety failure that could cause an action forbidden by MASTER_SPEC.

The auditor must provide the concrete counterexample/evidence and explain why deferring to the next phase would be unsafe. Ordinary missing tests, incomplete observability, preferred extra assertions, style issues, broader fuzzing, and speculative risks do not qualify.

## 6. One-remediation loop and automatic recovery

Default cycle:

freeze contract -> build -> independent audit -> at most one consolidated remediation against existing frozen IDs -> pass.

If the phase still fails after remediation #1, perform a Phase Failure Root-Cause Review. Do not start blind remediation #2. The root-cause review must produce a newly frozen bounded recovery contract and, when no genuine human-authority boundary is involved, automatically authorize that recovery. A completed root-cause review is not itself a reason to park Claude waiting for the human.

Human input is required only for genuinely new authority: live/mainnet/canary arming, spending/paid-provider commitments, credentials/secrets, destructive evidence migration, threshold relaxation/retuning, phase skipping, or a material unresolved product/strategy decision.

## 7. Audit stopping rule

Once every sealed criterion is independently proven, the auditor must stop searching for optional reasons to withhold approval.

New legitimate findings discovered during the bounded audit are classified under Sections 2-5 and carried forward as required. They do not reopen already-proven rows unless a concrete regression directly contradicts the frozen requirement.

## 8. Required audit disposition format

Every blocking audit finding must include:

- classification;
- exact frozen criterion ID, unless it is a NEW_SAFETY_OR_INTEGRITY_DEFECT;
- observed evidence/counterexample;
- exact failed pass condition;
- authorized correction scope.

Every newly discovered non-emergency issue outside the sealed contract must be labeled NEXT_PHASE_CARRYFORWARD or HARDENING_BACKLOG.

An audit that says "needs another check," "needs stronger proof," or equivalent without a pre-existing frozen criterion ID is invalid as a blocking disposition.

## 9. Phase advancement

When all sealed current-phase criteria pass, approve the phase even if NEXT_PHASE_CARRYFORWARD or HARDENING_BACKLOG items exist. Then freeze the next phase Acceptance Contract, incorporating required carryforwards, and authorize the immediate next phase in the same orchestration cycle unless MASTER_SPEC or a genuine human-authority boundary requires a stop.

A/S qualification, research success, or phase approval never implies live authorization.
