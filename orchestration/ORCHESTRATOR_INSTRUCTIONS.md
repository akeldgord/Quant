# ARGUS Orchestrator Instructions

OWNER: ARGUS ORCHESTRATOR. The implementation agent must not modify this file.
MASTER_SPEC.md remains authoritative. Execute only the ACTIVE instruction.

INSTRUCTION_ID: argus-phase-4-remediation-001
ISSUED_AT: 2026-09-01T14:18:33Z
TARGET_COMMIT: d95a629985668a0ba73795d3ad8daeb5534ce855
AUTHORIZED_ACTION: CLOSE_CONSOLIDATED_FROZEN_PHASE_4_FINDINGS
AUTHORIZED_PHASE: 4
APPROVES_PHASE: NONE
STATUS: ACTIVE

## Disposition and scope lock

AUDIT_ID: argus-phase-4-audit-001
DISPOSITION: FAIL_REMEDIATION_REQUIRED

Phase 4 is not approved. Phase 5 remains blocked. Execute ALL seven findings
below as ONE remediation batch, then hand off and STOP. This is the first
Phase 4 remediation, not another Phase 3 round. Phases 0/1/1.5/2/3 retain their
recorded approvals; all closed Phase 3 findings stay closed absent regression.
No retuning, extra review gates or optional hardening is authorized as a blocker.

Canonical gate: MASTER_SPEC.md as frozen by argus-phase-4-001 at instruction
commit 379c5bc886abe7e99cdd3360fe3e71925ac932ce, plus that instruction's explicit
pre-implementation decisions. MASTER_SPEC SHA-256 remains unchanged:
41f7242c288feec709b1ed72e62c74a1dc5e3b3cd9ad01e9b6e28373d9d14011.
Applicable sections: 19-20, 44-48, 84, 93-94 and Phase 4; inherited immutable
evidence, provider priority/accounting and authorization rules. No Phase 5
copyability/forward-alpha model, graph build or live execution is required.

## Immutable audit and independent evidence

Repository akeldgord/Quant; branch claude/argus-folder-setup-77ahrk.
Audit target is the header target; its direct parent/implementation commit is
92bcc6a2d9b77497d077c671df9a5fb6d011332a. Diff base is 379c5bc886abe7e99cdd3360fe3e71925ac932ce.
Matching handoff handoff-0025-phase-4, exact instruction argus-phase-4-001;
checkpoint orchestration/checkpoints/phase_4.md and bundle
orchestration/bundles/phase_4.txt; demo and JSON under orchestration/phase_4/.

Fresh GitHub HEAD/file reads and a clean exact-SHA checkout fetched from GitHub
establish the submission. Both builder commits have the exact sole terminal
instruction trailer. Spec, protocol and orchestrator instruction are unchanged.
Phase 3 approval was correctly applied to BUILD_STATE; no Phase 4 self-approval.
Canonical files, checkpoint/bundle, complete affected service/CLI/schema paths,
test assertions, raw results and replay script/results were inspected. Actual
production checkpoint/bundle validators pass, including exact embedded bytes.

Auditor independently executed:

    uv run pytest tests/unit tests/golden tests/phase_1_5 -q
    # 660 passed in 26.41s, exit 0
    uv run ruff check .
    # All checks passed, exit 0
    uv run ruff format --check .
    # 245 locally discoverable files already formatted, exit 0
    uv run mypy
    # 128 source files clean, exit 0
    uv run argus fixtures validate-real-chain
    # all 12 authentic fixtures pass, exit 0

Temporary independent read-only probes exercised the production functions with
minimal session adapters; HTTP behavior used httpx.MockTransport plus the REAL
JupiterClient. They made no network calls and changed no database. Results:

1. Event first-seen T, first construction T+2h, score created/as-of T+1h:
   _create_prospective_event takes that future score 95. Score SQL has no as-of
   or created-at cutoff. A frozen row can be frozen with the wrong initial data.
2. first_seen T, monitoring/intent creation T+60s: nominal +1s probe due T+61s,
   not T+1s. The submitted demo corroborates this: first seen 09:22:19, quote
   requested 09:22:23.7, nominal 1s, recorded scheduling delay only 0.7s instead
   of 3.7s. Request/response latency itself is correctly 100ms.
3. Scanner limit=1 with first eligible row already processed: returns zero;
   candidate SQL applies LIMIT without excluding existing prospective rows.
4. Real JupiterClient with mocked HTTP 400 COULD_NOT_FIND_ANY_ROUTE becomes
   QUOTE_FAILED; actual scheduler RequestDropped likewise becomes QUOTE_FAILED,
   not missing capacity. Positive output with routePlan=[] becomes SUCCESS and
   route_present=True in _classify_quote.
5. Two interleaved terminal transactions for the same reverse probe both read
   unresponded state and both record different outputs (200 and 100). No claim
   token/owner test, terminal row lock or conditional update protects either.
   This adapter proves code interleaving, not a PostgreSQL execution claim.
6. Report transitions S->A, DISCOVERED->WATCH, PROBATION->B produce one promotion
   and two demotions, rather than two promotions and one demotion. The query
   reads only to_tier, so cannot distinguish the actual direction.
7. Calling demo cleanup with an address mapped to a pre-existing wallet emits
   ten DELETE statements and commits; no run ownership check exists. No actual
   deletion was executed during audit. The script calls this cleanup in finally
   even if its attempt to insert that already-existing wallet failed.

Builder-only results inspected, NOT independently rerun against PostgreSQL:
808 full tests, 16 new Phase 4/notification/report tests, acquisition 36,
qualification 17, migration 17, golden/replay/phase_1_5 112; raw commands and
0016 downgrade/upgrade are present. This auditor has no configured approved DB
credential; none requested or entered. That environmental limitation is not a
blocker and does not excuse the independently demonstrated code defects.

## Complete frozen requirement-to-evidence matrix

| Obligation | Code/test/evidence assessment | Status |
|---|---|---|
| Frozen first-seen, distinct leader/confirmation time | Existing rows retain first_seen, but late confirmation is never revisited; delayed initial snapshot uses future state | Partial; P4-R1/R3 |
| Point-in-time score/tier/token/position/cluster context | Latest/current values at scan time, no first-seen bounds; test only changes score AFTER event already exists | FAIL P4-R1 |
| Scheduled probes anchored to observation; actual latency | Request/response measured correctly; target_due uses intent creation now instead of event.first_seen | FAIL P4-R2; retain latency measurement |
| Tracked-wallet monitoring continues beyond a batch | Exclusion occurs after SQL LIMIT; original batch permanently blocks later swaps | FAIL P4-R3 |
| Separate mark/executable evidence | Mark price/return distinct from raw reverse quote; unsellable rows and missing prices representable | PASS structure; provider mapping P4-R4 |
| Unsellable outcomes preserved through production path | Custom fake-only errors work; actual HTTP errors collapse; route availability invented from positive output | FAIL P4-R4 |
| Capacity miss is missing data; shared priority/accounting | Shadow CLI bypasses PriorityScheduler; RequestDropped not handled; DexScreener calls omit usage recorder | FAIL P4-R4 |
| Stream gaps block eligible live state | Existing Phase 1 degraded state untouched; Phase 4 adds no live entry/arming path | PASS inherited, do not reopen |
| Restart/replay prevents duplicate trade/replacement evidence | Sequential stale-claim replay test passes; overlapping terminal writes unprotected, including mark jobs | FAIL P4-R5 |
| Telegram integration and daily report | Safe notifier class exists but no ordinary producer invokes it; real report counts mislabeled and available required fields replaced with NOT_IMPLEMENTED | FAIL P4-R6 |
| Complete REAL/REPLAY lifecycle | Dependency injection and replay substitution accepted; lifecycle services reached; demo shares/destructively cleans ordinary DB | FAIL P4-R7 and timing issue, not a demand for real data |
| Decimal/raw units, separated assets, safe migrations | New tables/constraints and separate quote/mark families; no destructive upgrade of earlier tables | PASS inspected; no unrelated redesign |
| Fresh evidence, trailers, protected files and live prohibitions | Valid immutable submission; fresh bundle; no real signing/trading path | PASS |

## Accepted limitations / non-blocking backlog

- REPLAY service-level dependency injection IS acceptable. No real Jupiter,
  Helius, DexScreener or Telegram call is required for acceptance. Do not add a
  provider credential, CLI fake-mode flag or prospective profitability gate.
- The disclosed SWAP_SIMPLE/confidence interesting-trade approximation and
  SOL/wrapped-SOL buy universe are HARDENING_BACKLOG for this shadow-only gate,
  provided their scope remains explicit and no live eligibility claim is made.
  Full semantic-proof persistence and expansion to other quote assets do not
  block approval. Do not relabel them as full is_copy_eligible enforcement.
- Missing graph/hypothesis/live-execution features remain explicitly unavailable;
  do not pull later phases forward. Nullable unavailable market marks are valid.
- Phase 3's accepted one-wallet sample limitation and environmental deferrals
  remain unchanged. No forced A/S wallets and no score/eligibility retuning.
- Preserve already-proven checkpoint formatting, real-fixture parsing, fake
  notifier secret guard, separate outcome families and request/response timing.

## One ordered remediation batch

First run git status, git pull --ff-only, git log -5 and read canonical files in
PROTOCOL order. Verify this instruction is one instruction-only commit whose
direct parent is the header target. STOP on unexpected movement, protected-file
changes or overlapping dirty state. Implement P4-R7 isolation first, then R1-R3
observation/lifecycle, R4-R5 provider/jobs, R6 reporting/notifications. Additive
schema changes are authorized when needed for these existing obligations; no
rewriting/deleting past evidence or changes to frozen scores/thresholds.

### P4-R1 — Future information in the initial prospective snapshot

Classification: SAFETY_OR_INTEGRITY_BLOCKING. Severity HIGH.
Authority: MASTER_SPEC section 44; argus-phase-4-001 task 2 and frozen
point-in-time score/context gate. Surface: shadow/prospective.py helpers and
scanner eligibility, with necessary snapshot references/models/tests.

Root cause: first_seen_at comes from the old swap, but score is latest by
created_at, tier is wallets.current_tier, token snapshot is latest without a
cutoff, position context sums all OPEN historical snapshots, and cluster cutoff
is scan now. A wallet promoted after a trade can retrospectively qualify it;
later position/market/cluster observations can enter an earlier signal.

Required behavior: use event.first_seen_at as the immutable knowledge cutoff.
Select only score/tier/market/position/cluster evidence genuinely available by
that cutoff (both effective/as-of and recorded/observed time where represented).
Resolve tier from immutable tier history, not current_tier. Preserve selected
source identities so the snapshot can be checked. Do not sum superseded position
snapshot copies as separate open positions. If state did not exist at T, record
unavailable; do not use later state to create earlier eligibility. Scanner may
discover old rows later but cannot claim they were qualifying prospective data
at T based on a later promotion. Preserve original snapshots after creation.

Tests before/with fix: first scan is delayed until AFTER a rescore, promotion,
new token price, new position snapshot and cluster change. Assert every snapshot
and selection decision uses only data known at first_seen, not scan time. Test
no pre-T score/tier evidence, equality at T, future rows already in DB, duplicate
OPEN snapshots and exact replay after later updates. Existing after-creation
immutability test stays passing; it alone does not cover this defect.

### P4-R2 — Wrong time origin for delay probes

Classification: SAFETY_OR_INTEGRITY_BLOCKING. Severity HIGH.
Authority: sections 45-46; phase-4-001 task 3 and quote-timing gate.
Surface: intents.create_shadow_intent_for_event/_schedule_entry_delay_probes,
quote job scheduling metrics, demo and assertions.

Root cause: observed_at=now is passed when creating probes; now is signal
processing time, not ARGUS first observation. Use event.first_seen_at for all
entry target due times. Persist actual creation time separately; never backdate
row creation. Compute scheduling delay from actual request minus that fixed due
time; retain actual request/response latency. Delayed processing/confirmation
cannot reset the origin. An overdue attempt is honestly late or explicitly
missing; no synthetic timely fill. Do not rewrite old results to hide the bug.

Tests: first_seen T, consumer T+60s, nominal1s due T+1s; request T+62.7s records
61.7s scheduling delay and separate actual call latency. Include late
confirmation and replay. Regenerate a NEW labeled demo showing its first_seen,
due, actual request, response and correct arithmetic for every displayed probe.

### P4-R3 — Consumer stalls; confirmation and replay lifecycle incomplete

Classification: SPEC_BLOCKING. Severity HIGH.
Authority: Phase 4 tracked-wallet monitoring/confirmation handling; sections
19-20/44 and frozen duplicate/replay gate. Surface: prospective.py, monitor.py,
prospective event/confirmation persistence and associated tests.

Root cause: SQL limits oldest eligible swaps before excluding processed IDs.
Once the first limit rows have prospective events, every later pass returns no
new work. confirmation_time is read once; an event created processed-only is
never revisited when a real confirmation arrives. Unique swap_id alone also
allows another parser artifact of the same canonical wallet transaction to
become a second prospective trade.

Required behavior: exclude consumed economic events in SQL BEFORE ordering and
limit, with stable pagination/order. Repeated bounded scans must drain all
eligible work without starvation. Preserve chosen parser artifact but identify
one prospective economic event per canonical wallet transaction; reparse must
not silently create a second shadow trade. Record later confirmation evidence
via an immutable linked observation/update history without replacing the frozen
first_seen/score/context. Do not invent confirmation success or promote failed
source transactions to successful confirmations. This is not a new ban on
processed-only latency research and not a change to live commitment policy.

Tests: >2*limit eligible rows, repeated passes produce each once including after
the first full batch; concurrent/repeated passes and new rows after saturation;
processed event then confirmed/finalized observation in a later pass retains
first_seen and frozen snapshot and exposes the real confirmation exactly once;
two parser artifacts for one raw event do not create duplicate shadow trades.

### P4-R4 — Production provider failures/capacity do not reach honest outcomes

Classification: SPEC_BLOCKING. Severity HIGH.
Authority: sections 45-48 and inherited provider priority/accounting; task 3 and
frozen unsellable/capacity gates. Surface: shadow quote/mark jobs, production CLI
provider construction, existing scheduler/adapter integration, error mapping.

Root cause: only new ShadowQuoteError subclasses map to specific outcomes, but
ordinary JupiterClient raises HTTP/contract errors and PriorityScheduler raises
RequestDropped. CLI calls providers directly with no scheduler. Market clients
omit SqlUsageRecorder. _classify_quote invents route_present=True for any
positive output, including explicit empty route, and fee_estimate is always
None regardless of supplied evidence. Fake-provider tests bypass these seams.

Required behavior: wire entry P4_prospective_copyability_quote and reverse
P5_shadow_exit_quote through existing shared priority/capacity machinery, retain
its reason on rejection as PROVIDER_CAPACITY_MISS/missing observation. Do not
record a capacity skip as a failed trade or claim a provider request occurred
when none did. Preserve actual sent request/response timing and provider usage,
including market snapshot calls. Use the real adapter response/error contract
to distinguish known no-route/liquidity/restriction failures; unknown failures
remain QUOTE_FAILED, never guessed. Preserve sanitized reason and evidence.
Route presence must come from actual route evidence; empty/malformed routes
cannot create SUCCESS/fill. Check quote request identity/notional against the
returned quote before using it. Nonfinite/malformed impact or invalid outputs
must be explicit failed/unusable evidence, not crash a batch or fabricate success.
Retain available fee estimates with their asset/unit; absent estimates are
explicitly unavailable, never fabricated or blindly summed across currencies.
Use bounded adapter changes only; do not redesign Phase 1 parsing or providers.

Tests through real JupiterClient and mocked HTTP transport (no live access):
success with real-format route; HTTP no-route, restricted token, rate/capacity
failure and ordinary unknown failure; empty route/positive output, wrong quote
notional, malformed/nonfinite data. Exercise real scheduler drop under load and
prove missing reason, no outbound call and priority behavior. Check market and
quote usage accounting. Existing synthetic unsellable cases remain regressions,
but are not a substitute for these real adapter/runtime seam tests.

### P4-R5 — Overlapping workers can replace terminal evidence

Classification: SAFETY_OR_INTEGRITY_BLOCKING. Severity HIGH.
Authority: section 84; task 5 and frozen restart/no replacement-evidence gate.
Surface: quote_jobs and mark_jobs claim/execute/record paths and parent position
creation. No changes to unrelated earlier workers are required.

Root cause: claims expire after 30s, while provider retries or a batch can last
longer; terminal session.get is unlocked, checks only responded/actual time and
ignores claim owner/generation. Two terminal transactions can both read pending
and overwrite the same row. Two entry probes can race to create the unique
position; a uniqueness exception alone is not a complete recovery protocol.

Required behavior: use an ownership/attempt generation tied to each claim and
verify it atomically at terminal write. A row lock or conditional update must
allow only the current owned uncompleted attempt to publish terminal state.
A superseded worker cannot replace another response. Serialize/idempotently
resolve first position creation for one intent and its follow-up schedule.
Do not overwrite an already completed probe/mark timestamp, output or price.
Avoid needless provider call on an already-terminal invocation. Do not hold
database transactions across network I/O. Preserve abandoned-attempt/late-call
facts honestly; do not turn recovery into a false timely observation.

Tests: slow A exceeds lease, B reclaims, interleave BOTH reads before either
terminal commit; stale A must not publish over B. Repeat for mark jobs and two
successful entry probes for one intent; exactly one position/follow-up schedule,
no unhandled uniqueness failure or lost completed evidence. Kill after claim,
after provider response and around terminal commit; restart then exact replay
must not duplicate trade or replace evidence. Include a provider-call counter
in the already-completed no-op test (the current test catches the provider's
'should never be called' exception, masking that it WAS called).

### P4-R6 — Available report facts miscounted; notifier disconnected

Classification: SPEC_BLOCKING. Severity MEDIUM.
Authority: sections 93-94; task 6 and complete Phase 4 deliverables gate.
Surface: reports/daily.py, normal shadow/report producers and notification seam.

Root cause: promotions/demotions use only destination tier; new_wallets counts
discovery events rather than newly discovered wallet identities. Available
Phase 3 history and Phase 4 missing-probe/sample facts are replaced with
NOT_IMPLEMENTED. The only notifier producer is the demonstration's manual call;
normal shadow/report services never invoke the notifier.

Required behavior: compute lifecycle direction from from_tier/to_tier semantics
(S->A is not a promotion; DISCOVERED->WATCH and PROBATION->B are not demotions).
Count actual new wallets, not repeated discovery events. Populate required
current-phase facts from existing history/quote/mark evidence: low/unknown
completeness, missing observations/provider gaps, sample counts and descriptive
MFE/MAE where sampled data supports them. Label sampled extrema/insufficient data
honestly; do not invent continuous market coverage. Capacity misses must not be
reported as completed usable executable observations without their missing-data
classification. Later hypothesis/graph/live features stay NOT_IMPLEMENTED.
Connect existing shadow-event/daily-summary producers to an injectable notifier
with disabled/no-op default and FakeTelegramTransport in tests/demo. No external
send, credentials or Telegram control actions. Future live event sources remain
out of scope. Notification failure must not lose or rewrite the trading-research
record; no new exactly-once Telegram delivery infrastructure is required.

Tests: explicit transition directions above, multiple discoveries for one wallet,
low-completeness evidence, successful/unsellable/capacity-missing outcomes and
available sampled marks. Verify ordinary shadow/report service invokes the fake
transport with actual committed facts and fails safely if transport fails;
manual demo notifier calls alone are insufficient. Keep existing secret and
notification-only tests passing.

### P4-R7 — Replay demo can delete unrelated history and consume unrelated jobs

Classification: SAFETY_OR_INTEGRITY_BLOCKING. Severity CRITICAL.
Authority: inherited immutable evidence and explicit prohibition on evidence
rewrite; tasks 5/evidence preservation and safe REPLAY demonstration.
Surface: scripts/argus_phase4_replay_demo.py and demo fixtures/environment.

Root cause: script uses the shared configured database, uses a real fixture
wallet address, then finally looks up that address and deletes all its records.
If wallet insertion fails because that wallet already exists, finally can delete
the PRE-EXISTING row/history. Global due-job calls can also consume another
wallet's work using fake quotes. 'Deletes only rows it created' is false. Audit
found a concrete destructive code path, not proof that prior data was lost.

Required behavior: move the demo onto the existing isolated disposable-database
test pattern; refuse ordinary/shared DB targets. Use only disposable state owned
by this demo, not address-based cleanup against shared state. Provider/job scans
must have no access to unrelated queued work. Preserve the authentic raw fixture
as demo evidence; synthetic quotes/context stay clearly replay-labeled. Failure
before setup, mid-setup, during demo and during cleanup must leave pre-existing
wallets/history/jobs byte-for-byte unchanged. Do not delete existing evidence to
prepare the new run. An additive migration is allowed; destructive migration
reset/rollback of real or shared history is not.

Tests: pre-existing same-address wallet with scores/chain/shadow history, plus
unrelated due quote/mark jobs; inject setup failure and successful demo. Verify
none are changed or consumed. Verify shared-target refusal before writes/network.
Run normal replay only in owned disposable environment using existing approved
test access; no new credential entry, provider upgrade or external action.

## Claims and adversarial coverage closeout

- 'All ten gates pass' is rejected for R1-R7, not because the environment lacks
  real quotes. Honest replay substitution is accepted.
- Snapshot immutability after creation, raw/Decimal structures, basic sequential
  restart and synthetic unsellable handling are confirmed but narrower than
  full point-in-time/production error/concurrent recovery claims.
- Full-suite count 808 is builder raw evidence, not an independent DB run. Fresh
  offline 660-test results, type/lint/fixtures and negative probes are independent.
- Malformed/provider/capacity inputs, late observation, replay, batch boundary,
  stale claim/concurrency, destructive cleanup and reporting correctness have
  direct tests/probes or source proof above. Live execution/canary/key access and
  future-phase models are NOT_APPLICABLE to this gate, not newly demanded tests.
- No evidence claims actual data loss. Do not rewrite prior checkpoints to hide
  defects; append corrections and retain the original evidence. Use actual UTC
  capture times in the new handoff (the old hardcoded 14:35 timestamp was ahead
  of this audit's clock; not a separate phase blocker).
- Audit-of-audit complete: all frozen rows reviewed, each blocker anchored to
  pre-build authority with root cause, full known family and closure tests;
  optional depth separated. No further blocker is intentionally held for later.

## Validation, handoff and STOP

Add focused tests for ALL seven findings and run them plus:

    uv run pytest tests/unit/test_phase3_wallet_qualification.py -q
    uv run pytest tests/integration/test_wallet_acquisition.py -q
    uv run pytest tests/integration/test_phase3_wallet_qualification.py -q
    uv run pytest tests/integration/test_shadow_phase4.py tests/integration/test_daily_report.py tests/unit/test_telegram_notifier.py -q
    uv run pytest tests/integration/test_migrations.py -q
    uv run pytest tests/golden tests/replay tests/phase_1_5 -q
    uv run pytest -q
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy
    uv run alembic current
    uv run argus fixtures validate-real-chain

Run the corrected isolated demo, ordinary service/fake-notification/report path,
non-destructive migration preservation checks and changed-file secret scan.
Record exact commands/raw output/exit codes, skips, environment, resulting
commit, seven-finding closure matrix and replay label. Never print secrets.

Create fresh files only:
orchestration/checkpoints/phase_4_remediation_1.md
orchestration/bundles/phase_4_remediation_1.txt
Place new demo evidence in a new remediation-specific path, leaving the original
phase_4 evidence intact. Bundle must contain exact checkpoint bytes and valid
terminal markers. Update BUILD_STATE and append DECISION_LOG without self-approval.
Handoff must match argus-phase-4-remediation-001 exactly, name fresh files and a
real in-run commit, and state clean/pushed awaiting orchestrator review.

Every builder commit including hash-fill must end with this sole real trailer,
with nothing after it:

ARGUS-INSTRUCTION-ID: argus-phase-4-remediation-001

Verify production instruction/checkpoint/bundle validators and clean remote/local
equality, then STOP. Once this complete frozen packet passes with regressions,
approve Phase 4 and authorize only the immediate next permitted phase; do not
invent new optional gates.

LIVE_HELIUS_RPC_VALIDATION, LIVE_HELIUS_WSS_VALIDATION, PG17_COMPOSE_VALIDATION,
BQ_PUBLIC_DATASET_ACCESS remain deferred under existing owner/procedures and
closure gates. PG16 functional results are not PG17 validation. No credentials
or external provider validation requested here. No mainnet trading/canary,
signing/private-key/seed access, credential entry/disclosure, paid-provider use,
live arming, threshold relaxation, external Telegram sends, evidence rewrite or
phase skipping. All live flags remain false. Automation/build are not complete.
