# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0015-phase-1-5-remediation-1
UTC_TIMESTAMP: 2026-08-31T22:33:07Z
CURRENT_COMMIT: 3aa61b4d220c3211e4dca1ca46b18b1ab510376e
CURRENT_PHASE: 1.5
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-1-5-remediation-001
CHECKPOINT_PATH: orchestration/checkpoints/phase_1_5_remediation_1.md
BUNDLE_PATH: orchestration/bundles/phase_1_5_remediation_1.txt
TEST_STATUS: 9 targeted eligibility-gate tests passed; 46/46 Phase 1 parser/golden-fixture tests passed (up from 36); 6/6 Phase 1.5 tests passed (up from 4); full repository suite 563/563 passed, 0 failed, 0 unexplained skipped (real PostgreSQL 16); ruff clean; mypy clean
WORKING_TREE: clean (verified via `git status --porcelain` before this commit)
ORCHESTRATOR_REVIEW_REQUIRED: whether this one-finding remediation (the positive semantic proof gate closing the Solend/xStep false-eligibility defect) is sufficient to approve Phase 1.5, or whether the two limitations already disclosed in `orchestration/checkpoints/phase_1_5.md` and carried forward unchanged here (unproven data-acquisition breadth beyond 1 recovered early buyer; the 43% parser `UNKNOWN` rate on real lending/yield-position activity) still require resolution first. See checkpoint sections G and J for the full disposition.

## Work completed

Executed orchestrator instruction `argus-phase-1-5-remediation-001` in
full: an independent audit rejected the Phase 1.5 submission as
`FAIL_REMEDIATION_REQUIRED` on one SPEC_BLOCKING/SAFETY_OR_INTEGRITY_BLOCKING
finding, scoped narrowly to that one defect.

1. **Verified the defect directly before fixing it.** `git stash`ed only
   `src/argus/parsing/generic_parser.py` and confirmed the pre-fix
   parser genuinely returned `classification='SWAP_SIMPLE'`,
   `is_copy_eligible=True` for the real Solend withdrawal transaction
   named by the audit — not assumed from the instruction's own claim.
2. **Implemented a deterministic positive semantic proof gate.** A new,
   centrally versioned `_SUPPORTED_SWAP_PROGRAM_IDS` registry (Jupiter
   Aggregator V6, Raydium Liquidity Pool V4, Orca Whirlpool, pump.fun),
   each entry independently cross-checked against this project's own
   already-hand-reviewed permanent golden-fixture evidence before being
   added (never trusted from memory). `ParsedTransaction.
   is_copy_eligible` now additionally requires positive instruction-
   level evidence (`matched_swap_program_id is not None`) — a narrow
   allowlist, not a Solend/xStep-specific denylist, so the same defect
   class cannot recur for the next unsupported program without one new,
   cited registry entry, never a denylist patch.
3. **Both named false positives are now ineligible**; all 4 permanent
   golden real-chain fixtures already marked eligible before this round
   remain eligible, independently re-verified against the new gate.
4. **Reran the Phase 1.5 analysis** under the corrected parser
   (`PARSER_VERSION` bumped to `generic_balance_delta_v2`) and
   restructured its evidence to report delta-arithmetic agreement
   (28/28, unchanged) strictly separately from semantic eligibility
   validation (4/28 copy-eligible, each independently cited) — the two
   claims are never conflated anywhere in this round's evidence.
5. **`HISTORICAL_DATA_PATH = PASS_WITH_LIMITATIONS`** — unchanged
   disposition value, now resting on a corrected foundation.

Full per-item detail, the complete 14-item required-contract
disposition, and every command actually run:
`orchestration/checkpoints/phase_1_5_remediation_1.md`.

## Important findings

- The fix generalizes exactly as far as independently verified evidence
  supports, and no further: two other genuinely swap-shaped Phase 1.5
  transactions (`suppl_02_flash_swap2.json`'s Flash swap,
  `suppl_10_titan_swap_with_fees.json`'s Titan swap) remain honestly
  ineligible this round, since neither transaction's own instructions
  invoke a program in the 4-entry registry — not treated as a
  regression (neither was previously verified as genuine by this
  project) and not waved through to make the "genuine swaps stay
  eligible" story look cleaner than the evidence actually allows.
  Tracked as `HARDENING_BACKLOG`, not a blocker.
- Updating the 4 synthetic "known genuine swap" golden fixtures
  (`sol_to_token`, `token_to_sol`, `token_to_usdc`, `partial_sell`) to
  carry the same positive instruction evidence a real swap transaction
  would was itself required by the fix, not optional: under the new
  rule, their prior bare balance-shape claim no longer held any more
  evidentiary weight than the real evidence it needed to match.
- `PARSER_VERSION`'s bump from `_v1` to `_v2` incidentally collided with
  two pre-existing hardcoded version-string literals used as
  "hypothetical different version" placeholders in
  `tests/unit/test_reconciliation.py` and `tests/replay/test_replay.py`
  — both updated (mechanical renames only, no logic change) so they
  keep testing what they claim to test rather than silently comparing a
  string against itself.
- No existing golden/real-chain fixture's committed bytes changed
  (`argus fixtures validate-real-chain` still reports all 12 `ok`); no
  `src/argus` schema/persistence change was made, per the instruction's
  explicit statement that none was requested.
- `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is unchanged — still the
  orchestrator's `argus-phase-1-5-remediation-001` instruction,
  `STATUS: ACTIVE`. `last_orchestrator_approved_phase` remains `1` —
  this remediation approves no phase.
- All new commits this run carry the sole final trailer paragraph
  `ARGUS-INSTRUCTION-ID: argus-phase-1-5-remediation-001`, verified via
  `git interpret-trailers --parse` before push.

## Failures or limitations

- **Two genuinely swap-shaped Phase 1.5 transactions (Flash, Titan)
  remain ineligible** for lack of positive registry evidence for their
  specific venues — disclosed as `HARDENING_BACKLOG`, not claimed as
  resolved.
- The two limitations already disclosed in `orchestration/checkpoints/
  phase_1_5.md` are unchanged and carried forward, not re-litigated per
  the instruction's explicit scope limit: unproven data-acquisition
  breadth beyond 1 recovered early buyer; the disclosed 43% parser
  `UNKNOWN` rate on real lending/yield-position activity.
- `LIVE_HELIUS_RPC_VALIDATION`/`LIVE_HELIUS_WSS_VALIDATION`/
  `PG17_COMPOSE_VALIDATION`/`BQ_PUBLIC_DATASET_ACCESS` remain
  `DEFERRED_ENVIRONMENTAL_CHECK`, unchanged.

## Deferred checks

- The two `PASS_WITH_LIMITATIONS` limitations carried forward from
  `phase_1_5.md` (see `ORCHESTRATOR_REVIEW_REQUIRED` above).
- `LIVE_HELIUS_RPC_VALIDATION`/`LIVE_HELIUS_WSS_VALIDATION`/
  `PG17_COMPOSE_VALIDATION`/`BQ_PUBLIC_DATASET_ACCESS`.
- Extending the positive-swap-program registry to cover Flash/Titan (or
  any other genuinely verified venue) if a future use case requires it
  — `HARDENING_BACKLOG`, not required to close this remediation.

## Exact next action requested from orchestrator

Review this remediation's evidence
(`orchestration/checkpoints/phase_1_5_remediation_1.md` and
`orchestration/bundles/phase_1_5_remediation_1.txt`) against instruction
`argus-phase-1-5-remediation-001`'s required contract, and resolve
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
