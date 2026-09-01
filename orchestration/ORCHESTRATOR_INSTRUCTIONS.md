# ARGUS Orchestrator Instructions

OWNER: ARGUS ORCHESTRATOR. The implementation agent must not modify this file.
Execute only the ACTIVE instruction below. MASTER_SPEC.md remains authoritative
except for explicit orchestrator decisions recorded here.

---

INSTRUCTION_ID: argus-phase-3-remediation-002
ISSUED_AT: 2026-09-01T06:29:00Z
TARGET_COMMIT: 3fb7d5675bf4b6c1c497dad08eb319a0e349d188
AUTHORIZED_ACTION: CLOSE_REMAINING_FROZEN_PHASE_3_DEFECTS_AND_MIGRATION_REGRESSION
AUTHORIZED_PHASE: 3
APPROVES_PHASE: NONE
STATUS: ACTIVE

## Disposition and approved state

AUDIT_ID: argus-phase-3-remediation-audit-001
DISPOSITION: FAIL_REMEDIATION_REQUIRED

Phase 3 is NOT approved. Phase 4 remains blocked.
This is ONE consolidated second remediation, justified below. Implement all
listed work in one batch, produce one fresh handoff, then STOP. Do not retune,
redesign accepted behavior, or expand into future phases.

Predecessor approvals remain unchanged:
- Phase 0: PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION.
- Phase 1: 2fbc566af74832bc6523648f60ba8cb60d98eb31,
  PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION.
- Phase 1.5: c3148cc191de58ecab9b11cd05291cc8ffe45455,
  PASS_WITH_LIMITATIONS.
- Phase 2: a13ba2ab8729a08de3c571b7b12c32cc3f14c56b,
  PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION.

The accepted PHASE_3_CANDIDATE_SAMPLE_BLOCKED outcome (one genuine candidate,
zero usable positions) remains accepted and is NOT a remediation item.
No additional candidate, provider purchase, or live validation is required to
close this remediation. Zero A/S wallets is a valid result.

## Audit identity, authority, and independent work

Repository akeldgord/Quant, branch claude/argus-folder-setup-77ahrk.
Audited remote HEAD: 3fb7d5675bf4b6c1c497dad08eb319a0e349d188.
Direct parent / implementation: 5713e9bd86011ae1033507fbdab349cc3dc5fdbd.
Pre-work instruction commit: da09d4f4d68d3120e865ffec5b5470d6b2ec86c0.
Audited instruction: argus-phase-3-remediation-001, targeting
69a8de622b1977f92999ca680fcb8d851ba78c9f.
Handoff: handoff-0021-phase-3-remediation, exact instruction-ID match.
Checkpoint: orchestration/checkpoints/phase_3_remediation.md.
Bundle: orchestration/bundles/phase_3_remediation.txt.

Frozen authority: MASTER_SPEC v2.0 as at original Phase 3 authorization,
plus argus-phase-3-001 and remediation-001's explicit existing-requirement
clarifications. MASTER_SPEC remains byte-identical to the Phase 2 approved
target: Git blob 34538249bd6d617777e36768f0fc2a27fdf554b6,
SHA-256 41f7242c288feec709b1ed72e62c74a1dc5e3b3cd9ad01e9b6e28373d9d14011.
PROTOCOL.md and orchestrator-owned instructions were not changed by the builder.
Both submitted commits are linear descendants of the instruction commit and
have the required sole terminal instruction trailer. Fresh evidence paths are
newly added. The hash-fill commit is permitted by PROTOCOL section 5.

The auditor fetched GitHub HEAD, read the canonical/control/evidence files,
cloned an isolated checkout and fetched the exact remote commit, inspected all
20 changed files and affected Phase 3 call sites, and independently executed:
- uv sync --frozen: PASS (offline cache attempt lacked typer; normal locked
  dependency installation succeeded).
- uv run pytest tests/unit/test_phase3_wallet_qualification.py -q:
  23 passed.
- uv run pytest tests/unit/test_orchestrator_watch.py -q: 79 passed.
- uv run pytest tests/unit tests/golden tests/replay tests/phase_1_5 -q:
  651 passed, 9 setup errors, no assertion failures. All nine errors are
  database-backed replay cases stopped by MissingCredentialError for the
  absent local database admin credential. They are NOT counted as passes.
- uv run ruff check .: PASS.
- uv run ruff format --check .: PASS, 212 files.
- uv run mypy: PASS, 110 source files.
- uv run argus fixtures validate-real-chain: all 12 PASS.
- Independent deterministic probes of forged completeness, exact same-slot
  ties, cross-quote round trips, missing/tied exit times, persistence precision,
  and migration operations: concrete results recorded below.
- Twelve independent boundary cases at 7/30/90/180 days, each at one second
  outside / exactly on / one second inside: PASS. Empty outcome stats: PASS.
- Actual production checkpoint and bundle validators: old phase_3.md rejected,
  remediation checkpoint accepted, exact embedded checkpoint accepted.

The auditor had no configured PostgreSQL service/credentials. No credential
was entered or requested and no live/provider call was made. Integration,
populated migrations and the full 738-test claim were NOT independently rerun.
This environmental limit is not itself a new phase blocker. The findings below
are demonstrated by executable offline probes and source, not missing access.

## Frozen requirement-to-evidence matrix

| Requirement | Observed implementation and proof | Disposition |
|---|---|---|
| P3-R1 knowledge-time queries | Service bounds swaps.first_seen_at, discovery.created_at, early_buyers.created_at, and both cluster times; inspected SQL predicates; existing cluster test | CLOSED for these predicates; retain them |
| P3-R1 malformed economic timestamps and reason | Reconstruction silently drops future block_time; history assessment still receives the unfiltered list; no persisted rejection reason | REMAINS OPEN, P3-R1 |
| P3-R2 evidence-derived completeness | CLI constructs AcquisitionManifest from arbitrary JSON; no producer/load verification; executable fabricated manifest returns HIGH | REMAINS OPEN, P3-R2 |
| P3-R3 independent round trips / current WAC | Full-close/reopen and partial-sell/rebuy tests pass; source state machine verified | CLOSED for these cases |
| P3-R3 mixed quote within one round trip | Conflicting leg retained in references and forces LOW; supplied test passes | CLOSED for this case |
| P3-R3 total deterministic ordering / quote-safe downstream math | Exact same-key permutations differ; two independent SOL/USDC trips sum 1 SOL + 1000 USDC as 1001 | REMAINS OPEN, P3-R3 |
| P3-R4 five windows | Five production inserts, closed membership by final_exit_at, independent 12-boundary and empty-stat probes pass; clean qualification token filter inspected | CLOSED; no new window gate |
| P3-R5 lottery denominator / usable-token counts | Net PnL, strict 70%, nonpositive null cases and closed outcome counts verified in passing tests | CLOSED for these cases |
| P3-R5 deterministic realization curve | Null exit mixed with aware time raises TypeError; same token/exit ties give drawdown 0.9 versus 0 when permuted | REMAINS OPEN, P3-R5 |
| P3-R6 cluster score / initial desired tier / missing forward confidence | Canonical adjusted result feeds both consumers; initial forced-DISCOVERED removed; missing forward component now caps confidence; tests/source verified | CLOSED for these cases |
| P3-R6 exact replay / full decision identity | Storage rounds non-terminating score before equality; history manifest absent from score key; latest-row-only matching and current tier mishandle historical replay | REMAINS OPEN, P3-R6 |
| P3-R6 immutable historical decisions | New 0011 upgrade deletes score, tier, metric and position history and resets current tiers | REGRESSION, P3-R6 |
| P3-R7 terminal checkpoint / exact bundle | Actual production validators accept new pair and reject old malformed file; old files unchanged | CLOSED |
| Required raw validation evidence | Bundle has raw Git/dependency/compose/Alembic output, but test/lint/type/fixture results are narrative claims, not their required raw command output | OPEN, E1 |
| Inherited firewall, weights, thresholds, transfer uncertainty, small samples | Passing Phase 3/unit/golden tests and changed-source inspection; unchanged Phase 2 production source | Remain accepted, subject only to listed integration fixes |
| Candidate sample and earlier environmental deferrals | Explicit honest unchanged limitations | Accepted; do not reopen |

No accepted Phase 2 finding is reopened. No unrelated future-phase concern is
part of this audit.

## Adversarial matrix and claim ledger

| Scenario | Independent method and result |
|---|---|
| Caller invents COMPLETE, enumerated=true, empty accounts, provider="invented", reference="does-not-exist" | TESTED_FAIL: assess_wallet_history returns HIGH without any acquisition |
| Exact same slot/type/mints/raw amounts, different immutable IDs and timestamps, reverse input order | TESTED_FAIL: different first/last entry and ordered references |
| Two closed round trips, first SOL and second USDC | TESTED_FAIL: production scoring input shape loses quote mint; compute_position_stats sums incompatible values |
| Closed exits mix None and UTC datetime | TESTED_FAIL: offset-naive/aware TypeError |
| Distinct trips with same token and exit timestamp | TESTED_FAIL: +100,-90,+100 produces max drawdown .9; -90,+100,+100 gives 0 |
| Unrounded score versus Numeric(6,3) representation | TESTED_FAIL: 35.10833333333333333333333333 stores as 35.108; _score_equal is false on identical replay |
| Changed acquisition manifest/history reason with same visible swap IDs and final numbers | INSPECTED_FAIL: no history reference/content participates in score digest/equality |
| T, later T, then exact T replay | INSPECTED_FAIL: only latest score is compared; tier uses current mutable wallet tier and can append a backdated reverse transition |
| Upgrade 0010 with existing decisions | TESTED_FAIL by executing upgrade against a recording op adapter: four DELETE statements plus current_tier reset |
| Five windows, exact cutoffs and empty outcomes | TESTED_PASS pure boundaries; INSPECTED production persistence; DB rerun unavailable |
| Checkpoint old/new/exact bundle | TESTED_PASS using actual validator |
| Same-time discovery firewall, weights, thresholds, transfers | TESTED_PASS existing deterministic tests |
| PostgreSQL replay/integration/migration end-to-end | BLOCKED in auditor environment; builder results unverified, not deemed failures merely for environment |
| Live, paid, signing, credentials | INSPECTED: no such new action; remain prohibited |
| Concurrency / future live readiness unrelated to this patch | NOT_APPLICABLE to additional gate; no new requirement |

Material builder claims:
- "All 7 fixed / all 9 acceptance categories pass": FALSE as a complete gate
  claim; successful narrow tests do not cover the remaining cases above.
- "Real structured manifest, never caller-typed claim": FALSE. Wrapping caller
  assertions in a frozen dataclass is not acquisition evidence.
- "Same-slot ties": UNSUPPORTED by the named supplied test, which uses slots
  1 and 2; the independent actual-tie probe fails.
- "Round trips / open WAC / within-trip mixed quote": CONFIRMED for the tested
  ordinary cases, not for total order or downstream currency aggregation.
- "All windows": CONFIRMED for production writes and closed-boundary rules.
- "Canonical score / replay / full identity": NARROWER_THAN_CLAIMED; ordinary
  cluster example works, storage and historical replay/identity remain wrong.
- "Immutable history": FALSE for the new migration. Disclosure does not waive
  the explicit prohibition on deleting prior score/tier decisions.
- "738 tests / migrations / lint / type checks": partly independently confirmed
  as above; DB totals remain UNSUPPORTED by raw committed test output. Do not
  infer dishonesty; provide the missing proof in fresh evidence.
- "Checkpoint marker/bundle fixed": CONFIRMED.
- "No deviations": FALSE: migration deletion contradicts remediation-001
  required task 6 and MASTER_SPEC section 36.
- "Sample blocked and deferrals unchanged": CONFIRMED and accepted.

## Seven-part no-moving-goalposts justification for round 2

Each row supplies all seven parts. These are continuations of concrete frozen
requirements or a directly introduced integrity regression, not new product
scope. A second round is necessary because passing the supplied tests leaves
these exact failures; it is not authorized merely to improve test depth.

| 1. Exact blocker | 2. Classification | 3. Frozen authority | 4. Concrete consequence | 5. Why prior remediation did not close it | 6. Why not backlog/environmental | 7. No backlog promotion / bounded closure |
|---|---|---|---|---|---|---|
| P3-R1 future economic input silently discarded after history assessment | SPEC_BLOCKING | remediation-001 task 1 and acceptance 1-2: same bounded evidence, record exclusion reason; CORE-001/004 | history range can extend beyond as_of; omitted events have no required decision reason | filter added only inside ledger; tests assert list unchanged, not persisted reason/history cutoff | explicit previously requested behavior missing from production | finish common filter and reason only; no new source checks |
| P3-R2 caller-authored manifest still promotes HIGH | SAFETY_OR_INTEGRITY_BLOCKING | remediation-001 task 2: execute typed acquisition or load its immutable produced run; MASTER_SPEC 34 | fabricated completeness can justify eligibility | same status strings moved into JSON/dataclass; no trusted acquisition producer or verified loader exists | demonstrably false current research confidence, not provenance depth | wire existing provider/acquisition and persisted results; no paid service or new standard |
| P3-R3 unstable exact ties and cross-trip currency aggregation | SAFETY_OR_INTEGRITY_BLOCKING | remediation-001 task 3: total immutable event tie-break; never add SOL and USDC; MASTER_SPEC 35 | order changes positions; incomparable cash PnLs alter risk/lottery scores | tie-break not added; newly separate trips lose quote unit in PositionForScoring | executable wrong current-phase accounting | complete ordering and unit propagation; no FX provider or alternate accounting |
| P3-R5 undefined exit times / repeated-token tied exits | SPEC_BLOCKING | remediation-001 task 5 and acceptance 6: final_exit order with stable immutable tie-break | ordinary permitted missing time crashes; permutation changes drawdown | new field uses naive datetime.min and token_id rather than unique round-trip identity | failed frozen deterministic metric, no external dependency | deterministic known order, honest unknown order; no metric retuning |
| P3-R6b lossy replay / missing history identity / historical replay | SPEC_BLOCKING | remediation-001 task 6 and acceptance 7: same stored/printed/tier score, full semantic equality, exact replay | duplicates, stale provenance, backdated tier changes | comparison expanded but storage scale, history input and non-latest replay omitted | code failure under identical inputs, not optional dedup | fix only position/score/tier identity; broad metrics dedup stays backlog |
| P3-R6a migration deletes prior decisions | SAFETY_OR_INTEGRITY_BLOCKING | remediation-001 task 6: preserve append-only history, do not update prior score/tier rows; MASTER_SPEC CORE-001/004 and 36 | irreversible loss of historical scores/transitions; recomputation cannot restore past beliefs | introduced for new NOT NULL columns; empty-DB migration tests miss loss | direct integrity regression from this implementation | preserve legacy rows honestly; no falsified reconstruction or prior-evidence rewrite |
| E1 missing raw command evidence | SPEC_BLOCKING | remediation-001 Required commands and evidence: exact raw results, no narrative-only claim | full integration/migration PASS is not independently checkable from bundle | normal bundle generator collects metadata but not the claimed test command streams | explicitly frozen deliverable, not a new test-count demand | capture existing required checks plus listed defect probes; no optional coverage target |

P3-R4 and the P3-R7 marker defect are CLOSED. The non-goals below remain
HARDENING_BACKLOG. No SHOULD/MAY is promoted to MUST.

## Session start and work order

1. git status --porcelain; git pull --ff-only; git log -5 --oneline.
2. Read in order MASTER_SPEC.md, docs/BUILD_STATE.md, docs/DECISION_LOG.md,
   orchestration/PROTOCOL.md, this file, orchestration/AGENT_HANDOFF.md,
   orchestration/checkpoints/phase_3_remediation.md, its bundle.
3. Verify fresh remote/local equality. This instruction must be introduced by
   exactly one instruction-only commit whose direct parent is TARGET_COMMIT.
   On mismatch, dirty overlap, self-approval, or unexpected branch movement STOP.
4. First remove the destructive migration path; then implement common input
   evidence/acquisition binding; then ledger/metric ordering and unit safety;
   then lossless decision identity/replay; then regression/evidence. Complete
   all tasks before a single new handoff. Never run the current destructive
   migration against a non-disposable database.

## Required implementation, with precise limits

### P3-R6a — preserve existing history across upgrades FIRST

Affected: migrations/versions/0011_phase3_remediation_point_in_time_and_ledger_integrity.py,
Phase 3 ORM models, new forward migration if needed, migration tests.

The current upgrade executes:
DELETE FROM wallet_tier_history
DELETE FROM wallet_score_snapshots
DELETE FROM wallet_metrics_snapshots
DELETE FROM wallet_positions
UPDATE wallets SET current_tier = NULL

Remove this data-loss path. Explicit narrow change-control authorization:
amend the UNAPPROVED 0011 migration code so new 0010->head upgrades preserve
every existing row and relationship. This is a code correction, not permission
to edit historical checkpoints, recorded decisions, approved migration 0010,
or raw evidence. Add a new forward migration for databases already stamped
0011 whenever the final schema requires it.

Keep old decision rows byte-for-byte in their existing economic/result/time/
identity fields. New provenance fields may be null for legacy rows; do not
invent a digest, round-trip identity, or "verified" manifest for legacy results.
Use existing algorithm version plus nullable new metadata to distinguish legacy
results; require real metadata for newly computed results in the production
write path. New recomputations append and never rewrite old scores/transitions.

Do not run a destructive downgrade to repair history. If 0011 already deleted
records in the builder's disposable dev database, disclose which environment/
tables were affected and whether a genuine pre-upgrade backup exists. Do not
claim recomputation restored original beliefs. Recovery of non-disposable
historical data requires explicit human authority; STOP that recovery action,
not the independent safe code/tests. No live database is authorized here.

Test a populated 0010 database with identifiable legacy position, score, metric,
tier transition and current-tier rows, upgrade to head, and assert all original
values/FKs/counts remain. Also test already-0011->head, fresh zero->head and a
safe repeat upgrade. Tests use disposable local data, never real credentials
entered for this task.

### P3-R1/P3-R2 — actual acquisition evidence and one bounded input manifest

Affected: history_reconstruction.py, qualification_service.py, cli.py,
existing historical_acquisition.py/ChainProvider integration and minimal
append-only schema.

Choose the existing typed-acquisition-in-process route from remediation-001,
then persist its actual result for replay. Do not accept an arbitrary JSON file
as authority for HIGH/MEDIUM history. Remove the current status-bearing file
promotion path (or treat files strictly as unverified input that cannot raise
completeness). The evidence_reference string alone is not verification.

Compose existing acquire_historical_transactions and
ChainProvider.get_token_accounts:
- Actual wallet-address walk, actual token-account enumeration, and actual
  walks for the returned account pubkeys. Store pubkey, owner and mint; mint
  alone is not an account identity.
- Record terminal statuses/gaps and known expected boundary where available,
  run/as_of identity, provider set, observation times, page/transaction evidence
  references and the exact raw/parser input set used for reconstruction.
- Preserve approved Phase 2 page/cost/failure semantics; do not introduce a new
  provider framework or a historical-account archival completeness requirement.
  Missing enumeration/coverage remains explicitly non-HIGH, as frozen.
- Persist a real immutable acquisition-run result/manifest with wallet binding.
  For subsequent scores, load by run ID from that persisted record and verify
  wallet, observation cutoff, coverage and evidence refs. Do not load statuses
  from an arbitrary caller file or accept bool("false") as enumeration.
- Feed acquired transactions through existing raw preservation/parser machinery,
  not merely use a successful walk to bless an unrelated swaps fragment.
- HIGH requires the actual complete wallet and covered account walks; any
  partial/failed account or enumeration error is explicit and non-HIGH.
  STREAM_FORWARD_ONLY stays LOW, no evidence stays UNKNOWN.

This authorizes software wiring and deterministic fake-provider tests only.
Existing live-capable adapters must retain fail-closed credentials and accounting;
do not invoke a live/paid provider or request credentials.

Apply as_of and future economic-time validation once before history assessment,
position reconstruction and scoring. Persist excluded swap IDs with a specific
reason (e.g. FUTURE_ECONOMIC_TIMESTAMP) in the input evidence manifest while
retaining raw rows. No rejected event may extend the usable history range.
Existing first_seen/created_at/cluster SQL predicates must remain.

Acceptance:
- Arbitrary JSON claiming COMPLETE + true + empty accounts + nonexistent ref
  cannot produce verified HIGH or an eligible promotion; string "false" is not
  accepted as true.
- Fake provider performs wallet pagination, token-account enumeration and each
  account walk; resulting persisted manifest binds the exact wallet/events.
  Complete, missing enumeration, partial account, failed fetch and genuine
  enumerated-empty outcomes have the frozen honest classifications.
- A run from another wallet or learned after T cannot justify history at T.
- Add the already-requested full production as-of matrix (future/late swaps,
  discovery, early-buyer and cluster evidence) and inspect history, exclusions,
  components, all windows, score and tier; T is unchanged by later evidence.
- A future-economic-time-only event is preserved as rejected evidence with its
  reason, not counted as usable history or given recency credit.
- Changed manifest/reason/provider/boundary creates the necessary new history
  snapshot and participates in score identity even when numeric score matches.

### P3-R3/P3-R5 — stable ledger identity and unit-safe deterministic metrics

Affected: position_reconstruction.py, PositionForScoring/service construction,
scoring.py, minimal provenance/schema fields.

Keep the working WAC, independent round trips and within-trip LOW handling.
Append immutable transaction/event identity as the final ledger sort tie-break.
Carry stable round-trip identity (not token_id alone) into scoring. Input
permutations of the same manifest must not change first/last times, contributing
refs, round-trip indices, economics or drawdown.

Preserve quote_asset_mint through the scoring boundary. Never add currency-valued
PnL/cost/gains/losses across SOL and USDC, including separate trips of the same
token or different tokens. No invented conversion or new FX provider:
keep currency-valued metrics per quote asset, and mark cross-currency aggregate
net-PnL/profit-factor/drawdown/lottery-contribution unavailable when no common
unit exists. Dimensionless per-position return/count statistics may still be
computed over usable positions. Use the existing missing-component neutral prior,
no weight redistribution or threshold change. Report mixed-unit unavailability;
never silently compute 1001 from 1 SOL plus 1000 USDC.

Known realization times sort by final_exit_at then immutable round-trip identity.
Unknown exit time is missing ordering evidence, not datetime.min disguised as an
actual realization time. Preserve the position and order-independent metrics;
mark the affected realization-ordered drawdown unavailable with a reason when
its chronology cannot be established. Do not crash, manufacture timing, or give
unknown-time positions invented bounded-window membership.

Acceptance:
- Same slot, classification, mints and equal raw amounts; two distinct immutable
  IDs with distinct observed economic times: all permutations byte-identical.
  The prior test with slots 1 and 2 does NOT test this.
- Independent closed trips +1 SOL and +1000 USDC never yield cash PnL 1001;
  include both same-token-reopened and different-token cases.
- Mixed None/UTC exit times do not raise TypeError; unavailable chronology is
  reported rather than fabricated.
- Distinct trips sharing token and final_exit_at have identical drawdown across
  permutations using their immutable identity; compare fixed hand-calculated
  order, not an expected result generated by the implementation.
- Existing +100/-90 net ratio, exactly .70/just above, nonpositive net, usable
  closed-token counts, Decimal WAC, uncertainty, contamination and all windows
  remain passing.

### P3-R6b — lossless canonical decisions, complete identity, historical replay

Affected: qualification_service.py, score/position snapshot models and migrations,
tier_lifecycle.py only as needed.

Preserve the working canonical cluster-adjusted result, score-derived first tier,
missing-forward confidence rule and fixed weights.

Scores are currently unrestricted Decimal calculations stored as Numeric(6,3).
Do not compare unrounded computed scores to silently rounded database values.
Use lossless NUMERIC storage for newly computed score Decimals (with corresponding
safe schema migration), so the value persisted, returned and tier-evaluated is
identical. Do not retune cutoffs or silently round across them. For position
snapshot comparisons, use a documented deterministic storage representation of
existing fixed-scale fields while preserving exact ledger computation and the
same input identity; repeated database round trips must not append duplicates.

Bind score identity to the acquisition/history manifest and its semantics
(reason, provider, boundary, coverage), as well as the existing bounded raw-input
manifest, as_of, score/algorithm version, all components/penalties/confidence/
exclusions/gate reason and build/config/spec/git identities. A changed history
reason or manifest with equal score is not the same decision.

Search for an existing full semantic decision, not just the latest row. Exact
replay of T after T+delta must reuse T's score and position snapshots and must
not create another tier transition or replace the current tier with an older
decision. Historical analysis may append a genuinely new historical score,
but must not overwrite a later current-tier state. A new later decision can
append its own immutable transition. Keep score/position/transition writes atomic
inside the service transaction; failures must roll back the run.

Acceptance:
- A score with >3 fractional decimal places is stored/returned/tier-used exactly;
  identical invocation writes no duplicate score/position/tier row.
- Exact T, T+delta (different tier), T replay preserves both prior decisions,
  original transition IDs/timestamps/counts and the later current tier.
- Changed components, penalties, exclusions, acquisition/history reason or
  manifest, as_of, score version, build/config/spec/git identity each yields
  the appropriate new score even with equal final numbers.
- Exact full-semantic replay is idempotent after a DB session restart.
- Existing eligible first invocation and cluster penalty cutoff tests remain.

### E1 — fresh complete evidence; do not reopen the fixed marker

Keep the old Phase 3 and remediation-001 checkpoints/bundles immutable.
Create only:
- orchestration/checkpoints/phase_3_remediation_2.md
- orchestration/bundles/phase_3_remediation_2.txt

Use the standard start/end markers; verify the actual production validators and
exact checkpoint bytes inside the new bundle. Include raw output AND exit status
for commands, not only prose PASS counts:
- uv run pytest tests/unit/test_phase3_wallet_qualification.py -q
- uv run pytest tests/unit/test_orchestrator_watch.py -q
- all new focused tests for this instruction
- uv run pytest tests/integration/test_phase3_wallet_qualification.py -q
- uv run pytest tests/integration/test_migrations.py -q
- uv run pytest tests/golden tests/replay tests/phase_1_5 -q
- uv run pytest tests/integration -q
- uv run pytest -q
- uv run ruff check .
- uv run ruff format --check .
- uv run mypy
- uv run alembic current
- populated 0010 preservation, already-0011 upgrade, zero->head and safe
  idempotent-upgrade migration tests
- uv run argus fixtures validate-real-chain
- existing changed-file secret scan, with secret values never emitted

No unexplained skip/xfail/retry; identify environmental inability honestly.
PostgreSQL 16 remains an allowed functional substitute, not PG17 validation.
Do not claim "upgrade-from-0010" using only a second upgrade of an empty head DB.

Include a row for every remaining finding and its exact test/output, all closed
items retained, run identity, database-history loss disclosure, approved
deferrals, preserved safety state and STOP. Update docs/BUILD_STATE.md, append
docs/DECISION_LOG.md, replace handoff with a fresh HANDOFF_ID. Do not apply Phase 3
approval. The new handoff must have exactly:

LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-3-remediation-002

Every builder commit, including hash-fill commits, must end with exactly one
real terminal Git trailer and no paragraph after it:

ARGUS-INSTRUCTION-ID: argus-phase-3-remediation-002

Push and verify clean worktree plus exact fresh remote/local equality; STOP.

## Accepted deferrals, non-goals, and prohibitions

LIVE_HELIUS_RPC_VALIDATION, LIVE_HELIUS_WSS_VALIDATION, PG17_COMPOSE_VALIDATION,
and BQ_PUBLIC_DATASET_ACCESS remain DEFERRED_ENVIRONMENTAL_CHECK. Their prior
closure procedures/owners remain unchanged; operator-supplied approved environments
are required before dependent live-readiness claims. This remediation must not
enter credentials or close them by assertion.

HARDENING_BACKLOG remains non-blocking: automatic cluster detection, canonical
pair-order DB enforcement, extra clustering/calibration, automatic rare tier
assignment, broader metric-snapshot dedup, and additional reporting polish.
Open-position descriptive/fingerprint refinements do not create a new blocker:
closed outcome counts and returns are already restricted correctly; do not
retune the scoring population for speculative improvements.

No Phase 4, mainnet trading, canary, signing/broadcast, private-key/seed access,
credential entry/disclosure, paid-provider use/upgrade, live arming, threshold
relaxation, prior-evidence rewrite, or phase skipping is authorized.
No historical data restoration may be fabricated. Do not modify this instruction.

Once these remaining frozen cases and regressions are proven, the orchestrator
should approve Phase 3 and authorize immediate Phase 4 in the same audit cycle,
subject only to MASTER_SPEC's explicit STOP/human gates. No further optional
hardening gate may be introduced.
