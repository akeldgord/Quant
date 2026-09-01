# Phase 4 REPLAY lifecycle demonstration

Orchestrator instruction `argus-phase-4-001`, "Phase 4 acceptance and evidence":
"One complete REAL or REPLAY lifecycle is required... Demonstrate through normal
production wiring: leader executes -> ARGUS observes -> source tx confirms ->
shadow signal -> entry quote -> shadow fill -> mark outcome -> reverse
executable quote."

**REPLAY -- NOT PROSPECTIVE ALPHA EVIDENCE.**

Run via `uv run python scripts/argus_phase4_replay_demo.py` against real
Postgres 16 at migration head `0016`, using the `argus_ingest` DB role exactly
as production code paths do. Raw output captured verbatim at
`orchestration/phase_4/evidence/replay_demo_results.json`.

## Production wiring used

Every step below calls the exact same `argus.shadow.*`/`argus.reports.daily`
service functions the real `argus prospective run` / `argus shadow
run-entry-probes` / `argus shadow run-reverse-probes` / `argus shadow
run-mark-outcomes` / `argus report daily` CLI commands call internally --
never a parallel test-only reimplementation. The CLI's `shadow run-*` commands
hardwire the real `JupiterClient`/`DexScreenerClient` HTTP adapters (correct
for production use, with no override flag); this sandbox has no live network
access to those endpoints and no paid-provider credentials, and the frozen
acceptance table itself requires "controlled clocks and deterministic
providers" for this demonstration. This script therefore calls the identical
service functions with a deterministic provider/clock substituted at the same
dependency-injection seam the CLI uses.

## Data source and honesty disclosure

Two distinct evidence classes are used, and are never conflated in the data
recorded:

1. **Real evidence** -- "leader executes" is grounded in a genuine,
   independently-verified mainnet pump.fun buy transaction
   (`tests/golden/fixtures/real/real_mainnet_sol_to_token_swap.json`, slot
   `290506981`, signature
   `4U8kypMuCUCkR6teu2Vn8ujaEJUR3dcUU5QExZxSMMeJ5fRTvYfWs5M5AB9yNjjHKAQ4w433QVyUivc3Pp8gvG1R`,
   signer `EfbbhahGNuhqEraRZXrwETfsaKxScngEttdQixWAW4WE`; provenance and
   upstream citation in `tests/golden/fixtures/real/PROVENANCE.md`), parsed by
   the real, unmodified `argus.parsing.generic_parser.parse_transaction` --
   never a hand-fabricated `Swap` row. Its own output (`SWAP_SIMPLE`,
   confidence `1.000`, real input/output mints and raw amounts) is what gets
   persisted. "ARGUS observes" / "source tx confirms" persist that genuine
   parser output as real `chain_events`/`commitment_observations`/`swaps`
   rows via the same ORM models the real reconciliation engine writes.
2. **REPLAY / synthetic evidence** -- the shadow-signal wallet tier/score, the
   entry-quote/reverse-quote/mark-price responses, and the clock values that
   produced them are deterministic, injected fakes (`QueuedExecutionProvider`,
   `QueuedMarketDataProvider`, a scripted `Clock` subclass) -- never a live
   network call. These are not a recovered historical trading opportunity for
   this transaction; they demonstrate the real service functions' own
   request/response/outcome recording behavior end-to-end.

## Steps executed (in order, via the real service functions)

| # | Step | Function called | Result |
|---|---|---|---|
| 1 | Leader executes | `argus.parsing.generic_parser.parse_transaction` | `SWAP_SIMPLE`, confidence `1.000`, real fixture |
| 2 | ARGUS observes | `ChainEvent` persisted (`first_seen_at`) | `2024-09-18T09:22:19Z` |
| 3 | Source tx confirms | `CommitmentObservation` persisted (`CONFIRMED`) | `2024-09-18T09:22:21Z` |
| 4 | Shadow signal | `argus.shadow.monitor.run_prospective_monitoring_pass` | 1 prospective event + 1 shadow intent, 6 entry-delay probes scheduled (1s/5s/15s/30s/60s/300s) |
| 5 | Entry quote | `argus.shadow.quote_jobs.run_due_entry_probes` | `SUCCESS`; requested at `+0.7s`, target was `1s` -- actual `scheduling_delay_seconds=0.7`, `latency_ms=100` recorded, never a fabricated `1s` |
| 6 | Shadow fill | (same call, position created on first successful probe) | `ShadowPosition` opened, `entry_price_usd=1.00` |
| 7 | Mark outcome | `argus.shadow.mark_jobs.run_due_mark_outcomes` | `RECORDED`, mark price `1.50` (+50% vs entry) |
| 8 | Reverse executable quote | `argus.shadow.quote_jobs.run_due_reverse_probes` | `NO_ROUTE` -- same position, same horizon (`5m`), outcome distinct from the positive mark |
| 9 | Notification | `argus.telegram.notifier.TelegramNotifier` + `FakeTelegramTransport` | 1 `SHADOW_EVENT` message recorded in-memory, never sent externally |
| 10 | Daily report | `argus.reports.daily.build_daily_report` | real queried counts over the seeded window (below) |

## Frozen-gate proofs demonstrated by this one run

- **Quote actual latency recorded**: the entry probe's `1s` target actually
  responded at `+0.7s`/`+0.8s` (a controlled, non-`1s` scheduling delay) --
  `scheduling_delay_seconds=0.7` and `latency_ms=100` are the real recorded
  values, never a false `"1s"`.
- **Executable return distinct from mark**: the same `ShadowPosition` has a
  `RECORDED` mark outcome showing +50% and a `NO_ROUTE` reverse-executable
  outcome at the same `5m` horizon -- two distinct, independently persisted
  rows, never collapsed into one P&L figure.
- **Unsellable state preserved**: `NO_ROUTE` is a real, queryable
  `shadow_quote_probes.outcome` value, not a dropped row or a fabricated
  successful quote.
- **Complete phase deliverables/lifecycle**: all eight named steps plus quote
  jobs, reverse/mark outcomes, the fake notification, and the daily report
  ran in one integrated pass through the real production service layer.

## Daily report (real queried counts, `argus report daily`'s own function)

Window `2024-09-17T09:28:24.800Z` .. `2024-09-18T09:28:24.800Z` (anchored to
this REPLAY run's own deterministic timeline, not wall-clock "today" --
`build_daily_report` takes an explicit `now`, exactly as the real CLI command
does when given one):

```json
{
  "tracking": {"tracked_wallets": 1, "wallet_trades": 1, "stream_gaps_degraded_wallets": 0, "reconciliations_in_window": 0},
  "signals": {"signals": 1, "confirmations": 1, "convergence_events": "NOT_IMPLEMENTED"},
  "shadow": {"shadow_trades_opened_in_window": 1, "matured_executable_outcomes_in_window": 1, "matured_mark_outcomes_in_window": 1, "open_shadow_positions_total": 1, "mfe_mae": "NOT_IMPLEMENTED"},
  "data_quality": {"ambiguous_swaps_in_window": 0, "missing_mark_observations_overdue": 0, "low_completeness_wallets": "NOT_IMPLEMENTED", "provider_gaps": "NOT_IMPLEMENTED"}
}
```

`live` is unconditionally `{"ready_state": false, "canary_state": false,
"armed_state": false, ...}` -- unchanged by this or any Phase 4 code path, per
the instruction's absolute authorization boundary.

## Database state after the run

This script deletes the wallet/event/swap/prospective-event/shadow-intent/
position/probe/outcome rows it created immediately after capturing the JSON
snapshot above, so this one-off demonstration run never contaminates the
shared dev database's unscoped due-probe queries used by the regression
suite (`tests/integration/test_shadow_phase4.py` et al.) -- mirroring why
`tests/integration/test_migrations.py` uses its own disposable scratch
database instead of the shared one. The JSON file and this document are the
durable evidence; re-running the script reproduces the same lifecycle
deterministically (a fresh UUID per run, identical timestamps/outcomes).

## Full raw command run

```
$ uv run python scripts/argus_phase4_replay_demo.py
```

Exit code `0`. Full stdout is the JSON object saved verbatim at
`orchestration/phase_4/evidence/replay_demo_results.json`.
