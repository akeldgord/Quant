# ARGUS Orchestrator Instructions

**OWNER: ARGUS ORCHESTRATOR.** The implementation agent must not modify this
file. Execute only the ACTIVE instruction below. MASTER_SPEC.md remains
authoritative except where this instruction explicitly adds stricter
acceptance detail.

---

INSTRUCTION_ID: argus-phase-1-remediation-001
ISSUED_AT: 2026-08-31T05:14:25Z
TARGET_COMMIT: 32c2898ab8c278c2f75f4a2f40fedd9d35b24b08
AUTHORIZED_ACTION: REMEDIATE_PHASE_1_ONLY
AUTHORIZED_PHASE: 1
APPROVES_PHASE: NONE
STATUS: ACTIVE

## Independent audit disposition

- Phase 0 remains approved as
  `PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`.
- `PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK` remains open.
  It does not block this remediation, but it must be closed against real
  PostgreSQL 17 before live readiness may be approved.
- Phase 1 at the target commit is **not approved**. The reported
  `PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION` overstates the result
  because multiple non-environmental implementation requirements remain
  incomplete or incorrectly tested.
- Phase 1.5 and every later phase remain forbidden.
- This instruction approves no phase and authorizes Phase 1 remediation only.
- No live trade, mainnet canary, signing, private-key access, credential
  disclosure, paid-provider upgrade, live arming, threshold relaxation, or
  phase skip is authorized.

## Mandatory session start

Before changing code:

1. Run `git status --porcelain`, `git pull --ff-only`, and
   `git log -5 --oneline`.
2. Read the six canonical files in the exact order required by PROTOCOL.md.
3. Verify the checked-out instruction commit is exactly one
   instruction-file-only commit whose parent is the exact TARGET_COMMIT above.
4. Verify the worktree is clean and local HEAD equals the remote branch.
5. Verify `docs/BUILD_STATE.md` still has `current_phase: 1`,
   `last_orchestrator_approved_phase: 0`, and
   `awaiting_orchestrator_review: true`.
6. If any precondition is false, stop with an honest PARTIAL/FAIL handoff.
   Do not improvise around the gate.

## Audit findings that must be remediated

### 1. No production ingestion orchestration loop

The target has a WebSocket adapter, reconciliation engine, clock monitor,
scheduler, and streaming-usage model, but no continuously running code path
that composes them. Consequently, per-wallet subscriptions, automatic
disconnect/reconnect handling, scheduled truth reconciliation, clock-health
ticks, and streaming usage accounting do not exist as runtime behavior.

Implement a deterministic Phase 1 ingestion service and CLI entry point
(for example, `argus ingest run`) that:

- accepts the tracked-wallet set through a typed repository/config boundary;
- manages concurrent per-wallet subscriptions without sharing mutable wallet
  state incorrectly;
- records each WebSocket notification through the fast path;
- detects connect, subscribe, receive, timeout, disconnect, cancellation,
  and reconnect transitions;
- marks the affected wallet DEGRADED before or atomically with any unresolved
  transition;
- invokes truth-path reconciliation on every trigger required by
  MASTER_SPEC section 19 and also on a configurable periodic cadence;
- uses bounded, configurable reconnect backoff with deterministic injectable
  clock/sleep dependencies;
- records connection, subscription, reconnect, byte, and estimated-credit
  streaming counters at real invocation sites;
- samples/persists clock health and requires provider reconnection, successful
  reconciliation, and acknowledged clock recovery before restoring OK;
- is cancellation-safe, restart-safe, and idempotent;
- never treats a quiet stream, exhausted iterator, malformed message, or
  cancelled task as evidence that the wallet is healthy;
- exposes no signing, execution, broadcast, or live-entry path.

All runtime components must be injectable so the complete manager can be
tested without a credential or external network. Do not claim a fake
connector is live-provider validation.

### 2. Truth-path pagination can permanently lose events

`ReconciliationEngine.reconcile()` performs one
`getSignaturesForAddress` call with a 1000-record limit. If a gap contains
more than one page, it processes only the newest page and advances the
watermark past older unseen events.

Implement complete, bounded pagination with explicit page cursors and a
stable stop boundary. Requirements:

- retrieve every signature after the persisted reconciliation boundary,
  including gaps larger than 1000;
- process canonical events oldest-first;
- detect repeated cursors, non-progressing pages, inconsistent ordering,
  truncation, and configured safety ceilings and fail DEGRADED rather than
  skipping data;
- persist partial progress transactionally so a crash resumes without loss;
- do not advance a watermark beyond any unfetched or failed item;
- cover boundary-present, boundary-absent, duplicate-across-pages,
  empty-page, >1000-event, mid-page failure, and restart cases.

Adjust the provider protocol and Helius adapter to expose the actual Solana
pagination semantics rather than hiding them behind a single truncated list.

### 3. Commitment progression is not actually stored

A fast-path row is inserted with `confirmed_at=None`. Truth-path
reconciliation later attempts the same unique key; `SqlEventRecorder`
returns `False` and never records the confirmed transition. The existing
tests assert row count only and miss this. Also, `sig_info.err is None`
is transaction execution success, not commitment status; a failed
transaction can still be confirmed/finalized.

Implement an auditable commitment model that:

- keeps raw observations append-only;
- preserves the original `first_seen_at`;
- records processed/confirmed/finalized observations and their distinct
  observation timestamps monotonically;
- separates commitment status from transaction success/failure;
- makes the current canonical commitment state queryable deterministically;
- makes a fast-path event later become confirmed/finalized without rewriting
  or losing its original raw observation evidence;
- rejects commitment regression and conflicting source evidence;
- ensures processed-only events remain mechanically ineligible for future
  live execution;
- populates finalized state through a real code path, not schema-only debt.

Prefer an append-only commitment-observation/history table plus a
deterministic derived current-state query. If a different design is used,
document why it still satisfies CORE-002 and CORE-003 without mutating raw
evidence. Add a migration and least-privilege grants as needed.

### 4. Parsing is not connected to persistence

The generic parser and `swaps` table exist, but reconciliation only writes
`chain_events`; no production path parses a fetched transaction and
persists the derived classification linked to its event. Implement the
end-to-end canonical parse path:

- fetch and preserve raw transaction evidence first;
- parse deterministically from that evidence;
- persist one versioned derived classification linked to the canonical
  event;
- enforce deterministic dedup/replay constraints;
- preserve UNKNOWN/ambiguous/failed classifications for research;
- make UNKNOWN, ambiguous, failed, and insufficient-commitment records
  mechanically incapable of producing an eligible copy signal;
- support safe re-parsing under a new parser version without overwriting raw
  evidence or prior point-in-time results.

Add restart, duplicate-delivery, parser-failure, and transaction-failure
tests using the real SQL repositories.

### 5. Required golden evidence is synthetic

The target's golden-test source states that all fixtures are hand-built
synthetic payloads. The ACTIVE Phase 1 instruction required sanitized
real-chain golden transaction fixtures. Synthetic fixtures are useful unit
tests but cannot satisfy that acceptance criterion.

Add sanitized real-chain fixtures for every required category: SOL-to-token,
token-to-SOL, token-to-USDC, multi-hop swap, simple transfer, partial sell,
multiple token accounts, ambiguous multi-asset transaction, and failed
transaction. For each fixture preserve a non-secret provenance manifest with
at least chain, transaction signature, slot, capture source, capture time,
original-payload SHA-256, sanitized-payload SHA-256, sanitization operations,
and expected parser output. Sanitization must not alter fields used by the
parser.

If network/credential restrictions make acquisition impossible, do not
fabricate provenance and do not relabel synthetic data as real. Return
PARTIAL with this criterion NOT TESTED/blocked. Existing synthetic fixtures
may remain as additional unit fixtures but must be clearly labeled synthetic.

### 6. Adapter boundaries and contract validation are too weak

DexScreener, GeckoTerminal, and Jupiter return provider-shaped dictionaries
and accept essentially any JSON object. A top-level `dict` check is not
response-contract validation, and Helius nested result entries are also read
without complete structural validation.

Introduce typed canonical ARGUS response models and explicit validation:

- validate required keys, types, numeric-string formats, nullability, and
  list/object nesting before returning success;
- reject malformed success responses with typed provider-contract errors;
- return canonical ARGUS models to domain/consumer code while retaining raw
  provider evidence where required;
- validate Helius JSON-RPC envelopes and nested results for every implemented
  method;
- validate WebSocket acknowledgement and notification subscription identity,
  method, context, signature, slot, and error shape;
- do not classify malformed responses as merely unreachable;
- add adversarial malformed-response tests for every adapter and endpoint.

### 7. Usage accounting misses transport failures

When all retry attempts end in `httpx.TransportError`,
`request_with_retry()` raises before adapters call the usage recorder, so
real outbound attempts disappear from accounting. Streaming accounting has
no runtime caller.

Ensure every logical outbound operation records an auditable terminal row
on success, HTTP error, contract error, timeout, cancellation where safe, and
transport exhaustion. Record actual attempt/retry count, latency, bytes when
known, status, endpoint, request class, and estimated credits. Recording
failure must not mask the provider failure. Integrate streaming records with
the ingestion manager. Test transport exhaustion and recorder-failure
behavior explicitly.

### 8. Scheduler tests do not prove starvation protection

Strict priority alone can starve P1-P3 indefinitely under a sustained stream
of higher-priority work. The existing test proves ordering and non-dropping,
not bounded service.

Add a deterministic starvation policy that preserves the canonical P0-P6
priority semantics while guaranteeing safety-class requests P0-P3 are never
silently starved. Document the exact bound or service rule. Add sustained-load
tests showing each accepted safety request receives service, while P4-P6 may
be delayed/dropped only with an explicit missing-data reason. Validate
constructor limits (`max_concurrency > 0`, queue limits nonnegative) and
ensure cancellation cannot leak capacity or leave futures wedged.

### 9. Replay coverage is absent

`tests/replay/` collected zero tests despite the required replay command.
Add actual replay tests covering immutable raw evidence, deterministic parser
output, duplicate delivery, process restart, commitment progression, and
re-parse under a new parser version. The command must collect tests and pass.

### 10. Evidence/status accuracy

Do not mark an acceptance item PASS while its required runtime path is absent
or while a caveat directly contradicts the item. Specifically, streaming
usage without a caller, commitment progression without a promotion path,
schema-only finalized state, hand-built fixtures standing in for real-chain
fixtures, and a missing ingestion manager are not PASS.

Update BUILD_STATE, DECISION_LOG, checkpoint, bundle, and handoff with an
honest per-item disposition. Preserve the existing Phase 1 evidence files as
immutable history; create new remediation-specific files.

## Environmental validation disposition

The following may remain explicit deferred environmental checks after all
non-environmental implementation work above is complete:

- live Helius RPC connectivity;
- live Helius WebSocket connectivity;
- real PostgreSQL 17 Compose validation.

They may never be called PASS without actual execution. They do not authorize
live readiness. A missing credential must produce only the section-108
`LOCAL CREDENTIAL REQUIRED` notice and must never be printed, requested in
chat, or replaced by a mocked live claim.

Real-chain golden fixtures are a data-evidence requirement, not automatically
waived by the live-connection deferral. If authentic provenance cannot be
obtained from already available safe sources, report Phase 1 PARTIAL and stop.

## Mandatory acceptance tests

Add and independently demonstrate at least:

1. end-to-end manager: connect -> A -> disconnect -> B missed -> reconnect ->
   reconciliation -> A/B exactly once;
2. the same scenario across manager process restart and duplicate delivery;
3. multiple wallets remain isolated under concurrent subscriptions;
4. stream timeout, malformed message, exhausted iterator, subscription
   failure, host resume, and clock anomaly all fail DEGRADED;
5. recovery requires reconnection + complete reconciliation + healthy clock;
6. streaming usage is recorded from the manager's real code path;
7. a gap larger than 1000 is fully paginated with no loss;
8. repeated/non-progressing cursors and safety-ceiling exhaustion fail closed;
9. mid-page fetch failure resumes at the exact safe boundary after restart;
10. fast-path first-seen time survives confirmed and finalized progression;
11. failed on-chain transactions can be confirmed/finalized while remaining
    execution-failed and copy-ineligible;
12. commitment regression/conflict is rejected and audited;
13. reconciliation actually persists versioned parser output;
14. parser/repository duplication is idempotent across restart;
15. all required authenticated real-chain golden fixtures pass and their
    manifests/hash checks validate;
16. malformed contract responses are rejected for every provider endpoint;
17. transport exhaustion still produces usage evidence;
18. P0-P3 accepted requests receive bounded service under sustained load;
19. scheduler cancellation/invalid configuration cannot wedge capacity;
20. `tests/replay` collects and passes meaningful tests;
21. migration from zero and upgrade from Phase 0 head succeed where a
    database is available;
22. DB role grants remain least privilege;
23. no signing, signer, private-key, seed-phrase, live-arm, or broadcast path
    exists;
24. secret scan is clean;
25. no paid-provider feature is enabled;
26. no Phase 1.5 or later-phase code is started.

Run and record exact results for:

- `uv run pytest tests/unit -v`
- `uv run pytest tests/integration -v`
- `uv run pytest tests/golden -v`
- `uv run pytest tests/replay -v`
- `uv run pytest --cov --cov-report=term-missing`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy`
- relevant Alembic upgrade/current/downgrade checks;
- `uv run argus providers probe`;
- `uv run argus providers probe-history`;
- `uv run argus providers usage --provider helius`;
- an offline deterministic `argus ingest run` smoke test using injected
  fakes or a dedicated test-mode harness that cannot broadcast transactions.

Do not claim an unrun test. A substitute PostgreSQL server may support code
tests but must not be described as PostgreSQL 17 validation.

## Checkpoint, bundle, and handoff

At completion:

- keep Phase 1 awaiting orchestrator review; do not mark it approved;
- leave `last_orchestrator_approved_phase: 0` and the Phase 0
  `approved_commit` unchanged;
- create new immutable evidence paths:
  - `orchestration/checkpoints/phase_1_remediation_1.md`
  - `orchestration/bundles/phase_1_remediation_1.txt`;
- generate the canonical runtime checkpoint/bundle required by MASTER_SPEC;
- use a new unique handoff ID;
- set `LAST_ORCHESTRATOR_INSTRUCTION_ID` exactly to
  `argus-phase-1-remediation-001`;
- identify all commits and environmental deferrals exactly;
- state that Phase 1.5 remains blocked;
- verify remote HEAD equals local HEAD and the worktree is clean.

Every commit created during this run must contain exactly one valid terminal
trailer:

`ARGUS-INSTRUCTION-ID: argus-phase-1-remediation-001`

Then STOP. Do not modify this instruction file. Do not self-authorize Phase
1.5 or any later work.
