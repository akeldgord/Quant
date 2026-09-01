# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0018-phase-2-remediation-1
UTC_TIMESTAMP: 2026-09-01T02:17:23Z
CURRENT_COMMIT: 16737ca851ec51a528f4251fa94be3ef8ae84fc9
CURRENT_PHASE: 2
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-2-remediation-001
CHECKPOINT_PATH: orchestration/checkpoints/phase_2_remediation.md
BUNDLE_PATH: orchestration/bundles/phase_2_remediation.txt
TEST_STATUS: 519/519 unit passed (incl. 14 new P2-R2 tests); 71/71 integration passed (real PostgreSQL 16); 95/95 golden passed; 10/10 replay passed; 7/7 phase_1_5 passed; full repository suite 702/702 passed, 0 failed, 0 unexplained skipped, 85% overall coverage; ruff clean; ruff format clean; mypy clean (98 source files); 12/12 real-chain fixtures ok; secret scan clean (one pre-existing, unrelated, obviously-fake test string)
WORKING_TREE: clean (verified via `git status --porcelain` before this commit)
ORCHESTRATOR_REVIEW_REQUIRED: whether this round's remediation of all 8 frozen findings (P2-R1 through P2-R8), each independently mapped to exact code and tests and each of the 8 frozen remediation acceptance-test items individually scored PASS (checkpoint section E), is sufficient to approve Phase 2, or whether further remediation is required. See checkpoint sections B (per-finding detail), E (acceptance-test disposition), G (one disclosed deviation from prior-round precedent -- declining a destructive dev-database migration cycle), and H (known debt, none new) for the full disposition.

## Work completed

Executed orchestrator instruction `argus-phase-2-remediation-001` in
full: independently verified all safety gates (instruction-only commit
whose parent exactly matches `TARGET_COMMIT`
`6bde9fdf6d56c38517854700e8863d9103e831aa`; `AUTHORIZED_PHASE: 2` vs.
`docs/BUILD_STATE.md`'s `current_phase: 2`; clean worktree; local HEAD
equal to freshly-fetched remote HEAD; Phase 2 awaiting orchestrator
review and not marked approved) before any code was touched, then fixed
and proved exactly the 8 frozen findings named, nothing else.

1. **P2-R1 + P2-R8** (mint discrimination + evidence provenance). Real
   SPL Token / Token-2022 account-type discrimination
   (`_classify_mint_account_layout()`) replaces a bare
   `len(decoded) < 82` check that let a 165-byte legacy SPL token
   *account* validate as a Mint. `validate_from_token_balance_evidence`
   now evaluates every matching pre/post token-balance entry (never just
   the first), fails closed to `UNAVAILABLE` on conflicting decimals or
   owning program, and persists `chain_time` whenever the evidence's own
   `blockTime` supports it.
2. **P2-R2** (historical acquisition/provider boundary). New, typed,
   provider-neutral `acquire_historical_transactions()`
   (`src/argus/tokens/historical_acquisition.py`) over the existing
   Phase 1 `ChainProvider` contract -- bounded pagination with explicit
   handling for every named fault (multiple pages, duplicate item/page
   in both immediately-repeated-cursor and multi-step-cycle forms,
   premature short pages, safety-ceiling exhaustion, timeout/rate-limit/
   malformed-response provider failures, per-transaction fetch
   failures), never silently reporting COMPLETE on any fault. Wired
   through a real production CLI command, `argus discover
   acquire-and-run-archaeology`, not a test-only helper.
3. **P2-R3** (deterministic + semantically meaningful early buyers).
   A full `(slot, signature, wallet_address)` sort key replaces an
   implicit `PYTHONHASHSEED`-dependent tie-break (proven via a real
   subprocess test spawning the extractor under different hash seeds).
   Transaction-signer-set membership (`_transaction_signers()`) now
   classifies each candidate's `ownership_classification`, so a known
   program-derived account (the real pump.fun bonding-curve reserve PDA,
   re-verified against the real creation-transaction evidence) is never
   promoted into `wallets`/`early_buyers`/discovery events, while its raw
   evidence is still preserved -- "tag, don't delete" intact.
4. **P2-R4** (confidence-aware winner evaluation). `select_baseline`/
   `select_peak` now require HIGH/MEDIUM `market_state_confidence`;
   LOW/UNKNOWN/`NULL`-confidence observations can no longer create a
   milestone or trigger, closing the frozen finding's exact named
   scenario (a 12x LOW-confidence probe producing `MAJOR_WINNER`).
5. **P2-R5** (automatic trigger consumer/executor). A bounded,
   restart-safe `run_all_pending_triggers_for_token()` finds and executes
   a token's own pending trigger(s), wired through a new CLI command
   (`argus discover run-pending-trigger`) with no `--trigger-id` option
   at all -- no human ever copies a trigger ID between two commands.
6. **P2-R6** (crash-safe archaeology state machine). `run_archaeology`
   restructured into three independently-committing transaction phases
   (claim / extract+persist outputs / terminalize); a new
   `reap_stale_archaeology_runs()` restart-recovery reaper marks a
   genuinely stale RUNNING row `FAILED` with an honest `error_reason`.
   Proven via a real-Postgres crash-injection matrix covering all 4
   required boundaries.
7. **P2-R7** (u64-capable raw integer columns). New `U64Numeric` type
   (`NUMERIC(39,10)` storage, `[0, 2**64-1]` range + integrality CHECK
   constraints -- the nonzero-scale storage type was required after
   direct empirical proof that `NUMERIC(p,0)` silently rounds a
   fractional value rather than rejecting it) widens
   `token_market_snapshots.supply_raw`/`early_buyers.amount_raw` from
   signed `BigInteger` via new migration
   `0009_phase2_u64_raw_quantities.py`, with a fail-closed downgrade path
   and boundary round-trip tests for 0/1/`2**63`/`2**64-1`.

All 8 frozen remediation acceptance-test items (R1-R7 plus the
regression item) pass. Full per-finding detail, the complete
requirement-to-code/test matrix, and every command actually run:
`orchestration/checkpoints/phase_2_remediation.md`.

## Important findings

- **A fresh, from-clean-database, real end-to-end CLI re-run of the
  Phase 2 demonstration** (`orchestration/phase_2/
  DEMONSTRATION_REMEDIATION.md`, new file -- the original
  `orchestration/phase_2/DEMONSTRATION.md` is left unmodified as
  immutable historical record, per this instruction's own "do not
  overwrite Phase 2 evidence") directly confirms, via Postgres queries,
  that the original demonstration's second early-buyer row -- the
  bonding-curve reserve PDA, honestly disclosed at the time as "very
  likely not a human trader" -- is no longer present; only the genuine
  signer/dev-buy wallet is recorded, and the excluded candidate is
  explicitly counted (`unresolved_ownership_count=1`), not silently
  dropped.
- **The new P2-R2 live-acquisition CLI path was directly exercised
  against this sandbox's real missing-credential environment**, not
  merely built and unit-tested: `argus discover
  acquire-and-run-archaeology` with no `HELIUS_API_KEY` configured
  produces the exact section-108 `LOCAL CREDENTIAL REQUIRED` notice and
  attempts no network call -- the same fail-closed behavior `argus
  ingest run`'s live path already has.
- **One deliberate, disclosed deviation from prior-round precedent**:
  earlier rounds ran a destructive `alembic downgrade base`/`upgrade
  head` cycle directly against the shared dev database after confirming
  it held no data. This round's dev database now holds real Phase 2
  remediation demonstration evidence, so that cycle was **not** run
  against it this round; the full migration round-trip/boundary-value/
  fail-closed-downgrade proof instead comes entirely from
  `tests/integration/test_migrations.py`'s disposable-scratch-database
  fixture (checkpoint section G explains the full reasoning, including
  why the scratch-database mechanism is actually more thorough for
  proving the fail-closed downgrade path specifically).
- `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is unchanged -- still the
  orchestrator's `argus-phase-2-remediation-001` instruction, `STATUS:
  ACTIVE`. Phase 2 is NOT marked approved anywhere in this run's
  evidence, per this instruction's own explicit requirement.
- Both commits this run (the primary work commit and the follow-up
  commit-hash-fill-in commit) carry the sole final trailer paragraph
  `ARGUS-INSTRUCTION-ID: argus-phase-2-remediation-001`, verified via
  `git interpret-trailers --parse` before push.

## Failures or limitations

- Historical-evidence breadth for the demonstrated pump.fun token
  remains limited to its own creation transaction in this sandbox: the
  new P2-R2 live acquisition path exists and is CLI-wired, but
  exercising it against this specific token still requires a
  `HELIUS_API_KEY` this sandbox does not have (re-disclosed, not
  resolved, in `orchestration/phase_2/DEMONSTRATION_REMEDIATION.md`).
- Phase 1's own pre-existing `swaps.input_amount_raw`/`output_amount_raw`
  `BigInteger` columns share the same theoretical u64-overflow risk
  P2-R7 fixed for the two new Phase 2 columns, but are explicitly out of
  this remediation's scope (the instruction's own "New Phase 2
  `supply_raw` and `amount_raw` columns" wording) -- left as known,
  disclosed, pre-existing debt.
- `LIVE_HELIUS_RPC_VALIDATION`/`LIVE_HELIUS_WSS_VALIDATION`/`PG17_
  COMPOSE_VALIDATION`/`BQ_PUBLIC_DATASET_ACCESS` remain `DEFERRED_
  ENVIRONMENTAL_CHECK`, unchanged.

## Deferred checks

- All items under "Failures or limitations" above.
- Extending the u64 widening to Phase 1's own `swaps.input_amount_raw`/
  `output_amount_raw` columns, if a future phase's use case requires it.

## Exact next action requested from orchestrator

Review this remediation round's evidence
(`orchestration/checkpoints/phase_2_remediation.md` and
`orchestration/bundles/phase_2_remediation.txt`) against instruction
`argus-phase-2-remediation-001`'s 8 frozen findings and 8 frozen
remediation acceptance-test items, and resolve whether Phase 2 is now
approvable. If accepted, write the next `ACTIVE` instruction into
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md` (`TARGET_COMMIT` pinned to
the exact commit named in this handoff) to authorize Phase 3 or further
Phase 2 remediation. Phase 3 remains forbidden until then. Until a new
instruction exists, the watcher (if running) takes no action beyond
logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** unchanged from prior handoffs — if you
cloned/fetched this branch before 2026-08-30T22:35 UTC, re-clone or
`git fetch --all && git reset --hard origin/claude/argus-folder-setup-77ahrk`
rather than merging/rebasing the old (pre-rewrite) history.
