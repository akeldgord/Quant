# ARGUS Orchestrator Instructions

**OWNER: ARGUS ORCHESTRATOR.** The implementation agent must not modify this
file. Execute only the ACTIVE instruction below. MASTER_SPEC.md remains
authoritative except where this instruction explicitly records an orchestrator
approval, clarification, or change-control decision.

---

INSTRUCTION_ID: argus-phase-1-5-remediation-002
ISSUED_AT: 2026-08-31T22:58:28Z
TARGET_COMMIT: 5d85848ab5bff397a192a0868ffcf1077b691706
AUTHORIZED_ACTION: REMEDIATE_PHASE_1_5_INSTRUCTION_SEMANTIC_GATE_ONLY
AUTHORIZED_PHASE: 1.5
APPROVES_PHASE: NONE
STATUS: ACTIVE

## Independent audit disposition

### Predecessor phases

Phase 0 remains orchestrator-approved with disposition:

`PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`

Phase 1 remains orchestrator-approved at
`2fbc566af74832bc6523648f60ba8cb60d98eb31` with disposition:

`PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`

The following environmental checks remain deferred and mandatory before live
readiness, but do not block this remediation:

- `LIVE_HELIUS_RPC_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK`
- `LIVE_HELIUS_WSS_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK`
- `PG17_COMPOSE_VALIDATION = DEFERRED_ENVIRONMENTAL_CHECK`

### Phase 1.5 remediation-round-1 decision

The remediation submission at TARGET_COMMIT was independently audited against
the exact frozen criteria in instruction
`argus-phase-1-5-remediation-001`.

Phase 1.5 remains **NOT APPROVED**. Its disposition is:

`FAIL_REMEDIATION_REQUIRED`

Phase 2 and all later phases remain blocked.

The builder correctly made the authentic Solend withdrawal and xStep stake
ineligible, preserved the historical limitations, separated delta arithmetic
from eligibility reporting, added fresh evidence, kept Phase 1 as the last
approved phase, and did not start Phase 2. The control-plane evidence is fresh,
the two builder commits have valid terminal instruction trailers, and the bundle
contains the checkpoint bytes exactly once.

However, the implemented gate does not satisfy the already-frozen requirement
that automatic eligibility require positive evidence of a **trade/swap
instruction**. It proves only that some instruction invoked a program which is
also capable of swaps. That is not enough because the same programs execute
non-trade instructions.

## Why a second remediation is justified without moving the goalposts

The audit policy normally allows one consolidated remediation. This second pass
is justified because round 1 failed its own exact frozen blocker; this is not a
new product, provenance, or hardening requirement.

The governing frozen requirements are:

1. MASTER_SPEC.md section 21: an ambiguous interpretation must produce
   `NO AUTOMATIC COPY TRADE`.
2. `argus-phase-1-5-remediation-001`, Required remediation item 1:
   one-negative/one-positive balance shape is insufficient unless independent
   transaction evidence positively identifies a supported trade/swap path.
3. The same instruction, item 2: use program identities **and deterministic
   instruction/log discriminators as appropriate**.
4. The same instruction, item 3: unmatched semantics must fail closed.
5. The same instruction's required test 7: eligibility expectations must derive
   from raw instruction evidence, not the parser's own result.

This instruction narrows implementation to closing that unchanged defect. After
this exact blocker is fixed, the existing incomplete acquisition breadth,
43-percent UNKNOWN rate, missing live-provider measurements, and wider protocol
coverage remain non-blocking limitations/backlog. Do not reopen them.

## Frozen finding classification

### SPEC_BLOCKING and SAFETY_OR_INTEGRITY_BLOCKING

**Finding P15-R2-001 — program identity is mistaken for swap-instruction
identity.**

Observed production code:

- `_instruction_program_ids()` extracts only invoked program IDs.
- `_matched_swap_program_id()` intersects those IDs with
  `_SUPPORTED_SWAP_PROGRAM_IDS`.
- `ParsedTransaction.is_copy_eligible` accepts any `SWAP_SIMPLE` balance
  shape when `matched_swap_program_id is not None`.
- Instruction `data`, decoded instruction kind, and program-bound semantic
  discriminator are not checked.
- Log text is ignored.
- The four new synthetic positive fixtures contain an allowlisted
  `programId` but an empty `data` field. They therefore prove only the
  implementation's program-ID assumption, not a real swap instruction.
- `test_every_copy_eligible_row_has_independent_semantic_evidence` checks that
  the parser-produced program ID is in the parser's own registry. That is not
  an independent semantic oracle.

The repository itself contains authentic proof that an allowlisted program is
not synonymous with a swap: `tests/golden/fixtures/real/
real_mainnet_orca_close_position_multi_account.json` invokes the allowlisted
Orca Whirlpool program while its raw logs identify
`DecreaseLiquidity`, `CollectFees`, and `ClosePosition` operations.

Independent audit probe against TARGET_COMMIT:

1. Load the existing
   `tests/golden/fixtures/one_for_one_unsupported_program.json`.
2. Preserve its one-negative/one-positive balance shape.
3. Replace only the instruction program ID with each of the currently
   allowlisted Orca, Raydium, and pump.fun programs.
4. Add explicit non-swap log labels such as `IncreaseLiquidity`,
   `Deposit`, or a non-buy pump.fun instruction.
5. Run the production `parse_transaction()`.

The current parser returns `SWAP_SIMPLE`, a non-null
`matched_swap_program_id`, and `is_copy_eligible=True` in all three cases.
This reproduces the original fail-open defect family inside the new allowlist.

Risk: a lending, staking, liquidity, redemption, claim, create, close, or other
non-trade instruction issued by a program that also supports swaps can still
become an automatic copy signal whenever its net balance shape is one-out/
one-in. That directly violates the frozen no-automatic-copy rule and can create
materially false research signals.

### HARDENING_BACKLOG / permitted limitations

The following do not block this remediation or later Phase 1.5 approval:

- incomplete early-buyer recovery;
- incomplete candidate-wallet history and isolated-fixture coverage;
- the 43-percent UNKNOWN rate on position events that already fail closed;
- lack of live Helius/BigQuery acquisition measurements;
- support for additional programs or swap instruction variants not already
  proven by authentic committed evidence;
- production-scale historical archaeology;
- making Flash or Titan eligible;
- classification of every non-trade position operation into a dedicated
  category.

Do not turn these into remediation requirements.

## Mandatory session start and change control

Before changing code:

1. Run `git status --porcelain`, `git pull --ff-only`, and
   `git log -5 --oneline`.
2. Read, in this exact order:
   - `MASTER_SPEC.md`
   - `docs/BUILD_STATE.md`
   - `docs/DECISION_LOG.md`
   - `orchestration/PROTOCOL.md`
   - `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`
   - `orchestration/AGENT_HANDOFF.md`
   - `orchestration/checkpoints/phase_1_5_remediation_1.md`
   - `orchestration/bundles/phase_1_5_remediation_1.txt`
3. Verify this instruction commit changes only
   `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` and its parent is exactly
   TARGET_COMMIT `5d85848ab5bff397a192a0868ffcf1077b691706`.
4. Verify the worktree is clean and local HEAD equals a freshly fetched remote
   branch HEAD.
5. Verify `current_phase: 1.5`,
   `last_orchestrator_approved_phase: 1`, and
   `awaiting_orchestrator_review: true`.
6. If any target, ancestry, phase, instruction-ID, branch, or trust-state check
   fails, fail closed and STOP.

## Required implementation

Replace the program-only eligibility proof with a program-and-instruction
semantic proof.

### 1. Match the same instruction object

A positive match MUST bind all of the following to one canonical top-level or
inner instruction object:

- the resolved program ID;
- the instruction's raw `data` bytes;
- an exact, versioned swap-instruction discriminator allowed for that same
  program;
- a stable semantic label such as `buy`, `sell`, `route`, or `swap`.

Do not treat "some allowlisted program appeared anywhere in the transaction" as
proof that the transaction executed a trade.

### 2. Use a program-and-discriminator registry

Replace or subordinate `_SUPPORTED_SWAP_PROGRAM_IDS` with one centralized,
versioned, fail-closed registry keyed by program ID and exact binary instruction
discriminator. Each accepted pair must include:

- program ID;
- discriminator bytes and exact discriminator length;
- stable semantic label;
- citation to an authentic committed real swap fixture whose raw instruction
  contains that same pair;
- the fixture path and the exact top-level or inner instruction location used
  to derive it.

Accept only discriminator pairs directly proven by authentic committed swap
evidence. Do not add a pair from memory, program documentation alone, synthetic
fixtures, or a non-swap fixture. A program may have zero accepted pairs until
authentic swap evidence exists.

At minimum, evaluate the four currently reported eligible Phase 1.5 rows:

- pump.fun `Buy`;
- Jupiter V6 route/shared-route instruction actually used by the evidence;
- Orca Whirlpool `Swap`;
- Raydium Liquidity Pool V4 swap instruction.

If a row's authentic raw instruction does not provide enough evidence to define
a safe exact pair, make that row ineligible. Retaining all four eligible rows is
not required; failing closed is required.

### 3. Decode instruction data strictly

Solana raw instruction `data` is base58 text in the committed evidence.
Implement a deterministic, bounded decoder local to the parser or use an
already-declared repository dependency. Do not add a network service.

Required behavior:

- empty, absent, non-string, oversized, non-base58, non-canonical, or too-short
  data produces no semantic match and therefore no copy eligibility;
- malformed semantic evidence must not be converted into a match through
  Python type coercion;
- a `programIdIndex` must be a real integer, not `bool`, and must resolve
  within the canonical key list;
- direct `programId` must be a non-empty string;
- loaded-address-table limitations may remain fail-closed and documented if the
  current parser cannot resolve them;
- registry iteration and match selection must be deterministic.

If no suitable base58 dependency is already declared, implement a small local
strict decoder with a fixed Solana base58 alphabet, a conservative encoded-size
bound, correct leading-zero handling, and canonical round-trip validation.
Do not add a broad Solana SDK solely for this gate.

### 4. Preserve explicit match evidence

Extend `ParsedTransaction` so a positive eligibility decision exposes, at
minimum:

- matched program ID;
- matched semantic label;
- matched discriminator rendered as a stable hex string.

`is_copy_eligible` MUST require all three fields from one valid registry match,
in addition to every existing classification, confidence, decimals, failure,
and ambiguity gate. Any missing or unknown field means ineligible.

Bump `PARSER_VERSION` again because observable output changes. Preserve
`PARSER_BUILD_HASH`, immutable raw evidence, append-only derived outputs, and
deterministic reparse behavior. Do not rewrite historical raw evidence or prior
checkpoint/bundle files.

### 5. Logs are corroboration only

Program log lines such as `Instruction: Swap` may be reported as supporting
evidence, but unbound global log text MUST NOT by itself create eligibility.
A different invoked program can emit arbitrary text. Eligibility must rest on
the same instruction object's program ID plus decoded data discriminator.

### 6. Preserve scope and safe defaults

Do not:

- build full protocol parsers;
- add a Solend/xStep/Orca-position denylist;
- make Flash or Titan eligible without authentic program-and-discriminator
  evidence;
- weaken any existing confidence, decimals, ambiguity, failed-transaction,
  provider, commitment, or live-operation gate;
- change persistent schema unless unavoidable for the already-versioned parser
  output contract;
- begin Phase 2.

## Prospective tests

Add tests that fail TARGET_COMMIT for the intended reason and pass only after
the instruction-level gate exists.

### T1 — allowlisted program plus missing data is ineligible

For every program currently allowed by the registry, construct a one-out/
one-in `SWAP_SIMPLE` balance shape with that program ID but empty or absent
instruction data. Assert no semantic match and
`is_copy_eligible is False`.

Pre-fix failure: the current implementation marks each case eligible from the
program ID alone.

### T2 — allowlisted program plus unknown/non-swap discriminator is ineligible

For each supported program, use the correct program ID with a non-swap or
unknown discriminator. At least one case must copy the authentic Orca
`DecreaseLiquidity`, `CollectFees`, or `ClosePosition` instruction bytes
verbatim from
`real_mainnet_orca_close_position_multi_account.json`. Preserve a
one-out/one-in balance shape for the gate test. Assert no semantic match and no
eligibility.

### T3 — program and discriminator must belong together

Use a recognized discriminator from program A with program B's ID. Assert
ineligible. Use a recognized discriminator with an unknown program. Assert
ineligible.

### T4 — log text cannot grant eligibility

Use a one-out/one-in unsupported or non-swap instruction and add
`Program log: Instruction: Swap`. Assert ineligible.

### T5 — authentic Solend and xStep regressions remain closed

Load the exact committed Solend withdrawal and xStep stake evidence. Assert both
remain ineligible and expose no swap semantic match.

### T6 — authentic supported swaps require exact evidence

For every accepted registry pair, load the cited authentic real swap fixture,
locate the exact instruction object, independently assert its program ID and
decoded discriminator against fixed expected bytes, then assert the production
parser exposes the expected program/label/hex discriminator and eligibility.

Do not derive the expected discriminator by calling the production registry or
production matcher.

### T7 — altered authentic swap evidence fails closed

For each accepted pair, copy the authentic fixture in memory and remove,
truncate, corrupt, or replace the matched instruction data. Preserve its balance
shape. Assert eligibility becomes false.

### T8 — malformed base58 fails closed

Cover empty, wrong type, invalid alphabet, non-canonical encoding, oversized
input, and decoded data shorter than the required discriminator. Assert no
semantic match and no eligibility, with deterministic behavior.

### T9 — existing ambiguous and non-trade cases remain ineligible

Re-run failed, NFT, LP/position, multi-asset, unknown-program,
no-instruction-evidence, Solend, xStep, and authentic Orca close-position cases.
None may become copy eligible.

### T10 — deterministic reparse and version identity

Parse identical canonical input repeatedly and assert byte-for-byte-equivalent
dataclass output, match evidence, and eligibility under the new parser version.
Assert prior parser versions remain distinct in append-only reparse tests.

### T11 — Phase 1.5 oracle is independent

The Phase 1.5 test must compare every eligible row's parser result to a fixed
oracle table written from authentic raw evidence. Each oracle row must name the
file, signature, program ID, semantic label, exact discriminator hex, source
instruction location, and supporting log text if present. The expected table
must not import the production registry or call the production matcher.

## Evidence correction and rerun

Rerun the Phase 1.5 analysis under the corrected parser. The generated result,
new checkpoint, and new bundle must:

- keep delta-arithmetic validation separate from semantic validation;
- report matched program, semantic label, discriminator hex, and source
  instruction location for every eligible row;
- list every `SWAP_SIMPLE` but ineligible row;
- show Solend, xStep, and the new allowlisted-program/non-swap adversarial cases
  as ineligible;
- preserve honest Tests A, B, and D and their limitations unless a reproducible
  measured value changes;
- preserve the original raw evidence bytes;
- record exactly
  `HISTORICAL_DATA_PATH = PASS_WITH_LIMITATIONS` if this blocker is fixed
  and no new category-A/B defect is introduced.

Do not claim full historical completeness, production-scale cost, or broad
protocol support.

## Mandatory validation

Before handoff, run and record:

1. focused program-and-discriminator eligibility tests;
2. all Phase 1 parser/golden-fixture tests;
3. all Phase 1.5 tests and the rerun analysis;
4. all unit/replay tests affected by the parser-version bump;
5. the full repository test suite;
6. Ruff lint and format checks;
7. mypy;
8. the tracked-file secret scan;
9. real-chain fixture validation;
10. migration/integration checks only if schema or persistence behavior changes.

For the independent audit of TARGET_COMMIT, the auditor observed:

- `uv run pytest tests/golden tests/phase_1_5 -q`: 52 passed;
- Ruff lint/format: clean;
- mypy: clean;
- full suite in the auditor environment: 522 passed, 8 skipped, 33 setup
  errors, all caused by the intentionally absent local
  `ARGUS_DB_ADMIN_PASSWORD`. This is an auditor-environment limitation,
  not a code failure and not a new remediation requirement.

Report all skips and environmental limits honestly. Do not request, expose, or
commit credentials. PG16 evidence must never be described as PG17 validation.

## Required checkpoint, bundle, and handoff

Create new immutable evidence files:

- `orchestration/checkpoints/phase_1_5_remediation_2.md`
- `orchestration/bundles/phase_1_5_remediation_2.txt`

Do not overwrite:

- `orchestration/checkpoints/phase_1_5.md`
- `orchestration/bundles/phase_1_5.txt`
- `orchestration/checkpoints/phase_1_5_remediation_1.md`
- `orchestration/bundles/phase_1_5_remediation_1.txt`

The new checkpoint must include:

1. instruction ID, target, implementation commits, final commit, and phase;
2. the exact frozen finding and why round 2 was required;
3. the complete versioned program-and-discriminator registry;
4. an independent derivation/citation for every accepted pair;
5. the real Orca non-swap counterexample and before/after audit-probe result;
6. fixed oracle rows for every eligible Phase 1.5 transaction;
7. Solend/xStep and all T1-T11 results;
8. corrected Phase 1.5 Tests A-D and exact conclusion;
9. parser version/build identity and deterministic reparse proof;
10. all commands, counts, skips, environment, and failures;
11. remaining environmental deferrals and HARDENING_BACKLOG;
12. security/secret state;
13. deviations;
14. explicit STOP pending independent orchestrator audit.

Update `docs/BUILD_STATE.md`, append `docs/DECISION_LOG.md`, and replace
`orchestration/AGENT_HANDOFF.md` with a new handoff. Use a new
`HANDOFF_ID` and exactly:

`LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-1-5-remediation-002`

Keep `last_orchestrator_approved_phase: 1` and the approved Phase 1 commit
unchanged. Do not mark Phase 1.5 approved.

Every implementation-agent commit in this run must use exactly one real terminal
Git trailer recognized by `git interpret-trailers --parse`. Use this as the
sole final paragraph:

`ARGUS-INSTRUCTION-ID: argus-phase-1-5-remediation-002`

Put no paragraph after it.

Push all authorized work, verify local/remote HEAD equality and a clean
worktree, then STOP. Do not modify this instruction file, self-authorize Phase
1.5, begin Phase 2, or perform any other phase.

## Prohibitions preserved

This instruction does not authorize any mainnet trade, canary, transaction
broadcast, signer/private-key/seed access, credential entry or disclosure,
paid-provider upgrade or usage, live arming, threshold relaxation, evidence
rewrite, phase skip, or work outside the remediation above.
