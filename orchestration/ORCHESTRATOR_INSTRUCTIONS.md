# ARGUS Orchestrator Instructions

**OWNER: ARGUS ORCHESTRATOR.** The implementation agent must not modify this
file. Execute only the ACTIVE instruction below. MASTER_SPEC.md remains
authoritative except where this instruction explicitly records an orchestrator
approval, clarification, or change-control decision.

---

INSTRUCTION_ID: argus-phase-1-5-remediation-001
ISSUED_AT: 2026-08-31T21:59:13Z
TARGET_COMMIT: b68e37393370c7f9f3eb8860fecdaaa3f9c28696
AUTHORIZED_ACTION: REMEDIATE_PHASE_1_5_FALSE_COPY_ELIGIBILITY_ONLY
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

### Phase 1.5 decision

The Phase 1.5 submission at TARGET_COMMIT was independently audited against the
frozen Phase 1.5 gate. The feasibility evidence otherwise supports
`HISTORICAL_DATA_PATH = PASS_WITH_LIMITATIONS`: the submission uses real
historical Solana identities and preserved raw transactions, reports the severe
early-buyer and candidate-wallet coverage limitations honestly, checks 28
account-level balance-delta interpretations, and records measured local resource
usage plus transparent scaling assumptions.

Phase 1.5 is **NOT APPROVED** yet. Its current disposition is:

`FAIL_REMEDIATION_REQUIRED`

Phase 2 and all later phases remain blocked.

This is the single consolidated Phase 1.5 remediation pass contemplated by the
frozen-gate policy. The remediation is limited to the concrete blocker below.
Do not add unrelated hardening, new providers, new historical-data architecture,
or Phase 2 work.

## Frozen finding classification

### SPEC_BLOCKING and SAFETY_OR_INTEGRITY_BLOCKING

The audited production parser marks at least two authentic non-trade position
operations as `SWAP_SIMPLE` with confidence 1.0 and
`is_copy_eligible = true` solely because each transaction has one negative and
one positive asset delta:

1. `wallet_05_solend_withdraw_all.json` contains Solend
   `Withdraw Obligation Collateral and Redeem Reserve Collateral` instruction
   evidence.
2. `suppl_09_xstep_full_stake_ix.json` contains xStep `Stake` instruction
   evidence.

These are not swaps. Treating a lending withdrawal/redemption or staking
operation as an automatically copy-eligible swap violates MASTER_SPEC section
21's requirement that ambiguous interpretations produce no automatic copy
trade. It also creates materially false historical trade signals and a direct
future copy-safety risk. A one-out/one-in balance shape is not positive evidence
that a swap occurred.

The Phase 1.5 cross-validation currently verifies account-level delta arithmetic
only. It does not independently verify the semantic classification or copy
eligibility of every row, so it cannot rebut these false positives.

### HARDENING_BACKLOG / permitted limitations

The following do not block this remediation or Phase 1.5 approval:

- incomplete early-buyer recovery;
- incomplete candidate-wallet history and the isolated-fixture nature of the
  available historical sample;
- high `UNKNOWN` rate for position events that already fail closed;
- lack of live Helius or BigQuery acquisition measurements;
- broader per-protocol semantic coverage beyond the positive evidence needed
  for currently supported copy-eligible swaps;
- production-scale historical archaeology.

Keep these items accurately documented as limitations, deferrals, or backlog.
Do not turn them into mandatory work in this remediation.

## Mandatory session start and change-control checks

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
   - `orchestration/checkpoints/phase_1_5.md`
   - `orchestration/bundles/phase_1_5.txt`
3. Verify this instruction commit touches only
   `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` and its parent is exactly
   TARGET_COMMIT `b68e37393370c7f9f3eb8860fecdaaa3f9c28696`.
4. Verify the worktree is clean and local HEAD equals a freshly fetched remote
   branch HEAD.
5. Verify durable state still has Phase 1 as the last orchestrator-approved
   phase and Phase 1.5 awaiting review. Do not mark Phase 1.5 approved.
6. If any target, ancestry, branch, instruction-ID, or trust-state check fails,
   fail closed and report it. Do not bypass watcher or protocol checks.

## Required remediation

Implement a deterministic **positive semantic proof gate** for automatic copy
eligibility.

Required behavior:

1. Balance shape alone is insufficient. A transaction with exactly one negative
   and one positive asset delta MUST NOT be copy eligible unless independent
   transaction evidence positively identifies a supported trade/swap path.
2. Determine positive evidence from canonical raw transaction material already
   available to the parser, including top-level and inner program identities
   and deterministic instruction/log discriminators as appropriate.
3. Centralize and version the supported trade-evidence policy or registry so the
   eligibility decision is auditable and deterministic. Unknown, unsupported,
   or unmatched semantics must preserve their research evidence but fail closed
   with `is_copy_eligible = false`.
4. Do not implement only a negative denylist for Solend and xStep. That would
   leave the same defect for the next unknown lending, staking, LP, redemption,
   or position program.
5. Do not build full protocol parsers for every Solana program. This remediation
   requires a narrow positive allowlist/proof gate for copy eligibility, not a
   production historical parser expansion.
6. Genuine supported swap fixtures may remain copy eligible only when the
   positive semantic gate proves a supported trade path and all existing
   confidence/decimal/ambiguity conditions also pass.
7. The Solend withdrawal/redemption and xStep stake fixtures MUST be ineligible.
   Their research classification may remain an explicitly documented,
   unverified balance-shape classification, or may become `UNKNOWN`; either is
   acceptable if deterministic and never copy eligible.
8. Bump the parser/versioned build identity because observable parser eligibility
   output changes. Preserve immutable raw evidence, append-only derived-output
   semantics, and deterministic reparse behavior. Do not rewrite historical raw
   evidence.
9. Do not weaken confidence thresholds, ambiguity handling, decimal checks,
   provider gates, or any other existing safety control.

## Required tests

Add prospective regression tests that fail before the fix and pass after it.
At minimum prove:

1. The authentic Solend withdrawal/redemption fixture is not copy eligible.
2. The authentic xStep stake fixture is not copy eligible.
3. A one-negative/one-positive transaction from an unknown or unsupported
   program is not copy eligible.
4. Known genuine swap/trade golden fixtures remain eligible only when their
   canonical raw evidence satisfies the positive semantic gate.
5. Existing ambiguous, failed, NFT, LP/position, incomplete-decimal, or
   otherwise ineligible cases remain ineligible.
6. Reparse of identical canonical input under the new parser version is
   deterministic.
7. Every row that Phase 1.5 reports as copy eligible has an independently stated
   semantic expectation derived from raw logs/program/instruction evidence, not
   from the parser's own output.

The tests must exercise production parser and eligibility code. Mocks may test
boundaries but cannot be the only proof for the two authentic false-positive
fixtures or for retained genuine-swap eligibility.

## Evidence corrections and rerun

Rerun the Phase 1.5 analysis under the corrected parser and update the new
remediation evidence so that:

- account-level balance-delta agreement is reported separately from semantic
  classification/eligibility validation;
- no text claims that 28 balance-delta agreements prove 28 semantic
  classifications;
- each copy-eligible row lists the independent raw semantic evidence supporting
  eligibility;
- the Solend withdrawal/redemption and xStep stake are explicitly shown as
  ineligible;
- Test A, Test B, Test D, the real input identities, and the honest historical
  limitations are preserved unless a reproducible rerun changes a measured
  value;
- the conclusion remains exactly one MASTER_SPEC value. If no additional
  blocking defect is introduced and the false eligibility is fixed, the
  expected conclusion is
  `HISTORICAL_DATA_PATH = PASS_WITH_LIMITATIONS`.

Do not claim that the Phase 1.5 sample proves full historical completeness or
production-scale cost. Do not use live credentials or paid services to improve
the result.

## Mandatory validation

Before handoff, run and record the exact commands and results for:

1. targeted tests for the positive semantic eligibility gate;
2. all Phase 1 parser/golden-fixture tests;
3. all Phase 1.5 tests and the rerun analysis;
4. the full repository test suite;
5. Ruff lint and format checks;
6. mypy;
7. the tracked-file secret scan;
8. migration/integration checks only if the authorized implementation changes
   persistent schema or persistence behavior; no schema change is requested.

Report environmental skips and failures honestly. Do not represent a missing
credential, unavailable PG17 image, or unavailable live provider as a test PASS.

## Required checkpoint, bundle, and handoff

Create new immutable evidence files:

- `orchestration/checkpoints/phase_1_5_remediation_1.md`
- `orchestration/bundles/phase_1_5_remediation_1.txt`

Do not overwrite prior checkpoints or bundles.

The new checkpoint must include:

1. exact instruction ID, target commit, implementation commits, and final commit;
2. the frozen finding classification above and its disposition;
3. implementation design and exact positive semantic evidence policy;
4. before/after results for both authentic false-positive fixtures;
5. the complete copy-eligible-row semantic oracle and raw evidence basis;
6. corrected separation of delta arithmetic validation from semantic validation;
7. rerun Tests A-D and exact `HISTORICAL_DATA_PATH` conclusion;
8. all commands and results, including full-suite counts and skips;
9. parser version/build identity and deterministic reparse evidence;
10. remaining limitations, environmental deferrals, and
    `HARDENING_BACKLOG`;
11. secret/security state;
12. deviations, if any;
13. explicit STOP pending independent orchestrator audit.

Update `docs/BUILD_STATE.md`, append `docs/DECISION_LOG.md`, and replace
`orchestration/AGENT_HANDOFF.md` with a new handoff. The handoff must use a new
`HANDOFF_ID` and exactly:

`LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-1-5-remediation-001`

Phase 1.5 may be implementation-agent-complete and awaiting review, but
`last_orchestrator_approved_phase` MUST remain `1`.

Every implementation-agent commit in this run must carry exactly one real
terminal Git trailer recognized by `git interpret-trailers --parse`. Use this
as the sole final paragraph:

`ARGUS-INSTRUCTION-ID: argus-phase-1-5-remediation-001`

Do not put `Co-Authored-By`, `Claude-Session`, or any other paragraph after
that terminal trailer.

Push all authorized work, verify remote/local HEAD agreement and a clean
worktree, then STOP. Do not modify this instruction file, self-authorize Phase
1.5, begin Phase 2, or perform any other phase.

## Prohibitions preserved

This instruction does not authorize any mainnet trade, canary, transaction
broadcast, signing/private-key/seed access, credential entry or disclosure,
paid-provider upgrade or usage, live arming, threshold relaxation, evidence
rewrite, phase skip, or work outside the remediation above.
