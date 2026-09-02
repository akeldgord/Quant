# ARGUS Orchestrator Instructions

OWNER: ARGUS ORCHESTRATOR. Claude must not edit this file.
MASTER_SPEC.md remains authoritative. Read orchestration/AUDITOR_POLICY.md before implementing or auditing.

INSTRUCTION_ID: argus-phase-5-001
ISSUED_AT: 2026-09-02T18:30:00Z
TARGET_COMMIT: 354ed229eb4ba8c16622b008b7494b3687da525e
AUTHORIZED_ACTION: BUILD_PHASE_5_COPYABILITY_AND_FORWARD_INFORMATION
AUTHORIZED_PHASE: 5
APPROVES_PHASE: 4
STATUS: ACTIVE

## Decision and independent Phase 4 disposition

Phase 4 is approved at 354ed229eb4ba8c16622b008b7494b3687da525e as PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION. Implement Phase 5 immediately. Phase 6 is not authorized by this instruction.

Audited submission: handoff-0031-phase-4-recovery-5, implementation a6922ac8df812f48a34ff637ddc17e45f3c5afab, final evidence 354ed229eb4ba8c16622b008b7494b3687da525e, responding to argus-phase-4-recovery-005 at 3250313c2e5a424ec4f438350ca63780276224c2. Ancestry is the instruction followed by the implementation followed by its hash-fill evidence commit. Both Claude commits carry the exact terminal instruction trailer.

The audit was bounded to ASSERT-01, ASSERT-02 and the twelve listed checks. No new proof obligation was added:
- ASSERT-01 PASS: actual parent IDs reach the shared TC-01/03/04 helper; parent-scoped probe counts and wallet-scoped position counts are read before execution, after committed terminal execution, and after a fresh-session repeat. Equality, selected snapshot equality, and one HTTP call remain asserted. TC-02 success does not use the no-new-position helper.
- ASSERT-02 PASS: all 44 TC-04 cases capture DEBUG-and-above across both calls and reload; actual formatted captured text is checked for the existing fake sentinels and nonempty unsafe raw/escaped strings. Status-only persisted evidence remains exact. This is not a requirement for empty logs.
- Check 1 PASS: 94 collected nodes, identical node inventory to recovery-003.
- Checks 2–4 PASS with the existing environmental limitation: pinned builder output reports 162 combined, 128 affected integration, and 1073 full-suite passes. This auditor independently ran 610 unit cases, 96 passing golden/replay cases and 7 feasibility cases. Nine database replay cases and the attempted matrix execution stop at missing ARGUS_DB_ADMIN_PASSWORD, before product execution. These are environmental setup errors, not demonstrated code failures. An initial auditor command named a nonexistent tests/sanity directory and ran no tests; it was corrected, not counted as a pass. No database credential was requested, entered or disclosed.
- Checks 5–9 independently PASS: ruff check, ruff format (265 files in this environment), mypy src (128 source files), single Alembic head 0021, all 12 authentic chain fixtures.
- Checks 10–11 independently PASS on actual final artifacts: validate_checkpoint_content == (True, ''), validate_bundle_content == (True, ''), exact checkpoint bytes embedded.
- Check 12 PASS: clean pinned worktree; exact final trailers. Diff scope is tests, the permitted replay output-directory change, fresh artifacts, handoff/build state and append-only decision log. No src, migration, config, master, auditor policy, protocol, watcher or historical recovery-003 artifact changed.

All previously closed Phase 4 production findings remain CLOSED. No emergency defect was demonstrated. Audit-of-audit: both frozen assertions were inspected at their actual call sites, claims distinguished from independently executed checks, evidence pinned, and no stronger oracle introduced after seal. Approval is engineering acceptance, not empirical alpha validation or live readiness.

Environmental deferrals remain: PG17_COMPOSE_VALIDATION, LIVE_HELIUS_RPC_VALIDATION, LIVE_HELIUS_WSS_VALIDATION, BQ_PUBLIC_DATASET_ACCESS. Builder PostgreSQL 16 evidence remains an explicitly limited substitute, not PostgreSQL 17 validation.

NEXT_PHASE_CARRYFORWARD CF-P4-01: replay tests still invoke a script with a tracked report output default. The builder disclosed temporarily overwriting an old replay report before restoring it; the final historical bytes are unchanged. Consume this issue in P5-11 below. It does not reopen Phase 4.

## Authority, first action and scope

Synchronize and verify the clean branch, the target, its direct-parent instruction-only relationship, and current authorization. Read MASTER_SPEC.md, docs/BUILD_STATE.md, docs/DECISION_LOG.md, orchestration/PROTOCOL.md, orchestration/AUDITOR_POLICY.md, this instruction and the handoff. Record Phase 4 approval above in build state and append the decision log; set current phase to 5, approved phase to 4 and approved commit to the target. Do not self-approve Phase 5.

Use master v2.0, SHA256 41f7242c288feec709b1ed72e62c74a1dc5e3b3cd9ad01e9b6e28373d9d14011. Phase 5 implements sections 46–53 and its named phase gate using the existing Phase 3/4 evidence. This instruction freezes ordinary V1 analytical mechanics where the master specifies a component but not its normalization. These are transparent research priors, not strategy optimization. Existing weights, A/S thresholds, risk settings and live boundaries remain unchanged.

Build deterministic analytical modules under src/argus/copyability and src/argus/scoring, additive snapshot persistence, CLI/report wiring and the tests specified below. Reuse existing database/provider abstractions. No new provider, paid source, network acquisition requirement, model training, executor, signing or live order path. Phase 9 matched-universe controls, Phase 7 graph inference and Phase 8 calibrated convergence remain in their own phases.

Important current data limitation: Phase 4 creates one ShadowPosition per intent, at the first successful entry probe. Its reverse quotes are for THAT position's exact token quantity. Later entry-delay probes are not automatically independently valued positions. Do not scale that reverse quote to value another delay's different quantity. Use genuinely quantity-matched evidence where available; otherwise the cell is unavailable. Implement and test complete analytics on explicitly synthetic fixtures, but never label those as authentic prospective observations. No minimum number of genuine wallets, positive score, complete delay curve or A/S winner is required for Phase 5 acceptance.

## SEALED ACCEPTANCE CONTRACT — phase-5-v1

The complete blocking contract is P5-01 through P5-14 below, including the referenced mechanics and finite test cases. It is sealed by publication of this instruction. Test names may be selected by Claude, but the cases/assertions below may not be omitted; map each to exact pytest node IDs before handoff. No later auditor may add a new blocking behavior, case, oracle or evidence obligation. A newly noticed legitimate non-emergency issue outside these rows is NEXT_PHASE_CARRYFORWARD; optional work is HARDENING_BACKLOG. Only the narrow demonstrated emergencies in AUDITOR_POLICY section 5 may stop outside a frozen ID.

Environmental rule E applies to every row: use existing authorized evidence and local test infrastructure. Missing live access, PG17 infrastructure or auditor credentials may be explicitly deferred with the attempted command, reason, substitute evidence and remaining limitation. Synthetic fixtures establish software behavior only. A missing implementation or missing specified test is not an environmental limitation. No authority to provision or disclose secrets is granted.

### Frozen analytical mechanics M1–M7

M1 — Identity, times and units.
Every derived record carries wallet/event/source IDs, evidence class (AUTHENTIC_PROSPECTIVE, HISTORICAL, REPLAY, SYNTHETIC or UNKNOWN), as_of, computed_at, algorithm/config identity and contributing/excluded source IDs with reasons. Separate actual request/response, target delay and actual delay from first_seen_at. Use Decimal/integer raw amounts; ratios are dimensionless, return_pct = 100 * return_fraction. Reject zero/nonpositive denominator, mismatched mint/quantity and nonfinite values with explicit unavailable reasons. Do not sum currency amounts across mints.

Outcome summaries at cutoff C include only sources created/known by C and terminal/response/effective times <= C. Future or not-yet-terminal evidence cannot enter earlier summaries. Readiness at decision D may use only evidence known by D and excludes the current event's own future evaluation outcomes. Never overwrite Phase 4's point-in-time event snapshots or Phase 3 scores/tier history.

M2 — Executable outcomes and delay curves.
For an entry spending I raw units of quote mint and acquiring Q token raw units, a matching successful reverse quote selling exactly Q back to the same quote mint for O has quoted return O/I - 1. Include only separately evidenced additional costs, in the same quote unit, once; do not subtract DEX fees already incorporated in quote output twice. Preserve gross quoted return, cost basis/coverage and net-after-known-additional-cost return separately; unknown transaction costs remain a limitation, never an assertion of fully realized net performance.

Keep all entry/reverse terminal classifications, including NO_ROUTE, INSUFFICIENT_LIQUIDITY, PRICE_IMPACT_EXCESSIVE, QUOTE_FAILED, TOKEN_RESTRICTED and PROVIDER_CAPACITY_MISS. Failure has no invented numeric return; it remains in status/coverage/executability denominators. Pending/future rows remain explicitly pending. Mark returns remain separately labeled and never substitute into executable return.

Produce delay cells for targets 1/5/15/30/60/300 seconds and executable horizons 5m/30m/1h/6h/24h. Report actual delay and horizon durations, counts, distinct events/tokens, outcome classes, available return summaries and unavailable reasons. A late +1s target at +2.7s stays target=1s, actual=2.7s, not an observed +1s fill. Do not combine mismatched horizon, notional or evidence classes into one curve. Raw currency totals are grouped by mint. Identical event repetitions deduplicate, and six probes do not count as six independent wallet trades.

M3 — Information retention and forward value.
Use the available quantity-matched executable outcome family. Report a forward-information grid at 5s/15s/30s/60s/5m/30m/1h/6h/24h measured from first_seen_at, with actual evaluation times. Do not relabel an entry-relative +5m exit as first_seen-relative exactly +5m. Where there is no observation at a requested horizon, retain the actual observation separately and mark that exact cell unavailable; do not interpolate prices or invent quotes.

V1 benchmark is holding the same quote-asset units (zero return in that numeraire). Remaining executable return versus this explicitly named cash baseline is a forward-value proxy, not market-adjusted/residual selection alpha. A matched-universe abnormal-return field remains NULL with PHASE_9_MATCHED_CONTROLS_UNAVAILABLE unless actual already-authorized benchmark evidence is supplied; this phase must not build Phase 9.

For half-life, compare at least two delay points on the SAME event cohort, notional, quote unit, executable horizon and evidence class. Use median return fractions. Select the positive peak (earliest actual delay for ties). The half-life is the elapsed time from that peak to the first later OBSERVED point <= half the peak. Report also that crossing's absolute delay from first_seen_at. No fitted decay, forced monotonicity or interpolation. If no positive peak: NO_POSITIVE_SIGNAL; no later crossing: RIGHT_CENSORED and NULL half-life; incompatible/missing matched cohort: INSUFFICIENT_COMPARABLE_EVIDENCE. Record best observed delay even if it is not the earliest. Descriptive unmatched curves may still be reported, labeled non-comparable for half-life.

M4 — Robust size surprise.
Use the wallet's last at most 100 known prior positive buy notionals in the SAME quote mint during the 90 days strictly before the signal. Exclude the current buy, future-known rows, duplicates and persisted discovery-contaminating token evidence from the selection-usable baseline. Record median m, median absolute deviation MAD, baseline count, typical absolute size and recent median. When n>=5 and MAD>0, z=(current_size-m)/(1.4826*MAD). Store unbounded z descriptively and component=clamp(50+10*z,0,100). For n<5, m<=0 or MAD=0: z/component unavailable with a reason; size/m may remain descriptive when defined. Portfolio-relative statistics require actual point-in-time portfolio-value evidence in compatible units; otherwise NULL, not the sum of known open positions represented as total wealth.

M5 — Copyability V1 score and confidence.
Use precisely the existing config/signals_v1.yaml weights: prospective delayed follower alpha .35, liquidity/executability .15, post-entry stability .10, holding-duration suitability .10, latency tolerance .10, slippage sensitivity .10, sample confidence .10. Components are [0,100] and stored separately with availability/reasons. Freeze the normalization version as copyability_components_v1:
- delayed follower alpha proxy = clamp(50+100*median executable return fraction versus M3's quote-asset cash baseline,0,100), calculated at the fixed primary 5m executable horizon; label the benchmark/proxy, not matched-universe alpha.
- liquidity/executability = 100*successful quantity-matched reverse outcomes / all terminal reverse outcomes, within the fixed primary horizon. Capacity/quote failures stay in the denominator with breakdown; unknown future outcomes do not.
- post-entry stability = 100*nonnegative successful executable outcomes / successful executable outcomes across the listed observed horizons, first averaged within each event, then across events (one event cannot dominate by having more probes).
- holding-duration suitability = 100*the fraction of comparable same-event pairs whose 30m executable return is >= their 5m return. Missing pairs => unavailable.
- latency tolerance = clamp(100*positive_return_at_latest_comparable_delay/positive_peak_return,0,100), using M3's comparable curve; no positive peak => 0 when adequate comparable evidence exists, otherwise unavailable.
- slippage sensitivity = clamp(100*(1-mean absolute price-impact fraction),0,100) over eligible entry quotes; convert an explicitly evidenced persisted impact unit exactly once (fraction .02 and percentage-point 2 both mean .02 fraction). If a legacy source does not establish its unit, use NULL/IMPACT_UNIT_UNKNOWN rather than infer from the field name. This single-notional V1 impact proxy is not an empirically measured multi-notional sensitivity curve; store that limitation.
- sample confidence = 100*c, below.

Let n = distinct events with a usable quantity-matched primary-horizon executable return; k = their distinct non-null tokens; coverage = successful usable primary-horizon pairs / all eligible terminal entry-event opportunities (one per event, including entry failures/missing reverse outcomes; if denominator zero, coverage=0). c=min(1,n/20,k/10)*coverage. Confidence UNKNOWN when n=0; LOW if n<20 or k<10 or c<.5 or history completeness LOW/UNKNOWN; otherwise MEDIUM if c<.8 or completeness MEDIUM; otherwise HIGH. Persist n, k, denominator, c and confidence separately.

Missing components keep their frozen weight and a labeled neutral prior 50; no redistribution. With n=0, total copyability_score is NULL (components/prior contribution may be reported). With n>0, sum each frozen weight*measured-or-neutral component, without optimization. Missing components are not counted as measured evidence: also store available_weight and cap confidence LOW if available_weight<.5, MEDIUM if <1. These are new analytical confidence conventions, NOT changes to Phase 3 A/S eligibility. No retrospective rewrite/injection into existing qualification scores is authorized.

M6 — Opportunity readiness V1, research only.
Use existing weights exactly: qualification .20, copyability .20, remaining information at current delay .15, liquidity/executable impact .15, price movement since leader .10, relative size surprise .10, independent confirmation .10. Qualification comes from the frozen qualification snapshot, never descriptive score. Copyability is an eligible as-of analytical snapshot excluding the current event. Remaining information = clamp(50+100*r,0,100) for the latest nonfuture comparable observed return proxy at delay <= current elapsed delay; no extrapolation beyond available support. Liquidity/impact uses M5's impact normalization on the actual current valid quote. Price movement component = clamp(100-100*max(0,current_price/leader_price-1),0,100), only when both contemporaneous prices are evidenced and comparable. Size uses M4. Independent confirmation is 100 only for an evidenced independent confirming actor and 0 for evidenced absence; unknown dependence remains NULL, never inferred independent from different addresses. Advanced calibrated convergence is not built.

Evaluate the six master hard gates BEFORE an eligible score: token safety, chain freshness, wallet eligibility, history quality, quote validity, risk caps. Each is PASS/FAIL/UNKNOWN with evidence/reason; any FAIL/UNKNOWN => eligible=false and actionable_score=NULL. A clearly labeled research diagnostic weighted score may still be displayed using neutral 50 for unavailable components without weight redistribution. It is never an order or permission. Known component inputs outside [0,100] or nonfinite are invalid, not silently trusted. A/S, qualification>=85, copyability>=75, readiness>=90 and existing configured confidence/risk constraints are not weakened. If a later-phase risk/independence source does not yet exist, its gate/input is UNKNOWN, not fabricated PASS. All-gates-pass fixtures may test the numerical path, but real live authorization remains false unconditionally in this phase.

M7 — Separation and lineage.
Compute descriptive summaries separately from selection-usable summaries. Derive exclusions from persisted wallet_discovery_events provenance, not a caller's optional manual list. Discovery-contaminating observations may appear in descriptive output but not selection-usable components, sample/coverage counts, confidence, half-life, size baseline or readiness support. Preserve and report excluded IDs/reasons/counts. HISTORICAL/REPLAY/SYNTHETIC cannot become AUTHENTIC_PROSPECTIVE through a filename, report mode or later import. Unknown origin stays UNKNOWN and is excluded from authentic selection statistics until established by persisted provenance. Historical prior is a separately labeled nullable field in V1; do not blend it into measured prospective confidence or select wallets using it.

### P5-01 — As-of evidence and provenance
Failure classification: SPEC_BLOCKING. Evidence: production loader/lineage schema implementing M1/M7 and tests.
Exact cases: two wallet events with known times; append a future outcome and a late-recorded but backdated source; query the old cutoff and assert identical selected IDs, component inputs, counts and scores. Change current wallet score/tier after event creation and assert original frozen event values are used. Assert an outcome belonging to the current opportunity cannot enter its earlier readiness inputs. Test cutoff equality and one instant after cutoff.
PASS: all stated invariants hold through the production loader, not only hand-built feature objects. Environmental rule E applies.

### P5-02 — Executable arithmetic, failures and matching
Failure classification: SPEC_BLOCKING. Evidence: M2 calculator, loader, exact unit and database tests.
Exact cases: I=100,Q=200,O=120 => gross .2/20%; separately evidenced extra same-unit cost 5 => net .15/15%; absent cost => unknown-cost flag. Fee already included in O is not subtracted again. Include zero denominator, wrong mint, reverse quantity 201 instead of 200 and nonfinite input: unavailable, never fabricated return. Include each of the six terminal failure classes named M2 and pending. Positive mark +500% with NO_ROUTE yields no positive executable return and remains in failures. A later-delay entry with different Q cannot reuse the first ShadowPosition reverse quote.
PASS: exact Decimal results, explicit unavailable reasons, preserved classification/denominators and no fabricated fill. E applies.

### P5-03 — Delay curves and half-life
Failure classification: SPEC_BLOCKING. Evidence: M2/M3 production functions and deterministic fixtures.
Exact cases: complete six-delay matched cohort; target1/actual2.7; missing delay; incompatible notional/horizon; same event repeated. Curve medians .4 at1s,.2 at5s,.1 at15s => peak1, crossing5, elapsed4. Delayed peak .1 at1s,.4 at5s,.2 at15s => best5, crossing15, elapsed10. Also test tied peaks, no positive values, no crossing and unmatched event cohorts.
PASS: expected observed crossing/best delay, explicit censor/missing reasons, actual timing retained, repeat/input permutation identical, distinct-event counts not probe counts. E applies.

### P5-04 — Forward information values
Failure classification: SPEC_BLOCKING. Evidence: M3 calculator/report fields.
Exact cases: leader at t0, ARGUS first_seen t0+20s, exit measured first_seen+30s; report observation-relative timing not leader-relative50s. Entry delayed5s plus holding horizon5m must not be labeled first_seen+5m. Test executable/mark disagreement, missing exact horizon, and absent matched benchmark.
PASS: all nine horizon cells represented as measured or explicitly missing; cash-baseline proxy, executable versus mark and residual-alpha unavailability separated. No later chart/backfill price used for historical execution. E applies.

### P5-05 — Size surprise
Failure classification: SPEC_BLOCKING. Evidence: M4 production query/function.
Exact cases: prior sizes [1,2,3,4,5], current9 => median3,MAD1,z=6/1.4826; component clamps as specified. Test one huge outlier, n4, constant-size MAD0, mixed quote mints, current event exclusion, future-known/backdated buy exclusion, duplicate buy and missing portfolio valuation.
PASS: exact robust formula, baseline restricted to100/90d, named missing reasons and no invented portfolio-relative figure. E applies.

### P5-06 — Copyability and small samples
Failure classification: SPEC_BLOCKING. Evidence: M5 constants/config binding, pure function and loader tests.
Exact cases: all measured components80 => score80; one unavailable component retains weight*.50 prior contribution rather than redistributing. n=0 => NULL/UNKNOWN; n=1,k=1; n=19; k=9; n=20,k=10 with full coverage; low history; half coverage; unavailable-weight caps. Add a terminal unsuccessful opportunity and assert coverage/executability cannot improve. Repeat six probes from one event and assert n unchanged.
Also test impact .02 with explicit fraction units and 2 with explicit percentage-point units => component98, and absent impact unit => unavailable. PASS: exact frozen weights/normalizations and expected confidence boundaries; raw measured/missing values and prior contributions inspectable; no threshold/config retuning. E applies.

### P5-07 — Discovery firewall and evidence-class separation
Failure classification: SPEC_BLOCKING. Evidence: persisted-provenance production path implementing M7.
Exact database case: TOKEN_A discovers W; add very profitable A outcomes and extreme A sizes plus separate clean B/C outcomes. Compare with/without contaminating evidence: descriptive output/excluded reports may change, but every selection-usable component, count, coverage, confidence, half-life/size baseline and readiness support is identical. Add historical/replay/synthetic rows and assert they cannot inflate authentic prospective statistics. Test no genuine prospective evidence.
PASS: exact secondary-aggregate exclusion and class separation; no fabricated authentic sample. E applies.

### P5-08 — Readiness and hard gates
Failure classification: SAFETY_OR_INTEGRITY_BLOCKING. Evidence: M6 production readiness entry point and tests.
Exact cases: all seven component values80 with six passing gates => research numerical result80; one missing component contributes neutral50 at its original weight and is labeled. For EACH of the six gates, independently test FAIL and UNKNOWN with otherwise100 inputs: eligible=false, actionable_score=NULL. Test lower tier, LOW/UNKNOWN history, stale/invalid quote, zero/default risk allowance, out-of-range/nonfinite input, unproven independence and current-event future data. Test A/S versus B/unknown, qualification84.999/85, copyability74.999/75 and readiness89.999/90 without changing thresholds; existing configured confidence/risk constraints must still apply.
PASS: gates precede eligible scoring, qualification not descriptive, no bypass from high weighted score, and no live permission/dispatch under any fixture. E applies.

### P5-09 — Append-only analytical persistence and restart
Failure classification: SPEC_BLOCKING. Evidence: additive migration/models and real database round-trip.
Store immutable per-wallet summary and per-opportunity readiness snapshots with M1 lineage and stable unique identity based on subject, as_of, algorithm/config and evidence manifest digest. Same input rerun/restart yields the same semantic result and no extra snapshot; changed evidence/version yields a new snapshot, not an overwrite. Hash serialization uses stable ordering and Decimal strings; computed_at must not destabilize semantic identity.
Exact tests: two executions separated by new sessions; duplicate/concurrent insertion; transaction rollback then retry; changed version; upgrade from current0021 with a completed Phase4 row and verify it is unchanged. Capture scoped counts and snapshot values before/after.
PASS: unique idempotent result, preserved earlier snapshots/raw records, clean additive upgrade with one migration head. No destructive data migration. E applies.

### P5-10 — Runnable report and actual sample
Failure classification: SPEC_BLOCKING. Evidence: actual CLI wiring (choose and document one command under "argus copyability") and report JSON/human rendering.
Command accepts explicit as-of and optional wallet filter, loads persisted sources, runs calculators, persists/reuses snapshots and produces report. A read/report-only invocation does not dispatch quote providers or modify prior evidence.
Exact integration test: seeded persisted event/entry/reverse sources -> real command -> reload snapshot -> parsed report; run twice, assert stable source IDs/results and no duplicate snapshot. Include an empty database and a tracked wallet with partial data.
Report fields: wallet, qualification score, leader result if evidenced, follower1/5/15/30/60/300, actual delays, executable/mark outcomes, forward grid, half-life/best delay or reason, copyability/component values, size surprise, readiness/gate reasons, sample counts/confidence, exclusion/class breakdown, versions/as-of and limitations.
PASS: these fields are populated or explicitly unavailable; the checkpoint includes a genuine-current-evidence report with actual wallet count (zero/one allowed) AND a separately labeled deterministic synthetic demonstration. No paid/new sources or invented success to fill sparse cells. E applies.

### P5-11 — Consume CF-P4-01: safe replay artifact output
Failure classification: SPEC_BLOCKING. Evidence: replay script output-path interface and regression test; preserve existing isolated-database guards.
Implement an explicit output-directory option with a fresh untracked temporary/run-specific default. Tests pass tmp_path; neither defaults nor tests write historical orchestration evidence. Explicit export to a NEW phase5 evidence path is allowed. Refuse an existing output file rather than overwrite; do not add an overwrite flag.
Exact tests: two default invocations use separate destinations; explicit tmp output succeeds; an existing sentinel target fails and its bytes remain identical; existing tracked phase4/earlier artifact hashes are unchanged after the replay integration suite; existing shared-DB isolation tests still pass. Path validation occurs before expensive replay/provider work.
PASS: no manual EVIDENCE_DIR edit or restoration is needed to run tests, no old evidence rewrite, and database isolation semantics unchanged. E applies.

### P5-12 — Frozen regression/tool checks
Failure classification: SPEC_BLOCKING. Evidence: commands and complete output summaries.
Run: all new Phase5 unit/integration tests; the existing 94-case phase4 recovery matrix; tests/integration/test_phase4_recovery_2.py; tests/unit/test_phase4_recovery_2_contract.py; the seven affected Phase4 files listed below; full uv run pytest -q; uv run ruff check .; uv run ruff format --check .; uv run mypy src; uv run alembic heads; uv run argus fixtures validate-real-chain.
The seven files are test_shadow_phase4_remediation_observation.py, test_shadow_quote_jobs_provider_remediation.py, test_shadow_phase4.py, test_shadow_phase4_concurrency_remediation.py, test_migrations.py, test_daily_report_remediation.py and test_replay_demo_isolation.py under tests/integration/.
PASS: no non-environmental failures; baseline tests not removed/weakened/skipped to force green; 94 existing matrix nodes retained; one migration head, 12 authentic fixtures pass. Record any initial failing command plus successful correction, not only final totals. E applies.

### P5-13 — Self-audit and final evidence binding
Failure classification: SPEC_BLOCKING. Evidence: new orchestration/checkpoints/phase_5.md, orchestration/bundles/phase_5.txt and orchestration/phase_5/evidence/.
Before READY_FOR_AUDIT, enumerate P5-01..P5-14 with implementation symbols, exact test nodes/commands, actual results, pass condition and any E limitation. Include report, input/source manifest, versions/config/master hash, migration head, relevant counts, command output, changed-file list and explicit carryforward/debt/authority state. An aggregate green count without a specified row's actual assertion is not proof.
Use the standard ARGUS checkpoint markers and required validator sections. After final commit hashes are filled, invoke the real watcher validate_checkpoint_content and validate_bundle_content on FINAL files and assert both (True, '') AND exact complete checkpoint bytes in bundle. Preserve all historical checkpoints/bundles/evidence.
PASS: complete14-row mapping, exact validators/embedding, real run-local commit IDs, new paths, truthful actual sample and clean final worktree. E applies only to genuinely unavailable external execution, not these local artifacts.

### P5-14 — Scope, secret safety and handoff
Failure classification: SAFETY_OR_INTEGRITY_BLOCKING. Evidence: final diff, config comparison and fake-sentinel/no-dispatch tests.
No live/mainnet order, canary, signing/private-key/seed access, credential entry/disclosure, paid provider/upgrade, live arming, evidence rewrite, phase skip or threshold relaxation. New analytics command tested with provider/signing dispatch replaced by a raising sentinel must complete without dispatch. New report/exception/log paths given inert fake credential sentinel fields must omit those fields/values from emitted reports and captured DEBUG logs (safe reason/status allowed). Do not log an environment dump.
Allowed edits: Phase5 analytics/domain models/additive migrations, minimal config schema additions for algorithm identity without existing weight/threshold changes, CLI/report wiring, new tests plus necessary replay-output test updates, replay script for P5-11, new phase5 evidence, build state/append decision log/handoff. Existing Phase4 sources only for bounded wiring; no unrelated cleanup. No MASTER_SPEC/policy/protocol/watcher change.
Handoff must have the existing standard fields/sections, CURRENT_PHASE 5, LAST_ORCHESTRATOR_INSTRUCTION_ID exactly argus-phase-5-001, new phase5 paths and run-local CURRENT_COMMIT, clean worktree. Every Claude commit message ends with the exact final nonblank line:
ARGUS-INSTRUCTION-ID: argus-phase-5-001
Nothing after that trailer. Record this Phase4 approval but never self-approve Phase5.
PASS: scoped diff, unchanged existing authority/strategy settings, no secret leakage/no dispatch under specified tests, valid unique handoff and exact terminal trailers. E applies.

## Architect pre-seal review and carryforward disposition

Before publication I checked this contract against the Phase5 build list and five acceptance statements, source schemas (including the one-position-per-intent limitation), existing config weights and the auditor policy. All eight build outputs and required report fields are mapped to numbered rows. Known malformed/missing/unit/time/sample/firewall/restart/gate/report/evidence/output-overwrite proof obligations are specified before code, not left for a later stronger oracle.

Ordinary implementation choices are fixed: deterministic Decimal statistics, observed-point half-life, explicit cash baseline, neutral missing-component priors without redistribution, separate evidence classes, append-only snapshots and existing CLI/database stack. No current provider API assumption or new paid capability is required. No performance/alpha target is imposed.

CF-P4-01 is consumed by P5-11. Matched-universe residual alpha is explicitly Phase9; calibrated convergence Phase8; ancestry Phase7; isolated executor Phase6. They are not hidden Phase5 requirements. Existing environmental deferrals and optional raw-output whitespace cleanup remain nonblocking. No other new carryforward is introduced by this audit.

The contract is identified by argus-phase-5-001 / phase-5-v1 and the immutable instruction commit/blob. At session start Claude must record that carrying commit and SHA256 of the exact bytes between the SEALED ACCEPTANCE CONTRACT heading and the Architect pre-seal review heading in the checkpoint. This digest records the seal; it does not authorize editing this instruction. The subsequent auditor must compare that digest to the original instruction.

If a frozen test reveals a genuine implementation failure, fix it within this one build before handoff. Do not call the work ready while a specified non-environmental row fails. Unlisted improvements go to NEXT_PHASE_CARRYFORWARD or HARDENING_BACKLOG. Later audit may issue at most one consolidated ordinary remediation against existing IDs; persistent failure requires root-cause review followed by a newly sealed safe recovery, not an unexplained approval pause.

## Handoff and STOP

Implement the complete authorized Phase5 scope, self-audit the sealed rows, commit/push fresh evidence, verify clean synchronized HEAD, and STOP. Do not begin Phase6 or wait/poll inside the coding session. The orchestrator will independently audit exactly this seal and authorize the next safe phase after PASS.
