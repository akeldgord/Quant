# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0025-phase-4
UTC_TIMESTAMP: 2026-09-01T14:35:00Z
CURRENT_COMMIT: PLACEHOLDER_FILLED_IN_SECOND_COMMIT
CURRENT_PHASE: 4
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-4-001
CHECKPOINT_PATH: orchestration/checkpoints/phase_4.md
BUNDLE_PATH: orchestration/bundles/phase_4.txt
TEST_STATUS: 27/27 unit `test_phase3_wallet_qualification.py` passed (unchanged); 6/6 unit `test_telegram_notifier.py` passed (new); 36/36 integration `test_wallet_acquisition.py` passed (unchanged); 17/17 integration `test_phase3_wallet_qualification.py` passed (unchanged); 17/17 integration `test_migrations.py` passed (unchanged pass count; head now 0016, all 9 hardcoded head-revision assertions updated from `0015` to `0016`); 8/8 integration `test_shadow_phase4.py` passed (new -- covers frozen gates 1-6, 9); 2/2 integration `test_daily_report.py` passed (new); 112/112 golden+replay+phase_1_5 passed (unchanged); full repository suite 808/808 passed (up from 792; +16 exactly matches new Phase 4 tests), 0 failed, 0 unexplained skipped; ruff clean; ruff format clean (244 files); mypy clean (128 source files, up from 112); alembic head 0016 (was 0015), downgrade-0015/upgrade-head round-trip clean, re-verified after the full suite ran; 12/12 real-chain fixtures ok; secret scan clean on all 25 changed files/directories -- ALL RAW COMMAND OUTPUT embedded verbatim in the paired bundle
WORKING_TREE: clean (verified via `git status --porcelain` before this commit)
ORCHESTRATOR_REVIEW_REQUIRED: whether this Phase 4 build (checkpoint sections B-L) genuinely satisfies all ten frozen acceptance gates from `argus-phase-4-001`'s own table -- in particular whether the REPLAY lifecycle demonstration's substitution of a deterministic provider/clock for the CLI's real Jupiter/DexScreener adapters (documented in section E/G) is an acceptable reading of "normal production wiring" given this sandbox's total absence of live network/paid-provider access, whether the two disclosed approximations (section H: the SWAP_SIMPLE+confidence>=0.500 "sufficiently interesting" gate as a stand-in for the un-persisted full `is_copy_eligible` semantic-proof fields; the quote-asset-mint-set buy-direction heuristic) are acceptable for this phase's scope, and whether Phase 4 should be approved and Phase 5 authorized, or remediation required. This session does not and cannot apply Phase 4 approval itself.

## Work completed

Executed orchestrator instruction `argus-phase-4-001` in full: independently
verified all safety gates (single instruction-only commit whose parent
exactly matches `TARGET_COMMIT` `379c5bc886abe7e99cdd3360fe3e71925ac932ce`;
`AUTHORIZED_PHASE: 4` vs. `docs/BUILD_STATE.md`'s `current_phase: 3` at the
time (never skip ahead); clean worktree; local HEAD equal to
freshly-fetched remote HEAD) before any code was touched, then implemented
the complete authorized batch:

1. **Prospective monitoring**: `argus.shadow.prospective.scan_for_new_
   prospective_events` scans already-persisted Phase 1 `chain_events`/
   `swaps` evidence for new trades from tier-allowed tracked wallets,
   creating one point-in-time-frozen `ProspectiveEvent` per interesting
   swap -- wallet score/tier/context snapshot, token state, position-size
   context, and cluster state are all captured at observation time and
   never updated by later rescoring (proven by
   `test_prospective_event_snapshot_is_frozen_after_later_rescoring`).
   `graph_state_snapshot` is always the explicit "Phase 7 not yet
   implemented" sentinel, never fabricated. This is a separate consumer
   over Phase 1's own evidence, mirroring Phase 2's archaeology-trigger-
   consumer precedent -- no Phase 1/3 transactional code was touched.
2. **Shadow intent/entry-delay probes**: `argus.shadow.intents.create_
   shadow_intent_for_event` reuses the SAME `config/signals_v1.yaml`
   eligibility thresholds that already govern live eligibility
   elsewhere (never a manufactured looser bar) and schedules 6 entry-delay
   quote probes (1/5/15/30/60/300s from ARGUS observation). One
   configurable small notional (0.1 SOL, wrapped-SOL raw units, new
   `config/signals_v1.yaml` `shadow_copy` section).
3. **Shadow fills/positions + mark/reverse-executable outcomes**:
   `argus.shadow.quote_jobs`/`argus.shadow.mark_jobs` create a
   `ShadowPosition` on the first successful entry probe and schedule
   reverse-executable (5m/30m/1h/6h/24h) and mark (same horizons, 3d/7d
   optional) outcome jobs. Five typed unsellable outcomes (`NoRouteError`,
   `InsufficientLiquidityError`, `TokenRestrictedError`,
   `ProviderCapacityMissError`, plus the catch-all `QUOTE_FAILED`) are
   preserved as real, distinct, queryable rows, never dropped or replaced
   with fabricated P&L (`test_all_entry_probes_fail_with_distinct_
   unsellable_reasons_intent_becomes_no_fill`). The same position's mark
   and reverse-executable outcomes are proven distinct
   (`test_executable_return_distinct_from_mark_return_for_same_position`).
   Quote actual latency is recorded via an injected `Clock`, never
   asserted (`test_entry_probe_records_actual_latency_not_target_delay`
   proves a controlled +2.7s response to a nominal +1s target records the
   real 2.7s delay).
4. **Restart safety (section 84)**: every network-calling probe follows
   the SAME 3-step claim/call/record shape already proven by Phase 2's
   `run_archaeology` -- atomic `SELECT ... FOR UPDATE SKIP LOCKED` claim
   committed alone, the network call outside any open transaction with
   `requested_at`/`responded_at` captured via an injected `Clock`
   immediately before/after, one atomic terminal-write transaction guarded
   by an idempotent already-responded no-op check. Proven via a real
   crash-injection test (`test_crash_after_quote_before_record_reclaims_
   probe_no_duplicate_position`) and an already-responded reprocessing
   test (`test_reprocessing_an_already_responded_probe_is_a_no_op`), both
   against real Postgres.
5. **Notification-only Telegram integration**: `argus.telegram.notifier.
   TelegramNotifier` enforces a closed 12-event-type set and rejects
   secret-shaped text before it reaches any transport;
   `FakeTelegramTransport` is used everywhere in tests/the REPLAY demo;
   `HttpTelegramTransport` exists as real reviewable code but is never
   invoked with a real bot token anywhere in this repository.
6. **`argus report daily`**: `argus.reports.daily.build_daily_report`
   returns real queried counts for system/discovery/tracking/signals/
   shadow/data-quality sections over a window; `live`/`research` and any
   feature this offline report cannot measure use explicit
   `NOT_IMPLEMENTED`/`UNAVAILABLE` sentinels, never invented activity.

All six wired through real `argus prospective run`/`argus shadow
run-entry-probes`/`run-reverse-probes`/`run-mark-outcomes`/`argus report
daily` CLI commands, not test-only helpers.

**REPLAY lifecycle demonstration**: `scripts/argus_phase4_replay_demo.py`
(`orchestration/phase_4/DEMONSTRATION.md`,
`orchestration/phase_4/evidence/replay_demo_results.json`) proves all eight
named steps (leader executes -> ARGUS observes -> source tx confirms ->
shadow signal -> entry quote -> shadow fill -> mark outcome -> reverse
executable quote) plus quote jobs, reverse/mark outcomes, the fake
notification, and the daily report, all through the exact same
`argus.shadow.*`/`argus.reports.daily` service functions the real CLI
commands call. "Leader executes" is grounded in a genuine,
independently-verified mainnet pump.fun buy transaction
(`tests/golden/fixtures/real/real_mainnet_sol_to_token_swap.json`)
parsed by the real, unmodified `argus.parsing.generic_parser.parse_
transaction` -- never a hand-fabricated `Swap` row. Entry/reverse quote
responses and mark-price snapshots are deterministic injected fakes (this
sandbox has no live network/paid-provider access), clearly labeled
"REPLAY -- NOT PROSPECTIVE ALPHA EVIDENCE" throughout. The demo script
deletes the rows it created from the shared dev database immediately
after capturing evidence so this one-off run never contaminates the
regression suite's unscoped due-probe queries.

## Important findings

- All ten frozen acceptance gates from `argus-phase-4-001`'s own table
  pass -- see `orchestration/checkpoints/phase_4.md` section D for the
  full gate-to-test disposition, including "stream gaps block eligible
  live state," which is satisfied by the unmodified, pre-existing Phase 1
  `WalletStreamState.wallet_live_state=DEGRADED` mechanism -- Phase 4 adds
  no live-entry path at all.
- During test-writing, two genuine SQLAlchemy unit-of-work ordering
  bugs were found and fixed in the new integration test file's own
  helper functions (never in production code): a combined single-`flush()`
  of a `Wallet` row and a dependent `WalletScoreSnapshot` row in the same
  unit of work did not reliably order the parent insert first, requiring
  an intermediate `await session.flush()` between the two adds (and
  similarly between `ChainEvent` and its dependents); and the test
  cleanup helper's `DELETE` order violated its own foreign keys
  (`shadow_positions` was deleted before its `shadow_quote_probes`/
  `shadow_mark_outcomes` children). Both fixed in
  `tests/integration/test_shadow_phase4.py`/
  `tests/integration/test_daily_report.py`/
  `scripts/argus_phase4_replay_demo.py`'s own cleanup helpers only --
  no production ORM model or service code was touched to fix this.
- Two design decisions are honestly disclosed as approximations, not
  defects (checkpoint section H): the prospective-event "sufficiently
  interesting" gate (`classification == SWAP_SIMPLE` and `confidence >=
  0.500`) approximates `ParsedTransaction.is_copy_eligible` since
  `matched_swap_program_id`/`matched_semantic_label`/
  `matched_discriminator_hex` are never persisted by Phase 1's `swaps`
  table; "buy" direction is inferred via a quote-asset-mint-set heuristic
  since neither classification nor persisted evidence records buy/sell
  directly.
- This sandbox's local PostgreSQL service was found stopped at the start
  of this session's validation (unrelated to any change made here, the
  same recurring environmental note as prior rounds). Restarted via
  `sudo service postgresql start`, non-destructive on the same local dev
  cluster used throughout this project.
- `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is unchanged -- still the
  orchestrator's `argus-phase-4-001` instruction. Phase 4 is NOT marked
  approved anywhere in this session's evidence; `last_orchestrator_
  approved_phase` is `3` (unchanged), never `4`.
- Both commits this session (the primary work commit and the follow-up
  commit-hash-fill-in commit) carry the sole final trailer paragraph
  `ARGUS-INSTRUCTION-ID: argus-phase-4-001`, with no paragraph after it,
  verified via `git interpret-trailers --parse` before push.

## Failures or limitations

- None. All six ordered implementation steps and all ten frozen
  acceptance gates named by `argus-phase-4-001` are implemented and
  tested.
- The REPLAY demonstration's entry/reverse-quote/mark-price data is
  deterministic and synthetic (this sandbox has no live network/
  paid-provider access), clearly labeled throughout -- not a limitation
  of this build, but an explicit, instruction-permitted substitution.
- `LIVE_HELIUS_RPC_VALIDATION`/`LIVE_HELIUS_WSS_VALIDATION`/`PG17_
  COMPOSE_VALIDATION`/`BQ_PUBLIC_DATASET_ACCESS` remain `DEFERRED_
  ENVIRONMENTAL_CHECK`, unchanged, not reopened this session.

## Deferred checks

- All items under "Failures or limitations" above.

## Exact next action requested from orchestrator

Independently audit this Phase 4 build
(`orchestration/checkpoints/phase_4.md`,
`orchestration/bundles/phase_4.txt`) against `argus-phase-4-001`'s own
frozen acceptance-gate table. In particular: whether the REPLAY
demonstration's dependency-injection substitution of a deterministic
provider/clock for the CLI's real Jupiter/DexScreener HTTP adapters is an
acceptable reading of "normal production wiring... controlled clocks and
deterministic providers" given this sandbox's total absence of live
network/paid-provider access (documented in checkpoint section G); whether
the two disclosed approximations in section H are acceptable for this
phase's scope; and whether the restart-safety proof (section D, gate 9)
genuinely closes section 84's requirement. Only the orchestrator may apply
Phase 4 approval -- write the next `ACTIVE` instruction into
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md` (`TARGET_COMMIT` pinned to the
exact commit named in this handoff) to do so, or to require further
remediation. Phase 5 remains forbidden until then. Until a new instruction
exists, the watcher (if running) takes no action beyond logging
`NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** unchanged from prior handoffs — if you
cloned/fetched this branch before 2026-08-30T22:35 UTC, re-clone or
`git fetch --all && git reset --hard origin/claude/argus-folder-setup-77ahrk`
rather than merging/rebasing the old (pre-rewrite) history.
