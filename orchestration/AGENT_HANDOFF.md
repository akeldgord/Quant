# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0027-phase-4-remediation-2
UTC_TIMESTAMP: 2026-09-01T19:35:00Z
CURRENT_COMMIT: 9890802f91da02c51fc4a2f12715c821158dc53b
CURRENT_PHASE: 4
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-4-remediation-002
CHECKPOINT_PATH: orchestration/checkpoints/phase_4_remediation_2.md
BUNDLE_PATH: orchestration/bundles/phase_4_remediation_2.txt
TEST_STATUS: 80/80 unit `test_phase3_wallet_qualification.py` + integration `test_wallet_acquisition.py` + integration `test_phase3_wallet_qualification.py` passed (unchanged); 8/8 integration `test_shadow_phase4.py` passed (unchanged pass count, fixture updates only); 2/2 integration `test_daily_report.py` passed (unchanged); 6/6 unit `test_telegram_notifier.py` passed (unchanged); 17/17 integration `test_migrations.py` passed (unchanged pass count; head now 0020, all 9 hardcoded head-revision assertions updated `0018`->`0020`); 112/112 golden+replay+phase_1_5 passed (unchanged); 31/31 integration `test_shadow_phase4_remediation_observation.py` (up from 12 -- 19 new P4-R1/P4-R3-continued tests); 24/24 integration `test_shadow_quote_jobs_provider_remediation.py` (up from 14 -- 10 new P4-R4-continued tests); 7/7 integration `test_shadow_phase4_concurrency_remediation.py` (unchanged -- P4-R5 frozen); 12/12 integration `test_daily_report_remediation.py` (up from 10 -- P4-R6 continued, replacing two production-formula-duplicating test oracles with independent hand-computed ones); 8/8 integration `test_replay_demo_isolation.py` (unchanged -- P4-R7 frozen, fixture update only); full repository suite 890/890 passed, 0 failed, 0 unexplained skipped; ruff clean; ruff format clean (255 files); mypy clean (128 source files); alembic head 0020 (was 0018), downgrade-0018/upgrade-head round-trip clean through 0019/0020, re-verified after the full suite ran; 12/12 real-chain fixtures ok; secret scan clean on all 15 changed/new files plus the new evidence directory -- ALL RAW COMMAND OUTPUT embedded verbatim in the paired bundle
WORKING_TREE: clean (verified via `git status --porcelain` before this commit)
ORCHESTRATOR_REVIEW_REQUIRED: whether this round genuinely closes all 4 continued findings (P4-R1, P4-R3, P4-R4, P4-R6) against `argus-phase-4-remediation-audit-002`'s own concrete adversarial probes, whether P4-R2/P4-R5/P4-R7 remain correctly untouched and still pass, whether the two additional gaps found and fixed beyond the audit's own list (checkpoint section E: a scanner-level tier-eligibility generalization, a concurrent-insert SAVEPOINT race guard) are correctly and completely closed rather than merely disclosed, and whether Phase 4 should now be approved and Phase 5 authorized, or further remediation required. This session does not and cannot apply Phase 4 approval itself.

## Work completed

Executed orchestrator instruction `argus-phase-4-remediation-002` in full:
independently verified all safety gates (single instruction-only commit
whose parent exactly matches `TARGET_COMMIT`
`1d5cc5d93819cdeec050889a5b37c44d5b2f5c0b`; `AUTHORIZED_PHASE: 4` vs.
`docs/BUILD_STATE.md`'s `current_phase: 4` at the time -- not skipping
ahead; clean worktree; local HEAD equal to freshly-fetched remote HEAD)
before any code was touched, then closed the 4 findings independent
re-audit `argus-phase-4-remediation-audit-002` found only PARTIALLY
sufficient after round 1 (`FAIL_REMEDIATION_REQUIRED`, with a concrete
adversarial-probe justification for each), while explicitly NOT reopening
the 3 findings the same re-audit confirmed CLOSED (P4-R2/P4-R5/P4-R7):

1. **P4-R1 continued (first-seen knowledge boundary)**: point-in-time
   evidence selection now requires BOTH an effective-time bound AND a
   recorded-time bound together (round 1 only bounded one side, so a
   value effective-in-the-past-but-not-yet-recorded, or recorded-on-time-
   but-describing-a-future-period, could leak through); the token-state
   snapshot no longer falls back to a token's denormalized CURRENT
   lifecycle stage when no point-in-time snapshot exists; most severely,
   the scanner's own candidate-selection gate used a wallet's CURRENT
   tier even though the snapshot-content logic already used point-in-time
   tier history (a later promotion could retroactively pull an old,
   actually-ineligible swap into the candidate set; a later demotion could
   permanently exclude an old, genuinely-eligible one) -- fixed via a
   correlated SQL subquery computing each swap's own tier-at-its-own-
   cutoff, applied inside the same LIMIT-bounded query (never a Python-
   side post-filter, which would reintroduce starvation).
2. **P4-R3 continued (confirmation and repeated-pass lifecycle)**:
   confirmation lookups checked commitment level alone with no
   `transaction_succeeded` filter, so a CONFIRMED observation of a FAILED
   transaction was silently treated as success, and a FINALIZED-only
   success was never considered -- fixed via one new shared
   `_confirmed_success_observation` helper (both call sites now agree
   byte-for-byte); the late-confirmation revisit query had no check that
   resolvable evidence actually existed before selecting its LIMIT-bounded
   batch, so permanently-unconfirmable rows could starve a later
   genuinely-resolvable one -- fixed via an `exists()` subquery before
   LIMIT; a concurrent scanner's TOCTOU race on its own NOT-EXISTS check
   could raise an uncaught `IntegrityError` aborting an entire batch --
   fixed via a per-candidate Postgres SAVEPOINT, proven via genuine
   `asyncio.gather` concurrency.
3. **P4-R4 continued (honest provider evidence)**: mint-identity
   verification now checks the response's own RAW `inputMint`/
   `outputMint` fields, never the caller-echoed `ExecutableQuote` labels;
   route-plan evidence now requires each entry to be structurally
   well-formed, not merely a non-empty list (`routePlan=[null]` is
   equivalent to no route); a SUPPLIED-but-garbage/nonfinite
   `priceImpactPct` is now an explicit `QUOTE_FAILED`, distinct from a
   genuinely absent one (which stays leniently `None`) -- a deliberate
   reversal of round 1's own over-broad leniency fix; Jupiter's own
   structured `platformFee.amount` is now honestly parsed, never
   fabricated; `requested_at`/`responded_at` are now captured from inside
   the actually-dispatched scheduler callable so a queue wait is never
   conflated with provider latency; a new `terminal_at` column (migration
   0020) records every terminal decision regardless of whether a real
   dispatch occurred, now the source of truth for claim-candidate
   filtering, no-fill checks, and report-window queries.
4. **P4-R6 continued (current-phase report accuracy)**: SHADOW's
   `mfe_mae` now samples this window's own real `ShadowMarkOutcome`
   returns, never historical Phase 3 `WalletPosition` data; those
   historical figures, when retained, moved to RESEARCH's own separately
   labeled `historical_backtest` section, grouped by quote asset and
   restricted to each wallet's current chosen history reconstruction;
   `low_completeness_wallets` now counts distinct wallets by their
   CURRENT assessment only, never every historical LOW/UNKNOWN row; the
   single `matured_executable_outcomes_in_window` count is replaced by an
   explicit successful/unsellable/missing_capacity breakdown with a
   separate overdue-unattempted count.

**Two additional genuine gaps found and fixed beyond the audit's own 4
findings**, while writing this round's own required focused tests --
never weakened or hidden (checkpoint section E has the full detail):

- The scanner-level tier-eligibility fix under P4-R1 generalizes beyond
  the audit's own single literal worked example to every tier promotion/
  demotion, not just the one case named.
- A concurrent scanner's TOCTOU race under P4-R3 had no protection at
  all before this round; fixed with a per-candidate Postgres SAVEPOINT.

An unintended side effect was caught and corrected mid-session: an
earlier invocation of `scripts/argus_phase4_replay_demo.py` (before this
round's required validation commands were run) wrote to its
still-hardcoded `phase_4_remediation_1` evidence path, overwriting round
1's frozen evidence file. Caught via `git status --porcelain` before any
commit, reverted with `git checkout --`, and `EVIDENCE_DIR` fixed to point
at `phase_4_remediation_2/evidence` so this cannot recur --
`orchestration/phase_4_remediation_1/evidence/replay_demo_results.json`
is confirmed byte-for-byte unmodified in the final diff.

## Important findings

- All 4 continued findings from `argus-phase-4-remediation-audit-002` are
  FIXED -- see `orchestration/checkpoints/phase_4_remediation_2.md`
  section B for the full requirement-to-evidence matrix and section C for
  the instruction's own required seven-part no-moving-goalposts
  justification.
- P4-R2/P4-R5/P4-R7 (confirmed CLOSED by the re-audit) were NOT touched
  except where P4-R4's own continued fix required threading the new
  `terminal_at` column through P4-R5's ALREADY-EXISTING generation-check
  guard (a strict addition, never a weakening) -- section D of the new
  checkpoint confirms every frozen finding's own regression tests still
  pass unmodified.
- `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is unchanged -- still the
  orchestrator's `argus-phase-4-remediation-002` instruction. Phase 4 is
  NOT marked approved anywhere in this session's evidence;
  `last_orchestrator_approved_phase` is `3` (unchanged), never `4`.
- Both commits this session (the primary work commit and the follow-up
  commit-hash-fill-in commit) carry the sole final trailer paragraph
  `ARGUS-INSTRUCTION-ID: argus-phase-4-remediation-002`, with no
  paragraph after it, verified via `git interpret-trailers --parse`
  before push.

## Failures or limitations

- None. All 4 continued findings are closed with real, tested fixes, and
  the 2 additional gaps found while testing them are also closed at their
  root cause.
- `LIVE_HELIUS_RPC_VALIDATION`/`LIVE_HELIUS_WSS_VALIDATION`/`PG17_
  COMPOSE_VALIDATION`/`BQ_PUBLIC_DATASET_ACCESS` remain `DEFERRED_
  ENVIRONMENTAL_CHECK`, unchanged, not reopened this round. No live
  Jupiter/DexScreener network access remains an explicit, disclosed
  constraint of this sandbox (P4-R4's real-adapter tests use
  `httpx.MockTransport`/a real `PriorityScheduler` with purely-local
  `asyncio` synchronization, never a live endpoint).

## Deferred checks

- All items under "Failures or limitations" above.

## Exact next action requested from orchestrator

Independently re-audit this remediation round
(`orchestration/checkpoints/phase_4_remediation_2.md`,
`orchestration/bundles/phase_4_remediation_2.txt`) against
`argus-phase-4-remediation-audit-002`'s own 4 continued findings and
concrete adversarial probes. In particular: whether each continued
finding's required-test scenarios (named verbatim in
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md`'s per-finding sections) are
genuinely satisfied by the extended/new test files, whether the two
additional gaps found and fixed beyond the audit's own list are correctly
closed, whether P4-R2/P4-R5/P4-R7 remain genuinely untouched and still
pass, and whether the original 10 frozen acceptance gates plus round 1's
own added regression proof still hold with no regression. Only the
orchestrator may apply Phase 4 approval -- write the next `ACTIVE`
instruction into `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`
(`TARGET_COMMIT` pinned to the exact commit named in this handoff) to do
so, or to require further remediation. Phase 5 remains forbidden until
then. Until a new instruction exists, the watcher (if running) takes no
action beyond logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** unchanged from prior handoffs — if you
cloned/fetched this branch before 2026-08-30T22:35 UTC, re-clone or
`git fetch --all && git reset --hard origin/claude/argus-folder-setup-77ahrk`
rather than merging/rebasing the old (pre-rewrite) history.
