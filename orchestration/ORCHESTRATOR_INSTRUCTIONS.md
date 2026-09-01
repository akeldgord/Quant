# ARGUS Orchestrator Instructions

**OWNER: ARGUS ORCHESTRATOR.** The implementation agent must not modify this
file. Execute only the ACTIVE instruction below. MASTER_SPEC.md remains
authoritative except where this instruction explicitly records an orchestrator
approval, clarification, or change-control decision.

---

INSTRUCTION_ID: argus-phase-2-remediation-002
ISSUED_AT: 2026-09-01T02:32:04Z
TARGET_COMMIT: c99341a9c767c006cfe96fa4948dd54a9efe712b
AUTHORIZED_ACTION: REMEDIATE_ONE_REMAINING_FROZEN_PHASE_2_BOUNDARY_DEFECT_ONLY
AUTHORIZED_PHASE: 2
APPROVES_PHASE: NONE
STATUS: ACTIVE

## Independent re-audit disposition

Phase 0 remains approved as `PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`.
Phase 1 remains approved at `2fbc566af74832bc6523648f60ba8cb60d98eb31`
as `PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`. Phase 1.5 remains approved at
`c3148cc191de58ecab9b11cd05291cc8ffe45455` as `PASS_WITH_LIMITATIONS`.

The Phase 2 remediation submitted at implementation commit
`16737ca851ec51a528f4251fa94be3ef8ae84fc9` with final evidence commit
`c99341a9c767c006cfe96fa4948dd54a9efe712b` was independently re-audited.
Seven of the eight frozen findings from `argus-phase-2-remediation-001` are
CLOSED: **P2-R1, P2-R3, P2-R4, P2-R5, P2-R6, P2-R7, and P2-R8.** They MUST NOT
be reopened or expanded in this run. Their accepted implementation and tests
are regression-only evidence now.

Phase 2 is not yet approved because one narrow portion of P2-R2 remains open.
Phase 3 and all later phases remain blocked until this exact item is fixed and
re-audited.

## Why a second remediation is justified

This second remediation is permitted under the no-moving-goalposts policy only
because the remaining defect is an explicit acceptance case already frozen in
`argus-phase-2-remediation-001`; it is not newly invented hardening.

1. **Exact blocker:** the historical acquisition service has no explicit
   expected-history boundary to prove whether an empty/short pagination page is
   a legitimate end or a premature provider truncation. It unconditionally
   treats any empty/short page as complete.
2. **Classification:** `SPEC_BLOCKING` only.
3. **Frozen governing requirement:** P2-R2 in
   `argus-phase-2-remediation-001` explicitly required handling a
   **"premature empty/short page before an expected boundary"** and stated that
   none of the listed failure modes may be reported complete without direct
   completion evidence. Frozen acceptance test R2 required that case in the
   deterministic provider matrix with exact terminal completeness/status.
4. **Concrete consequence:** when a caller has an independently known expected
   historical boundary, a provider can truncate early with an empty/short page
   and ARGUS can incorrectly label incomplete history `COMPLETE`, contaminating
   archaeology/research completeness claims.
5. **Why the prior audit did not close it:** remediation-001 was broad. The
   builder's new test module describes a "premature short/empty page" in its
   header, but the actual tests only prove that an ordinary short final page and
   an ordinary empty history are treated as complete. The missing expected-
   boundary distinction became clear only during the focused remediation
   re-audit.
6. **Why this is not backlog/deferred:** it is a literal frozen R2 acceptance
   case and directly affects the truthfulness of current Phase 2 historical
   completeness status.
7. **No backlog promotion:** confirmed. No new robustness, provenance depth,
   concurrency behavior, live-provider validation, or future-phase work is
   being promoted to blocking status.

## Required remediation — one item only

Modify the existing provider-neutral historical acquisition boundary so a
caller can supply an **explicit expected historical boundary** that is
machine-checkable against the observed pagination walk. Use one deterministic,
typed contract appropriate to the existing provider abstraction, such as an
expected oldest slot/time/signature boundary or an equivalent unambiguous
boundary. Do not add multiple competing boundary schemes unless the existing
provider contract genuinely requires them.

Required behavior:

- If no external expected boundary is supplied, preserve the current documented
  Solana pagination semantics for an ordinary naturally short/empty terminal
  page; do not destabilize already-passing behavior.
- If an expected boundary is supplied, the acquisition result may report
  `COMPLETE` only after the observed walk has actually satisfied that boundary.
- An empty page or short page that arrives **before** the supplied expected
  boundary is satisfied must return `PARTIAL` (or the existing equivalent
  non-complete terminal status), preserve all successfully acquired evidence,
  and record a specific `known_gaps`/completeness reason identifying the
  unsatisfied boundary.
- The expected boundary must be propagated through the ordinary service/CLI
  path where applicable; it must not exist only as a test-only argument.
- Do not use a caller-supplied `--partial` flag as the proof. The service itself
  must compare observed evidence with the expected boundary.
- Keep existing pagination caps, duplicate/cycle/order detection, provider
  usage accounting, per-transaction failure behavior, archaeology integration,
  and all accepted P2-R1/R3/R4/R5/R6/R7/R8 behavior unchanged except for any
  minimal wiring strictly needed for this fix.

## Frozen acceptance tests for remediation-002

Add the smallest deterministic tests needed to prove the missing matrix row:

1. **Premature short page:** provide an expected boundary that has not been
   reached, return a short page, and assert non-COMPLETE/PARTIAL status, the
   unsatisfied boundary in gap/completeness evidence, preservation of fetched
   transactions, and correct provider usage accounting.
2. **Premature empty page:** after at least one valid page, return an empty page
   before the expected boundary and assert the same fail-closed behavior.
3. **Boundary satisfied:** provide an expected boundary that is actually
   reached/satisfied and assert the same otherwise-valid walk may report
   `COMPLETE`.
4. **No-boundary regression:** existing ordinary short-final-page and
   empty-history semantics continue to pass exactly as documented.
5. Run the focused historical-acquisition tests, affected CLI/integration tests,
   all Phase 2 tests, the full repository suite, Ruff lint/format, mypy, and the
   existing real-chain/golden regression suite. Report exact counts. Previously
   approved environmental deferrals remain deferrals; do not spend this run
   reopening them.

## Efficiency / scope lock

This is intentionally a tiny final Phase 2 remediation.

- Do **not** redesign Phase 2.
- Do **not** add new security or hardening requirements.
- Do **not** revisit the seven closed P2 findings except for regression tests.
- Do **not** begin Phase 3.
- Do **not** invent extra tests unrelated to this boundary defect.
- Implement the smallest production-grade correction, run the required
  regressions, create fresh evidence, push, and STOP.

If this exact boundary defect is proven fixed with no regression, the next
orchestrator audit should approve Phase 2 and authorize Phase 3 in the same
cycle.

## Evidence and handoff

Create fresh immutable evidence files; do not overwrite prior remediation
records:

- `orchestration/checkpoints/phase_2_remediation_2.md`
- `orchestration/bundles/phase_2_remediation_2.txt`

Update `docs/BUILD_STATE.md`, append `docs/DECISION_LOG.md`, and replace
`orchestration/AGENT_HANDOFF.md` with a new matching handoff. Do not mark Phase
2 orchestrator-approved. Use a new `HANDOFF_ID` and exactly:

`LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-2-remediation-002`

Every implementation-agent commit for this run must end with exactly one real
terminal Git trailer, with no paragraph after it:

`ARGUS-INSTRUCTION-ID: argus-phase-2-remediation-002`

Push, verify clean worktree and exact local/remote HEAD equality, then STOP.

## Prohibitions preserved

This instruction does not authorize Phase 3, a phase skip, mainnet trade,
canary, quote intended for execution, transaction signing or broadcast,
signer/private-key/seed access, credential entry/disclosure, paid-provider
upgrade or use, live arming, threshold relaxation, evidence rewrite, or work
outside the single frozen P2-R2 boundary defect above. Claude must not modify
this instruction file or self-authorize Phase 2 or any later phase.
