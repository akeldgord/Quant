# ARGUS Orchestrator Instructions

**OWNER: ARGUS ORCHESTRATOR.** The implementation agent must not modify this
file. Execute only the ACTIVE instruction below. MASTER_SPEC.md remains
authoritative except where this instruction explicitly records an orchestrator
approval, clarification, or change-control decision.

---

INSTRUCTION_ID: argus-phase-2-001
ISSUED_AT: 2026-08-31T23:50:40Z
TARGET_COMMIT: c3148cc191de58ecab9b11cd05291cc8ffe45455
AUTHORIZED_ACTION: EXECUTE_PHASE_2_TOKEN_AND_WALLET_DISCOVERY_ONLY
AUTHORIZED_PHASE: 2
APPROVES_PHASE: 1.5
STATUS: ACTIVE

## Independent audit disposition

### Phase 0

Phase 0 remains orchestrator-approved:

`PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`

### Phase 1

Phase 1 remains orchestrator-approved at
`2fbc566af74832bc6523648f60ba8cb60d98eb31`:

`PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`

The following checks remain open and must be closed before live readiness, but
do not block Phase 2 research work:

- `LIVE_HELIUS_RPC_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK`
- `LIVE_HELIUS_WSS_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK`
- `PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK`
- `BQ_PUBLIC_DATASET_ACCESS = DEFERRED_ENVIRONMENTAL_CHECK`

### Phase 1.5

Phase 1.5 is independently approved at exact audited remote commit
`c3148cc191de58ecab9b11cd05291cc8ffe45455` with disposition:

`PASS_WITH_LIMITATIONS`

The historical-data conclusion remains exactly:

`HISTORICAL_DATA_PATH = PASS_WITH_LIMITATIONS`

The Phase 1.5 remediation-round-2 semantic gate passed independent audit. The
parser now requires an exact program-and-instruction-discriminator pair from
the same canonical instruction object; missing, malformed, cross-program,
non-swap, or log-only evidence fails closed. Independent adversarial probes
confirmed the old code fails open and the submitted code fails closed. The
auditor independently observed 102/102 scoped parser and Phase 1.5 tests pass,
Ruff clean, mypy clean, and all 12 real-chain fixtures validate. The auditor's
full suite produced 572 passes, 8 permitted environment skips, and 33 setup
errors solely because `ARGUS_DB_ADMIN_PASSWORD` is intentionally unavailable
in the audit environment; this matches the previously disclosed environmental
limitation and is not a code failure.

No `SPEC_BLOCKING` or `SAFETY_OR_INTEGRITY_BLOCKING` finding remains for Phase
1.5. Existing limitations remain non-blocking: incomplete historical
acquisition breadth, the disclosed 43-percent UNKNOWN rate for position events
that already fail closed, missing live-provider measurements, and incomplete
protocol/discriminator coverage. A minor evidence-formatting debt also remains:
the generated Phase 1.5 JSON exposes matched program, semantic label, and
discriminator but not the oracle's source-instruction location; the immutable
checkpoint and independent oracle do record those locations. This does not
alter the original Phase 1.5 gate or the independently proven safety behavior.

Phase 2 is authorized. Phase 3 and later phases remain blocked.

## Frozen Phase 2 gate

The canonical gate is MASTER_SPEC.md Phase 2 — TOKEN + WALLET DISCOVERY, plus
the already-applicable requirements listed below. This instruction clarifies
how to prove those existing requirements; it does not add a later-phase
production pipeline or live-readiness gate.

Phase 2 goal: create historical and prospective candidate-wallet discovery.

Required Phase 2 build surface:

1. token model;
2. token market snapshots;
3. point-in-time reference prices;
4. token lifecycle metadata;
5. bootstrap-token importer;
6. free-first historical provider adapters;
7. early-buyer extraction;
8. wallet discovery provenance;
9. prospective winner watcher;
10. winner milestone events;
11. automatic archaeology trigger;
12. wallet candidate creation;
13. negative-control schema support;
14. on-chain mint validation.

Required demonstration: at least one verified historical token, reporting its
mint, winner category, versioned baseline methodology, recovered early buyers,
data source, history limitations, and sanitized sample rows.

Required acceptance outcomes:

- token mint validated;
- lifecycle stage persisted;
- discovery provenance persisted;
- at least one historical archaeology run works;
- early-wallet extraction reproducible;
- source limitations explicit;
- discovery-trigger observations identifiable for later exclusion.

## Authority and inherited invariants

Implement the Phase 2 gate exactly. Preserve these existing requirements:

1. **Point-in-time truth and immutable raw evidence.** Store chain/provider
   observation time separately from chain time. Raw observations remain
   append-only. Never use future token outcomes, present-day supply, or revised
   market data to rewrite what was knowable at discovery time.
2. **Determinism and reproducibility.** Every meaningful discovery decision
   records algorithm version, config version/hash, git commit, input evidence
   references, timestamp, reason codes, and result. Stable ordering and
   idempotency are required for repeated archaeology and trigger delivery.
3. **Financial arithmetic.** Use raw integers for on-chain quantities and
   `Decimal` for canonical prices and USD values. Do not introduce binary-float
   canonical accounting.
4. **Token lifecycle.** Distinguish where observable: `TOKEN_CREATION`,
   `BONDING_CURVE`, `LAUNCHPAD_TRADING`, `MIGRATION`, `AMM_POOL`, and
   `MULTIPLE_POOLS`. Persist venue, venue program, pool/curve address, and
   lifecycle stage. Unknown or unrecoverable values remain explicit, not
   fabricated.
5. **Reference prices.** Persist at minimum SOL/USD and USDC/USD with source,
   observed_at, and confidence. Do not permanently assume USDC equals exactly
   USD 1. Historical calculations use point-in-time prices where practical.
6. **Historical market state.** Persist confidence for historical price,
   supply, liquidity, FDV, market cap, and pool state. Use `NULL` instead of
   false precision when contemporaneous evidence cannot be recovered.
7. **Winner definitions.** Initial research labels are `MAJOR_WINNER >= 10x`,
   `MONSTER >= 20x`, and `EXTREME >= 50x`. They are research labels, not trade
   signals. Persist winner-definition version, baseline timestamp/price/
   liquidity, peak price, and peak timestamp. The baseline methodology must use
   the earliest reliably tradable market state, not an untradeable zero-
   liquidity launch price.
8. **Discovery provenance.** Every `wallet_discovery_event` records wallet,
   discovered_at, discovery channel, nullable trigger token/wallet/event,
   trigger reason, and algorithm version. Historical winner archaeology and
   prospective winner archaeology must remain distinguishable.
9. **Anti-survivorship support.** Discovery-triggering token/event rows must be
   retained and mechanically identifiable for later qualification exclusion as
   `DISCOVERY_CONTAMINATION`; Phase 2 does not implement Phase 3 scoring. The
   schema must also support negative-control archaeology without claiming that
   full negative-control research is complete in Phase 2.
10. **Early buyers.** Attempt to recover the first 100 distinct meaningful net
    buyers and preserve at least the earliest 50 useful candidates if
    recoverable. Do not invent unavailable buyers. Record the fields required
    by MASTER_SPEC section 33, including ordering, venue, lifecycle stage,
    point-in-time entry state/confidence, token age, raw amount, and USD
    estimate where supportable. Tag possible deployer/insider/bundler/funder-
    related/bot status; do not automatically delete such wallets.
11. **Provider boundaries and cost.** Reuse typed provider interfaces and the
    central priority/cost accounting already built. Begin with free sources.
    No paid archival path may be enabled silently. Provider gaps, truncation,
    pagination limits, and completeness limits must be explicit.
12. **Research/custody separation.** No research process may access signing
    material. This phase creates no trade intent, order, transaction, or live
    execution path.

## Mandatory session start and change control

Before changing code:

1. Run `git status --porcelain`, `git pull --ff-only`, and
   `git log -5 --oneline`.
2. Read, in exact order:
   - `MASTER_SPEC.md`
   - `docs/BUILD_STATE.md`
   - `docs/DECISION_LOG.md`
   - `orchestration/PROTOCOL.md`
   - `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`
   - `orchestration/AGENT_HANDOFF.md`
   - `orchestration/checkpoints/phase_1_5_remediation_2.md`
   - `orchestration/bundles/phase_1_5_remediation_2.txt`
3. Verify the current instruction commit changes only
   `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` and its parent is exactly
   TARGET_COMMIT `c3148cc191de58ecab9b11cd05291cc8ffe45455`.
4. Verify the worktree is clean and local HEAD equals a freshly fetched remote
   branch HEAD.
5. Verify `current_phase: 1.5`, `last_completed_phase: 1.5`,
   `last_orchestrator_approved_phase: 1`, and
   `awaiting_orchestrator_review: true` before applying this explicit approval.
6. If any target, ancestry, phase, instruction-ID, branch, or trust-state check
   fails, fail closed and STOP.

## Required implementation

### 1. Persistence and migrations

Add the minimum normalized PostgreSQL 17-compatible schema needed for the
Phase 2 build surface. Preserve existing append-only chain/provider evidence
and existing role separation. Migrations must work from zero and from current
head, downgrade safely where the repository contract requires it, and be
restart/idempotency tested.

At minimum, persist the responsibilities required by MASTER_SPEC sections
24-33: tokens, token market snapshots, token discovery/outcomes or equivalent
normalized records, reference asset prices, wallet candidates/wallets, wallet
discovery events, winner milestone events, archaeology runs, and negative-
control linkage/support. Modest SQL normalization is implementation discretion;
do not remove required history or provenance.

Use uniqueness/idempotency keys that prevent duplicate token, milestone,
archaeology-trigger, early-buyer, wallet-candidate, and discovery-provenance
rows when the same source observation is replayed. Do not overwrite a prior
point-in-time belief with a later observation.

### 2. Token import and on-chain mint validation

Implement a deterministic bootstrap-token importer. It must reject malformed
addresses and must not treat address shape alone as on-chain mint validation.
Validation must use committed chain/provider evidence to establish that the
address is a token mint and record validation source, observation/chain time,
commitment where available, evidence reference, and result.

Malformed, missing, conflicting, unresolvable, wrong-owner, or non-mint account
evidence fails closed. A provider-capacity or environmental miss is recorded as
missing/limited evidence, never converted to a validated mint.

### 3. Token lifecycle and market-state ledger

Persist lifecycle observations, venue/program/pool identifiers, market
snapshots, and point-in-time reference prices. Preserve source, observed_at,
chain timestamp where available, confidence, algorithm/config version, and raw
evidence reference. Repeated observations append or deduplicate by canonical
source identity; they do not rewrite older beliefs.

Compute winner labels only from a versioned baseline methodology and observed
peak evidence. Make winner labels research-only. Missing contemporaneous
supply/liquidity/reference-price data yields explicit `NULL`/low-confidence
fields, not today's values backfilled into historical state.

### 4. Historical provider adapters and archaeology service

Implement provider-neutral historical adapters over the already-approved
free-first sources and Phase 1 provider contracts. Pagination, repeated cursor,
truncation, empty-page, rate-limit, and partial-response behavior must be
explicit and fail closed for completeness claims. Record provider usage through
the existing accounting path.

Implement one deterministic historical archaeology run for a verified token.
The run must persist its token, input evidence set, provider/source, time range,
algorithm/config/git identity, known gaps, completeness statement, winner
definition/baseline version, output candidate rows, and terminal status.
Retries or replay must not duplicate outputs or erase a failed/partial prior
attempt.

### 5. Early-buyer extraction and wallet candidates

Extract distinct meaningful net buyers using deterministic net-flow semantics,
stable ordering, and explicit tie-breaking. Record all MASTER_SPEC section 33
fields that evidence can support. Keep raw amounts and Decimal conversions
separate. Exclude no address merely because a tag suggests deployer, insider,
bundler, related funder, or bot; persist those as tags with evidence and
confidence.

Create wallet candidates and a `wallet_discovery_event` for each discovery.
Persist exact discovery channel and trigger linkage. The observation that
caused discovery must be permanently queryable as discovery-contaminated for
Phase 3 qualification exclusion. Do not implement or claim Phase 3 wallet
scoring.

### 6. Prospective winner watcher and automatic trigger

Implement the deterministic prospective discovery path. A token crossing a
versioned winner milestone from point-in-time market observations creates one
idempotent winner-milestone event and one bounded archaeology trigger. Duplicate
or replayed observations must not create duplicate milestone or trigger rows.
Out-of-order, stale, low-confidence, or incomplete observations must not
silently rewrite an earlier milestone decision.

The watcher may be demonstrated with deterministic REPLAY data when live
provider access remains environmentally unavailable. A replay is not live
Helius validation and must be labeled as replay. Automatic archaeology here
means automatic creation/execution of the research job within the Phase 2
system; it does not mean a trade, quote, order, or live execution action.

### 7. Negative-control schema support

Persist enough structure to associate winner-token archaeology with control
tokens and the matching dimensions named by MASTER_SPEC section 31: launch
period, venue, early liquidity, early market cap, and early transaction
activity. Phase 2 acceptance requires schema and deterministic round-trip
support, not completion of a full negative-control study.

### 8. CLI/runtime wiring and reports

Wire the production code through ordinary ARGUS CLI/service entry points. At
minimum provide reproducible commands to import/validate a token, run historical
archaeology, and run/replay the prospective winner watcher. Tests that call an
unwired helper do not prove this requirement.

Produce the MASTER_SPEC Phase 2 demonstration for at least one verified real
historical token. Reusing the verified Phase 1.5 token is allowed if provenance
and validation remain authentic. Report mint, winner category, baseline method,
early buyers, data source, history limitations, and sanitized sample rows.

## Prospective acceptance tests

Write tests before or with implementation. Each test must assert durable state
and forbidden side effects, not only that no exception occurred.

### P2-T1 — mint validation fails closed

Cover valid committed mint evidence plus malformed address, valid-shaped
non-mint account, wrong owner, missing account, malformed provider response,
and unavailable provider. Only authentic mint evidence may persist a validated
status. No credential or live call is required for the deterministic fixture
test.

### P2-T2 — lifecycle and market snapshots preserve point-in-time truth

Persist multiple lifecycle/market observations for one token. Assert older
rows remain unchanged, observed_at differs from chain time, confidence/source/
evidence references persist, and unavailable historical fields remain NULL.

### P2-T3 — winner baseline is tradable and versioned

Use a fixture containing a zero-liquidity launch observation followed by a
reliably tradable observation. Assert the zero-liquidity point is not used to
inflate the winner multiple; persist baseline version, timestamp, price,
liquidity, peak, category, and reason codes. Assert winner labels cannot create
trade intents or signals.

### P2-T4 — historical archaeology works on real evidence

Run the production CLI/service path for at least one verified historical token
using committed real evidence. Assert an archaeology run, source/time range,
gaps/completeness, input references, early buyers, wallet candidates, and
discovery events persist. Mocks may test errors but cannot satisfy this real-
evidence demonstration.

### P2-T5 — early-buyer extraction is reproducible

Replay identical evidence twice and in different page/delivery order. Assert
the same distinct-buyer set, stable sequence/tie-break order, raw amounts,
supported Decimal USD estimates, lifecycle/venue fields, tags, and no duplicate
rows. Explicitly assert unavailable buyers are not invented.

### P2-T6 — discovery contamination remains identifiable

For every candidate created by archaeology, assert the exact trigger token/
event/reason/channel/algorithm version is persisted and queryable. Assert the
trigger observation is marked for later `DISCOVERY_CONTAMINATION` exclusion
without deleting it. Do not calculate Phase 3 qualification scores.

### P2-T7 — prospective milestone trigger is idempotent

Replay below-threshold, threshold-crossing, duplicate, stale, out-of-order, and
restarted-worker observations. Assert exactly one milestone and one archaeology
trigger for each first valid crossing; no phase skip, signal, trade intent,
order, or execution side effect may occur.

### P2-T8 — historical provider failure matrix

Cover pagination, repeated cursor/cycle, duplicate page, empty page before
completion, truncation/cap, timeout, rate limit, malformed response, and partial
success. Assert source limitations and terminal run status are explicit and no
partial response is reported as complete.

### P2-T9 — negative-control schema round trip

Persist a winner token, a matched control token, matching dimensions, method/
version, and evidence references. Assert the control is not mislabeled a
winner and no live eligibility is derived from either label.

### P2-T10 — migration, restart, and concurrency safety

Test migration from zero and current head, role grants, duplicate concurrent
trigger delivery, crash/restart around archaeology-run creation and output
commit, and rollback on persistence failure. Assert no lost provenance,
partially claimed success, or duplicate canonical output.

### P2-T11 — predecessor regression and safety

Replay all historical golden parser fixtures and the Phase 1.5 semantic-gate
tests. Assert no unexpected classification/eligibility change, all ambiguous
and unsupported semantics remain ineligible, and no signer/private-key/
broadcast/live-arm/paid-provider path is introduced.

## Mandatory validation and evidence

Before handoff, run and record:

1. focused Phase 2 unit, contract, and property tests;
2. real-evidence historical archaeology demonstration;
3. deterministic prospective-watcher replay;
4. migration-from-zero and upgrade-from-current-head checks against the
   available local PostgreSQL substitute, labeled accurately;
5. parser/golden and Phase 1.5 regression tests;
6. all affected integration and restart/concurrency tests;
7. full repository test suite;
8. Ruff lint and format checks;
9. mypy;
10. tracked-file secret scan;
11. `argus fixtures validate-real-chain`;
12. generated demonstration/report reproducibility check.

Report exact commands, counts, failures, skips, and environment. If a check is
environmentally unavailable, classify it honestly and cite the already-
approved deferral or stop for orchestrator review; do not invent a pass. PG16
must never be described as PG17 validation.

Create fresh immutable evidence:

- `orchestration/checkpoints/phase_2.md`
- `orchestration/bundles/phase_2.txt`

The checkpoint must include:

1. instruction/target/result commit identities and changed files;
2. requirement-to-code/test/evidence matrix for every Phase 2 acceptance item;
3. schema/migration and role-grant summary;
4. the verified historical-token demonstration and sanitized sample rows;
5. source/provider/time-range/gap/completeness details;
6. early-buyer reproducibility and idempotency results;
7. discovery provenance and contamination-exclusion proof;
8. prospective milestone/replay and restart proof;
9. negative-control schema proof;
10. all commands and exact results;
11. environmental deferrals and non-blocking debt;
12. security, credential, paid-provider, and live-state confirmation;
13. deviations;
14. explicit STOP pending independent Phase 2 audit.

Update `docs/BUILD_STATE.md`, append `docs/DECISION_LOG.md`, and replace
`orchestration/AGENT_HANDOFF.md` with a new handoff. Apply this instruction's
explicit approval by setting `last_orchestrator_approved_phase: 1.5` and
`approved_commit: c3148cc191de58ecab9b11cd05291cc8ffe45455`. Do not mark
Phase 2 approved.

Use a new `HANDOFF_ID` and exactly:

`LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-2-001`

Every implementation-agent commit in this run must use exactly one real
terminal Git trailer recognized by `git interpret-trailers --parse`, as the sole
final paragraph:

`ARGUS-INSTRUCTION-ID: argus-phase-2-001`

Push all authorized work, verify clean worktree and local/remote HEAD equality,
then STOP. Do not modify this instruction file, self-authorize Phase 2, begin
Phase 3, or perform any later-phase work.

## Prohibitions preserved

This instruction does not authorize any mainnet trade, canary, transaction
broadcast, quote intended for execution, signer/private-key/seed access,
credential entry or disclosure, paid-provider upgrade or usage, live arming,
threshold relaxation, evidence rewrite, phase skip, or work outside Phase 2.

