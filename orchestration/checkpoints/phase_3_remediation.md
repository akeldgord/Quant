================ ARGUS ORCHESTRATOR CHECKPOINT ================

A. Identity
PROJECT: ARGUS
MASTER_SPEC_VERSION: v2.0
SCOPE: Phase 3 consolidated remediation -- close all 7 frozen blocking
  findings (P3-R1 through P3-R7) from independent audit `argus-phase-3-
  audit-001`, per orchestrator instruction `argus-phase-3-remediation-001`
  (`AUTHORIZED_ACTION: REMEDIATE_ALL_FROZEN_PHASE_3_BLOCKERS_ONLY`). This is
  the first and only consolidated Phase 3 remediation.
STATUS: All 7 frozen findings (P3-R1..P3-R7) are fixed with real, tested
  code and real, tested checkpoint-protocol regression. All 9 required
  prospective acceptance-test categories pass. Phase 3 remains NOT
  orchestrator-approved -- this checkpoint reports remediation completion
  for independent audit, it does not and cannot itself apply approval.
UTC_TIMESTAMP: 2026-09-01T05:35:00Z
GIT_COMMIT: 5713e9bd86011ae1033507fbdab349cc3dc5fdbd
TARGET_COMMIT: 69a8de622b1977f92999ca680fcb8d851ba78c9f
AUTHORIZED_PHASE: 3
APPROVES_PHASE: NONE

B. Requirement-to-evidence disposition / acceptance criteria (one row per
   frozen finding)

| Finding | Fix location | Test proof | Result |
|---|---|---|---|
| P3-R1 (point-in-time firewall absent in production) | `src/argus/wallets/qualification_service.py` sections 1-4 (swaps `first_seen_at <= now`, discovery events `created_at <= now`, early buyers `created_at <= now`, cluster links `as_of <= now AND created_at <= now`); `src/argus/wallets/position_reconstruction.py` (`known_swaps` filtered by `block_time <= as_of` before any round-trip math; malformed/future `block_time` excluded, never clamped) | Unit: `test_p3_future_dated_swap_excluded_from_reconstruction_evidence_preserved`, `test_p3_future_dated_only_evidence_excludes_the_token_entirely`, `test_p3_recency_uses_point_in_time_as_of_never_a_fixed_clock`. Integration: `test_p3_service_level_as_of_boundary_excludes_future_cluster_link` (real Postgres: cluster link dated after `t0` produces no quarantine/penalty at `t0`; scoring at `later` picks it up; replaying `t0` again after `later` exists reproduces the identical `t0` score) | FIXED |
| P3-R2 (history completeness caller-asserted, token-account-blind) | `src/argus/wallets/history_reconstruction.py` (`AcquisitionManifest`/`TokenAccountCoverage` typed structures; HIGH requires `wallet_walk_status == COMPLETE` AND `token_accounts_enumerated is True` AND every known ATA's coverage complete); `src/argus/cli.py` (`--acquisition-status`/`--acquisition-known-gaps` free-text flags removed, replaced by `--acquisition-manifest-file <path>` parsed into the typed structure, fails closed on malformed input) | Unit: `test_p3_history_assessment_derives_from_real_acquisition_manifest_not_a_claim` (all 4 completeness tiers plus `ValueError` on missing manifest under `LIVE_ACQUISITION_WALK`) | FIXED |
| P3-R3 (ledger not round-trip- or quote-safe) | `src/argus/wallets/position_reconstruction.py` (`ALGORITHM_VERSION` bumped to `position_reconstruction_v2`; `_RoundTripState.has_activity` state machine flushes and resets a `ReconstructedPosition` every time `open_quantity` returns to zero; `round_trip_index`/`contributing_swap_ids`/`input_manifest_digest` added; a leg in an incompatible quote asset is excluded from quantity/cost math, preserved as a raw reference, forces confidence to LOW) | Unit: `test_p3_full_close_then_reopen_produces_two_independent_round_trips`, `test_p3_partial_sell_then_later_buy_uses_current_open_inventory_basis`, `test_p3_mixed_quote_asset_never_summed_excluded_as_unresolved`, `test_p3_input_permutations_and_same_slot_ties_are_byte_identical`, `test_p3_decimal_boundary_values_prove_no_float_conversion` | FIXED |
| P3-R4 (recency-window metrics schema-only) | `src/argus/wallets/qualification_service.py` section 5b (writes `WalletMetricsSnapshot` rows for LIFETIME/180D/90D/30D/7D every run, each from the same contamination-filtered, `final_exit_at`/`last_entry_at`-windowed qualifying-position set; an empty window gets explicit zero/null metrics) | Integration: `test_p3_all_five_metric_windows_persisted_with_correct_membership` (real Postgres: a closed round trip 3 days before `as_of` appears in all 5 windows; one 200 days before `as_of` appears only in LIFETIME, never copied into the bounded windows) | FIXED |
| P3-R5 (lottery/drawdown/usable-outcome metrics wrong) | `src/argus/wallets/scoring.py` (`largest_trade_contribution_pct`/`top_three_trade_contribution_pct` now divide by estimated net lifetime P&L, `None` when net P&L <= 0; drawdown equity curve ordered by `final_exit_at`; `distinct_tokens` counts only tokens with a closed usable outcome) | Unit: `test_p3_lottery_dominance_uses_net_pnl_not_gross_gains_with_boundary`, `test_p3_drawdown_uses_final_exit_at_order_not_last_entry_at`, `test_p3_distinct_tokens_counts_only_closed_usable_outcomes` | FIXED |
| P3-R6 (score/tier/identity disagreement) | `src/argus/wallets/qualification_service.py` (cluster-uncertainty penalty folded via `dataclasses.replace` into ONE canonical `ScoringResult` before persistence and tier evaluation; `_score_equal`/`_history_rows_equal` expanded to full semantic identity; `BUILD_HASH` now hashes all 6 Phase 3 artifact files); `src/argus/wallets/tier_lifecycle.py` (`current_tier is None` DISCOVERED special case removed -- desired tier always computed from current evidence); `src/argus/wallets/scoring.py` (`missing_required` now includes `forward_information`) | Integration: `test_p3_cluster_penalty_crossing_tier_cutoff_persists_the_same_adjusted_score` (real Postgres: a 0.60-probability cluster link applies the fixed 10-point penalty, crossing the wallet from TIER_A (73.75) to TIER_B (63.75) -- never QUARANTINE -- and the persisted `WalletScoreSnapshot.qualification_score` is byte-identical to the tier-driving adjusted score), `test_p3_eligible_wallet_first_invocation_not_forced_discovered_replay_idempotent` (an eligible wallet's first score is its real, score-derived tier, never forced DISCOVERED; exact replay creates no new score/tier row -- exactly 1 `WalletTierTransition` row after 2 identical invocations). Unit: `test_p3_missing_forward_information_counts_toward_missing_evidence_and_caps_confidence` | FIXED |
| P3-R7 (checkpoint missing terminal marker) | New `orchestration/checkpoints/phase_3_remediation.md`/`orchestration/bundles/phase_3_remediation.txt` (this checkpoint, correctly terminated); historical `orchestration/checkpoints/phase_3.md`/`.txt` left byte-for-byte unmodified, preserved as evidence of the defect | Unit: `test_validate_checkpoint_content_rejects_missing_end_marker`, `test_validate_checkpoint_content_rejects_the_actual_historical_phase_3_checkpoint` (reads the real, unmodified `orchestration/checkpoints/phase_3.md` from disk and proves the pre-existing, UNCHANGED `scripts/argus_orchestrator_watch.py::validate_checkpoint_content` validator already correctly rejects it -- the defect was in the prior submission process, not the validator; no production-code change was needed or made to the validator itself) | FIXED |

C. Point-in-time knowledge-cutoff matrix

| Evidence source | Bound applied | Where |
|---|---|---|
| `Swap` | `first_seen_at <= now` | `qualification_service.py` swap query, section 1 |
| `Swap.block_time` (economic timestamp, independent of `first_seen_at`) | excluded (not clamped) if `> as_of` | `position_reconstruction.py::reconstruct_positions_for_wallet` |
| `WalletDiscoveryEvent` | `created_at <= now` | `qualification_service.py` section 2 |
| `EarlyBuyer` | `created_at <= now` | `qualification_service.py` section 3 |
| `WalletClusterLink` | `as_of <= now AND created_at <= now` | `qualification_service.py` section 4 |

All 4 evidence sources plus the reconstruction-level `block_time` guard were
unbounded before this remediation (P3-R1's observed proof). Every one is now
bounded to the same immutable `as_of`/`now` parameter passed into
`reconstruct_and_score_wallet`, and position reconstruction, descriptive
metrics, qualification metrics, contamination exclusions, recency windows,
penalties, score snapshots, and tiers all consume that same bounded manifest
-- proven at the real-service level by
`test_p3_service_level_as_of_boundary_excludes_future_cluster_link`.

D. History-coverage matrix (P3-R2)

| `wallet_walk_status` | `token_accounts_enumerated` | ATA coverage | Result |
|---|---|---|---|
| COMPLETE | False | n/a | not HIGH (MEDIUM/LOW per manifest reason) |
| COMPLETE | True | one account PARTIAL/FAILED | not HIGH, exact gap recorded |
| COMPLETE | True | all accounts COMPLETE (or genuinely zero accounts) | HIGH |
| PARTIAL/FAILED | any | any | not HIGH |
| `evidence_source=STREAM_FORWARD_ONLY` | n/a | n/a | LOW (unchanged) |
| no evidence | n/a | n/a | UNKNOWN (unchanged) |
| `evidence_source=LIVE_ACQUISITION_WALK`, `acquisition_manifest=None` | -- | -- | `ValueError`, fails closed |

The CLI no longer accepts a free-text `--acquisition-status`; `argus wallets
reconstruct-and-score` now takes `--acquisition-manifest-file <path>`,
parsing a real JSON manifest into the typed `AcquisitionManifest`/
`TokenAccountCoverage` structures and failing closed (`typer.Exit(code=1)`)
on malformed input.

E. Round-trip / quote-safety matrix (P3-R3)

| Scenario | Result |
|---|---|
| Buy, full close, reopen, full close | 2 independently identified `ReconstructedPosition` rows, each with its own `round_trip_index`, hand-verified PnL/holding-time |
| Buy, partial sell, further buy while open | OPEN position's `average_cost_quote == open_cost_basis / open_quantity`, reflecting current inventory, not the lifetime-flat average |
| Mixed SOL/USDC legs within one open inventory | never summed; round trip forced LOW confidence and excluded from qualification; raw legs preserved via `contributing_swap_ids` |
| Input permutation / same-slot ties | byte-identical output (`test_p3_input_permutations_and_same_slot_ties_are_byte_identical`) |
| Decimal boundary values | no float conversion anywhere in the path (`test_p3_decimal_boundary_values_prove_no_float_conversion`) |

F. Metric-window matrix (P3-R4)

| Window | Membership rule | Empty-window behavior |
|---|---|---|
| LIFETIME | all bounded, contamination-filtered closed round trips | n/a (always has data if any exist) |
| 180D | `final_exit_at` (closed) / last-known-activity (open) within `[as_of-180d, as_of]` | explicit zero counts / null metrics, never a LIFETIME copy |
| 90D | same, 90-day window | same |
| 30D | same, 30-day window | same |
| 7D | same, 7-day window | same |

Real-Postgres proof (`test_p3_all_five_metric_windows_persisted_with_correct_
membership`): a round trip closed 3 days before `as_of` is counted in all 5
windows; one closed 200 days before `as_of` is counted only in LIFETIME.

G. Lottery / drawdown / usable-outcome matrix (P3-R5)

| Case | Result |
|---|---|
| PnL +100 / -90 (net lifetime PnL +10) | ratio 100/10 = 10.0 > 0.70 -- `LOTTERY_DOMINATED` fires |
| Ratio exactly 0.70 | not flagged (strict `>`) |
| Ratio just above 0.70 | flagged |
| Net lifetime PnL <= 0 | contribution is `None` (not-applicable), never a spurious positive-contribution claim |
| Drawdown equity curve | ordered by `final_exit_at` with a stable tie-breaker, not `last_entry_at` |
| `distinct_tokens` | counts only tokens with >= 1 closed HIGH/MEDIUM-confidence round trip with a usable outcome; open/unresolved positions never inflate it |

H. Canonical score/tier matrix (P3-R6)

| Case | Result |
|---|---|
| Cluster penalty crosses A/B cutoff | persisted `WalletScoreSnapshot.qualification_score` and the tier decision both use the SAME `dataclasses.replace`-folded `ScoringResult` -- proven byte-identical at the real-service level |
| Eligible wallet, first invocation | tier is the real score-derived tier, never forced DISCOVERED |
| Eligible wallet, exact replay | no new score row, no new tier row (`score_written=False`, `tier_transition=None`) |
| Missing `forward_information` | counted toward the missing-evidence confidence tally (previously excluded); remains null with its 15% neutral-prior weight, no redistribution |
| Same final score, changed components/penalties/exclusions/history reason/manifest/as_of/build identity | `_score_equal` (11-parameter full semantic comparison) treats this as a NEW snapshot, never deduped |
| History-row equality | now includes `history_completeness_reason` |
| `BUILD_HASH` | hashes all 6 Phase 3 artifact files concatenated, not just `qualification_service.py` |

I. Checkpoint-protocol matrix (P3-R7)

| Item | Result |
|---|---|
| Historical `orchestration/checkpoints/phase_3.md` (no END marker) | rejected by the pre-existing, unmodified `validate_checkpoint_content` -- proven directly against the real file on disk |
| This checkpoint (`phase_3_remediation.md`) | begins with the required `================ ARGUS ORCHESTRATOR CHECKPOINT ================` line and ends with the required `================ END ARGUS CHECKPOINT =========================` line |
| `orchestration/bundles/phase_3_remediation.txt` | contains this checkpoint's bytes verbatim plus the required PROTOCOL.md review items |
| Historical `phase_3.md`/`phase_3.txt` | byte-for-byte unmodified, preserved as evidence |

J. PHASE_3_CANDIDATE_SAMPLE_BLOCKED disposition (unchanged, not a remediation item)

Per `argus-phase-3-remediation-001`'s own explicit statement, "The exact
PHASE_3_CANDIDATE_SAMPLE_BLOCKED result is accepted... It is not a
remediation item." `orchestration/phase_3/SAMPLE_REPORT.md` is unchanged: 1
genuine candidate wallet, zero usable positions, `history_completeness=
UNKNOWN`, `qualification_score=descriptive_score=50.00` (the honest neutral
prior). No new authorized authentic evidence exists in this sandbox that
would change this disposition, so it was not touched.

K. Commands actually run (all against this exact commit -- this
   checkpoint's own `GIT_COMMIT`, filled in by the second commit per this
   project's established two-commit convention)

- `uv run pytest tests/unit/test_phase3_wallet_qualification.py -q` -- 23
  passed (up from 12 in the original submission; +11 new remediation
  tests).
- `uv run pytest tests/integration/test_phase3_wallet_qualification.py -q`
  -- 7 passed (up from 3; +4 new remediation tests, real PostgreSQL 16).
- `uv run pytest tests/unit/test_orchestrator_watch.py -q` (the P3-R7
  focused remediation module) -- includes 2 new tests proving the
  pre-existing checkpoint-marker validator's correctness; full module
  passes.
- `uv run pytest tests/integration/test_migrations.py -q` -- 13 passed (7
  head-revision assertions mechanically updated from `"0010"` to `"0011"`
  for the new migration, same pattern as the original Phase 3 submission's
  `"0009"` -> `"0010"` update).
- `uv run pytest tests/golden tests/replay tests/phase_1_5 -q` -- 112
  passed (unchanged -- regression).
- `uv run pytest tests/integration -q` -- 78 passed (up from 74).
- `uv run pytest -q` (full repository suite) -- 738 passed, 0 failed, 0
  unexplained skipped (up from 721).
- `uv run ruff check .` -- All checks passed.
- `uv run ruff format --check .` -- 211 files already formatted.
- `uv run mypy` (bare -- `[tool.mypy]` scopes this to `src/argus`) --
  Success: no issues found in 110 source files.
- `uv run alembic current` -- `0011 (head)`.
- Migration round-trip: `tests/integration/test_migrations.py`'s
  `test_migration_from_zero_to_head_creates_identity_columns` (zero-to-head
  through 0011), `test_upgrade_head_is_idempotent_and_restart_safe`
  (upgrade-from-0010-equivalent via a second head upgrade, restart-safe),
  and `test_downgrade_then_upgrade_restores_identity_columns_cleanly`
  (downgrade to 0005 then re-upgrade to head, clean) all pass at head
  `0011` -- migration `0011_phase3_remediation_point_in_time_and_ledger_
  integrity.py`'s own `upgrade()`/`downgrade()` are exercised by every one
  of these.
- `uv run argus fixtures validate-real-chain` -- all 12 real-chain fixtures
  ok (unaffected by this round -- regression-confirmed).
- Changed-file secret scan (AWS-style keys, PEM headers, inline
  password/api-key/secret/token literals) across every file this round
  touched (`git status --short`) -- clean, no matches.
- `git diff --stat 69a8de622b1977f92999ca680fcb8d851ba78c9f -- .
  ':!orchestration'` (including the new untracked migration file) -- 15
  files changed, 1957 insertions(+), 363 deletions(-).

PostgreSQL 16 remains the explicit functional substitute for PostgreSQL 17;
none of the above is described as PostgreSQL 17 validation.

L. Test results

- unit `test_phase3_wallet_qualification.py`: 23/23 (was 12/12)
- unit full suite: 548 passed
- integration `test_phase3_wallet_qualification.py`: 7/7 (was 3/3, real
  PostgreSQL 16)
- integration `test_migrations.py`: 13/13
- integration full suite: 78 passed (was 74)
- golden + replay + phase_1_5: 112 passed (unchanged -- regression)
- full repository suite: 738 passed, 0 failed, 0 unexplained skipped (up
  from 721)
- ruff check: clean
- ruff format --check: clean (211 files)
- mypy: clean, 110 source files
- real-chain fixtures: 12/12 ok
- alembic head: 0011

M. Frozen findings disposition summary

All 7 frozen findings (P3-R1 through P3-R7) are FIXED -- see sections B
through I above for the exact code/test/evidence mapping required by this
instruction. No optional hardening item from the `HARDENING_BACKLOG` list
(automated cluster-link discovery, DB-enforced canonical wallet ordering,
automatic RETIRED assignment, additional cluster signals, broader
metric-snapshot deduplication beyond the exact frozen replay requirements)
was pulled into this remediation's scope.

N. Frozen regression (required test category 9)

- The original discovery-contamination fixture
  (`test_p3_discovery_contamination_excluded_from_qualification_not_
  descriptive`, `test_p3_discovery_contamination_never_leaks_through_
  recency_or_tier_gate`, and the integration
  `test_p3_discovery_contamination_excluded_at_the_service_level`) still
  proves descriptive inclusion and qualification exclusion through
  components, counts, windows, penalties, confidence, and tier eligibility
  -- unchanged pass.
- Transfer uncertainty
  (`test_p3_unresolved_transfer_never_becomes_a_fabricated_buy`,
  `test_p3_transfer_alongside_genuine_swaps_downgrades_confidence_not_
  quantity`), small-sample shrinkage
  (`test_p3_tiny_but_superficially_excellent_sample_cannot_reach_top_
  score`), frozen weights/threshold values
  (`test_p3_sample_gate_thresholds_are_the_frozen_v1_values`), migration
  history (0001-0010 all still apply cleanly beneath the new 0011), Phase 0
  through 2 semantics (`tests/unit`, `tests/integration/
  test_phase2_discovery.py` regression-clean inside the full-suite run),
  golden fixtures, replay, and all safety prohibitions remain unchanged --
  all pass unchanged in the full-suite run (section L).

O. Environmental deferrals (unchanged from the original Phase 3 submission;
   none reopened this round, per this instruction's own explicit
   requirement that they "must remain explicitly deferred")

- `LIVE_HELIUS_RPC_VALIDATION` -- DEFERRED_ENVIRONMENTAL_CHECK, unchanged.
- `LIVE_HELIUS_WSS_VALIDATION` -- DEFERRED_ENVIRONMENTAL_CHECK, unchanged.
- `PG17_COMPOSE_VALIDATION` -- DEFERRED_ENVIRONMENTAL_CHECK, unchanged.
  PostgreSQL 16 remains the explicit functional substitute; every
  Postgres-backed command in section K ran against it, never described as
  PostgreSQL 17 validation.
- `BQ_PUBLIC_DATASET_ACCESS` -- unchanged deferral.

None of these deferrals is claimed as PASS, and none authorizes live
readiness by itself.

P. Deviation from the audit instruction

None. Work was strictly limited to the 7 named frozen findings
(`AUTHORIZED_ACTION: REMEDIATE_ALL_FROZEN_PHASE_3_BLOCKERS_ONLY`): no
`HARDENING_BACKLOG` item was pulled into scope; the already-accepted
structural contamination split, frozen component weights, 20-position/
10-token thresholds, transfer-uncertainty rule, honest candidate-sample
fallback, Phase 2 acquisition safety cases, and approved provider
architecture were not redesigned or retuned beyond the minimal wiring these
7 findings required (e.g. `AcquisitionManifest` replacing the free-text CLI
flag for P3-R2, `round_trip_index` added to the existing schema for P3-R3
without rewriting migration 0010). No Phase 4 work was begun. The
historical `orchestration/checkpoints/phase_3.md`/`orchestration/bundles/
phase_3.txt` were not overwritten. `orchestration/ORCHESTRATOR_
INSTRUCTIONS.md` was not modified. No live trade, signing, credential
disclosure, paid-provider upgrade, or threshold relaxation was performed or
attempted.

This sandbox's local PostgreSQL service was found stopped at the start of
this round's validation (unrelated to any change made here) and was
restarted (`sudo service postgresql start`), the same non-destructive,
local dev cluster used throughout this project -- no data lost, no schema
change beyond migration 0011's own deliberate, disclosed data-clearing
step (section Q).

Q. Migration 0011 data-clearing disclosure

Migration `0011_phase3_remediation_point_in_time_and_ledger_integrity.py`
adds new `NOT NULL` columns (`wallet_positions.round_trip_index`,
`wallet_positions.input_manifest_digest`,
`wallet_score_snapshots.input_manifest_digest`) that cannot be honestly
backfilled for rows computed under the pre-remediation, now-fixed buggy
code (single-lifetime-row positions, unbounded evidence queries, the
unadjusted-tier bug). Its `upgrade()` therefore `DELETE`s all rows from the
4 derived/recomputable Phase 3 decision tables (`wallet_tier_history`,
`wallet_score_snapshots`, `wallet_metrics_snapshots`, `wallet_positions`)
and resets `wallets.current_tier = NULL`. All raw evidence tables (`swaps`,
`wallets` identity rows, `wallet_discovery_events`, `early_buyers`,
`wallet_cluster_links`) are completely untouched -- no chain evidence is
lost, only derived decisions computed by code this remediation replaces.
This is disclosed here explicitly, not silent. `downgrade()` reverses the
schema changes only (not data).

R. Known bugs / debt

- No new known bugs are introduced by this round's changes.
- `WalletMetricsSnapshot` now persists all 5 windows (P3-R4 fixed) -- the
  original submission's own disclosed debt item is closed.
- All other known debt items disclosed in
  `orchestration/checkpoints/phase_3.md` sections not superseded by this
  remediation (wallet-cluster-link *detection* from raw evidence is not
  built this round -- only *consumption* of already-persisted links,
  unchanged and explicitly accepted as `HARDENING_BACKLOG` by this
  instruction) remain unchanged and not reopened.

S. Security state

- `LIVE_READY_SOFTWARE=false`, `LIVE_CANARY_PASSED=false`,
  `LIVE_ARMED=false` -- unaffected.
- No signing, signer, private-key, seed-phrase, live-arm, or broadcast path
  exists anywhere in this round's changed files (section K's diff-stat
  file list).
- Credential handling for `HELIUS_API_KEY` is unchanged.
- Secret scan clean on this round's changed files (section K).
- No paid-provider feature enabled; no Phase 4 or later-phase code started;
  `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` not modified.

T. Cost confirmation

No real provider call was made anywhere in this round: every new test uses
the same deterministic fixtures/fakes already established in the Phase 3
codebase (`_FakeSwap`, real-but-local-only Postgres rows via
`connection_for_role(..., DbRole.INGEST)`), never a real or paid provider.
Zero new usage-recorder rows this round.

U. Next specified phase

Per orchestrator instruction `argus-phase-3-remediation-001`, this
instruction approves no phase and authorizes remediation of exactly the 7
named frozen Phase 3 findings. `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`
was not modified.
`docs/BUILD_STATE.md`'s `last_orchestrator_approved_phase` (`2`) and
`approved_commit` are left unchanged -- this session does not and cannot
self-approve Phase 3. Per this project's established two-commit convention,
this checkpoint, the paired bundle, `docs/BUILD_STATE.md`,
`docs/DECISION_LOG.md`, and `orchestration/AGENT_HANDOFF.md` are committed
once with every commit-hash-bearing field set to the literal placeholder
`5713e9bd86011ae1033507fbdab349cc3dc5fdbd`, then a second, immediately following
commit fills in that first commit's own real hash in every one of those
fields -- both commits carry the sole terminal trailer
`ARGUS-INSTRUCTION-ID: argus-phase-3-remediation-001` with no paragraph
after it, verified via `git interpret-trailers --parse` before push.

STOP. Await independent audit of this remediation before any further phase
work. Passing these builder tests does not approve Phase 3.

================ END ARGUS CHECKPOINT =========================
