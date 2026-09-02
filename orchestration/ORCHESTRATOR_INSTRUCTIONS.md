# ARGUS Orchestrator Instructions

OWNER: ARGUS ORCHESTRATOR. The implementation agent must not modify this file.
MASTER_SPEC.md remains authoritative. Execute only the ACTIVE instruction.

INSTRUCTION_ID: argus-phase-4-recovery-001
ISSUED_AT: 2026-09-02T02:40:00Z
TARGET_COMMIT: 9aa8b8decf8cb17e1b3bb28e9e1ebd0b2083acda
AUTHORIZED_ACTION: PHASE_4_ROOT_CAUSE_RECOVERY
AUTHORIZED_PHASE: 4
APPROVES_PHASE: NONE
STATUS: ACTIVE

## Human authorization and purpose

The human operator explicitly authorized proceeding after the Phase 4 failure root-cause review. This is a controlled recovery from that STOP, not an ordinary remediation-003 and not permission to reopen Phase 4 generally.

Implement exactly the five unresolved SPEC_BLOCKING rows frozen in argus-phase-4-failure-review-001. Every other Phase 4 finding previously proven PASS/CLOSED remains closed. Do not add requirements, redesign closed behavior, retune thresholds, pull Phase 5 work forward, or perform optional hardening as part of this recovery.

Phase 4 remains unapproved until independent audit of this recovery. Phase 5 remains blocked.

## Recovery acceptance matrix — frozen before implementation

The following matrix is the complete blocking scope. Claude MUST implement and self-audit every row before handoff. A green general test suite is insufficient if any row lacks direct proof.

### P4-REC-01 — Token and position creation-time cutoffs

Frozen requirement: prospective state at cutoff T must not consume a Token whose created_at > T even when first_observed_at <= T, and must not consume a WalletPosition whose created_at > T even when first_entry_at <= T. Preserve already-passing score/tier/market/cluster dual-clock behavior and the single-history position rule.

Required implementation evidence:
- production token-state snapshot path explicitly bounds both Token.first_observed_at <= T and Token.created_at <= T;
- production position-context path explicitly bounds the represented WalletPosition.created_at <= T and its already-required economic time <= T;
- ordinary monitor caller uses these bounded paths with no mutable-current fallback.

Required tests/pass conditions:
1. split-clock Token: first_observed_at=T, created_at=T+1h => unavailable at T;
2. equality Token: both relevant clocks <=T => available subject to existing rules;
3. split-clock WalletPosition: first_entry_at=T, created_at=T+1h => excluded at T;
4. equality WalletPosition: both relevant clocks <=T => included subject to existing rules;
5. existing single-history, score, tier, market and cluster temporal regressions remain green.

### P4-REC-02 — Structural quote-route validation

Frozen requirement: a nonempty dictionary is not sufficient route evidence. A SUCCESS quote must contain structurally valid route entry evidence with correctly typed/parseable mint and amount fields required by the provider contract. Invalid route structure must never create an executable/shadow sample. Apply the same validator to entry and reverse probes.

Required implementation evidence:
- route validator checks required nested swapInfo fields rather than dictionary shape alone;
- required mint values are nonempty strings and required amounts are valid positive integer/raw-amount representations as applicable to the existing adapter contract;
- malformed/wrong-type/missing required fields produce QUOTE_FAILED or the already-frozen non-success classification, never SUCCESS;
- no new venue semantics or economic route attestation is added.

Required tests/pass conditions through the real adapter path with mocked transport:
1. normal complete provider-format route => SUCCESS;
2. swapInfo={} => not SUCCESS;
3. missing required mint/amount => not SUCCESS;
4. wrong-type mint => not SUCCESS;
5. malformed/nonpositive required raw amount => not SUCCESS;
6. invalid route produces no executable position/shadow sample;
7. existing wrong top-level mint, NaN/Infinity impact, empty/no-route and excessive-impact cases remain green.

### P4-REC-03 — Preserve sanitized terminal failure evidence

Frozen requirement: terminal probe records must preserve safe, supplied provider status/code/reason and scheduler rejection reason needed to explain NO_ROUTE, PROVIDER_CAPACITY_MISS and QUOTE_FAILED. Do not store secrets, headers, arbitrary URLs, or unsanitized bodies. Do not invent provider mappings.

Required implementation evidence:
- shared entry/reverse exception seam persists a bounded structured/sanitized failure-evidence representation;
- known HTTP status/provider code supplied by the adapter survives persistence/restart;
- scheduler RequestDropped reason and priority class, when supplied, survive persistence/restart;
- unknown provider codes remain QUOTE_FAILED while preserving safe supplied evidence;
- existing coarse outcome classification and provider accounting remain intact.

Required tests/pass conditions:
1. real-adapter mocked HTTP400 known no-route response => NO_ROUTE plus preserved sanitized status/code;
2. mocked HTTP429 => PROVIDER_CAPACITY_MISS plus preserved sanitized status/code;
3. unknown safe provider code => QUOTE_FAILED plus preserved code/status;
4. scheduler rejection => zero HTTP calls, null call timestamps as already frozen, terminal timestamp present, preserved sanitized drop reason/priority;
5. restart/reload returns the same safe evidence;
6. tests assert secrets/arbitrary body/header data are not persisted.

### P4-REC-04 — Populated predecessor migration compatibility

Frozen requirement: migration 0020 and terminal-state consumers must accept truthful preexisting Phase 4 rows without deleting, fabricating, or rewriting historical evidence. Existing completed rows must remain completed and must never cause provider re-calls; pending rows must remain runnable.

Required implementation evidence:
- migration strategy establishes a truthful compatibility representation for legacy completed rows before any terminal-state constraint is validated;
- immutable existing IDs, response/error evidence, timestamps and outcomes are preserved;
- consumer terminal detection handles migrated legacy completed rows consistently;
- pending predecessor rows are not falsely terminalized;
- repeated startup/migration state is stable.

Required tests/pass conditions:
1. create a populated schema at predecessor revision 0018 containing at minimum completed success, completed error/no-route, completed capacity-miss, and pending probe rows;
2. upgrade through 0020 successfully;
3. all old evidence/IDs asserted unchanged except new compatibility fields whose values must be deterministically derived from existing truthful evidence;
4. all legacy completed rows satisfy the new invariant and are treated terminal;
5. replay/worker pass makes zero provider calls for those completed rows;
6. pending row remains claimable/runnable;
7. repeated startup is stable/idempotent;
8. migration graph/head and existing worker-ownership tests remain green.

No migration may delete historical rows, replace IDs, manufacture provider observations, or use current wall-clock time as fake historical evidence. If no truthful deterministic terminal time can be derived for a legacy category, STOP and report that exact category rather than inventing one.

### P4-REC-05 — Report-end-bounded latest history

Frozen requirement: data-quality reporting must select the latest relevant wallet-history assessment known at report end, not a later assessment. Existing per-wallet deduplication stays intact.

Required implementation evidence:
- latest-history-per-wallet selection accepts the report-end cutoff and excludes history records whose recorded/created time is after end according to the existing history model;
- _build_data_quality passes the report end into that selection;
- one wallet contributes at most one qualifying latest-known assessment.

Required tests/pass conditions:
1. wallet has LOW history before report end and HIGH history after report end => earlier report uses LOW only;
2. later report after HIGH exists => uses HIGH only;
3. multiple pre-end versions => exactly one latest eligible version counted;
4. history only after report end => wallet is not counted as having that history at the earlier end;
5. existing quote-asset grouping, shadow extrema and outcome-separation reporting tests remain green.

## Mandatory self-audit before READY_FOR_AUDIT

Before handoff Claude MUST produce a row-by-row acceptance report for P4-REC-01 through P4-REC-05 containing:
- exact production file/function evidence;
- exact test names proving every numbered pass condition;
- command and result for each focused test group;
- full prior-phase regression result;
- lint/format/type-check results;
- migration graph result;
- explicit statement of any environmental validation not actually run.

Claude must adversarially execute the exact counterexamples from the root-cause review, not merely inspect tests. If any matrix row fails, do not hand off as READY_FOR_AUDIT; fix within this single recovery implementation before submission.

Required evidence artifacts:
- orchestration/checkpoints/phase_4_recovery.md
- orchestration/bundles/phase_4_recovery.txt

The bundle must embed or identify the row-level self-audit evidence and must distinguish builder-executed PostgreSQL/provider tests from anything environmentally deferred.

## Scope and safety boundaries

DO NOT:
- modify MASTER_SPEC.md or orchestration/PROTOCOL.md;
- modify this instruction file;
- reopen P4-R2, P4-R3, P4-R5 worker ownership, P4-R7, or any other closed finding absent a concrete regression caused by this recovery;
- implement Phase 5;
- change scoring/qualification thresholds or weights;
- use a new or paid provider;
- enter/request credentials or secrets;
- authorize or implement mainnet execution, canary trading, signing/private-key/seed access, live arming, or evidence rewriting;
- delete historical evidence to make a migration pass.

If implementation exposes a genuinely new safety/integrity defect outside these five rows, STOP and report it rather than silently expanding scope.

## Handoff contract

On successful completion, update normal builder-owned state/decision/handoff/checkpoint/bundle artifacts as required by PROTOCOL.md and STOP for independent audit.

AGENT_HANDOFF.md must use:
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-4-recovery-001

Every Claude implementation commit submitted under this instruction must end with the exact terminal trailer below, with nothing after it:

ARGUS-INSTRUCTION-ID: argus-phase-4-recovery-001

Do not self-approve Phase 4 or authorize Phase 5.