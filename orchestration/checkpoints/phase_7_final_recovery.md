================ ARGUS ORCHESTRATOR CHECKPOINT ================

RETROACTIVE_POST_BUILD_RECOVERY_CHECKPOINT — NOT A CONTEMPORANEOUS PHASE STOP

A. Identity

PROJECT: ARGUS
SCOPE: Phase 7 (ALPHA ANCESTRY), MASTER_SPEC.md section 55-56 region
(directional-edge / lead-follow graph). This document is NOT a
contemporaneous per-phase orchestrator STOP -- Phase 7 was originally
built, and is here corrected, under the human's explicit authorization
(recorded in `orchestration/AGENT_HANDOFF.md` / this session's own
history) for Claude to carry Phases 7-11 through to completion without
the normal per-phase orchestrator STOP/audit cycle. This checkpoint does
NOT claim that a contemporaneous STOP, independent audit, or approval
occurred for Phase 7 at build time. It exists solely to satisfy FSR-14
(`argus-final-spec-recovery-001`, instruction section F): a truthful,
retroactive record mapping Phase 7's original build requirements to the
CORRECTED implementation this recovery produced, the specific leak that
was repaired, and the actual tests run against the fix.
STATUS: RETROACTIVE_RECOVERY_RECORDED (not an orchestrator PASS/approval)
GIT_COMMIT (this checkpoint's own HEAD at authoring time):
50d96933b5ecde421300e96ce7694dfcc3b7ca62

Recovery authority: `argus-final-spec-recovery-001`
(`orchestration/ORCHESTRATOR_INSTRUCTIONS.md`), item FSR-05 (Phase 7's
own fix) plus the shared FSR-04 point-in-time invariant every later FSR
item reuses. `TARGET_COMMIT` audited as contaminated:
`ea77dd55b1e6be91b61b2f8b37e1d70449a3cb30`.

B. What Phase 7 originally built (unchanged by this recovery)

`src/argus/graph/` -- the directional-edge / lead-follow graph:
base-rate-corrected, multiple-comparison-corrected (q-value) leader ->
follower statistics per wallet pair, aggregated from real chain-observed
entries (`load_wallet_token_entries`), persisted to `directional_edges`
(migration `0025`). This structural build (the statistical estimator,
the persistence identity, the CLI `argus graph report` command) is
UNCHANGED by this recovery -- the defect FSR-05 fixed was narrower and
specific to one derived field.

C. The historical leak/omission this recovery repaired (FSR-05)

`directional_edges.forward_information_after_leader` (and its sample-
count columns) is the evidence for "does a leader's entry still carry
predictive information after other signals are known" -- MASTER_SPEC's
own required field. Before this recovery, this field's production loader
sourced its underlying per-follower forward return from other wallets'
generic token price movement rather than each FOLLOWER's own real Phase 5
executable-return evidence at the horizon actually being measured, and
did not exclude cases with no genuine executable evidence -- an honest
"evidence unavailable" case could be silently absent from the aggregate
rather than recorded as a disclosed missing reason.

D. The corrected implementation

- `src/argus/graph/loaders.py`: `load_forward_information_observations`
  (new/corrected) sources each qualifying follower's own real Phase 5
  reverse-executable quote (via `argus.copyability.loaders.
  load_wallet_opportunities`, the same production event population
  M2/M3/M5/every later phase reuses) at the SAME horizon label the
  directional edge's own forward-information field claims, matched by
  the follower's own `(token_id, first_seen_at)` -- never a generic
  token-price proxy.
- A follower observation with no matching Phase 5 opportunity, or one
  still `PENDING`/`UNAVAILABLE`, is excluded from the aggregate with an
  explicit missing-reason, never silently coerced into the sample or
  silently dropped without a record.
- `src/argus/graph/service.py`/`persistence.py`:
  `forward_information_sample_count`/`forward_information_eligible_count`
  (migration `0030`) persist the real observed-vs-eligible counts,
  satisfying MASTER_SPEC's own require-a-disclosed-denominator rule.
- Reuses the shared `argus.copyability.identity.known_by_cutoff`
  point-in-time pattern (FSR-04) throughout -- no follower's later
  knowledge leaks into an earlier leader-entry's own forward-information
  computation.

E. Actual tests run against the corrected implementation

- `tests/integration/test_phase7_graph_persistence_and_report.py::
  test_fsr05_forward_information_uses_followers_own_executable_return`
  and `::test_fsr05_forward_information_missing_reason_when_no_
  executable_evidence` -- both written this recovery, seeding a real
  FILLED `ShadowIntent`/`ShadowPosition` + `ShadowQuoteProbe` fixture
  (mirroring the exact Phase 5 evidence shape every later phase's own
  FSR fix reuses) and asserting the persisted
  `forward_information_after_leader` value matches the follower's real
  quote-derived return, never a token-price proxy; the missing-evidence
  case asserts an explicit excluded/missing reason, never a fabricated
  zero.
- Full repository unit suite (`uv run pytest tests/unit -q`): 1124
  passed, 0 failed, at this recovery's final commit (re-run after every
  later FSR item in this same recovery session, including FSR-13's
  version bumps -- Phase 7's own `ALGORITHM_VERSION` ("alpha_ancestry_v1")
  was intentionally NOT bumped by FSR-13, whose own text scopes the
  version/invalidation registry to "Phase 8-11" only; Phase 7's fix here
  is treated as a direct in-place correction, not a versioned/
  invalidated derived-run family).
- `uv run ruff format --check`, `uv run ruff check`, `uv run mypy src`:
  clean across the full repository at this recovery's final commit.
- Migration round-trip (`alembic upgrade head` / `downgrade -1` /
  `upgrade head`) verified against a fresh throwaway PostgreSQL 16
  database through migration `0036` (the final migration this recovery
  produced).

F. Environmental limitations (disclosed, not a builder failure)

This sandbox has a real, reachable local PostgreSQL 16 server (unlike
earlier phases' documented "no Postgres at all" environment) -- but NOT
PostgreSQL 17, the version `docker-compose.yml`/MASTER_SPEC's own
production target specifies (FSR-03's own subject, tracked separately).
No Docker daemon is available in this sandbox
(`docker compose up -d postgres` fails: "Cannot connect to the Docker
daemon"), so the PG17 container path itself could not be exercised; PG16
was used directly instead for all DB-backed validation in this recovery.
This session's shared long-lived development database
(`argus`) accumulated cross-test data pollution over the course of this
very long recovery session (many FSR items' own fixtures reusing the
same fixed anchor timestamp, `2025-06-01T12:00:00Z`, across hundreds of
test invocations) -- every DB-backed integration test in this recovery
was therefore independently re-validated against a FRESH, isolated,
migrated-to-head throwaway database (created and dropped per test) to
obtain a trustworthy pass, rather than relying on the shared `argus`
database's own polluted state. This is a disclosed sandbox/methodology
limitation, not evidence of a defect in the corrected code itself.

G. Changed/new files (Phase 7 portion of this recovery, FSR-05)

Modified: `src/argus/graph/loaders.py`, `src/argus/graph/service.py`,
`src/argus/graph/persistence.py`, `src/argus/domain/directional_edges.py`,
`src/argus/cli.py` (graph report section).
New: `migrations/versions/0030_fsr05_forward_information_evidence.py`
(exact filename as committed this recovery); the two FSR-05 tests named
in section E, added to the existing
`tests/integration/test_phase7_graph_persistence_and_report.py`.

Untouched (preserved byte-for-byte): all Phase 0-6 checkpoint/bundle
files under `orchestration/checkpoints/`/`orchestration/bundles/`;
`MASTER_SPEC.md`; `orchestration/AUDITOR_POLICY.md`;
`orchestration/PROTOCOL.md`; migrations `0001` through `0029` (never
rewritten -- this recovery is purely additive, migrations `0030` onward).

H. Acceptance statement

This document records that the Phase 7 forward-information leak (FSR-05)
was identified and repaired, with real corrected-implementation tests
passing against it, as part of the `argus-final-spec-recovery-001`
authorized recovery. It does NOT assert that a contemporaneous
orchestrator STOP/independent audit occurred for original Phase 7 or for
this recovery. Final acceptance of the full `argus-final-spec-recovery-
001` contract (all FSR-01 through FSR-16 items) is recorded separately,
per FSR-15/16, once every item in the contract is complete.

I. Next action

No STOP is issued by this document. This is historical-record-keeping
only, per FSR-14's own explicit instruction. Recovery work on the
remaining FSR-01..16 items continues per the human's standing "Begin"
authorization already recorded in this session.

================ END ARGUS CHECKPOINT =========================
