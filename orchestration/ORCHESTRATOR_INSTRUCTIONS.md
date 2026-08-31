# ARGUS Orchestrator Instructions

**OWNER: ARGUS ORCHESTRATOR.** The implementation agent must not modify this
file. Execute only the ACTIVE instruction below. MASTER_SPEC.md remains
authoritative except where this instruction explicitly adds stricter
acceptance detail.

---

INSTRUCTION_ID: argus-phase-1-remediation-002
ISSUED_AT: 2026-08-31T07:25:12Z
TARGET_COMMIT: 04f367b8e03e99718812f872a34e73e170c44f0d
AUTHORIZED_ACTION: REMEDIATE_PHASE_1_ROUND_2_ONLY
AUTHORIZED_PHASE: 1
APPROVES_PHASE: NONE
STATUS: ACTIVE

## Independent audit disposition

- Phase 0 remains approved as
  `PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`.
- `PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK` remains open
  and blocks live readiness, not this remediation.
- Phase 1 remediation round 1 is **not approved**.
- Phase 1 remains blocked because independent code review found additional
  non-environmental correctness and safety defects described below.
- Authenticated real-chain golden fixtures also remain incomplete.
- Phase 1.5 and every later phase remain forbidden.
- This instruction approves no phase and authorizes only the listed Phase 1
  remediation.
- No live trade, mainnet canary, signing, private-key access, credential
  disclosure, paid-provider upgrade, live arming, threshold relaxation, or
  phase skip is authorized.

## Mandatory session start

Before changing code:

1. Run `git status --porcelain`, `git pull --ff-only`, and
   `git log -5 --oneline`.
2. Read the six canonical files in the exact PROTOCOL.md order.
3. Verify the checked-out instruction commit is exactly one
   instruction-file-only commit whose parent is the exact TARGET_COMMIT above.
4. Verify the worktree is clean and local HEAD equals the remote branch.
5. Verify BUILD_STATE still has `current_phase: 1`,
   `last_orchestrator_approved_phase: 0`, and
   `awaiting_orchestrator_review: true`.
6. If any precondition is false, stop with an honest PARTIAL/FAIL handoff.

## Audit findings that must be remediated

### 1. Recovery can report OK before a WebSocket is connected

`IngestionManager._stream_once()` constructs an async generator and then
calls reconciliation before the generator's first `__anext__()`. In the
real Helius adapter, connection establishment, subscribe send, and subscribe
ack all occur lazily inside that first iteration. Therefore a successful
reconciliation can mark a wallet OK before any socket exists or subscription
ack has been received.

Periodic reconciliation has the same safety flaw: it can set a disconnected
wallet back to OK during reconnect backoff because
`ReconciliationEngine.reconcile()` does not know whether the stream is
connected. This violates the required three-part recovery gate.

Replace the implicit async-generator lifecycle with an explicit, typed
subscription-session boundary that does not report ready until:

- the socket connection exists;
- the subscription request was sent;
- a valid matching subscription acknowledgement was received.

Persist or atomically maintain independent recovery dimensions for each
wallet:

- stream connected/subscribed;
- reconciliation complete through its safe boundary;
- clock healthy/recovered.

Derive wallet live state from all three. No standalone scheduled
reconciliation, finalization sweep, clock tick, or other background action may
restore OK while the stream dimension is false. Disconnect, timeout,
malformed message, iterator exhaustion, cancellation, host resume, and
subscription failure must clear the stream dimension before recovery begins.

Add a real lifecycle test whose fake has a lazy async-generator handshake so
it proves reconciliation cannot restore OK before the first iteration
actually establishes and acknowledges the subscription.

### 2. One AsyncSession is shared across concurrent tasks

The live CLI creates one SQLAlchemy `AsyncSession` and shares it through one
reconciliation engine, all repositories, HTTP usage recording, every wallet
task, periodic reconciliation, and clock work. SQLAlchemy AsyncSession is a
mutable unit of work and is not safe for concurrent task use. Multi-wallet
runtime can corrupt transaction state, cross-commit another wallet's work, or
fail unpredictably even though in-memory tests pass.

Refactor live wiring around session/unit-of-work factories:

- no AsyncSession instance may be used concurrently by different tasks;
- each wallet operation/reconciliation item gets an explicit transaction
  boundary;
- usage accounting uses a safe independent transaction path;
- per-item event + commitment + parse result + watermark advancement is
  atomic for that wallet;
- a failure cannot commit another task's pending work;
- partial progress remains restart-safe;
- session rollback/closure is guaranteed on cancellation and exceptions.

Add real PostgreSQL integration tests with multiple wallets, simultaneous
stream events, simultaneous periodic reconciliation, usage writes, forced
failure in one wallet, and restart. Prove the unaffected wallet commits
correctly and the failed wallet cannot cross-commit or corrupt it.

### 3. Background task failures are silently lost

`IngestionManager.run()` waits only on `stop_event`. If the periodic task,
clock task, or a wallet task exits unexpectedly after an error in its own
failure-handling path, the manager can remain alive forever with part of
ingestion dead.

Implement structured supervision:

- any unexpected child completion or exception must be observed immediately;
- mark affected/all relevant wallets DEGRADED before shutdown;
- cancel and await sibling tasks;
- close/unsubscribe resources;
- propagate a typed terminal manager failure to the CLI/process;
- never leave the process apparently healthy with a dead child;
- normal operator shutdown remains distinct, deterministic, and fail-safe.

Test failures in the wallet loop, periodic loop, clock loop, degradation
writer, usage writer, and cleanup path.

### 4. Finalization tracking is still not a runtime path

`sweep_finalization()` exists, but `IngestionManager` never calls it.
A callable method that no production loop schedules is still dead code.

Add a configurable finalization sweep cadence to the real manager. It must:

- use the same safe per-wallet unit-of-work boundary;
- batch within the provider's documented/request limits;
- append FINALIZED only when the provider reports it;
- distinguish duplicate/no-op from an actual new promotion;
- record and surface failures without falsely restoring wallet health;
- run after confirmed ingestion and across restart;
- preserve provider usage accounting.

Add manager-level and real-SQL tests proving confirmed events are later
promoted by the running manager, exactly once.

### 5. Commitment derivation and conflict handling are not deterministic or atomic

The SQL store orders only by `created_at`, yet derivation uses list position
as the final tie-break. Rows sharing `created_at` have no guaranteed SQL
order, so current state can vary between queries. Also,
`CommitmentTracker.record()` examines the first same-level row. After an
unknown-to-known refinement, a later conflicting known value can be compared
against the older unknown row and wrongly appended. Read-check-append is also
race-prone under concurrent stream/reconciliation/finalization work.

Implement:

- a durable monotonic per-event observation sequence or another explicit,
  stable total order stored in the database;
- deterministic SQL ordering by that total order;
- validation against the full current same-level state, not the first row;
- atomic per-event serialization using a database-safe mechanism;
- an append-only durable audit record for rejected regression/conflict
  attempts, including reason and source metadata;
- a result type that distinguishes APPENDED, DUPLICATE_NOOP, REJECTED, and
  FAILED, so finalization counts only actual promotions;
- database CHECK constraints for commitment values and required invariants.

Add concurrent real-SQL tests, exact timestamp-tie tests across independent
sessions, unknown->known->conflicting-known tests, and repeated-finalization
tests.

### 6. Immutable ledgers are writable after insert

Migration 0003 grants `UPDATE` on `commitment_observations` to
`argus_ingest`. Earlier Phase 1 grants also permit UPDATE on
`chain_events`, despite the stated append-only raw-evidence rule.

Enforce immutability mechanically:

- ingest may INSERT/SELECT immutable observation tables but not UPDATE or
  DELETE;
- add database-level protection against UPDATE/DELETE for raw chain events,
  commitment observations, and rejection/audit observations;
- retain UPDATE only where mutable derived state truly requires it, such as
  wallet watermarks;
- add role-level integration tests proving attempted mutation/deletion fails;
- preserve migration downgrade correctness.

### 7. Provider protocols still expose provider-shaped dictionaries

The checkpoint claims typed canonical ARGUS response models, but
`MarketDataProvider` and `ExecutionProvider` still return
`dict[str, Any]`, and the adapters return provider-shaped dictionaries.
Validation helpers alone do not satisfy the typed canonical boundary.

Introduce canonical immutable ARGUS models for:

- token/pair market snapshot;
- historical OHLCV candle/page;
- executable quote;
- unsigned order-construction result;
- any other provider response consumed outside its adapter.

Protocols must return these canonical models. Provider-specific raw JSON must
remain inside adapters, except immutable raw evidence explicitly preserved
alongside the canonical model. Use Decimal/integer raw units for financial
fields. Validate all required nested values before construction. Update probes
and tests so no domain/consumer code indexes provider-specific dictionaries.

Raw Solana transaction evidence may remain a validated raw payload because its
purpose is immutable replay, but all separately consumed metadata must use
typed canonical models.

### 8. Usage rows misclassify contract/application failures as OK

`send_with_usage()` writes `status="ok"` immediately after an HTTP 2xx
response, before JSON decoding, JSON-RPC error handling, or response-contract
validation. A malformed body or provider application error is therefore
persisted as success. Cancellation is also not represented.

Refactor the adapter lifecycle so one terminal logical-operation outcome is
recorded after decode and validation:

- success;
- HTTP error;
- transport exhaustion;
- timeout;
- provider application/RPC error;
- JSON decode error;
- contract error;
- cancellation where safely observable.

Preserve actual attempt count, latency, bytes, endpoint, request class,
cache-hit state, and estimated credits when known. Usage-recorder failure must
not mask the provider error, but it must emit a safe operational-health signal
rather than disappear silently. Ensure no duplicate contradictory terminal
rows are created for one logical operation.

Add adversarial tests for each terminal outcome on every adapter family.

### 9. Parser failures are not durably recorded and can be skipped forever

On parser error, reconciliation increments an in-memory counter and advances
the durable watermark. After restart there is no durable record explaining
why the event lacks a parsed row and no production retry/reparse queue.
Also, `SqlSwapRecorder` catches every IntegrityError and labels it a
duplicate, which can hide foreign-key, range, or schema failures.

Implement a durable, versioned parse-attempt/result ledger:

- record success, UNKNOWN, and failure with event ID, parser version,
  attempted_at, error class/safe reason, input payload hash, code/config/git
  identity, and retry disposition;
- make pending/retryable parse failures queryable and replayable from
  immutable raw evidence;
- add a production CLI/sweep for deterministic reparse without rewriting
  prior attempts or raw evidence;
- watermark advancement may proceed only when the parse outcome is durably
  recorded;
- catch a uniqueness collision as idempotency only after confirming the
  expected `(event_id, parser_version)` row exists; re-raise every other
  IntegrityError;
- apply the same collision-specific rule to event dedup rather than treating
  arbitrary integrity failures as duplicates.

Test malformed payload, DB constraint failure, duplicate version, new parser
version, retry after restart, and concurrent duplicate attempts.

### 10. Pagination does not validate continuity or ordering

The pagination code checks only whether the oldest cursor repeats. It does not
reject duplicate overlap across pages, inconsistent newest-first ordering,
slot regression within a page, cursor cycles involving more than one value,
or a missing/pruned persisted boundary. A short/empty page is treated as
success even when the old boundary was never verifiably reached.

Add deterministic validation that:

- each page and the combined sequence are correctly ordered;
- signatures are unique across pages unless a documented overlap rule is
  explicitly normalized and audited;
- every cursor value is globally non-repeating;
- the persisted boundary is verified as reachable/continuous when one exists;
- pruned/unavailable history fails DEGRADED with an explicit gap reason;
- safety-ceiling behavior has a documented recovery/backfill path and cannot
  remain permanently wedged without an operator-visible blocker;
- no watermark advances on an unverified gap.

Cover two-page cursor cycles, page overlap, out-of-order slots/signatures,
missing boundary, pruned history, exact full final page, and >ceiling gaps.

### 11. Scheduler submitter cancellation still leaves queued work executable

If a caller awaiting `submit()` is cancelled before its queue item is
dispatched, the future may be cancelled but the queue item remains and its
`coro_factory` can later execute without a live requester.

Remove cancelled queued items or skip them before dispatch, decrement pending
counts exactly once, and prove cancellation cannot execute abandoned work,
leak capacity, corrupt starvation age, or wedge later requests.

### 12. Real-chain golden evidence remains required

Synthetic fixtures remain useful but do not satisfy the real-chain fixture
criterion. Do not permanently substitute synthetic data.

The sandbox can access GitHub even though general RPC egress is blocked.
Use read-only GitHub access to search established open-source Solana parser,
indexer, or SDK repositories for authentic captured `getTransaction`
fixtures. Import only fixtures whose upstream provenance is traceable to an
immutable upstream repository commit and whose license permits reuse.

For every required category preserve:

- chain, signature, slot, and transaction version;
- upstream repository, immutable commit SHA, and exact source path;
- upstream license;
- original bytes/hash;
- sanitization transform and sanitized hash;
- fields used by the parser and expected canonical output.

Do not invent a signature or claim authenticity from payload shape alone. If
a category cannot be sourced and independently supported from GitHub evidence,
leave it NOT TESTED and return PARTIAL. Also add an offline import/validation
command so a future network-enabled host can capture and verify missing
fixtures without changing parser expectations.

Live RPC/WebSocket checks and real PostgreSQL 17 Compose validation may remain
explicit environmental deferrals, but real-chain fixture authenticity must
remain open until actually supported.

## Mandatory acceptance tests

Independently demonstrate at least:

1. no wallet becomes OK before a real subscription-ready acknowledgement;
2. periodic reconciliation cannot restore OK while disconnected;
3. recovery requires stream-ready + complete reconciliation + healthy clock;
4. multi-wallet real-SQL concurrency uses no shared AsyncSession and has no
   cross-commit/cross-rollback;
5. any child-task death terminates the manager fail-closed;
6. manager shutdown/cancellation closes resources and leaves safe state;
7. running manager performs confirmed-to-finalized promotion exactly once;
8. commitment ordering is stable across independent SQL sessions and ties;
9. unknown->known->conflicting-known rejects and durably audits conflict;
10. concurrent commitment writes serialize safely;
11. immutable ledger UPDATE/DELETE is denied at the database and role layers;
12. provider protocols return canonical typed ARGUS models;
13. contract/RPC/JSON failures produce non-OK terminal usage records;
14. usage recorder failure is visible but never masks provider outcome;
15. parser failures persist and are replayable after restart;
16. unrelated IntegrityError is never swallowed as a duplicate;
17. pagination rejects overlap, cycles, ordering faults, and missing boundary;
18. safety-ceiling recovery is deterministic and operator-visible;
19. cancelled scheduler submissions never execute;
20. replay tests cover the new concurrency, commitment, parser, and pagination
    paths;
21. every required authenticated real-chain fixture and provenance hash
    validates, or the item remains explicitly NOT TESTED/PARTIAL;
22. migration from zero and upgrade from Phase 0 head succeed where a
    database is available;
23. DB grants remain least privilege;
24. no signing, signer, private-key, seed-phrase, live-arm, or broadcast path
    exists;
25. secret scan is clean;
26. no paid-provider feature is enabled;
27. no Phase 1.5 or later-phase code is started.

Run and record exact results for:

- `uv run pytest tests/unit -v`
- `uv run pytest tests/integration -v`
- `uv run pytest tests/golden -v`
- `uv run pytest tests/replay -v`
- `uv run pytest --cov --cov-report=term-missing`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy`
- relevant Alembic upgrade/current/downgrade checks;
- `uv run argus providers probe`;
- `uv run argus providers probe-history`;
- `uv run argus providers usage --provider helius`;
- offline deterministic `argus ingest run --test-mode`;
- the real-chain fixture import/validation command in offline validation mode.

Do not claim an unrun test. PostgreSQL 16 may support code tests but must not
be described as PostgreSQL 17 validation.

## Checkpoint, bundle, and handoff

At completion:

- keep Phase 1 awaiting orchestrator review and not approved;
- leave `last_orchestrator_approved_phase: 0` and the Phase 0
  `approved_commit` unchanged;
- preserve all earlier evidence files as immutable history;
- create:
  - `orchestration/checkpoints/phase_1_remediation_2.md`
  - `orchestration/bundles/phase_1_remediation_2.txt`;
- generate the canonical runtime checkpoint/bundle required by MASTER_SPEC;
- use a new unique handoff ID;
- set `LAST_ORCHESTRATOR_INSTRUCTION_ID` exactly to
  `argus-phase-1-remediation-002`;
- identify all commits, test results, open failures, and deferrals exactly;
- state clearly that Phase 1.5 remains blocked;
- verify remote HEAD equals local HEAD and the worktree is clean.

Every commit created during this run must contain exactly one valid terminal
trailer:

`ARGUS-INSTRUCTION-ID: argus-phase-1-remediation-002`

Then STOP. Do not modify this instruction file. Do not self-authorize Phase
1.5 or any later work.
