================ ARGUS ORCHESTRATOR CHECKPOINT ================

RETROACTIVE_POST_BUILD_RECOVERY_CHECKPOINT — NOT A CONTEMPORANEOUS PHASE STOP

A. Identity

PROJECT: ARGUS
SCOPE: Phase 10 (SYNTHETIC SUPER-WALLET), MASTER_SPEC.md section 64
region (five prospective strategy backtests A-E, shadow-only). This
document is NOT a contemporaneous per-phase orchestrator STOP -- Phase
10 was originally built, and is here corrected, under the human's
explicit authorization for Claude to carry Phases 7-11 through to
completion without the normal per-phase orchestrator STOP/audit cycle.
This checkpoint does NOT claim a contemporaneous STOP, independent
audit, or approval occurred for Phase 10 at build time. It exists solely
to satisfy FSR-14 (`argus-final-spec-recovery-001`, instruction section
F).
STATUS: RETROACTIVE_RECOVERY_RECORDED (not an orchestrator PASS/approval)
GIT_COMMIT (this checkpoint's own HEAD at authoring time):
50d96933b5ecde421300e96ce7694dfcc3b7ca62

Recovery authority: `argus-final-spec-recovery-001`, item FSR-08 (Phase
10's own fix). `TARGET_COMMIT` audited as contaminated:
`ea77dd55b1e6be91b61b2f8b37e1d70449a3cb30`.

B. What Phase 10 originally built (unchanged by this recovery)

`src/argus/synthetic/` -- five prospective strategy backtests (A: source
entry -> source exit; B: discovery specialist -> source exit; C:
discovery -> confirmation -> source exit; D: discovery -> confirmation
-> exit oracle; E: high convergence -> exit convergence), each matching
entry/exit trigger events from already-persisted Phase 4/7/8/9 evidence
and computing a per-strategy summary (trade count, win rate, profit
factor, max drawdown, capital utilization). This structural build (the
five strategy definitions, the trade-matching engine, `synthetic_
strategy_trades`/`synthetic_strategy_summaries` persistence, the CLI
`argus synthetic report` command, "shadow only unless later approved" --
this module has no live-execution capability anywhere) is UNCHANGED by
this recovery.

C. The historical leak/omission this recovery repaired (FSR-08)

Phase 10's primary backtest result (`gross_return`/`net_return`/
`outcome`) was computed from a fixed-cost-haircut MARK PRICE (nearest
`token_market_snapshots` row around entry/exit, minus a flat disclosed
haircut) rather than the entry wallet's own real Phase 5 executable-
return evidence -- meaning the headline backtest numbers described what
a naive mark-price proxy would have shown, not what was actually
executable. Separately, Strategy B's discovery-specialist filter and
Strategy D's exit-specialist filter both used a SINGLE Phase 9
specialist classification computed once at the final run cutoff and
reused for every candidate entry/exit, regardless of that entry/exit's
own decision time -- a wallet that became a discovery/exit specialist
only AFTER an earlier entry could incorrectly admit that earlier entry
into the strategy (a real look-ahead-bias leak).

D. The corrected implementation

- `src/argus/synthetic/service.py`'s `_price_and_persist_trades`:
  `gross_return`/`net_return`/`outcome` are now sourced from the entry
  wallet's own real Phase 5 reverse-executable quote at the primary 5m
  horizon (the same production event population `argus.copyability.
  loaders.load_wallet_opportunities` every later phase's own FSR fix
  reuses), matched by `(token_id, first_seen_at == entry.at)`. The OLD
  mark-price computation is preserved unchanged but now purely
  descriptive, in new `mark_gross_return`/`mark_net_return` columns
  (migration `0034`) -- never consulted for the primary result.
- An explicit no-route/insufficient-liquidity/excessive-impact/quote-
  failure observation is recorded as `FAILURE_EXECUTABLE_QUOTE_FAILED`
  (new outcome value, never dropped, never folded into `RESOLVED`); no
  matching Phase 5 evidence at all (or one still `PENDING`/
  `UNAVAILABLE`) is `FAILURE_NO_EXECUTABLE_EVIDENCE`. Strategy E's
  swarm-anchored entries (no single entry wallet) are honestly always
  `FAILURE_NO_EXECUTABLE_EVIDENCE` -- a disclosed scope limitation, not
  a fabricated value.
- New `synthetic_strategy_summaries.insufficient_executable_sample`
  boolean (migration `0034`) flags a strategy with NO real executable
  evidence at all (never silently falls back to mark prices to produce
  a "real-looking" but actually mark-derived result).
- Strategy B's discovery-specialist filter and Strategy D's exit-
  specialist filter now use each entry/exit's OWN decision-time Phase 9
  classification -- `compute_and_persist_phase10` re-invokes Phase 9's
  own idempotent cascade once per DISTINCT decision time actually needed
  (a disclosed O(distinct decision times) performance cost) and queries
  `WalletSpecialistScore.as_of == that decision time`, instead of a
  single cutoff-wide set.
- FSR-13 (this same recovery) subsequently bumped Phase 10's own
  `ALGORITHM_VERSION` from `synthetic_super_wallet_v1` to
  `synthetic_super_wallet_v2` and registered the old version in the new
  `contaminated_run_invalidations` registry.
- `src/argus/cli.py`'s synthetic report was separately found, during
  this same recovery, to hardcode the literal string
  `"synthetic_super_wallet_v1"` in its own report dict -- fixed to
  reference the real `ALGORITHM_VERSION` constant.

E. Actual tests run against the corrected implementation

- `tests/integration/test_phase10_synthetic_persistence_and_report.py`
  (full file, including four new FSR-08 tests --
  `test_strategy_a_uses_real_executable_return_not_mark_price`,
  `test_unsellable_reverse_quote_is_a_failed_executable_outcome`,
  `test_no_phase5_evidence_never_falls_back_to_mark_price`,
  `test_strategy_b_discovery_filter_uses_entrys_own_decision_time`):
  each test run individually against a fresh, migrated-to-head
  throwaway PostgreSQL 16 database (the shared long-lived development
  database's own cross-test pollution across this long session made a
  combined non-isolated run unreliable for this file specifically --
  disclosed in section F) -- all passed.
- Full repository unit suite (`uv run pytest tests/unit -q`): 1124
  passed, 0 failed, at this recovery's final commit.
- `uv run ruff format --check`, `uv run ruff check`, `uv run mypy src`:
  clean across the full repository at this recovery's final commit.
- Migration round-trip (`alembic upgrade head` / `downgrade -1` /
  `upgrade head`) verified against a fresh throwaway PostgreSQL 16
  database through migration `0036`.

F. Environmental limitations (disclosed, not a builder failure)

Same disclosed class as every other phase in this recovery (see the
companion `phase_7_final_recovery.md` section F): real local PostgreSQL
16 reachable, PostgreSQL 17 not available (tracked separately under
FSR-03). Phase 10's own integration suite specifically and concretely
demonstrated the shared `argus` development database's cross-test
pollution during this recovery: running the full file together against
that shared database produced Strategy A trade counts inflated by
leftover rows from unrelated earlier test runs in this same long
session (all sharing the fixed anchor timestamp
`2025-06-01T12:00:00Z`), because Phase 10's own entry/exit loaders read
ALL tracked-wallet activity in the database, not just a given test's own
seeded wallet. Each test in this file was therefore independently
re-validated against a freshly created, migrated-to-head, then-dropped
throwaway database to obtain a trustworthy result.

G. Changed/new files (Phase 10 portion of this recovery, FSR-08 + FSR-13's
   version bump)

Modified: `src/argus/synthetic/service.py`, `loaders.py`,
`persistence.py`, `src/argus/domain/synthetic_strategy_trades.py`,
`synthetic_strategy_summaries.py`, `src/argus/cli.py` (synthetic report
section).
New: `migrations/versions/0034_fsr08_synthetic_executable_return.py`;
the four FSR-08 tests named in section E, added to the existing
`tests/integration/test_phase10_synthetic_persistence_and_report.py`.

Untouched (preserved byte-for-byte): all Phase 0-6 checkpoint/bundle
files; `MASTER_SPEC.md`; `orchestration/AUDITOR_POLICY.md`;
`orchestration/PROTOCOL.md`; migrations `0001` through `0033` (never
rewritten).

H. Acceptance statement

This document records that Phase 10's mark-price-primary backtest result
and specialist-filter look-ahead-bias leak (FSR-08) were identified and
repaired, with real tests passing against the corrected implementation,
as part of the `argus-final-spec-recovery-001` authorized recovery. It
does NOT assert a contemporaneous orchestrator STOP/independent audit
occurred for original Phase 10 or for this recovery. Final acceptance of
the full recovery contract is recorded separately, per FSR-15/16.

I. Next action

No STOP is issued by this document. Historical-record-keeping only, per
FSR-14. Recovery work on the remaining FSR-01..16 items continues.

================ END ARGUS CHECKPOINT =========================
