# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0016-phase-1-5-remediation-2
UTC_TIMESTAMP: PLACEHOLDER_FILLED_IN_SECOND_COMMIT
CURRENT_COMMIT: PLACEHOLDER_FILLED_IN_SECOND_COMMIT
CURRENT_PHASE: 1.5
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-1-5-remediation-002
CHECKPOINT_PATH: orchestration/checkpoints/phase_1_5_remediation_2.md
BUNDLE_PATH: orchestration/bundles/phase_1_5_remediation_2.txt
TEST_STATUS: 95/95 golden parser tests passed (up from 46); 7/7 Phase 1.5 tests passed (up from 6); full repository suite 613/613 passed, 0 failed, 0 unexplained skipped (real PostgreSQL 16); ruff clean; mypy clean
WORKING_TREE: clean (verified via `git status --porcelain` before this commit)
ORCHESTRATOR_REVIEW_REQUIRED: whether this second remediation (the program-and-instruction-discriminator semantic gate closing finding P15-R2-001) is sufficient to approve Phase 1.5, or whether the standing limitations already disclosed across `phase_1_5.md`/`phase_1_5_remediation_1.md` and carried forward unchanged here (unproven data-acquisition breadth; the 43% parser `UNKNOWN` rate; the honest new disclosure that suppl_13_titan_swap_with_fees_2.json becomes ineligible under the stricter gate) still require resolution first. See checkpoint sections H and K for the full disposition.

## Work completed

Executed orchestrator instruction `argus-phase-1-5-remediation-002` in
full: an independent audit rejected round 1's remediation as
`FAIL_REMEDIATION_REQUIRED` on one SPEC_BLOCKING/SAFETY_OR_INTEGRITY_BLOCKING
finding (`P15-R2-001`), scoped narrowly to that one defect.

1. **Reproduced the defect directly against `TARGET_COMMIT`'s real code
   before fixing it.** Loaded `TARGET_COMMIT`'s actual
   `generic_parser.py` bytes into a separate module and called
   `parse_transaction()` on 6 representative adversarial probes
   (mirroring the instruction's own Orca/Raydium/pump.fun + non-swap-log
   audit probe, extended to all 4 registered programs plus a
   cross-program discriminator-reuse case) -- all 6 genuinely returned
   `is_copy_eligible=True` under the pre-fix code, not assumed from the
   instruction's own claim.
2. **Implemented a program-AND-instruction-discriminator gate.** Replaced
   `_SUPPORTED_SWAP_PROGRAM_IDS` with `_SWAP_INSTRUCTION_REGISTRY`: each
   accepted pair binds a program ID to an exact instruction discriminator,
   both required to come from the SAME canonical instruction object as
   the transaction's own decoded `data`. A new strict, local, bounded
   base58 decoder (`_decode_base58_strict`) fails closed on anything
   absent, non-string, oversized, outside the fixed alphabet, or
   non-canonical -- no repository dependency already declared a base58
   codec (checked), and no broad Solana SDK was added.
3. **Every registry pair independently derived from authentic evidence.**
   All 4 accepted pairs (Jupiter V6 `shared_accounts_route`, Raydium LP V4
   `swap_base_in`, Orca Whirlpool `swap`, pump.fun `buy`) were derived by
   decoding the cited fixture's own raw instruction `data` at the exact
   named location -- never from memory, documentation, a synthetic
   fixture, or a non-swap fixture. The real Orca `DecreaseLiquidity`/
   `CollectFees`/`ClosePosition` discriminators are proven absent from
   the registry; `DecreaseLiquidity`'s bytes are replayed verbatim in a
   new test, per the instruction's explicit citation requirement.
4. **Honest disclosure, not smoothed over.** `suppl_13_titan_swap_
   with_fees_2.json`, eligible under round 1's program-only check,
   correctly becomes ineligible: its actual Raydium invocation's
   discriminator is `0x10`, not the registered `swap_base_in` (`0x09`).
   The instruction explicitly permits this ("Retaining all four eligible
   rows is not required; failing closed is required").
5. **All 11 required test categories (T1-T11) implemented and passing**,
   including T11's fixed, hand-written Phase 1.5 oracle that does not
   import the production registry or call the production matcher --
   correcting the exact defect the round-2 audit found in the prior
   version of that test.
6. **`HISTORICAL_DATA_PATH = PASS_WITH_LIMITATIONS`** — unchanged
   disposition value, now resting on a corrected foundation.

Full per-item detail, the complete registry citation table, and every
command actually run:
`orchestration/checkpoints/phase_1_5_remediation_2.md`.

## Important findings

- The fix generalizes exactly as far as independently verified evidence
  supports, and no further: `suppl_13_titan_swap_with_fees_2.json`'s
  actual Raydium instruction variant (tag `0x10`) is NOT added to the
  registry from this round's own observation of it alone, since no
  independent citation proves it is genuinely a swap instruction --
  extending coverage to it is `HARDENING_BACKLOG`, not done this round.
- `_SWAP_INSTRUCTION_REGISTRY`'s Orca Whirlpool `swap` discriminator
  (`f8c69e91e17587c8`) is cited from a Phase 1.5 evidence file
  (`orchestration/phase_1_5/evidence/raw/suppl_11_dflow_swap_with_fee.json`,
  an inner instruction), not the permanent real-chain corpus -- no
  genuine Orca `swap` instruction is committed there. This is the same
  kind of already-committed, already-license-vetted evidence this
  project has used throughout; the citation makes the source explicit.
- `PARSER_VERSION`'s bump from `_v2` to `_v3` incidentally collided with
  one pre-existing hardcoded version-string literal
  (`tests/unit/test_reconciliation.py`) — updated (mechanical rename
  only, no logic change); `tests/replay/test_replay.py`'s round-1
  `_v9` placeholder was reconfirmed to still not collide and was left
  unchanged.
- `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is unchanged — still the
  orchestrator's `argus-phase-1-5-remediation-002` instruction,
  `STATUS: ACTIVE`. `last_orchestrator_approved_phase` remains `1` —
  this remediation approves no phase.
- All new commits this run carry the sole final trailer paragraph
  `ARGUS-INSTRUCTION-ID: argus-phase-1-5-remediation-002`, verified via
  `git interpret-trailers --parse` before push.

## Failures or limitations

- **`suppl_13_titan_swap_with_fees_2.json` becomes ineligible** under
  the stricter gate — disclosed as `HARDENING_BACKLOG`, not claimed as
  resolved or hidden by omission.
- The limitations already disclosed in `orchestration/checkpoints/
  phase_1_5.md` and `phase_1_5_remediation_1.md` are unchanged and
  carried forward, not re-litigated per the instruction's explicit scope
  limit: unproven data-acquisition breadth beyond 1 recovered early
  buyer; the disclosed 43% parser `UNKNOWN` rate on real lending/
  yield-position activity.
- `LIVE_HELIUS_RPC_VALIDATION`/`LIVE_HELIUS_WSS_VALIDATION`/
  `PG17_COMPOSE_VALIDATION`/`BQ_PUBLIC_DATASET_ACCESS` remain
  `DEFERRED_ENVIRONMENTAL_CHECK`, unchanged.

## Deferred checks

- The limitations carried forward from `phase_1_5.md`/
  `phase_1_5_remediation_1.md` (see `ORCHESTRATOR_REVIEW_REQUIRED` above).
- `LIVE_HELIUS_RPC_VALIDATION`/`LIVE_HELIUS_WSS_VALIDATION`/
  `PG17_COMPOSE_VALIDATION`/`BQ_PUBLIC_DATASET_ACCESS`.
- Extending the registry to cover Titan's actual Raydium instruction
  variant (or any other genuinely verified venue/instruction) if a
  future use case requires it — `HARDENING_BACKLOG`, not required to
  close this remediation.

## Exact next action requested from orchestrator

Review this remediation's evidence
(`orchestration/checkpoints/phase_1_5_remediation_2.md` and
`orchestration/bundles/phase_1_5_remediation_2.txt`) against instruction
`argus-phase-1-5-remediation-002`'s required contract, and resolve
whether Phase 1.5 is now approvable. If accepted, write the next
`ACTIVE` instruction into `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`
(`TARGET_COMMIT` pinned to the exact commit named in this handoff) to
authorize Phase 2 or further Phase 1.5 work. Phase 2 remains forbidden
until then. Until a new instruction exists, the watcher (if running)
takes no action beyond logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** unchanged from prior handoffs — if you
cloned/fetched this branch before 2026-08-30T22:35 UTC, re-clone or
`git fetch --all && git reset --hard origin/claude/argus-folder-setup-77ahrk`
rather than merging/rebasing the old (pre-rewrite) history.
