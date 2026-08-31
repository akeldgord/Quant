# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0007-phase-1
UTC_TIMESTAMP: 2026-08-31T04:59:22Z
CURRENT_COMMIT: 28a88f74d28e70542050f5d5e8d9a9d139f26bb8
CURRENT_PHASE: 1
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-1-001
CHECKPOINT_PATH: orchestration/checkpoints/phase_1.md
BUNDLE_PATH: orchestration/bundles/phase_1.txt
TEST_STATUS: unit 163/163 passed; integration 18/18 passed (real PostgreSQL 16); golden 23/23 passed; replay 0 collected; full suite 204/204 passed, 91% coverage; ruff clean; mypy clean
WORKING_TREE: clean (verified via `git status --porcelain` before and after this commit)
ORCHESTRATOR_REVIEW_REQUIRED: whether acceptance criteria 1-2 (live Solana RPC/WebSocket) may remain deferred like PG17_COMPOSE_VALIDATION until credentials/network access are available, and whether the missing end-to-end stream-manager loop must be built before Phase 1 is considered fully complete — see orchestration/checkpoints/phase_1.md section L; PG17_COMPOSE_VALIDATION (deferred, unrelated) still open — see docs/BUILD_STATE.md

## Work completed

Executed orchestrator instruction `argus-phase-1-001` in full: implemented
Phase 1 (live Solana chain data acquisition and deterministic canonical
parsing) against the fixed 27-item mandatory acceptance checklist.

1. **Helius standard RPC + WebSocket adapter** — `HeliusRpcClient`
   (`ChainProvider`) and `HeliusWebSocketStream` (`LiveChainStream`),
   credential-gated on `HELIUS_API_KEY` with the exact section-108
   `LOCAL CREDENTIAL REQUIRED` notice on a missing key. The WebSocket
   stream never treats a dropped connection as "no new activity" — any
   read/connect failure raises out of the async generator.
2. **DexScreener, GeckoTerminal, Jupiter adapters** — current market
   state, historical-OHLCV-only, and quote/unsigned-order-construction
   only respectively. `JupiterClient` has no sign/execute/broadcast
   method anywhere (asserted directly by test).
3. **Fast-path/truth-path reconciliation** (`ReconciliationEngine`) —
   implements the mandatory deterministic disconnect/reconnect scenario
   (A observed → disconnect → B occurs while disconnected → reconnect →
   reconciliation discovers B; final ledger contains each exactly once),
   repeated across process-restart and duplicate-delivery variants,
   against both in-memory fakes and a real Postgres database.
4. **Durable clock-anomaly detection wired into reconciliation gating**
   (new this round) — `PersistentClockMonitor` wraps the existing Phase 0
   `ClockHeartbeat` and persists every wall/monotonic comparison to a new
   `clock_health_events` table; `ReconciliationEngine` now keeps a wallet
   `DEGRADED` on an outstanding clock anomaly even when reconciliation
   itself succeeds, per MASTER_SPEC.md section 17's three independent
   conditions (provider reconnection + chain reconciliation + clock
   health recovery).
5. **Immutable `chain_events` ledger** plus `swaps`, `wallet_stream_state`,
   `clock_health_events` — UUID event IDs, `first_seen_at`/`confirmed_at`/
   `finalized_at` kept distinct, dedup unique constraint on
   `(transaction_signature, wallet_address, event_type)`, least-privilege
   GRANTs matching the Phase 0 pattern.
6. **Generic balance-delta swap parser** — all 7 required classifications,
   11 sanitized golden fixtures (9 required categories + 2 extra). A real
   `TOKEN_CREATE` misclassification bug was found and fixed before any
   test existed (an ordinary first-buy-of-a-new-mint swap was wrongly
   classified as `TOKEN_CREATE`); a regression test documents the exact
   failure mode. `is_copy_eligible` is mechanically `False` for any
   ambiguous/`UNKNOWN` result.
7. **Central P0–P6 priority scheduler** — strict cross-submission
   ordering verified stable under concurrency; safety classes never
   dropped; droppable classes dropped only with an explicit reason.
8. **Provider usage/cost accounting** — today/MTD/30-day-projected
   credits, 70/85/95% warnings, wired into every real outbound HTTP/RPC
   call in all 4 adapters and tested.
9. **HTTP retry/backoff** (new this round) — `argus/providers/retry.py`:
   retries only transient failures (connection errors, 5xx) with
   configurable exponential backoff; a well-formed 4xx is never retried;
   on exhaustion, the last *real* response/exception is
   returned/re-raised, never fabricated. Wired into all 4 adapters;
   confirmed live (probe latency for the unreachable REST providers rose
   from ~215ms to ~2.2s once retry started actually running against the
   sandbox's real network-egress block).
10. **Adapter contract-validation fix** (found this round) — Helius's
    `_rpc()` previously raised a bare `KeyError` on a response missing
    both `result` and `error`; now raises a typed `HeliusRpcError` naming
    the malformed response explicitly.
11. **Provider capability/history/usage probe CLI** — `argus providers
    probe`/`probe-history`/`usage`. A real bug was found and fixed:
    `_throttle()` queried a nested `providers.<name>.` config path that
    does not exist (`config/providers.yaml` merges flat), so every
    probe's `configured_throttle_per_sec` silently printed `None`.
    Confirmed fixed live: Helius=5.0/DexScreener=2.0/GeckoTerminal=1.0/
    Jupiter=2.0.

Full per-item detail and the 27-item PASS/FAIL/NOT TESTED disposition:
`orchestration/checkpoints/phase_1.md`.

## Important findings

- Two real logic bugs were found and fixed *before* being caught by any
  external review: the `TOKEN_CREATE` misclassification (parser) and the
  flat-vs-nested config path (`_throttle()`), each with a regression test
  documenting the exact failure mode.
- A SAVEPOINT bug was also caught during design review (not this task's
  code, but the underlying `SqlEventRecorder.record()` this task's
  reconciliation engine depends on): a bare `session.rollback()` on a
  duplicate-key `IntegrityError` would have wiped out prior
  successfully-flushed rows in the same multi-row `reconcile()` session,
  not just the duplicate. Already fixed and tested in an earlier session.
- This sandbox has no general internet egress (confirmed via `ProxyError:
  403 Forbidden` on every live REST call attempt) and no `HELIUS_API_KEY`
  configured (`.env` has the variable present but empty) — acceptance
  criteria 1–2 are honestly `NOT TESTED`, not fabricated as passing.
- `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is unchanged — still the
  orchestrator's `argus-phase-1-001` instruction, `STATUS: ACTIVE`. This
  task did not and could not self-approve any phase;
  `last_orchestrator_approved_phase` in `docs/BUILD_STATE.md` remains `0`.

## Failures or limitations

- **Acceptance criteria 1–2 (live Solana RPC/WebSocket): NOT TESTED.**
  Blocked by this sandbox's missing `HELIUS_API_KEY` and lack of general
  internet egress — an environmental limitation, not an architecture gap
  (the RPC/WS clients themselves are fully built and tested against
  injectable fakes).
- **No end-to-end stream-manager orchestration loop.** `HeliusWebSocketStream`,
  `ReconciliationEngine`, and the priority scheduler are each built and
  tested in isolation, but there is no continuously-running process
  (e.g. an `argus ingest run` command) that opens a live WebSocket,
  manages multiple concurrent per-wallet subscriptions, automatically
  triggers `reconcile()` on a real disconnect/reconnect, and periodically
  records streaming usage/clock-health ticks. This is a genuine,
  disclosed scope gap — not an environmental block — more appropriately
  built and validated once real credentials/network access exist to
  check its reconnect/backoff timing against actual Helius WebSocket
  behavior rather than guessing at it against a fake connector.
- **Streaming usage recording has no live invocation site.**
  `StreamingUsageRecord`/`record_streaming()` is implemented and
  unit-tested in isolation but is never called by any live code path,
  since no stream-manager loop exists to drive periodic ticks (same root
  cause as the item above).
- **`finalized_at` is schema-only.** `chain_events.finalized_at` exists in
  the schema (kept distinct from `confirmed_at` per section 5/CORE-003)
  but no current code path populates it — only the confirmed-vs-not-yet-
  confirmed commitment tier is tracked, not Solana's "finalized" tier.
- **`tests/replay/` remains an empty placeholder.** The instruction lists
  `uv run pytest tests/replay -v` among the required validation commands;
  it was run and honestly recorded as 0 tests collected. No new
  replay-specific test was judged separately necessary beyond the
  golden-fixture suite, which already provides deterministic,
  replayed-transaction-style parser testing — but the empty directory is
  called out here rather than left unexplained.
- DexScreener/GeckoTerminal/Jupiter response-contract validation remains
  a coarse `isinstance(dict)` check, not a full schema validator (only
  Helius's JSON-RPC envelope was tightened this round, since it has a
  concrete `result`/`error` contract to validate against).

## Deferred checks

- `PG17_COMPOSE_VALIDATION` (unchanged, unrelated — see
  `docs/BUILD_STATE.md`).
- Live Solana RPC/WebSocket connectivity against a real `HELIUS_API_KEY`
  and real network access (acceptance criteria 1–2).
- The end-to-end stream-manager orchestration loop (see "Failures or
  limitations" above) — whether this blocks Phase 1 approval or can be
  deferred like `PG17_COMPOSE_VALIDATION` is an open question for the
  orchestrator, see `orchestration/checkpoints/phase_1.md` section L.

## Exact next action requested from orchestrator

Review this Phase 1 build's evidence (`orchestration/checkpoints/phase_1.md`
and `orchestration/bundles/phase_1.txt`) against the 27 mandatory
acceptance criteria in instruction `argus-phase-1-001`, and resolve the
two open questions in the checkpoint's section L (whether criteria 1–2's
environmental NOT TESTED status and the missing stream-manager loop block
Phase 1 approval or may be deferred). If accepted, write the next `ACTIVE`
instruction into `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`
(`TARGET_COMMIT` pinned to the exact commit named in this handoff) to
authorize the next piece of work. Phase 1.5 and all later phases remain
forbidden until then. Until a new instruction exists, the watcher (if
running) takes no action beyond logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** unchanged from prior handoffs — if you
cloned/fetched this branch before 2026-08-30T22:35 UTC, re-clone or
`git fetch --all && git reset --hard origin/claude/argus-folder-setup-77ahrk`
rather than merging/rebasing the old (pre-rewrite) history.
