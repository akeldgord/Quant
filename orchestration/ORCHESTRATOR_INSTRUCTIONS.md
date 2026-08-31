# ARGUS Orchestrator Instructions

**OWNER: ARGUS ORCHESTRATOR.** The implementation agent must not modify this
file. Execute only the ACTIVE instruction below. MASTER_SPEC.md remains
authoritative except where this instruction explicitly adds stricter
acceptance detail.

---

INSTRUCTION_ID: argus-phase-1-remediation-003
ISSUED_AT: 2026-08-31T10:20:25Z
TARGET_COMMIT: 87a0e2efe329512a78f81331da24a85adf62bbbe
AUTHORIZED_ACTION: REMEDIATE_PHASE_1_ROUND_3_ONLY
AUTHORIZED_PHASE: 1
APPROVES_PHASE: NONE
STATUS: ACTIVE

## Independent audit disposition

- Phase 0 remains approved as
  `PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`.
- `PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK` remains open
  and blocks live readiness, not this remediation.
- Phase 1 remediation round 2 is **not approved**. Its checkpoint honestly
  reports `STATUS: PARTIAL`, and independent source review found additional
  acceptance gaps below.
- Phase 1 remains unapproved. Phase 1.5 and every later phase remain forbidden.
- This instruction approves no phase and authorizes only the listed Phase 1
  remediation.
- No live trade, mainnet canary, signing, private-key or seed access,
  credential disclosure or entry, paid-provider upgrade, live arming,
  threshold relaxation, or phase skip is authorized.

## Mandatory session start

Before changing code:

1. Run `git status --porcelain`, `git pull --ff-only`, and
   `git log -5 --oneline`.
2. Read the six canonical files in the exact PROTOCOL.md order.
3. Verify the checked-out instruction commit is exactly one
   instruction-file-only commit whose parent is the exact TARGET_COMMIT above.
4. Verify the worktree is clean and local HEAD equals the remote branch.
5. Verify BUILD_STATE still has `current_phase: 1`,
   `last_orchestrator_approved_phase: 0`, and
   `awaiting_orchestrator_review: true`.
6. If any precondition is false, stop with an honest PARTIAL/FAIL handoff.

## Audit findings that must be remediated

### 1. Required authenticated real-chain parser fixtures remain incomplete

The submitted checkpoint is correctly `PARTIAL`: only the simple-transfer
category is supported by authenticated real-chain bytes. The remaining
required categories are NOT TESTED:

- SOL to token swap;
- token to SOL swap;
- token to USDC swap;
- multi-hop swap;
- partial sell;
- multiple token-account / LP-style action;
- ambiguous multi-asset transaction;
- failed transaction.

The prior search did not inspect the most relevant DEX/AMM and indexer
repositories. Search public, license-compatible repositories including
Jupiter, Raydium, Orca/Whirlpools, Meteora, Phoenix/OpenBook, established
Solana indexers/parsers, and their tests/examples. A fixture is acceptable
only if immutable upstream evidence supports that its bytes are an authentic
captured chain response. Repository naming, payload shape, or a plausible
signature alone is not authentication.

For every category, preserve and validate the provenance fields required by
the previous instruction: chain, signature, slot, transaction version,
upstream repository, immutable commit SHA, exact path, license, original
bytes/hash, transformation, sanitized hash, parser input fields, and expected
canonical output. Verify the upstream blob at the pinned commit and record its
blob/hash. Do not invent, reconstruct, or relabel synthetic data as real.

If a category still cannot be authenticated from available evidence, leave it
NOT TESTED and return PARTIAL. Do not approve Phase 1 by weakening or waiving
this gate.

### 2. Pagination still accepts an unverified persisted boundary

`ReconciliationEngine._fetch_all_pages()` treats an empty or short page as
proof that a persisted `boundary_signature` was reached. It never observes
that signature. A provider can return an empty/short page because history is
pruned, incomplete, or faulty, and the code reports success. This does not
satisfy round-2 criterion 17 or the explicit requirement that a persisted
boundary be verified as reachable/continuous.

Implement an evidence-bearing boundary algorithm. When a persisted boundary
exists, success requires observing and matching that exact boundary in the
provider's address-history sequence (for example, page with `before` only
until the boundary itself appears, then exclude it from new work), or an
equivalent independent check that proves both address membership and
continuity. Merely passing `until` and receiving fewer than `limit` items
is insufficient.

Requirements:

- an empty/short page before the exact boundary is observed must fail DEGRADED
  with an explicit missing/pruned-boundary reason;
- the initial bootstrap case with no boundary must be handled separately;
- no event, parse result, or watermark may advance after an unverified gap;
- page ordering, cross-page uniqueness, cursor non-repetition, exact-boundary
  handling, and safety ceilings remain deterministic;
- same-slot entries must not be given a fabricated total order;
- recovery/backfill after a ceiling or missing boundary must be explicit and
  operator-visible.

Add adversarial provider fakes for: no new events with boundary as newest,
one and multiple new pages, boundary exactly at a page edge, empty page before
boundary, short page before boundary, pruned boundary, repeated/cyclic cursor,
overlap, ordering fault, and ceiling breach. Include restart/replay tests that
prove no loss and no watermark advance on every failure.

### 3. Helius result-contract failures can still be recorded as OK usage

`HeliusRpcClient._rpc()` calls `send_with_usage()` and records `ok` after
only top-level JSON-RPC validation. Method-specific validation happens later
in `get_transaction()`, `get_signatures_for_address()`,
`get_signature_statuses()`, `get_balance()`, and
`get_token_accounts()`. A malformed method result therefore leaves an
`ok` usage row and then raises. This directly contradicts acceptance
criteria 13 and 14 and the checkpoint's PASS claim.

Move every method's complete nested contract validation and canonical model
construction inside the single accounted logical operation. Exactly one
terminal usage result may exist per call, and no validation failure may have
an `ok` record. Distinguish well-formed RPC errors from malformed response
contracts. Preserve retry count, latency, bytes, endpoint, request class, and
credit estimate.

Add a malformed nested-result test for every Helius method, plus JSON decode,
HTTP, RPC, transport, timeout, success, and usage-recorder-failure tests.
Assert the exact single terminal status and prove no contradictory row exists.
Audit the other adapters for the same post-accounting validation pattern and
fix any instance found.

### 4. Streaming usage-recorder failures still disappear silently

`IngestionManager._record_streaming()` still wraps the recorder in
`contextlib.suppress(Exception)`. This violates the requirement that a usage
recorder failure never mask the provider outcome but must emit a safe,
operator-visible health signal.

Replace silent suppression with a structured warning/health event containing
safe metadata only. It must not expose credentials or replace the underlying
stream outcome. Test connection, subscription, reconnect, and byte-accounting
recorder failures. Each must be visible, non-secret, and must not corrupt the
stream state machine.

### 5. Parse-attempt evidence omits required build/config/git identity

The round-2 instruction required each durable parse attempt to record
code/config/git identity. Migration 0004 and `ParseAttemptDraft` store
parser version and payload hash but no build hash, config hash, MASTER_SPEC
hash, or git commit. Therefore the immutable attempt cannot be reproduced
against the exact code/configuration that produced it.

Extend the append-only parse-attempt schema and runtime wiring with the
canonical build/config/spec/git identities defined by MASTER_SPEC. Values
must be captured at attempt time, be non-empty in production wiring, and be
preserved on reparse. A new parser version or build identity creates a new
attempt; it never rewrites prior evidence. Add migration-from-zero,
upgrade-from-0003/0005, downgrade, idempotency, restart, and reparse tests.
Keep grants append-only and least privilege.

### 6. Finalization provider failure is silently converted to zero promotions

`sweep_finalization()` catches every provider exception and returns `0`.
The running manager cannot distinguish “nothing finalized” from “the provider
check failed,” so the failure is neither surfaced nor reflected in health.
This contradicts the prior remediation requirement to record and surface
finalization failures without falsely restoring health.

Return a typed sweep outcome or propagate a typed failure. Record a safe
operational reason and ensure the supervised manager handles repeated or
terminal failures deterministically. A failed sweep must never be counted as a
successful zero-result sweep and must not restore wallet health. Preserve
confirmed-event safety semantics and provider usage accounting. Test provider
failure, malformed status response, partial/mismatched status cardinality,
cancellation, restart, duplicate finalized observation, and clean zero/new
promotion outcomes.

## Mandatory acceptance tests

Independently demonstrate at least:

1. every required real-chain category validates with immutable, licensed
   upstream provenance, or remains explicitly NOT TESTED and the checkpoint is
   PARTIAL;
2. a persisted pagination boundary is observed exactly before success;
3. empty/short/pruned history before that boundary fails DEGRADED;
4. no watermark or derived evidence advances across an unverified gap;
5. pagination overlap, cycles, order faults, exact edges, no-new-event, and
   ceiling recovery are covered in unit and replay tests;
6. every Helius method records one non-OK terminal usage row for malformed
   nested results and never records contradictory OK;
7. every provider adapter performs all result validation inside its accounted
   operation;
8. streaming recorder failure emits a safe visible signal without masking the
   stream outcome;
9. parse attempts durably preserve build, config, MASTER_SPEC, parser, payload,
   and git identities;
10. old parse attempts remain immutable and reparse creates versioned evidence;
11. finalization failure is distinguishable from zero promotions and is
    surfaced by the running manager;
12. finalization promotion remains idempotent and restart-safe;
13. real multi-wallet PostgreSQL tests still prove session isolation,
    commitment serialization, and append-only grants;
14. the required disconnect/reconnect reconciliation scenario still produces A
    and B exactly once;
15. no signing, signer, private-key, seed-phrase, live-arm, or broadcast path
    exists;
16. secret scan is clean;
17. no paid-provider feature is enabled;
18. no Phase 1.5 or later-phase code is started.

Run and record exact results for:

- `uv run pytest tests/unit -v`
- `uv run pytest tests/integration -v`
- `uv run pytest tests/golden -v`
- `uv run pytest tests/replay -v`
- `uv run pytest --cov --cov-report=term-missing`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy`
- relevant Alembic upgrade/current/downgrade checks, including upgrade from
  the pre-remediation schema;
- `uv run argus providers probe`
- `uv run argus providers probe-history`
- `uv run argus providers usage --provider helius`
- offline deterministic `uv run argus ingest run --test-mode`
- `uv run argus fixtures validate-real-chain`.

Do not claim an unrun test. PostgreSQL 16 may support code tests but must not
be described as PostgreSQL 17 validation. Live RPC/WebSocket and PG17 checks
may remain explicit environmental deferrals, but authenticated fixture
coverage may not be silently waived.

## Checkpoint, bundle, and handoff

At completion:

- keep Phase 1 awaiting orchestrator review and not approved;
- leave `last_orchestrator_approved_phase: 0` and the Phase 0
  `approved_commit` unchanged;
- preserve every earlier checkpoint and bundle as immutable history;
- create:
  - `orchestration/checkpoints/phase_1_remediation_3.md`
  - `orchestration/bundles/phase_1_remediation_3.txt`;
- generate the canonical runtime checkpoint/bundle required by MASTER_SPEC;
- use a new unique handoff ID;
- set `LAST_ORCHESTRATOR_INSTRUCTION_ID` exactly to
  `argus-phase-1-remediation-003`;
- identify every commit, exact test result, open failure, and deferral;
- state clearly that Phase 1.5 remains blocked;
- verify remote HEAD equals local HEAD and the worktree is clean.

Every commit created during this run must contain exactly one valid terminal
trailer:

`ARGUS-INSTRUCTION-ID: argus-phase-1-remediation-003`

Then STOP. Do not modify this instruction file. Do not self-authorize Phase
1, Phase 1.5, or any later work.
