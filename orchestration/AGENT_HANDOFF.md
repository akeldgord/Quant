# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0042-final-spec-recovery-002-clarification-001
UTC_TIMESTAMP: 2026-09-05T03:10:00Z
CURRENT_COMMIT: (this handoff's own commit -- see `git log -1`)
CURRENT_PHASE: 11
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-final-spec-recovery-002-clarification-001
WORKING_TREE: clean
CHECKPOINT_PATH: orchestration/checkpoints/final_spec_recovery.md
BUNDLE_PATH: orchestration/bundles/final_spec_recovery.txt
TEST_STATUS: R2-01 focused (+7 new single-intent-mode tests) 26 passed; R2-02 focused (+3 new tests incl. the full 7-step mutation recipe) 5 passed; R2-03 focused (+10 new tests) 29 passed; tests/unit+tests/golden+tests/replay (1333 tests) 0 failed; tests/integration (fresh isolated-database template) 418 passed/0 failed (one genuine pre-existing test-assumption bug found and fixed mid-round, unrelated to the clarification's own requested changes -- see checkpoint section K-CLARIFICATION-001). ruff check/ruff format --check/mypy clean (228 source files). Secret scan clean across all 20 changed/new files this round. Single Alembic head (0041). PostgreSQL 17 remains FINAL_RECOVERY_ENVIRONMENT_BLOCKED -- reconfirmed, NOT retried this round, per the clarification instruction's own explicit AUTHORIZED_ACTION -- LIVE_READY_SOFTWARE=false.
ORCHESTRATOR_REVIEW_REQUIRED: FINAL_ORIGINAL_SPEC_AUDIT -- all R2-01..R2-04 software requirements pass, including every literal clarification in `argus-final-spec-recovery-002-clarification-001` (see checkpoint section B-CLARIFICATION-001 for the full description of each fix). The sole remaining blocker is PostgreSQL 17 environment access (section 8 of the checkpoint), an external sandbox restriction rather than a software defect. No further gaps are disclosed this round: the base round's own disclosed R2-02 mutation-recipe gap is now CLOSED.

## Work completed this round (`argus-final-spec-recovery-002-clarification-001`)

An independent audit found the prior round's R2-01/R2-02/R2-03 items (all
marked PASS) not yet proven against their own already-frozen wording, and
issued three literal clarifications. R2-04 was reconfirmed CLOSED/PASS
(untouched, per the clarification's own instruction); PG17 was
reconfirmed `FINAL_RECOVERY_ENVIRONMENT_BLOCKED` (not retried).

**R2-01 clarification**: `execute_intent_pipeline`
(`src/argus/executor/pipeline.py`) now owns its own transaction boundary
on every return path (`await session.commit()`), replacing an internal
`session.flush()` that left the signature+`SUBMITTED` row visible only
inside a still-open transaction a real process crash could roll back --
callers must no longer wrap it in their own `session.begin()`. The crash
test was rewritten to simulate a REAL crash boundary via a
`_CrashingConfirmationProvider` plus a second, independent DB connection
verifying durability before the simulated crash unwinds. `src/argus/
executor/main.py` gained a narrow, config-gated "single-intent mode"
that actually invokes `execute_intent_pipeline()` with real
production-capable adapters -- closing the gap where `main`'s production
identity had no real code path to the pipeline at all -- while remaining
impossible to dispatch under repository defaults (the existing hard risk
gates, unchanged, plus a new defense-in-depth field allowlist proving an
operator's params file can never spoof identity/arm/canary fields). 7 new
tests (`tests/unit/test_r201_single_intent_mode.py`).

**R2-02 clarification**: added `wallet_specialist_scores.
source_knowledge_max_at` (migration 0041, additive, CHECK-constraint-
enforced `<= as_of`) -- the MAX knowledge-time among every source row
that actually contributed to a score, across all four specialist
dimensions, including a genuine independent pre-existing bug found and
fixed in the same pass (`load_latest_exit_skill` was missing the
`created_at <= cutoff` half of `known_by_cutoff` its own sibling consumer
already applied correctly to the same table). Both Phase 10 and Phase 11
consumer loaders now additionally require `source_knowledge_max_at <=
decision_time`. The full literal section-4.3 7-step mutation-test recipe
(seed E1 -> reconstruct Phase 9 for T -> capture Phase 10/11 values at T
-> append a knowable-only-later row -> rebuild under a fresh invocation
-> prove byte-identical T decision inputs -> move cutoff forward and
prove legitimate divergence) is now implemented end-to-end against a real
evidence source with genuine `<=`-based re-selection
(`wallet_score_snapshots`) -- closing the base round's own disclosed gap.
`ALGORITHM_VERSION` bumped `counterfactual_alpha_v3` -> `_v4` and
`order_flow_prediction_v3` -> `_v4` (genuine algorithm evolution; no
durable v3 row ever existed, so no additional invalidation row was
seeded). 3 new tests plus the base round's own 2.

**R2-03 clarification**: Strategy A/B's entry price previously reused
`opportunity.entry_fill` unconditionally with no check of its own actual
timing against the strategy's own modeled entry timing. New
`_select_own_entry_fill_if_contemporaneous`
(`src/argus/synthetic/service.py`) validates the matching `ENTRY_DELAY`
probe's real observed timing against its own configured target delay
before trusting the loader's precomputed result -- a drifted or
unverifiable fill is honestly `FAILURE_NO_EXECUTABLE_EVIDENCE`. The
hardcoded, unversioned `[0.5x, 2.0x]` contemporaneous-matching ratio band
was replaced by `Phase10RunConfig.contemporaneous_match_max_delta` (an
explicit `timedelta`, included in `config_hash()`) -- eligibility is now
an ABSOLUTE delta against a versioned tolerance, with a deterministic
`(distance, target_label)` tiebreak, governing all three contemporaneous
decisions. `ALGORITHM_VERSION` bumped `synthetic_super_wallet_v3` -> `_v4`
(same no-additional-invalidation reasoning as R2-02). 10 new tests
(absolute-delta boundaries, deterministic tiebreaks, 6 new own-entry-fill
tests, a `config_hash()` versioning test, 1 new integration drift test)
plus the base round's own 18.

One genuine pre-existing test bug, unrelated to any of the three
clarified items, was found and fixed while running the full regression
sweep: `test_registry_names_all_four_contaminated_phases_with_reason`
compared a fixed historical migration value against the LIVE
`ALGORITHM_VERSION` import, an implicit assumption that broke once this
round's own version bumps landed -- corrected to the literal historical
value the migration actually recorded.

## Base round work (`argus-final-spec-recovery-002`, prior handoff, unaffected structurally this round)

Executed the complete bounded `argus-final-spec-recovery-002` remediation
(R2-01 through R2-04) -- see the checkpoint's own section B for the full
description: the integrated executor pipeline seam, the R2-02 knowledge-
time filters this round's own persisted-provenance mechanism now
supersedes, the R2-03 contemporaneous exit/entry-probe matching this
round's own versioned tolerance now supersedes, and the R2-04 hermetic
two-tier `isolated_database` test fixture (reconfirmed CLOSED, untouched
this round).

## Security-state confirmation

- Phase 6.5 (MAINNET CANARY) has NOT run and was not attempted.
- No mainnet transaction was signed or broadcast -- every test uses
  exclusively caller-scripted fakes or direct DB fixtures.
- No real operator key/seed was accessed, read, printed, logged, or
  exposed.
- No funded wallet was created; no arm file was created or modified.
- No capital default was changed from zero; `LIVE_ARMED=false` and
  `LIVE_CANARY_PASSED=false` throughout.
- No paid provider was enabled.
- No secret was requested; no credentials were used this round beyond
  the same pre-existing, previously-scrubbed dev-only `.env` literals the
  base round already disclosed, used solely to configure the same local
  ephemeral non-Docker PostgreSQL 16 cluster.
- Secret scan: clean across all 20 changed/new files this round.
- `LIVE_CANARY_PASSED=false`
- `LIVE_ARMED=false`
- `LIVE_READY_SOFTWARE=false` (PostgreSQL 17 remains environment-blocked,
  reconfirmed not retried this round per the clarification's own explicit
  instruction).
- This round did not modify `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`,
  did not self-approve, and did not perform Phase 6.5.

Full itemized evidence: checkpoint section N.

## Deferred / open items (explicitly disclosed, not hidden)

- PostgreSQL 17 validation remains blocked in this sandbox (unchanged
  disposition; not retried this round per the clarification's own
  explicit instruction). Needs either a sandbox with unblocked
  registry/PGDG egress, or an operator-run `make up && make test` against
  the repository's own `compose.yaml` with a real PostgreSQL 17 image.
- No large-N real-wallet Phase 10 v4/Phase 11 v4 research report was
  generated this round (out of this bounded remediation's own scope,
  unchanged from the base round's own disclosure).

No other gaps are disclosed: the base round's own R2-02 mutation-recipe
gap is CLOSED this round.

## Exact next action requested from orchestrator

Per `orchestration/AUDITOR_POLICY.md`: audit this clarification round
(`argus-final-spec-recovery-002-clarification-001`) against
`orchestration/checkpoints/final_spec_recovery.md` and
`orchestration/bundles/final_spec_recovery.txt`. If satisfied that every
non-environment requirement is genuinely met, only the orchestrator/human
operator may apply final recovery approval -- write the next `ACTIVE`
instruction into `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`
(`TARGET_COMMIT` pinned to this handoff's own `CURRENT_COMMIT`) to do so,
to authorize PostgreSQL 17 validation as a follow-up scope, or to require
further remediation. This session does not and cannot apply final
recovery approval itself. Until a new instruction exists, the watcher (if
running) takes no action beyond logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** if you cloned/fetched this branch
before this handoff's own `UTC_TIMESTAMP`, re-fetch to pick up this
round's commits.
