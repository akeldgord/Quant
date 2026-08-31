# ARGUS Orchestrator Instructions

**OWNER: ARGUS ORCHESTRATOR.** The implementation agent must not modify this
file. Execute only the ACTIVE instruction below. MASTER_SPEC.md remains
authoritative except where this instruction adds stricter acceptance detail.

---

INSTRUCTION_ID: argus-phase-1-remediation-006
ISSUED_AT: 2026-08-31T17:50:14Z
TARGET_COMMIT: fbe46c44861e489f65d55abac01eedc4934318a7
AUTHORIZED_ACTION: REMEDIATE_PHASE_1_ROUND_6_AND_WATCHER_HARDENING_ONLY
AUTHORIZED_PHASE: 1
APPROVES_PHASE: NONE
STATUS: ACTIVE

## Independent audit disposition

- Phase 0 remains approved as `PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`.
- `PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK` remains open. It
  does not block this remediation, but it still blocks live readiness.
- Phase 1 remediation round 5 is **rejected as FAIL_REMEDIATION_REQUIRED**.
  Several round-5 fixes are real and should be preserved, but independent
  review found remaining defects in production git identity, fixture
  provenance, independent fixture semantics, Helius contract validation, and
  the unattended watcher pre-launch branch-movement barrier.
- Phase 1 remains unapproved. Phase 1.5 and every later phase remain blocked.
- This instruction approves no phase and authorizes only the remediation below.
- Live Helius RPC/WebSocket connectivity may remain an explicitly named
  `DEFERRED_ENVIRONMENTAL_CHECK` if the implementation environment still lacks
  the required credential/network path. Do not convert an unrun live check to
  PASS. This deferral, like PG17, must be closed before live readiness.
- No live trade, mainnet canary, transaction broadcast, signing, private-key or
  seed access, credential entry/disclosure, paid-provider upgrade, live arming,
  threshold relaxation, or phase skip is authorized.

## Mandatory session start

Before changing code:

1. Run `git status --porcelain`, `git pull --ff-only`, and
   `git log -5 --oneline`.
2. Read, in this exact order:
   `MASTER_SPEC.md`, `docs/BUILD_STATE.md`, `docs/DECISION_LOG.md`,
   `orchestration/PROTOCOL.md`, `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`,
   `orchestration/AGENT_HANDOFF.md`.
3. Verify this ACTIVE instruction is introduced by exactly one commit that
   touches only `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` and whose parent
   is exactly the TARGET_COMMIT above.
4. Verify the worktree is clean and local HEAD equals freshly fetched remote
   branch HEAD.
5. Verify BUILD_STATE still has `current_phase: 1`,
   `last_orchestrator_approved_phase: 0`, and
   `awaiting_orchestrator_review: true`.
6. If any precondition is false, do not improvise. Stop with an honest
   PARTIAL/FAIL handoff and no Phase 1.5 work.

## Required engineering approach

Treat this as one consolidated remediation pass. Before editing, create a
requirement-to-code-to-test matrix for every finding below plus every Phase 1
MASTER_SPEC acceptance item. Inspect production call paths, persistent state,
provider boundaries, and watcher state transitions; do not rely on helper-level
unit tests alone.

For each finding, add at least one negative/adversarial regression test that
would fail on TARGET_COMMIT `fbe46c44861e489f65d55abac01eedc4934318a7`
and pass only after the fix. Preserve the correct round-5 behavior, including:

- failed/ambiguous/decimals-zero transactions remaining ineligible;
- `SWAP_COMPLEX` remaining ineligible absent deterministic proof;
- exact typed WebSocket acknowledgement matching;
- early-notification buffering;
- quiet-socket transport liveness probing;
- deterministic reconciliation and A/B missed-event recovery;
- parser-artifact-aware append-only reparse behavior;
- populated-data migration 0007 downgrade refusal without evidence loss;
- commitment monotonicity/finalization behavior;
- database session isolation;
- provider accounting;
- phase gating and terminal watcher quarantine on instruction-file mutation.

Do not close findings by changing wording, weakening an acceptance criterion,
renaming a fixture, recomputing a hash over self-authored metadata, or treating
builder-generated values as independent evidence.

## Audit findings and mandatory remediation

### 1. Production Git identity still fails open when Git is present but unverifiable

`resolve_production_git_commit()` now checks dirty state before trusting an
override, which is an improvement. However `_is_dirty_checkout()` returns
`None` for **every** `git status` failure, and the production resolver treats
that result as if Git metadata were absent. A valid-looking
`ARGUS_BUILD_GIT_COMMIT` is then accepted. Therefore a corrupt, unreadable,
broken, permission-denied, or otherwise unverifiable Git checkout can still be
represented by an arbitrary override SHA.

Required behavior:

- Distinguish at least these states explicitly: `GIT_ABSENT`, `GIT_PRESENT_CLEAN`,
  `GIT_PRESENT_DIRTY`, and `GIT_PRESENT_UNVERIFIABLE`.
- A failed Git command is **not** evidence that Git metadata is absent.
- If `.git`/worktree metadata is present or the process is in a Git worktree,
  any failure to establish clean status or exact HEAD must fail closed in
  production, even when a valid override is supplied.
- In a real Git checkout, an override must exactly equal verified HEAD.
- A build-time override may be accepted only when Git metadata is positively
  established to be absent, and the existing deployment provenance contract
  is satisfied.
- Test: clean/no override; clean/matching override; clean/mismatch; dirty/no
  override; dirty/matching override; dirty/mismatch; genuinely no-Git valid
  override; no-Git invalid override; missing identity; explicit test mode;
  **Git metadata present but `git status` fails**; Git metadata present but
  `rev-parse HEAD` fails; permission/unreadable/corrupt-worktree simulation.
- Existing historical sentinel rows remain append-only and must not be rewritten.

### 2. Fixture provenance does not yet prove commit -> tree/path -> blob offline

Round 5 stores a `git ls-tree` output line and later re-parses that saved line.
That proves only that the saved text agrees with itself. It does **not** prove,
offline, that the declared upstream commit actually contains the declared path
at a tree that resolves to the declared blob. The validator's own comments
acknowledge that it is an offline consistency check rather than a re-verification
of the upstream ref. This does not satisfy remediation-005 finding #2.

Required behavior:

- Preserve enough immutable Git object evidence to verify offline the actual
  object chain from the declared commit to the relevant tree entry/path and
  final blob for both the transaction source and license/notice evidence.
- Acceptable designs include a minimal content-addressed set of raw Git commit,
  tree, and blob objects (or an equivalent deterministic Git bundle/object
  pack) from which the validator independently recomputes object IDs and walks
  the path. A saved `git ls-tree` text line alone is insufficient.
- The validator must recompute every object ID from raw object bytes and prove:
  declared commit -> declared root tree -> path traversal -> declared source
  blob, and the same for the license/notice path.
- Bind repository identity, declared immutable commit, source path, license
  path, source bytes, license bytes, transform manifest, expectation, reviewer
  evidence, and final sanitized output into the evidence record.
- Clearly distinguish what can be proven offline (Git object-chain/content
  integrity) from what inherently required the original online acquisition
  (for example, that a particular remote hostname served that commit). Do not
  label an online-only property as offline-proven.
- Add tamper tests for commit object bytes/ID, root tree ID, intermediate tree,
  path component, blob ID, source bytes, license object/path/bytes, transform
  order/content, repository/commit metadata, expectation, reviewer evidence,
  and final sanitized bytes.

### 3. The independent golden oracle loses account-level context and leaves record identity fields weakly bound

`ExpectedAssetDelta` has `account_context`, but the production observation path
first aggregates token movement by mint and validation then hard-codes every
observed `account_context` to `None`. The committed LP/multiple-account fixture
therefore cannot independently prove the multiple-token-account property it is
being used to close. The current Orca fixture being classified `UNKNOWN`
instead of `LP_ACTION` is **not by itself a failure**: MASTER_SPEC requires
real multiple-token-account/LP-style evidence and fail-closed parsing, not a
specific `LP_ACTION` label. The problem is that the evidence system currently
discards the account-level facts needed to prove the category.

Required behavior:

- Preserve an account-level canonical delta view before any by-mint aggregation.
  Each material token-account delta must retain at minimum account index/pubkey
  or another deterministic account identifier, owner/wallet relationship,
  mint, pre/post raw amount, net raw delta, decimals, and exact UI delta.
- Keep by-mint aggregation for parser logic if useful, but do not use it as the
  independent oracle for account-level semantics.
- Populate and validate `account_context` (or a stronger typed replacement)
  whenever account identity is material.
- Re-review every real-chain fixture against raw evidence. The multiple-account
  category must demonstrably contain the required distinct relevant token
  account behavior. If the current Orca fixture cannot satisfy that exact
  semantic requirement from the chosen wallet perspective, source a better
  authentic fixture; do not relabel it.
- The existing Orca fixture may count even though the parser emits `UNKNOWN`
  rather than `LP_ACTION` **only if** the independent account-level evidence
  proves the multiple-account/LP-style category and the parser correctly keeps
  it ineligible.
- Bind and validate record identity fields that can otherwise drift from the
  rebuilt payload: at minimum category, chain, transaction signature, slot,
  transaction version, upstream path, and expectation identity. Rebuilt
  payload signature/slot/version must be checked against the record, not merely
  fed back into the parser as trusted inputs.
- Add direct tamper tests for all record identity fields and an adversarial test
  where two accounts of the same mint move differently; aggregation must not
  erase the evidence needed by the oracle.

### 4. Helius HTTP/canonical-model validation is still incomplete

Round 5 added many useful nested checks, but several unsafe/overstated cases
remain.

Required behavior:

- Validate the JSON-RPC envelope itself for every HTTP RPC call: response must
  be an object with exact supported `jsonrpc` version and exact request-ID
  type/value; mismatched IDs/versions and mixed result/error responses fail
  closed inside the single accounted operation.
- `get_transaction(signature)` must bind response identity to the request. The
  returned canonical primary transaction signature must be non-empty and must
  equal the requested signature; a structurally valid response for a different
  transaction must not be accepted or persisted under the requested identity.
- All downstream-consumed slot/block-time/fee/balance/raw-amount fields must use
  strict, explicit numeric domains. Reject booleans, negatives where impossible,
  and oversized values. For Solana raw lamport/SPL amounts and slots, enforce
  the correct on-chain unsigned-width bounds where applicable. Decimal integer
  strings must be ASCII decimal digits and bounded before conversion; do not
  accept arbitrarily large strings merely because `int()` can parse them.
- `get_signatures_for_address` currently accepts negative slot/blockTime values;
  reject impossible values and safely validate conversion to UTC timestamps.
- For non-null `get_signature_statuses` entries, require the contract fields
  used by ARGUS to be present and validate explicit null only where the Solana
  RPC contract permits it. A missing `err` key must not become an implicit
  successful `None` through `.get()`.
- Empty/invalid identity strings used as signatures, account keys, mints,
  owners, or token-account pubkeys must fail the adapter contract before
  persistence/consumption. Use a deterministic minimal syntactic validation
  appropriate to the field; do not add network lookups.
- `TokenAccountInfo.raw` must be genuinely immutable. `MappingProxyType(entry)`
  is only a shallow wrapper and still exposes mutable nested dict/list objects;
  it can also retain aliases. Deep-copy then recursively freeze to immutable
  canonical structures, store canonical immutable bytes, or otherwise prove
  nested source mutations and caller mutation attempts cannot alter the
  returned evidence.
- Every new contract failure must still produce exactly one terminal non-OK
  provider-usage record; successful calls exactly one OK record; never double
  account.
- Add negative tests for HTTP JSON-RPC id/version mismatch, bool IDs,
  result+error coexistence, wrong returned transaction signature, negative and
  overflow slots/balances/fees/amounts, huge numeric strings, Unicode-digit
  strings, missing status error field, empty identity strings, and nested raw
  mutation/alias attempts. Add positive controls for the valid boundary values.

### 5. The unattended watcher has a pre-launch remote-branch freshness race

The watcher fetches/pulls early in `tick()`, then later compares local HEAD to
`origin/<branch>` immediately before launch. But `git_remote_head()` only reads
the locally cached remote-tracking ref; there is no fresh fetch at that final
barrier. If the remote branch moves after the early fetch but before launch,
the cached comparison can still pass and Claude can be launched against stale
review state. Post-run attribution may catch the drift later, but the safety
property required here is to avoid launching unauthorized/stale work in the
first place.

Required behavior:

- Add a final **fresh remote pre-launch barrier** after instruction/phase/target
  validation and as close as practical to process launch.
- Before changing watcher state to RUNNING or invoking Claude, perform a fresh
  fetch of the exact branch, then re-check: clean worktree; local HEAD equals
  freshly fetched remote HEAD; ACTIVE instruction bytes/fields are unchanged;
  target-commit provenance still passes; phase authorization still passes.
- If the remote moved, the fetch failed, the instructions changed, the
  worktree changed, or any revalidation is ambiguous, do not launch Claude.
  Exit/return deterministically so the next tick can pull and evaluate the new
  remote state. Do not consume or mark the stale instruction complete.
- Snapshot the actual working-tree instruction-file hash that Claude will read,
  and require it to equal the committed HEAD blob at the pre-launch barrier;
  continue retaining the existing post-run mutation check/quarantine.
- Add a deterministic test in which the remote moves **after the first fetch/
  pull but before the final launch barrier**; assert Claude runner call count is
  zero. Add variants for a final fetch failure and a local instruction/worktree
  mutation between initial parse and final barrier.
- Preserve the existing single-instance lock, restart behavior, exact trailer
  attribution, new-evidence checks, and terminal quarantine semantics.

### 6. Evidence/reporting must reflect what is actually proven

Round 5's 490-test result, 87% coverage, migration behavior, parser fail-closed
changes, and WebSocket improvements are useful evidence, but they do not turn
the unresolved items above into PASS.

Required behavior:

- Keep historical checkpoint/phase-history rows immutable. Add new round-6
  checkpoint/bundle/history entries; do not rewrite what prior rounds claimed
  at the time.
- Cross-check BUILD_STATE, DECISION_LOG, checkpoint, bundle, handoff, fixture
  provenance, fixture coverage matrix, and test output before handoff.
- Use only `PASS`, `FAIL`, `PARTIAL`, `NOT TESTED`, or
  `DEFERRED_ENVIRONMENTAL_CHECK` for acceptance dispositions, with a reason and
  direct evidence reference for every non-PASS item.
- Do not call PostgreSQL 16 evidence PostgreSQL 17 validation.
- Do not call mocked/fake Helius transport evidence live RPC/WebSocket
  validation.

## Mandatory acceptance matrix

Round 6 is complete only when fresh evidence proves all of the following:

1. Production Git identity distinguishes absent Git from present-but-unverifiable
   Git and fails closed for every dirty/unverifiable checkout regardless of
   override.
2. Every counted authentic fixture has an offline-verifiable Git object chain
   proving declared commit/tree/path/blob for source and license evidence; a
   saved `ls-tree` line alone cannot satisfy this item.
3. Every counted fixture has an independent semantic oracle that validates
   wallet perspective, account-level deltas where material, by-mint deltas,
   classification, eligibility, input/output amounts, fee, failure state,
   confidence rule, rationale, and evidence.
4. The multiple-token-account/LP-style category is proven by authentic
   account-level evidence. The parser label may be `UNKNOWN` rather than
   `LP_ACTION` if the semantic category is independently proven and remains
   ineligible.
5. All nine MASTER_SPEC real-chain fixture categories remain authentic and
   independently validated after the stronger provenance/oracle checks;
   otherwise Phase 1 remains PARTIAL.
6. Fixture record identity fields are bound to and checked against rebuilt raw
   evidence; every direct tamper class fails closed.
7. Helius HTTP JSON-RPC envelope and every downstream-consumed field use strict
   type/domain/identity validation; wrong-transaction and malformed numeric
   responses cannot cross the adapter boundary.
8. `TokenAccountInfo.raw` or its replacement is deeply immutable and
   alias-safe; nested mutation cannot change returned canonical evidence.
9. Every Helius success/failure path records exactly one correct terminal
   provider-usage outcome.
10. WebSocket typed acknowledgement, early-notification preservation, bounded
    lifecycle, quiet-socket liveness, dead-socket reconciliation, and exact
    once canonicalization remain green.
11. Reparse remains parser-artifact-aware, append-only, concurrent-safe,
    restart-safe, and converges to no pending work.
12. Migration 0007 populated-data downgrade behavior remains non-destructive
    and fail-closed when the older schema cannot represent the data.
13. Direct pagination-boundary proof, commitment monotonicity, finalization,
    disconnect/reconnect A/B, persistent watermarks, database session
    isolation, provider priority/accounting, and restart/crash regressions
    remain green.
14. The watcher performs a fresh final remote pre-launch barrier and cannot
    launch on a remote branch that moved after its initial fetch/pull.
15. Watcher stale CLAIMED/RUNNING handling, failed-Claude handling, exact
    handoff ID, fresh checkpoint/bundle requirements, dirty/unpushed rejection,
    trailer attribution, target-commit protection, and terminal instruction-file
    quarantine remain green.
16. Real PostgreSQL concurrency/migration checks remain green. Any PostgreSQL
    16 run is labeled PostgreSQL 16 only.
17. Live Helius RPC/WSS and PG17 checks are either actually run and evidenced or
    remain explicit `DEFERRED_ENVIRONMENTAL_CHECK`; no simulated test can close
    them.
18. No signer/signing/key/seed/live-arm/broadcast/mainnet trade/paid-provider
    enablement exists, and no Phase 1.5 or later-phase implementation begins.
19. Secret scan is clean; no credential is entered, displayed, logged, or
    committed.
20. Full repository quality gates and the full Phase 1 + watcher regression
    suite pass with no unexplained skips.

## Required test evidence

Run and record exact commands, exit codes, pass/fail/skip counts, durations,
environment, and relevant artifact hashes for at least:

- `uv run pytest tests/unit -v`
- `uv run pytest tests/integration -v`
- `uv run pytest tests/golden -v`
- `uv run pytest tests/replay -v`
- `uv run pytest tests/unit/test_orchestrator_watch.py -v`
- targeted production-git-identity adversarial tests
- targeted fixture object-chain/account-context/tamper tests
- targeted Helius malformed-contract + exact-usage-count tests
- targeted watcher late-remote-movement/final-fetch-failure tests
- `uv run pytest --cov --cov-report=term-missing`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy`
- relevant Alembic upgrade/current/downgrade + populated-data checks
- `uv run argus providers probe`
- `uv run argus providers probe-history`
- `uv run argus providers usage --provider helius`
- offline deterministic `uv run argus ingest run --test-mode`
- offline fixture rebuild/validation proving the Git object chain and all
  committed fixture semantics
- repeated current-artifact reparse proving convergence
- secret scan covering tracked files and relevant history policy

If a command cannot run because of the known environment, record the exact
reason and use `DEFERRED_ENVIRONMENTAL_CHECK` or `NOT TESTED` as appropriate.
Never claim an unrun command.

## Required checkpoint and handoff

When the authorized work is complete:

1. Create a **new** immutable checkpoint:
   `orchestration/checkpoints/phase_1_remediation_6.md`
2. Create a **new** immutable bundle:
   `orchestration/bundles/phase_1_remediation_6.txt`
3. The bundle must contain the checkpoint bytes verbatim plus the review
   evidence required by PROTOCOL.md.
4. Update `docs/BUILD_STATE.md` without marking Phase 1 orchestrator-approved.
5. Append any material orchestrator-approved protocol/tooling decision to
   `docs/DECISION_LOG.md`; do not rewrite prior entries.
6. Update `orchestration/AGENT_HANDOFF.md` with a new HANDOFF_ID and
   `LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-1-remediation-006`.
7. Every commit created during this run must carry exactly one real terminal
   trailer:
   `ARGUS-INSTRUCTION-ID: argus-phase-1-remediation-006`
8. Commit and push all authorized work. Verify clean working tree and exact
   local/remote HEAD agreement.
9. STOP. Do not begin Phase 1.5.

## Phase gate

This instruction does **not** approve Phase 1.

`last_orchestrator_approved_phase` must remain `0`.

Phase 1.5 is forbidden until an independent orchestrator audit of the new
round-6 handoff explicitly approves Phase 1 and issues a separate ACTIVE
instruction with `APPROVES_PHASE: 1` and `AUTHORIZED_PHASE: 1.5`.
