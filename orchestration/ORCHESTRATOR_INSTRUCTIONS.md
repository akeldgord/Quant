# ARGUS Orchestrator Instructions

OWNER: ARGUS ORCHESTRATOR. The implementation agent must not modify this file.
MASTER_SPEC.md remains authoritative. Execute only the ACTIVE instruction.

INSTRUCTION_ID: argus-phase-4-remediation-002
ISSUED_AT: 2026-09-01T17:22:28Z
TARGET_COMMIT: 1d5cc5d93819cdeec050889a5b37c44d5b2f5c0b
AUTHORIZED_ACTION: CLOSE_REMAINING_FROZEN_PHASE_4_FINDINGS
AUTHORIZED_PHASE: 4
APPROVES_PHASE: NONE
STATUS: ACTIVE

## Disposition and frozen scope

AUDIT_ID: argus-phase-4-remediation-audit-001
DISPOSITION: FAIL_REMEDIATION_REQUIRED

Phase 4 remains unapproved; Phase 5 remains blocked. Execute the four remaining
findings below as ONE batch, produce fresh evidence, then STOP. This is a
justified second remediation of the SAME frozen requirements, not a new gate.
P4-R2, P4-R5 and P4-R7 are CLOSED. Do not redesign or reopen them absent concrete
regression evidence. Preserve their behavior while making necessary wiring changes.
All Phase 0/1/1.5/2/3 approvals and closed findings remain unchanged.

Authority: MASTER_SPEC.md as frozen by argus-phase-4-001 at
379c5bc886abe7e99cdd3360fe3e71925ac932ce, its explicit pre-build decisions, and
the already-frozen corrective behavior in argus-phase-4-remediation-001 at
8b0e6dd52a37bbd517c97265d71fe8be381ea591. MASTER_SPEC SHA-256 is unchanged:
41f7242c288feec709b1ed72e62c74a1dc5e3b3cd9ad01e9b6e28373d9d14011.
Relevant authority is CORE-001/002/003/004, sections 19-20, 44-48, 84, 93-94,
the Phase 4 gate, and inherited provider priority/accounting and asset-unit rules.
No Phase 5 scoring, forward-alpha model, graph, live execution or new data-source
requirement is introduced. No SHOULD/MAY has been promoted to MUST.

## Audit identity and independent work

Repository akeldgord/Quant; branch claude/argus-folder-setup-77ahrk.
Audited remote HEAD is the header target; parent/implementation commit is
285f5a9fe993ff72a02ef6470ea9627952389428, whose direct parent is the prior
instruction commit 8b0e6dd52a37bbd517c97265d71fe8be381ea591. Diff base is that
instruction commit. Handoff: handoff-0026-phase-4-remediation-1, exactly matching
argus-phase-4-remediation-001. Referenced evidence:
orchestration/checkpoints/phase_4_remediation_1.md,
orchestration/bundles/phase_4_remediation_1.txt,
orchestration/phase_4_remediation_1/evidence/replay_demo_results.json.

Fresh GitHub reads, exact-SHA fetch/clean detached checkout and both terminal
commit trailers were verified. No protected spec/protocol/instruction changes,
historical evidence replacement, phase skipping or self-approval was found.
Canonical files were read in protocol order, followed by checkpoint/bundle,
complete changed production service/CLI/domain/migration paths, focused test
sources and affected predecessor interfaces. The audit-build-phase skill was
used for requirement traceability, adversarial checks and audit-of-audit.

Auditor-executed checks at this target:

    uv run pytest tests/unit tests/golden tests/phase_1_5 -q
    # 660 passed in 18.93s, exit 0
    uv run ruff check .
    # All checks passed, exit 0
    uv run ruff format --check .
    # 253 locally discoverable files already formatted, exit 0
    uv run mypy
    # 128 source files clean, exit 0
    uv run argus fixtures validate-real-chain
    # all 12 authentic fixtures pass, exit 0
    uv run pytest tests/integration/test_replay_demo_isolation.py -q -k refuse_unless
    # 2 passed, 6 deselected in 0.49s, exit 0; deliberate guard-only selection
    uv run alembic heads
    # 0018 (head), exit 0; repository migration graph, NOT a DB execution
    uv run pytest tests/integration/test_shadow_phase4_remediation_observation.py -q -x
    # setup blocked: MissingCredentialError, ARGUS_DB_ADMIN_PASSWORD; exit 1

No credential was requested/entered and no real database/provider was used by
the auditor. The last result is an environmental limit, NOT a product failure.
Builder evidence reports 859 full tests, 51 new tests, migration17, acquisition36,
qualification17 and golden/replay/spike112. Their recorded result lines and test
sources were inspected; PostgreSQL results are NOT claimed as independently
rerun. Migration round-trip text includes a narrative summary rather than a
full command transcript; retain honest provenance in the next bundle. Existing
PG16 substitute / PG17 environmental deferral remains accepted.

Independent temporary probes executed production functions. Temporal/report
SELECTs were compiled from the actual SQLAlchemy statements and evaluated on
controlled in-memory SQLite rows; this is a query-predicate oracle, not a claim
of PostgreSQL concurrency or migration validation. Quote probes used the REAL
JupiterClient, httpx.MockTransport, real PriorityScheduler and minimal in-memory
session adapters. All final probe assertions completed, exit 0. Results:

1. Tier effective T but recorded T+1h is selected at cutoff T. Score created T
   but as_of T+1h is selected at T. Without a pre-T market snapshot, token state
   copies current_lifecycle_stage from a token first observed after T.
2. Confirmation queue limit1, oldest event never confirmed, second event truly
   confirmed: three repeated passes update zero events. A CONFIRMED observation
   with transaction_succeeded=False is accepted without a success distinction.
3. Real mocked Jupiter responses with NaN/Infinity impact, routePlan=[null], or
   outputMint=UNRELATED all produce SUCCESS. A real-format supplied fee remains
   fee_estimate_raw=None. Empty route is correctly NO_ROUTE (retain that fix).
4. Real scheduler drop produces zero HTTP calls but persists non-null requested_at
   and responded_at, with no retained rejection reason. A controlled queue wait
   sends HTTP at T+60 but records requested_at=T, delay=0 and latency=60000ms.
5. One SUCCESS, one NO_ROUTE and one capacity miss produce matured count3 without
   a shadow-outcome breakdown. Actual shadow marks are ignored for extrema.
   One wallet with two old LOW assessments and a later HIGH is counted as two
   low-completeness wallets. 1 SOL and 100 USDC historical MFE are averaged into
   an unidentified quote amount of 50.5 in the shadow report.
6. R2 independently passes: first_seen T / creation T+60 gives +1s due T+1 and
   created_at T+60. Production checkpoint/bundle validators pass, including
   exact embedded checkpoint bytes. The new demo's due/request/response values
   correctly yield 2.7s scheduling delay and 100ms response latency.

## Complete requirement-to-evidence matrix

| Frozen obligation | Observed code/test/evidence | Disposition |
|---|---|---|
| R1: evidence known at first_seen, both recorded/effective time | score lacks as_of bound; tier lacks created_at bound; market lacks created_at bound; token fallback uses mutable current state | FAIL, R1 continued |
| R1: selection and context independent of later changes | scanner still prefilters Wallet.current_tier; later demotion can omit an earlier tracked trade; single-history position selection and cluster dual bounds improve context | FAIL selection; retain single-history/cluster fixes |
| R2: probe origin/actual creation and due arithmetic | intents uses event.first_seen_at, separate created_at; worked-example test and corrected demo | CLOSED; queued actual-call timing remains R4, not a reopening of origin |
| R3: drain new economic events; parser replay | NOT EXISTS before LIMIT and canonical event_id uniqueness; 7-row/limit3 and two-parser tests | PASS sequential new-event drain/dedup; retain |
| R3: late confirmation/finality and repeat/concurrent passes | pending LIMIT applied before checking resolvable evidence; only CONFIRMED, no success distinction; concurrent new-event insert has no conflict recovery | FAIL, R3 continued |
| R4: actual provider error and capacity paths | real no-route/429/drop mapped, CLI scheduler and usage recorder wired; rejection details lost; no-send and queued time mislabeled | Partial, R4 continued |
| R4: valid quote identity, route, impact, fees | notional check and empty-route fix work; malformed nonempty route/wrong mint/nonfinite impact accepted; fee always None | FAIL, R4 continued |
| R5: owned terminal writes for quote AND mark | generation passed from claim, FOR UPDATE terminal guard; terminal no-call; parent-intent lock serializes first position; crash/replay tests | CLOSED by code and inspected test evidence; DB rerun environmental |
| R6: tier direction, new-wallet count, notifier integration | correct from/to rank, Wallet identity count, ordinary service/CLI callers, notification after commit with failure isolation | PASS, retain |
| R6: available shadow/sample/data-quality facts | historical MFE substituted for shadow marks, cross-unit average, repeated history rows counted as wallets, no outcome/sample breakdown | FAIL, R6 continued |
| R7: replay cannot delete/consume shared evidence | creates new scratch DB before writes; all service scans scoped there; no shared address cleanup; failure/success preservation tests | CLOSED; actual PG run is builder evidence |
| Separate mark/executable, immutable first_seen, stream safety | distinct tables/outputs and Phase1 degraded-state mechanism retained; no live route added | PASS inherited structure; current data defects above remain blocking |
| Evidence/trailers/phase and safety controls | new checkpoint/bundle/demo, correct chain and trailers, protected files unchanged; no new executor grants | PASS inspected; no actual loss or live action alleged |

## Seven-part no-moving-goalposts justification for round 2

| 1. Exact remaining blocker | 2. Classification | 3. Frozen authority | 4. Concrete consequence | 5. Why round 1 did not close it | 6. Why not backlog/environment | 7. Bounded closure |
|---|---|---|---|---|---|---|
| P4-R1 temporal predicates/fallback/selection | SAFETY_OR_INTEGRITY_BLOCKING | section44/CORE-001; remediation001 R1 explicitly requires BOTH effective/as-of and recorded/observed cutoff, and first-seen selection | future knowledge or current tier changes alter old research observations | tests move all timestamps together and retain current A/S; no split-clock or post-T-token fallback/demotion case | demonstrated current query behavior, not provenance depth or unavailable provider | complete same cutoff across existing fields/selection; preserve no-evidence state and source refs |
| P4-R3 confirmation starvation/finality/success and duplicate-pass recovery | SPEC_BLOCKING | sections19-20/44/84; remediation001 R3 explicitly requires repeated/concurrent bounded passes and processed->confirmed/finalized without promoting failed tx | real confirmations remain permanently unseen or indistinguishable from failed transactions; concurrent inserts can abort a pass | new-event pagination was fixed, same pre-filter-LIMIT bug copied to confirmation revisit; tests cover one successful CONFIRMED row and sequential scans | ordinary monitoring lifecycle, no external data needed | resolve evidence before limit, preserve source finality/success and immutable links; recover duplicate claim without rewriting snapshots |
| P4-R4 quote validity and actual-call/missing evidence | SPEC_BLOCKING | sections45-48; remediation001 R4 explicitly forbids malformed/nonfinite SUCCESS, requires identity/fees/reason and no invented request | invalid quotes make fills; queue wait becomes fake call latency; a dropped call appears sent | tests explicitly assert lenient SUCCESS contrary to instruction, omit wrong mint/malformed nonempty route, and assert drop outcome without timestamp/reason | concrete contract failures with real adapter and scheduler, not more hypothetical hardening | reject demonstrated invalid inputs; capture dispatch timing and terminal no-send state; preserve fees/error reason within current quote path |
| P4-R6 current-phase report accuracy | SPEC_BLOCKING | section93 and remediation001 R6 requires shadow sampled marks, current completeness, sample/missing classification; inherited asset-unit integrity | shadow report ignores its marks, counts versions as wallets, averages SOL with USDC | tests seed historical positions and duplicate production formulas instead of checking shadow data and independent unit/count oracles | materially false current report, not Phase5 scoring or sample thresholds | query existing shadow/history evidence with explicit units, unique current wallet state and outcome breakdown |

These are incomplete executions of frozen corrections. No new provider,
security feature, statistical threshold, identity attestation or operational
readiness requirement is being added. Closed work stays closed. Round 3 would
require a new explicit exact frozen/current-integrity justification; it is not
pre-authorized by this instruction.

## One ordered implementation batch

0. Start with git status, git pull --ff-only, git log -5. Read canonical files
   in PROTOCOL order. Verify this instruction is one instruction-only commit
   directly atop the header target. STOP on protected-file change, overlap,
   unexpected branch movement or target mismatch. Never edit this file.
   Read the four continuation sections and write their negative tests FIRST
   or together with code. Do not merely rename existing passing assertions.

### 1. P4-R1 — Complete the existing first-seen knowledge boundary

Severity HIGH. Classification SAFETY_OR_INTEGRITY_BLOCKING.
Surface: shadow/prospective.py, its scanner and snapshot helpers/tests.

- _score_snapshot_as_of: require BOTH created_at <= cutoff and as_of <= cutoff.
- _tier_transition_as_of: require BOTH transitioned_at <= cutoff and created_at
  <= cutoff. Preserve the exact chosen transition_id and score_id.
- _token_state_snapshot: require observed_at AND created_at <= cutoff for
  snapshots. A Token row created/first-observed after cutoff is unavailable at
  that time. With an eligible token but no eligible market/lifecycle snapshot,
  do not copy tokens.current_lifecycle_stage; return explicit unavailable
  lifecycle/market state. Preserve immutable mint identity separately.
- Keep position reconstruction restricted to one eligible history, never sum
  duplicate historical versions. Bound the selected position rows' represented
  recorded/economic times to the same cutoff. Keep existing dual-bound cluster
  query and source references. No Phase3 reconstruction redesign is authorized.
- Scanner eligibility must not depend on the wallet's later current_tier.
  Evaluate the allowed tracked tier at each swap.first_seen_at from eligible
  immutable tier history. Apply eligibility/exclusion before the batch LIMIT
  so permanently ineligible old rows do not cause a new starvation bug. A later
  promotion cannot qualify an old event; later demotion cannot erase an event
  that actually qualified at T. Missing T state remains unavailable/ineligible,
  not a reason to fabricate a qualifying score or tier. Preserve already-created
  prospective snapshots; do not backfill new values into old decisions.

Required tests: split effective-vs-recorded timestamps in each represented
family, inclusive equality, token first known after T, eligible token with only
post-T lifecycle state, wallet A at T then WATCH before first scan, wallet WATCH
at T then A before scan, and >limit permanently ineligible rows before eligible
work. Assert selected IDs/values, no future input, no fabricated intent and
deterministic drain/replay. Tests must run the ordinary monitor/scanner, not
only helper predicates. Existing single-history and after-creation immutability
tests remain passing.

### 2. P4-R3 — Finish confirmation and repeated-pass lifecycle

Severity HIGH. Classification SPEC_BLOCKING.
Surface: prospective.revisit_pending_confirmations, initial confirmation lookup,
scan_for_new_prospective_events, monitor and narrowly necessary domain/schema.

- Build the eligible confirmation candidate set by joining/selecting resolvable
  commitment evidence BEFORE applying LIMIT. Old events with no resolvable
  evidence must not permanently occupy every batch slot.
- Consume actual CONFIRMED or FINALIZED source evidence. Preserve observed
  finality, transaction_succeeded (including unknown), source observation ID
  and timestamp; never treat failed/unknown as successful confirmation. Initial
  creation and late revisit must use the same semantics. A finalized-only
  successful observation must not be missed solely because no intermediate
  CONFIRMED record exists. Do not change live commitment policy or ban existing
  processed-only research.
- Use existing immutable CommitmentObservation rows as authority; persist a
  linked immutable application record if needed to bind the prospective event
  to its selected observation. confirmation_time may remain a cache only when
  it is reproducible from that preserved link. Do not replace first_seen, score
  or context. Preserve repeated/finalized observations as evidence rather than
  overwriting the original selection. No deletion of historical rows.
- Concurrent scanners must resolve a competing canonical-event insert as an
  idempotent already-consumed result, not abort unrelated batch work or create
  a second intent. Use database conflict handling scoped to the existing
  canonical identity and return only genuinely newly created events for intent
  creation. Preserve sequential dedup/NOT EXISTS fixes and R5 worker locking.

Required tests: >2*limit unconfirmed events preceding a later successfully
confirmed event; repeated passes must reach it. Finalized-only success, failed
confirmed, failed finalized, unknown success, delayed evidence and replay must
retain truthful status/source IDs. Two ordinary monitor passes interleaved on
the same new event plus independent events must complete without duplicate
trade, evidence replacement or lost batch progress. The former one-row positive
confirmation test is necessary but insufficient. Keep migrations additive and
role grants least-privilege; do not reset shared history to make them pass.

### 3. P4-R4 — Finish honest provider evidence at the existing seam

Severity HIGH. Classification SPEC_BLOCKING.
Surface: quote_jobs classification/call/record, Jupiter response validation,
probe/position evidence and report consumers of terminal state. Existing P4/P5
scheduler wiring and market/quote usage recorders must remain in place.

- Validate actual returned inputMint/outputMint and amount against the request;
  JupiterClient currently labels the returned object with caller mints, hiding
  raw mint disagreement. Check the raw provider fields, not just those labels.
- Nonempty list is not route validation: routePlan=[null] or invalid route
  members cannot assert a route/fill. Require structurally valid provider route
  entries and their mint/amount evidence under the existing quote contract.
  Do not demand new economic/semantic proof beyond that contract.
- Nonfinite or malformed supplied priceImpactPct must produce explicit
  QUOTE_FAILED/unusable evidence and no fill, not SUCCESS with None. Missing
  impact must remain explicit; never silently assert a known-safe value.
  Preserve genuine PRICE_IMPACT_EXCESSIVE and empty/no-route classifications.
- Retain available provider fee components with their actual feeMint and raw
  units. Do not always clear fee_estimate_raw, and never add heterogeneous
  currencies. A structured fee-component field is sufficient; unsupported
  aggregate stays unavailable with reason. Preserve the original raw response.
- Preserve sanitized structured error/capacity reason and actual HTTP status/
  provider code when supplied. Retain existing known no-route/429 mappings;
  recognized restriction/liquidity errors must not collapse into an invented
  success. Unknown provider codes remain QUOTE_FAILED, never guessed. Cover
  the frozen restricted-token real-adapter test; only contract-supported error
  codes may receive specific classifications.
- Capture provider requested_at INSIDE the scheduler's dispatched callable,
  immediately before the actual provider call; response time immediately after.
  Queue time is scheduling delay, not provider latency. Preserve retry/usage
  evidence honestly; do not relabel enqueue time as network send time.
- A scheduler drop before dispatch has no request/response timestamps or call
  latency. Persist its terminal decision time/reason separately. Therefore use
  explicit terminal state/time for claim, no-op, intent-finalization and report
  logic instead of assuming responded_at non-null is the only completion proof.
  HTTP429 is different: it DID make a request and keeps actual send/response
  evidence. Both remain missing capacity, not usable/failed trade performance.
- Adapt R5 generation-and-lock guards to terminal no-send states without
  weakening them. Preserve no-provider-call on any terminal replay. Legacy
  records must not have missing timing/reason fabricated or evidence rewritten.

Required tests through real JupiterClient + httpx.MockTransport: normal route,
empty route, [null]/malformed route, mismatched raw mints/notional, nonfinite and
malformed impact, known no-route/restriction, unknown error, supplied same-asset
and mixed-asset fees. Assert no position for unusable quote and exact preserved
raw/error evidence. Replace the current lenient-SUCCESS test oracle, which
contradicts remediation001. Controlled real scheduler: enqueue T, dispatch T+60,
response T+60.1 => request T+60, latency100ms, correct due-based delay. Queue
rejection => zero HTTP calls, null call times, terminal capacity reason, and
exact replay with zero further calls. HTTP429 => actual HTTP call/times retained.
Keep usage accounting and all closed stale-worker/position-race regressions.

### 4. P4-R6 — Correct current-phase report data, not future models

Severity MEDIUM. Classification SPEC_BLOCKING.
Surface: reports/daily.py and its focused tests; no Phase5 models required.

- Keep corrected promotions/demotions, new-wallet identities and best-effort
  notification wiring. Do not replace or broaden those completed fixes.
- Compute descriptive SHADOW sampled MFE/MAE from existing ShadowMarkOutcome
  returns for the corresponding ShadowPosition, using actual observation times
  within the stated reporting scope. Report sampled maxima/minima with counts
  and explicit sampled-not-continuous caveat. No marks means insufficient
  sample, not zero. Historical WalletPosition metrics, if retained, belong in
  a separately labeled historical section and must be grouped by quote asset
  and chosen history identity, never averaged across SOL/USDC or replays.
- low_completeness_wallets counts distinct wallets by the relevant latest
  known history at report end, not every historical LOW row. A current HIGH
  supersedes old LOW assessments for that current-state count; preserve all
  history rows. State scope and missing-history treatment explicitly.
- Report current-phase sample/outcome counts from actual prospective/shadow
  evidence: successful executable observations, unsellable/error observations,
  terminal missing-capacity observations and overdue unattempted observations
  separately. A total-attempt count may include missing attempts if explicitly
  named and broken down; never present it as usable executable sample size.
  Link terminal no-send capacity records from R4 without pretending a request
  occurred. Future hypothesis/graph/live fields remain NOT_IMPLEMENTED.

Required tests with hand-computed oracles: one shadow position with observed
returns +0.5/-0.2 => sampled max +0.5/min -0.2 and count2; no historical position
rows needed. Late/out-of-window marks cannot change an earlier report scope.
One wallet LOW->LOW->HIGH => current low count0, not2; a second current UNKNOWN
wallet counts1. Repeated reconstruction must not multiply distinct-wallet or
chosen-position samples. SOL/USDC historical amounts must never yield an
unlabeled 50.5 quote average. SUCCESS + NO_ROUTE + CAPACITY_MISS => explicit
three-class breakdown with usable sample excluding missing capacity; terminal
no-send vs overdue pending remain distinguishable. Preserve notifier failure
isolation and no external delivery during tests.

## Adversarial coverage and claim ledger

| Failure class | Audit method/result | Residual action |
|---|---|---|
| Split clocks, late initial scan, unavailable state | Actual SELECT oracle + production fallback: TESTED_FAIL; current-tier prefilter INSPECTED | R1 |
| Batch saturation, late/failed/finalized confirmation | Actual SELECT oracle TESTED_FAIL; finality filter/concurrent insert path INSPECTED | R3 |
| Malformed/nonfinite/wrong identity, provider errors | Real adapter/mock HTTP TESTED_FAIL; ordinary success/empty route confirmed | R4 |
| Queue wait/drop vs actual send | Real scheduler/control clock TESTED_FAIL | R4 |
| Worker stale lease/terminal concurrency/crash replay | Lock/generation/parent-serialization source and test assertions INSPECTED; PG execution BLOCKED locally | R5 closed, preserve |
| Duplicate history/mixed units/missing shadow samples | Actual report SELECT oracle TESTED_FAIL | R6 |
| Shared cleanup/failed setup/unrelated jobs | Isolated script/source and preservation tests INSPECTED; guard tests TESTED_PASS; PG execution builder-only | R7 closed, preserve |
| Instruction identity/evidence replay/phase limits | Fresh exact-SHA chain/diff and validators TESTED_PASS | Retain; refetch before write |
| Live/canary/paid/key operations, future scoring | NOT_APPLICABLE to authorized build; no such operation performed | Still prohibited |

| Builder claim | Independent conclusion | Effect |
|---|---|---|
| All seven findings fixed/all gates PASS/no limitations | FALSE for R1/R3/R4/R6 based on concrete probes above | Phase4 FAIL |
| All point-in-time fields bounded | NARROWER_THAN_CLAIMED: some bounds/refs correct, split clocks and fallback fail | R1 |
| Scanner drains and confirmation is complete | New-event sequential drain confirmed; confirmation/concurrent coverage incomplete | R3 |
| Strict quote identity and malformed-data handling | Notional/empty-route fixed; tests enshrine invalid-impact SUCCESS | R4 |
| Real scheduler and provider usage wired | CONFIRMED code; timestamp/reason semantics still false | R4 |
| Both competing terminal reads occur before either commit | NARROWER_THAN_CLAIMED: stale test releases A after B commits; source lock still prevents lost terminal writes; two-entry test genuinely races | R5 accepted, correct wording only |
| Report available facts now correct | Tier/new-wallet/notifier confirmed; shadow/history/unit/sample claims false | R6 |
| Demo isolated and old evidence preserved | CONFIRMED source, diff and meaningful builder tests; no auditor PG run | R7 accepted |
| 859 full tests/migration pass | Builder-recorded evidence, not independently rerun; offline660/type/lint/fixtures independently confirmed | Allowed environmental distinction |

Audit-of-audit completed: every prior finding and affected gate has a disposition;
PASS entries have direct source/test/probe support; all demonstrated blocker
families are included here; optional depth and future work are excluded. No
additional known blocker is being held for a later instruction.

## Validation, evidence and STOP

Run all newly added focused negative/positive tests, then:

    uv run pytest tests/integration/test_shadow_phase4_remediation_observation.py tests/integration/test_shadow_quote_jobs_provider_remediation.py tests/integration/test_shadow_phase4_concurrency_remediation.py tests/integration/test_daily_report_remediation.py tests/integration/test_replay_demo_isolation.py -q
    uv run pytest tests/unit/test_phase3_wallet_qualification.py tests/integration/test_wallet_acquisition.py tests/integration/test_phase3_wallet_qualification.py -q
    uv run pytest tests/integration/test_shadow_phase4.py tests/integration/test_daily_report.py tests/unit/test_telegram_notifier.py -q
    uv run pytest tests/integration/test_migrations.py -q
    uv run pytest tests/golden tests/replay tests/phase_1_5 -q
    uv run pytest -q
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy
    uv run alembic heads
    uv run argus fixtures validate-real-chain

Exercise any new migration on owned disposable databases using existing
approved test access; preserve populated history and replay terminal outcomes.
Do not reset/downgrade a shared database or request new credentials. Capture
actual commands, outputs, counts, warnings/skips, environment and final head.
Run a secret scan without printing secret values. Do not substitute prose
such as '(clean round-trip)' for captured migration output.

Create NEW evidence only:

- orchestration/checkpoints/phase_4_remediation_2.md
- orchestration/bundles/phase_4_remediation_2.txt
- Any regenerated demo output under orchestration/phase_4_remediation_2/;
  keep phase_4 and phase_4_remediation_1 artifacts unchanged. Adjust the demo's
  destination for this new run before invoking it; never overwrite old evidence.

Checkpoint must include R1/R3/R4/R6 requirement-to-evidence closure rows, retained
R2/R5/R7 regression status, precise limitation/deferral statements, test oracles,
security state, actual UTC timestamp, exact opening/ending markers and STOP.
Bundle embeds its exact bytes and full command evidence. Update BUILD_STATE
and DECISION_LOG truthfully without self-approval; last approved phase stays3.
Handoff must identify a new ID, this exact instruction ID and real run commit.
Every builder commit, including evidence/hash-fill, MUST end in the sole exact
terminal trailer below with nothing after it:

    ARGUS-INSTRUCTION-ID: argus-phase-4-remediation-002

Environmental deferrals remain LIVE_HELIUS_RPC_VALIDATION,
LIVE_HELIUS_WSS_VALIDATION, PG17_COMPOSE_VALIDATION, BQ_PUBLIC_DATASET_ACCESS.
Human/operator owns provision of an approved environment; builder captures the
documented real RPC/WSS checks and PG17 make bootstrap && make up / migrations /
tests there when separately authorized. Closure requires recorded actual
environment/results and orchestrator review before live readiness, not before
this code remediation can pass. No real Jupiter/DexScreener/Telegram call is
required here. Replay injection remains allowed; accepted one-wallet Phase3
sample limitation remains non-blocking. Honest environment limits never justify
fabricated PASS and never create a new software acceptance gate.

No threshold relaxation, retuning, mainnet trade, canary, signing/key/seed access,
credential entry/disclosure, paid-provider upgrade/use, live arming, evidence
rewrite or phase skip. No external Telegram send during this work. Additive
schema changes are authorized only for these frozen corrections; no deletion
of existing evidence. STOP after one consolidated submission. Only independent
orchestrator approval may authorize Phase 5.
