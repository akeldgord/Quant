# ARGUS Orchestrator Instructions

**OWNER: ARGUS ORCHESTRATOR.** The implementation agent must not modify this
file. Execute only the ACTIVE instruction below. MASTER_SPEC.md remains
authoritative except where this instruction explicitly records an orchestrator
approval, clarification, or change-control decision.

---

INSTRUCTION_ID: argus-phase-3-001
ISSUED_AT: 2026-09-01T03:04:00Z
TARGET_COMMIT: a13ba2ab8729a08de3c571b7b12c32cc3f14c56b
AUTHORIZED_ACTION: EXECUTE_PHASE_3_WALLET_RECONSTRUCTION_AND_UNBIASED_QUALIFICATION_ONLY
AUTHORIZED_PHASE: 3
APPROVES_PHASE: 2
STATUS: ACTIVE

## Independent audit disposition

Phase 0 remains approved as `PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`.
Phase 1 remains approved at `2fbc566af74832bc6523648f60ba8cb60d98eb31`
as `PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`.
Phase 1.5 remains approved at `c3148cc191de58ecab9b11cd05291cc8ffe45455`
as `PASS_WITH_LIMITATIONS`.

**Phase 2 is APPROVED at exact remote commit
`a13ba2ab8729a08de3c571b7b12c32cc3f14c56b` as
`PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`.**

The final focused re-audit verified the only remaining frozen P2-R2 defect:
`acquire_historical_transactions()` now accepts a typed
`expected_oldest_slot`, reports `PARTIAL` when a short/empty page arrives before
that boundary is reached, preserves already-acquired evidence, names the
unsatisfied boundary, reports `COMPLETE` when the boundary is actually
satisfied, preserves prior behavior when no boundary is supplied, and threads
the boundary through the ordinary CLI/service path. The four frozen
remediation-002 acceptance cases are present and the submitted regression
bundle reports 706/706 repository tests passing, 71/71 real-PostgreSQL-16
integration tests, 95/95 golden tests, 10/10 replay tests, 7/7 Phase-1.5 tests,
Ruff clean, Ruff format clean, mypy clean, and 12/12 real-chain fixtures valid.
The remediation run is exactly two linear, verified Claude commits on the
instruction commit and both use the exact terminal instruction trailer.

The following environmental checks remain deferred and must NOT be represented
as passed or as live readiness:

- `LIVE_HELIUS_RPC_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK`
- `LIVE_HELIUS_WSS_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK`
- `PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK`
- `BQ_PUBLIC_DATASET_ACCESS = DEFERRED_ENVIRONMENTAL_CHECK` where still applicable

These do not block Phase 3. They do block later claims that depend on those
specific live/environmental validations.

No Phase 2 finding is reopened by this instruction. P2-R1 through P2-R8 are
closed unless future work produces concrete regression evidence.

## Phase 3 frozen goal

Implement MASTER_SPEC Phase 3 exactly:

**WALLET RECONSTRUCTION + UNBIASED QUALIFICATION**

Goal: reconstruct candidate-wallet histories and score them without using the
discovery evidence that selected the wallet to justify its own qualification.

Build only the Phase 3 scope:

- wallet history reconstruction
- explicit history completeness
- deterministic position ledger
- round-trip derivation
- position confidence
- wallet metrics
- descriptive score
- qualification score
- discovery-evidence exclusion
- lottery-dominance handling
- recency decay
- initial clustering
- tier lifecycle

Do not begin Phase 4 prospective monitoring/shadow copying.

## Canonical Phase 3 semantics

### 1. Historical evidence and completeness

For every reconstructed wallet history, persist/derive the MASTER_SPEC section
34 fields or their canonical schema equivalents:

- `history_start`
- `history_end`
- `history_provider_set`
- `history_completeness`
- `history_completeness_reason`

Allowed completeness states are `HIGH`, `MEDIUM`, `LOW`, `UNKNOWN`.

Do not assume `getSignaturesForAddress(wallet)` alone is complete wallet
activity. Include associated token-account evidence where available through the
already-approved historical architecture. Missing or unrecoverable history is
explicit missing evidence, never zero activity. `LOW`/`UNKNOWN` completeness
must reduce qualification confidence and cannot silently be treated as full
history.

Use free/currently-authorized sources only. No paid provider is authorized.
Previously approved live-provider/environmental deferrals remain deferrals;
Phase 3 must function and be testable without converting them into fake PASSes.

### 2. Deterministic position reconstruction

Use MASTER_SPEC section 35 V1 weighted-average inventory accounting. Preserve
raw position events so alternative accounting remains recomputable.

Derive where evidence permits:

- first/last entry
- entry quantity/value
- weighted-average cost
- partial exits
- final exit
- realized and unrealized P&L
- holding duration
- MFE / MAE
- peak value
- peak-profit capture

Use exact raw-unit/Decimal arithmetic. Never use binary floating point for
financial quantities. Transfers with uncertain economic meaning remain
uncertain; do not magically classify them as purchases or sales.

Position confidence must use `HIGH`, `MEDIUM`, `LOW`, `UNRESOLVED` (or exact
canonical equivalents). Only HIGH/MEDIUM-confidence positions may materially
contribute to qualification metrics.

### 3. Discovery contamination firewall — highest-priority invariant

The critical MASTER_SPEC test is mandatory and phase-blocking:

- `TOKEN_A` discovers wallet `W`.
- `TOKEN_A` is a huge winner.
- `TOKEN_A` MAY affect W's descriptive score.
- `TOKEN_A` MUST NOT affect W's qualification score, qualification component
  metrics, tier eligibility, or confidence evidence used to justify selection.

This exclusion must be based on persisted discovery provenance, not fixture
names or a hand-maintained token list. Exclude every observation whose token or
event is discovery-contaminating for that wallet according to point-in-time
provenance. Preserve the excluded observations and report them; never delete raw
evidence to make the score clean.

Add direct automated assertions proving the contamination cannot leak through
secondary aggregates such as lifetime P&L, hit rate, recency windows, sample
count, largest-trade contribution, or tier gates.

### 4. Wallet feature fingerprint and scoring

Implement the Phase-3-relevant parts of MASTER_SPEC sections 37-41.

Persist independent components rather than only one opaque score. At minimum:

- selection skill
- early-discovery / entry timing where evidence supports it
- exit skill
- risk control / risk-adjusted behavior
- consistency
- forward-information component if it can be computed without Phase 4 future
  data; otherwise persist explicit missing/not-yet-prospective status rather
  than fabricate it
- recency
- data confidence
- insider/cluster/predation or related penalties where Phase 3 evidence supports
  them

Qualification score v1 uses the frozen weights in MASTER_SPEC section 38:

- selection alpha: 25%
- consistency: 15%
- entry timing: 15%
- forward information: 15%
- risk-adjusted return: 10%
- exit capture: 10%
- recency: 5%
- data confidence: 5%

Apply penalties separately. Do not optimize/retune these weights in Phase 3.
If a required component is unavailable because prospective evidence does not
yet exist, handle it with an explicit versioned missing-evidence rule that does
not fabricate positive evidence and document the resulting confidence effect.
Do not silently redistribute its weight to make scores look better.

Store score version, component values, penalties, final score, confidence, and
excluded discovery observations with reproducible algorithm/config/git identity.

### 5. Sample-size constraints

A wallet may not become `A` or `S` on a tiny sample.

Frozen V1 historical eligibility target:

- at least 20 usable closed positions
- at least 10 distinct tokens with usable outcomes
- history completeness not `LOW`/`UNKNOWN`
- discovery-contaminating observations excluded

Treat these as evidence gates, not proof of alpha. Small samples must be
confidence-shrunk toward the population prior or otherwise deterministically
constrained so they cannot receive unjustified elite qualification.

Do not loosen thresholds because real candidates are sparse.

### 6. Lottery dominance and recency

Compute the section-40 metrics where evidence permits:

- median return
- trimmed mean return
- winsorized return
- profit factor
- hit rate
- largest-trade contribution
- top-three-trade contribution
- max drawdown
- distinct profitable-token count

Flag `LOTTERY_DOMINATED` when the largest position contributes more than 70% of
estimated lifetime P&L. In V1 this is a penalty/flag, not automatic rejection.

Maintain lifetime, 180-day, 90-day, 30-day, and 7-day metrics where data exists.
Use a versioned deterministic recency-decay rule. Historical observations remain
immutable.

### 7. Initial clustering and tier lifecycle

Implement only the initial Phase 3 clustering necessary for qualification and
confidence. Evidence may include common funding, direct transfers, same initial
funder, synchronized activity, repeated sizing/token sequences, shared deployer
relations, shared cash-out destinations, and strong temporal co-occurrence.

Estimate common-control/independence evidence conservatively; do not claim
real-world identity. Absence of a cluster link is not proof of independence.
Keep cluster conclusions temporal/versioned where persisted.

Support wallet lifecycle states defined by MASTER_SPEC section 36:
`DISCOVERED`, `WATCH`, `PROBATION`, `B`, `A`, `S`, `QUARANTINE`, `DORMANT`,
`RETIRED`. Every transition is timestamped and immutable. Phase 3 must not make
A/S equivalent to live authorization; later live gates still apply.

## Required Phase 3 tests

Implement high-value tests sufficient to prove the frozen gate without test
inflation. At minimum:

1. **Discovery contamination fixture:** TOKEN_A discovers W and is a huge winner;
   descriptive includes it, qualification excludes it. Assert no leakage through
   component metrics, sample counts, recency aggregates, or tier gates.
2. **Weighted-average ledger:** buys, partial sell, further buy, final sell with
   exact raw-unit/Decimal expected cost basis and realized P&L.
3. **Transfer uncertainty:** unresolved transfer does not become a fabricated
   buy/sell and appropriately lowers position/history confidence.
4. **Completeness-confidence coupling:** identical economic observations under
   HIGH versus LOW/UNKNOWN history completeness produce the correct confidence/
   eligibility difference; LOW/UNKNOWN cannot qualify A/S.
5. **Small-sample constraint:** superficially excellent tiny sample cannot become
   A/S and shows deterministic shrinkage/constraint reason.
6. **Lottery dominance:** >70% largest-position contribution produces the
   required flag/penalty; boundary behavior is deterministic.
7. **Recency/versioning:** windows/decay use point-in-time timestamps and do not
   leak future observations into an earlier score snapshot.
8. **Tier lifecycle:** transitions are immutable/timestamped and replay is
   idempotent; later score changes do not rewrite earlier tier state.
9. **Restart/replay:** repeated reconstruction/scoring from identical evidence
   yields the same canonical outputs without duplicate position/score/tier rows.
10. **Regression:** all previously approved Phase 0-2 semantic/golden/replay
    tests remain passing. Any failure in an approved invariant is blocking
    regression evidence, not an invitation to rewrite the old gate.

Do not manufacture dozens of superficial tests. Cover the financial/data
invariants deeply.

## Required Phase 3 sample report

Produce a report for at least five genuine candidate wallets if five can be
established from already-authorized authentic evidence. For each report:

- usable trades/positions
- history completeness and reason
- discovery-trigger token(s)
- excluded observations
- descriptive score
- qualification score
- selection skill
- entry skill
- exit skill
- consistency
- risk metrics
- penalties/flags
- resulting tier and confidence

Do not fabricate wallet history to satisfy the five-wallet report. Synthetic
fixtures are valid for deterministic tests but do not count as the five genuine
sample wallets. If fewer than five genuine candidates can be established with
the currently authorized free evidence paths, output exactly
`PHASE_3_CANDIDATE_SAMPLE_BLOCKED` in the checkpoint, report the actual count and
missing evidence, and STOP for orchestrator review rather than inventing data or
using a paid source.

A poor score, low completeness, or zero A/S wallets is a valid Phase 3 result.
Do not retune the score or eligibility rules to force attractive candidates.

## Persistence and architecture rules

- Extend the existing modular monolith and PostgreSQL/Alembic architecture.
- Add forward migrations only; do not rewrite accepted migration history.
- Raw observations stay append-only.
- Derived score/position artifacts must be versioned/reproducible and should use
  stable idempotency identities.
- Preserve observation time versus chain time.
- Record algorithm version, config/hash, git commit, timestamp, input references,
  reason codes, and result for meaningful decisions.
- If a significant migration is required after Phase 3, MASTER_SPEC section 97
  requires a backup/equivalent migration-safe snapshot before that later
  migration; do not prematurely turn that later requirement into a Phase 3
  acceptance blocker.
- Do not add a neural network, LLM runtime decision loop, new message broker,
  microservice, paid-data dependency, or Phase 4 worker.

## Phase 3 acceptance — frozen now

Audit Phase 3 later against exactly these MASTER_SPEC acceptance items and the
clarifications above:

- `[P/F] discovery contamination excluded`
- `[P/F] descriptive/qualification scores differ where expected`
- `[P/F] weighted-average ledger correct`
- `[P/F] transfer uncertainty handled`
- `[P/F] Decimal/raw-unit accounting correct`
- `[P/F] history completeness affects confidence`
- `[P/F] tier transitions timestamped`
- `[P/F] small samples shrunk/constrained`

The five-wallet sample report and the critical contamination fixture are also
explicit MASTER_SPEC Phase 3 requirements and are part of the gate.

No future audit may turn optional hardening, Phase 4 behavior, live execution,
or deeper-than-required clustering into a Phase 3 blocker unless concrete
current safety/integrity evidence makes it necessary.

## Quality / evidence requirements

Run and report exact commands/counts for:

- focused Phase 3 unit tests
- Phase 3 database/integration tests on the available PostgreSQL substitute
- migration zero-to-head and repository-standard downgrade/re-upgrade checks if
  Phase 3 adds migrations
- all golden/replay tests
- full repository suite
- Ruff lint and format check
- mypy
- real-chain fixture validation
- secret scan over changed files

Previously approved environmental deferrals stay explicit. Do not call PG16
PG17 validation and do not claim live Helius validation without credentials and
a real reachable provider.

Create fresh immutable evidence:

- `orchestration/checkpoints/phase_3.md`
- `orchestration/bundles/phase_3.txt`

Update `docs/BUILD_STATE.md`, append `docs/DECISION_LOG.md`, and replace
`orchestration/AGENT_HANDOFF.md` with the matching handoff.

The implementation agent may mark Phase 3 implementation complete/awaiting
review, but `last_orchestrator_approved_phase` must become `2` (this instruction
approves Phase 2) and must NOT become `3` until a later orchestrator approval.
`approved_commit` should record this Phase 2 approval target
`a13ba2ab8729a08de3c571b7b12c32cc3f14c56b`.

Use a new handoff ID and exactly:

`LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-3-001`

Every implementation-agent commit must end with exactly one real terminal Git
trailer, with no paragraph after it:

`ARGUS-INSTRUCTION-ID: argus-phase-3-001`

Push, verify clean worktree and exact local/remote HEAD equality, then STOP.
Do not begin Phase 4.

## Prohibitions preserved

This instruction does not authorize Phase 4, prospective shadow copying,
mainnet strategy trading, canary execution, signing/broadcast, signer/private-
key/seed access, credential entry/disclosure, paid-provider upgrade/use, live
arming, threshold relaxation, evidence rewrite, or phase skip. Claude must not
modify this instruction file or self-authorize Phase 3 or any later phase.
