# ARGUS Orchestrator Instructions

**OWNER: ARGUS ORCHESTRATOR.** The implementation agent must not modify this
file. Execute only the ACTIVE instruction below. MASTER_SPEC.md remains
authoritative except where this instruction explicitly records an orchestrator
approval, clarification, or change-control decision.

---

INSTRUCTION_ID: argus-phase-2-remediation-001
ISSUED_AT: 2026-09-01T01:03:18Z
TARGET_COMMIT: 6bde9fdf6d56c38517854700e8863d9103e831aa
AUTHORIZED_ACTION: REMEDIATE_FROZEN_PHASE_2_BLOCKERS_ONLY
AUTHORIZED_PHASE: 2
APPROVES_PHASE: NONE
STATUS: ACTIVE

## Independent audit disposition

Phase 0 remains approved as `PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`.
Phase 1 remains approved at `2fbc566af74832bc6523648f60ba8cb60d98eb31`
as `PASS_WITH_DEFERRED_ENVIRONMENTAL_VALIDATION`. Phase 1.5 remains approved at
`c3148cc191de58ecab9b11cd05291cc8ffe45455` as `PASS_WITH_LIMITATIONS`.

Phase 2 at exact audited remote commit
`6bde9fdf6d56c38517854700e8863d9103e831aa` is **not approved**. Phase 3 and
all later phases remain blocked.

The audit accepted the Phase 2 schema breadth, point-in-time append model,
reference-price ledger, versioned winner thresholds, discovery-contamination
field, negative-control schema, CLI entry points, real fixture provenance,
explicit replay labeling, role grants, and custody/live-trading prohibitions.
Do not redesign those accepted areas unless a change is strictly required by
the blockers below.

## Frozen audit findings

These are violations of the Phase 2 gate frozen in `argus-phase-2-001`; they
are not new product requirements.

| ID | Classification | Frozen requirement | Independently verified defect |
|---|---|---|---|
| P2-R1 | SPEC_BLOCKING + SAFETY_OR_INTEGRITY_BLOCKING | P2-T1; authentic on-chain mint validation must reject a valid-shaped non-mint | `validate_from_account_info()` accepts a 165-byte legacy SPL token-account payload as `VALID` whenever bytes 44/45 resemble mint decimals/initialized state. The submitted test describes a 165-byte account but only supplies 70 bytes, so it never exercises the false-positive path. |
| P2-R2 | SPEC_BLOCKING | Required implementation 4 and P2-T8 | No Phase 2 historical provider adapter/acquisition path was implemented. The CLI accepts already-collected files only. The claimed P2-T8 tests do not exercise pagination, cursor cycles, duplicate pages, premature empty pages, caps, timeout, rate limit, or provider usage accounting. |
| P2-R3 | SPEC_BLOCKING + SAFETY_OR_INTEGRITY_BLOCKING | Required implementation 5, MASTER_SPEC section 33, P2-T5 | Early-buyer ordering is not deterministic across processes: candidates tied on `(slot, signature)` retain iteration order from a Python `set`; varying `PYTHONHASHSEED` reverses the submitted real fixture's sequence. The same extractor promotes the known pump.fun bonding-curve reserve PDA into `wallets`, `early_buyers`, and discovery events even though it is not a meaningful buyer wallet. “Tag, do not delete” applies to actual wallets with risk tags, not program reserve/state accounts. |
| P2-R4 | SPEC_BLOCKING + SAFETY_OR_INTEGRITY_BLOCKING | Required implementation 6 and P2-T7 | Winner evaluation discards `market_state_confidence`; LOW/UNKNOWN/incomplete snapshots can create a winner milestone and archaeology trigger. An independent 12x probe produced `MAJOR_WINNER` even though the evaluation surface had no confidence field. |
| P2-R5 | SPEC_BLOCKING | Required implementation 6 and P2-T7 | The prospective watcher creates a trigger row, but there is no wired automatic trigger consumer/executor. The demonstration manually passes the trigger ID to a second CLI command. The frozen instruction defined automatic archaeology as creation **and execution** of the bounded research job inside Phase 2. |
| P2-R6 | SPEC_BLOCKING | P2-T10 | The submitted tests cover duplicate trigger delivery and transaction rollback, but do not cover crash/restart around durable run creation or output commit. `run_archaeology()` creates RUNNING state and all outputs in one caller transaction; a process crash rolls the whole attempt away, losing the required attempt provenance rather than leaving a recoverable/terminal state. |
| P2-R7 | SPEC_BLOCKING | CORE financial arithmetic and Phase 2 persistence | New Phase 2 `supply_raw` and `amount_raw` columns use signed PostgreSQL `BIGINT`, which cannot represent the full Solana/SPL unsigned 64-bit range. Exact raw integer persistence must accept at least `2^64 - 1` without overflow or float conversion. |
| P2-R8 | SPEC_BLOCKING | Required implementation 2 and P2-T1 | Mint-validation evidence handling does not fail closed on conflicting matching token-balance entries and persists `chain_time=None` and `commitment=None` even when the committed transaction evidence contains usable block/slot/time provenance. |

No additional hardening idea may be made blocking in this remediation. Fix and
prove exactly P2-R1 through P2-R8, then stop.

## Mandatory session start and change control

Before changing code:

1. Run `git status --porcelain`, `git pull --ff-only`, and
   `git log -5 --oneline`.
2. Read, in exact order: `MASTER_SPEC.md`, `docs/BUILD_STATE.md`,
   `docs/DECISION_LOG.md`, `orchestration/PROTOCOL.md`, this file,
   `orchestration/AGENT_HANDOFF.md`, `orchestration/checkpoints/phase_2.md`,
   and `orchestration/bundles/phase_2.txt`.
3. Verify the instruction-only commit containing this file has parent exactly
   `TARGET_COMMIT`, changes only this file, and local HEAD equals the freshly
   fetched remote branch HEAD.
4. Verify Phase 2 is awaiting orchestrator review and Phase 2 is not marked
   orchestrator-approved. On any mismatch, fail closed and STOP.

## Required remediation

### 1. Correct mint-account discrimination and evidence provenance

- Use exact, vetted SPL Token and Token-2022 account-type discrimination. A
  legacy 165-byte token account, multisig account, malformed extension layout,
  uninitialized mint, wrong owner, and valid-shaped arbitrary payload must not
  validate as a mint. Do not infer account type merely from “length >= 82” and
  bytes 44/45.
- For token-balance evidence, evaluate every matching pre/post entry. Conflicting
  decimals, program IDs, malformed values, failed/unsupported evidence, or
  other contradictions must return a non-VALID result with a reason.
- Persist chain time/slot reference and commitment/finality semantics whenever
  the evidence supports them. Preserve the distinct validation source; do not
  relabel fixture evidence as a live account-info call.
- Add adversarial tests containing a genuine 165-byte legacy token-account
  shape with byte 45 set to 1, valid legacy and Token-2022 mint shapes, malformed
  Token-2022 extensions, and conflicting pre/post token-balance entries.

### 2. Add the actual historical acquisition/provider boundary

- Implement a typed, provider-neutral Phase 2 historical acquisition service
  over the existing Phase 1 `ChainProvider`/provider contracts. It must acquire
  address signatures and transactions through bounded pagination, normalize
  them into the archaeology input type, and feed the existing archaeology
  service. Keep the offline evidence-file path for deterministic demonstrations.
- Explicitly handle and persist: multiple pages, duplicate item/page,
  immediately repeated cursor, multi-step cursor cycle, premature empty/short
  page before an expected boundary, maximum-page/cap exhaustion, timeout, rate
  limit, malformed response, transaction-fetch failure, and partial success.
  None may be reported complete without direct completion evidence.
- Real provider calls must flow through existing provider usage/cost accounting.
  Tests may use a deterministic fake provider and fake usage recorder; no live
  credential and no paid provider is authorized.
- Wire this acquisition service through an ordinary CLI/service command, not a
  test-only helper.

### 3. Make early-buyer output deterministic and semantically meaningful

- Define a total stable ordering including an explicit final wallet-address (or
  other immutable evidence-derived) tie-breaker. Results must be identical
  across separate processes with different `PYTHONHASHSEED` values, input/page
  permutations, and replay.
- Separate raw net-positive token-account observations from qualified buyer
  wallets. Use transaction signer/account metadata and canonical instruction
  roles or an equivalent evidence-grounded classifier so a known pool, curve,
  reserve, vault, or program-state account does not become a wallet candidate.
  Unknown/unresolved ownership must remain explicit and fail closed for wallet
  candidacy; do not erase its raw evidence.
- Preserve the rule that a genuine wallet tagged possible deployer, insider,
  bundler, funder-related, or bot is tagged rather than deleted.
- Re-run the real pump.fun fixture: the signer/dev-buy may remain a tagged buyer;
  the known bonding-curve reserve PDA must not be inserted as a buyer wallet or
  discovery candidate. Update the demonstration honestly.

### 4. Enforce confidence and complete the automatic trigger loop

- Carry snapshot confidence/completeness into winner evaluation. LOW, UNKNOWN,
  NULL-confidence, incomplete, missing-price, missing-liquidity, zero-liquidity,
  stale, or otherwise non-reliably-tradable observations must not create a
  milestone or trigger. Persist explicit reason/status for ignored observations
  where the existing schema permits; do not silently reinterpret them.
- Preserve the versioned baseline and no-rewrite behavior for already-recorded
  milestones.
- Add a bounded, restart-safe production service/CLI path that claims pending
  archaeology triggers and executes the corresponding archaeology run without
  a human manually copying a trigger ID into another command. Exactly-once
  canonical output must be enforced by database identities; duplicate delivery
  is expected and safe.
- A deterministic replay test must cross a milestone, create a trigger, invoke
  the normal trigger processor, and produce/terminalize the linked archaeology
  run automatically. Assert zero trade, signal, order, signer, broadcast, paid-
  provider, and phase-advance side effects.

### 5. Make archaeology durable across crashes and preserve exact raw integers

- Refactor the archaeology state machine so run/claim provenance is durably
  visible before output work, terminalization is durable, and restart can
  deterministically recover or fail-and-retry a stale RUNNING/CLAIMED attempt.
  Do not leave a silent wedge and do not lose the attempt merely because the
  worker process exits.
- Test injected crash/failure at least: after durable run creation/claim, during
  extraction, after output insertion but before terminalization, and during
  terminal commit. After restart, assert one terminal canonical result, no
  duplicated buyer/discovery output, preserved failed/stale attempt evidence,
  and correct trigger consumption.
- Add a forward migration from current head (do not rewrite accepted history)
  so every Phase 2 raw on-chain quantity can represent the full unsigned 64-bit
  domain. Use an exact integer-capable PostgreSQL type such as `NUMERIC(20,0)`
  with range/integrality checks, and keep Python values as `int`. Add boundary
  round-trip tests for 0/1, `2^63`, and `2^64 - 1`, plus rejection of negative,
  fractional, and `2^64` values where the field is u64.

## Frozen remediation acceptance tests

The new submission must include and pass, at minimum:

1. **R1 mint discriminator:** the independent 165-byte token-account false
   positive now fails closed; valid legacy/Token-2022 mints pass; malformed,
   wrong-owner, non-mint, conflicting-entry, unavailable, and missing evidence
   never persist `mint_validated=True`; available chain/commitment provenance is
   stored.
2. **R2 provider matrix:** one deterministic contract suite covers every P2-T8
   case listed above and asserts exact terminal completeness/status, evidence
   references, and usage records. A source-text assertion or caller-supplied
   `--partial` flag alone is not proof.
3. **R3 deterministic meaningful buyers:** subprocess/hash-seed tests prove
   byte-identical ordering. The real fixture produces no reserve-PDA wallet
   candidate while preserving the raw observation and genuine signer/dev-buy.
4. **R4 confidence:** a 100x LOW/UNKNOWN/incomplete peak creates no milestone or
   trigger; an otherwise identical accepted-confidence observation produces the
   expected one-time milestone and trigger; replay/restart stays idempotent.
5. **R5 automatic execution:** normal production wiring consumes a newly
   generated trigger into one linked terminal archaeology run without manual
   trigger-ID transport.
6. **R6 crash matrix:** injected crashes at all required boundaries recover
   deterministically with preserved attempt provenance and no duplicate output.
7. **R7 u64 persistence:** migration from 0008/current head, zero-to-head,
   downgrade/re-upgrade per repository convention, and exact u64 boundary
   round trips pass on the available PostgreSQL substitute.
8. **Regression:** all original P2-T1 through P2-T11 tests remain, are corrected
   where they overstated coverage, and pass; Phase 1.5 semantic/golden tests,
   full repository suite, Ruff lint/format, mypy, secret scan, and real-chain
   fixture validation pass or carry only previously approved environmental
   deferrals.

The audit environment lacked `ARGUS_DB_ADMIN_PASSWORD`, so its independent
integration rerun could not start; this is not a new deferral for the builder.
The builder must run the database tests in its already-demonstrated local
PostgreSQL environment and report exact commands/counts.

## Evidence and handoff

Create fresh immutable files (do not overwrite Phase 2 evidence):

- `orchestration/checkpoints/phase_2_remediation.md`
- `orchestration/bundles/phase_2_remediation.txt`

The checkpoint must map P2-R1 through P2-R8 to exact code, tests, and fresh
command output; include adversarial before/after proofs, migration and crash
matrices, provider failure matrix, updated real-token demonstration, all test
counts/skips/failures, environmental limits, security/cost confirmation, and an
explicit STOP. The bundle must contain the checkpoint bytes verbatim and the
review evidence required by PROTOCOL.md.

Update `docs/BUILD_STATE.md`, append `docs/DECISION_LOG.md`, and replace
`orchestration/AGENT_HANDOFF.md` with a new matching handoff. Do not mark Phase
2 orchestrator-approved. Use a new `HANDOFF_ID` and exactly:

`LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-2-remediation-001`

Every implementation-agent commit must end with exactly one real terminal Git
trailer:

`ARGUS-INSTRUCTION-ID: argus-phase-2-remediation-001`

Push, verify clean worktree and exact local/remote HEAD equality, then STOP.

## Prohibitions preserved

This instruction does not authorize Phase 3, a phase skip, mainnet trade,
canary, quote intended for execution, transaction signing or broadcast,
signer/private-key/seed access, credential entry/disclosure, paid-provider
upgrade or use, live arming, threshold relaxation, evidence rewrite, or any
work outside the frozen Phase 2 remediation above. Claude must not modify this
instruction file or self-authorize Phase 2 or any later phase.
