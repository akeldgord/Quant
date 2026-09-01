================ ARGUS ORCHESTRATOR CHECKPOINT ================

A. Identity
PROJECT: ARGUS
MASTER_SPEC_VERSION: v2.0
SCOPE: Phase 4 consolidated remediation round 1 -- close all 7 frozen
  blocking findings (P4-R1 through P4-R7) from independent audit
  `argus-phase-4-audit-001` (`FAIL_REMEDIATION_REQUIRED`), per orchestrator
  instruction `argus-phase-4-remediation-001` (`AUTHORIZED_ACTION:
  CLOSE_CONSOLIDATED_FROZEN_PHASE_4_FINDINGS`). This is the first and only
  Phase 4 remediation round so far. Phases 0/1/1.5/2/3 retain their recorded
  approvals; all previously-closed Phase 3 findings stay closed (no
  regression). No retuning, extra review gates, or optional hardening was
  performed as if it were a blocker.
STATUS: All 7 frozen findings (P4-R1..P4-R7) are fixed with real, tested
  code. Two additional genuine gaps discovered while writing this
  remediation's own required focused tests (a missing DB grant, an
  uncaught nonfinite-Decimal comparison crash, and a real concurrency race
  found by the P4-R5 test) were also fixed at their root cause, never
  papered over. Phase 4 itself is NOT orchestrator-approved -- this
  checkpoint reports remediation completion for independent re-audit, it
  does not and cannot itself apply approval.
UTC_TIMESTAMP: 2026-09-01T16:30:00Z
GIT_COMMIT: 285f5a9fe993ff72a02ef6470ea9627952389428
TARGET_COMMIT: d95a629985668a0ba73795d3ad8daeb5534ce855
AUTHORIZED_PHASE: 4
APPROVES_PHASE: NONE

B. Finding-to-evidence disposition (one row per frozen finding)

| Finding | Fix location | Test proof | Result |
|---|---|---|---|
| P4-R1 (future information in the initial prospective snapshot) | `src/argus/shadow/prospective.py`: `_score_snapshot_as_of`/`_tier_transition_as_of` (new, cutoff-bounded queries), cutoff-parameterized `_token_state_snapshot`/`_position_size_context`/`_cluster_state_snapshot`, `_create_prospective_event` computes `cutoff = swap.first_seen_at` and resolves tier from `_tier_transition_as_of` (never `wallet.current_tier`); migration `0017` adds nullable `prospective_events.score_snapshot_id`/`tier_transition_id` provenance columns | `tests/integration/test_shadow_phase4_remediation_observation.py`: `test_snapshot_reflects_only_pre_cutoff_evidence_never_later_updates` (delayed scan after rescore/promotion/new price/new position/cluster change), `test_snapshot_with_no_pre_cutoff_score_or_tier_falls_back_honestly`, `test_evidence_dated_exactly_at_cutoff_is_included` (inclusive `<=` boundary), `test_future_rows_already_in_db_before_scan_are_ignored`, `test_position_context_uses_only_single_most_recent_history_id`, `test_exact_replay_after_later_updates_snapshot_byte_for_byte_unchanged` | FIXED |
| P4-R2 (wrong time origin for delay probes) | `src/argus/shadow/intents.py`: `_schedule_entry_delay_probes(due_origin=event.first_seen_at, created_at=now, ...)`, `create_shadow_intent_for_event` passes `due_origin=event.first_seen_at` | `test_probe_due_at_anchored_to_first_seen_at_matches_worked_example` (first_seen T, consumer T+60s, nominal 1s due T+1s; request T+62.7s records 61.7s scheduling delay, matching the audit's own worked example exactly), `test_late_confirmation_does_not_affect_probe_due_time_anchoring`, `test_monitoring_pass_replay_no_second_intent_no_rescheduled_probes` | FIXED |
| P4-R3 (consumer stalls; confirmation/replay lifecycle incomplete) | `src/argus/shadow/prospective.py`: `scan_for_new_prospective_events` excludes claimed events via `~exists().where(ProspectiveEvent.event_id == Swap.event_id)` BEFORE `LIMIT`, dedups per canonical `event_id` via `DISTINCT ON`; new `revisit_pending_confirmations`; `src/argus/shadow/monitor.py` calls it first in `run_prospective_monitoring_pass`; migration `0017` adds NOT-NULL, uniquely-constrained `prospective_events.event_id` (backfilled from `swaps.event_id`) | `test_scan_drains_all_eligible_swaps_without_starvation` (>2x limit eligible rows, repeated bounded passes drain all, new rows after saturation still picked up), `test_revisit_pending_confirmations_idempotent_and_frozen_fields_untouched`, `test_two_parser_artifacts_same_event_id_produce_only_one_prospective_event` | FIXED |
| P4-R4 (provider failures/capacity not reaching honest outcomes) | `src/argus/shadow/quote_jobs.py`: `_classify_provider_exception` (real `RequestDropped` -> `PROVIDER_CAPACITY_MISS`; real `httpx.HTTPStatusError` 429 -> capacity miss, Jupiter `COULD_NOT_FIND_ANY_ROUTE` -> `NO_ROUTE`, else honest `QUOTE_FAILED`); `_classify_quote` verifies `inAmount` identity and requires non-empty `routePlan` before `SUCCESS`/`route_present=True`; `run_due_entry_probes`/`run_due_reverse_probes` now accept and route through a real `PriorityScheduler` (`PRIORITY_CLASS_ENTRY_DELAY`/`PRIORITY_CLASS_REVERSE_EXECUTABLE`) -- the first production wiring of this previously-unused shared scheduler; `src/argus/cli.py` supplies `usage_recorder` to `DexScreenerClient` construction (previously omitted) | `tests/integration/test_shadow_quote_jobs_provider_remediation.py` (14 tests): real `JupiterClient` + `httpx.MockTransport` for success/no-route/unrecognized-error/429/unparseable-500/empty-route/notional-mismatch/malformed-impact(4 variants including literal NaN/Infinity), real `PriorityScheduler` drop-never-reaches-network + accepted-request-still-reaches-network, real usage-recorder accounting | FIXED |
| P4-R5 (overlapping workers can replace terminal evidence) | `src/argus/shadow/quote_jobs.py`/`mark_jobs.py`: migration `0017` adds `claim_generation` to both tables, incremented on claim; terminal write re-reads `SELECT ... FOR UPDATE` and verifies the observed generation still matches before publishing; an already-terminal probe/outcome now returns immediately BEFORE any provider/market-data call | `tests/integration/test_shadow_phase4_concurrency_remediation.py` (7 tests): genuine `asyncio.gather` interleaved stale-vs-fresh races for both quote probes and mark outcomes (both sides' `SELECT ... FOR UPDATE` proven to have executed before either commits), the same-intent two-probe position race (below), 3 crash-injection/atomicity/restart tests, a no-op re-execution test with an explicit provider-call counter; `tests/integration/test_shadow_phase4.py`'s existing no-op regression test strengthened with the same counter | FIXED |
| P4-R6 (report tier-direction/new-wallet counting wrong; notifier disconnected) | `src/argus/reports/daily.py`: `_build_discovery` compares `from_tier`/`to_tier` via real `WALLET_TIERS` rank order (`_TIER_RANK`), excluding `_EXIT_TIERS` from the progression comparison; `new_wallets` counts distinct `Wallet.first_discovered_at` in-window; `low_completeness_wallets`/`provider_gaps`/`mfe_mae`/`research.sample_counts` populated from real queries; `_notify_daily_summary`/`build_daily_report(notifier=...)`; `src/argus/shadow/quote_jobs.py`'s `_notify_shadow_event`/`_execute_and_record_probe(notifier=...)` | `tests/integration/test_daily_report_remediation.py` (10 tests): the audit's own worked example (S->A, DISCOVERED->WATCH, PROBATION->B) now correctly asserts 2 promotions/1 demotion (not the pre-fix "1 promotion, 2 demotions"), plus B->WATCH demotion / A->QUARANTINE quarantine-only / exit-tier neither-case; multiple discovery events for one wallet counted once; low-completeness/mfe_mae/sample_counts reflect real data; ordinary `run_due_entry_probes`/`build_daily_report` invoke the fake transport with real committed facts (never a manual `.notify()` call); notifier failure never affects the committed record | FIXED |
| P4-R7 (replay demo can delete unrelated history and consume unrelated jobs) | `scripts/argus_phase4_replay_demo.py`: rewritten onto the disposable-scratch-database pattern (`SCRATCH_DATABASE_PREFIX`, `refuse_unless_scratch_database`, `_new_scratch_database_name`, scratch DB created/migrated/dropped in `main()`, migrations run via `asyncio.to_thread` to avoid alembic's own nested-event-loop conflict) | `tests/integration/test_replay_demo_isolation.py` (8 tests): a pre-existing shared-DB wallet with real score/tier/swap history plus unrelated due `shadow_quote_probes`/`shadow_mark_outcomes` proven byte-for-byte unchanged across a clean run AND fault injection at all 4 lifecycle points (`before_create_database`/`before_migration`/`after_migration`/`before_lifecycle`); `refuse_unless_scratch_database` unit tests; scratch database confirmed actually dropped via `pg_database` after a successful run | FIXED |

Two additional gaps found and fixed beyond the audit's own 7 findings, while
writing these tests -- not weakened, not hidden:

| Gap | Fix location | Discovered by |
|---|---|---|
| `argus_ingest` role had no `UPDATE` privilege on `prospective_events` at all -- P4-R3's real `revisit_pending_confirmations` fix is correct Python but would throw `InsufficientPrivilegeError` in real Postgres the first time a genuinely late confirmation needed recording (existing/original tests never exercised this since they always seeded the CONFIRMED observation before scanning) | New additive migration `0018_phase4_remediation_1_confirmation_time_update_grant.py`: `GRANT UPDATE (confirmation_time) ON prospective_events TO argus_ingest` -- column-scoped, not the whole row; every other column stays exactly as append-only as migration 0016 intended | `test_late_confirmation_does_not_affect_probe_due_time_anchoring`/`test_revisit_pending_confirmations_idempotent_and_frozen_fields_untouched` failed with a real `InsufficientPrivilegeError` against real Postgres before this fix |
| A parsed-but-nonfinite `Decimal("NaN")`/`Decimal("Infinity")` `priceImpactPct` crashed `_classify_quote`'s `price_impact > max_impact` comparison with an uncaught `decimal.InvalidOperation` -- `Decimal(str(raw_impact))` parses these literal strings successfully (no exception at parse time), so the existing `except (ValueError, ArithmeticError)` guard around the parse never caught it; the exception propagated out of `_execute_and_record_probe`, aborting the ENTIRE claimed batch, not just the one bad probe | `src/argus/shadow/quote_jobs.py::_classify_quote`: a parsed-but-nonfinite `price_impact` (checked via `.is_finite()`) is now folded into the same honest `None`-leniency path as a genuinely unparseable string, immediately after parsing and before any comparison | `test_real_jupiter_malformed_price_impact_is_lenient_not_a_crash[literal-nan]`/`[literal-infinity]` parametrized cases, added while writing P4-R4's required real-adapter tests |
| Two different entry-delay probes for the SAME shadow intent could both resolve `SUCCESS` and race, under genuine `asyncio.gather` concurrency, to create the first `ShadowPosition` via an unguarded check-then-insert in `_execute_and_record_probe` -- the loser's `session.flush()` raised an unhandled `sqlalchemy.exc.IntegrityError`/`asyncpg.UniqueViolationError` on the position's own unique `shadow_intent_id` constraint instead of being absorbed | `src/argus/shadow/quote_jobs.py::_execute_and_record_probe`: acquires `SELECT ... FOR UPDATE` on the parent `ShadowIntent` row BEFORE the `existing_position` check, serializing concurrent creators for the same intent -- the loser blocks on the lock, then its own post-lock re-check correctly finds the winner's already-committed row | `test_two_entry_probes_racing_for_first_position_of_same_intent`, written exactly per this instruction's own P4-R5 required-test list ("two successful entry probes for one intent; exactly one position... no unhandled uniqueness failure") -- reproduced the real `IntegrityError` deterministically across 3 solo runs before the fix, passed deterministically across 3 solo runs plus a combined run after |

C. Commands actually run (raw output; PostgreSQL 16 local dev server, no
   live network/paid-provider access anywhere in this round)

```
$ uv run pytest tests/unit/test_phase3_wallet_qualification.py -q
27 passed in 0.52s

$ uv run pytest tests/integration/test_wallet_acquisition.py -q
36 passed in 3.38s

$ uv run pytest tests/integration/test_phase3_wallet_qualification.py -q
17 passed in 5.85s

$ uv run pytest tests/integration/test_shadow_phase4.py tests/integration/test_daily_report.py tests/unit/test_telegram_notifier.py -q
16 passed in 2.63s

$ uv run pytest tests/integration/test_migrations.py -q
17 passed, 33 warnings in 25.67s

$ uv run pytest tests/golden tests/replay tests/phase_1_5 -q
112 passed in 2.06s

$ uv run pytest tests/integration/test_shadow_phase4_remediation_observation.py tests/integration/test_shadow_quote_jobs_provider_remediation.py tests/integration/test_shadow_phase4_concurrency_remediation.py tests/integration/test_daily_report_remediation.py tests/integration/test_replay_demo_isolation.py -q
51 passed in 23.62s

$ uv run pytest -q
859 passed, 33 warnings in 128.02s

$ uv run ruff check .
All checks passed!

$ uv run ruff format --check .
252 files already formatted

$ uv run mypy
Success: no issues found in 128 source files

$ uv run alembic current
0018 (head)

$ uv run argus fixtures validate-real-chain
real_mainnet_dca_close_dual_asset_transfer_in: ok - ok
real_mainnet_failed_nft_sale: ok - ok
real_mainnet_multi_hop_swap: ok - ok
real_mainnet_orca_close_position_multi_account: ok - ok
real_mainnet_partial_sell: ok - ok
real_mainnet_sol_to_token_swap: ok - ok
real_mainnet_sol_transfer_multi: ok - ok
real_mainnet_sol_transfer_received: ok - ok
real_mainnet_sol_transfer_single: ok - ok
real_mainnet_token_to_sol_swap: ok - ok
real_mainnet_token_to_usdc_swap: ok - ok
real_mainnet_usdc_transfer: ok - ok

$ uv run alembic downgrade 0016 && uv run alembic upgrade head
(clean round-trip through 0017 -> 0018 and back, no errors, re-verified
 after the full suite ran; final state: 0018 (head))

$ uv run python scripts/argus_phase4_replay_demo.py
(exit 0 -- full JSON evidence in
 orchestration/phase_4_remediation_1/evidence/replay_demo_results.json;
 scratch database created, migrated to head 0018, lifecycle completed,
 dropped afterward -- shared dev database confirmed untouched by
 test_replay_demo_isolation.py above)

$ git status --porcelain (changed-file secret scan: AWS-style keys, PEM
  headers, inline password/api-key/secret/token literals) across all 23
  files/directories this remediation round touched -- clean, no matches,
  no secret values emitted.
```

D. Frozen acceptance-gate regression (acceptance criteria: the original 10
   gates from `argus-phase-4-001`'s own table, re-confirmed still passing
   after this remediation's changes)

All 10 gates from `orchestration/checkpoints/phase_4.md` section D remain
PASS: the original tests (`test_prospective_event_snapshot_is_frozen_after_
later_rescoring`, `test_entry_probe_records_actual_latency_not_target_delay`,
`test_executable_return_distinct_from_mark_return_for_same_position`,
`test_all_entry_probes_fail_with_distinct_unsellable_reasons_intent_
becomes_no_fill`, `test_crash_after_quote_before_record_reclaims_probe_no_
duplicate_position`, `test_reprocessing_an_already_responded_probe_is_a_
no_op`) all still pass unmodified in behavior (the last one strengthened,
not weakened, with a provider-call counter -- section C). The unmodified
Phase 1 `WalletStreamState.wallet_live_state=DEGRADED` mechanism remains
untouched. No previously-closed finding from any prior phase was reopened.

E. Test results summary

- unit `test_phase3_wallet_qualification.py`: 27/27 (unchanged)
- integration `test_wallet_acquisition.py`: 36/36 (unchanged)
- integration `test_phase3_wallet_qualification.py`: 17/17 (unchanged)
- integration `test_migrations.py`: 17/17 (unchanged pass count; head now
  0018, all 9 hardcoded head-revision assertions updated 0016 -> 0018)
- integration `test_shadow_phase4.py`: 8/8 (unchanged pass count; the
  already-terminal no-op test strengthened with a provider-call counter)
- integration `test_daily_report.py`: 2/2 (unchanged)
- unit `test_telegram_notifier.py`: 6/6 (unchanged)
- golden + replay + phase_1_5: 112 passed (unchanged)
- NEW integration `test_shadow_phase4_remediation_observation.py`: 12/12
  (P4-R1/R2/R3)
- NEW integration `test_shadow_quote_jobs_provider_remediation.py`: 14/14
  (P4-R4, real `JupiterClient`+`httpx.MockTransport`+real
  `PriorityScheduler`)
- NEW integration `test_shadow_phase4_concurrency_remediation.py`: 7/7
  (P4-R5, genuine `asyncio.gather` concurrency)
- NEW integration `test_daily_report_remediation.py`: 10/10 (P4-R6)
- NEW integration `test_replay_demo_isolation.py`: 8/8 (P4-R7)
- full repository suite: 859 passed, 0 failed, 0 unexplained skipped (up
  from 808; +51 exactly matches the 5 new test files' combined count)
- ruff check: clean
- ruff format --check: clean (252 files)
- mypy: clean, 128 source files (unchanged file count)
- real-chain fixtures: 12/12 ok
- alembic head: 0018 (was 0016), downgrade-0016/upgrade-head round-trip
  clean through 0017/0018, re-verified after the full suite ran
- secret scan: clean

F. Deviation from the instruction

None substantive. The instruction's own ordering (P4-R7 isolation first,
then P4-R1-R3, then P4-R4-R5, then P4-R6) was followed exactly. The two
additional gaps (section B) were fixed beyond the instruction's explicit
7-finding list, but strictly within scope: both are direct, necessary
consequences of the instruction's own required behavior for P4-R3 and P4-R4
respectively (a real DB grant P4-R3's own fix needs to actually run; a
crash the instruction's own P4-R4 test requirements -- "malformed/nonfinite
impact or invalid outputs must be explicit failed/unusable evidence, not
crash a batch" -- explicitly named as a requirement), and the third (P4-R5's
position-creation race) is the literal scenario the instruction's own P4-R5
test list names ("two successful entry probes for one intent"). No
optional hardening or retuning was added. No Phase 5+ work was started.
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md` was not modified. No live
trade, signing, credential entry/disclosure, paid-provider use/upgrade,
live arming, or threshold relaxation was performed or attempted.

G. Known bugs / debt (unchanged from `orchestration/checkpoints/phase_4.md`
   section H except where noted)

- The "sufficiently interesting" gate approximation and quote-asset-mint-
  set "buy" heuristic are unchanged, still disclosed in
  `src/argus/shadow/prospective.py`'s own module docstring.
- `entry_price_usd`/mark-outcome descriptive-only status unchanged.
- Telegram notification now HAS two ordinary production callers (P4-R6,
  section B) -- the prior checkpoint's "no ordinary producer invokes it"
  debt item is resolved, not merely disclosed differently.
- No new known bugs are introduced by this round's changes beyond the two
  gaps in section B, both now fixed (not open debt).

H. Security state

- `LIVE_READY_SOFTWARE=false`, `LIVE_CANARY_PASSED=false`,
  `LIVE_ARMED=false` -- unaffected; unchanged from `phase_4.md`.
- No signing, signer, private-key, seed-phrase, live-arm, or broadcast path
  exists anywhere in this round's changed files. `argus_executor` DB role
  receives zero new grants. The one new grant (migration 0018) is scoped
  to `argus_ingest`, one column, one table, `UPDATE` only.
- `HttpTelegramTransport` is still never invoked with a real bot token
  anywhere in this repository -- every new/existing notifier call site in
  this round uses `FakeTelegramTransport`.
- No real Jupiter/DexScreener network call was made anywhere in this
  round's tests or REPLAY demonstration -- P4-R4's tests use
  `httpx.MockTransport` against the REAL `JupiterClient` code path (no
  live network), never a live endpoint.
- Secret scan clean on this round's 23 changed/new files (section C).
- No paid-provider feature enabled; no Phase 5+ code started;
  `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` not modified.

I. Cost confirmation

No real provider call was made anywhere in this remediation round: every
new test uses either the pre-existing deterministic fake/queued providers
or a real `JupiterClient` wired to `httpx.MockTransport` (a real class, a
fake transport, zero live network I/O), against real-but-local-only
Postgres via `connection_for_role(..., DbRole.INGEST)`/`connection_for_
admin`. Zero new real usage-recorder rows against a live provider this
round.

J. Environmental deferrals (unchanged, none reopened this round)

- `LIVE_HELIUS_RPC_VALIDATION` -- DEFERRED_ENVIRONMENTAL_CHECK, unchanged.
- `LIVE_HELIUS_WSS_VALIDATION` -- DEFERRED_ENVIRONMENTAL_CHECK, unchanged.
- `PG17_COMPOSE_VALIDATION` -- DEFERRED_ENVIRONMENTAL_CHECK, unchanged.
  PostgreSQL 16 remains the explicit functional substitute; every
  Postgres-backed command in section C ran against it.
- `BQ_PUBLIC_DATASET_ACCESS` -- unchanged deferral.
- No live Jupiter/DexScreener network access -- P4-R4's real-adapter tests
  use `httpx.MockTransport`, an explicit, disclosed substitution, not a
  silent gap.

None of these deferrals is claimed as PASS, and none authorizes live
readiness by itself. The accepted `PHASE_3_CANDIDATE_SAMPLE_BLOCKED` result
is unchanged and unaffected by this round.

K. Next specified phase

Per orchestrator instruction `argus-phase-4-remediation-001`, this
checkpoint approves no phase (`APPROVES_PHASE: NONE`). `docs/BUILD_STATE.
md`'s `last_orchestrator_approved_phase` (`3`) and `approved_commit` are
left unchanged -- this session does not and cannot self-approve Phase 4.
Per this project's established two-commit convention, this checkpoint, the
paired bundle, `docs/BUILD_STATE.md`, `docs/DECISION_LOG.md`, and
`orchestration/AGENT_HANDOFF.md` are committed once with every commit-hash-
bearing field set to the literal placeholder
`285f5a9fe993ff72a02ef6470ea9627952389428`, then a second, immediately following
commit fills in that first commit's own real hash in every one of those
fields -- both commits carry the sole terminal trailer `ARGUS-INSTRUCTION-
ID: argus-phase-4-remediation-001` with no paragraph after it, verified via
`git interpret-trailers --parse` before push.

STOP. Await independent re-audit of this remediation round before any
further phase work. Passing these builder tests does not approve Phase 4.
Only the orchestrator's own independent review may write the next `ACTIVE`
instruction into `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`, approving
Phase 4 and authorizing Phase 5, or requiring further remediation.

================ END ARGUS CHECKPOINT =========================
