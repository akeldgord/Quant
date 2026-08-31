# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0008-phase-1-remediation-1
UTC_TIMESTAMP: 2026-08-31T06:47:00Z
CURRENT_COMMIT: 83bb38497ac3af1402f38dabee6858e00ce2e9fb
CURRENT_PHASE: 1
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-1-remediation-001
CHECKPOINT_PATH: orchestration/checkpoints/phase_1_remediation_1.md
BUNDLE_PATH: orchestration/bundles/phase_1_remediation_1.txt
TEST_STATUS: unit 212/212 passed; integration 19/19 passed (real PostgreSQL 16); golden 23/23 passed; replay 6/6 passed (was 0 collected before this round); full suite 260/260 passed, 84% coverage; ruff clean; mypy clean; alembic downgrade-to-base/upgrade-to-head clean
WORKING_TREE: clean (verified via `git status --porcelain` before this commit)
ORCHESTRATOR_REVIEW_REQUIRED: acceptance criterion 15 (authenticated real-chain golden fixtures) is honestly NOT TESTED/blocked — this sandbox has no general internet egress and no already-available safe source of authentic transaction data (see orchestration/checkpoints/phase_1_remediation_1.md section E item 15 and docs/DECISION_LOG.md); resolving it requires either running the acquisition step from an environment with real network access, or an explicit orchestrator decision on whether the existing synthetic-but-schema-accurate fixtures are an acceptable permanent substitute for this one criterion. PG17_COMPOSE_VALIDATION (deferred, unrelated, unchanged) still open — see docs/BUILD_STATE.md.

## Work completed

Executed orchestrator instruction `argus-phase-1-remediation-001` in
full: an independent audit rejected the prior Phase 1 self-assessment
(`PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`) as overstated, citing 10
concrete findings. All 10 are remediated with real, tested code:

1. **No production ingestion orchestration loop → built.** New
   `IngestionManager` (`src/argus/ingestion/manager.py`) and CLI
   (`argus ingest run`) compose the WebSocket stream, reconciliation
   engine, and clock monitor into real, restart-safe, per-wallet runtime
   behavior for the first time. Every dependency is injectable; a
   `--test-mode` path (`NullLiveStream`/`NullChainProvider`/in-memory
   repositories) proves the CLI's own wiring with zero credential, zero
   network, zero DB.
2. **Truth-path pagination could lose events → fixed.**
   `ReconciliationEngine._fetch_all_pages()` implements real Solana
   `before`/`until` cursor pagination, fails DEGRADED on a
   non-progressing cursor or safety-ceiling breach, persists the
   watermark per item via an injectable `commit_hook`, and never advances
   past an unfetched item.
3. **Commitment progression not actually stored → fixed.** New
   append-only `commitment_observations` table (migration `0003`)
   replaces the `confirmed_at`/`finalized_at` columns, which the dedup
   unique constraint always blocked from ever being set. A tie-breaking
   bug in the new `derive_current_state()` was found and fixed before
   reaching committed code.
4. **Parsing not connected to persistence → fixed.** `reconcile()` now
   parses every fetched transaction and persists the versioned
   classification via a new `SqlSwapRecorder`, linked to the canonical
   event through a new `RecordOutcome(event_id, is_new)` return type that
   recovers the real event id on a duplicate delivery.
5. **Golden evidence is synthetic → honestly PARTIAL.** Re-confirmed via
   direct `curl` and the proxy's own status endpoint that this sandbox
   has no reachable chain-data or market-data host. Kept the 11 existing
   synthetic fixtures, added `tests/golden/fixtures/PROVENANCE.md`
   labeling every one individually, and report acceptance criterion 15 as
   NOT TESTED/blocked rather than PASS, per the instruction's own
   explicit fallback for this case.
6. **Weak adapter contract validation → fixed.** New
   `argus.providers.contract` typed validation helpers, used across every
   adapter; full structural validation of Helius RPC/WS envelopes.
7. **Usage accounting misses transport failures → fixed.** New
   `send_with_usage()` centralizes retry+usage-recording so transport
   exhaustion still produces a terminal usage row; streaming usage is now
   wired into the manager's real call sites.
8. **Scheduler starvation not proven → fixed.** Dispatch-count-bounded
   aging guarantees P0-P3 service under a sustained stream of
   same-or-higher-priority arrivals; constructor validation and
   cancellation-safety hardening added.
9. **Replay coverage absent → fixed.** 6 real `tests/replay` tests (was 0
   collected), covering raw-evidence immutability, parser determinism,
   duplicate-delivery idempotency, restart recovery, deterministic
   commitment derivation, and safe re-parsing under a new parser version.
10. **Evidence/status accuracy → this handoff and the new checkpoint**
    score all 26 mandatory acceptance criteria individually (25 PASS, 1
    honestly NOT TESTED) rather than asserting a blanket PASS.

Full per-finding detail, the complete 26-item disposition, and every
command actually run: `orchestration/checkpoints/phase_1_remediation_1.md`.

## Important findings

- Two genuine bugs were found and fixed during this round, both caught by
  dedicated regression tests before reaching committed code: a
  commitment-state tie-breaking bug in `derive_current_state()` (same
  rank + same timestamp picked the wrong entry), and a missing-real-
  event-id-on-duplicate bug (a duplicate chain-event delivery had no way
  to recover the real, already-persisted event id, which would have
  violated a foreign key or orphaned a dependent row).
- This sandbox still has no general internet egress (re-confirmed via
  direct `curl` to two real hosts and the proxy's own status endpoint,
  which reports an explicit gateway-level policy denial for both) — this
  is the same environmental limitation disclosed in every prior handoff
  on this project, not new.
- `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is unchanged — still the
  orchestrator's `argus-phase-1-remediation-001` instruction,
  `STATUS: ACTIVE`. This task did not and could not self-approve any
  phase; `last_orchestrator_approved_phase` in `docs/BUILD_STATE.md`
  remains `0`, and the Phase 0 `approved_commit` is unchanged.
- All changes stayed strictly within the existing Phase 1 module set
  (`src/argus/domain`, `src/argus/ingestion`, `src/argus/providers`,
  `src/argus/cli.py`) — confirmed via `git diff --stat` against the
  pre-remediation target commit. No Phase 1.5 or later-phase code (no
  DB-backed wallet discovery, no trade/copy-execution path) was started.

## Failures or limitations

- **Acceptance criterion 15 (authenticated real-chain golden fixtures):
  NOT TESTED / BLOCKED.** This sandbox has no general internet egress and
  no already-available safe source of authentic transaction data. The 11
  existing fixtures remain synthetic, individually labeled as such in
  `tests/golden/fixtures/PROVENANCE.md`. This is not claimed as PASS.
- **Live Helius RPC/WebSocket connectivity: NOT TESTED** (unchanged from
  every prior handoff — no `HELIUS_API_KEY` configured and no general
  internet egress in this sandbox). The real `WebSocketsConnector`
  wrapper is built but has never been exercised against a live socket.
- **`PG17_COMPOSE_VALIDATION` remains `DEFERRED_ENVIRONMENTAL_CHECK`**
  (unchanged, unrelated to this round — see `docs/BUILD_STATE.md`).
- Coverage on a small number of modules is low for structural reasons,
  not because the behavior is unverified: `src/argus/ingestion/test_mode.py`
  (0% via `--cov`) and `src/argus/providers/helius/websocket_connector.py`
  (0% via `--cov`) are both exercised through the real CLI process in the
  offline smoke test and (for the connector) only ever meaningfully
  testable against a live credential — never faked as "tested" in either
  case. See `orchestration/checkpoints/phase_1_remediation_1.md` section C
  for the full coverage breakdown.

## Deferred checks

- Acceptance criterion 15 — real-chain golden fixtures (see
  `ORCHESTRATOR_REVIEW_REQUIRED` above and checkpoint section E item 15).
- Live Solana RPC/WebSocket connectivity against a real `HELIUS_API_KEY`
  and real network access.
- `PG17_COMPOSE_VALIDATION` (unchanged, unrelated).

## Exact next action requested from orchestrator

Review this remediation round's evidence
(`orchestration/checkpoints/phase_1_remediation_1.md` and
`orchestration/bundles/phase_1_remediation_1.txt`) against the 26
mandatory acceptance criteria in instruction
`argus-phase-1-remediation-001`, and resolve the one open question:
whether acceptance criterion 15's environmental NOT TESTED/blocked status
may be accepted as a permanent disposition for this specific criterion
(the existing synthetic fixtures standing in for it), or whether
acquisition must be retried from an environment with real network access
before Phase 1 may be approved. If accepted, write the next `ACTIVE`
instruction into `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`
(`TARGET_COMMIT` pinned to the exact commit named in this handoff) to
authorize the next piece of work. Phase 1.5 and all later phases remain
forbidden until then. Until a new instruction exists, the watcher (if
running) takes no action beyond logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** unchanged from prior handoffs — if you
cloned/fetched this branch before 2026-08-30T22:35 UTC, re-clone or
`git fetch --all && git reset --hard origin/claude/argus-folder-setup-77ahrk`
rather than merging/rebasing the old (pre-rewrite) history.
