# ARGUS Orchestrator Instructions

**OWNER: ARGUS ORCHESTRATOR.** The implementation agent must not modify this
file. Execute only the ACTIVE instruction below. MASTER_SPEC.md remains
authoritative except where this instruction adds stricter acceptance detail.

---

INSTRUCTION_ID: argus-phase-1-remediation-005
ISSUED_AT: 2026-08-31T15:05:00Z
TARGET_COMMIT: d1b7ef0ae9c4d40ada15cac60fb7931bf8de2376
AUTHORIZED_ACTION: REMEDIATE_PHASE_1_ROUND_5_ONLY
AUTHORIZED_PHASE: 1
APPROVES_PHASE: NONE
STATUS: ACTIVE

## Independent audit disposition

- Phase 0 remains approved as PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION.
- PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK remains open and
  blocks live readiness, not this remediation.
- Phase 1 remediation round 4 is rejected as FAIL_REMEDIATION_REQUIRED.
  The builder honestly reported one partial criterion, but independent review
  found additional untested and unsafe behavior described below.
- Phase 1 remains unapproved. Phase 1.5 and all later phases remain blocked.
- This instruction approves no phase and authorizes only the listed Phase 1
  remediation.
- No live trade, mainnet canary, transaction construction or broadcast,
  signing, private-key or seed access, credential disclosure or entry,
  paid-provider upgrade, live arming, threshold relaxation, or phase skip is
  authorized.

## Mandatory session start

Before changing code:

1. Run git status --porcelain, git pull --ff-only, and git log -5 --oneline.
2. Read the six canonical files in the exact PROTOCOL.md order.
3. Verify this instruction is in exactly one instruction-file-only commit whose
   parent is the exact TARGET_COMMIT above.
4. Verify the worktree is clean and local HEAD equals the remote branch.
5. Verify BUILD_STATE still has current_phase 1,
   last_orchestrator_approved_phase 0, and awaiting_orchestrator_review true.
6. If any precondition is false, stop with an honest PARTIAL/FAIL handoff.

## Required engineering approach

Treat this as one consolidated repair pass. Before implementation, build a
requirement-to-code-to-test matrix covering every finding and every Phase 1
MASTER_SPEC requirement. Inspect production call paths, not only helper tests.
For each fix, add a negative/adversarial test that fails on the submitted
round-4 implementation and passes only after the fix. Preserve all correct
round-4 behavior, including parser-artifact selection, current-artifact reparse
convergence, visible missing-finalization failure, pagination boundary checks,
session isolation, restart recovery, append-only evidence, and provider
accounting.

Do not satisfy an acceptance item by changing wording, weakening a category,
renaming a fixture, or asserting a builder-generated value as an independent
oracle.

## Audit findings and required remediation

### 1. Golden expectations remain circular and incomplete

RealChainFixtureRecord and its importer currently store only expected and
observed classification/confidence. validate_real_chain_fixtures compares only
those fields. It does not independently assert copy eligibility, wallet
perspective, canonical asset deltas, input/output mint, raw/UI material
amounts, network fee, or semantic evidence. This does not satisfy the round-4
instruction and cannot detect a confidently wrong parse.

Implement a typed immutable independent expectation for every wallet
perspective. At minimum it must include:

- independently reviewed classification and is_copy_eligible;
- wallet perspective and the method used to establish it;
- ordered canonical asset deltas with mint, account context where material,
  raw integer amount, decimals, and exact UI amount;
- expected input/output mint and material input/output amounts where applicable;
- network fee and failed-transaction status;
- confidence expectation or bounded rule;
- semantic rationale and the evidence used by the reviewer.

Keep parser-observed output separate. Importing may record observed output but
must never promote it to expected truth. Offline validation must compare every
applicable canonical field. A parser mismatch may be preserved as a quarantined
research fixture, but it must fail golden validation and cannot count as passing
category coverage.

### 2. Provenance is not fully bound or tamper-evident

The round-4 provenance records useful hashes, but metadata such as upstream
repository, commit, path, license, and reviewer method is not cryptographically
bound to the preserved source. Editing those fields can still pass. Source
container/envelope type and license evidence are also incomplete.

For each authentic fixture, preserve an offline-verifiable evidence chain that
binds:

- repository identity, immutable commit, tree/path, and Git blob identity;
- exact original bytes and their SHA-256;
- source container/envelope type;
- ordered deterministic transforms, with input and output hash per step;
- exact final sanitized bytes and SHA-256;
- license file path, exact license/notice bytes or immutable blob, its hash,
  compatibility decision, and required attribution;
- wallet perspective, independent reviewer method, semantic evidence, and
  expectation-object hash.

Where Git objects are used, preserve enough immutable commit/tree/blob evidence
to prove that the declared path at the declared commit resolves to the declared
blob. A bare metadata string is insufficient. The offline validator must
rebuild the sanitized fixture and fail closed on tampering with repository,
commit, path, tree/blob, source bytes, source hash, transform order or content,
license path/content/hash/notice, reviewer evidence, expectation, or final
output. If a property can only be verified online, report it separately and do
not count it as offline PASS.

Add direct tamper tests for every field group above.

### 3. All nine authentic real-chain fixture categories are still required

The truthful round-4 status is six of nine. The missing categories are:

- genuinely ambiguous multi-asset behavior that must be UNKNOWN and ineligible;
- multiple-token-account or LP-style behavior;
- failed on-chain transaction with non-null meta.err.

The following public artifacts are candidate starting points discovered during
independent review. They are not pre-approved fixtures. Verify exact bytes,
commit, license, wallet perspective, and semantics before use:

- failed: coinbase/chainstorage commit
  e5932902bae94e0578d13328f9f4135b3c95c252,
  internal/utils/fixtures/parser/solana/transaction_err.json, with license
  evidence from LICENSE.md at the same commit;
- LP/multiple accounts: quellen-sol/ingestooor commit
  74e2039ec8dbc61bc5df1e08540ec5a3f3cd991e,
  crates/parsers/tests/orca/orca_add_liq.json, and, if useful, the Raydium
  increase-liquidity fixtures in that repository, with LICENSE evidence;
- ambiguous/non-fungible candidate: milktoastlab/SolanaNFTBot commit
  e77710555004db314117d435f0d2b4f1dca54a77,
  src/lib/marketplaces/__fixtures__/magicEdenSaleTxV2.ts. A buyer-perspective
  NFT purchase is a useful adversarial case because balance deltas alone can
  resemble a swap. The same repository also contains magicEdenFailedTx.ts.

A getBlock transactions array or TypeScript fixture wrapper requires an
explicit, deterministic, audited extraction transform. Do not execute source
code to extract a fixture.

Complete all nine authentic categories if compatible evidence is available.
The failed and LP candidates above may not be dismissed as unavailable without
documented source, license, and semantic review. If any category genuinely
cannot be verified, report it as NOT TESTED/PARTIAL and do not request Phase 1
approval.

The checkpoint matrix must list all nine categories consistently, with exact
source, commit/path/blob, wallet perspective, independent expectation,
observed result, eligibility, evidence hash, and PASS/PARTIAL/FAIL status.

### 4. The generic parser is not fail-closed for ambiguous assets

Current balance-delta logic marks any transaction with both negative and
positive wallet deltas as SWAP_SIMPLE or SWAP_COMPLEX. SWAP_COMPLEX is
copy-eligible above the confidence threshold. This makes multi-asset, LP-like,
NFT, and otherwise unproven transactions eligible without deterministic proof.
A decimals-zero NFT purchase can be called a simple swap.

Define and document fail-closed Phase 1 semantics:

- failed transactions are UNKNOWN and ineligible;
- genuinely ambiguous multi-asset transactions are UNKNOWN and ineligible;
- NFT/non-fungible or decimals-zero asset movement is not automatically a
  fungible copy-trade swap;
- LP creation/removal, multiple material candidate legs, multiple relevant
  token accounts, or an unproven route is ineligible;
- balance deltas may preserve research evidence but cannot alone prove
  copy-trade eligibility for an ambiguous complex route;
- SWAP_COMPLEX must be ineligible in v1 unless a separate deterministic proof
  rule is defined, implemented, and demonstrated with authentic fixtures.

Test the authentic ambiguous, NFT/non-fungible, LP, multiple-account, failed,
simple swap, multi-hop, transfer, and partial-sell cases. Demonstrate that no
ambiguous event can emit an eligible signal.

### 5. Helius HTTP contracts are still under-validated

Validate every field used by persistence, parsing, reconciliation, provider
health, and downstream consumers inside the single accounted operation. Reject
Python booleans wherever an integer is required.

At minimum:

- get_slot and get_balance require strict nonnegative integers, not bool;
- get_transaction requires a non-null object with a nonempty canonical
  signatures list, transaction.message object, accountKeys list and supported
  account-key shapes, required meta.err field, strict nonnegative meta.fee,
  preBalances/postBalances strict nonnegative integer arrays with coherent
  lengths, valid slot/blockTime when consumed, and fully validated token-balance
  entries;
- each token-balance entry requires accountIndex strict integer in range,
  mint/owner strings as applicable, uiTokenAmount.amount as a nonnegative
  decimal integer string, and bounded nonnegative decimals;
- get_token_accounts validates returned ownership against the requested wallet,
  canonical field types, nonnegative amounts, bounded decimals, and returns
  immutable typed adapter models rather than provider-shaped dictionaries;
- get_signature_statuses validates every consumed nested field, including
  strict slot/error/confirmation values.

Malformed fields, missing required fields, incoherent array lengths, wrong
owner, out-of-range index, bool-as-int, nulls, and oversized/invalid numeric
forms must fail closed. Each operation, including validation failures, must
write exactly one terminal provider-usage record with the correct non-OK
outcome. No double-accounting is allowed.

### 6. WebSocket acknowledgement and lifecycle behavior can lose evidence

_read_matching_ack currently uses Python equality, so JSON true can match
request ID 1. It also consumes and discards nonmatching messages, including a
valid early notification. Cleanup has no bounded timeout. The manager treats
30 seconds of normal socket silence as a dead connection and reconnects,
creating avoidable provider use and gap risk.

Required behavior:

- JSON-RPC version, request ID type and value, result/error exclusivity, and
  subscription result type must match exactly; bool, string, float, null,
  unrelated ID, wrong version, and mixed result/error are invalid;
- a valid notification arriving before the matching acknowledgement must be
  buffered and replayed in order, or the connection must fail closed without
  losing the need for truth-path reconciliation;
- connect, send, acknowledgement, receive-liveness probe, cancellation, and
  context-manager cleanup must all be bounded;
- quiet but transport-healthy sockets must not reconnect every receive timeout;
  use transport ping/pong or an equivalent explicit liveness check and run
  reconciliation without needless resubscription;
- truly dead sockets must close, reconcile, reconnect, resubscribe, and process
  each canonical event exactly once;
- reconnect and provider-usage behavior must remain feasible under the
  documented free-first provider budget.

Add deterministic tests for typed-ID mismatches, early notification before ack,
multiple unrelated messages, bounded cleanup, cancellation during every
transition, quiet healthy socket, dead socket, restart, reconciliation, no lost
notification, no duplicate canonicalization, and exact reconnect/accounting
counts.

### 7. Production Git identity can be spoofed by an override

resolve_production_git_commit currently returns ARGUS_BUILD_GIT_COMMIT before
checking an available checkout. A dirty checkout can therefore provide any
valid-looking SHA, and a clean checkout can provide an override that disagrees
with HEAD.

Required behavior:

- when Git metadata exists, always verify clean state and resolve HEAD;
- an override in a Git checkout must exactly equal resolved HEAD or fail;
- dirty or unverifiable source fails closed in production even when an override
  is present;
- a build-time override is accepted only when Git metadata is absent and its
  deployment provenance/attestation is explicit and validated;
- non-production test mode may return an honest test sentinel, but may not turn
  a supplied or dirty identity into a verified production SHA;
- historical sentinel evidence remains append-only and is not rewritten.

Test clean/no override, clean/matching override, clean/mismatch, dirty/no
override, dirty/matching override, dirty/mismatch, no-Git valid override,
no-Git invalid override, missing identity, and explicit test mode.

### 8. Migration 0007 downgrade evidence is incomplete

Migration 0007 widens uniqueness from event_id + parser_version to event_id +
parser_version + build_hash. After multiple build-hash rows exist for the same
event/version, restoring the narrower uniqueness can fail. The claimed
downgrade-to-base result does not prove a populated compatible data state.

Choose and document one honest behavior:

- provide a deterministic non-destructive downgrade that preserves evidence; or
- preflight and fail closed with a clear incompatibility reason when populated
  evidence cannot fit the older schema.

Never silently delete, merge, rewrite, or select one append-only result. Add a
real PostgreSQL migration test with multiple valid build rows, and report the
supported downgrade state precisely rather than claiming universal success.

### 9. Evidence and state reporting must be internally consistent

BUILD_STATE correctly reports six of nine categories, while checkpoint/handoff
acceptance text omits the multiple-account/LP gap in places. Reconcile every
claim across BUILD_STATE, checkpoint, bundle, handoff, provenance, and test
output. A criterion is PASS only when fresh evidence proves the exact criterion.
Use PASS, FAIL, PARTIAL, NOT TESTED, or DEFERRED_ENVIRONMENTAL_CHECK honestly.

## Mandatory acceptance matrix

The remediation is complete only when fresh evidence demonstrates all of the
following:

1. All nine MASTER_SPEC real-chain fixture categories are authentic,
   independently reviewed, provenance-bound, and parser-validated; otherwise
   Phase 1 remains PARTIAL.
2. Every real fixture has a typed independent semantic oracle covering
   classification, eligibility, perspective, deltas, material amounts, fee,
   confidence rule, failure status, rationale, and evidence.
3. Offline rebuild and validation binds source commit/tree/path/blob, exact
   bytes, container, transforms, license/notice, reviewer evidence,
   expectation, and final output; every tamper class fails.
4. Ambiguous, NFT/non-fungible, LP, multi-account, unproven complex, and failed
   transactions are ineligible; the authentic ambiguous case is UNKNOWN.
5. Simple swaps, multi-hop swaps, transfers, and partial sells retain correct
   canonical results without broadening eligibility.
6. Every Helius HTTP method fully validates every downstream-consumed field and
   writes exactly one terminal usage record for success and every failure.
7. WebSocket readiness requires exact typed acknowledgement, early messages are
   not lost, all lifecycle operations are bounded, quiet healthy sockets do not
   churn, and dead sockets reconcile safely.
8. Production Git identity cannot be overridden around a clean/HEAD check and
   no unverifiable SHA is accepted.
9. Reparse remains parser-artifact-aware, append-only, concurrent-safe,
   restart-safe, and converges to no pending work.
10. Migration downgrade behavior is proven with populated multi-build data and
    never destroys evidence.
11. Direct pagination-boundary proof, commitment monotonicity, finalization,
    disconnect/reconnect A/B, database session isolation, provider accounting,
    and restart/crash regressions remain green.
12. Real PostgreSQL concurrency and migration checks remain green. PostgreSQL
    16 results must not be called PostgreSQL 17 validation.
13. No signer, signing, key/seed handling, live arm, broadcast, mainnet trade,
    paid-provider enablement, Phase 1.5 code, or later-phase work exists.
14. Secret scan is clean and no credential is entered, exposed, or committed.
15. All repository quality gates and the full Phase 1 regression suite pass.

## Required test evidence

Run and record exact commands, exit codes, counts, durations, environment, and
relevant artifact hashes for:

- uv run pytest tests/unit -v
- uv run pytest tests/integration -v
- uv run pytest tests/golden -v
- uv run pytest tests/replay -v
- uv run pytest --cov --cov-report=term-missing
- uv run ruff check .
- uv run ruff format --check .
- uv run mypy
- relevant Alembic upgrade/current/downgrade and populated-data checks
- uv run argus providers probe
- uv run argus providers probe-history
- uv run argus providers usage --provider helius
- offline deterministic uv run argus ingest run --test-mode
- offline fixture rebuild/validation including the full tamper suite
- repeated current-artifact reparse demonstrating convergence
- WebSocket quiet/dead/restart/loss/duplicate/accounting scenarios
- production Git-identity matrix
- a secret scan covering tracked source and generated evidence

Also include a prospective requirement-to-test matrix and a claim ledger mapping
every PASS statement to the exact code path, test name, and fresh output. Run an
audit-of-the-audit before handoff: search for untested branches, skipped tests,
self-generated expected values, mocks that bypass production wiring, stale
evidence, changed category definitions, and contradictions across documents.

Do not claim an unrun test. Environmental failures must be reported with the
exact blocker. Live RPC/WebSocket and PG17 checks may remain explicit
environmental deferrals only where MASTER_SPEC permits; they cannot be called
PASS. Existing PG17_COMPOSE_VALIDATION remains open.

## Checkpoint, bundle, and handoff

At completion:

- keep Phase 1 awaiting orchestrator review and not approved;
- leave last_orchestrator_approved_phase 0 and the Phase 0 approved_commit
  unchanged;
- preserve every earlier checkpoint and bundle as immutable history;
- create:
  - orchestration/checkpoints/phase_1_remediation_5.md
  - orchestration/bundles/phase_1_remediation_5.txt;
- generate the canonical runtime checkpoint/bundle required by MASTER_SPEC;
- use a new unique handoff ID;
- set LAST_ORCHESTRATOR_INSTRUCTION_ID exactly to
  argus-phase-1-remediation-005;
- identify every commit, changed production path, test result, open failure,
  and environmental deferral;
- include the consistent nine-category fixture matrix, requirement traceability
  matrix, claim ledger, and audit-of-audit results;
- state clearly that Phase 1.5 remains blocked;
- verify remote HEAD equals local HEAD and the worktree is clean.

Every commit created during this run must contain exactly one valid terminal
trailer:

ARGUS-INSTRUCTION-ID: argus-phase-1-remediation-005

Then STOP. Do not modify this instruction file. Do not self-authorize Phase 1,
Phase 1.5, or any later work.
