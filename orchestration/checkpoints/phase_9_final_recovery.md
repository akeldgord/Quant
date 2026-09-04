================ ARGUS ORCHESTRATOR CHECKPOINT ================

RETROACTIVE_POST_BUILD_RECOVERY_CHECKPOINT — NOT A CONTEMPORANEOUS PHASE STOP

A. Identity

PROJECT: ARGUS
SCOPE: Phase 9 (COUNTERFACTUAL ALPHA + SPECIALISTS), MASTER_SPEC.md
section 62 (ENTRY AND EXIT SPECIALISTS) / section 61 (PREDATION
DETECTION) region. This document is NOT a contemporaneous per-phase
orchestrator STOP -- Phase 9 was originally built, and is here
corrected, under the human's explicit authorization for Claude to carry
Phases 7-11 through to completion without the normal per-phase
orchestrator STOP/audit cycle. This checkpoint does NOT claim a
contemporaneous STOP, independent audit, or approval occurred for Phase
9 at build time. It exists solely to satisfy FSR-14
(`argus-final-spec-recovery-001`, instruction section F).
STATUS: RETROACTIVE_RECOVERY_RECORDED (not an orchestrator PASS/approval)
GIT_COMMIT (this checkpoint's own HEAD at authoring time):
50d96933b5ecde421300e96ce7694dfcc3b7ca62

Recovery authority: `argus-final-spec-recovery-001`, item FSR-07 (Phase
9's own fix). `TARGET_COMMIT` audited as contaminated:
`ea77dd55b1e6be91b61b2f8b37e1d70449a3cb30`.

B. What Phase 9 originally built (unchanged by this recovery)

`src/argus/counterfactual/` -- counterfactual alpha estimation
(residual selection alpha against size-matched control tokens), entry/
discovery/validation/exit specialist percentile scoring and dominant-
specialty classification (`argus.counterfactual.specialists`), and
predation-detection scoring (follower influx + leader-exit timing).
This structural build (the alpha estimator, the percentile-ranking
specialist classification, `counterfactual_alpha_estimates`/
`wallet_specialist_scores`/`wallet_predation_scores` persistence, the
CLI `argus counterfactual report` command) is UNCHANGED by this
recovery.

C. The historical leak/omission this recovery repaired (FSR-07)

Phase 9's predation-detection score (`wallet_predation_scores.
predation_score`) was computed from an INCOMPLETE input set: section
61's own required repetition-frequency factor
(`exit_after_influx_count`, already computed but never incorporated as a
confidence factor) and real follower price-impact evidence (the
followers' own Phase 5 executable-entry price impact) were both absent
-- `price_impact_mean` defaulted to `NULL` unconditionally, a disclosed-
but-never-fixed pre-recovery placeholder. Separately, a price-impact
blend-formula defect (`_PRICE_IMPACT_BLEND_WEIGHT = 0.5 + 0.5 *
normalized`) meant the blended score could never exceed the price-
impact-blind core score, structurally capping the metric below its own
intended range regardless of how much real price impact was observed.
Independently, `ALGORITHM_VERSION` (`"counterfactual_alpha_
specialists_v1"`, 36 characters) exceeded the `algorithm_version`
column's `VARCHAR(32)` width on all four Phase 9 tables -- every real
Phase 9 write would have failed under real database constraint
enforcement, undetected because this sandbox's earlier no-Postgres-at-
all environment could never exercise the constraint for real.

D. The corrected implementation

- `src/argus/counterfactual/predation.py`: repetition frequency
  (`exit_after_influx_count`) now enters the score as a disclosed V1
  confidence factor (section 38's own "V1 priors to be evaluated
  prospectively" precedent, never a calibrated probability); real
  follower price-impact evidence is sourced from the followers' own real
  Phase 5 shadow-position `entry_price_impact_pct` (via the same
  production event population `argus.copyability.loaders.
  load_wallet_opportunities` every later phase's own FSR fix reuses).
- `src/argus/domain/wallet_predation_scores.py`: new
  `price_impact_incorporated` boolean column (migration `0033`) records
  HONESTLY, per row, whether real price-impact evidence was actually
  available and used -- missing evidence makes the result explicitly
  partial, never silently treated as complete.
- The price-impact blend formula was corrected to
  `_PRICE_IMPACT_BLEND_FLOOR + normalized_price_impact(...)` (range
  `[0.5, 1.5]`), with the final score capped via `min(core * impact_
  factor, Decimal(1))` -- verified via the full predation unit-test
  suite (17 tests) covering the corrected range end-to-end.
- `ALGORITHM_VERSION` renamed from `"counterfactual_alpha_
  specialists_v1"` (36 chars) to `"counterfactual_alpha_v2"` (23 chars,
  fits `VARCHAR(32)`) -- fixing the write-time constraint violation and
  simultaneously serving FSR-13's own "new algorithm ID when the
  algorithm changes" requirement for this phase.
- `src/argus/cli.py`'s counterfactual report was separately found,
  during this same recovery, to query `WalletSpecialistScore`/
  `WalletPredationScore`/`CounterfactualAlphaEstimate` by the HARDCODED
  OLD string `"counterfactual_alpha_specialists_v1"` in three separate
  `WHERE` clauses, left over from before this very FSR-07 version bump
  -- meaning `argus counterfactual report` had been silently returning
  EMPTY specialist/predation/top-estimate sections ever since FSR-07's
  bump, undetected because the CLI integration test only asserted field
  PRESENCE, not non-empty content. Fixed to reference the real
  `ALGORITHM_VERSION` constant in all three queries and the report dict.
- FSR-13 (this same recovery) registered
  `"counterfactual_alpha_specialists_v1"` in the new
  `contaminated_run_invalidations` registry, superseded by
  `"counterfactual_alpha_v2"`.

E. Actual tests run against the corrected implementation

- `tests/integration/test_phase9_counterfactual_persistence_and_report.py`
  (full file, 6 tests including `test_fsr07_predation_incorporates_
  real_follower_price_impact` and the price-impact-missing/pre-cutoff
  coverage): 6/6 passed in isolation against a fresh, migrated-to-head
  throwaway PostgreSQL 16 database -- including
  `test_cli_counterfactual_report_runs_and_prints_required_fields`,
  which now genuinely exercises the corrected (non-hardcoded) query
  path.
- `tests/unit/test_phase9_*predation*.py` (17 nodes): 17/17 passed,
  covering the corrected price-impact blend formula's full range.
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
FSR-03); the shared long-lived `argus` development database accumulated
cross-test pollution over this long session, so every DB-backed
assertion above was independently re-validated against a fresh,
isolated, migrated-to-head throwaway database.

G. Changed/new files (Phase 9 portion of this recovery, FSR-07 + FSR-13's
   version bump + the CLI hardcoded-version-string fix)

Modified: `src/argus/counterfactual/service.py`, `predation.py`,
`persistence.py`, `src/argus/domain/wallet_predation_scores.py`,
`src/argus/cli.py` (counterfactual report section, three query sites
plus the report dict).
New: `migrations/versions/0033_fsr07_predation_price_impact_
incorporated.py`.

Untouched (preserved byte-for-byte): all Phase 0-6 checkpoint/bundle
files; `MASTER_SPEC.md`; `orchestration/AUDITOR_POLICY.md`;
`orchestration/PROTOCOL.md`; migrations `0001` through `0032` (never
rewritten).

H. Acceptance statement

This document records that Phase 9's incomplete predation inputs, price-
impact blend-formula defect, VARCHAR(32) write-constraint violation, and
the CLI's stale-version-string query bug (FSR-07, discovered and fixed
together in this recovery) were identified and repaired, with real tests
passing against the corrected implementation, as part of the
`argus-final-spec-recovery-001` authorized recovery. It does NOT assert
a contemporaneous orchestrator STOP/independent audit occurred for
original Phase 9 or for this recovery. Final acceptance of the full
recovery contract is recorded separately, per FSR-15/16.

I. Next action

No STOP is issued by this document. Historical-record-keeping only, per
FSR-14. Recovery work on the remaining FSR-01..16 items continues.

================ END ARGUS CHECKPOINT =========================
