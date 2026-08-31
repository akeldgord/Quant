# ARGUS Orchestrator Instructions

**OWNER: ARGUS ORCHESTRATOR.** The implementation agent must not modify this
file. Execute only the ACTIVE instruction below. MASTER_SPEC.md remains
authoritative except where this instruction explicitly adds stricter
acceptance detail.

---

INSTRUCTION_ID: argus-phase-1-001
ISSUED_AT: 2026-08-31T04:04:52Z
TARGET_COMMIT: 141af487fcfdff41d1597c19ea062139f5427f52
AUTHORIZED_ACTION: IMPLEMENT_PHASE_1_ONLY
AUTHORIZED_PHASE: 1
APPROVES_PHASE: 0
STATUS: ACTIVE

## Independent audit disposition

- Phase 0 is approved at the audited target commit as
  `PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`.
- `PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK` remains open.
  It does not block Phase 1, but it must be closed against real PostgreSQL
  17 before live readiness may be approved.
- Watcher remediation round 3 is accepted for continued build orchestration.
  Its unsigned, file-trust attribution boundary remains documented and must
  not be overstated.
- Phase 1 is authorized by this instruction.
- Phase 1.5 and all later phases remain forbidden.
- No live trade, mainnet canary, signing, private-key access, credential
  disclosure, paid-provider upgrade, live arming, threshold relaxation, or
  phase skip is authorized.

## Mandatory session start and state transition

Before changing code:

1. Run `git status --porcelain`, `git pull --ff-only`, and
   `git log -5 --oneline`.
2. Read the six canonical files in the exact order required by PROTOCOL.md.
3. Verify the checked-out instruction commit is exactly one instruction-only
   commit whose parent is the exact target above.
4. Verify the worktree is clean and local HEAD equals the remote branch.
5. Update BUILD_STATE only as permitted by this approval:
   - mark Phase 0 orchestrator-approved;
   - set `last_orchestrator_approved_phase` to `0`;
   - set `approved_commit` to the exact audited target commit above;
   - enter Phase 1 without claiming it complete or approved.
6. If any precondition is false, stop with a PARTIAL/FAIL handoff. Do not
   improvise around the gate.

## Phase 1 goal

Prove reliable, auditable acquisition and deterministic canonical parsing of
live Solana chain data using the fixed modular-monolith, free-first
architecture.

Implement Phase 1 only:

- Helius/Solana standard RPC adapter;
- standard Solana WebSocket adapter;
- reconnect handling and per-wallet subscriptions;
- persistent per-wallet stream/reconciliation watermarks;
- deterministic truth-path reconciliation and stream-gap detection;
- provider capability, history, and usage probes;
- HTTP and streaming usage accounting;
- DexScreener adapter;
- GeckoTerminal adapter;
- Jupiter quote/order-construction adapter with no signing;
- centralized request-priority scheduler;
- immutable `chain_events`;
- transaction fetching;
- deterministic generic balance-delta swap parser;
- sanitized golden transaction fixtures.

Do not implement token/wallet discovery, scoring, shadow trading, execution,
signing, Phase 1.5 historical feasibility work, or any later-phase feature.

## Provider architecture and cost controls

Keep provider response objects behind typed adapters/protocols. Domain and
persistence code must consume canonical ARGUS models, never provider-specific
objects.

Use the fixed free-first provider baseline:

- Helius standard RPC and standard WebSocket functionality for initial live
  chain access;
- DexScreener for pair/token lookup and current market state;
- GeckoTerminal for historical OHLCV/fallback use, not high-frequency live
  dependence;
- Jupiter for executable quotes and unsigned order construction only.

No paid or accelerated endpoint may be enabled. No provider allowance may be
treated as an architecture constant. Use conservative configurable local
limits below published maxima.

Every outbound request must record the fields required by MASTER_SPEC section
14, including provider, endpoint, request class, timing, latency, status,
retry count, estimated credits, bytes received, and cache-hit state.
Streaming accounting must record connection, subscription, reconnect, bytes,
and estimated-credit counters. Implement usage reporting for today,
month-to-date, 30-day projection, allowance percentage, and warnings at
70%, 85%, and 95%. Never auto-upgrade.

Implement the canonical Jupiter priority order exactly:

- P0 emergency live exit;
- P1 ordinary live exit;
- P2 live entry order;
- P3 live safety/sellability check;
- P4 prospective copyability quote;
- P5 shadow exit quote;
- P6 background research.

Phase 1 must test scheduler ordering and starvation protection, but it must
not execute any live action. When constrained, background research may be
delayed or dropped with an explicit missing-data reason; safety-class
requests must never be silently starved.

Provider probes must report reachability, supported functions, configured
throttle, response-contract status, latency, and health. History probes must
report the earliest/latest available data, partitions/freshness where
applicable, estimated query/download size, and limitations. Do not infer
availability from marketing text.

If a credential is genuinely required and is not already configured locally,
do not request or print it. Emit only the MASTER_SPEC section 108
`LOCAL CREDENTIAL REQUIRED` notice and return PARTIAL. Do not substitute a
mocked provider probe and claim live acceptance.

## Immutable event ledger and observation-time truth

Implement canonical `chain_events` with immutable raw evidence and
deduplication. At minimum preserve:

- UUID event ID;
- chain and slot;
- block time;
- `first_seen_at`;
- confirmed/finalized timestamps when known;
- provider and provider receipt time;
- transaction signature;
- event type;
- optional wallet and mint;
- raw payload or immutable payload reference;
- payload hash;
- parser version;
- creation timestamp.

Raw observations are append-only. Derived data may be recomputed without
rewriting raw point-in-time truth. Always keep block time, first-seen time,
confirmed time, and finalized time distinct.

Use integer raw units for on-chain quantities and Decimal for canonical
prices/accounting. Do not use binary float for canonical financial values.

Store commitment progression. Processed-only events may be retained for
latency research, but no processed-only event may be eligible for future
live execution under the standing confirmed-source policy.

## Fast path, truth path, and reconciliation

Each tracked wallet must use:

- WebSocket fast-path observation;
- periodic RPC/history truth-path reconciliation.

Persist at least:

- last stream signature and slot;
- last reconciled signature and slot;
- last reconciliation timestamp;
- stream health.

On disconnect, reconnect, process restart, timeout, subscription failure,
clock anomaly, or host resume, perform reconciliation. If reconciliation is
unresolved, mark the wallet live state DEGRADED. A degraded wallet can never
produce an eligible live-entry intent.

Implement the mandatory deterministic scenario:

1. stream connects;
2. event A is observed;
3. disconnect occurs;
4. event B occurs while disconnected;
5. reconnect occurs;
6. reconciliation discovers B.

The final canonical ledger must contain A exactly once and B exactly once.
Repeat the scenario across process restart and duplicate-delivery variants.

Use both UTC wall time and monotonic time. Persist wall timestamps and use
monotonic time for latency/duration. Detect material clock jumps and
suspend/resume conditions. Such conditions must block any future live-entry
eligibility until provider reconnection, chain reconciliation, and clock
health recovery are complete.

## Transaction fetching and generic parser

Start with deterministic wallet-owned pre/post balance-delta reconstruction;
do not build a separate parser for every DEX.

The parser must:

1. obtain and preserve raw transaction evidence;
2. identify wallet-owned accounts;
3. canonicalize SOL and wrapped SOL;
4. calculate net native/token deltas;
5. account for network fees;
6. identify meaningful asset inflow/outflow;
7. classify deterministically;
8. emit confidence and parser version.

Required classifications:

- `SWAP_SIMPLE`
- `SWAP_COMPLEX`
- `TRANSFER_IN`
- `TRANSFER_OUT`
- `TOKEN_CREATE`
- `LP_ACTION`
- `UNKNOWN`

Required sanitized real-chain golden fixtures:

- SOL to token;
- token to SOL;
- token to USDC;
- multi-hop swap;
- simple transfer;
- partial sell;
- multiple token accounts;
- ambiguous multi-asset transaction;
- failed transaction.

Any ambiguous or UNKNOWN interpretation must be preserved for research but
must be mechanically incapable of creating an eligible live-copy signal.
Golden-fixture output changes must fail until reviewed.

## Database and restart requirements

Use PostgreSQL 17 architecture, SQLAlchemy 2.x, asyncpg, and Alembic. Do not
replace the database or introduce services outside the fixed modular
monolith.

Add migrations for Phase 1 canonical entities without weakening Phase 0 role
separation. Verify migration from zero and upgrade from the existing Phase 0
head. Add constraints/indexes for deterministic deduplication and replay.
Verify transaction/event ingestion and watermarks survive process restart.

Where the current environment cannot run real PostgreSQL 17, keep the
existing deferred flag honest. A substitute server or mock may support code
tests but must not be called PostgreSQL 17 validation.

## Mandatory acceptance tests

Independently demonstrate and record each as PASS, FAIL, or NOT TESTED:

1. configured Solana RPC works;
2. configured WebSocket works;
3. disconnect is detected;
4. reconnect works;
5. reconciliation recovers a missed event;
6. A and B are each canonicalized exactly once;
7. duplicate deliveries remain idempotent;
8. watermarks persist across restart;
9. commitment status and progression are stored;
10. clock health and anomalies are stored;
11. provider priority ordering and starvation protection work;
12. HTTP and streaming usage are counted;
13. 70/85/95 usage warnings trigger correctly;
14. adapter contract validation rejects malformed provider responses;
15. retry/backoff honors configured limits and never fabricates data;
16. every required golden parser fixture passes;
17. raw-unit and Decimal arithmetic remain exact;
18. ambiguous/UNKNOWN transactions cannot create live-copy signals;
19. stream gaps and unresolved reconciliation force DEGRADED state;
20. restart during reconciliation fails closed and resumes idempotently;
21. migration from zero succeeds where a database is available;
22. upgrade from the Phase 0 Alembic head succeeds;
23. DB role grants remain least privilege;
24. no signing, signer, private-key, seed-phrase, live-arm, or transaction
    broadcast path exists;
25. secret scan is clean;
26. no paid-provider feature is enabled;
27. no Phase 1.5 or later-phase code was started.

Use deterministic unit tests, contract tests, real temporary persistence
where suitable, replay/golden tests, and narrow live smoke probes only where
credentials/network access are safely available. Tests must not make a
mainnet trade or broadcast a transaction.

Run and record exact results for at least:

- `uv run pytest tests/unit -v`
- `uv run pytest tests/integration -v`
- `uv run pytest tests/golden -v`
- `uv run pytest tests/replay -v`
- `uv run pytest --cov --cov-report=term-missing`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy`
- relevant Alembic upgrade/current checks;
- `argus providers probe`;
- `argus providers probe-history`;
- `argus providers usage`.

Do not claim an unrun test. Environmental failure must be reported honestly
as PARTIAL/NOT TESTED with the exact blocker.

## Checkpoint, bundle, and handoff

At completion:

- set BUILD_STATE to Phase 1 completed and awaiting orchestrator review only
  if all required build work is actually complete;
- do not mark Phase 1 orchestrator-approved;
- create new immutable evidence:
  - `orchestration/checkpoints/phase_1.md`
  - `orchestration/bundles/phase_1.txt`;
- generate the canonical runtime checkpoint/bundle required by MASTER_SPEC;
- use a new unique handoff ID;
- set the last-instruction ID exactly to `argus-phase-1-001`;
- include honest failures, provider limitations, credential/network
  blockers, data-quality warnings, and deferred checks;
- state clearly that Phase 1.5 remains blocked;
- verify remote HEAD equals local HEAD and the worktree is clean.

Every commit created for this run must contain exactly one valid terminal
trailer with value `argus-phase-1-001`.

Then STOP. Do not modify this instruction file. Do not begin Phase 1.5.
