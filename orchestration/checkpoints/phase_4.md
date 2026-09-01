================ ARGUS ORCHESTRATOR CHECKPOINT ================

A. Identity
PROJECT: ARGUS
MASTER_SPEC_VERSION: v2.0
SCOPE: Phase 4 (PROSPECTIVE MONITORING + SHADOW COPYING), authorized in full
  as one complete implementation batch by orchestrator instruction
  `argus-phase-4-001` (`AUTHORIZED_PHASE: 4`, `AUTHORIZED_ACTION:
  IMPLEMENT_COMPLETE_PHASE_4_PROSPECTIVE_MONITORING_AND_SHADOW_COPYING`),
  which in the same instruction independently approves Phase 3
  (`APPROVES_PHASE: 3`). MASTER_SPEC.md sections 44-48 (prospective shadow
  monitoring, shadow copy execution, copyability delay probes, executable
  returns, unsellable-is-a-real-outcome), section 84 (restart/crash
  acceptance), section 93 (daily report), section 94 (Telegram
  notification-only integration). Sections 49-51 (COPYABILITY SCORE v1,
  INFORMATION HALF-LIFE, FORWARD INFORMATION VALUE) and 85-87 (RESEARCH
  HYPOTHESIS infra) are explicitly out of scope (Phase 5+ per the
  instruction).
STATUS: Phase 4 build complete: schema, prospective-event/shadow-intent/
  position/quote-probe/mark-outcome services, CLI wiring, notification-only
  Telegram integration, `argus report daily`, an integrated production-
  entry-point REPLAY lifecycle demonstration, and all frozen acceptance-gate
  tests pass. Phase 4 itself is NOT orchestrator-approved -- this checkpoint
  reports build completion for independent audit, it does not and cannot
  itself apply approval.
UTC_TIMESTAMP: 2026-09-01T14:35:00Z
GIT_COMMIT: PLACEHOLDER_FILLED_IN_SECOND_COMMIT
TARGET_COMMIT: 379c5bc886abe7e99cdd3360fe3e71925ac932ce
AUTHORIZED_PHASE: 4
APPROVES_PHASE: NONE

B. Schema / service / CLI path (acceptance criteria: real production wiring,
   never a test-only reimplementation)

Migration `0016_phase4_prospective_monitoring_and_shadow_copying.py` (head
was `0015`) adds 5 new tables with least-privilege role grants:
`prospective_events`, `shadow_intents`, `shadow_positions`,
`shadow_quote_probes`, `shadow_mark_outcomes`. `argus_ingest` gets
SELECT+INSERT on all five, plus targeted UPDATE only where a row is
genuinely mutated in place (`shadow_intents`, `shadow_quote_probes`,
`shadow_mark_outcomes` -- status/claim/response writes); `argus_research`
gets broad SELECT; `argus_executor` gets nothing -- Phase 4 creates no live
order/signing/broadcast path.

| Layer | Module | Real entry point |
|---|---|---|
| Prospective-event scanning | `argus.shadow.prospective` (`scan_for_new_prospective_events`) | `argus prospective run` |
| Shadow intent + entry-delay scheduling | `argus.shadow.intents` (`create_shadow_intent_for_event`) | called from the same monitoring pass |
| Monitoring-pass orchestration | `argus.shadow.monitor` (`run_prospective_monitoring_pass`) | `argus prospective run` |
| Entry/reverse quote probes | `argus.shadow.quote_jobs` (`run_due_entry_probes`, `run_due_reverse_probes`) | `argus shadow run-entry-probes`, `argus shadow run-reverse-probes` |
| Mark outcomes | `argus.shadow.mark_jobs` (`run_due_mark_outcomes`) | `argus shadow run-mark-outcomes` |
| Notification | `argus.telegram.notifier` (`TelegramNotifier`, `FakeTelegramTransport`, `HttpTelegramTransport`) | not yet wired to a CLI trigger -- exercised directly in tests/the REPLAY demo, per the instruction's own "notification-only... do not send external messages" |
| Daily report | `argus.reports.daily` (`build_daily_report`) | `argus report daily` |

`scan_for_new_prospective_events` is a separate consumer over already-
persisted Phase 1 `chain_events`/`swaps` evidence (mirroring Phase 2's
archaeology-trigger-consumer precedent), never inlined into
`ReconciliationEngine`'s own transactional item-processing method -- no
Phase 1/3 transactional code was touched. Shadow eligibility reuses the
SAME `config/signals_v1.yaml` thresholds (`thresholds.wallet_tier_allowed`,
`thresholds.qualification_score_min`) that already govern live eligibility
elsewhere in the project -- never a manufactured, looser bar. `graph_state_
snapshot` is always the explicit sentinel `{"available": false, "reason":
"Phase 7 (ALPHA ANCESTRY) not yet implemented"}`, never fabricated.

Restart-safety (section 84): every network-calling probe follows the SAME
3-step claim/call/record shape already proven by Phase 2's
`run_archaeology` -- (1) atomic claim via `SELECT ... FOR UPDATE SKIP
LOCKED` committed alone, (2) the network call happens OUTSIDE any open
transaction with `requested_at`/`responded_at` captured via an injected
`Clock.utc_now()` immediately before/after, (3) one atomic transaction
writes the terminal outcome, guarded by an idempotent "already responded ->
no-op" check so a duplicate/re-executed step 3 never double-writes.

C. Commands actually run (raw output; PostgreSQL 16 local dev server, no
   live network/paid-provider access anywhere in this phase)

```
$ sudo service postgresql start
 * Starting PostgreSQL 16 database server
   ...done.

$ uv run pytest tests/unit/test_phase3_wallet_qualification.py -q
27 passed in 0.71s

$ uv run pytest tests/integration/test_wallet_acquisition.py -q
36 passed in 4.39s

$ uv run pytest tests/integration/test_phase3_wallet_qualification.py -q
17 passed in 7.49s

$ uv run pytest tests/integration/test_migrations.py -q
17 passed, 33 warnings in 29.67s

$ uv run pytest tests/golden tests/replay tests/phase_1_5 -q
112 passed in 2.72s

$ uv run pytest tests/integration/test_shadow_phase4.py tests/integration/test_daily_report.py tests/unit/test_telegram_notifier.py -q
16 passed in 3.16s

$ uv run pytest -q
808 passed, 33 warnings in 117.19s

$ uv run ruff check .
All checks passed!

$ uv run ruff format --check .
244 files already formatted

$ uv run mypy
Success: no issues found in 128 source files

$ uv run alembic current
0016 (head)

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

$ uv run alembic downgrade 0015 && uv run alembic upgrade head
(clean round-trip, no errors, re-verified after the full suite ran)

$ uv run python scripts/argus_phase4_replay_demo.py
(exit 0 -- full JSON evidence in orchestration/phase_4/evidence/replay_demo_results.json,
 see orchestration/phase_4/DEMONSTRATION.md)

$ git status --porcelain (changed-file secret scan: AWS-style keys, PEM
  headers, inline password/api-key/secret/token literals) across all 25
  files/directories this phase touched -- clean, no matches, no secret
  values emitted.
```

D. Frozen acceptance-gate matrix (per `argus-phase-4-001`'s own table)

| Frozen gate | Required proof | Test | Result |
|---|---|---|---|
| Observation timestamp frozen | Duplicate/late replay and restart preserve original first-seen; leader and confirmation times remain distinct | `test_prospective_event_snapshot_is_frozen_after_later_rescoring` | PASS |
| Point-in-time score/context frozen | Score/tier/context change after observation cannot alter the existing event's snapshot | `test_prospective_event_snapshot_is_frozen_after_later_rescoring` | PASS |
| Quote actual latency recorded | Controlled +2.7s request for nominal +1s target records actual timestamps/delay, not a false +1s | `test_entry_probe_records_actual_latency_not_target_delay`, REPLAY demo step 5 | PASS |
| Executable return distinct from mark | Same position, positive mark and unavailable/adverse reverse quote retain distinct outcomes | `test_executable_return_distinct_from_mark_return_for_same_position`, REPLAY demo steps 7-8 | PASS |
| Unsellable state preserved | Parameterized no-route/liquidity/impact/quote-failure/restricted cases remain visible in stored outcomes/reports | `test_all_entry_probes_fail_with_distinct_unsellable_reasons_intent_becomes_no_fill` | PASS |
| Provider-capacity miss is missing data | Exhausted capacity records missing probe and reason without fabricated fill/return; priority/accounting regressions remain passing | `test_all_entry_probes_fail_with_distinct_unsellable_reasons_intent_becomes_no_fill` (`OUTCOME_PROVIDER_CAPACITY_MISS`); full-suite regression | PASS |
| Stream gaps block eligible live state | Disconnect/restart/reconciliation gap and clock discontinuity remain degraded/disarmed until existing recovery conditions hold | Unmodified Phase 1 `WalletStreamState.wallet_live_state=DEGRADED` mechanism (`tests/unit/test_reconciliation.py`); no Phase 4 code path grants live eligibility -- there is no live-entry path in this phase at all | PASS (inherited, unmodified) |
| Complete phase deliverables/lifecycle | Integrated production-entry-point REPLAY demonstration covers all eight steps plus quote jobs, reverse/mark outcomes, fake notification and daily report | `orchestration/phase_4/DEMONSTRATION.md` + `orchestration/phase_4/evidence/replay_demo_results.json` | PASS |
| Shadow restart requirement (section 84) | Interruption before/after durable shadow/job writes and restart/replay produces no duplicate shadow trade or replacement evidence | `test_crash_after_quote_before_record_reclaims_probe_no_duplicate_position`, `test_reprocessing_an_already_responded_probe_is_a_no_op` | PASS |
| Inherited integrity/security | Raw-unit/Decimal arithmetic, event/position units, idempotency, non-destructive migrations, prior-phase regression and secret/safe-default tests | Full suite (section C), migration round-trip, secret scan | PASS |

E. REPLAY lifecycle demonstration (see `orchestration/phase_4/
   DEMONSTRATION.md` for the complete writeup)

**REPLAY -- NOT PROSPECTIVE ALPHA EVIDENCE.** `scripts/argus_phase4_replay_
demo.py` demonstrates leader executes -> ARGUS observes -> source tx
confirms -> shadow signal -> entry quote -> shadow fill -> mark outcome ->
reverse executable quote through the SAME `argus.shadow.*`/`argus.reports.
daily` service functions the real CLI commands call, substituting a
deterministic provider/clock at the same dependency-injection seam the CLI
uses (this sandbox has no live network access to Jupiter/DexScreener and no
paid-provider credentials; the frozen acceptance table itself requires
"controlled clocks and deterministic providers" for this demonstration).
"Leader executes" is grounded in a genuine, independently-verified mainnet
pump.fun buy transaction (`tests/golden/fixtures/real/real_mainnet_sol_to_
token_swap.json`, slot 290506981, signer `EfbbhahGNuhqEraRZXrwETfsaKxScngEt
tdQixWAW4WE`), parsed by the real, unmodified `argus.parsing.generic_parser.
parse_transaction` -- never a hand-fabricated `Swap` row. Full raw JSON
result at `orchestration/phase_4/evidence/replay_demo_results.json`. The
demo script deletes the rows it created from the shared dev database
immediately after capturing evidence, so this one-off run never
contaminates the regression suite's unscoped due-probe queries (confirmed
clean afterward -- section C).

F. Test results summary

- unit `test_phase3_wallet_qualification.py`: 27/27 (unchanged)
- unit `test_telegram_notifier.py`: 6/6 (new)
- integration `test_wallet_acquisition.py`: 36/36 (unchanged)
- integration `test_phase3_wallet_qualification.py`: 17/17 (unchanged)
- integration `test_migrations.py`: 17/17 (unchanged pass count; head now
  0016, all 9 hardcoded head-revision assertions updated from `0015` to
  `0016`)
- integration `test_shadow_phase4.py`: 8/8 (new -- covers gates 1-6, 9)
- integration `test_daily_report.py`: 2/2 (new)
- golden + replay + phase_1_5: 112 passed (unchanged)
- full repository suite: 808 passed, 0 failed, 0 unexplained skipped (up
  from 792; +16 exactly matches the 16 new Phase 4 tests)
- ruff check: clean
- ruff format --check: clean (244 files)
- mypy: clean, 128 source files (up from 112)
- real-chain fixtures: 12/12 ok
- alembic head: 0016 (was 0015), downgrade-0015/upgrade-head round-trip
  clean, re-verified after the full suite ran
- secret scan: clean

G. Deviation from the instruction

None substantive. The instruction's own acceptance table calls for a
"controlled clocks and deterministic providers" REPLAY demonstration
"through normal production wiring"; the real CLI's `shadow run-*` commands
hardwire the real `JupiterClient`/`DexScreenerClient` HTTP adapters with no
override flag (correct for production, since this sandbox has no live
network/paid-provider access to exercise them safely at all). The REPLAY
demo script therefore calls the identical underlying service functions
those CLI commands call, substituting a deterministic provider/clock at the
same dependency-injection seam -- documented explicitly in the script's own
module docstring and in section E above, not silently substituted. No
Phase 5+ work (COPYABILITY SCORE v1, INFORMATION HALF-LIFE, FORWARD
INFORMATION VALUE, RESEARCH HYPOTHESIS infra) was started.
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md` was not modified. No live
trade, signing, credential entry/disclosure, paid-provider use/upgrade,
live arming, or threshold relaxation was performed or attempted.

H. Known bugs / debt

- The "sufficiently interesting" gate in `argus.shadow.prospective`
  (`classification == SWAP_SIMPLE` and `confidence >= 0.500`) is an
  honestly-disclosed APPROXIMATION of `ParsedTransaction.is_copy_eligible`
  -- the persisted `swaps` table does not carry `matched_swap_program_id`/
  `matched_semantic_label`/`matched_discriminator_hex` (never persisted by
  Phase 1), so the full positive-semantic-proof gate cannot be re-evaluated
  from stored evidence alone. Disclosed in the module's own docstring.
- "Buy" direction (`is_buy`) is inferred via a quote-asset-mint-set
  heuristic (SOL/wrapped-SOL as the input side), since neither
  classification nor persisted evidence records buy/sell directly.
- `entry_price_usd` on `ShadowPosition` is a best-effort market-price
  snapshot via an optional injected `MarketDataProvider`; nullable when
  unavailable, never fabricated. Mark outcomes remain descriptive-only per
  section 47's own statement that the reverse-executable probe is the
  primary copyability outcome.
- Telegram notification is exercised directly (tests, REPLAY demo) but has
  no CLI trigger command yet -- the instruction requires notification-only
  integration exist and be provably safe (fake transport, closed event-type
  set, secret-like-content rejection), not that every event type already
  has a production caller wiring it in; no live event source calls
  `TelegramNotifier.notify` anywhere in this phase.
- No new known bugs are introduced by this phase's changes beyond the
  above, all pre-existing/disclosed design choices, not defects.

I. Security state

- `LIVE_READY_SOFTWARE=false`, `LIVE_CANARY_PASSED=false`,
  `LIVE_ARMED=false` -- unaffected; `argus.reports.daily._build_live()`
  hardcodes all three false unconditionally.
- No signing, signer, private-key, seed-phrase, live-arm, or broadcast path
  exists anywhere in this phase's changed files. `argus_executor` DB role
  receives zero new grants.
- `HttpTelegramTransport` exists as real, reviewable code but is never
  invoked with a real bot token anywhere in this repository's tests, CLI
  wiring, or REPLAY demonstration -- every call site uses
  `FakeTelegramTransport`.
- `TelegramNotifier.notify` rejects any text matching a secret-shaped
  pattern (`api_key`/`secret`/`token`/`password`/`private_key`/
  `seed_phrase` followed by `:`/`=` and 8+ non-whitespace characters)
  before it ever reaches a transport (`test_telegram_notifier.py`).
- No real Jupiter/DexScreener network call was made anywhere in this
  phase's tests or REPLAY demonstration -- every provider is a deterministic
  fake/queued dataclass; the CLI's own real adapters are unchanged.
- Secret scan clean on this phase's 25 changed files/directories (section
  C).
- No paid-provider feature enabled; no Phase 5+ code started;
  `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` not modified.

J. Cost confirmation

No real provider call was made anywhere in this phase: every new test and
the REPLAY demonstration use deterministic fake/queued execution and
market-data providers against real-but-local-only Postgres via
`connection_for_role(..., DbRole.INGEST)`. Zero new usage-recorder rows
this phase.

K. Environmental deferrals (unchanged, none reopened this phase)

- `LIVE_HELIUS_RPC_VALIDATION` -- DEFERRED_ENVIRONMENTAL_CHECK, unchanged.
- `LIVE_HELIUS_WSS_VALIDATION` -- DEFERRED_ENVIRONMENTAL_CHECK, unchanged.
- `PG17_COMPOSE_VALIDATION` -- DEFERRED_ENVIRONMENTAL_CHECK, unchanged.
  PostgreSQL 16 remains the explicit functional substitute; every
  Postgres-backed command in section C ran against it.
- `BQ_PUBLIC_DATASET_ACCESS` -- unchanged deferral.
- No live Jupiter/DexScreener network access -- the REPLAY demonstration's
  own explicit, disclosed substitution (section E), not a silent gap.

None of these deferrals is claimed as PASS, and none authorizes live
readiness by itself. The accepted `PHASE_3_CANDIDATE_SAMPLE_BLOCKED` result
(`orchestration/phase_3/SAMPLE_REPORT.md`) is unchanged and unaffected by
Phase 4.

L. Next specified phase

Per orchestrator instruction `argus-phase-4-001`, this checkpoint approves
no phase (`APPROVES_PHASE: NONE`) -- the instruction's own `APPROVES_PHASE:
3` was already applied to `docs/BUILD_STATE.md` at the start of this
session (see `docs/DECISION_LOG.md`'s 2026-09-01 entry). This checkpoint
reports completion of the authorized Phase 4 build for independent audit;
`docs/BUILD_STATE.md`'s `last_orchestrator_approved_phase` (`3`) and
`approved_commit` are left unchanged -- this session does not and cannot
self-approve Phase 4. Per this project's established two-commit convention,
this checkpoint, the paired bundle, `docs/BUILD_STATE.md`, `docs/
DECISION_LOG.md`, and `orchestration/AGENT_HANDOFF.md` are committed once
with every commit-hash-bearing field set to the literal placeholder
`PLACEHOLDER_FILLED_IN_SECOND_COMMIT`, then a second, immediately following
commit fills in that first commit's own real hash in every one of those
fields -- both commits carry the sole terminal trailer `ARGUS-INSTRUCTION-
ID: argus-phase-4-001` with no paragraph after it, verified via `git
interpret-trailers --parse` before push.

STOP. Await independent audit of this Phase 4 build before any further
phase work. Passing these builder tests does not approve Phase 4. Only the
orchestrator's own independent review may write the next `ACTIVE`
instruction into `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`, approving
Phase 4 and authorizing Phase 5 or requiring remediation.

================ END ARGUS CHECKPOINT =========================
