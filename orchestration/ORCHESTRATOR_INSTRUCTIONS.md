# ARGUS Orchestrator Instructions

OWNER: ARGUS ORCHESTRATOR. The implementation agent must not modify this file.
MASTER_SPEC.md remains authoritative. Execute only the ACTIVE instruction.

INSTRUCTION_ID: argus-phase-4-001
ISSUED_AT: 2026-09-01T12:25:21Z
TARGET_COMMIT: efb8837f01ab6aaa451c6ee3263e4effa389c4e6
AUTHORIZED_ACTION: IMPLEMENT_COMPLETE_PHASE_4_PROSPECTIVE_MONITORING_AND_SHADOW_COPYING
AUTHORIZED_PHASE: 4
APPROVES_PHASE: 3
STATUS: ACTIVE

## Phase 3 approval and immediate Phase 4 authorization

AUDIT_ID: argus-phase-3-remediation-audit-004
DISPOSITION: PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION

Phase 3 is independently approved at the exact target above. P3-R2a and
P3-R2b are CLOSED to the frozen fourth-remediation gate. All previously closed
Phase 3 findings remain closed: P3-R1, P3-R3, P3-R4, P3-R5, P3-R6a, P3-R6b,
P3-R7, E1 and the string-boolean defect. No current SPEC_BLOCKING or
SAFETY_OR_INTEGRITY_BLOCKING finding remains. Phases 0/1/1.5/2 retain their
existing approvals. Phase 4 is authorized now as ONE complete implementation
batch, ending at its explicit STOP/checkpoint. Phase 5 remains unauthorized.

The honest one-wallet PHASE_3_CANDIDATE_SAMPLE_BLOCKED outcome remains the
previously accepted, non-blocking limitation. It is not five-wallet evidence,
not validated alpha, and not authority to retune scores or relax eligibility.
Do not reopen this accepted outcome or hunt for more optional Phase 3 hardening.

## Immutable audit record

Repository: akeldgord/Quant.
Branch: claude/argus-folder-setup-77ahrk.
Audited remote handoff commit: efb8837f01ab6aaa451c6ee3263e4effa389c4e6.
Direct parent / implementation commit: 135eede039a67843a30b11f93c3ac08508c84f19.
Pre-work instruction commit: 2cbdb81ca917eac877a9f9f68dfbffc57d69998b.
Matching instruction: argus-phase-3-remediation-004.
Matching handoff: handoff-0024-phase-3-remediation-4.
Checkpoint: orchestration/checkpoints/phase_3_remediation_4.md.
Bundle: orchestration/bundles/phase_3_remediation_4.txt.
Canonical MASTER_SPEC.md SHA-256, unchanged from the frozen Phase 3 contract:
41f7242c288feec709b1ed72e62c74a1dc5e3b3cd9ad01e9b6e28373d9d14011.

Fresh GitHub HEAD and handoff were reconciled with a clean exact-SHA checkout
fetched directly from GitHub. Both builder commits form a linear chain and
carry the sole terminal argus-phase-3-remediation-004 trailer. Protected spec,
protocol and instruction are unchanged. Evidence files are new; the exact
checkpoint is embedded in its bundle. Production checkpoint/bundle validators
pass. No self-approval, schema change or future-phase implementation was found.
Canonical state/decision records, instruction, handoff, checkpoint, raw bundle,
complete remediation diff and affected production/test paths were inspected.

### Complete remaining-requirement matrix

| Frozen requirement | Independent evidence | Result |
|---|---|---|
| P3-R2a: bind reconstruction to verified run's actual derived evidence | qualification_service loads verified manifest before SQL; genuine derived IDs constrain Swap query with wallet and as-of bounds; independent production-entry-point SQL probe confirms exact ID parameter and no swap query for empty set | PASS/CLOSED |
| Unrelated same-wallet rows cannot enter history, ledger or score | single selected set enters shared future-time filter, history and reconstruction; full service integration source asserts unrelated mint excluded and empty run yields UNKNOWN/zero positions; fresh raw PG16 results inspected | PASS |
| One parser artifact per raw event; changed evidence gives new immutable identity | producer signature deduplication, decoder duplicate-signature rejection, recorded selected artifact; bound swap IDs; artifact-rebinding service test preserves two historical identities and distinct position snapshots | PASS |
| P3-R2b: missing evidence/account keys and null genuine references fail closed | manifest_from_dict requires both keys and non-null string swap/version/build identity for genuine outcomes; independently rerun decoder tests | PASS/CLOSED |
| Conflicting walk statuses/fetch-failed COMPLETE/unsatisfied-boundary COMPLETE rejected | common _check_walk_internal_consistency and wallet/account status equality checks; independent decoder tests | PASS |
| Exact referenced raw/parsed evidence and wallet/artifact identity verified | loader resolves run and event, wallet/signature/hash and swap/event/artifact; authoritative run cutoff remains as-of bounded; producer records actual existing artifact; negative loader tests plus raw results inspected | PASS |
| Valid acquisition, parse/fetch/owner/hash/boundary failure semantics | producer/persist/load test sources and raw 36-test acquisition results; unchanged historical acquisition path | PASS |
| As-of, contamination, sample, scoring, windows, accounting, replay and immutable decision regressions | shared filtering/identity path retained; no ledger/scoring/migration changes; independently rerun unit/golden/phase_1_5 tests and inspected affected service/replay/migration test sources/results | Retain prior closures |
| Authentic sample fallback, prohibited operations and environmental limits | unchanged accepted sample report and explicit deferrals; no new provider calls or live code | Accepted |
| Fresh evidence, matching handoff, terminal trailers, protected files | exact Git objects and production evidence validators | PASS |

### Adversarial coverage and claim ledger

| Scenario / claim | Method and result |
|---|---|
| Named versus empty consumer evidence | Independent read-only session/SQL adapter exercised actual reconstruct_and_score_wallet entry point up to history assessment: named query includes exact bound UUID, wallet and as-of; empty set issues no swap query. TESTED_PASS. This is not represented as a database integration run. |
| Missing arrays, null derived/parser references, status disagreement, fetch/boundary conflicts, boolean/duplicate regressions | 15 production decoder tests independently pass; 21 database-backed tests explicitly deselected. TESTED_PASS. |
| Nonexistent/wrong-event/artifact references, producer preservation, unrelated rows and parser rebinding | Production implementation and meaningful negative/positive integration assertions inspected alongside fresh raw PG16 output. INSPECTED. |
| Full producer-to-score coverage claim | Proven by composed producer/persist/load tests and production consumer tests/wiring, not claimed as one independently executed end-to-end PostgreSQL test. Claim narrowed, non-blocking. |
| Unit/golden/phase_1_5 regression | Auditor executed 654 tests, all pass, exit 0. CONFIRMED for this scope, not a full-suite claim. |
| Full repository 792 / integration 128 / acquisition 36 / qualification 17 / migrations 17 / golden+replay+phase_1_5 112 | Builder raw command outputs inspected at this commit; tests and diff corroborate added cases. Not independently rerun against PostgreSQL. |
| Replay rerun | Auditor attempted tests/replay: 1 passed, 9 setup errors, exit 1, all nine due to missing ARGUS_DB_ADMIN_PASSWORD. Environmental inability, not a new product failure or request to enter credentials. |
| Ruff, format, mypy, authentic fixtures | Independently pass: ruff check; format check (222 locally discoverable files); mypy 112 source files; all 12 real-chain fixtures. Builder format count 221 is not substituted for the auditor count. |
| Restart/atomicity/immutable history | No migration or transaction-boundary change; existing replay and preservation sources/results inspected; prior accepted fixes retained. |
| Live/paid/secret/phase-skip control | Scoped diff and unchanged protected controls inspected; no new authority. |

Independent commands (all exit 0 except explicitly recorded replay setup errors):

    uv run pytest tests/unit tests/golden tests/phase_1_5 -q
    uv run pytest tests/integration/test_wallet_acquisition.py -k manifest_decode -q
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy
    uv run argus fixtures validate-real-chain
    uv run pytest tests/replay -q

The independent temporary consumer probe and production checkpoint/bundle
validators also passed. An initial probe fixture omitted its required slot;
that audit-harness typo was corrected before the successful probe, not treated
as a product finding. No audit-only source was committed to the project.

Audit-of-audit: both frozen remaining findings and every related acceptance
category have evidence above; closed findings were checked only for affected
regressions. Builder claims are separated from independent executions. No
optional hardening or future-phase criterion was promoted to a blocker.

## Environmental deferrals and operational limits

LIVE_HELIUS_RPC_VALIDATION, LIVE_HELIUS_WSS_VALIDATION,
PG17_COMPOSE_VALIDATION and BQ_PUBLIC_DATASET_ACCESS remain
DEFERRED_ENVIRONMENTAL_CHECK under their existing recorded procedures/owners.
They are not PASS and not reopened as Phase 3 blockers. PG16 proves the reported
functional tests, not PG17-specific behavior. This auditor had no configured
approved DB credential; none was requested, entered, printed or provisioned.

Closure remains the human/operator's authorized environment: execute the
existing provider probe/stream-reconciliation checks with approved access;
perform make bootstrap && make up (or equivalent) on actual postgres:17 and
rerun migrations/full tests; perform the existing BigQuery access check only
with separately authorized access/cost. Preserve exact results, versions and
limitations in the build state/decision log and a fresh checkpoint. No live
readiness claim before all applicable environmental checks and later explicit
safety/human gates close. No new real-provider validation is needed for the
Phase 4 REPLAY alternative below.

## Frozen Phase 4 contract (before implementation)

Authority: MASTER_SPEC.md at this instruction's target, same digest above,
particularly Phase 4 and sections 19-20, 44-48, 84, 93-94, with the inherited
point-in-time, Decimal/raw-unit, immutable-evidence, capacity and safety rules.
This instruction does not amend MASTER_SPEC. Required versus optional language
retains its original strength. No Phase 5 copyability/forward-value scoring,
Phase 6 graph expansion, live execution or additional approval gate is added.

Implement the ENTIRE Phase 4 in one batch:

1. Session/control check. Run git status, git pull --ff-only, git log -5;
   read canonical files in PROTOCOL order. Verify this instruction is one
   instruction-only commit directly on its target. STOP on unexpected movement,
   protected-file changes or conflicting dirty state. Apply this explicit Phase
   3 approval to BUILD_STATE (approved commit is the audited target; current
   phase becomes 4); append the decision log without rewriting history.

2. Wire tracked-wallet monitoring to the real Phase 1 fast/truth path, canonical
   parsed events and commitment observations. Add prospective events and shadow
   intent creation to production service/CLI wiring, not only test helpers.
   Preserve first-seen time, leader time and confirmation time as distinct data.
   Freeze the wallet score/tier, token, position-size, cluster and graph context
   available at that observation. Use immutable references/snapshots; no later
   reconstruction may replace the original signal values. Missing future-phase
   graph or prospective-only context is explicitly unavailable, never fabricated.
   A/S is not live authority; use honest shadow/research eligibility and preserve
   existing live thresholds rather than manufacturing qualified wallets.

3. Implement shadow intent/position lifecycle, entry quotes and scheduled delay
   probes through existing provider adapters and priority/accounting machinery.
   Delays are 1, 5, 15, 30, 60, 300 seconds from ARGUS observation (existing
   config/signals_v1.yaml), not retrospective leader time. Persist target/due,
   actual request/response, latency/scheduling delay, configured standardized
   small notional, expected output, route, price impact, fee estimate and result.
   One configurable small notional is sufficient; retain its asset/raw units
   and config identity. No historical chart may stand in for a contemporaneous
   quote. If confirmation, scheduling or capacity prevents a target probe,
   record the actual timing/missing reason; never backdate or call +2.7s '+1s'.
   Reuse existing confirmation policy and degraded-wallet gating; processed-only
   observations may remain latency-research evidence, not live permission.

4. Implement shadow fills/positions plus separate mark and executable outcome
   families. Where capacity permits, reverse executable quote targets are 5m,
   30m, 1h, 6h, 24h; preserve due/actual time, scheduling delay, route/output and
   price impact. Longer mark horizons 3d/7d retain the spec's optional strength.
   Outcomes must use consistent assets/units and retained evidence. Preserve
   NO_ROUTE, INSUFFICIENT_LIQUIDITY, PRICE_IMPACT_EXCESSIVE, QUOTE_FAILED and
   TOKEN_RESTRICTED as real outcomes, never dropped or replaced with mark P&L.
   Provider-capacity misses are explicit missing observations, not zero returns,
   failed trades or invented successful quotes. No Phase 5 score/model is required.

5. Persist lifecycle transitions/jobs/outcomes sufficiently for the existing
   crash/restart requirement: kill a shadow worker mid-job then resume without
   duplicate shadow trade or rewritten observation/snapshot/quote timestamps.
   Keep transaction ownership, replay/idempotency, migration preservation and
   established role boundaries. Stream gaps, unresolved reconciliation and clock
   discontinuity must not restore eligible live-entry state. Code remains
   disarmed; there is no trading or signing path in this authorization.

6. Add notification-only Telegram integration and argus report daily. Exercise
   Telegram through a fake transport; do not send external messages, request
   credentials, or add arming/risk/transaction commands. Reports follow section
   93: system/provider use, discovery/lifecycle, tracking/gaps/reconciliation,
   signals/confirmations, shadow trades/matured executable outcomes, live state,
   research sample/anomalies and data quality. Sections depending on later phases
   report unavailable/not implemented, not invented activity. Avoid causal claims;
   preserve mark/executable and replay/prospective distinctions prominently.

## Phase 4 acceptance and evidence (frozen now)

One complete REAL or REPLAY lifecycle is required. Use the allowed REPLAY route
in the current uncredentialed environment; label every demo/report concerned:

REPLAY — NOT PROSPECTIVE ALPHA EVIDENCE

Demonstrate through normal production wiring:
leader executes -> ARGUS observes -> source tx confirms -> shadow signal ->
entry quote -> shadow fill -> mark outcome -> reverse executable quote.
Use controlled clocks and deterministic providers; replayed quotes must never
be presented as actual historical executable opportunity or prospective samples.
Authentic existing transaction fixtures may ground parser inputs; fake quote
responses/timing remain explicitly simulation. Do not acquire new paid sources.

| Frozen gate | Required proof |
|---|---|
| Observation timestamp frozen | Duplicate/late replay and restart preserve original first-seen; leader and confirmation times remain distinct. |
| Point-in-time score/context frozen | Score/tier/context change after observation cannot alter the existing event's snapshot; future evidence cannot enter it. |
| Quote actual latency recorded | Controlled +2.7s request for nominal +1s target records actual timestamps/delay, not a false +1s observation. |
| Executable return distinct from mark | Same position with positive mark and unavailable/adverse reverse quote retains distinct outcomes. |
| Unsellable state preserved | Parameterized no-route/liquidity/impact/quote-failure/restricted cases remain visible in stored outcomes/reports. |
| Provider-capacity miss is missing data | Exhausted capacity records missing probe and reason without fabricated fill/return; priority/accounting regressions remain passing. |
| Stream gaps block eligible live state | Disconnect/restart/reconciliation gap and clock discontinuity remain degraded/disarmed until existing recovery conditions hold; no live action. |
| Complete phase deliverables/lifecycle | Integrated production-entry-point REPLAY demonstration covers all eight steps plus quote jobs, reverse/mark outcomes, fake notification and daily report. |
| Shadow restart requirement (section 84) | Interruption before/after durable shadow/job writes and restart/replay produces no duplicate shadow trade or replacement evidence. |
| Inherited integrity/security | Raw-unit/Decimal arithmetic, event/position units, idempotency, non-destructive migrations, prior-phase regression and secret/safe-default tests. |

Required validation: focused Phase 4 unit/integration/replay tests, existing
Phase 3 unit/acquisition/qualification tests, migrations, golden+replay+phase_1_5,
full pytest, ruff check/format, mypy, alembic head and fixture verification.
Use the established commands:

    uv run pytest tests/unit/test_phase3_wallet_qualification.py -q
    uv run pytest tests/integration/test_wallet_acquisition.py -q
    uv run pytest tests/integration/test_phase3_wallet_qualification.py -q
    uv run pytest tests/integration/test_migrations.py -q
    uv run pytest tests/golden tests/replay tests/phase_1_5 -q
    uv run pytest -q
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy
    uv run alembic current
    uv run argus fixtures validate-real-chain

Also record the exact new focused-test and production demo/report commands and
changed-file secret scan (never print secret values). Capture raw outputs, exit
status, counts, failures/skips and environment. Existing allowed environmental
deferrals remain honest deferrals, not an endless remediation trigger. Do not
claim a skipped or unavailable external check passed.

Create NEW checkpoint orchestration/checkpoints/phase_4.md and bundle
orchestration/bundles/phase_4.txt. Include requirement-to-evidence matrix, schema/
service/CLI path, actual replay lifecycle artifact references, failure/restart
results, raw validation output, limits and all security flags. Use standard
terminal checkpoint markers; bundle embeds exact checkpoint bytes. Update
BUILD_STATE and append DECISION_LOG; never rewrite previous evidence. Handoff
must identify this instruction exactly as argus-phase-4-001, new evidence paths,
real in-run commit and clean state, awaiting independent review.

Every builder commit, including documentation hash-fill, must end with the sole
real terminal trailer below, with nothing after it:

ARGUS-INSTRUCTION-ID: argus-phase-4-001

Commit/push, verify remote/local equality and evidence validators, then STOP.
Do not approve Phase 4 yourself. Independent audit is required before Phase 5.

## Absolute authorization boundary

No mainnet trading, canary, signing/private-key/seed access, credential entry or
disclosure, paid-provider use/upgrade, live arming, threshold relaxation,
evidence rewrite or phase skipping. Do not run real monitoring/quote services
or external Telegram delivery without separately established human authority.
This authorizes implementation and deterministic offline/replay validation of
Phase 4, not operational deployment or live readiness. All live safety flags
remain false. Batch all permitted Phase 4 work; add no intermediate review gate.
