# ARGUS Orchestrator Instructions

OWNER: ARGUS ORCHESTRATOR. The implementation agent must not modify this file.
MASTER_SPEC.md remains authoritative. Execute only the ACTIVE instruction.

INSTRUCTION_ID: argus-phase-3-remediation-004
ISSUED_AT: 2026-09-01T10:18:46Z
TARGET_COMMIT: fb2a3f7d2b75c526d06568ab3708ff85e1c1448d
AUTHORIZED_ACTION: ENFORCE_EXISTING_ACQUISITION_EVIDENCE_BINDING_AT_LOAD_AND_USE
AUTHORIZED_PHASE: 3
APPROVES_PHASE: NONE
STATUS: ACTIVE

## Audit disposition and scope lock

AUDIT_ID: argus-phase-3-remediation-audit-003
DISPOSITION: FAIL_REMEDIATION_REQUIRED

Phase 3 remains unapproved; Phase 4 remains blocked. This is one consolidated,
narrow fourth remediation of the SAME P3-R2 evidence-binding requirement.
Do not re-audit or redesign the accepted phase. The seven-part justification
below is mandatory authority for this exceptional additional round.

Approved phases 0/1/1.5/2 remain unchanged. The honest one-wallet
PHASE_3_CANDIDATE_SAMPLE_BLOCKED result remains accepted and non-blocking.
All previously closed findings remain closed absent concrete regression:
P3-R1, P3-R3, P3-R4, P3-R5, P3-R6a, P3-R6b, P3-R7 and E1.
The original bool("false") defect is now CLOSED. Do not rework its fix.

## Immutable audit identity and evidence

Branch: claude/argus-folder-setup-77ahrk, repository akeldgord/Quant.
Audit target: fb2a3f7d2b75c526d06568ab3708ff85e1c1448d.
Implementation parent: 34080e5e70f88b668af6ca3543e1d1f39145d582.
Pre-work instruction commit: 67c49a562af01e98a5797bc2010fe5c5e6216fa8.
Matching handoff: handoff-0023-phase-3-remediation-3.
Checkpoint/bundle: orchestration/checkpoints/phase_3_remediation_3.md and
orchestration/bundles/phase_3_remediation_3.txt.
Frozen MASTER_SPEC SHA-256:
41f7242c288feec709b1ed72e62c74a1dc5e3b3cd9ad01e9b6e28373d9d14011.

Fresh GitHub reads and a checkout fetched directly from GitHub prove linear
two-commit ancestry, sole terminal trailers, unchanged instructions/spec/
protocol, fresh evidence paths and clean audited checkout. The actual production
checkpoint/bundle validators accept the exact submitted pair. Ruff check,
format check and mypy independently pass. An independent combined unit/golden/
phase_1_5/decoder run passed 656 tests (22 explicitly deselected database-backed
or matched-name tests), exit 0. This is not a full-suite claim. The builder's bundle contains raw
777-test results including 24 acquisition and 14 qualification integration
tests. Those DB-backed results were inspected, not independently rerun: this
audit has no configured approved database credential. This limitation is NOT
a blocker, nor a request for credentials.

## Complete remaining-requirement matrix

| Frozen obligation | Evidence / result | Disposition |
|---|---|---|
| Real wallet/account walks, run identity, per-walk counts, optional boundary | acquisition.py producer and historical_acquisition.py/CLI diff; focused tests and raw output | PASS |
| Strict boolean, duplicate account/signature rejection | manifest_from_dict and six decoder tests | CLOSED |
| Parse/fetch/hash/owner failures explicitly non-HIGH | producer outcomes and assess_wallet_history gap branch; focused test sources | PASS for these producer cases |
| Resolve referenced chain events and derived swaps | loader resolves supplied non-null IDs; existing missing-event/hash tests | PARTIAL: null/missing evidence bypasses checks, P3-R2b |
| Exact raw/parser input set USED for reconstruction | qualification_service.py selects every Swap for wallet/as_of, never restricts to acquired_evidence | FAIL, P3-R2a |
| Conflicting/malformed manifest cannot justify HIGH | missing acquired_evidence defaults to []; contradictory walk status ignored; null derived ID skips verification | FAIL, P3-R2b |
| History/run identity and exact replay | manifest contains run_id and participates in existing history/score identity | PASS; preserve |
| Prior-phase semantics and closed fixes | only additive boundary result fields and narrow source changes; no migrations/scoring/ledger changes | Retain acceptance |
| Candidate fallback, environmental/live gates, fresh evidence | unchanged fallback/deferrals; standard validators pass | Accepted |

## Independent adversarial probes and claim ledger

Production functions were executed offline; database rows were supplied by a
minimal read-only session adapter for the loader probe, not claimed as a real
PostgreSQL run. Expected results came from the frozen requirement, not the code.

1. A valid COMPLETE/enumerated manifest with acquired_evidence=[] plus an
   unrelated nonempty swaps list returns HIGH from assess_wallet_history.
   The production service supplies this very list shape: it independently
   queries ALL Swap rows for wallet_address with first_seen_at <= now.
2. Delete acquired_evidence from that manifest: decoding succeeds, and the
   same assessment returns HIGH. A missing required evidence set becomes empty.
3. Set wallet_walk.status=PARTIAL and transaction_fetch_failures=1 while leaving
   wallet_walk_status=COMPLETE: decoding succeeds and assessment returns HIGH.
4. Supply PARSED evidence referencing a matching real-shaped ChainEvent, but
   derived_swap_id=None: load_verified_acquisition_manifest returns successfully
   WITHOUT any Swap query, and assessment returns HIGH.

These are not speculative provider attacks or optional provenance depth.
They directly exercise missing/conflicting references and successful-walk
blessing of unrelated evidence already forbidden before this implementation.

Claims confirmed: real acquisition producer; boolean fix; preserved raw parse
failure; owner check; boundary threading; fresh raw evidence and closed regressions.
Claim narrowed: "exact raw/parser input set" is recorded, but not enforced at
the reconstruction consumer. "Every malformed input fails closed" is false
for the concrete omissions/conflicts above. No dishonesty is inferred.

## Seven-part no-moving-goalposts justification

| 1. Exact blocker | 2. Classification | 3. Frozen authority | 4. Concrete consequence | 5. Why round 3 missed it | 6. Why not backlog/environmental | 7. Bounded closure |
|---|---|---|---|---|---|---|
| P3-R2a: verified run does not constrain reconstruction's actual swap input | SAFETY_OR_INTEGRITY_BLOCKING | remediation-002 forbids a successful walk blessing unrelated swaps; remediation-003 tasks 2/4 require exact raw/parser input set USED for reconstruction and verified existing parsed evidence | unrelated or multiple parser-version rows can change positions/samples/score under a run that did not name them | manifest was enriched, but qualification_service was not wired to consume its derived references; tests check producer/load, not complete acquisition-to-score flow | ordinary current service behavior can materially falsify research; no external dependency | bind LIVE_ACQUISITION_WALK reconstruction to its verified derived input IDs; preserve other source modes and all closed scoring logic |
| P3-R2b: missing evidence/null derived reference/conflicting walk summary passes validation | SPEC_BLOCKING | remediation-003 task 5 and focused tests explicitly require missing required fields, malformed/unresolved references and conflicting identities to fail closed | empty or internally partial/unparsed evidence can still justify HIGH | checks validate selected literals and only supplied non-null refs; omitted arrays and null derived refs bypass them; duplicate status copies are not reconciled | executable failure of exact frozen acceptance, not new arbitrary validation depth | require existing mandatory fields and genuine-evidence refs, reconcile duplicate walk fields, and reject these demonstrated conflicts; no new provider/crypto/provenance standard |

## Ordered implementation — one batch only

0. Begin with git status, git pull --ff-only, git log -5; read canonical files
   in PROTOCOL order and this audit's checkpoint/bundle. Verify this instruction
   is a single instruction-only commit directly on TARGET_COMMIT. STOP on
   mismatch, dirty overlap, changed protected files or unexpected movement.

1. Complete existing manifest/load validation in history_reconstruction.py and
   acquisition.py. Require acquired_evidence and associated_token_accounts to
   be explicitly present arrays; an explicitly empty array remains legitimate.
   PARSED and ALREADY_KNOWN_VERIFIED must name a non-null resolving derived swap.
   Validate that named swap's wallet/event/parser artifact matches the evidence.
   For already-known evidence, record the selected swap's actual parser version
   and build hash, rather than null metadata. Preserve exact historical artifact
   choice; do not silently reparse all history with today's artifact.
   Validate manifest/run wallet and cutoff identity against their authoritative
   rows. Reconcile wallet_walk_status with wallet_walk.status and each account's
   status with its walk.status. A failed fetch or unsatisfied supplied boundary
   must not coexist with trusted COMPLETE. Reject the demonstrated missing/null/
   conflicting cases with a typed verification error before assessment.

2. Wire qualification_service.py's LIVE_ACQUISITION_WALK branch to use only the
   verified run's named genuine derived swap rows for history, ledger, sample
   counts, metrics and scores. Apply the existing as-of and economic-time filter
   to that selected set and preserve its exclusion reasons. Preserve failed/
   rejected evidence as recorded gaps, not usable economic rows. Extra wallet
   Swap rows not named by this run must not silently enter it or inherit its
   completeness. A new acquisition run can explicitly bind a changed input set;
   do not modify the old run. STREAM_FORWARD_ONLY behavior remains unchanged.
   Ensure one raw event is not counted multiple times merely because multiple
   historical parser-artifact rows exist. This is input identity selection,
   not a scoring/threshold/ledger redesign.

3. Keep writes append-only and transactionally atomic. No new schema is required
   unless the existing JSONB cannot represent the fields already specified.
   Old sparse/unverified run records must remain preserved and fail closed
   rather than being relabeled verified. No historical evidence rewriting.

## Focused acceptance tests

Use deterministic fake provider plus existing disposable PostgreSQL harness.
Exercise the complete producer -> persisted run -> verified load -> production
reconstruct-and-score path, not only helper return values.

- Valid complete wallet/account acquisition references all used events/parsed
  rows; same verified run replays without duplicate score/position/tier.
- Seed unrelated same-wallet parsed rows, then acquire a different exact set.
  Only named rows affect history, positions, sample counts, all windows and
  score. With a genuinely empty acquired set, unrelated DB rows do not become
  HIGH usable history; retain the established zero-evidence UNKNOWN behavior.
- Two parser-artifact rows for one raw event: explicitly select/bind one,
  reconstruct it once; changing the bound artifact/input yields an honest new
  run/history/score identity without rewriting past decisions.
- Missing acquired_evidence or associated_token_accounts is rejected; explicit
  empty arrays remain accepted when actual acquisition evidence is empty.
- PARSED/ALREADY_KNOWN_VERIFIED with null, nonexistent or wrong-event/wallet/
  artifact derived swap is rejected; existing valid references still pass.
- Conflicting top-level/per-walk status, failed-fetch-plus-COMPLETE, and
  unsatisfied-boundary-plus-COMPLETE cannot justify HIGH.
- Existing false/string/numeric boolean, duplicates, owner, parse/fetch failure,
  wrong wallet, future cutoff, hash mismatch and boundary cases remain passing.

Run the existing required commands and capture raw outputs/exit status:
uv run pytest tests/unit/test_phase3_wallet_qualification.py -q
uv run pytest tests/unit/test_orchestrator_watch.py -q
uv run pytest tests/integration/test_wallet_acquisition.py -v
uv run pytest tests/integration/test_phase3_wallet_qualification.py -q
uv run pytest tests/integration/test_migrations.py -q
uv run pytest tests/golden tests/replay tests/phase_1_5 -q
uv run pytest tests/integration -q
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run alembic current
uv run argus fixtures validate-real-chain
Also run the existing changed-file secret scan without printing secrets.
Honest allowed environmental deferrals do not require endless retries.

## Evidence, handoff and STOP

Create NEW files only:
orchestration/checkpoints/phase_3_remediation_4.md
orchestration/bundles/phase_3_remediation_4.txt

Include exact raw command output, complete two-finding closure matrix, preserved
closed findings/deferrals and valid terminal markers. Verify the actual production
validators and exact embedded checkpoint bytes. Update BUILD_STATE and append
DECISION_LOG normally; no self-approval. Fresh handoff must identify:

LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-3-remediation-004

Every builder commit including hash-fill must end with the sole real trailer:

ARGUS-INSTRUCTION-ID: argus-phase-3-remediation-004

Push and verify clean remote/local equality, then STOP for independent review.
When these two exact manifestations pass with regressions, approve Phase 3 and
authorize immediate Phase 4; do not add optional hardening gates.

## Preserved prohibitions and deferrals

LIVE_HELIUS_RPC_VALIDATION, LIVE_HELIUS_WSS_VALIDATION, PG17_COMPOSE_VALIDATION
and BQ_PUBLIC_DATASET_ACCESS remain deferred under their already-recorded
procedures/owners. They are not reopened here. No real provider calls are
required. No Phase 4, trading/canary/live arming, signing/key/seed access,
credential entry/disclosure, paid-provider use/upgrade, threshold relaxation,
candidate expansion, evidence rewrite, or phase skipping is authorized.
