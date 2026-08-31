# ARGUS Orchestrator Instructions

**OWNER: ARGUS ORCHESTRATOR.** The implementation agent must not modify this
file. Execute only the ACTIVE instruction below. MASTER_SPEC.md remains
authoritative except where this instruction explicitly adds stricter
acceptance detail.

---

INSTRUCTION_ID: argus-phase-1-remediation-004
ISSUED_AT: 2026-08-31T12:25:32Z
TARGET_COMMIT: a589e15c29937b140ae96bdfc2d75de62a9109c2
AUTHORIZED_ACTION: REMEDIATE_PHASE_1_ROUND_4_ONLY
AUTHORIZED_PHASE: 1
APPROVES_PHASE: NONE
STATUS: ACTIVE

## Independent audit disposition

- Phase 0 remains approved as
  `PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`.
- `PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK` remains open
  and blocks live readiness, not this remediation.
- Phase 1 remediation round 3 is **not approved**. Its checkpoint correctly
  reports `STATUS: PARTIAL`, but its 17/18 scoring overstates fixture
  coverage and several runtime acceptance claims.
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

### 1. Real-chain coverage is six of nine categories, not seven

The submitted `real_mainnet_ambiguous_multi_asset` fixture is not an
ambiguous-parser fixture. The parser classifies it `TRANSFER_IN` with
confidence `1.000`. It therefore does not exercise the required ambiguous
transaction path, does not prove `UNKNOWN` handling, and does not prove that
an ambiguous real transaction cannot create a live-copy signal.

Correct all checkpoint, handoff, BUILD_STATE, provenance, and test claims.
The genuinely supported real-chain categories are currently:

- simple transfer;
- SOL to token;
- token to SOL;
- token to USDC;
- multi-hop swap;
- partial sell.

The still-open categories are:

- genuinely ambiguous transaction that the parser classifies `UNKNOWN` and
  marks ineligible;
- multiple token-account / LP-style action;
- failed on-chain transaction with non-null `meta.err`.

Keep the structurally multi-asset DCA-close fixture as an additional useful
fixture, but do not count it as the ambiguous category. Do not rename a
confident result as ambiguous.

Search further only where evidence is credible. If any category remains
unavailable, keep it NOT TESTED/PARTIAL. Do not weaken the category semantics
or fabricate evidence.

### 2. Imported upstream provenance is not byte-for-byte reproducible

Independent review fetched
`0xjeffro/tx-parser@475b1ebff79a2f41ec966919fdefa01f11f6c5d7`
`solana/data/pumpfun_buy_0.json`. The upstream file is a single-element JSON
array, while ARGUS stores only the unwrapped object. Parsed payloads match, but
the provenance record:

- has no upstream Git blob SHA;
- has no SHA-256 of the exact upstream file bytes;
- does not preserve the exact upstream bytes;
- records `sanitization_transform` as “canonicalized JSON formatting only,”
  omitting the array-unwrapping transform;
- sets `original_sha256` from the already-unwrapped import input, not the
  exact upstream file.

The same defect applies to the six new `0xjeffro/tx-parser` fixtures. The
older fixtures also lack an upstream blob identity.

Extend the provenance schema and importer/validator to preserve and verify:

- exact upstream repository, commit, path, and Git blob SHA;
- SHA-256 of the exact upstream file bytes before any transformation;
- source container/envelope format;
- an ordered, deterministic transform manifest, including single-element
  array extraction and JSON-RPC `result` extraction;
- SHA-256 after every transform and of the final sanitized fixture;
- license identity and required attribution/notice;
- independent semantic expectation evidence.

Either preserve the exact upstream bytes in a content-addressed source area or
provide an equivalent offline-verifiable artifact. The validator must rebuild
the sanitized fixture from those exact source bytes and fail on any source,
transform, provenance, or output mismatch. Re-import all current real-chain
fixtures through this corrected path. Add tamper tests for upstream bytes,
blob SHA, source hash, transform order, path/commit, and sanitized output.

### 3. Golden expectations are generated by the parser under test

`import_real_chain_fixture()` runs the current parser and writes that output
as the expected classification/confidence. Validation then reruns the same
parser and compares it with its own saved result. This detects later drift but
cannot detect an existing misclassification. The confidently classified
“ambiguous” fixture demonstrates the circularity.

Separate observed output from independently reviewed expected output:

- importer may record the parser's observed output, but must not promote it to
  expected truth;
- expected canonical classification, eligibility, asset deltas, and material
  amounts must come from independent transaction semantics/manual review or a
  trusted upstream interpretation;
- provenance must record the evidence and reviewer method;
- fixture validation fails when observed parser output disagrees with the
  independent expectation;
- an ambiguous fixture must assert `UNKNOWN`, low/appropriate confidence, and
  `is_copy_eligible == false`;
- failed transactions must assert `UNKNOWN` and ineligible regardless of
  apparent balance fields.

Add category-specific tests. A test that only checks filenames, hashes, or
self-generated expectations is insufficient.

### 4. Helius contract validation is still shallow and WebSocket acks are not matched

The HTTP accounting boundary is improved, but “complete nested validation” is
still overstated:

- `get_transaction()` accepts a non-object `transaction` and does not
  validate required nested message/signature/meta fields used downstream;
- `get_token_accounts()` accepts any list elements while returning
  `list[dict[str, Any]]`;
- `get_signature_statuses()` does not fully validate slot/error field types;
- Python booleans may pass integer checks;
- token-account responses remain provider-shaped dictionaries outside the
  adapter instead of canonical typed models.

Define the minimum complete contract required by every downstream consumer.
Validate it inside the accounted operation and return canonical immutable
models for separately consumed token-account metadata. Raw
`getTransaction` evidence may remain raw only after all fields needed for
safe persistence/parsing are validated.

Also fix `HeliusWebSocketStream.open_subscription()`: it accepts any message
with an integer `result`, without requiring JSON-RPC version and exact
request-ID equality or rejecting a simultaneous/error response. A mismatched
ack can mark the stream ready. Require a valid, exact matching acknowledgement
before readiness. Add bounded connect/send/ack timeouts so a half-open
subscription cannot wedge forever.

Test malformed nested objects and element types, bool-as-int cases, null
transaction, mismatched JSON-RPC IDs, missing/wrong JSON-RPC version, error
responses, unrelated acks, timeout/cancellation, and cleanup. Every HTTP
failure must still create exactly one correct non-OK usage record.

### 5. Reparse selection ignores the new build identity

`SqlParseAttemptRecorder.events_pending_at_version()` filters only by
`parser_version`. If an event already has SUCCESS/UNKNOWN under that version,
a changed `build_hash` is never selected, even though round 3 claims that a
new build identity creates a new attempt.

Make the pending/reparse identity explicit and deterministic. At minimum,
selection must distinguish the current executable parser artifact using
`parser_version + build_hash`; document whether config/spec changes also
require a new parse. Git commit remains audit metadata and must not cause
unbounded reparsing merely because documentation changed.

The derived `swaps` uniqueness/versioning must support the same identity. A
new parser build cannot append an honest new attempt while silently retaining
an incompatible old derived row as the only canonical result. Either version
derived rows by parser artifact identity or fail closed when source hash
changes without a parser-version bump. Do not update old rows.

Add real PostgreSQL and restart tests for:

- same version + same build = idempotent;
- same version + changed build = deterministic new attempt or explicit
  version-mismatch failure;
- changed parser version = new attempt and derived row;
- old SUCCESS does not suppress a required new-artifact attempt;
- failures remain retryable;
- concurrent reparse cannot create contradictory duplicate results.

### 6. The historical-version CLI claim is false

`argus ingest reparse --parser-version OLD` queries events pending under
`OLD`, but executes only the currently imported parser and records the
current `PARSER_VERSION`. Re-running the same command can select the same old
events forever. The CLI cannot execute historical parser code merely from a
string label.

Choose one honest design:

- current-artifact-only: remove/reject arbitrary historical target versions;
  allow an explicit source-attempt selector while clearly recording that the
  current artifact performed the reparse; or
- artifact registry: load a real immutable parser artifact matching the
  requested version/hash and verify it before execution.

Never claim an old parser ran when only the current parser exists. Prove a
bounded sweep makes forward progress and becomes empty when repeated under the
same output identity.

### 7. Production git identity can silently become a sentinel

`git_commit_sha()` returns `GIT_COMMIT_UNAVAILABLE`, and the production
parse path accepts it as a valid non-empty identity. This does not satisfy
exact point-in-time git identity.

Production ingestion/reparse must obtain a validated immutable commit from the
checkout or a build-time deployment value and fail closed if neither is
available. Require a full validated SHA and reject dirty/unverifiable source
unless an explicit non-production test mode is active. Test missing git,
invalid override, dirty checkout, clean checkout, and valid build-time
override. Existing pre-round-3 sentinel rows remain honest historical
evidence and must not be rewritten.

### 8. A missing finalization source is a misconfiguration, not a clean sweep

`sweep_finalization()` returns `ok=True, promoted=0` when no
`RecentEventSource` is wired. In the real manager this capability is required;
treating its absence as a clean zero result can hide dead finalization wiring.

Return `ok=False` with an explicit configuration reason when the capability
is missing. Preserve clean zero only for a correctly wired source with no
eligible candidates or no new promotions. Add manager and restart tests.

## Mandatory acceptance tests

Independently demonstrate at least:

1. fixture coverage is reported as exactly supported, with no confident
   classification counted as an ambiguous fixture;
2. every imported fixture preserves exact upstream bytes, upstream Git blob,
   source hash, deterministic transforms, final hash, and license evidence;
3. all committed fixtures rebuild offline from their preserved source evidence;
4. independently reviewed expected outcomes, not parser self-output, drive
   golden PASS/FAIL;
5. real ambiguous and failed fixtures are UNKNOWN/ineligible, or remain
   explicitly NOT TESTED/PARTIAL;
6. every Helius HTTP method rejects all malformed fields used downstream and
   records exactly one correct terminal usage outcome;
7. token-account metadata crossing the adapter boundary is canonical and typed;
8. WebSocket readiness requires exact matching JSON-RPC acknowledgement and
   bounded lifecycle timeouts;
9. reparse selection and derived-row versioning are parser-artifact-aware;
10. repeated reparse under one identity terminates with no pending work;
11. historical-version CLI behavior is truthful and deterministic;
12. production git identity is exact and fails closed when unavailable/dirty;
13. missing finalization-source wiring is a typed visible failure;
14. pagination direct-boundary proof and all round-3 regression tests remain
    passing;
15. the disconnect/reconnect A/B scenario still canonicalizes each exactly once;
16. real PostgreSQL session isolation, commitment serialization, migrations,
    and append-only grants remain passing;
17. no signing, signer, private-key, seed-phrase, live-arm, or broadcast path
    exists;
18. secret scan is clean;
19. no paid-provider feature is enabled;
20. no Phase 1.5 or later-phase code is started.

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
- `uv run argus providers probe`
- `uv run argus providers probe-history`
- `uv run argus providers usage --provider helius`
- offline deterministic `uv run argus ingest run --test-mode`
- corrected offline fixture rebuild/validation command;
- repeated current-artifact reparse demonstrating convergence.

Do not claim an unrun test. PostgreSQL 16 may support code tests but must not
be described as PostgreSQL 17 validation. Live RPC/WebSocket and PG17 checks
may remain explicit environmental deferrals. Missing authentic fixture
categories must remain explicit and may not be relabeled or self-certified.

## Checkpoint, bundle, and handoff

At completion:

- keep Phase 1 awaiting orchestrator review and not approved;
- leave `last_orchestrator_approved_phase: 0` and the Phase 0
  `approved_commit` unchanged;
- preserve every earlier checkpoint and bundle as immutable history;
- create:
  - `orchestration/checkpoints/phase_1_remediation_4.md`
  - `orchestration/bundles/phase_1_remediation_4.txt`;
- generate the canonical runtime checkpoint/bundle required by MASTER_SPEC;
- use a new unique handoff ID;
- set `LAST_ORCHESTRATOR_INSTRUCTION_ID` exactly to
  `argus-phase-1-remediation-004`;
- identify every commit, exact test result, open failure, and deferral;
- state clearly that Phase 1.5 remains blocked;
- verify remote HEAD equals local HEAD and the worktree is clean.

Every commit created during this run must contain exactly one valid terminal
trailer:

`ARGUS-INSTRUCTION-ID: argus-phase-1-remediation-004`

Then STOP. Do not modify this instruction file. Do not self-authorize Phase
1, Phase 1.5, or any later work.
