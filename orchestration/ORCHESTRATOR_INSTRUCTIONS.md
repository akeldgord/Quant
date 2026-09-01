# ARGUS Orchestrator Instructions

OWNER: ARGUS ORCHESTRATOR. The implementation agent must not modify this file.
Execute only the ACTIVE instruction below. MASTER_SPEC.md remains authoritative
except for explicit orchestrator decisions recorded here.

---

INSTRUCTION_ID: argus-phase-3-remediation-003
ISSUED_AT: 2026-09-01T08:45:00Z
TARGET_COMMIT: ad21304a2f9fedd3c11a39a8d840ce577e0afe58
AUTHORIZED_ACTION: CLOSE_FINAL_FROZEN_PHASE_3_ACQUISITION_EVIDENCE_DEFECT
AUTHORIZED_PHASE: 3
APPROVES_PHASE: NONE
STATUS: ACTIVE

## Disposition

AUDIT_ID: argus-phase-3-remediation-audit-002
DISPOSITION: FAIL_NARROW_REMEDIATION_REQUIRED

Phase 3 is not approved and Phase 4 remains blocked. This is a narrowly
justified third remediation for the one remaining frozen P3-R2 defect. Do not
rework closed findings or add optional hardening.

The accepted PHASE_3_CANDIDATE_SAMPLE_BLOCKED outcome remains accepted. Phase
0, 1, 1.5 and 2 approvals and all environmental deferrals remain unchanged.

## Independent focused audit

Audited GitHub commit ad21304a2f9fedd3c11a39a8d840ce577e0afe58,
implementation parent 5735e0bd314314004add920fbb8cf6fd40d43db3, handoff
handoff-0022-phase-3-remediation-2, checkpoint
orchestration/checkpoints/phase_3_remediation_2.md and its exact bundle.
Instruction trailers and linear ancestry pass. MASTER_SPEC remains at frozen
SHA-256 41f7242c288feec709b1ed72e62c74a1dc5e3b3cd9ad01e9b6e28373d9d14011.

Independent results:
- 654 unit/golden/phase_1_5 tests passed.
- The focused Phase 3 and watcher subset passed: 208 tests.
- ruff, format and mypy passed; checkpoint and bundle production validators
  accepted the exact submitted pair.
- PostgreSQL-backed tests were not independently rerun because this audit
  environment has no approved database credential. The builder's raw bundle
  evidence is accepted for those paths; this environmental limit is not a
  blocker.

Closed and not to be reopened absent a concrete regression: P3-R1 common as-of
filter/exclusion reason; P3-R3 deterministic ledger and quote-unit safety;
P3-R4 windows; P3-R5 realization ordering; P3-R6a migration preservation;
P3-R6b score/history identity and historical replay; P3-R7 checkpoint marker;
E1 raw command evidence. The one-wallet candidate-sample stop remains honest
and accepted.

## Remaining blocker

P3-R2 remains SAFETY_OR_INTEGRITY_BLOCKING and SPEC_BLOCKING in two directly
related manifestations:

1. The persisted acquisition manifest is only a summary assertion. It stores
   status, enumeration, account pubkey/mint/owner, provider, gaps and a synthetic
   string such as `wallet_acquisition:<wallet>:<time>`. It does not store or
   verify the required run/as-of identity inside the manifest, per-address page
   and transaction counts, transaction signatures, chain-event/payload hashes,
   parser outcomes, swap/event references, expected boundary state, or the exact
   raw/parser input set used for reconstruction. `load_verified_acquisition_manifest`
   verifies only row existence, wallet_id and observation_cutoff, then trusts the
   JSONB summary. A successful address walk can therefore be marked COMPLETE/HIGH
   even when an acquired transaction raised in parsing, or when an already-known
   chain event was skipped without proving it supplies the required parsed input.
   That is the exact frozen prohibition on using a successful walk to bless an
   unrelated/incomplete swaps fragment.
2. `manifest_from_dict` uses `bool(data["token_accounts_enumerated"])`.
   The independently executed production probe decodes the string `"false"` as
   True. This directly fails remediation-002's explicit acceptance sentence
   "string false is not accepted as true."

No other blocker remains.

## Seven-part no-moving-goalposts justification for remediation round 3

| Part | Exact justification |
|---|---|
| 1. Exact blocker | The produced/loaded acquisition run does not bind or verify its exact acquired raw/parser evidence, and its persisted decoder accepts string `"false"` as true. |
| 2. Classification | SAFETY_OR_INTEGRITY_BLOCKING plus SPEC_BLOCKING. |
| 3. Frozen authority | Remediation-002 P3-R2 required page/transaction evidence references, exact raw/parser input set, verified coverage/evidence refs, no successful-walk blessing of unrelated swaps, and explicitly forbade `bool("false")`. MASTER_SPEC section 34 requires evidence-derived completeness. |
| 4. Concrete consequence | HIGH history confidence and qualification eligibility can be justified despite missing/unparseable/unbound transaction evidence; a malformed persisted boolean can falsely claim enumeration. This can materially falsify current Phase 3 research conclusions. |
| 5. Why round 2 did not close it | Round 2 added a real acquisition call and immutable row, but tests prove calls and row existence only. They do not assert exact evidence binding, parse failures/already-known missing parser outputs, strict JSON types, or reference resolution. |
| 6. Why not backlog/environmental | Both failures are present in deterministic production code and one is reproduced offline. Neither depends on live RPC, paid data or PostgreSQL version. They violate explicit frozen acceptance, not optional provenance depth. |
| 7. Bounded closure | Add strict typed validation and exact evidence references to the existing acquisition-run path only, with focused fake-provider/Postgres tests and regressions. No new provider, score, phase, threshold, candidate, or live requirement is authorized. |

## Required implementation

Amend only the existing P3-R2 acquisition evidence path and minimal append-only
schema/model/CLI wiring needed for it:

1. Persist a typed acquisition-run manifest that binds the run ID, wallet ID and
   address, observation cutoff, provider set, algorithm/parser versions, and
   every wallet/token-account walk. For each walk persist address, account
   pubkey/owner/mint where applicable, terminal status, known gaps, expected
   oldest boundary and whether satisfied when supplied, pages fetched,
   signatures seen and transaction-fetch failures.
2. Persist the exact acquired transaction/raw/parser input set: at minimum each
   acquired signature and slot, resolved chain_event ID and payload hash,
   parser outcome/version/build identity, and the derived swap/event references
   used by reconstruction. An equivalent normalized child table is acceptable
   if the manifest commits to its complete immutable identity. References must
   be machine-resolvable and verified on load, not a synthetic free-form string.
3. Generate the run ID before building the manifest so subsequent history and
   score provenance can identify the exact acquisition run. Bind the
   WalletHistoryQuality snapshot to that run identity, directly or in its
   strictly validated manifest, so two genuinely different runs are not
   silently indistinguishable.
4. Treat transaction fetch or parse failure as explicit preserved evidence and
   a known gap that prevents HIGH. For an already-known signature, verify the
   existing raw payload/hash and required parser-derived evidence belongs to
   this wallet and input set; otherwise parse safely through the normal path or
   record a non-HIGH gap. Never use event existence alone as proof.
5. Make manifest decoding fail closed. `token_accounts_enumerated` must be an
   actual JSON boolean; statuses and required identifiers must be valid typed
   values; account owner must match the acquired wallet under the existing
   ChainProvider contract; duplicate/conflicting account or evidence identities
   must not justify HIGH. Reject malformed or unresolved references rather than
   coercing them.
6. Preserve the existing no-boundary semantics. Where a typed expected boundary
   is supplied to this ordinary service/CLI path, pass it to
   `acquire_historical_transactions` and persist the boundary/result. Do not
   invent a boundary when none is independently known.

Required focused tests:
- persisted string `"false"`, numeric truthy values and missing required fields
  fail verification and cannot produce HIGH or eligibility;
- complete wallet + enumerated-empty accounts binds an exact empty evidence set
  honestly; complete wallet + complete accounts binds every address/signature/
  raw/parser/derived reference and loads successfully;
- parser exception, transaction fetch failure, and pre-existing event without
  matching parser-derived evidence are explicit non-HIGH gaps with raw evidence
  preserved;
- wrong wallet/run, future observation cutoff, wrong owner, unresolved event,
  payload-hash mismatch and conflicting/duplicate references fail closed;
- expected-boundary supplied/unsatisfied/satisfied and no-boundary regressions;
- exact replay reuses the same verified run; a genuinely changed run/evidence
  set creates distinct history/score identity even when numeric results match;
- all previously passing remediation-002 focused, Phase 3, migration, unit,
  integration, golden/replay, lint, format, type and fixture checks remain pass.

Create fresh evidence only at:
- orchestration/checkpoints/phase_3_remediation_3.md
- orchestration/bundles/phase_3_remediation_3.txt

Include raw command output and exit codes, a concise requirement/evidence matrix,
database migration preservation evidence, changed-file secret scan, accepted
deferrals, and exact STOP. Update BUILD_STATE/DECISION_LOG and handoff normally.
The handoff must say:

LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-3-remediation-003

Every builder commit must end with exactly one terminal trailer and nothing
after it:

ARGUS-INSTRUCTION-ID: argus-phase-3-remediation-003

Push, verify clean remote/local equality, and STOP for independent audit.

## Prohibitions and non-goals

No Phase 4, live/mainnet/canary trading, signing/broadcast, key/seed access,
credential entry or disclosure, paid provider use/upgrade, live arming,
threshold relaxation, candidate expansion, historical evidence rewrite, or
phase skipping. Do not reopen closed findings or promote HARDENING_BACKLOG.

