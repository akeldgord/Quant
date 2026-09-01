# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0026-phase-4-remediation-1
UTC_TIMESTAMP: 2026-09-01T16:30:00Z
CURRENT_COMMIT: PLACEHOLDER_FILLED_IN_SECOND_COMMIT
CURRENT_PHASE: 4
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-4-remediation-001
CHECKPOINT_PATH: orchestration/checkpoints/phase_4_remediation_1.md
BUNDLE_PATH: orchestration/bundles/phase_4_remediation_1.txt
TEST_STATUS: 27/27 unit `test_phase3_wallet_qualification.py` passed (unchanged); 36/36 integration `test_wallet_acquisition.py` passed (unchanged); 17/17 integration `test_phase3_wallet_qualification.py` passed (unchanged); 8/8 integration `test_shadow_phase4.py` passed (unchanged pass count; the already-terminal no-op regression test strengthened with a provider-call counter); 2/2 integration `test_daily_report.py` passed (unchanged); 6/6 unit `test_telegram_notifier.py` passed (unchanged); 17/17 integration `test_migrations.py` passed (unchanged pass count; head now 0018, all 9 hardcoded head-revision assertions updated from `0016` to `0018`); 112/112 golden+replay+phase_1_5 passed (unchanged); NEW 12/12 integration `test_shadow_phase4_remediation_observation.py` (P4-R1/R2/R3); NEW 14/14 integration `test_shadow_quote_jobs_provider_remediation.py` (P4-R4, real `JupiterClient`+`httpx.MockTransport`+real `PriorityScheduler`); NEW 7/7 integration `test_shadow_phase4_concurrency_remediation.py` (P4-R5, genuine `asyncio.gather` concurrency); NEW 10/10 integration `test_daily_report_remediation.py` (P4-R6); NEW 8/8 integration `test_replay_demo_isolation.py` (P4-R7); full repository suite 859/859 passed (up from 808; +51 exactly matches the 5 new test files' combined count), 0 failed, 0 unexplained skipped; ruff clean; ruff format clean (252 files); mypy clean (128 source files, unchanged); alembic head 0018 (was 0016), downgrade-0016/upgrade-head round-trip clean through 0017/0018, re-verified after the full suite ran; 12/12 real-chain fixtures ok; secret scan clean on all 23 changed/new files -- ALL RAW COMMAND OUTPUT embedded verbatim in the paired bundle
WORKING_TREE: clean (verified via `git status --porcelain` before this commit)
ORCHESTRATOR_REVIEW_REQUIRED: whether this remediation round genuinely closes all 7 frozen findings (P4-R1 through P4-R7) from `argus-phase-4-audit-001`, whether the two additional gaps found and fixed beyond the audit's own list (checkpoint section B: a missing `argus_ingest` UPDATE grant, a nonfinite-Decimal comparison crash, a genuine `ShadowPosition`-creation race) are correctly and completely closed rather than merely disclosed, and whether Phase 4 should now be approved and Phase 5 authorized, or further remediation required. This session does not and cannot apply Phase 4 approval itself.

## Work completed

Executed orchestrator instruction `argus-phase-4-remediation-001` in full:
independently verified all safety gates (single instruction-only commit
whose parent exactly matches `TARGET_COMMIT`
`d95a629985668a0ba73795d3ad8daeb5534ce855`; `AUTHORIZED_PHASE: 4` vs.
`docs/BUILD_STATE.md`'s `current_phase: 4` at the time -- not skipping
ahead, since this is a remediation of the SAME phase, not a new one; clean
worktree; local HEAD equal to freshly-fetched remote HEAD) before any code
was touched, then closed all 7 frozen findings from independent audit
`argus-phase-4-audit-001` (`FAIL_REMEDIATION_REQUIRED`) as one consolidated
batch, in the instruction's own explicit order:

1. **P4-R7 (isolation, done first)**: `scripts/argus_phase4_replay_demo.py`
   rewritten onto the same disposable-scratch-database pattern
   `tests/integration/test_migrations.py` already established -- creates a
   uniquely-named scratch database, points `ARGUS_DB_NAME` at it, runs
   migrations (via `asyncio.to_thread`, since alembic's own `env.py` calls
   `asyncio.run()` internally and would otherwise conflict with this
   script's own already-running event loop), runs the full lifecycle,
   unconditionally drops the scratch database afterward. A defense-in-depth
   `refuse_unless_scratch_database` guard is checked before every write/
   network-shaped call. Proven via 8 new tests including fault injection at
   all 4 lifecycle points, each leaving a pre-existing shared-database
   wallet and its unrelated queued due jobs byte-for-byte unchanged.
2. **P4-R1 (point-in-time knowledge cutoff)**: every prospective-event
   snapshot field (score, tier, token market state, position context,
   cluster links) is now selected strictly as-of `swap.first_seen_at`,
   never as-of wall-clock scan time; tier is resolved from immutable
   `WalletTierTransition` history, never `wallets.current_tier`; the
   exact source-row identities used are persisted alongside the values
   (migration 0017) so the snapshot can be independently checked.
3. **P4-R2 (probe due-time origin)**: entry-delay probe `target_due_at` is
   now anchored to `event.first_seen_at`, never to the monitoring pass's
   own wall-clock `now` -- proven against the audit's own exact worked
   example (first_seen T, consumer T+60s, nominal 1s due T+1s, request
   T+62.7s recording 61.7s scheduling delay).
4. **P4-R3 (scanner starvation + confirmation replay)**: the candidate scan
   now excludes already-claimed economic events via SQL BEFORE any `LIMIT`
   (a fully-processed batch can no longer permanently block later
   genuinely-new swaps) and deduplicates per canonical `chain_events.
   event_id` (two parser artifacts of one transaction can no longer create
   two shadow trades); a new `revisit_pending_confirmations` safely records
   a late-arriving real confirmation exactly once, touching only
   `confirmation_time`, never the rest of the frozen snapshot.
5. **P4-R4 (honest provider-failure/capacity classification)**: real
   `httpx.HTTPStatusError`/`PriorityScheduler.RequestDropped` are now
   correctly classified (not just the fake-provider-only exception family);
   `_classify_quote` now verifies response identity and requires genuine
   non-empty route evidence before ever reporting success; the shared
   `PriorityScheduler` -- previously built and unit-tested but never
   actually wired into any production code path -- is now wired into the
   real CLI entry/reverse-probe commands for the first time.
6. **P4-R5 (overlapping-worker terminal-evidence race)**: a
   `claim_generation` counter (migration 0017), verified via `SELECT ...
   FOR UPDATE` at the terminal write, ensures a stale worker superseded by
   a fresh reclaim can never overwrite the fresh attempt's result; an
   already-terminal probe/outcome now returns before ever calling the
   provider.
7. **P4-R6 (report accuracy + notifier wiring)**: tier-direction counting
   now uses real `WALLET_TIERS` rank order (the audit's own worked example
   -- S->A, DISCOVERED->WATCH, PROBATION->B -- now correctly counts 2
   promotions/1 demotion, not the pre-fix "1 promotion, 2 demotions");
   `new_wallets` counts distinct wallet identities, not repeated discovery
   events; a real injectable `notifier` is now wired into two ordinary
   production services (`build_daily_report`, the shadow entry-probe fill
   path) for the first time, using only their own already-committed facts,
   disabled/no-op by default, `FakeTelegramTransport` in tests.

**Two additional genuine gaps found and fixed beyond the audit's own 7
findings**, while writing this remediation's own required focused tests --
never weakened or hidden (checkpoint section B has the full detail):

- `argus_ingest` had no `UPDATE` privilege at all on `prospective_events`,
  so P4-R3's correct Python fix would have thrown
  `InsufficientPrivilegeError` in real production. Fixed with a new
  additive migration (`0018`) granting `UPDATE` on ONLY the
  `confirmation_time` column.
- A parsed-but-nonfinite `Decimal("NaN")`/`Decimal("Infinity")`
  `priceImpactPct` crashed `_classify_quote`'s comparison with an uncaught
  `decimal.InvalidOperation`, aborting an entire claimed probe batch. Fixed
  by folding a nonfinite parse result into the same honest `None`-leniency
  path the module already documents for unparseable impact data.
- Two entry-delay probes for the SAME shadow intent could race, under
  genuine concurrent load, to create the first `ShadowPosition`, raising an
  unhandled `IntegrityError`. Fixed with a `SELECT ... FOR UPDATE` lock on
  the parent `ShadowIntent` row, serializing concurrent creators.

## Important findings

- All 7 frozen findings from `argus-phase-4-audit-001` are FIXED -- see
  `orchestration/checkpoints/phase_4_remediation_1.md` section B for the
  full finding-to-evidence disposition, including the two additional gaps.
- All 10 original frozen acceptance gates from `argus-phase-4-001`'s own
  table (the pre-remediation build) remain PASS after this round's changes
  -- section D of the new checkpoint confirms no regression.
- Telegram notification now has two real ordinary production callers
  (`build_daily_report`, the shadow entry-probe fill path) -- the prior
  checkpoint's disclosed "no ordinary producer invokes it" item is
  resolved, not merely re-disclosed.
- `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is unchanged -- still the
  orchestrator's `argus-phase-4-remediation-001` instruction. Phase 4 is
  NOT marked approved anywhere in this session's evidence;
  `last_orchestrator_approved_phase` is `3` (unchanged), never `4`.
- Both commits this session (the primary work commit and the follow-up
  commit-hash-fill-in commit) carry the sole final trailer paragraph
  `ARGUS-INSTRUCTION-ID: argus-phase-4-remediation-001`, with no paragraph
  after it, verified via `git interpret-trailers --parse` before push.

## Failures or limitations

- None. All 7 named findings are closed with real, tested fixes, and the 2
  additional gaps found while testing them are also closed at their root
  cause.
- `LIVE_HELIUS_RPC_VALIDATION`/`LIVE_HELIUS_WSS_VALIDATION`/`PG17_
  COMPOSE_VALIDATION`/`BQ_PUBLIC_DATASET_ACCESS` remain `DEFERRED_
  ENVIRONMENTAL_CHECK`, unchanged, not reopened this round. No live
  Jupiter/DexScreener network access remains an explicit, disclosed
  constraint of this sandbox (P4-R4's real-adapter tests use
  `httpx.MockTransport`, never a live endpoint).

## Deferred checks

- All items under "Failures or limitations" above.

## Exact next action requested from orchestrator

Independently re-audit this remediation round
(`orchestration/checkpoints/phase_4_remediation_1.md`,
`orchestration/bundles/phase_4_remediation_1.txt`) against
`argus-phase-4-audit-001`'s own 7 frozen findings. In particular: whether
each finding's required-test scenarios (named verbatim in
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md`'s per-finding sections) are
genuinely satisfied by the new test files, whether the two additional gaps
found and fixed beyond the audit's own list are correctly closed, and
whether the original 10 frozen acceptance gates still hold with no
regression. Only the orchestrator may apply Phase 4 approval -- write the
next `ACTIVE` instruction into `orchestration/ORCHESTRATOR_INSTRUCTIONS.md`
(`TARGET_COMMIT` pinned to the exact commit named in this handoff) to do
so, or to require further remediation. Phase 5 remains forbidden until
then. Until a new instruction exists, the watcher (if running) takes no
action beyond logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** unchanged from prior handoffs — if you
cloned/fetched this branch before 2026-08-30T22:35 UTC, re-clone or
`git fetch --all && git reset --hard origin/claude/argus-folder-setup-77ahrk`
rather than merging/rebasing the old (pre-rewrite) history.
