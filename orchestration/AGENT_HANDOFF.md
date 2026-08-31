# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0012-phase-1-remediation-5
UTC_TIMESTAMP: 2026-08-31T16:42:35Z
CURRENT_COMMIT: 6c7f4df1cce181dd54383b6dbb09f6be27df4471
CURRENT_PHASE: 1
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-1-remediation-005
CHECKPOINT_PATH: orchestration/checkpoints/phase_1_remediation_5.md
BUNDLE_PATH: orchestration/bundles/phase_1_remediation_5.txt
TEST_STATUS: unit 405/405 passed; integration 43/43 passed (real PostgreSQL 16, incl. 2/2 new migration 0007 populated-data downgrade tests); golden 32/32 passed; replay 10/10 passed; full suite 490/490 passed, 87% coverage; ruff clean; mypy clean; alembic downgrade-to-base/upgrade-to-head clean through migration 0007
WORKING_TREE: clean (verified via `git status --porcelain` before this commit)
ORCHESTRATOR_REVIEW_REQUIRED: acceptance-matrix item 1 (fixture authenticity+review+binding+validation) carries one documented caveat -- the newly-sourced `real_mainnet_orca_increase_liquidity_multi_asset_outflow` fixture satisfies the "multiple token-account/LP-style action" required category's substance (a real multi-token-account liquidity transaction, correctly never a confident single-asset trade) but its own emitted classification is `UNKNOWN` via the ambiguous-multi-asset-outflow branch, not the `LP_ACTION` label (see checkpoint section E item 1 and `tests/golden/fixtures/real/SEARCH_LOG.md`'s "Round 5" section for the full reasoning and evaluated alternatives). Real-chain fixture coverage is otherwise complete: 9 of 9 required categories now have real-chain evidence, up from round 4's honest 6 of 9. PG17_COMPOSE_VALIDATION (deferred, unrelated, unchanged) still open -- see docs/BUILD_STATE.md.

## Work completed

Executed orchestrator instruction `argus-phase-1-remediation-005` in
full: an independent audit rejected round 4 outright
(`FAIL_REMEDIATION_REQUIRED`, not merely PARTIAL), citing 9 concrete
findings and a 15-item mandatory acceptance matrix. All 9 findings are
remediated with real, tested code:

1. **Production git identity could be spoofed by a dirty checkout's
   override → fixed.** `resolve_production_git_commit()` checked the
   `ARGUS_BUILD_GIT_COMMIT` override *before* checking whether the
   checkout was dirty or even resolvable. Rewritten to a strict 4-step
   order: validate the override's format; resolve dirty-state; if git
   metadata is entirely absent, a well-formed override is the only path;
   if git metadata is present, a dirty checkout is *always* rejected
   regardless of any override; only then is HEAD resolved and checked
   against a supplied override for exact equality.
2. **The generic parser was not fail-closed for ambiguous/NFT/LP/
   multi-hop assets → fixed.** `SWAP_COMPLEX` is no longer
   copy-eligible; eligibility additionally requires both legs' decimals
   be nonzero; two or more same-direction assets with no offsetting leg
   now resolve to `UNKNOWN` at zero confidence instead of a
   largest-leg guess. A new public `compute_asset_deltas()` exposes the
   full ordered per-asset delta set, needed by finding #1's independent
   fixture review below.
3. **Golden fixture expectations were still circular-adjacent and
   provenance was not fully tamper-evident → fixed.** Replaced the flat
   `expected_classification`/`expected_confidence`/`upstream_license`
   strings with a typed, immutable `ExpectedOutcome` (wallet
   perspective, every asset delta, expected input/output, network fee,
   failed-tx status, a confidence rule, reviewer method/rationale/
   evidence) and real `git ls-tree`-backed `GitTreeAttestation`/
   `LicenseEvidence` cryptographically binding upstream repo/commit/
   path/blob/license, folded into one `evidence_chain_hash` so a
   single-field edit is detectable offline. All 10 then-existing
   fixtures were re-imported through the new schema with genuinely
   independent, hand-reasoned expectations.
4. **Two of nine required real-chain fixture categories were still
   missing → fixed.** Searched the three named candidate repositories;
   sourced a genuine failed on-chain transaction
   (`real_mainnet_failed_nft_sale`, via a new deterministic
   `extract_ts_const_export_default` transform step unlocking
   TypeScript-wrapped upstream sources) and a genuine multi-token-account
   Orca Whirlpool liquidity transaction
   (`real_mainnet_orca_increase_liquidity_multi_asset_outflow`, with the
   documented label caveat above). Combined with finding #2's fix
   independently making the previously-imported DCA-close fixture
   resolve to `UNKNOWN` (now genuinely satisfying the ambiguous-
   multi-asset category), real-chain evidence now exists for all 9 of 9
   required categories.
5. **Helius HTTP contract validation was still incomplete → fixed.**
   `get_slot`/`get_balance` now reject a JSON `bool` as an integer;
   `get_transaction` now requires `meta.err`'s presence, validates
   `meta.fee`/`preBalances`/`postBalances` as strict-nonnegative-int
   arrays coherent in length with `accountKeys`, requires a top-level
   `slot`, and fully validates any `preTokenBalances`/
   `postTokenBalances` entries; `get_token_accounts` cross-checks a
   returned entry's `owner` against the requested wallet and returns a
   genuinely immutable `TokenAccountInfo.raw`.
6. **WebSocket ack matching had a type-equality bug, lost early
   notifications, had unbounded cleanup, and reconnected every
   receive-timeout → fixed.** Ack matching is now an exact type+value
   check (`"id": true` could previously match request id `1` under
   Python's `==`); every non-matching message (including a genuine
   notification arriving before the ack) is now buffered and replayed,
   never discarded; a new transport-level ping/pong `check_liveness()`
   lets the ingestion manager distinguish "quiet but alive" from
   "genuinely dead", reusing a single pending receive task across
   multiple timeout/liveness-probe cycles rather than reconnecting a
   healthy-but-quiet socket; connect/send/ack/close are all bounded,
   including the cleanup path itself.
7. **Migration 0007's downgrade was unproven against populated,
   multi-build data → fixed.** `downgrade()` now runs a preflight check
   and fails closed with a precise, actionable reason
   (`Downgrade0007IncompatibleDataError`) when incompatible
   multi-build-hash `swaps` data exists, rather than an opaque Postgres
   constraint-violation crash mid-migration; proceeds exactly as before
   otherwise. Proven with 2 new real-Postgres tests against a genuinely
   populated scratch database (one proving the supported path, one
   proving the refusal).
8. **Evidence/state reporting consistency → this checkpoint.**
   `docs/BUILD_STATE.md`'s fixture-coverage blocker and phase-history
   table, `tests/golden/fixtures/real/SEARCH_LOG.md`, and this
   checkpoint's acceptance-matrix section E are cross-checked to state
   the same 9-of-9-with-one-caveat disposition and the same
   490-test/87%-coverage figures. An audit-of-the-audit (checkpoint
   section H) checked for untested branches, skipped tests,
   self-generated expected values, mocks bypassing production wiring,
   stale evidence, changed category definitions, and cross-document
   contradictions before this checkpoint was finalized.

Full per-finding detail, the complete 15-item acceptance-matrix
disposition, and every command actually run:
`orchestration/checkpoints/phase_1_remediation_5.md`.

## Important findings

- Two existing ingestion-manager tests were found, on inspection, to be
  *unknowingly depending on the very WebSocket reconnect-storm defect
  finding #6 fixes* to reach their target state:
  `test_multiple_wallets_remain_isolated_under_concurrent_subscriptions`
  raced two wallets' reconnect cycles against each other and asserted on
  whichever a tight poll loop happened to catch first; the clock-anomaly
  recovery test's `script()` call nested two `ConnectionError`s inside
  one session's items list (the second was dead code -- `raise` inside
  `notifications()`'s for-loop never reaches a second item), and was, in
  practice, reaching its target reconnect count only via the old
  defect's every-timeout-reconnects-a-quiet-socket behavior. Both were
  retimed/rescripted to prove the same properties without relying on the
  defect -- caught during this round's own test-suite work, not left as
  an unaddressed gap.
- All fixture upstream evidence (git tree attestations, license
  evidence, source bytes) was captured via real `git clone
  --filter=blob:none --no-checkout` + `git ls-tree` against the actual
  upstream repositories (this sandbox's confirmed-working `git`/
  `raw.githubusercontent.com` access, unchanged from prior rounds), not
  hand-transcribed -- the round 5 finding #3 fixtures' blob SHAs were
  independently cross-verified against round 4's own recorded values
  and matched exactly for the 9 fixtures carried over.
- Round 2/3/4's own checkpoints and `docs/BUILD_STATE.md` phase-history
  rows are left unmodified as immutable history of what was claimed at
  the time -- matching this project's existing convention for
  superseded rows.
- `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is unchanged -- still the
  orchestrator's `argus-phase-1-remediation-005` instruction,
  `STATUS: ACTIVE`. This task did not and could not self-approve any
  phase; `last_orchestrator_approved_phase` in `docs/BUILD_STATE.md`
  remains `0`, and the Phase 0 `approved_commit` is unchanged.
- All changes stayed strictly within the existing Phase 1 module set
  (`src/argus/{cli.py,config.py,golden_fixtures.py,ingestion,parsing,
  providers}`, `migrations/`, `tests/`, `scripts/`, `docs/BUILD_STATE.md`)
  -- confirmed via `git diff --stat` against the pre-remediation target
  commit. No Phase 1.5 or later-phase code was started.

## Failures or limitations

- **Acceptance-matrix item 1 carries one documented caveat, not full
  unqualified PASS.** The LP-action real-chain fixture's substantive
  match (a real multi-token-account liquidity transaction, correctly
  never a confident single-asset trade) is on a different emitted label
  (`UNKNOWN`, not `LP_ACTION`) than the category name suggests -- see
  checkpoint section E item 1 for the full reasoning. Not claimed as an
  unqualified PASS.
- **Live Helius RPC/WebSocket connectivity: NOT TESTED** (unchanged from
  every prior handoff -- no `HELIUS_API_KEY` configured and no general
  internet egress to chain-data hosts in this sandbox). The new
  `check_liveness()` ping/pong probe is therefore also unexercised
  live; proven against the fake connector's scripted pong/hang/raise
  scenarios instead.
- **`PG17_COMPOSE_VALIDATION` remains `DEFERRED_ENVIRONMENTAL_CHECK`**
  (unchanged, unrelated to this round -- see `docs/BUILD_STATE.md`). The
  new migration 0007 populated-data downgrade tests were verified
  against the same substitute local PostgreSQL 16 server used
  throughout this project.
- Coverage on a small number of modules is low for structural reasons,
  not because the behavior is unverified: `src/argus/ingestion/
  test_mode.py` (0%) and `src/argus/providers/helius/
  websocket_connector.py` (0%) are exercised through the real CLI
  process/adapter tests against a fake connector, never faked as
  "tested". See `orchestration/checkpoints/phase_1_remediation_5.md`
  section C for the full coverage breakdown.

## Deferred checks

- Acceptance-matrix item 1's documented label caveat (see
  `ORCHESTRATOR_REVIEW_REQUIRED` above and checkpoint section E item 1).
- Live Solana RPC/WebSocket connectivity against a real `HELIUS_API_KEY`
  and real network access.
- `PG17_COMPOSE_VALIDATION` (unchanged, unrelated).

## Exact next action requested from orchestrator

Review this remediation round's evidence
(`orchestration/checkpoints/phase_1_remediation_5.md` and
`orchestration/bundles/phase_1_remediation_5.txt`) against the 15-item
mandatory acceptance matrix in instruction
`argus-phase-1-remediation-005`, and resolve the one open question:
whether the LP-action real-chain fixture's substantive match on a
different emitted label (`UNKNOWN`, not `LP_ACTION`) is an acceptable
disposition for that required category, or whether a fixture that
specifically triggers the `LP_ACTION` label must still be sourced. If
accepted, write the next `ACTIVE` instruction into
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md` (`TARGET_COMMIT` pinned to
the exact commit named in this handoff) to authorize the next piece of
work. Phase 1.5 and all later phases remain forbidden until then. Until a
new instruction exists, the watcher (if running) takes no action beyond
logging `NO_ACTIVE_INSTRUCTION`.

**Note on this branch's history:** unchanged from prior handoffs — if you
cloned/fetched this branch before 2026-08-30T22:35 UTC, re-clone or
`git fetch --all && git reset --hard origin/claude/argus-folder-setup-77ahrk`
rather than merging/rebasing the old (pre-rewrite) history.
