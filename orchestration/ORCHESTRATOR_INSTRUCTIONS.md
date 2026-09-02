# ARGUS Orchestrator Instructions

OWNER: ARGUS ORCHESTRATOR. Claude must not edit this file.
MASTER_SPEC.md remains authoritative. Read orchestration/AUDITOR_POLICY.md before acting.

INSTRUCTION_ID: argus-phase-5-remediation-001
ISSUED_AT: 2026-09-02T20:30:00Z
TARGET_COMMIT: 63e5610d091aec132da23b95313a0d15d0d7d3fe
AUTHORIZED_ACTION: REMEDIATE_PHASE_5_EXISTING_SEALED_CRITERIA
AUTHORIZED_PHASE: 5
APPROVES_PHASE: NONE
STATUS: ACTIVE

## Decision, scope and seal

Phase 5: FAIL_EXISTING_CRITERION / REMEDIATION_REQUIRED. This is its FIRST consolidated ordinary remediation, not another Phase 4 repair. Implement the complete packet below now. Phase 6 remains unauthorized. No human approval pause is needed for this bounded work.

Audited handoff: handoff-0032-phase-5-001 at final evidence commit 63e5610d091aec132da23b95313a0d15d0d7d3fe, implementation aac910cee873851f266d6d98eb60d90c4be3d49a, responding to instruction argus-phase-5-001 at 102e6a49b159af76b9cde677cb24ed79b09b523f. Ancestry and both terminal instruction trailers match. Reads, code inspection and executions were pinned to that final evidence commit.

The ONLY functional acceptance contract remains phase-5-v1, P5-01 through P5-14 and M1-M7, published BEFORE implementation at 102e6a49b159af76b9cde677cb24ed79b09b523f. Original instruction blob cab1fbb6e6700bd7ab8cd38e8410d8ed07039ae1. Original sealed section is 25966 UTF-8 bytes, SHA256 d2291c823715a51e9c3aa92b8a758c2b703c57b88f03cb2d0637a5bbe2c294b5, offsets 6333:32299 in that instruction. This digest independently matches the submitted checkpoint. Its exact text is reproduced below. The findings below explain existing failures; they add no new criterion, case, threshold, proof standard or provider requirement.

Administrative substitutions only: this remediation uses its own instruction ID/trailer, target commit and fresh evidence paths listed at the end. Where the reproduced original P5-13/P5-14 names original submission paths or argus-phase-5-001, use the remediation paths/ID for the NEW submission, while preserving the original artifacts and original seal. This does not alter any behavior/test obligation.

Approved phases 0 through 4 remain approved; Phase 4 is PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION at 354ed229eb4ba8c16622b008b7494b3687da525e. Never reopen closed Phase 4 findings. MASTER_SPEC v2.0 SHA256 remains 41f7242c288feec709b1ed72e62c74a1dc5e3b3cd9ad01e9b6e28373d9d14011. No config weight, threshold, risk allowance or authority relaxation. No new paid/source access, credential entry/disclosure, live/mainnet/canary/signing/private-key/seed work, destructive migration, raw/evidence rewrite or phase skip.

## Independent audit evidence and limitations

Independently executed on pinned HEAD:
- New Phase 5 unit files: 96 passed.
- tests/unit tests/golden tests/phase_1_5: 808 passed.
- Full uv run pytest -q --tb=no: 839 passed, 21 skipped, 314 setup errors. Database-backed cases cannot acquire the required local database credential in this audit environment. A separate attempted Phase 5 integration run with -x shows MissingCredentialError for ARGUS_DB_ADMIN_PASSWORD before product execution. No credential was requested, entered or disclosed. These unavailable executions are environmental rule E, not product failures or new blockers.
- Existing Phase 4 recovery matrix: 94 nodes collected; its source and all old baseline test files are unchanged.
- ruff check and format: PASS (290 files formatted); mypy src: PASS (141 source files).
- Alembic: one head, 0022. This verifies graph shape, NOT a live upgrade.
- Authentic fixture validation: all 12 PASS.
- Final checkpoint validator and bundle validator both (True, ''); exact complete checkpoint bytes embedded.
- Clean pinned worktree; unchanged master, policy, protocol, watcher, existing config and historical evidence. The diff is scoped to the new Phase 5 implementation/evidence and permitted replay/CLI work.
- Read-only isolated probes executed the production pure functions/service and production loader transformations with controlled returned rows. They demonstrate the numerical/time failures described below without a live database. The concurrent-insert defect is supported by source inspection plus a real SQLAlchemy transaction-context reproduction without database I/O; a real concurrent database test remains required by original P5-09 and subject to E.

The builder's 839 passed / 335 skipped is its own environment's report, not this auditor's result. Missing infrastructure is accepted under E. Missing implementations or missing pre-specified test assertions are NOT E. No live action, secret exposure or destructive data loss was observed. This disposition does NOT invoke the policy's emergency exception.

Audit command correction: an initial text lookup used nonexistent scripts/argus_watcher.py; corrected to scripts/argus_orchestrator_watch.py. An initial transaction probe had an unbound AsyncSession and yielded UnboundExecutionError; corrected by binding a nonconnecting async engine, where rollback then execute inside the same outer begin raises InvalidRequestError. Neither initial attempt is counted as proof.

## Consolidated findings and authorized corrections

### F5-01 — Production knowledge-time, provenance and size-baseline selection

Classification: SPEC_BLOCKING.
Frozen IDs: P5-01, P5-05, P5-07; mechanics M1, M4, M7.
Locations: src/argus/copyability/loaders.py and service.py; derived lineage models.

Observed:
- load_wallet_shadow_positions bounds position.created_at and probe.terminal_at but not probe.created_at/responded_at. A controlled probe created/responded one instant AFTER cutoff, with terminal_at equal to cutoff, is included (one selected observation instead of zero). _load_long_horizon_returns has the same incomplete source-time treatment.
- load_prior_buy_sizes tests first_seen_at but not Swap.created_at. A buy first seen before C but recorded after C remains in the returned baseline. Dedup is swap_id rather than the underlying repeated buy/event identity.
- compute_wallet_copyability passes token_id_by_mint={} to the real baseline loader. Consequently persisted discovery-excluded token IDs cannot exclude those buys by output mint.
- The service substitutes current_size=None with zero, producing z=-2.023472278429785511938486443 for prior [1,2,3,4,5] instead of missing-current evidence. It uses as_of as signal time rather than an actual selected opportunity's signal/current-buy identity.
- Table membership is assumed authentic in loader documentation; the production path does not establish evidence class from persisted provenance. identity.py constants do not enforce class separation. Full event/entry/outcome/score/history/exclusion lineage is not carried through the result.

Failed pass condition: late/future evidence and discovery evidence cannot alter old selection inputs; actual prior-buy/evidence-class restrictions and explicit unavailable current size must hold through the loader, not just helper objects.

Correction:
- Load one provenance-bound, knowledge-time-bounded evidence set for each cutoff/decision; require applicable created/known AND response/terminal/effective times <= cutoff. Preserve frozen event score/tier/history references rather than substituting the wallet's current state. Explicitly exclude the current opportunity from its own readiness support.
- Resolve token mint/ID joins from persisted records; apply persisted discovery exclusions to every selection-usable family, including sizes. Select the last at most 100 prior positive buys in the same quote mint and 90-day signal window; exclude current, duplicate and future-known/backdated buys.
- Carry evidence class, subject/source IDs, actual times and exclusion reasons in the analytical data passed onward. Unknown origin is UNKNOWN and excluded from authentic prospective selection, not promoted because it resides in a production table. Historical priors remain separately labeled. Use synthetic fixtures for complete software behavior; do not relabel them authentic.
- Preserve missing current size/portfolio valuation as unavailable, not zero or inferred wealth. Do not fabricate a signal for a wallet with no current opportunity.
- Prove the original P5-01 temporal/frozen-snapshot cases, P5-05 query cases and full P5-07 secondary-aggregate/class case, with real production loader calls. Complete cases are in the unchanged seal below.

### F5-02 — Executable outcomes, cohort matching and incorrect time labels

Classification: SPEC_BLOCKING.
Frozen IDs: P5-02, P5-03, P5-04; mechanics M1-M3.
Locations: executable_returns.py, delay_curves.py, loaders.py, service.py.

Observed:
- A 5s delayed entry's 5m holding return .2 is labeled by the production service as an available first_seen+5s forward return .2. Long holding labels are similarly used as first_seen labels without entry/actual exit time adjustment. This contradicts the original explicit entry5s+holding5m case, not a newly requested clock convention.
- The test named test_entry_delayed_5s_plus_5m_holding_reported_at_5m_not_first_seen_plus_5m_mislabel asserts a measured 5m cell instead of checking the forbidden relabel. The leader/first_seen test has no timestamps.
- DelayObservation/DelayPoint retain nominal target seconds but not actual request/response delay, notional, unit, horizon and class needed for comparison. The target1/actual2.7 test never constructs or asserts 2.7.
- compute_half_life accepts disjoint event cohorts: event A at1s=.4 and event B at5s=.2 yields PEAK_FOUND instead of INSUFFICIENT_COMPARABLE_EVIDENCE. Tests called matched use different event IDs at each delay.
- Production loading collapses the six terminal failure classes into FAILED and omits missing/pending reverse observations from its outcome list; cost coverage/gross/net distinctions from the arithmetic helper are lost downstream.
- A nonfinite denominator reaches <=0 before finite validation; Decimal('NaN') raises InvalidOperation instead of explicit unavailable. Valid 100/200/120 and known-cost arithmetic itself passes.

Correction:
- Retain exact entry/reverse source identity, mint/Q matching, target AND actual timings, class, notional, horizon, gross/net/cost coverage, individual failure classifications and pending/unavailable reasons through persistence/reporting.
- Compute first_seen-relative evaluation times from actual evidence. Entry at +5s and a 5m holding exit at +305s is a retained +305s observation; absent a genuine +300s observation, the exact first_seen+5m cell is unavailable. It is not evidence at +5s either. Do not interpolate/relabel or reuse the first position's reverse quote for another entry quantity.
- Partition comparable curves by the existing M2/M3 dimensions and same event cohort; compute observed crossings using actual delay, preserving nominal labels separately. Unmatched descriptive curves may exist but cannot support half-life or comparable latency. Preserve missing target cells/reasons.
- Validate finite/positive/matching inputs before arithmetic; preserve the already correct Decimal and cost-once behavior.
- Correct contradictory Phase 5 fixtures to the ORIGINAL expectations and complete the original P5-02/03/04 cases. Do not weaken or modify old Phase 4 tests.

### F5-03 — Measured component wiring and event coverage are incomplete

Classification: SPEC_BLOCKING.
Frozen IDs: P5-06, with P5-02/P5-07 secondary-aggregate requirements; mechanic M5.
Location: compute_wallet_copyability in service.py and its production inputs.

Observed:
- Starting from ShadowPosition drops entry failures, which have no position; missing reverse outcomes are also dropped. coverage_denominator is the remaining observation length, not all eligible terminal entry-event opportunities.
- n is list length and k includes token IDs from failed observations, rather than the distinct events/tokens with usable primary outcomes.
- Stability uses only the primary 5m outcome sign instead of the per-event fraction across the listed observed horizons.
- Holding-duration pair counts are hardcoded zero, price impact None, history completeness UNKNOWN. Supplying available same-event 5m and 30m evidence still yields unavailable holding suitability. Current M5 confidence therefore never reflects available history evidence correctly.
- Latency declares any two nominal points comparable; it inherits F5-02's cohort defect. Long-horizon evidence affecting output is missing from the contributing manifest.

Failed pass condition: the actual loader/service must supply the frozen component definitions, denominator and measured/missing confidence facts, not merely expose a correct pure formula behind placeholder inputs.

Correction:
- Construct the primary opportunity population from eligible terminal events/entry outcomes, retaining entry failures and missing reverses in coverage and terminal reverse failures in executability. Deduplicate by actual event identity before n, k and other aggregates; k comes from usable primary events only.
- Wire all evidenced horizons into per-event stability and comparable same-event 5m/30m holding pairs. Read actual point-in-time history completeness. Normalize explicitly evidenced impact units once; unknown unit stays unavailable, not guessed. M3 comparable evidence drives latency.
- Preserve denominator, c, availability/available_weight, component values/prior contributions and all contributing source IDs in snapshots/report. Include every output-contributing horizon in identity evidence.
- Keep existing frozen weights, robust math and neutral-prior/confidence formulas that already pass. Unknown genuinely absent data remains allowed; never hardcode unavailable for data the loader can establish.
- Execute P5-06's original boundary, unsuccessful-opportunity, six-probes-one-event and impact-unit cases through the production aggregation seam, not just manually supplied n/k values.

### F5-04 — Readiness is an unwired helper and does not enforce the frozen gates

Classification: SAFETY_OR_INTEGRITY_BLOCKING, FAIL_EXISTING_CRITERION.
Frozen ID: P5-08; related production-input/report clauses P5-01/P5-10; mechanic M6.
Locations: scoring/readiness.py, service.py and OpportunityReadinessSnapshot wiring.

Observed:
- compute_readiness has no production service/CLI caller. OpportunityReadinessSnapshot is not built/persisted by the actual report path.
- Six gate statuses are simply supplied by the caller; production evidence-based wallet tier/qualification/copyability/history/freshness/quote/risk evaluation and current-event exclusion are absent.
- Qualification150 is clamped to100 and eligible=true under supplied PASS gates. QualificationNaN raises InvalidOperation. This is the opposite of the frozen invalid/nonfinite case.
- Components are calculated before the gate decision. Tests toggle manually constructed PASS/FAIL/UNKNOWN values but do not exercise the required actual tier/85/75/90/default-risk boundaries.
- A numerical diagnostic80 may be calculated under an all-PASS synthetic fixture, but that does not authorize an actionable readiness80. The original contract preserves readiness>=90 and the other stated constraints.

Correction:
- Implement the production opportunity-readiness entry point using frozen qualification (not descriptive), eligible as-of copyability excluding the current event, actual current quote/price/size evidence and conservative independence. Missing later-phase risk/independence information is UNKNOWN, not fabricated PASS. No Phase 7/8/9 module or executor is requested.
- Evaluate all six gates and existing configured tier/confidence/risk constraints before eligible/actionable scoring; keep research diagnostic separately labeled. Validate known component inputs; do not silently clamp invalid pre-normalized score inputs or crash on nonfinite inputs. Formula-level clamping explicitly specified by M5/M6 remains valid.
- Enforce original A/S versus B/unknown, 84.999/85, 74.999/75 and 89.999/90 boundaries without changing values. FAIL/UNKNOWN remains ineligible with NULL actionable score, even with otherwise100 components.
- Persist/reuse per-opportunity analytical snapshots and emit gate evidence/reasons. Live permission/dispatch remains false regardless of research result.
- Supply every original P5-08 case, including actual lower-tier/history/stale/invalid-quote/zero-risk/unproven-independence/current-future input paths. This is an existing sealed safety row; no emergency or actual live incident is asserted.

### F5-05 — Snapshot identity and conflict recovery do not satisfy restart semantics

Classification: SPEC_BLOCKING.
Frozen ID: P5-09; M1/M7 lineage.
Locations: copyability/persistence.py, both new snapshot models, migration0022, service manifest construction.

Observed:
- Both unique constraints and both existing-row queries use subject/as_of/algorithm_version/evidence_manifest_digest but omit config_hash. The config hash stored as metadata cannot prevent reuse under changed config.
- The source manifest excludes long-horizon outcomes that change report values, so changed contributing evidence can reuse a stale snapshot.
- Both get_or_create functions catch IntegrityError, call session.rollback(), then execute in the same outer session.begin() used by the real CLI. A bound SQLAlchemy AsyncSession reproduces InvalidRequestError after this rollback within the outer context. The error handler is not safe merely because a unique constraint exists.
- The sole P5-09 integration test covers sequential wallet reuse and changed digest, not the original concurrent insert, rollback/retry, changed version and upgrade-with-completed-Phase4-row cases. The checkpoint incorrectly labels the concurrency concern HARDENING_BACKLOG despite P5-09 explicitly naming it.

Correction:
- Bind lookup AND unique identity to subject/as_of/algorithm/config and complete stable contributing evidence. Keep computed_at out of semantic identity; deterministic ordering/Decimal serialization and all output-contributing source IDs must be retained.
- Resolve duplicate insertion without rolling back/invalidating the caller's outer transaction: use PostgreSQL INSERT ... ON CONFLICT DO NOTHING against the complete unique identity, then select the winning row within the still-active caller transaction and return accurate created/reused status. Do not catch-and-continue on the same closed transaction or suppress unrelated integrity errors.
- Keep migrations additive and data-preserving. If schema correction is needed, append a new migration after0022; do not rewrite an already-published migration or delete old analytical/raw/Phase4 rows. Version newly computed semantics rather than overwriting prior snapshots.
- Implement original P5-09 session, concurrency, rollback/retry, changed-version and upgrade-from0021-with-completed-row tests, including scoped counts/snapshot values. E may defer execution, not the existence of runnable tests. The concurrency item is covered by this existing criterion, not a new carryforward.

### F5-06 — The real report omits required analyses and its integration fixture does not exercise them

Classification: SPEC_BLOCKING.
Frozen ID: P5-10; associated M1-M7 reporting.
Locations: cli.copyability_report, service.py, test_phase5_persistence_and_report.py.

Observed:
- The command emits wallet copyability only. Missing required fields include frozen qualification, evidenced/unavailable leader result, actual follower timings, executable versus mark/cost/status families, opportunity readiness/gate reasons, evidence-class/coverage breakdown and explicit limitations.
- The CLI test seeds only a wallet, not the specified persisted event/entry/reverse chain; no readiness snapshot is loaded. The empty-database test conditionally asserts only if exit_code==0, so any exception passes it.
- The synthetic demonstration calls isolated functions; it cannot establish missing production-loader/CLI wiring. Lack of a genuine-current database report itself is already allowed by E and is NOT an additional blocker.

Correction:
- Wire the repaired wallet/opportunity production calculations into the documented argus copyability report path, persisting/reusing both analytical snapshot families without providers or earlier-evidence writes.
- Emit every original P5-10 field, measured where supported, otherwise explicit null/unavailable with reason. Include separate selection/descriptive/class views and actual times; do not invent complete curves, positive returns or actual authentic samples.
- Implement the ORIGINAL seeded persisted event/entry/reverse -> real CLI -> parsed report -> reload snapshot test; run twice and assert stable source IDs/results/scoped counts. Keep empty and partial-wallet cases. Required assertions must run on a successful invocation; infrastructure-unavailable execution is reported as E, not a vacuous pass.
- Produce the actual-current-evidence report only if authorized infrastructure permits (zero/one wallet valid), plus the separately labeled deterministic synthetic demonstration. No new source or sample minimum.

### F5-07 — Enumerated proof obligations were not implemented, despite an all-row PASS claim

Classification: SPEC_BLOCKING under P5-13; the omitted secret/no-dispatch proof also fails the already-frozen P5-14 SAFETY_OR_INTEGRITY_BLOCKING row. This is NOT a newly discovered emergency.
Frozen IDs: P5-01 through P5-11 and P5-13/P5-14; regression obligation P5-12 remains subject to E.

Observed:
- The 14-row table cites green helpers or aggregate counts where the seal requires loader/call-site assertions. Concrete examples are given F5-01 through F5-06.
- P5-11's output-path helper change and six unit tests are valid, but existing replay integration tests still do not pass tmp_path and no required pre/post historical-artifact hash assertion wraps that suite.
- No new-analytics fake-credential-sentinel/captured-DEBUG test or raising provider/signing-dispatch sentinel test required by P5-14 is present. Static no-import inspection is a useful scope check, not that pre-specified proof.
- The checkpoint says all other subrequirements passed and concurrency is outside the contract. Those claims conflict with the actual original text. Validator syntax, seal digest and embedding themselves DO pass.

Correction and finite completion map:
- Expand the self-audit to EVERY exact case/assertion already enumerated in the reproduced seal, giving real node IDs and actual execution outcomes. Do not count a named test as proof when it omits the stated inputs/oracle. Environmental execution gaps remain explicit; do not call missing code/tests deferred environment.
- For P5-01/05/07: production temporal/frozen-state/current-event, prior-window/mint/dedup/current-buy, full secondary aggregate and class separation cases.
- For P5-02/03/04: actual nonfinite and quantity mismatch, preserved failure/mark disagreement, actual2.7 and same/mismatched cohort/notional/horizon, input permutation, and true first_seen timestamps with missing exact-horizon assertions.
- For P5-06/08: production event population, component wiring, impact-unit normalization, frozen confidence boundaries, and actual readiness gate/threshold/invalid/current-event cases.
- For P5-09/10: both snapshot semantics and all originally enumerated persistence cases; seeded real CLI/reload/counts; genuine-empty and partial data.
- For P5-11: preserve accepted output-path refusal/fresh-default behavior and old isolated-database guards; pass explicit tmp_path from replay tests and check unchanged historical tracked artifact hashes before/after replay suite as originally specified. Never overwrite then restore old evidence.
- For P5-14: run the new analytics command with relevant provider/signing dispatch replaced by raising sentinels; test inert fake credential fields through report/exception/log paths and assert omission from report and captured DEBUG text. Do not use real credentials, print environment values or dispatch a provider.
- For P5-12: rerun precisely the frozen regression/tool command inventory below; preserve all94 old matrix nodes and old passing checks.
- For P5-13: publish truthful complete case mapping and final validators/embedding in NEW artifacts. Correct previous claims by appending a new decision, not editing historical checkpoint/bundle/evidence. The existing seal/validator pass needs no new stronger oracle.

This completion map references the original finite obligations; it does not authorize the next audit to add another missing-proof requirement. Once these original obligations pass, approve Phase 5 and move newly noticed non-emergency issues forward.

## Accepted portions and row disposition

Keep already correct code where possible. No rewrite for style or extra architecture:
- P5-01 FAIL: production cutoffs/frozen inputs/lineage.
- P5-02 PARTIAL: valid exact return/cost helper and named pure failures pass; finite handling and retained production outcomes fail.
- P5-03 FAIL: actual timing/comparability missing; observed crossing arithmetic is usable once fed properly matched actual-time points.
- P5-04 FAIL: production relabeling; nine-cell shape, named cash baseline and Phase9 NULL marker pass.
- P5-05 PARTIAL: median/MAD/z/prior formula passes for supplied valid data; production baseline/current-size selection fails.
- P5-06 FAIL: existing config-bound pure formula/prior/confidence mathematics retained; production evidence/population wiring fails.
- P5-07 FAIL: persisted discovery token lookup for positions is useful, but sizes/full secondary aggregates/classes are not covered.
- P5-08 FAIL: diagnostic weighted helper/gate status representation retained; actual entry point/invalid-input/threshold enforcement absent.
- P5-09 FAIL: additive table creation/role restrictions and sequential-key concept retained; full identity/conflict handling and specified tests incomplete.
- P5-10 FAIL: basic empty-wallet command exists; full pipeline/fields/test absent. Genuine sample execution alone is E.
- P5-11 PARTIAL: fresh default/refusal/path validation PASS; exact replay test-output/hash proof remains incomplete.
- P5-12 PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION for inspected unchanged baseline/static/fixture checks; rerun original inventory after corrections.
- P5-13 PARTIAL: artifact format/digest/embedding/ancestry PASS; complete truthful case-level proof mapping fails.
- P5-14 PARTIAL: scoped diff/unchanged settings/handoff/trailers PASS; pre-specified sentinel tests absent.

No new NEXT_PHASE_CARRYFORWARD item was introduced in this bounded audit. CF-P4-01 remains mapped solely to original P5-11. Optional historical whitespace cleanup remains HARDENING_BACKLOG. Phase7 ancestry, Phase8 calibrated convergence and Phase9 matched controls remain out of scope. No new provider, live dataset, model tuning or empirical-alpha requirement.

## Implementation order, self-audit and stopping condition

1. Before editing code, enumerate every exact original sealed case and bind it to the real implementation seam/test oracle. The contract below is the fixed inventory; do not substitute a row name for the actual case.
2. Correct the shared production evidence representation/cutoffs/provenance/event population (F5-01), retaining identity/times/class/status facts needed by all consumers.
3. Correct quantity-matched outcomes, actual-time/cohort curves and forward grid (F5-02), then wire M5/size/history/impact aggregates (F5-03).
4. Complete evidence-based research readiness and config/evidence-bound append-only persistence (F5-04/05).
5. Wire the full real report and complete original integration/sentinel/replay proof (F5-06/07).
6. Run the same frozen case inventory yourself; fix every non-environmental failure before handoff. A high passing test count is not row completion. Tests knowingly contradicting original expectations must be corrected to the original contract, never used to reinterpret it.
7. Publish fresh evidence, verify final files/clean remote state, then STOP. No Phase6 work.

There is no additional ordinary remediation budget after this one. If a frozen failure remains at the next audit, policy section6 requires root-cause review and a newly sealed bounded safe recovery, automatically authorized unless genuine new human authority is needed. This is not permission for blind patch chains or new goalposts.

## Original sealed acceptance contract (verbatim)

The following section is copied byte-for-byte from the original immutable instruction. Its 25966-byte SHA256 stated above remains the authority. Administrative substitutions were explicitly limited above.

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

## Remediation handoff and artifact binding

Use NEW paths:
- orchestration/checkpoints/phase_5_remediation_1.md
- orchestration/bundles/phase_5_remediation_1.txt
- orchestration/phase_5_remediation_1/evidence/

Preserve original phase_5.md, phase_5.txt and orchestration/phase_5/evidence/ byte-for-byte. Record original instruction commit and seal digest plus this remediation's carrying commit and content identity. Update only build state/current handoff and append a decision-log entry reflecting this audit; Phase4 remains the last approved phase.

Final checkpoint: all original P5-01..P5-14 cases mapped to symbols/node IDs/commands/results/limitations, full source/report identities and actual count, changed paths, command output summaries, authority/carryforward state. Standard markers/sections; run validate_checkpoint_content and validate_bundle_content against FINAL hash-filled files and assert (True, '') and exact complete checkpoint inclusion. A genuine infrastructure inability may be E exactly as in the original seal; do not invent a successful execution, authentic sample or absent source.

Handoff: new unique HANDOFF_ID; CURRENT_PHASE 5; LAST_ORCHESTRATOR_INSTRUCTION_ID exactly argus-phase-5-remediation-001; run-local CURRENT_COMMIT and the new checkpoint/bundle paths; clean synchronized branch. Do not self-approve.

Every Claude implementation/evidence commit must end with the exact terminal line below and nothing after it:
ARGUS-INSTRUCTION-ID: argus-phase-5-remediation-001

Implement, self-audit the complete unchanged seal, commit/push and STOP for independent review. Do not poll or begin another phase.
