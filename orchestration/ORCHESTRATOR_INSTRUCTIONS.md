# ARGUS Orchestrator Instructions

OWNER: ARGUS ORCHESTRATOR. The implementation agent must not modify this file.
Execute only the ACTIVE instruction below. MASTER_SPEC.md remains authoritative
except where this instruction explicitly records an orchestrator approval,
clarification, or change-control decision.

---

INSTRUCTION_ID: argus-phase-3-remediation-001
ISSUED_AT: 2026-09-01T04:14:16Z
TARGET_COMMIT: 69a8de622b1977f92999ca680fcb8d851ba78c9f
AUTHORIZED_ACTION: REMEDIATE_ALL_FROZEN_PHASE_3_BLOCKERS_ONLY
AUTHORIZED_PHASE: 3
APPROVES_PHASE: NONE
STATUS: ACTIVE

## Independent audit disposition

Phase 0 remains approved as PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION.
Phase 1 remains approved at 2fbc566af74832bc6523648f60ba8cb60d98eb31 as
PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION.
Phase 1.5 remains approved at c3148cc191de58ecab9b11cd05291cc8ffe45455 as
PASS_WITH_LIMITATIONS.
Phase 2 remains approved at a13ba2ab8729a08de3c571b7b12c32cc3f14c56b as
PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION.

Phase 3 at exact audited remote commit
69a8de622b1977f92999ca680fcb8d851ba78c9f is NOT APPROVED.
Disposition: FAIL_REMEDIATION_REQUIRED.
Phase 4 and every later phase remain blocked.

This is the first and only consolidated Phase 3 remediation. It closes every
currently knowable blocking finding from the full frozen-gate audit. No optional
hardening item may be promoted into a blocker during this remediation.

## Audit identity and scope

- AUDIT_ID: argus-phase-3-audit-001
- AUDITED_BRANCH: claude/argus-folder-setup-77ahrk
- AUDITED_REMOTE_HEAD: 69a8de622b1977f92999ca680fcb8d851ba78c9f
- IMPLEMENTATION_COMMIT: f2e69423c1f93beb657ccc0bc415828ac2de046b
- EVIDENCE_HASH_FILL_COMMIT: 69a8de622b1977f92999ca680fcb8d851ba78c9f
- ACTIVE_INSTRUCTION_AUDITED: argus-phase-3-001
- FROZEN_PHASE_TARGET: a13ba2ab8729a08de3c571b7b12c32cc3f14c56b
- MASTER_SPEC: v2.0, Phase 3 and sections 34 through 43, plus CORE-001,
  CORE-004, sections 104 through 109, and section 116
- HANDOFF: handoff-0020-phase-3
- CHECKPOINT: orchestration/checkpoints/phase_3.md
- BUNDLE: orchestration/bundles/phase_3.txt
- AUDIT_ENVIRONMENT: immutable GitHub reads and source/test/evidence inspection.
  The auditor did not have the builder's local PostgreSQL service, so builder
  command results were checked against raw committed bundle output and test
  source but were not independently rerun.
- EXCLUDED_SCOPE: Phase 4 prospective monitoring/shadow copying, live execution,
  paid providers, canary, signing, threshold retuning, and deeper graph work.

The exact PHASE_3_CANDIDATE_SAMPLE_BLOCKED result is accepted. The committed
sample report honestly proves one genuine candidate and zero usable positions,
does not fabricate five wallets, does not loosen thresholds, and follows the
frozen fallback. It is not a remediation item.

The previously approved environmental deferrals remain unchanged:
LIVE_HELIUS_RPC_VALIDATION, LIVE_HELIUS_WSS_VALIDATION,
PG17_COMPOSE_VALIDATION, and BQ_PUBLIC_DATASET_ACCESS. They must remain
explicitly deferred and must not be reported as passed or as live readiness.

## Requirement-to-evidence disposition

| Frozen requirement | Independent result | Gate status |
|---|---|---|
| Structural discovery-contamination exclusion | Filtered qualification pass exists and direct unit/integration tests prove the ordinary same-time case | PASS, subject only to P3-R1 point-in-time repair |
| Descriptive and qualification scores differ | Independently visible in scoring code and tests | PASS |
| Weighted-average ledger and round-trip derivation | One token is collapsed into one lifetime row; current open basis and quote-unit separation are incorrect or absent | FAIL: P3-R3 |
| Transfer uncertainty | Transfer-only stays unresolved; mixed transfer evidence lowers confidence | PASS |
| Decimal/raw-unit accounting | Decimal arithmetic is used, but incomparable quote units can be summed | FAIL: P3-R3 |
| History completeness affects confidence/eligibility | LOW/UNKNOWN gate exists, but HIGH can be created from caller text and wallet-address-only history | FAIL: P3-R2 |
| Frozen score weights and separate penalties | Weights are exact; later service/tier handling is inconsistent and missing evidence does not lower confidence as claimed | FAIL: P3-R6 |
| Small samples constrained | 20-position/10-token/completeness gate and shrinkage exist | PASS |
| Lottery dominance and required metrics | Threshold comparison exists, but denominator, usable-token count, and drawdown order are wrong | FAIL: P3-R5 |
| Lifetime/180D/90D/30D/7D metrics | Schema accepts five windows; production service writes LIFETIME only | FAIL: P3-R4 |
| Point-in-time recency/no future leakage | Pure test changes as_of but never inserts future evidence; production queries are unbounded by as_of | FAIL: P3-R1 |
| Initial clustering | Pairwise evidence schema and conservative consumer exist; absence remains unknown | PASS to frozen minimum; automated link discovery is HARDENING_BACKLOG |
| Immutable timestamped tier lifecycle | Append-only table exists, but first-run/replay and adjusted-score consistency fail | FAIL: P3-R6 |
| Replay/idempotency | Narrow test passes; full semantic snapshot identity and eligible first-run tier replay fail | FAIL: P3-R6 |
| Five genuine wallets or exact blocked fallback | Exact blocked fallback with one genuine wallet and missing evidence is present | PASS_WITH_ALLOWED_ENVIRONMENTAL_LIMITATION |
| Checkpoint/bundle protocol | Bundle contains checkpoint bytes, but checkpoint has no required terminal END marker | FAIL: P3-R7 |
| Phase and safety boundaries | No Phase 4, trade, signer, credential, paid-provider, or live-arming work found | PASS |

## Adversarial coverage disposition

| Failure class | Independent result |
|---|---|
| Future swap, discovery event, early-buyer evidence, and cluster link | TESTED_FAIL by source trace: service selects all rows and scoring grants future timestamps full recency |
| Late-arriving historical event | TESTED_FAIL by source trace: no first_seen_at <= as_of knowledge boundary |
| Caller-forged acquisition completeness | TESTED_FAIL: CLI accepts free-text acquisition status and unit test supplies the claimed status directly |
| Associated-token-account omission | TESTED_FAIL: complete wallet-address pagination alone maps to HIGH |
| Full close then reopen same token | TESTED_FAIL by state-machine trace: one lifetime position is returned |
| Mixed SOL/USDC quote legs | TESTED_FAIL by state-machine trace: quantities are summed under the first quote mint |
| Partial sell then later buy while still open | TESTED_FAIL by arithmetic trace: persisted average uses lifetime buys, not current open inventory basis |
| Empty and populated recency windows | TESTED_FAIL: only LIFETIME is written |
| Net-PnL lottery dominance with offsetting losses | TESTED_FAIL: denominator is positive gains, not estimated lifetime P&L |
| Drawdown realization ordering | TESTED_FAIL: last_entry_at is used instead of final_exit_at |
| Cluster penalty crossing a tier cutoff | TESTED_FAIL: persisted score is adjusted, tier receives the unadjusted ScoringResult |
| Eligible wallet first invocation then exact replay | TESTED_FAIL: first invocation is forced to DISCOVERED; identical second invocation can create A/S |
| Same final score with changed components/exclusions/identity | TESTED_FAIL: score equality compares only two scores and eligibility |
| Missing forward-information evidence | TESTED_FAIL: it is explicitly excluded from the confidence-missing count |
| Checkpoint terminal marker | TESTED_FAIL: zero END-marker occurrences |
| Credential, signer, broadcast, paid/live side effects | INSPECTED PASS |
| Candidate scarcity | INSPECTED PASS: exact allowed blocked fallback |

## Claim-verification ledger

| Builder claim | Independent result |
|---|---|
| 721/721 tests, Ruff, format, mypy, migrations, fixtures, secret scan pass | Confirmed as committed raw bundle claims; not independently rerun in auditor environment |
| Discovery firewall is structural | Confirmed for same-time inputs; narrower than claimed because production as_of filtering is absent |
| History completeness derives from real acquisition status, not a claim | FALSE: the CLI accepts --acquisition-status and the test passes STATUS_COMPLETE directly |
| Weighted-average reconstruction and round-trip derivation are complete | FALSE for full-close/reopen, current open cost basis, and mixed quote assets |
| Point-in-time recency has no future leakage | FALSE: the test checks clock sensitivity only; future evidence is not excluded |
| All required recency windows are maintained where data exists | FALSE: production writes LIFETIME only, which the handoff also discloses |
| Tier lifecycle replay is idempotent | NARROWER_THAN_CLAIMED: the test uses an ineligible wallet; an eligible first run changes tier on identical replay |
| Missing prospective evidence lowers confidence | FALSE for forward_information because code excludes it from the missing count |
| Initial clustering is conservative | Confirmed for consumption of persisted links; automatic link detection is not required for this remediation |
| Candidate sample fallback is honest | Confirmed |
| Checkpoint follows the standard marker contract | FALSE: the required terminal marker is absent |
| No prohibited live/paid/credential action occurred | Confirmed by changed-source inspection and committed evidence |

## Frozen findings

### P3-R1 — point-in-time firewall is absent in the production service

Classification: SPEC_BLOCKING + SAFETY_OR_INTEGRITY_BLOCKING.
Severity: HIGH.

Governing requirements: CORE-001 point-in-time truth; Phase 3 discovery
firewall; argus-phase-3-001 required test 7; the frozen rule that earlier score
snapshots cannot use future observations.

Observed proof:
- reconstruct_and_score_wallet selects every Swap for the wallet with no
  Swap.first_seen_at <= now boundary.
- It selects every WalletDiscoveryEvent with no discovered_at/created_at <= now
  boundary.
- It selects every EarlyBuyer with no observed/created time boundary.
- It selects every WalletClusterLink with no as_of/created_at <= now boundary.
- score_wallet accepts every supplied position. compute_feature_fingerprint
  clamps a future last_entry_at to zero days old, awarding full recency.
- The submitted recency test only compares one already-known position at two
  later as_of values. It never adds or mutates future evidence.

Risk: an earlier score, component, sample count, exclusion set, cluster penalty,
or tier can be changed by evidence ARGUS had not observed at that time. That
materially falsifies research conclusions and violates the project's highest
data-integrity rule.

### P3-R2 — history completeness can be asserted by the caller and ignores token accounts

Classification: SPEC_BLOCKING + SAFETY_OR_INTEGRITY_BLOCKING.
Severity: HIGH.

Governing requirements: MASTER_SPEC section 34 and argus-phase-3-001 section 1:
do not assume getSignaturesForAddress(wallet) is complete; include associated
token-account evidence where available; missing history is explicit; HIGH must
rest on actual evidence.

Observed proof:
- The CLI accepts --evidence-source LIVE_ACQUISITION_WALK plus caller-provided
  --acquisition-status COMPLETE/PARTIAL/FAILED and --acquisition-known-gaps.
- assess_wallet_history maps caller-supplied COMPLETE directly to HIGH.
- No persisted acquisition result or event manifest is loaded and verified.
- No associated token-account enumeration/coverage state participates in HIGH.
- The test named derives_from_real_acquisition_status passes STATUS_COMPLETE as a
  function argument; it does not prove the status came from a real acquisition.

Risk: any existing swaps fragment can be labeled HIGH by typing COMPLETE, which
can unlock historical eligibility and A/S tiers with incomplete evidence.

### P3-R3 — the ledger does not implement correct round trips or quote-safe weighted average

Classification: SPEC_BLOCKING + SAFETY_OR_INTEGRITY_BLOCKING.
Severity: HIGH.

Governing requirements: MASTER_SPEC Phase 3 build items position ledger and
round-trip derivation; section 35 deterministic weighted-average inventory;
frozen acceptance for weighted-average ledger and exact Decimal/raw accounting.

Observed proof:
- reconstruct_positions_for_wallet emits one ReconstructedPosition per token,
  not one per completed/reopened round trip.
- A buy after a full close merely clears final_exit_at inside the same aggregate;
  earlier entry totals and realized PnL remain merged.
- quote_asset_mint is taken from the first leg, but later SOL and USDC legs are
  accumulated without conversion or an unresolved-state veto.
- average_cost_quote is total lifetime entry value divided by total lifetime
  buys. After a partial sale and later buy, that is not the weighted-average
  basis of the remaining open inventory.
- The submitted arithmetic test never closes and reopens, never mixes quote
  assets, and ends fully flat, so these paths are untested.

Risk: position count, distinct-token/sample evidence, cost basis, realized PnL,
holding period, and every downstream score can be materially wrong.

### P3-R4 — required recency-window metrics are schema-only

Classification: SPEC_BLOCKING.
Severity: MEDIUM.

Governing requirements: MASTER_SPEC section 41 and the frozen instruction:
maintain lifetime, 180-day, 90-day, 30-day, and 7-day metrics where data exists.

Observed proof: qualification_service imports WINDOW_LIFETIME and inserts
exactly one WalletMetricsSnapshot per run. It never computes or persists 180D,
90D, 30D, or 7D windows. The handoff discloses this as debt, but the obligation
was frozen before implementation.

Risk: the Phase 3 feature fingerprint and decay surface are incomplete, and
later comparisons can silently use lifetime metrics where a bounded window was
required.

### P3-R5 — lottery/sample/risk metrics use incorrect populations or ordering

Classification: SPEC_BLOCKING + SAFETY_OR_INTEGRITY_BLOCKING.
Severity: HIGH.

Governing requirements: MASTER_SPEC sections 39 through 41 and frozen lottery,
recency, and no-future-leakage tests.

Observed proof:
- largest_trade_contribution_pct divides the largest profitable position by
  total positive gains, not estimated lifetime net PnL as frozen.
- max drawdown is ordered by last_entry_at while the comment claims realization
  order; final_exit_at is not even present on PositionForScoring.
- distinct_tokens counts every position, including open positions without a
  usable closed outcome, despite the gate requiring distinct tokens with usable
  outcomes.

Risk: a lottery-driven wallet can avoid the required flag, drawdown can be
misordered, and unusable tokens can inflate eligibility evidence.

### P3-R6 — score, confidence, snapshot identity, and tier state disagree

Classification: SPEC_BLOCKING + SAFETY_OR_INTEGRITY_BLOCKING.
Severity: HIGH.

Governing requirements: MASTER_SPEC sections 36 through 39; CORE-004;
argus-phase-3-001 missing-evidence rule; required tier/replay tests.

Observed proof:
- The service subtracts cluster_uncertainty_penalty into a local
  qualification_score, but determine_tier_transition receives the original
  unadjusted ScoringResult.
- determine_tier_transition forces any first scoring run to DISCOVERED. An
  otherwise eligible wallet can therefore transition to A/S on an identical
  second invocation, violating replay determinism.
- missing_required explicitly excludes forward_information, so its known
  absence has no confidence effect despite the frozen rule.
- _score_equal compares only qualification_score, descriptive_score, and
  eligibility. Changed component values, penalties, confidence, exclusion IDs,
  sample reason, as_of, config/spec/git/build identity, or input references can
  reuse a stale snapshot.
- history-row equality similarly ignores history_completeness_reason.
- BUILD_HASH hashes only qualification_service.py, not the scoring artifact or
  full build identity.

Risk: the tier can be justified by a different score than the persisted one;
identical replay changes state; changed evidence can be hidden behind an old
snapshot; audit identity can be false.

### P3-R7 — submitted checkpoint violates the frozen evidence protocol

Classification: SPEC_BLOCKING.
Severity: MEDIUM.

Governing requirements: MASTER_SPEC section 104 and PROTOCOL.md section 5.

Observed proof: orchestration/checkpoints/phase_3.md begins with the required
ARGUS marker but contains zero occurrences of the required terminal line:
================ END ARGUS CHECKPOINT =========================
The bundle does contain the checkpoint bytes, so the defect is the missing
checkpoint terminator, not a bundle mismatch.

Risk: the submission does not satisfy the mechanically frozen phase-handoff
contract and indicates the claimed watcher verification did not enforce its own
documented check.

## Non-blocking findings frozen as HARDENING_BACKLOG

These must not block this remediation and must not be pulled into its tests:

- Automated discovery of new wallet-cluster links from raw chain evidence.
  Phase 3's minimum pairwise evidence schema and conservative consumer are
  accepted.
- Database enforcement of canonical wallet_a_id/wallet_b_id ordering.
- Automatic assignment of every rare lifecycle state such as RETIRED.
- Additional cluster signals, probabilistic calibration, or Phase 4 graph work.
- Broader metric-snapshot deduplication beyond the exact frozen
  position/score/tier replay requirements, unless touched directly to fix
  P3-R6.

## Mandatory session start and change control

Before changing code:

1. Run git status --porcelain, git pull --ff-only, and git log -5 --oneline.
2. Read in exact order: MASTER_SPEC.md, docs/BUILD_STATE.md,
   docs/DECISION_LOG.md, orchestration/PROTOCOL.md, this file,
   orchestration/AGENT_HANDOFF.md, orchestration/checkpoints/phase_3.md,
   orchestration/bundles/phase_3.txt, and
   orchestration/phase_3/SAMPLE_REPORT.md.
3. Verify the instruction-only commit containing this file has parent exactly
   TARGET_COMMIT, changes only this file, and local HEAD equals the freshly
   fetched remote branch HEAD.
4. Verify Phase 3 is awaiting review and is not marked orchestrator-approved.
   On any mismatch, fail closed and STOP.

## Required remediation

### 1. Enforce one knowledge-time cutoff across the complete scoring path

- Treat the service parameter now as the immutable score as_of.
- Query only swaps with Swap.first_seen_at <= as_of. A transaction whose chain
  time is earlier but first_seen_at is later remains unknown at that snapshot.
- Query only wallet discovery provenance observed by as_of, only early-buyer
  evidence created/observed by as_of, and only cluster links with both
  link.as_of <= as_of and link.created_at <= as_of.
- Position reconstruction, descriptive metrics, qualification metrics,
  contamination exclusions, recency windows, penalties, score snapshots, and
  tiers must all use that same bounded evidence manifest.
- Reject or exclude malformed future-dated economic timestamps rather than
  clamping them into full recency credit. Preserve the raw row and record the
  exclusion/reason.
- Persist an input-manifest digest and enough stable input references/counts to
  reproduce the score.

### 2. Make history completeness evidence-bound and token-account-aware

- Remove the ability for a caller to manufacture HIGH by passing free-text
  acquisition status. The ordinary CLI must either:
  a) execute the typed acquisition path and pass its actual result directly
  through the same process, or
  b) load a persisted, immutable acquisition-run record and manifest produced
  by that path.
- Persist/verify the wallet address walk, associated token-account enumeration,
  each included account-history walk, terminal statuses, known gaps, provider
  set, time range, and event references used for reconstruction.
- HIGH requires the wallet-address walk and all known associated token-account
  coverage to be complete through the stated boundary. Wallet-address-only
  COMPLETE is not HIGH. Missing enumeration or any unresolved account history
  must produce MEDIUM, LOW, or UNKNOWN with an exact reason.
- Link the history-quality snapshot to the verified acquisition run/manifest.
  STREAM_FORWARD_ONLY remains LOW and zero evidence remains UNKNOWN.
- A changed reason, provider set, boundary, coverage state, or manifest must
  append a new history-quality snapshot rather than silently reuse the old row.
- Tests use a deterministic fake provider/acquisition manifest. No credential,
  live call, or paid provider is authorized.

### 3. Implement round-trip-safe, quote-safe weighted-average inventory

- Emit a separate deterministic position/round-trip result whenever inventory
  reaches zero and later reopens. Add a stable round_trip_index or equivalent
  identity to the forward schema; do not rewrite migration 0010.
- Preserve every raw swap reference that fed each round trip, directly or via a
  stable input-manifest digest.
- Maintain open_quantity and open_cost_basis exactly with Decimal arithmetic.
  For an open round trip, average_cost_quote must equal
  open_cost_basis / open_quantity after partial exits and later buys.
  For a closed round trip, persist the deterministic entry-weighted average for
  that round trip and its final realized PnL.
- Never add SOL and USDC or any two incomparable quote units. If quote asset
  changes while inventory is open and no frozen conversion evidence exists,
  preserve the legs, mark the affected round trip UNRESOLVED/LOW as appropriate,
  and exclude it from qualification. Do not invent a conversion.
- Use a total stable event order with slot plus immutable transaction/event
  identity as the final tie-breaker. Input/query permutations must yield
  byte-identical results.
- Sample counts use closed HIGH/MEDIUM round trips. Distinct-token eligibility
  counts only tokens with at least one such usable closed outcome.

### 4. Materialize all five metric windows

- At each score as_of, compute and persist LIFETIME, 180D, 90D, 30D, and 7D
  WalletMetricsSnapshot rows from the same bounded, contamination-filtered
  evidence manifest.
- Use final_exit_at for closed-position outcome-window membership and the
  appropriate last-known activity time for open-position recency only.
- A window with no qualifying evidence must be explicit with zero counts and
  null metrics, never copied from LIFETIME.
- Do not use a later observation in an earlier window snapshot.
- Keep the frozen V1 weights and thresholds unchanged.

### 5. Correct lottery dominance, drawdown ordering, and usable-outcome counts

- For estimated lifetime net PnL > 0, compute largest-trade contribution as the
  largest positive closed-round-trip PnL divided by total net closed-round-trip
  PnL. If net lifetime PnL <= 0, contribution is null/not-applicable and cannot
  be described as a positive lifetime-profit contribution.
- LOTTERY_DOMINATED is true only when that defined ratio is strictly greater
  than 0.70. Preserve the flag/penalty rule; it is not an automatic rejection.
- Order the closed-trade equity curve by final_exit_at with a stable immutable
  tie-breaker, not last_entry_at.
- Count distinct usable tokens only from closed HIGH/MEDIUM-confidence
  round trips with a usable outcome.
- Keep Decimal arithmetic exact and document all null/zero boundary semantics.

### 6. Make one canonical adjusted score drive persistence and tiers

- Fold every applied penalty, including cluster uncertainty, into one final
  ScoringResult or equivalent immutable decision object before persistence and
  tier evaluation. The score stored, score printed, and score used for the tier
  must be byte-identical.
- Determine the desired tier from the current complete score on the first
  scoring invocation. Do not force an eligible wallet to DISCOVERED only
  because current_tier is null. Exact replay of identical inputs/as_of must not
  create a second transition.
- The known missing forward_information component must cap/lower confidence
  according to one documented V1 rule. It remains null and contributes the
  neutral prior without weight redistribution; it must not be excluded from the
  missing-evidence confidence count.
- Snapshot idempotency must compare or key the full semantic decision:
  as_of, input-manifest digest/references, score version, all components, all
  penalties, final/descriptive score, confidence, exclusions, eligibility,
  gate reason, algorithm/build/config/spec/git identity. Equal final numbers
  with changed evidence or identity are not the same snapshot.
- Preserve append-only history. Do not update prior score or tier rows.
- Include history reason/manifest in history-snapshot equality.
- Use a build identity that changes whenever any scoring/ledger artifact
  affecting the decision changes.

### 7. Repair the checkpoint protocol in fresh remediation evidence

- Do not overwrite orchestration/checkpoints/phase_3.md or its bundle.
- Create orchestration/checkpoints/phase_3_remediation.md beginning with:
  ================ ARGUS ORCHESTRATOR CHECKPOINT ================
  and ending with:
  ================ END ARGUS CHECKPOINT =========================
- Create orchestration/bundles/phase_3_remediation.txt containing the
  checkpoint bytes verbatim plus every PROTOCOL.md-required review item.
- Add a direct automated protocol regression test proving a missing terminal
  marker fails validation. If the existing watcher validator already has such a
  test, fix the production path that allowed this submission and prove the exact
  Phase 3 malformed checkpoint is rejected.
- Do not rewrite the historical malformed checkpoint; preserve it as evidence.

## Prospective acceptance tests

All tests below must fail the audited code for the named reason and pass only
after the remediation.

1. P3-R1 service as-of matrix:
   - Insert past and future swaps distinguished by first_seen_at, a late-arriving
     old-block-time swap, past/future discovery events, past/future early-buyer
     rows, and past/future cluster links.
   - Score at T and T+delta through the production service.
   - At T, every component, count, exclusion, penalty, window, score, and tier
     uses only evidence known by T. At T+delta the newly known evidence may
     appear. The T snapshot remains unchanged.

2. P3-R1 future-timestamp fail-closed:
   - Supply a position/economic timestamp later than as_of.
   - Assert it receives no recency credit and cannot enter qualification.
     Assert the raw evidence remains and the exclusion reason is recorded.

3. P3-R2 completeness provenance:
   - Prove the CLI cannot promote a wallet by typing COMPLETE.
   - A complete wallet-address walk with missing token-account enumeration is
     not HIGH.
   - A complete wallet walk plus complete enumeration and complete histories for
     every known associated token account may be HIGH.
   - One partial/failed account walk lowers completeness and records the exact
     gap.
   - The persisted history row references the immutable acquisition manifest.

4. P3-R3 round-trip matrix:
   - Buy, full close, reopen, full close yields two separately identified closed
     round trips with independently hand-calculated PnL and holding times.
   - Buy, partial sell, further buy while open yields the exact current
     open_quantity/open_cost_basis/average_cost.
   - Mixed SOL/USDC within one open inventory never sums units and is excluded
     as unresolved without losing raw legs.
   - Input permutations and same-slot ties produce byte-identical output.
   - Decimal boundary values prove no float conversion.

5. P3-R4 window matrix:
   - Hand-place closed round trips just inside/outside 7D, 30D, 90D, and 180D.
   - Assert five distinct persisted windows with exact counts/metrics.
   - A contaminated token is absent from every qualification window.
   - Empty windows contain zero counts/null metrics, not lifetime copies.
   - Re-scoring an earlier as_of after later evidence exists is byte-identical.

6. P3-R5 metrics:
   - PnLs +100 and -90 produce net lifetime PnL 10 and a ratio >0.70, so the
     lottery flag/penalty fires.
   - Exact 0.70 is not flagged; just above is flagged.
   - Net PnL <=0 has explicit null/not-applicable contribution semantics.
   - Drawdown follows final_exit_at order with a tie-breaker.
   - Open/unresolved positions do not inflate closed-position or distinct-token
     eligibility counts.

7. P3-R6 canonical score/tier:
   - A cluster penalty that crosses an A/S/B cutoff changes both persisted score
     and tier from the same adjusted value.
   - An eligible wallet's first score produces its score-derived tier; exact
     replay produces no new score or tier row.
   - Missing forward information prevents HIGH confidence under the documented
     V1 rule while remaining null and retaining its 15% neutral-prior weight.
   - Same final score but different components, penalties, exclusions, history
     reason, input manifest, as_of, or build/config/spec/git identity creates the
     required new immutable snapshot.
   - Exact identical full semantic input remains idempotent.

8. P3-R7 protocol:
   - The historical Phase 3 checkpoint without an END marker is rejected.
   - The fresh remediation checkpoint is accepted.
   - The fresh bundle contains its checkpoint bytes exactly.

9. Frozen regression:
   - Original contamination fixture still proves descriptive inclusion and
     qualification exclusion through components, counts, windows, penalties,
     confidence, and tier eligibility.
   - Transfer uncertainty, small-sample shrinkage, frozen weights, threshold
     values, migration history, Phase 0 through 2 semantics, golden fixtures,
     replay, and all safety prohibitions remain unchanged.

## Required commands and evidence

Run and record exact raw results for at least:

- uv run pytest tests/unit/test_phase3_wallet_qualification.py -q
- uv run pytest tests/integration/test_phase3_wallet_qualification.py -q
- the new focused remediation test modules
- uv run pytest tests/integration/test_migrations.py -q
- uv run pytest tests/golden tests/replay tests/phase_1_5 -q
- uv run pytest tests/integration -q
- uv run pytest -q
- uv run ruff check .
- uv run ruff format --check .
- uv run mypy
- uv run alembic current
- repository-standard zero-to-head, upgrade-from-0010, and
  downgrade/re-upgrade checks for every new forward migration
- uv run argus fixtures validate-real-chain
- changed-file secret scan

No unexplained skip, xfail, flaky retry, failed command, or narrative-only
claim is allowed. PostgreSQL 16 may remain the explicit functional substitute;
do not call it PostgreSQL 17.

Create fresh immutable evidence only:

- orchestration/checkpoints/phase_3_remediation.md
- orchestration/bundles/phase_3_remediation.txt

The checkpoint must contain:
- one row for P3-R1 through P3-R7 with exact code/test/evidence;
- the complete point-in-time, history-coverage, round-trip, window, metrics,
  score/tier, and protocol matrices;
- exact test counts, failures, skips, environment, migrations, and commands;
- the accepted PHASE_3_CANDIDATE_SAMPLE_BLOCKED result unchanged unless new
  authorized authentic evidence genuinely changes it;
- all environmental deferrals and prohibited live operations;
- an explicit STOP.

Update docs/BUILD_STATE.md, append docs/DECISION_LOG.md, and replace
orchestration/AGENT_HANDOFF.md. Do not mark Phase 3 orchestrator-approved.
Use a new HANDOFF_ID and exactly:

LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-3-remediation-001

Every implementation-agent commit must end with exactly one real terminal Git
trailer, with no paragraph after it:

ARGUS-INSTRUCTION-ID: argus-phase-3-remediation-001

Push, verify clean worktree and exact local/remote HEAD equality, then STOP.

## Frozen accepted areas and prohibitions

Do not redesign or retune the already-accepted structural contamination split,
frozen component weights, 20-position/10-token thresholds, transfer-uncertainty
rule, honest candidate-sample fallback, Phase 2 acquisition safety cases, or
approved provider architecture except for the minimal wiring required by these
findings.

This instruction does not authorize Phase 4, prospective shadow copying,
mainnet strategy trading, canary execution, signing/broadcast, signer/private
key/seed access, credential entry/disclosure, paid-provider upgrade/use, live
arming, threshold relaxation, evidence rewrite, or phase skip. Claude must not
modify this instruction file or self-authorize Phase 3 or any later phase.

Passing builder tests does not approve Phase 3. After the matching remediation
handoff, STOP for independent audit.