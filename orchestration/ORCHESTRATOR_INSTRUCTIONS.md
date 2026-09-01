# ARGUS Orchestrator Instructions

OWNER: ARGUS ORCHESTRATOR. The implementation agent must not modify this file.
MASTER_SPEC.md remains authoritative. No implementation is authorized below.

INSTRUCTION_ID: argus-phase-4-failure-review-001
ISSUED_AT: 2026-09-01T20:12:12Z
TARGET_COMMIT: abb7df93fca33a9128095a56103c9bf80b9c3dd2
AUTHORIZED_ACTION: NONE
AUTHORIZED_PHASE: 4
APPROVES_PHASE: NONE
STATUS: NO_INSTRUCTION

## STOP disposition and human change control

AUDIT_ID: argus-phase-4-remediation-audit-002
DISPOSITION: FAIL_STOP_ROOT_CAUSE_REVIEW

STOP implementation. This is an inert audit/root-cause-review record, NOT
remediation-003, NOT permission to implement the recovery matrix, and NOT a
request for another implementation submission. The previous ACTIVE remediation
has been consumed by the handoff identified below. There is now no executable
instruction. The existing protocol/parser treats NO_INSTRUCTION as no launch;
the phase field preserves context, not authority to work.

Phase 4 remains unapproved; Phase 5 remains blocked. P4-R3 now closes. P4-R2,
P4-R5's existing worker-ownership logic, and P4-R7 remain closed. Do not reopen
those fixes or prior-phase findings. The new migration compatibility defect
below is in R4's new terminal-state wiring, not a rejection of the already
accepted worker-locking design. All Phase 0/1/1.5/2/3 approvals are unchanged.

Human-approved process decision, September 1, 2026: one build plus at most one
remediation. Phase 4 was already in remediation-002 when this rule was agreed;
the human explicitly directed a root-cause review, not remediation-003, if this
submission failed. The older seven-part exception does not override that STOP.
This document completes the review and records a proposed recovery contract;
resumption requires explicit human direction and a subsequent ACTIVE instruction.

For Phase 5 onward, before implementation authorization, freeze an atomic
requirement -> implementation evidence -> exact test -> pass condition matrix.
The builder must self-audit every row before declaring READY_FOR_AUDIT. Missing
rows or a green suite without the row-level proof are not completion. This is
the approved process correction, not permission to add product requirements.

## Audit identity and scope

Repository: akeldgord/Quant. Branch: claude/argus-folder-setup-77ahrk.
Audited remote HEAD: header target. Implementation/parent:
9890802f91da02c51fc4a2f12715c821158dc53b, directly based on instruction commit
3a16e150c5a9dd387f77d96e45a5e27f47a78182. Diff base is that instruction commit.
Matching handoff: handoff-0027-phase-4-remediation-2, recorded 2026-09-01T19:35:00Z,
LAST_ORCHESTRATOR_INSTRUCTION_ID exactly argus-phase-4-remediation-002.
Evidence: orchestration/checkpoints/phase_4_remediation_2.md,
orchestration/bundles/phase_4_remediation_2.txt,
orchestration/phase_4_remediation_2/evidence/replay_demo_results.json.

Frozen authority: MASTER_SPEC at Phase 4 authorization
379c5bc886abe7e99cdd3360fe3e71925ac932ce, its pre-build decisions, remediation-001
8b0e6dd52a37bbd517c97265d71fe8be381ea591, and the explicit remaining corrections
in remediation-002. MASTER_SPEC SHA-256 is unchanged:
41f7242c288feec709b1ed72e62c74a1dc5e3b3cd9ad01e9b6e28373d9d14011.
Relevant requirements: CORE-001/002/004, sections 44-48, 84, 93 and the Phase 4
gate. Only R1/R3/R4/R6 and affected regressions were re-audited. No Phase 5 model,
new provider, prospective alpha result, live-readiness or optional hardening gate.

Fresh GitHub HEAD/control-file reads, exact-SHA local checkout, two terminal
instruction-ID trailers, parent chain, canonical state/decision-log changes,
unchanged spec/protocol/instruction, checkpoint/bundle and source/test deltas
were checked. New evidence paths are new; old evidence remains unchanged in the
committed diff. Build-state still names Phase 3 as last orchestrator approval.
No actual deletion, live action, or secret exposure is alleged.

## Independent evidence and environmental limits

Auditor-executed at the audited target:

    uv run pytest tests/unit tests/golden tests/phase_1_5 -q
    # 660 passed in 17.52s; exit 0
    uv run ruff check .
    # All checks passed; exit 0
    uv run ruff format --check .
    # 256 locally discoverable files formatted; exit 0
    uv run mypy
    # 128 source files clean; exit 0
    uv run alembic heads
    # 0020 (head); exit 0; migration GRAPH, not DB execution
    uv run argus fixtures validate-real-chain
    # all 12 authentic fixtures pass; exit 0
    uv run pytest tests/integration/test_replay_demo_isolation.py -q -k refuse_unless
    # 2 passed, 6 deliberately deselected in 0.33s; exit 0
    uv run pytest tests/integration/test_shadow_phase4_remediation_observation.py -q -x
    # setup blocked by missing ARGUS_DB_ADMIN_PASSWORD; 1 setup error, exit 1

No credential was entered/requested; no external provider or database was used
by the auditor. The setup error is an environmental deferral, not a product
finding. Builder reports 890 passed with 33 warnings, focused82, predecessor80,
migration17, golden/replay/spike112, and a PG16 round-trip. Recorded result lines
and test sources were inspected; those PG executions are NOT independently
rerun. The migration summary does not prove a populated Phase 4 upgrade. File
format count differs locally by one; the check passed, not a product blocker.

Read-only temporary probes ran actual production functions with real
JupiterClient/httpx.MockTransport, the real PriorityScheduler, and minimal
in-memory persistence adapters. Production SELECT predicates were compiled and
executed against controlled SQLite rows, not a PostgreSQL concurrency claim.
The report-end counterexample has only ONE history row, so PostgreSQL DISTINCT
ON versus SQLite DISTINCT does not affect its result. The actual migration0020
upgrade function was executed with a capturing operations adapter; its captured
CHECK expression was evaluated against an old completed row. This proves the
constraint contradiction, not an assertion that an actual shared DB failed.
All probe assertions completed, exit 0. Results:

1. Score/tier split-clock exclusions PASS. A token first observed after T is
   unavailable; mutable lifecycle fallback is gone. But Token.first_observed_at
   =T, created_at=T+1h remains available at T. An OPEN WalletPosition with
   first_entry_at=T, created_at=T+1h under an eligible history is counted at T.
2. Seven unresolvable events before a finalized-success eighth event, limit1:
   the eighth is reached. False/unknown execution results are excluded, and
   the selected successful observation ID is retained. R3 PASS.
3. Real mocked Jupiter: wrong raw mint, NaN, Infinity and malformed impact are
   QUOTE_FAILED; routePlan=[null] is NO_ROUTE. However routePlan=[{"swapInfo":{}}]
   and [{"swapInfo":{"inputMint":42,"inAmount":"garbage"}}] both yield SUCCESS.
4. Real HTTP400 COULD_NOT_FIND_ANY_ROUTE maps to NO_ROUTE; HTTP429 maps to
   PROVIDER_CAPACITY_MISS. In both cases the supplied error code is discarded:
   raw_quote=None, no structured error/status/reason written on the probe.
   Scheduler rejection makes zero HTTP calls, has null call times and a genuine
   terminal_at, and replay makes zero further calls (PASS). Its actual
   RequestDropped.reason/priority class are nevertheless discarded (FAIL).
5. Migration0020 adds nullable terminal_at with no default/compatibility step,
   then adds validated CHECK (responded_at IS NULL OR terminal_at IS NOT NULL).
   For every legacy completed probe: responded_at is non-null and the new
   terminal_at is null; the actual CHECK evaluates FALSE. A populated upgrade
   cannot satisfy that constraint. No historical evidence must be deleted or
   invented to get past it.
6. Shadow marks +0.5/-0.2 in-window, 99 out-of-window => extrema +0.5/-0.2/count2.
   SUCCESS + NO_ROUTE + CAPACITY_MISS => separate counts, usable2. PASS.
   But one LOW history created after the report end is counted as low1 in the
   earlier report: latest-history selection has no report-end bound. FAIL.
7. Production checkpoint/bundle validators pass, including exact embedded
   checkpoint bytes. Replay remains explicitly NOT PROSPECTIVE ALPHA EVIDENCE.

## Complete remaining-gate traceability matrix

| Frozen obligation | Code and meaningful evidence | Result |
|---|---|---|
| R1 score effective AND recorded time <= first_seen | _score_snapshot_as_of; both split-clock tests and independent SELECT probe | PASS, retain |
| R1 tier effective AND recorded time <= first_seen; retain IDs | _tier_transition_as_of, snapshot IDs; split-clock/equality tests and SELECT probe | PASS, retain |
| R1 market dual-time bound; no current lifecycle fallback | _token_state_snapshot; market/fallback tests; direct probe | PASS, retain |
| R1 token creation/first-observation bound | only first_observed_at checked; split creation-time probe | FAIL R1-T |
| R1 single-history position context, represented recorded/economic bounds | chosen history and first_entry_at bound exist; WalletPosition.created_at bound absent | FAIL R1-T; single-history/entry-time fixes retained |
| R1 cluster dual bound/source reference | existing as_of/created_at predicates and cluster context unchanged | PASS inherited |
| R1 scanner tier-at-first_seen before LIMIT | correlated tier subquery, not current_tier; promotion/demotion and saturated-ineligible tests | PASS inspected, PG execution builder-only |
| R3 confirmation resolvability before LIMIT | correlated successful CONFIRMED/FINALIZED EXISTS; independent seven-before-one probe | PASS |
| R3 finality/success/source ID; initial and revisit same semantics | shared _confirmed_success_observation, FK0019, failed/unknown/finalized/delayed tests | PASS |
| R3 duplicate scanner recovery and no lost unrelated batch | per-candidate SAVEPOINT, event identity unique, return only inserted rows; genuine gather test | PASS inspected; no auditor PG concurrency claim |
| R4 returned top-level mint/notional identity | _classify_quote; real-adapter negative tests/probes | PASS |
| R4 route entries include valid mint/amount evidence | validator checks only dict and swapInfo dict; empty/garbage nested objects yield SUCCESS | FAIL R4-V |
| R4 invalid supplied impact vs honest missing; no-route/excessive remain | _classify_quote, real-adapter cases including NaN/Infinity | PASS |
| R4 available fees/raw response retained without cross-unit sum | raw_quote preserves route feeMint/feeAmount and platformFee; no cross-mint sum introduced | PASS preservation; normalized fee-unit clarity is non-blocking debt |
| R4 sanitized error/capacity reason and supplied status/code | exception handler retains only coarse outcome; real400/429/drop probes | FAIL R4-E |
| R4 actual dispatch timing, separate queue delay | times inside dispatched callable; real scheduler T+60/T+60.1 test asserts100ms | PASS inspected |
| R4 no-send null times, terminal time, replay no-call | new terminal_at guards; real scheduler drop/replay probe | PASS for newly created rows |
| R4 legacy compatibility without evidence rewrite; R5 preservation | migration0020 CHECK rejects all preexisting completed rows | FAIL R4-M; worker-lock design stays closed |
| R6 shadow sampled extrema/count/caveat vs historical | ShadowMarkOutcome query; independent .5/-.2/late99 probe | PASS |
| R6 historical grouping by asset/chosen history, no repeated versions | _build_research groups quote_asset_mint and latest-history IDs; SOL/USDC and repeated-reconstruction tests | PASS inspected for stated current-history scope |
| R6 distinct current wallet completeness at report end | DISTINCT ON deduplicates versions but lacks created_at<=end | FAIL R6-T |
| R6 outcome/missing/overdue separation and no future models | explicit successful/unsellable/missing_capacity and pending counts; independent oracle | PASS |
| R2 origin, R5 ownership guards, R7 isolated replay | unchanged origin/locking/isolation; only necessary terminal wiring; 7 concurrency/8 isolation builder tests, independent2 guards | Remain CLOSED except new R4 migration finding above |
| Evidence, authentic fixture, phase and safety boundaries | clean diff, exact trailers/validators,12 fixtures, no protected edits or new live path | PASS |

## Remaining findings: exact scope, not a new repair instruction

All five entries below are SPEC_BLOCKING. No HARDENING_BACKLOG item blocks
approval, and no additional blocking finding is being reserved for another round.

### R1-T — Represented creation-time cutoffs remain incomplete

Severity MEDIUM. Existing P4-R1, not a new gate. Remediation002 explicitly says
a Token row created/first-observed after cutoff is unavailable, and position
rows' represented recorded/economic times are bounded to that cutoff.
prospective._token_state_snapshot omits Token.created_at; _position_size_context
omits WalletPosition.created_at. The controlled probes above violate those
exact frozen clauses. This is not a claim of observed production corruption:
the ordinary token importer currently initializes both token clocks equally.
That initialization does not prove the explicitly required dual-clock consumer
contract. Other temporal subrequirements that passed stay closed.
Root cause: the dual-clock rule was applied to score/tier/market, not all
explicitly listed records. Affected surface: token/context snapshot helpers
and their ordinary monitor caller. Required proof before any resumed handoff:
split-clock token and position tests through the monitoring path, plus equality
and existing single-history regressions. No Phase3 redesign is required.

### R4-V — A dictionary is still being treated as route evidence

Severity HIGH. Existing R4 explicitly requires structurally valid route entries
and their mint/amount evidence, not merely a nonempty routePlan. The new helper
_is_structurally_valid_route_entry tests only two dictionary shapes. Its empty
or nonsensical swapInfo still yields SUCCESS and positive expected output in
the real-adapter path; the entry path consequently remains eligible to create
a shadow fill. Same validator handles entry and reverse probes.
Root cause: one more nesting level was checked, but required fields were not.
Required proof: normal complete route passes; empty/missing/wrong-type route
mint/amount evidence fails with no position/executable sample. No economic
route attestation, new venue support, or deeper optional semantic gate.

### R4-E — Terminal outcome loses the supplied failure evidence

Severity MEDIUM. Existing R4 requires sanitized error/capacity reason and supplied
status/provider code, separately from terminal time. _execute_and_record_probe
catches the exception and saves only _classify_provider_exception(exc); the
error branch never populates raw_quote or a structured error record. Real
HTTP400/429 and real scheduler-drop probes reproduce the loss. Global usage
accounting is retained but is not the missing bound provider-code/drop-reason
record. The coarse no-route/capacity classification itself is correct.
Root cause: completion timing was repaired, while evidence preservation was
omitted. Affected surface: shared entry/reverse exception seam, probe record,
capacity terminal path and its tests. Required proof: exact sanitized known
no-route/status/code and queue reason survive restart; unknown codes remain
QUOTE_FAILED with preserved safe evidence; contract-supported restriction case
must not depend exclusively on a fake-provider exception. No secret body or
arbitrary URL/header logging, no guessed provider-code mapping.

### R4-M — New terminal-state migration cannot accept old completed rows

Severity HIGH. New current-phase regression of R4 compatibility/R5 preservation,
not an optional future upgrade requirement. migration0020 adds terminal_at NULL,
then CHECK responded_at IS NULL OR terminal_at IS NOT NULL, without first
providing any truthful legacy representation. Every valid legacy completed row
therefore violates the new constraint. Actual captured migration operations and
CHECK truth evaluation prove it. The worker now also assumes terminal_at alone,
so merely bypassing the CHECK would make old completions look unfinished.
Root cause: a fresh-schema test was treated as upgrade compatibility proof;
new terminal state was designed without the populated predecessor state.
Affected surface: migration0020, terminal detection/claims/finalization/report
consumers, compatibility tests. Required proof: populated0018 upgrade including
completed success/error/capacity and pending rows; immutable old evidence/IDs
preserved; completed rows never re-call providers, pending rows remain runnable;
repeated startup stable. This report authorizes NO migration, backfill, downgrade,
data deletion, or evidence rewrite on an existing database.

### R6-T — Current-history count ignores the stated report end

Severity MEDIUM. Existing R6 explicitly says relevant latest known history at
report end. _latest_history_id_per_wallet_subquery takes no cutoff and has no
time predicate; _build_data_quality supplies start/end but does not use them for
history selection. A single LOW history created after end counts1 in the older
report. Deduplication itself passes and must not be redesigned.
Root cause: 'latest' was implemented as latest in the database, not latest known
at the named cutoff. Required proof: at end E, only a post-E history contributes
no pre-E history; pre-E LOW plus post-E HIGH remains LOW at E and HIGH after the
new assessment; same cutoff produces stable counts, equality explicit; state
the treatment of no known history. No retroactive database edits.

## Phase Failure Root-Cause Review — four required answers

### 1. Was the frozen gate unclear?

Partly at the process level, not as a reason to invent new product rules.
The remaining obligations were expressly written before this remediation:
dual clocks, route mint/amount evidence, error details, truthful old-state
compatibility and latest-known-at-report-end. However the architect grouped
many independent obligations into four large finding packets and supplied
worked examples rather than one executable/atomic acceptance row per clause.
No populated Phase4 migration fixture was supplied with the state change.
That made omission easy and verification expensive. Architect/process ownership:
replace broad 'finding fixed' signoff with atomic coverage frozen BEFORE work.

### 2. Was a clear requirement implemented incorrectly?

Yes. The source omits explicit recorded-time predicates, accepts empty route
evidence, drops explicit error details, and fails to bound history by report
end. New migration logic rejects the predecessor's completed-row shape. The
checkpoint's four-row matrix declares whole findings FIXED after proving only
subsets. It even calls scanner tier selection/concurrent inserts 'additional'
discoveries although both were already explicit instruction clauses. This is
observable incomplete contract coverage, not an accusation about intent.
Builder ownership: self-audit every frozen clause against production wiring,
including negative and predecessor-state cases, before another readiness claim.

### 3. Did the audit introduce a new requirement?

No for the five findings retained above: R1-T/R4-V/R4-E/R6-T cite explicit
remediation002 clauses; R4-M is a direct regression caused by the new migration
under the existing preservation/restart contract. Its discovery after coding
does not create a new product requirement. Conversely, deeper route economics,
an extra normalized fee schema, real-provider validation, or a populated live
alpha sample are NOT required here. Fee components already preserved in raw
JSON are accepted; further fee-unit presentation is HARDENING_BACKLOG only.
No genuine observed data loss is alleged. Existing accepted replay/environment
limitations and closed subrequirements remain accepted.

### 4. Why did the tests miss it?

The new tests are meaningful but not a complete contract harness:

- score/tier clocks split; token tests change first-observation with creation,
  and position creation-after-cutoff is absent;
- malformed routes cover null/missing swapInfo/non-object, not an empty or
  malformed swapInfo dictionary;
- error tests assert coarse outcome, not preserved code/status/reason;
- migration tests updated head assertions to0020 but do not seed completed
  Phase4 rows before the0018->0020 transition;
- report tests independently verify version deduplication, but omit post-end
  histories, reproducing 'latest now' in their expected-state scope.

The independently executing probes now reproduce those omissions. Before
implementation resumes, these cases must become named, independently derived
regression tests in the agreed recovery harness. The recovery matrix below is
a proposed contract, not authority to start that work. The orchestrator also
owns the process failure of allowing repeated repair chains; a fourth patch
cycle disguised as 'review follow-up' is not permitted.

## Proposed recovery acceptance matrix — INERT, approval required

| Frozen requirement | Implementation evidence to inspect | Exact proposed test | Independent pass condition |
|---|---|---|---|
| R1-T token recorded cutoff | token snapshot ordinary monitor path | test_token_recorded_after_cutoff_unavailable | first_observed=T, created=T+1 => unavailable at T; equality available |
| R1-T position recorded cutoff | selected history/context ordinary monitor path | test_position_recorded_after_cutoff_not_counted | eligible history, position first_entry=T/created=T+1 => not counted at T; unchanged existing history rows |
| R4-V route field evidence | real Jupiter -> shared classifier -> entry/reverse persistence | test_route_nested_mint_amount_evidence_required | valid complete route succeeds; empty/invalid swapInfo mints/amounts never fill or become usable quote |
| R4-E durable sanitized failure facts | real HTTP and scheduler exception -> terminal record -> reread | test_terminal_error_and_capacity_details_survive_replay | exact safe status/code/reason retained; unknown stays failure; zero further calls for terminal replay |
| R4-M predecessor compatibility | actual migration + all terminal consumers | test_populated_0018_upgrade_preserves_completed_probes | success/error/capacity/pending fixture upgrades; old byte evidence/IDs retained; complete rows no-call; pending still eligible |
| R6-T report knowledge cutoff | latest-history query in daily report | test_completeness_latest_known_at_report_end | LOW pre-E/HIGH post-E => low1 at E, low0 later; only post-E row is not a known low wallet at E; absence stated |

Recovery approval must identify the frozen harness and implementation scope
before any code changes. Preserve all already-passing cases and rerun affected
Phase4 tests, predecessor tests, migrations, full suite, lint/type/fixtures and
evidence validation in the authorized environment. An allowed environmental
deferral remains a deferral, never grounds for another speculative repair loop.
The auditor's temporary in-memory probes are not a substitute for the populated
PostgreSQL migration acceptance test on resumption.

## Adversarial coverage and claim ledger

| Failure class | Method | Result |
|---|---|---|
| Split effective/recorded clocks | actual SELECT/helpers, controlled rows; tests inspected | mixed PASS/FAIL R1-T |
| Saturated confirmation queue/finality/false/unknown | actual SELECT/helper; shared semantics/source FK | PASS R3 |
| New-event duplicate/concurrent insert | SAVEPOINT/unique identity and gather test inspection | PASS; PG runtime auditor-deferred |
| Malformed quote identity/impact/route | real adapter + MockTransport | identity/impact PASS; nested route FAIL R4-V |
| HTTP/drop details versus no-send timing/replay | real adapter/scheduler/recording path | timing/replay PASS; details FAIL R4-E |
| Populated predecessor schema transition | actual upgrade operations captured, CHECK evaluated | FAIL R4-M; no shared DB touched |
| Report shadow extrema/missing units/history time | real report SELECTs, hand-computed values | samples/units PASS; end cutoff FAIL R6-T |
| Worker locks/isolated replay | source/tests,2 isolated guard tests | CLOSED preserved; populated-state issue separately R4-M |
| Phase skipping/spec drift/secret/live/paid changes | exact commit diff, trailers, control checks | no such change found; all prohibited |

| Material builder claim | Independent disposition |
|---|---|
| All four continued findings FIXED | FALSE: R3 closes; R1/R4/R6 retain only the listed deficiencies |
| Full point-in-time boundary implemented | NARROWER_THAN_CLAIMED: score/tier/market/scanner pass; token/position recorded bounds missing |
| Confirmation finality/success/batch/race fixed | CONFIRMED by query probes and meaningful source/test evidence; actual PG concurrency not rerun |
| Honest route/fee/error/terminal evidence complete | NARROWER_THAN_CLAIMED: outer identity/impact/timing/raw fee retention pass; nested route/error facts/legacy transition fail |
| Report data now correct | NARROWER_THAN_CLAIMED: shadow extrema, asset grouping/dedup, class breakdown pass; report-end history fails |
| All regression/migration commands pass | Builder-reported890/33warnings; independently660/type/lint/fixtures pass. Existing migration tests do not prove populated Phase4 upgrade |
| No substantive deviations, no new known bugs | Incorrect as completeness claim given demonstrated omissions/regression; not evidence of deliberate deception |
| Replay isolated, old evidence preserved, no self-approval | CONFIRMED committed diff/source/guard tests; demo labels/cost limitations accepted |

Audit-of-audit: every remaining clause is mapped; failures cite frozen text or
current migration regression; accepted fixes remain closed; optional depth is
not blocking; environmental inability is not conflated with a defect. The full
known blocker list is above. No further implementation packet is authorized.

## Environmental deferrals and safety remain unchanged

LIVE_HELIUS_RPC_VALIDATION, LIVE_HELIUS_WSS_VALIDATION,
PG17_COMPOSE_VALIDATION and BQ_PUBLIC_DATASET_ACCESS remain deferred under the
previously approved closure procedures and gates. PG16 is only the accepted
functional substitute; no PG17 PASS is implied. Real Jupiter/DexScreener/
Telegram access is not required for this replay-allowed phase. The accepted
Phase3 one-wallet sample outcome is unchanged. These deferrals block live
readiness as previously specified, not Phase4 solely by their existence.

No mainnet trade, canary, signing/private-key/seed access, credential entry or
disclosure, paid-provider use/upgrade, live arming, threshold relaxation,
evidence rewrite, or phase skip is authorized. Do not run migration0020 against
an existing populated database to 'see if it works.' Do not clear/drop existing
history to satisfy it. Do not edit canonical history or this instruction.

STOP. Await explicit human direction on the root-cause review and a new ACTIVE
authorization. No remediation-003, Phase5 work, or autonomous recovery run.
