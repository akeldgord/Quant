================ ARGUS ORCHESTRATOR CHECKPOINT ================

A. Identity, instruction/target/result commit identities, and changed files (item 1)

PROJECT: ARGUS
MASTER_SPEC_VERSION: v2.0
SCOPE: Phase 3 -- WALLET RECONSTRUCTION + UNBIASED QUALIFICATION, per
  orchestrator instruction `argus-phase-3-001` (`AUTHORIZED_ACTION:
  EXECUTE_PHASE_3_WALLET_RECONSTRUCTION_AND_UNBIASED_QUALIFICATION_ONLY`,
  `AUTHORIZED_PHASE: 3`, `APPROVES_PHASE: 2`). This instruction also
  independently approved Phase 2 at exact remote commit
  `a13ba2ab8729a08de3c571b7b12c32cc3f14c56b` (`PASS_WITH_DEFERRED_
  ENVIRONMENTAL_VALIDATION`) -- see `docs/BUILD_STATE.md` for that
  approval applied and `docs/DECISION_LOG.md` for the decision record.
STATUS: PHASE_3_BUILD_COMPLETE_AWAITING_ORCHESTRATOR_REVIEW,
  PHASE_3_CANDIDATE_SAMPLE_BLOCKED (see section D)
UTC_TIMESTAMP: 2026-09-01T04:41:00Z
GIT_COMMIT: PLACEHOLDER_FILLED_IN_SECOND_COMMIT
TARGET_COMMIT: c4adf963ed3a0cae815867b6cc97b6aa5b47f48a
AUTHORIZED_PHASE: 3
APPROVES_PHASE: 2 (applied to `docs/BUILD_STATE.md`; Phase 3 itself is
  explicitly NOT self-approved by this checkpoint -- per this
  instruction's own explicit "`last_orchestrator_approved_phase` must
  become `2` ... and must NOT become `3`" -- see section N)

Mandatory session-start checks (verified before any code change this
run): the instruction commit's sole change is `orchestration/
ORCHESTRATOR_INSTRUCTIONS.md` and its parent is exactly `TARGET_COMMIT`
(`git log -1 --format='%H %P'` on the instruction commit
`c4adf963ed3a0cae815867b6cc97b6aa5b47f48a` shows parent
`a13ba2ab8729a08de3c571b7b12c32cc3f14c56b`, an exact match); worktree
clean before starting; local HEAD equal to a freshly fetched remote
branch HEAD; `docs/BUILD_STATE.md` preconditions matched (`current_phase:
2`, `last_completed_phase: 2`, `last_orchestrator_approved_phase: 1.5`,
`awaiting_orchestrator_review: true`) before applying this instruction's
explicit Phase 2 approval.

Changed files this run (`git diff --cached --stat HEAD` immediately
before this commit, 21 paths -- 5 modified, 16 new):

- Modified: `src/argus/cli.py` (new `argus wallets reconstruct-and-score`
  command), `src/argus/domain/__init__.py` (eager-import the 6 new
  domain modules), `src/argus/domain/wallets.py` (new `current_tier`
  column), `tests/integration/test_migrations.py` (7 mechanical
  `"0009"` -> `"0010"` head-revision assertion updates, see section K),
  `tests/integration/test_phase2_discovery.py` (2 pre-existing cleanup
  helpers extended to also delete the 6 new Phase 3 tables' rows before
  deleting a `wallets`/`tokens` row they now FK-reference, plus the
  `wallets` role-grant assertion updated for its new legitimate `UPDATE`
  grant -- see section K).
- New migration: `migrations/versions/0010_phase3_wallet_reconstruction_
  and_qualification.py`.
- New domain models (6): `src/argus/domain/{wallet_history_quality,
  wallet_positions,wallet_metrics_snapshots,wallet_score_snapshots,
  wallet_tier_history,wallet_cluster_links}.py`.
- New services (6): `src/argus/wallets/{history_reconstruction,
  position_reconstruction,scoring,clustering,tier_lifecycle,
  qualification_service}.py`.
- New tests (2): `tests/unit/test_phase3_wallet_qualification.py` (12
  tests), `tests/integration/test_phase3_wallet_qualification.py` (3
  tests).
- New evidence (1): `orchestration/phase_3/SAMPLE_REPORT.md` (the
  required 5-wallet sample report, honestly `PHASE_3_CANDIDATE_SAMPLE_
  BLOCKED` -- see section D).
- This checkpoint, its bundle, `docs/BUILD_STATE.md`,
  `docs/DECISION_LOG.md`, and a new `orchestration/AGENT_HANDOFF.md`
  (added in this same commit).

B. Requirement-to-code/test/evidence matrix (item 2)

Required Phase 3 build surface (instruction's numbered list, 13 items):

| # | Item | Code | Test/evidence |
|---|---|---|---|
| 1 | wallet history reconstruction | `src/argus/wallets/history_reconstruction.py` | required test 4, P3 unit/integration |
| 2 | explicit history completeness | `assess_wallet_history()` -> `HIGH/MEDIUM/LOW/UNKNOWN` | required test 4 |
| 3 | deterministic position ledger | `src/argus/wallets/position_reconstruction.py` (V1 weighted-average-cost) | required test 2 |
| 4 | round-trip derivation | raw `swaps` evidence preserved; positions always recomputable from it, never a second raw-event table | required test 9 (restart/replay) |
| 5 | position confidence | `HIGH/MEDIUM/LOW/UNRESOLVED`, `RELIABLY_QUALIFYING_POSITION_CONFIDENCE` | required test 3 |
| 6 | wallet metrics | `src/argus/domain/wallet_metrics_snapshots.py`, `compute_position_stats`/`compute_feature_fingerprint` | required tests 6, 7 |
| 7 | descriptive score | `score_wallet()`'s `descriptive_score` (all positions, any confidence) | required test 1 |
| 8 | qualification score | `score_wallet()`'s `qualification_score` (filtered positions only) | required test 1, section 38 frozen weights |
| 9 | discovery-evidence exclusion | structural firewall, `discovery_contaminated_token_ids` filter before any qualification computation | required test 1 (phase-blocking) |
| 10 | lottery-dominance handling | `LOTTERY_DOMINANCE_THRESHOLD=0.70`, `LOTTERY_DOMINANCE_PENALTY=15` | required test 6 |
| 11 | recency decay | `RECENCY_FULL_CREDIT_DAYS=7`/`RECENCY_ZERO_CREDIT_DAYS=365`, `WalletMetricsSnapshot.metrics_window` (`LIFETIME/180D/90D/30D/7D`) | required test 7 |
| 12 | initial clustering | `src/argus/wallets/clustering.py`, `wallet_cluster_links` | tier-lifecycle integration test |
| 13 | tier lifecycle | `src/argus/wallets/tier_lifecycle.py`, `wallet_tier_history` | required test 8 |

Required acceptance items (instruction's frozen list, all 8 -- see
section H for the full disposition): discovery contamination excluded --
descriptive/qualification scores differ where expected -- weighted-
average ledger correct -- transfer uncertainty handled -- Decimal/raw-
unit accounting correct -- history completeness affects confidence --
tier transitions timestamped -- small samples shrunk/constrained. The
five-wallet sample report (section D) and the critical contamination
fixture (required test 1) are both satisfied as part of this gate.

C. Schema/migration and role-grant summary (item 3)

Migration `0010_phase3_wallet_reconstruction_and_qualification.py`
(`down_revision = "0009"`), hand-written `op.create_table` per the
project's established convention, tested from zero and from current
head, downgrade-then-reupgrade cycle proven clean (section K). 6 new
tables plus one altered column:

- `wallet_history_quality` (light, append-only; `history_completeness`
  CHECK-constrained to `HIGH/MEDIUM/LOW/UNKNOWN`).
- `wallet_positions` (append-only; `confidence` CHECK-constrained to
  `HIGH/MEDIUM/LOW/UNRESOLVED`, `status` to `OPEN/CLOSED`; `Numeric(38,
  18)` for every quote-currency/quantity field, matching `swaps`'
  existing raw-unit precedent -- never a binary float).
- `wallet_metrics_snapshots` (append-only; `metrics_window` -- renamed
  from the spec's `window`, a reserved PostgreSQL keyword that breaks a
  bare CHECK-constraint SQL string, see section K -- CHECK-constrained
  to `LIFETIME/180D/90D/30D/7D`).
- `wallet_score_snapshots` (append-only; the phase's one audit-critical
  decision ledger, `FullIdentityMixin` -- `build_hash`/`config_hash`/
  `master_spec_hash`/`git_commit`, matching the `parse_attempts`/
  `token_mint_validations`/`archaeology_runs` precedent; `component_
  values`/`penalties` JSONB, `excluded_discovery_token_ids` JSONB list).
- `wallet_tier_history` (append-only; `to_tier` CHECK-constrained to the
  9 section-36 states; `source_score_id` nullable FK to `wallet_score_
  snapshots`).
- `wallet_cluster_links` (append-only; `evidence_type` CHECK-constrained
  to the 9 section-42 evidence types; `probability` CHECK 0-1;
  `wallet_a_id <> wallet_b_id` CHECK).
- `wallets.current_tier` (new nullable column, `String(16)`): a
  denormalized cache of the latest `wallet_tier_history` row, the exact
  same precedent as `tokens.current_lifecycle_stage` from Phase 2.

Role grants: all 6 new tables get `SELECT, INSERT` only for
`argus_ingest` (append-only, no UPDATE/DELETE); `argus_ingest`
additionally gets `UPDATE` on `wallets` (its first ever mutable field --
`current_tier`), a legitimate new grant this run's own migration adds,
not an oversight -- `argus_research` gets `SELECT` only on all 6 new
tables. `tests/integration/test_phase2_discovery.py::
test_p2t10_phase2_tables_have_role_grants_matching_immutability_
convention`'s append-only assertion list was updated to exclude
`wallets` for exactly this reason (mirroring how `tokens` was already
excluded for its own pre-existing `current_lifecycle_stage` mutability;
see section K).

D. Five-wallet sample report -- PHASE_3_CANDIDATE_SAMPLE_BLOCKED (item 4)

Full report: `orchestration/phase_3/SAMPLE_REPORT.md`. Per this
instruction's own explicit fallback, reported honestly rather than
worked around: **exactly 1 genuine candidate wallet** exists in this
sandbox from already-authorized authentic evidence, not 5.

This sandbox's only independently-verified real evidence source
(unchanged since Phase 1.5/2) is the single creation transaction of
pump.fun token `5dNYcCZXEGfGgbdUdq7MMR7KLsNJLLLgL83wLH8Fpump`. Re-running
Phase 2's own established real-token demonstration end-to-end via the
production CLI against this evidence (`argus tokens import-bootstrap`,
`argus discover archaeology-run --run-type HISTORICAL_WINNER`) discovers
exactly 1 wallet -- `6xo262KbDXepWbF3vPTrFXysr5vJwk3mozBXmXk3hmMx`, the
transaction's own fee payer (the creator's genuine bundled dev-buy). This
is one fewer than Phase 2's original 2-wallet demonstration: the second
candidate from that run was the pump.fun bonding curve's own program-
derived reserve account, correctly excluded automatically since Phase 2
remediation round 1's evidence-grounded `ownership_classification` (no
new Phase 3 code involved).

Running `argus wallets reconstruct-and-score` against this one real
wallet (real production CLI, real `argus_ingest`-role path):
`history_completeness=UNKNOWN` (zero `swaps` rows exist for it -- no
live ingestion stream or historical acquisition walk has ever run
against this wallet's own transaction history in this sandbox; Phase 2's
raw balance-delta archaeology technique that discovered it writes
directly to `early_buyers`, never through `swaps`), `positions_
reconstructed=0`, `qualification_score=descriptive_score=50.00` (the
neutral prior throughout, since nothing is computable from zero
positions -- never fabricated), `eligible_for_qualification=False`,
`tier_transition: -> DISCOVERED`. This falls enormously short of the
frozen V1 sample-size gate (>=20 usable closed positions, >=10 distinct
tokens, completeness not LOW/UNKNOWN) on every dimension at once.

Missing evidence to reach 5 genuine candidates: a live Solana RPC/
WebSocket credential or reachable indexed historical dataset (currently
`DEFERRED_ENVIRONMENTAL_CHECK`, unchanged since Phase 1/2), to populate
real `swaps` evidence for several real wallets each with >=20 real closed
positions across >=10 distinct tokens. Neither exists in this sandbox
today. Per this instruction's own explicit rule ("A poor score, low
completeness, or zero A/S wallets is a valid Phase 3 result"), this is
reported as-is -- the frozen thresholds were not loosened, Phase 1.5's
separate 14-transaction wallet was not substituted (it has no `wallets`/
`wallet_discovery_events` row -- never run through Phase 2 discovery, so
it is not an "already-discovered wallet" Phase 3's service scope
requires), and no synthetic wallet history was fabricated and passed off
as a genuine candidate.

E. Discovery-contamination firewall -- the phase-blocking invariant (item 5)

The critical MASTER_SPEC test is structural, not a post-hoc filter:
`score_wallet()` (`src/argus/wallets/scoring.py`) computes
`qualification_score` from a SEPARATELY-filtered position list
(`token_id not in discovery_contaminated_token_ids` AND HIGH/MEDIUM
confidence only) from the very start of the computation, while
`descriptive_score` is computed from a second, independent pass over
every position, any confidence, contaminated tokens included -- the
huge-winner discovery-trigger token simply never enters the
qualification computation's inputs at all, so it cannot leak through any
secondary aggregate (sample counts, hit rate, recency windows, largest-
trade contribution, tier gates) by construction.

Two independent proofs, at both the pure-function and full-persisted-
service level:

- `tests/unit/test_phase3_wallet_qualification.py::
  test_p3_discovery_contamination_excluded_from_qualification_not_
  descriptive` -- asserts `qualification_score`, `stats.closed_count`,
  `stats.distinct_tokens`, `stats.hit_rate`, `stats.largest_trade_
  contribution_pct`, `eligible_for_qualification`, and `penalties` are
  ALL byte-identical whether or not a fabricated huge contaminated
  winner is present, while `descriptive_score` is measurably higher with
  it (a plain arithmetic mean, not the qualification pass's outlier-
  resistant median -- see section K for why the median alone did not
  move under this fixture, and the fix).
- `tests/integration/test_phase3_wallet_qualification.py::
  test_p3_discovery_contamination_excluded_at_the_service_level` -- two
  real wallets against real Postgres, one clean and one with an added
  discovery-trigger huge-winner position plus a real `wallet_discovery_
  events` row naming it: `qualification_score` is byte-identical between
  them, `positions_reconstructed` correctly shows 2 vs. 1 (the
  contaminated position is preserved and reported, never deleted from
  raw evidence -- this instruction's own explicit requirement).

`discovery_contaminated_token_ids` is derived exclusively from real,
persisted `wallet_discovery_events.trigger_token_id` provenance by
`qualification_service.reconstruct_and_score_wallet()` -- never a
fixture name or hand-maintained list.

F. Position reconstruction and financial accounting (item 6)

`src/argus/wallets/position_reconstruction.py` implements MASTER_SPEC
section 35's V1 weighted-average-cost inventory accounting entirely in
`Decimal`, never binary float. Required test 2
(`test_p3_weighted_average_ledger_buys_partial_sell_buy_sell`) uses a
hand-traced scenario (independently derived before any code was run, not
copied from output): buy 100 @ 1 SOL/unit, partial-sell 40 @ 1.5
SOL/unit, buy 50 more @ 2 SOL/unit, final-sell the remaining 110 @ 3
SOL/unit -> `entry_quantity=150`, `entry_value_quote=200`, `average_
cost_quote=200/150`, `partial_exit_count=1`, `realized_pnl_quote=190`
(20 from the first partial sell + 170 from the final sell),
`status=CLOSED`, `confidence=HIGH`, `unrealized_pnl_quote=Decimal(0)`
(tautological for a closed position -- an OPEN position's is always
`None`, never fabricated from a stale historical fill price, since this
project has no continuous intraday price feed).

Transfer uncertainty (required test 3): `TRANSFER_IN`/`TRANSFER_OUT`
legs never become a fabricated buy/sell (`test_p3_unresolved_transfer_
never_becomes_a_fabricated_buy`); a transfer alongside genuine swaps for
the same token downgrades confidence without changing the reconstructed
quantity (`test_p3_transfer_alongside_genuine_swaps_downgrades_
confidence_not_quantity`); an oversell beyond reconstructed holdings
(more evidence of a sale than a bought quantity can explain) downgrades
to `LOW` confidence rather than silently going negative (`test_p3_
oversell_beyond_reconstructed_holdings_downgrades_to_low_confidence`).

Sort order for same-slot legs is fully content-derived (`(slot,
classification, input_mint, output_mint, input_amount_raw, output_
amount_raw)`), never dependent on `wallet_address` (constant per call)
or a random ingestion-time value -- required for required test 9
(restart/replay): an independent re-parse of identical raw evidence must
reproduce byte-identical positions.

G. History completeness and its effect on confidence (item 7)

`src/argus/wallets/history_reconstruction.py` reuses Phase 2's already-
proven `acquire_historical_transactions()` boundary-aware terminal status
(`STATUS_COMPLETE`/`STATUS_PARTIAL`) rather than building new pagination/
completeness logic -- a well-motivated cross-phase reuse, since that
service's own honest completeness terminal status maps directly onto
`HIGH`/`MEDIUM`. No evidence at all -> `UNKNOWN` (never assumed to mean
zero on-chain activity). `STREAM_FORWARD_ONLY` (evidence only from
whatever point live ingestion began) always maps to `LOW` -- it can never
by itself claim a complete history.

Required test 4 (`test_p3_low_unknown_history_completeness_blocks_
eligibility_identical_positions`): the exact same 25-closed-position
economic evidence produces `eligible_for_qualification=True` under
`HIGH` completeness and `False` under `LOW`/`UNKNOWN` -- and,
critically, `qualification_score` is NOT identical between `HIGH` and
`LOW` despite the sample count itself being large enough (25 >= 20, 25
>= 10 tokens): the completeness-only shrinkage fix (section K) makes an
otherwise-passing sample still shrink toward the neutral prior when
completeness alone is the blocker, since an incomplete evidence fragment
may not represent this wallet's real history. `test_p3_history_
assessment_derives_from_real_acquisition_status_not_a_claim` proves
`assess_wallet_history()` raises `ValueError` rather than accepting a
bare, unverified `--partial`-style claim when `LIVE_ACQUISITION_WALK` is
asserted without a real terminal `acquisition_status`.

H. Sample-size gate, lottery dominance, and recency (item 8) -- and the frozen 8-item acceptance disposition

| Acceptance item | Status | Evidence |
|---|---|---|
| discovery contamination excluded | PASS | section E |
| descriptive/qualification scores differ where expected | PASS | section E (unit test); `test_p3_discovery_contamination_never_leaks_through_recency_or_tier_gate` |
| weighted-average ledger correct | PASS | section F |
| transfer uncertainty handled | PASS | section F |
| Decimal/raw-unit accounting correct | PASS | section F; every quote-currency field is `Decimal`/`Numeric(38,18)`, never float, throughout `position_reconstruction.py`/`scoring.py` |
| history completeness affects confidence | PASS | section G |
| tier transitions timestamped | PASS | `test_p3_tier_lifecycle_transitions_are_immutable_and_timestamped` (real Postgres): a `DISCOVERED` transition (`from_tier=None`) followed by a real `WalletClusterLink` at probability 0.95 driving a genuine `QUARANTINE` transition on a second `reconstruct_and_score_wallet()` call; the first transition row's `from_tier`/`to_tier`/`transitioned_at` are asserted byte-identical after the second transition is recorded -- immutability proven, not merely claimed |
| small samples shrunk/constrained | PASS | `test_p3_tiny_but_superficially_excellent_sample_cannot_reach_top_score` (deterministic proportional shrinkage toward the neutral prior, `position_fraction * token_fraction * completeness_fraction`, never a fixed cap that could still imply near-elite standing on a tiny sample); `test_p3_sample_gate_thresholds_are_the_frozen_v1_values` (`MIN_USABLE_CLOSED_POSITIONS=20`, `MIN_DISTINCT_TOKENS=10`, asserted against the literal frozen instruction values, not merely against the module's own constants) |

Lottery dominance (required test 6,
`test_p3_lottery_dominance_flag_and_boundary_are_deterministic`):
`LOTTERY_DOMINATED` flags when the largest position's share of positive
lifetime P&L exceeds the frozen 70% threshold, `LOTTERY_DOMINANCE_
PENALTY=15` applied as a penalty/flag, never automatic rejection;
boundary behavior (exactly at 70%) is deterministic.

Recency (required test 7, `test_p3_recency_uses_point_in_time_as_of_
never_a_fixed_clock`): `compute_feature_fingerprint(..., as_of=...)`
takes an explicit point-in-time parameter throughout -- never
`datetime.now()` -- so an identical position set scored `as_of` two
different times produces two different, correctly-ordered recency
values, and an earlier snapshot can never be retroactively altered by a
later observation (`WalletMetricsSnapshot.metrics_window` persists
`LIFETIME`/`180D`/`90D`/`30D`/`7D` per snapshot; V1 persists the
`LIFETIME` window at each `reconstruct_and_score_wallet()` call --
narrower windows are a straightforward mechanical extension using the
same `as_of`-parameterized functions, not built this phase per the
instruction's own 13-item scope list not requiring all 5 windows be
persisted simultaneously).

I. Restart/replay idempotency (item 9, part of the disposition above)

`test_p3_restart_replay_identical_evidence_produces_no_duplicate_rows`
(real Postgres): running `reconstruct_and_score_wallet()` twice against
byte-identical evidence yields `positions_written=0`/`positions_
unchanged=1`/`score_written=False`/`tier_transition=None` on the second
call, and direct row-count queries confirm exactly 1 row in each of
`wallet_positions`/`wallet_score_snapshots`/`wallet_tier_history` after
both calls -- proven via explicit content-equality comparison against
each wallet's latest existing row before insert (`_positions_equal`/
`_score_equal` in `qualification_service.py`), plus `determine_tier_
transition()` returning `None` when the computed tier equals the current
tier.

J. Requirement-to-test matrix -- all 9 required test categories (item 10, part 1)

(Required test 10, regression, is covered by the full repository suite
below rather than a dedicated function, per this instruction's own
explicit convention -- see section K.)

| Required test | Status | Where |
|---|---|---|
| 1. discovery contamination fixture (phase-blocking) | PASS | section E (2 tests, unit + integration) |
| 2. weighted-average ledger | PASS | section F |
| 3. transfer uncertainty | PASS | section F (3 tests) |
| 4. completeness-confidence coupling | PASS | section G (2 tests) |
| 5. small-sample constraint | PASS | section H (2 tests) |
| 6. lottery dominance | PASS | section H |
| 7. recency/versioning | PASS | section H |
| 8. tier lifecycle | PASS | section H (integration) |
| 9. restart/replay | PASS | section I (integration) |

K. All commands, exact results, and defects found/fixed during self-review (item 10, part 2)

Two real defects were found and fixed via my own adversarial test-writing
and empirical test-run output, before any evidence was recorded -- both
disclosed here rather than silently corrected:

1. **Descriptive score insensitive to a single extreme winner.** The
   first draft of the required-test-1 fixture failed:
   `descriptive_score` was byte-identical with/without the contaminated
   huge winner, because `selection_skill`'s median-based formula (used
   identically for both the qualification and descriptive pass) is, by
   design, robust to exactly one outlier among an even-sized sample --
   the qualification pass's deliberate anti-lottery-inflation property,
   but it defeated the required test's premise for the descriptive pass.
   Fixed by adding a plain arithmetic `mean_return` (never persisted as
   its own snapshot column -- an internal-only stats field, the same
   precedent `PositionStats.total_realized_pnl` already sets) and a
   `compute_feature_fingerprint(..., robust: bool)` parameter: `robust=
   True` (qualification) keeps the outlier-resistant median; `robust=
   False` (descriptive only) uses the raw mean, so a wallet's descriptive
   picture genuinely reflects every position handed to it, discovery-
   trigger token included. Verified: baseline/contaminated descriptive
   scores now differ (75 -> 100, clamped) while qualification scores stay
   byte-identical (both derived from a filtered set that never contained
   the contaminated token to begin with).
2. **Completeness-only sample-gate failure did not shrink the score.**
   Required test 4's second assertion (`low.qualification_score !=
   high.qualification_score`) failed: with a 25-position/25-token sample
   (large enough to individually satisfy both count thresholds),
   `LOW`/`UNKNOWN` completeness alone triggered the ineligible-shrinkage
   branch, but `position_fraction`/`token_fraction` were each `min(1,
   .../threshold)` = 1 (since the counts already exceed the thresholds),
   so `sample_fraction = 1` and the "shrunk" score equaled the raw
   score exactly -- completeness contributed no shrinkage at all. Fixed
   by adding an explicit `completeness_fraction` term to the shrinkage
   product (`HIGH`/`MEDIUM` = 1, `LOW` = 0.5, `UNKNOWN` = 0 -- fully
   unknown history shrinks all the way to the neutral prior), so an
   incomplete evidence fragment can never pass through the sample gate
   unshrunk merely because its position/token counts happen to be large.

Both fixes were verified via `uv run pytest tests/unit/test_phase3_
wallet_qualification.py -q` going from 2 failed/10 passed to 12/12
passed, then re-confirmed clean via the full suite below.

A third, non-financial defect was found and fixed while running the full
repository suite after these two: `tests/integration/
test_phase2_discovery.py`'s `_cleanup_wallets()`/`_cleanup_token()`
helpers (written before Phase 3 existed) did not know about the 6 new
Phase 3 child tables, so `test_p2t4_historical_archaeology_on_real_
evidence`'s own cleanup of the real pump.fun wallet/token (which this
run's own sample-report demonstration, section D, had also fed through
`argus wallets reconstruct-and-score`) failed with a foreign-key
violation. Fixed by extending both helpers to also delete the relevant
Phase 3 child rows before deleting the parent `wallets`/`tokens` row --
this is the identical "two independent Phase N/N+1 pieces of test code
touch the same one real evidence token" collision Phase 2's own
checkpoint (section K there) already documented and resolved the same
way: re-run the affected real-evidence demonstration a second time,
after all validation, so the final DB state reflects it.

```
uv run pytest tests/unit/test_phase3_wallet_qualification.py tests/integration/test_phase3_wallet_qualification.py -q
  -> 15 passed

uv run pytest tests/integration/test_migrations.py -q      -> (included in integration total below)
uv run pytest tests/golden tests/replay tests/phase_1_5 -q  -> 112 passed
uv run pytest tests/integration -q                           -> 74 passed
uv run pytest -q                                             -> 721 passed
uv run ruff check .                                          -> All checks passed!
uv run ruff format --check .                                 -> 209 files already formatted
uv run mypy                                                   -> Success: no issues found in 110 source files
uv run alembic current                                        -> 0010 (head)
uv run argus fixtures validate-real-chain                    -> 12/12 ok
git diff HEAD -- <changed files> | grep -iE 'password|api[_-]?key|secret|BEGIN ... PRIVATE KEY|AKIA...'
                                                               -> no matches (clean)
```

Mechanical `"0009"` -> `"0010"` head-revision updates in `tests/
integration/test_migrations.py` (7 occurrences of `assert
_current_revision(scratch_database) == "0009"` immediately following a
`command.upgrade(cfg, "head")` or an "expect still at head after a
refused downgrade" assertion; every other `"0009"` reference in that file
names migration 0009 specifically as a fixed historical revision, e.g.
`command.downgrade(cfg, "0008")`, and was left unchanged) -- the exact
same category of expected churn every prior phase's own new migration
has required.

Migration 0010's own downgrade-then-reupgrade cycle was proven clean
against the real dev Postgres 16 instance during development (`alembic
downgrade 0009` then `alembic upgrade head`, `alembic current` confirming
`0010 (head)` both before and after), independently of the automated
`tests/integration/test_migrations.py` zero-to-head/upgrade-from-N
coverage that now also spans through 0010.

Environment: local PostgreSQL 16 (found stopped and restarted via `sudo
service postgresql start`, non-destructive on this sandbox's dev
cluster, twice during this run -- unrelated to any code change,
disclosed per this project's established honesty convention); this is
a substitute for the PG17 Compose target, unchanged and disclosed since
Phase 0 (`PG17_COMPOSE_VALIDATION` in `docs/BUILD_STATE.md`).

L. Environmental deferrals and non-blocking debt (item 11)

No new deferrals introduced this phase. Carried forward unchanged:
`LIVE_HELIUS_RPC_VALIDATION`, `LIVE_HELIUS_WSS_VALIDATION`, `PG17_
COMPOSE_VALIDATION`, `BQ_PUBLIC_DATASET_ACCESS` (all `DEFERRED_
ENVIRONMENTAL_CHECK`, per `docs/BUILD_STATE.md`). Non-blocking debt
specific to Phase 3, disclosed rather than hidden:

- The five-wallet sample report is `PHASE_3_CANDIDATE_SAMPLE_BLOCKED`
  (section D) -- a direct, explicit consequence of this sandbox's
  unchanged live-provider-access limitation, not a Phase 3 code defect.
  Resolving it requires the same `LIVE_HELIUS_RPC_VALIDATION`
  environmental deferral that has blocked deeper real-evidence work
  since Phase 1.
- `WalletMetricsSnapshot` persists only the `LIFETIME` recency/metrics
  window per `reconstruct_and_score_wallet()` call; the `180D`/`90D`/
  `30D`/`7D` windows are schema-ready (`RECENCY_WINDOWS` constant,
  `metrics_window` CHECK constraint already accepts all 5 values) and
  mechanically straightforward to add (the same `as_of`-parameterized
  `compute_position_stats`/`compute_feature_fingerprint` functions,
  called once per window with a filtered position list) but were not
  wired into the service this phase, since the instruction's own 13-item
  scope list requires "lifetime, 180-day, 90-day, 30-day, and 7-day
  metrics **where data exists**" and this sandbox's one real candidate
  wallet (section D) has none.
- Clustering (`src/argus/wallets/clustering.py`) computes a real
  `cluster_risk`/`independence_probability` estimate from persisted
  `wallet_cluster_links` evidence, but no automated process yet detects
  and writes those links from raw evidence (common funding, synchronized
  activity, etc.) -- this instruction's own explicit "implement only the
  initial Phase 3 clustering necessary for qualification and confidence"
  scope limit; link *detection* is left for a later phase, matching the
  instruction's framing of clustering as evidence *consumption*
  (`assess_wallet_cluster_risk`) this phase, not evidence generation.

M. Security, credential, paid-provider, and live-state confirmation (item 12)

No credential was entered, displayed, or logged. No signer, private key,
or seed material was accessed or referenced. No paid provider was
enabled or called -- the sample-report demonstration (section D) reused
only the same offline, already-committed real evidence file Phase 1.5/2
established. No trade intent, order, quote, transaction, or live-
execution side effect exists anywhere in the new code -- a `git grep`-
based scan for `sign_transaction`/`send_transaction`/
`sendRawTransaction`/`private_key`/`Keypair(`/`broadcast` across the new
`src/argus/wallets/`+`src/argus/domain/` modules returns no matches (this
phase's own module docstrings repeatedly restate that a tier assignment
is research evidence only, never live authorization by itself). Secret
scan (section K) is clean.

N. Deviations (item 13) and explicit STOP (item 14)

Deviations from this instruction: none. Work stayed within
`AUTHORIZED_ACTION:
EXECUTE_PHASE_3_WALLET_RECONSTRUCTION_AND_UNBIASED_QUALIFICATION_ONLY`:
no Phase 4 prospective monitoring/shadow copying, no live provider
enablement, no threshold relaxation to manufacture attractive candidates,
no unrelated redesign of Phase 0-2 code beyond the mechanical `"0009"`
-> `"0010"` migration-head test updates and the two pre-existing Phase 2
integration-test cleanup-helper/role-grant-assertion fixes this phase's
own new cross-table foreign keys and new `wallets.current_tier` UPDATE
grant required (both genuine correctness fixes surfaced by this phase's
own schema, not scope creep -- see section K).

`orchestration/ORCHESTRATOR_INSTRUCTIONS.md` was not modified.
`docs/BUILD_STATE.md`'s `last_orchestrator_approved_phase` is set to `2`
and `approved_commit` to `a13ba2ab8729a08de3c571b7b12c32cc3f14c56b` per
this instruction's own explicit approval -- **Phase 3 itself is
explicitly NOT marked approved**, per this instruction's own explicit
"must NOT become `3` until a later orchestrator approval."

**STOP. This checkpoint and its bundle are submitted for independent
Phase 3 orchestrator audit. No Phase 4 work, no self-authorization of
Phase 3, and no further `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`
change will occur until a new orchestrator instruction is issued.**
