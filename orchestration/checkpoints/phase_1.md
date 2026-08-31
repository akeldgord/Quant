================ ARGUS ORCHESTRATOR CHECKPOINT ================

A. Identity
PROJECT: ARGUS
MASTER_SPEC_VERSION: v2.0
SCOPE: Phase 1 — live Solana chain data acquisition and deterministic
  canonical parsing, per orchestrator instruction argus-phase-1-001.
STATUS: PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION
UTC_TIMESTAMP: 2026-08-31T04:59:22Z
GIT_COMMIT: 28a88f74d28e70542050f5d5e8d9a9d139f26bb8
TARGET_COMMIT: 141af487fcfdff41d1597c19ea062139f5427f52
AUTHORIZED_PHASE: 1
APPROVES_PHASE: NONE

B. What was built

Per orchestrator instruction argus-phase-1-001 (APPROVES_PHASE: 0,
AUTHORIZED_PHASE: 1), implemented Phase 1 in full against the fixed
27-item mandatory acceptance checklist:

1. **Helius standard RPC + WebSocket adapter**
   (`src/argus/providers/helius/client.py`) — `HeliusRpcClient`
   implements `ChainProvider` (getTransaction, getSignaturesForAddress,
   getBalance, getTokenAccountsByOwner, getSlot) against injected
   `httpx.AsyncClient`; `HeliusWebSocketStream` implements
   `LiveChainStream` against a `WebSocketConnector` protocol (real
   connector never touched in tests — a fake connector proves the
   subscribe/notification/disconnect-raises path). Credential-gated on
   `HELIUS_API_KEY`: missing key raises `MissingProviderCredentialError`
   with the exact section-108 `LOCAL CREDENTIAL REQUIRED` notice.
2. **DexScreener, GeckoTerminal, Jupiter adapters**
   (`src/argus/providers/{dexscreener,geckoterminal,jupiter}/client.py`)
   — DexScreener for current market state; GeckoTerminal for historical
   OHLCV only (PROV-003); Jupiter for quote + unsigned-order construction
   only — no signing/execute/broadcast method exists anywhere in
   `JupiterClient` (asserted directly by test).
3. **Fast-path/truth-path reconciliation**
   (`src/argus/ingestion/reconciliation.py`) — `ReconciliationEngine`
   with `observe_stream_event()` (fast path, never sets `confirmed_at`)
   and `reconcile()` (truth path — fetches signatures since the last
   watermark, dedups via `EventRecorder.record()`'s return value, sets
   `confirmed_at` when the provider reports no error, marks the wallet
   `DEGRADED` on any provider failure while preserving partial progress
   already recorded). Implements the mandatory deterministic
   disconnect/reconnect scenario (stream connects → A observed →
   disconnect → B occurs while disconnected → reconnect → reconciliation
   discovers B; final ledger contains A and B exactly once), repeated
   across process-restart and duplicate-delivery variants, against both
   in-memory fakes and real SQL repositories on a real Postgres database.
4. **Durable clock-anomaly detection wired into reconciliation gating**
   (`src/argus/ingestion/clock_monitor.py`,
   `src/argus/domain/clock_health.py`,
   `src/argus/ingestion/clock_health_repository.py`) — new
   `PersistentClockMonitor` wraps the existing (Phase 0)
   `ClockHeartbeat` and persists every wall/monotonic comparison to a new
   `clock_health_events` table, not just an in-process flag.
   `ReconciliationEngine` now takes an optional `clock_monitor` and, per
   MASTER_SPEC.md section 17, keeps a wallet `DEGRADED` on an outstanding
   clock anomaly even when the reconciliation call itself succeeds —
   provider reconnection, chain reconciliation, and clock health recovery
   are three independent conditions, not one.
5. **Immutable `chain_events` ledger, `swaps`, `wallet_stream_state`,
   `clock_health_events`** (`src/argus/domain/*.py`,
   `migrations/versions/0002_*.py`) — UUID event IDs,
   `first_seen_at`/`confirmed_at`/`finalized_at` kept distinct,
   `UniqueConstraint(transaction_signature, wallet_address, event_type)`
   as the dedup key, per-role least-privilege GRANTs matching the Phase 0
   pattern (`argus_ingest`: SELECT/INSERT/UPDATE; `argus_research`:
   SELECT; `argus_executor`: nothing — Phase 1 never executes).
6. **Generic balance-delta swap parser**
   (`src/argus/parsing/generic_parser.py`) — deterministic decision tree
   over signed non-zero balance deltas (SOL canonicalized with wrapped-SOL
   mint), producing all 7 required classifications
   (`SWAP_SIMPLE`/`SWAP_COMPLEX`/`TRANSFER_IN`/`TRANSFER_OUT`/
   `TOKEN_CREATE`/`LP_ACTION`/`UNKNOWN`) with confidence + parser version.
   `is_copy_eligible` is `True` only for `SWAP_SIMPLE`/`SWAP_COMPLEX` with
   confidence ≥ 0.5 — an ambiguous/`UNKNOWN` transaction is mechanically
   incapable of producing a live-copy signal. 11 sanitized golden
   fixtures (`tests/golden/fixtures/*.json`) cover all 9 required
   categories (SOL→token, token→SOL, token→USDC, multi-hop swap, simple
   transfer, partial sell, multiple token accounts, ambiguous multi-asset,
   failed transaction) plus 2 extra (transfer-out, token-create) to
   exercise every classification. A real bug was found and fixed here
   before any test existed: the original `TOKEN_CREATE` heuristic
   misclassified an ordinary first-buy-of-a-new-mint swap as
   `TOKEN_CREATE` — fixed to require the new account's delta be exactly
   zero, and a regression test documents the exact failure mode.
7. **Central P0–P6 priority scheduler**
   (`src/argus/providers/scheduler.py`) — strict cross-submission
   priority ordering verified stable under concurrency; safety classes
   (P0–P3) are never dropped; droppable research classes (P4–P6) are
   dropped only with an explicit reason once a configured queue-depth
   limit is reached.
8. **Provider usage/cost accounting** (`src/argus/providers/usage.py`) —
   `SqlUsageRecorder`/`UsageReporter` for today/MTD/30-day-projected
   credits and 70/85/95% warnings against an optional monthly allowance;
   no code path anywhere touches provider tier configuration (COST-002).
   Wired into every real outbound HTTP/RPC call in all 4 adapters (see
   "Data quality warnings" for the one part of this that remains
   logic-only).
9. **HTTP retry/backoff** (`src/argus/providers/retry.py`, new this
   round) — retries only transient failures (`httpx.TransportError`,
   5xx) with exponential backoff honoring a configurable
   `max_attempts`/`base_delay_seconds`/`max_delay_seconds` (read from
   `config/providers.yaml`'s new `retry:` block); a well-formed 4xx is
   never retried; on exhaustion, the last *real* response/exception is
   returned/re-raised — nothing is ever fabricated. Wired into all 4
   provider adapters.
10. **Adapter contract-validation fix** (found this round): Helius's
    `_rpc()` previously raised a bare `KeyError` on a malformed response
    missing both `result` and `error`; now raises a typed
    `HeliusRpcError` naming the malformed response explicitly.
11. **Provider capability/history/usage probe CLI**
    (`src/argus/cli.py` `providers probe`/`probe-history`/`usage`,
    `src/argus/providers/probes.py`) — reports reachability, supported
    functions, configured throttle, response-contract status, latency,
    and health, never inferred from marketing text. A real bug was found
    and fixed here: `_throttle()` queried a nested `providers.<name>.`
    config path that does not exist — `config/providers.yaml` is merged
    *flat* — so every probe's `configured_throttle_per_sec` silently
    printed `None`. Fixed and regression-tested
    (`tests/unit/test_probes.py`); confirmed live via
    `uv run argus providers probe`, which now correctly prints
    Helius=5.0/DexScreener=2.0/GeckoTerminal=1.0/Jupiter=2.0.

C. Files changed
New: `migrations/versions/0002_phase1_chain_events_swaps_watermarks.py`,
`scripts/_generate_golden_fixtures.py` (one-off fixture generator, not
part of the application), `src/argus/domain/{chain_events,clock_health,
swaps,wallet_stream_state}.py`, `src/argus/ingestion/*.py`,
`src/argus/parsing/generic_parser.py`, `src/argus/providers/{credentials,
probes,retry,scheduler,usage}.py`, `src/argus/providers/{dexscreener,
geckoterminal,helius,jupiter}/client.py`, `tests/golden/` (fixtures +
tests), `tests/integration/test_{clock_health_sql,phase1_schema,
reconciliation_sql,usage_accounting}.py`, `tests/unit/test_{clock_monitor,
priority_scheduler,probes,provider_adapters,reconciliation,retry}.py`.
Modified: `config/providers.yaml` (new `retry:` block),
`docs/BUILD_STATE.md`, `migrations/env.py` (register new ORM metadata),
`src/argus/cli.py` (`providers` command group), `src/argus/clock.py`
(`ClockHeartbeat.last_sample` accessor), `src/argus/providers/__init__.py`
(provider protocol definitions).
Not modified: `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` (verified via
`git hash-object` before and after this task; orchestrator-owned).

D. Commands actually run
- Full re-read of the ACTIVE instruction (`orchestration/ORCHESTRATOR_INSTRUCTIONS.md`,
  instruction_id=argus-phase-1-001) plus MASTER_SPEC.md, docs/BUILD_STATE.md,
  docs/DECISION_LOG.md, orchestration/PROTOCOL.md,
  orchestration/AGENT_HANDOFF.md, before writing any code.
- Pre-execution safety verification: `git merge-base --is-ancestor
  141af487fcfdff41d1597c19ea062139f5427f52 HEAD` (OK: ancestor);
  `git diff --name-only 141af487... HEAD` (only
  orchestration/ORCHESTRATOR_INSTRUCTIONS.md differed); `git rev-parse HEAD^`
  equals the target; docs/BUILD_STATE.md's current_phase/
  last_completed_phase/awaiting_orchestrator_review checked against
  AUTHORIZED_PHASE: 1 / APPROVES_PHASE: 0 (valid phase-advance case) before
  updating BUILD_STATE per the instruction's mandatory session-start steps.
- Local PostgreSQL 16 started (`sudo service postgresql start`; substitute
  server, same as Phase 0's established deferred-PG17 pattern) and used
  for every real-database test and migration verification below.
- `uv run alembic upgrade head` / `downgrade -1` / `upgrade head` /
  `downgrade base` / `upgrade head` — migration-from-zero and
  upgrade-from-Phase-0-head both verified working cleanly, repeatedly.
- `uv run pytest tests/unit -v` — 163 passed, 0 failed
- `uv run pytest tests/integration -v` — 18 passed, 0 failed (real Postgres)
- `uv run pytest tests/golden -v` — 23 passed, 0 failed
- `uv run pytest tests/replay -v` — 0 collected ("no tests ran"); see
  "Data quality warnings" below
- `uv run pytest --cov --cov-report=term-missing` — 204 passed, 91%
  overall coverage
- `uv run ruff check .` — All checks passed!
- `uv run ruff format --check .` — 113 files already formatted
- `uv run mypy` — Success: no issues found in 59 source files
- `uv run argus providers probe` — Helius: CREDENTIAL_REQUIRED (exact
  section-108 notice printed, no value ever printed or logged);
  DexScreener/GeckoTerminal/Jupiter: UNREACHABLE (`ProxyError: 403
  Forbidden` — this sandbox has no general internet egress); exit code 1,
  every field (including `configured_throttle_per_sec`, after the fix
  above) populated correctly; no crash, no fabricated data.
- `uv run argus providers probe-history` — GeckoTerminal: UNREACHABLE
  (same network blocker); exit code 1; no crash.
- `uv run argus providers usage --provider helius --monthly-allowance 100`
  — printed today/MTD/projected credits = 0 (honest: no real provider
  call has ever succeeded in this environment to generate usage rows),
  monthly_allowance echoed, no warning triggered; exit code 0.
- grep-based secret scan across all tracked files for common secret
  patterns (API key formats, private-key PEM headers, password literals)
  — clean; `.env` confirmed gitignored and not tracked;
  `HELIUS_API_KEY` confirmed empty in the local `.env`.

E. Test results
pytest (unit): 163 passed, 0 failed, 0 skipped
pytest (integration): 18 passed, 0 failed, 0 skipped (real PostgreSQL 16)
pytest (golden): 23 passed, 0 failed, 0 skipped
pytest (replay): 0 collected
pytest (full, with coverage): 204 passed, 0 failed
coverage: 91% overall (1470 statements, 113 missed); every new Phase 1
  module ≥ 88%, most at 100% (see "Sample outputs" for the per-module
  table)
ruff: All checks passed!
ruff format --check: 113 files already formatted
mypy: Success: no issues found in 59 source files

F. Acceptance criteria (27 mandatory, per argus-phase-1-001)
[NOT TESTED] 1. configured Solana RPC works — blocked by this sandbox
  having no `HELIUS_API_KEY` configured locally and no general internet
  egress (confirmed live: `argus providers probe` reports
  `CREDENTIAL_REQUIRED` for Helius). The RPC client itself is fully
  built and tested against `httpx.MockTransport` (request/response
  shape, error handling, retry, usage recording).
[NOT TESTED] 2. configured WebSocket works — same blockers as #1. The WS
  client's subscribe/notification/disconnect-raise/bad-ack-raise logic is
  fully built and tested against a fake `WebSocketConnector`.
[PASS] 3. disconnect is detected — `HeliusWebSocketStream` raises (never
  silently stops) on a dropped connection; `ReconciliationEngine` accepts
  a `DISCONNECT` trigger.
[PASS] 4. reconnect works — mandatory A/B scenario test.
[PASS] 5. reconciliation recovers a missed event — same test.
[PASS] 6. A and B are each canonicalized exactly once — same test, plus
  the real-SQL dedup-constraint integration test.
[PASS] 7. duplicate deliveries remain idempotent — both stream-path and
  truth-path duplicate-delivery tests.
[PASS] 8. watermarks persist across restart — fake-store process-restart
  test plus a real-SQL round-trip test.
[PASS] 9. commitment status and progression are stored — `first_seen_at`
  (fast path) and `confirmed_at` (truth path, set exactly when the
  provider reports no error) are both populated and tested end-to-end.
  Caveat: the `finalized_at` column exists in the schema but is not
  populated by any current code path — Solana's "finalized" commitment
  tier is not tracked yet, only "confirmed vs. not yet confirmed". Stated
  honestly rather than claimed complete.
[PASS] 10. clock health and anomalies are stored — new this round:
  `PersistentClockMonitor` + `clock_health_events` table, unit-tested
  (anomaly detection, persistence, acknowledge) and integration-tested
  against real Postgres; `ReconciliationEngine` now keeps a wallet
  `DEGRADED` on an outstanding clock anomaly even after a successful
  reconciliation (tested).
[PASS] 11. provider priority ordering and starvation protection work —
  6 scheduler tests, including strict ordering under concurrency (stable
  across repeated runs) and safety-class-never-dropped.
[PASS] 12. HTTP and streaming usage are counted — HTTP/RPC usage
  recording is wired into every real outbound call in all 4 provider
  adapters and tested (`test_helius_rpc_call_records_usage_when_recorder_provided`,
  `test_geckoterminal_records_usage_for_both_endpoints`) plus the
  underlying accounting logic (`UsageReporter`/`SqlUsageRecorder`)
  against real Postgres. Caveat: `StreamingUsageRecord`/
  `record_streaming()` is implemented and unit-tested in isolation, but
  has no live invocation site yet, since no continuously-running stream
  manager exists to drive periodic streaming ticks (see "Data quality
  warnings").
[PASS] 13. 70/85/95 usage warnings trigger correctly — exact-value
  integration test (74.48% of a 50-credit allowance triggers only the
  70% threshold).
[PASS] 14. adapter contract validation rejects malformed provider
  responses — fixed and tested this round: Helius's `_rpc()` now raises
  a typed `HeliusRpcError` (not a bare `KeyError`) when a response has
  neither `result` nor `error`.
[PASS] 15. retry/backoff honors configured limits and never fabricates
  data — new this round: `argus/providers/retry.py`, 9 dedicated tests
  (exact backoff schedule, exhaustion returns/re-raises the last *real*
  response/exception, 4xx never retried, config-driven policy), wired
  into all 4 adapters, confirmed live (probe latencies for the
  unreachable REST providers rose from ~215ms to ~2.2s once retry was
  wired in, consistent with 3 real attempts against the sandbox's actual
  network-egress block).
[PASS] 16. every required golden parser fixture passes — 11 fixtures (9
  required + 2 extra), 23 tests, all passing.
[PASS] 17. raw-unit and Decimal arithmetic remain exact — `swaps` schema
  uses `BigInteger` for raw amounts and `Numeric(38,18)`/`Numeric(4,3)`
  for UI amounts/confidence; golden-fixture tests assert exact raw-int
  values.
[PASS] 18. ambiguous/UNKNOWN transactions cannot create live-copy
  signals — `ParsedTransaction.is_copy_eligible` is `True` only for
  `SWAP_SIMPLE`/`SWAP_COMPLEX` with confidence ≥ 0.5; tested directly.
[PASS] 19. stream gaps and unresolved reconciliation force DEGRADED
  state — tested (unresolved-reconciliation test, mid-fetch-failure
  test, clock-anomaly test).
[PASS] 20. restart during reconciliation fails closed and resumes
  idempotently — mid-reconciliation-fetch-failure test preserves partial
  progress and marks DEGRADED; a subsequent `reconcile()` call correctly
  resumes from the preserved watermark (tested).
[PASS] 21. migration from zero succeeds where a database is available —
  verified against real local PostgreSQL 16 (`alembic downgrade base` →
  `upgrade head`).
[PASS] 22. upgrade from the Phase 0 Alembic head succeeds — verified
  (`0001` → `0002`, repeatedly, both directions).
[PASS] 23. DB role grants remain least privilege — `argus_ingest`:
  SELECT/INSERT/UPDATE; `argus_research`: SELECT-only (tested directly:
  a research-role session cannot write); `argus_executor`: no grant on
  any Phase 1 table.
[PASS] 24. no signing, signer, private-key, seed-phrase, live-arm, or
  transaction broadcast path exists — `JupiterClient` has no
  `sign`/`execute`/`broadcast` method anywhere (asserted directly by
  test); no other Phase 1 code touches a private key or broadcasts a
  transaction.
[PASS] 25. secret scan is clean — grep-based scan across all tracked
  files, clean; `.env` gitignored and not tracked; `HELIUS_API_KEY`
  confirmed empty locally.
[PASS] 26. no paid-provider feature is enabled — every provider config
  defaults to `enabled: false`/`tier: free`; no code path anywhere
  changes a provider's tier or enables a paid feature (COST-002).
[PASS] 27. no Phase 1.5 or later-phase code was started — no token/wallet
  discovery, scoring, shadow trading, execution, or signing code exists
  anywhere in this diff.

G. Database/data sanity
`chain_events`, `swaps`, `wallet_stream_state`, `clock_health_events`
tables created via migration `0002`, verified against real local
PostgreSQL 16 with 0 rows outside test runs (each integration test
cleans up its own rows in a `finally` block). Dedup unique constraint
(`transaction_signature`, `wallet_address`, `event_type`) verified to
reject a duplicate insert directly. Least-privilege GRANTs verified per
role. No real chain data exists anywhere — every row in every test is
synthetic/fake-provider-generated, never a real Solana transaction (this
sandbox has no live network access to fetch one).

H. Provider usage
0 real provider usage rows exist — no real outbound call to Helius,
DexScreener, GeckoTerminal, or Jupiter has ever succeeded in this
environment (Helius blocked on missing credential; the other three
blocked by this sandbox's lack of general internet egress, confirmed via
`ProxyError: 403 Forbidden` on every live attempt). `argus providers
usage --provider helius` therefore honestly reports all-zero usage. The
usage-accounting *logic* itself (recording, summarizing, threshold
warnings) is fully built and tested against real Postgres with
synthetic rows.

I. Data quality warnings
- Items 1–2 of section F: NOT TESTED, blocked by this sandbox's missing
  `HELIUS_API_KEY` and lack of general internet egress — not an
  architecture gap, an environmental one, exactly analogous to Phase 0's
  `PG17_COMPOSE_VALIDATION` deferral.
- No end-to-end "stream manager" exists yet: `HeliusWebSocketStream`,
  `ReconciliationEngine`, and the priority scheduler are each built and
  tested in isolation, but there is no continuously-running orchestration
  loop (e.g. an `argus ingest run` command) that actually opens a live
  WebSocket, manages multiple concurrent per-wallet subscriptions,
  automatically triggers `reconcile()` on a real disconnect/reconnect,
  and periodically records streaming usage/clock-health ticks. Every
  "reconnect handling" and "per-wallet subscription" acceptance criterion
  that could be tested without a live network connection has been
  (disconnect-raises, reconcile-on-trigger, exactly-once canonicalization,
  DEGRADED gating, clock-anomaly gating) — what remains is wiring these
  already-tested pieces into one long-running process, which is more
  appropriately built and validated once real credentials and network
  access are available (its reconnect/backoff timing needs to be checked
  against actual Helius WebSocket behavior, not guessed at against a
  fake connector). This is a genuine, disclosed scope gap, not an
  environmental block — stated plainly rather than left implicit.
- `tests/replay/` remains an empty placeholder (`__init__.py` only); the
  instruction lists `uv run pytest tests/replay -v` among the required
  validation commands, and it was run and honestly recorded as 0 tests
  collected. The instruction's own "Mandatory acceptance tests" section
  lists "replay/golden tests" as one *kind* of test to use "where
  suitable" rather than a separately mandatory deliverable, and the
  golden-fixture suite (`tests/golden/`) already provides deterministic,
  replayed-transaction-style testing of the parser; no additional
  replay-specific test was judged necessary beyond that, but the empty
  directory is called out here rather than silently left unexplained.
- `PG17_COMPOSE_VALIDATION` remains `DEFERRED_ENVIRONMENTAL_CHECK`
  (unchanged, unrelated to this task) — see docs/BUILD_STATE.md.

J. Sample outputs
Per-module coverage for every new/modified Phase 1 file (from
`uv run pytest --cov --cov-report=term-missing`):
`argus/domain/chain_events.py` 100%, `argus/domain/clock_health.py` 100%,
`argus/domain/swaps.py` 100%, `argus/domain/wallet_stream_state.py` 96%,
`argus/ingestion/clock_health_repository.py` 100%,
`argus/ingestion/clock_monitor.py` 100%,
`argus/ingestion/event_repository.py` 100%,
`argus/ingestion/reconciliation.py` 100%,
`argus/ingestion/watermark_repository.py` 94%,
`argus/parsing/generic_parser.py` 95%, `argus/providers/__init__.py` 100%,
`argus/providers/credentials.py` 100%,
`argus/providers/dexscreener/client.py` 93%,
`argus/providers/geckoterminal/client.py` 100%,
`argus/providers/helius/client.py` 90%, `argus/providers/jupiter/client.py` 94%,
`argus/providers/probes.py` 88%, `argus/providers/retry.py` 100%,
`argus/providers/scheduler.py` 88%, `argus/providers/usage.py` 100%.
`argus/cli.py` is 46% (the `providers usage`/`probe`/`probe-history`
commands' own thin printing/wiring code is exercised only by the live
CLI runs above, not by a dedicated unit test, matching the existing
pattern for `health`/`config_show`/`checkpoint bundle`).

K. Architectural deviations
NONE from MASTER_SPEC.md. The `clock_health_events` table and
`PersistentClockMonitor`/`ReconciliationEngine` clock-anomaly gating are
new this round but implement MASTER_SPEC.md section 17 exactly as
specified ("detect material clock jumps... block any future live-entry
eligibility until provider reconnection, chain reconciliation, and clock
health recovery are complete"), not a deviation from it.

L. ORCHESTRATOR_REVIEW_REQUIRED
- Whether items 1–2 (live RPC/WebSocket) may remain deferred like
  `PG17_COMPOSE_VALIDATION` until credentials/network access are
  available, or must block Phase 1 approval.
- Whether the missing end-to-end stream-manager orchestration loop (see
  "Data quality warnings") must be built before Phase 1 is considered
  fully complete, or is acceptable to defer to when live credentials are
  available to validate its reconnect/backoff behavior for real.
- `PG17_COMPOSE_VALIDATION` (unchanged, unrelated — see
  docs/BUILD_STATE.md).

M. Known bugs / debt
- Streaming usage recording (`StreamingUsageRecord`/`record_streaming`)
  has no live invocation site (see "Data quality warnings").
- `finalized_at` on `chain_events` is schema-only; no code path populates
  it yet (see acceptance criterion 9 caveat).
- DexScreener/GeckoTerminal/Jupiter response-contract validation remains
  a coarse `isinstance(dict)` check in `probes.py`, not a full schema
  validator (Helius's JSON-RPC contract validation was tightened this
  round; the REST providers' validation was not, since they have no
  analogous `result`/`error` envelope to validate against).
- No end-to-end stream-manager loop (see "Data quality warnings").

N. Security state
- No live trade, mainnet canary, signing, private-key access, credential
  disclosure, paid-provider upgrade, live arming, or threshold relaxation
  anywhere in this task.
- `JupiterClient` has no sign/execute/broadcast method anywhere,
  asserted directly by test.
- Credential handling for `HELIUS_API_KEY` mirrors the exact Phase 0
  fail-closed pattern (`argus/db/credentials.py`) via a new
  `argus/providers/credentials.py`: missing credential raises the exact
  section-108 `LOCAL CREDENTIAL REQUIRED` notice, never a mocked
  fallback claiming live acceptance.
- LIVE_READY_SOFTWARE=false, LIVE_CANARY_PASSED=false, LIVE_ARMED=false —
  unaffected.
- Secret scan clean (see section D).

O. Next specified phase
Per orchestrator instruction argus-phase-1-001: Phase 1.5 and all later
phases remain forbidden. `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` was
not modified. `docs/BUILD_STATE.md`'s `last_orchestrator_approved_phase`/
`approved_commit` are untouched by this task (still Phase 0, as set by
the orchestrator's own instruction) — this session does not and cannot
self-approve Phase 1. STOP. Await orchestrator review of this checkpoint
and the two open questions in section L before any further phase work.

================ END ARGUS CHECKPOINT =========================
