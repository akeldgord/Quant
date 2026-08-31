# ARGUS Agent Handoff

**OWNER: IMPLEMENTATION AGENT.** Updated every time work is handed back to
the orchestrator. Treat this as the agent's current status message — an
index into the full checkpoint/bundle, not a replacement for either. See
`orchestration/PROTOCOL.md` section 5 for the contract this file implements.

---

HANDOFF_ID: handoff-0010-phase-1-remediation-3
UTC_TIMESTAMP: 2026-08-31T12:15:00Z
CURRENT_COMMIT: 81dd46cbfa3a46dd97c2f59a92ec62a42ab4fda9
CURRENT_PHASE: 1
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: argus-phase-1-remediation-003
CHECKPOINT_PATH: orchestration/checkpoints/phase_1_remediation_3.md
BUNDLE_PATH: orchestration/bundles/phase_1_remediation_3.txt
TEST_STATUS: unit 302/302 passed; integration 36/36 passed (real PostgreSQL 16, incl. 6/6 new migration tests); golden 23/23 passed; replay 10/10 passed (was 8 before this round's own pruned-boundary and reparse-identity coverage); full suite 371/371 passed, 86% coverage; ruff clean; mypy clean; alembic downgrade-to-base/upgrade-to-head clean through migration 0006
WORKING_TREE: clean (verified via `git status --porcelain` before this commit)
ORCHESTRATOR_REVIEW_REQUIRED: acceptance criterion 1 (authenticated real-chain golden fixtures) is honestly PARTIAL — 7 of 9 round-1-required categories now have genuine real-chain fixtures (up from 4 of 9 after round 2; see orchestration/checkpoints/phase_1_remediation_3.md section E item 1 and tests/golden/fixtures/real/SEARCH_LOG.md), the remaining 2 (multiple token-account/LP-style action; a genuinely failed transaction) are honestly NOT TESTED since no repository checked across either round embeds either; resolving the remainder requires either an environment with real RPC egress to capture one directly, or a not-yet-checked repository that happens to embed either. PG17_COMPOSE_VALIDATION (deferred, unrelated, unchanged) still open — see docs/BUILD_STATE.md.

## Work completed

Executed orchestrator instruction `argus-phase-1-remediation-003` in
full: an independent audit rejected round 2's remediation as still
insufficient, citing 6 concrete findings. All 6 are remediated with
real, tested code:

1. **Pagination accepted an unverified persisted boundary → fixed.**
   `ReconciliationEngine._fetch_all_pages()` no longer relies on the
   provider's `until` truncation as proof a persisted boundary was
   reached — it now walks purely via `before_signature` and requires
   directly observing and matching the exact boundary signature in the
   provider's own address-history sequence. An empty/short page reached
   without that match is a new, distinct DEGRADED failure with an
   operator-visible reason; the watermark never advances across it. 6
   new adversarial unit tests plus a real-Postgres replay test across
   two independent process restarts.
2. **Helius result-contract failures could be recorded as OK usage →
   fixed.** Every method's nested contract validation now runs inside
   the same accounted operation `send_with_usage()` decides the terminal
   outcome from, not after it returns. Audited DexScreener/GeckoTerminal/
   Jupiter for the same pattern — all three already compliant. Added
   malformed-nested-result tests for every Helius method (`get_token_accounts`
   previously had no test coverage at all).
3. **Streaming usage-recorder failures disappeared silently → fixed.**
   Replaced `contextlib.suppress(Exception)` with the same structured
   `usage_recorder_failed` warning pattern round 2's finding #8
   established for the HTTP path — safe metadata only, never masking the
   real stream outcome or control flow.
4. **Parse-attempt evidence omitted required build/config/git identity →
   fixed.** New migration 0006 adds four NOT NULL, CHECK-constrained
   columns (`build_hash`, `config_hash`, `master_spec_hash`,
   `git_commit`) to `parse_attempts`; pre-existing round-2 rows backfill
   an explicit sentinel, never a fabricated value. New
   `argus.config.git_commit_sha()` and
   `argus.parsing.generic_parser.PARSER_BUILD_HASH` (a content hash of
   the parser module itself, distinct from the human-assigned
   `PARSER_VERSION` label); `ReconciliationEngine` now requires an
   explicit `parse_identity` argument. A new
   `tests/integration/test_migrations.py` (6 tests) proves
   migration-from-zero, upgrade-from-0003-through-head,
   upgrade-from-0005 backfill correctness, downgrade, idempotency, and
   restart-safety against a disposable scratch database.
5. **Finalization provider failure silently converted to zero
   promotions → fixed.** `sweep_finalization()` now returns a typed
   `FinalizationSweepResult(ok, promoted, reason)` instead of a bare
   `int` — a provider exception, a malformed/mismatched-cardinality
   response, or a per-event append failure are all now distinguishable
   from a genuine zero-result sweep. The manager's own background loop
   logs a visible `finalization_sweep_failed` warning on any `ok=False`
   result.
6. **Real-chain golden evidence still required → PARTIAL, real
   progress.** Searched DEX/AMM program repositories (Raydium,
   Orca/Whirlpools, Phoenix, OpenBook, Meteora) and several
   general-purpose Solana transaction-parser repositories. Every DEX/AMM
   program repository tests exclusively against synthetic local-validator
   state; `0xjeffro/tx-parser` (MPL-2.0) does embed 26 real captured
   `getTransaction` fixtures. Imported 6 more real fixtures, covering 5
   more required categories (SOL-to-token, token-to-SOL, token-to-USDC,
   multi-hop, partial-sell swaps) plus an ambiguous multi-asset
   transaction — 7 of 9 required categories now real-chain evidenced,
   up from 4 of 9. The remaining 2 (multiple token-account/LP-style
   action; a genuinely failed transaction) are honestly NOT TESTED — see
   `tests/golden/fixtures/real/SEARCH_LOG.md`.

Full per-finding detail, the complete 18-item disposition, and every
command actually run: `orchestration/checkpoints/phase_1_remediation_3.md`.

## Important findings

- No genuine production bugs required a follow-up fix during this
  round's own review (unlike round 2, which found four) — every
  finding's implementation passed its own adversarial test suite and the
  full regression suite. One test-authoring mistake was caught and
  corrected *during* development of finding #6's test suite (a scripted
  fake-provider transaction ordering tripped finding #2's own
  pagination-ordering-fault detector before the intended scenario ran),
  fixed before that commit was made — not a production defect.
- `0xjeffro/tx-parser`'s fixture files are each a JSON array wrapping one
  captured transaction (`[{...}]`), not the bare object
  `argus fixtures import-real-chain` expects — the upstream repository's
  own Go test-fixture-loading convention. Each was mechanically unwrapped
  before import; this changes zero bytes of the actual captured
  transaction and is recorded verbatim in each fixture's
  `--upstream-path` note.
- Two `0xjeffro/tx-parser` candidates were evaluated and rejected for the
  "ambiguous multi-asset" category before the one actually imported was
  chosen, specifically because the real parser resolved them confidently
  rather than exhibiting genuine ambiguity — see
  `tests/golden/fixtures/real/SEARCH_LOG.md` for exactly which and why.
  The fixture that was imported is documented transparently: the real
  parser classifies it `TRANSFER_IN` at confidence 1.000, not `UNKNOWN`
  — the transaction is honestly multi-asset in structure, but the
  parser's actual output is recorded as-is, not implied to be ambiguous
  itself.
- `orchestration/ORCHESTRATOR_INSTRUCTIONS.md` is unchanged — still the
  orchestrator's `argus-phase-1-remediation-003` instruction,
  `STATUS: ACTIVE`. This task did not and could not self-approve any
  phase; `last_orchestrator_approved_phase` in `docs/BUILD_STATE.md`
  remains `0`, and the Phase 0 `approved_commit` is unchanged.
- All changes stayed strictly within the existing Phase 1 module set
  (`src/argus/{cli.py,config.py,domain,ingestion,parsing,providers}`,
  `migrations/`, `tests/`) — confirmed via `git diff --stat` against the
  pre-remediation target commit. No Phase 1.5 or later-phase code was
  started.

## Failures or limitations

- **Acceptance criterion 1 (authenticated real-chain golden fixtures):
  PARTIAL — 7 of 9 required categories.** Real progress this round (up
  from 4 of 9 after round 2), but not complete: "multiple token-account/
  LP-style action" and a genuinely failed on-chain transaction were not
  found in any repository checked across rounds 2 or 3. See
  `tests/golden/fixtures/real/SEARCH_LOG.md` for the full search log,
  including every repository checked and why it was or wasn't usable.
  This is not claimed as full PASS.
- **Live Helius RPC/WebSocket connectivity: NOT TESTED** (unchanged from
  every prior handoff — no `HELIUS_API_KEY` configured and no general
  internet egress to chain-data hosts in this sandbox).
- **`PG17_COMPOSE_VALIDATION` remains `DEFERRED_ENVIRONMENTAL_CHECK`**
  (unchanged, unrelated to this round — see `docs/BUILD_STATE.md`).
- Coverage on a small number of modules is low for structural reasons,
  not because the behavior is unverified: `src/argus/cli.py` (33%),
  `src/argus/ingestion/test_mode.py` (0%), and
  `src/argus/providers/helius/websocket_connector.py` (0%) are all
  exercised through the real CLI process, never faked as "tested". See
  `orchestration/checkpoints/phase_1_remediation_3.md` section C for the
  full coverage breakdown.

## Deferred checks

- Acceptance criterion 1 — the 2 remaining real-chain fixture categories
  (see `ORCHESTRATOR_REVIEW_REQUIRED` above and checkpoint section E
  item 1).
- Live Solana RPC/WebSocket connectivity against a real `HELIUS_API_KEY`
  and real network access.
- `PG17_COMPOSE_VALIDATION` (unchanged, unrelated).

## Exact next action requested from orchestrator

Review this remediation round's evidence
(`orchestration/checkpoints/phase_1_remediation_3.md` and
`orchestration/bundles/phase_1_remediation_3.txt`) against the 18
mandatory acceptance criteria in instruction
`argus-phase-1-remediation-003`, and resolve the one open question:
whether the current real-chain fixture coverage (7 of 9 required
categories, all genuinely real and provenance-complete) is an acceptable
disposition for criterion 1 to proceed on, or whether the remaining 2
categories must be sourced (from an environment with real RPC egress, or
a not-yet-checked repository) before Phase 1 may be approved. If
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
